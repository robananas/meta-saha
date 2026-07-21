#!/usr/bin/env python3
"""Roban BLE Secure Protocol v2 framing, handshake, and record layer."""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"R2"
VERSION = 2
KIND_CLIENT_HELLO = 1
KIND_SERVER_HELLO = 2
KIND_ENCRYPTED = 3
TRANSPORT_HEADER = struct.Struct(">2sBBHBBH")
TRANSPORT_HEADER_SIZE = TRANSPORT_HEADER.size
MAX_FRAGMENT_COUNT = 255
MAX_MESSAGE_BYTES = 16 * 1024
MAX_FRAGMENT_BODY = 509
DEFAULT_REASSEMBLY_TIMEOUT = 10.0
MAX_INFLIGHT_MESSAGES = 8

CLIENT_HELLO_PREFIX = struct.Struct(">BB32s32s32s")
SERVER_HELLO_PREFIX = struct.Struct(">BBQ32s32s32s")
SIGNATURE_BYTES = 64
CLIENT_HELLO_SIZE = CLIENT_HELLO_PREFIX.size + SIGNATURE_BYTES
SERVER_HELLO_SIZE = SERVER_HELLO_PREFIX.size + SIGNATURE_BYTES

DIRECTION_CLIENT_TO_SERVER = 0
DIRECTION_SERVER_TO_CLIENT = 1
INNER_HEADER = struct.Struct(">QBIHI")
INNER_HEADER_SIZE = INNER_HEADER.size
AEAD_TAG_BYTES = 16
MSG_FINISHED = 1
MSG_REQUEST = 16
MSG_RESPONSE = 17
MSG_ERROR = 18
MSG_PROGRESS = 19
FINISHED_PAYLOAD = b"finished-v2"
HKDF_INFO = b"Roban BLE Secure Protocol v2"


class ProtocolError(ValueError):
    """An unauthenticated or malformed protocol input was rejected."""


class ReplayError(ProtocolError):
    """A record sequence was duplicated or arrived out of order."""


@dataclass(frozen=True)
class TransportMetadata:
    kind: int
    message_id: int
    count: int
    total: int

    def aad(self) -> bytes:
        return struct.pack(">2sBBHBH", MAGIC, VERSION, self.kind, self.message_id, self.count, self.total)


@dataclass
class _Assembly:
    metadata: TransportMetadata
    created: float
    fragments: dict[int, bytes] = field(default_factory=dict)


class Reassembler:
    def __init__(
        self,
        *,
        timeout: float = DEFAULT_REASSEMBLY_TIMEOUT,
        max_message_bytes: int = MAX_MESSAGE_BYTES,
        max_inflight: int = MAX_INFLIGHT_MESSAGES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout = timeout
        self.max_message_bytes = max_message_bytes
        self.max_inflight = max_inflight
        self.clock = clock
        self._messages: dict[tuple[int, int], _Assembly] = {}

    def expire(self) -> None:
        now = self.clock()
        self._messages = {
            key: value for key, value in self._messages.items() if now - value.created <= self.timeout
        }

    def clear(self) -> None:
        self._messages.clear()

    def feed(self, fragment: bytes) -> tuple[TransportMetadata, bytes] | None:
        self.expire()
        if len(fragment) < TRANSPORT_HEADER_SIZE:
            raise ProtocolError("transport fragment is shorter than header")
        magic, version, kind, message_id, index, count, total = TRANSPORT_HEADER.unpack_from(fragment)
        body = fragment[TRANSPORT_HEADER_SIZE:]
        if magic != MAGIC or version != VERSION:
            raise ProtocolError("unsupported transport magic or version")
        if kind not in (KIND_CLIENT_HELLO, KIND_SERVER_HELLO, KIND_ENCRYPTED):
            raise ProtocolError("unsupported transport kind")
        if count < 1 or count > MAX_FRAGMENT_COUNT or index >= count:
            raise ProtocolError("invalid fragment index/count")
        if total < 1 or total > self.max_message_bytes:
            raise ProtocolError("invalid reassembled length")
        if not body or len(body) > MAX_FRAGMENT_BODY or len(body) > total:
            raise ProtocolError("invalid fragment body length")
        metadata = TransportMetadata(kind, message_id, count, total)
        key = (kind, message_id)
        assembly = self._messages.get(key)
        if assembly is None:
            if len(self._messages) >= self.max_inflight:
                raise ProtocolError("too many incomplete messages")
            assembly = _Assembly(metadata, self.clock())
            self._messages[key] = assembly
        elif assembly.metadata != metadata:
            del self._messages[key]
            raise ProtocolError("fragment metadata changed mid-message")
        prior = assembly.fragments.get(index)
        if prior is not None and prior != body:
            del self._messages[key]
            raise ProtocolError("conflicting duplicate fragment")
        assembly.fragments[index] = body
        received = sum(len(value) for value in assembly.fragments.values())
        if received > total:
            del self._messages[key]
            raise ProtocolError("fragment bodies exceed declared total")
        if len(assembly.fragments) != count:
            return None
        payload = b"".join(assembly.fragments[i] for i in range(count))
        del self._messages[key]
        if len(payload) != total:
            raise ProtocolError("reassembled length does not match total")
        return metadata, payload


def fragment_message(kind: int, message_id: int, payload: bytes, att_payload_bytes: int) -> list[bytes]:
    body_size = min(MAX_FRAGMENT_BODY, att_payload_bytes - TRANSPORT_HEADER_SIZE)
    if body_size < 1:
        raise ProtocolError("ATT payload cannot contain transport body")
    if not payload or len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError("invalid message length")
    count = (len(payload) + body_size - 1) // body_size
    if count > MAX_FRAGMENT_COUNT:
        raise ProtocolError("message requires too many fragments")
    return [
        TRANSPORT_HEADER.pack(MAGIC, VERSION, kind, message_id, index, count, len(payload))
        + payload[index * body_size:(index + 1) * body_size]
        for index in range(count)
    ]


def _x25519_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _client_sig_input(key_id: bytes, ephemeral: bytes, nonce: bytes) -> bytes:
    return b"R2-ClientHello" + bytes((VERSION, 0)) + key_id + ephemeral + nonce


def _server_sig_input(client_hello: bytes, session_id: int, key_id: bytes, ephemeral: bytes, nonce: bytes) -> bytes:
    return b"R2-ServerHello" + client_hello + struct.pack(">Q", session_id) + key_id + ephemeral + nonce


def encode_client_hello(identity: Ed25519PrivateKey, ephemeral: X25519PrivateKey, nonce: bytes) -> bytes:
    if len(nonce) != 32:
        raise ProtocolError("client nonce must be 32 bytes")
    public = identity.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    eph = _x25519_public(ephemeral)
    prefix = CLIENT_HELLO_PREFIX.pack(VERSION, 0, public, eph, nonce)
    return prefix + identity.sign(_client_sig_input(public, eph, nonce))


@dataclass(frozen=True)
class Record:
    session_id: int
    direction: int
    sequence: int
    message_type: int
    request_id: int
    payload: bytes


class SecureChannel:
    def __init__(self, session_id: int, client_to_server: bytes, server_to_client: bytes) -> None:
        self.session_id = session_id
        self._rx = ChaCha20Poly1305(client_to_server)
        self._tx = ChaCha20Poly1305(server_to_client)
        self.rx_sequence = 0
        self.tx_sequence = 0

    @staticmethod
    def _nonce(session_id: int, direction: int, sequence: int) -> bytes:
        return struct.pack(">Q", session_id)[:7] + bytes((direction,)) + struct.pack(">I", sequence)

    def encrypt(self, message_type: int, request_id: int, payload: bytes, metadata: TransportMetadata) -> bytes:
        sequence = self.tx_sequence
        plain = INNER_HEADER.pack(
            self.session_id, DIRECTION_SERVER_TO_CLIENT, sequence, message_type, request_id
        ) + payload
        ciphertext = self._tx.encrypt(
            self._nonce(self.session_id, DIRECTION_SERVER_TO_CLIENT, sequence), plain, metadata.aad()
        )
        self.tx_sequence += 1
        return ciphertext

    def decrypt(self, ciphertext: bytes, metadata: TransportMetadata) -> Record:
        if len(ciphertext) < INNER_HEADER_SIZE + AEAD_TAG_BYTES:
            raise ProtocolError("encrypted message is too short")
        sequence = self.rx_sequence
        try:
            plain = self._rx.decrypt(
                self._nonce(self.session_id, DIRECTION_CLIENT_TO_SERVER, sequence),
                ciphertext,
                metadata.aad(),
            )
        except InvalidTag as exc:
            raise ProtocolError("record authentication failed") from exc
        session_id, direction, actual_sequence, message_type, request_id = INNER_HEADER.unpack_from(plain)
        if session_id != self.session_id or direction != DIRECTION_CLIENT_TO_SERVER:
            raise ProtocolError("record session or direction mismatch")
        if actual_sequence != sequence:
            raise ReplayError("record sequence mismatch")
        self.rx_sequence += 1
        return Record(session_id, direction, actual_sequence, message_type, request_id, plain[INNER_HEADER_SIZE:])


class ServerHandshake:
    def __init__(
        self,
        device_identity: Ed25519PrivateKey,
        app_keyring: Mapping[bytes, Ed25519PublicKey],
        *,
        random_bytes: Callable[[int], bytes] = os.urandom,
    ) -> None:
        self.device_identity = device_identity
        self.app_keyring = app_keyring
        self.random_bytes = random_bytes

    def accept(self, client_hello: bytes) -> tuple[bytes, SecureChannel]:
        if len(client_hello) != CLIENT_HELLO_SIZE:
            raise ProtocolError("ClientHello has invalid fixed length")
        version, flags, key_id, client_eph_raw, client_nonce = CLIENT_HELLO_PREFIX.unpack_from(client_hello)
        signature = client_hello[CLIENT_HELLO_PREFIX.size:]
        if version != VERSION or flags != 0:
            raise ProtocolError("unsupported ClientHello version or flags")
        app_key = self.app_keyring.get(key_id)
        if app_key is None:
            raise ProtocolError("untrusted application identity")
        try:
            app_key.verify(signature, _client_sig_input(key_id, client_eph_raw, client_nonce))
        except InvalidSignature as exc:
            raise ProtocolError("invalid ClientHello signature") from exc
        try:
            client_ephemeral = X25519PublicKey.from_public_bytes(client_eph_raw)
        except ValueError as exc:
            raise ProtocolError("invalid client ephemeral key") from exc
        server_ephemeral = X25519PrivateKey.generate()
        server_eph_raw = _x25519_public(server_ephemeral)
        server_nonce = self.random_bytes(32)
        session_id = int.from_bytes(self.random_bytes(8), "big") or 1
        device_key_id = self.device_identity.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        prefix = SERVER_HELLO_PREFIX.pack(
            VERSION, 0, session_id, device_key_id, server_eph_raw, server_nonce
        )
        signature = self.device_identity.sign(
            _server_sig_input(client_hello, session_id, device_key_id, server_eph_raw, server_nonce)
        )
        shared = server_ephemeral.exchange(client_ephemeral)
        material = HKDF(
            algorithm=hashes.SHA256(), length=64, salt=client_nonce + server_nonce, info=HKDF_INFO
        ).derive(shared)
        return prefix + signature, SecureChannel(session_id, material[:32], material[32:])
