#!/usr/bin/env python3

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from device_identity import (
    IdentityError,
    load_app_keyring,
    load_device_identity,
    public_key_bytes,
)
from secure_protocol import (
    CLIENT_HELLO_PREFIX,
    DIRECTION_CLIENT_TO_SERVER,
    FINISHED_PAYLOAD,
    HKDF_INFO,
    INNER_HEADER,
    KIND_CLIENT_HELLO,
    KIND_ENCRYPTED,
    KIND_SERVER_HELLO,
    MSG_FINISHED,
    ProtocolError,
    Reassembler,
    SERVER_HELLO_PREFIX,
    ServerHandshake,
    TransportMetadata,
    encode_client_hello,
    fragment_message,
)


class SecureProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = Ed25519PrivateKey.generate()
        self.device = Ed25519PrivateKey.generate()
        self.client_ephemeral = X25519PrivateKey.generate()
        self.client_nonce = bytes(range(32))
        self.client_hello = encode_client_hello(self.app, self.client_ephemeral, self.client_nonce)

    def test_att_mtu_23_reassembles_fixed_client_hello(self) -> None:
        fragments = fragment_message(KIND_CLIENT_HELLO, 7, self.client_hello, 20)
        self.assertGreater(len(fragments), 1)
        reassembler = Reassembler()
        result = None
        for fragment in reversed(fragments):
            result = reassembler.feed(fragment) or result
        self.assertIsNotNone(result)
        metadata, payload = result
        self.assertEqual(payload, self.client_hello)
        self.assertEqual(metadata.total, len(self.client_hello))

    def test_conflicting_duplicate_and_changed_metadata_are_rejected(self) -> None:
        fragments = fragment_message(KIND_CLIENT_HELLO, 8, self.client_hello, 20)
        reassembler = Reassembler()
        self.assertIsNone(reassembler.feed(fragments[0]))
        changed = bytearray(fragments[0])
        changed[-1] ^= 1
        with self.assertRaises(ProtocolError):
            reassembler.feed(bytes(changed))

    def test_handshake_and_finished_are_single_aead_over_reassembled_ciphertext(self) -> None:
        app_public = self.app.public_key()
        server_hello, channel = ServerHandshake(
            self.device, {public_key_bytes(app_public): app_public}, random_bytes=os.urandom
        ).accept(self.client_hello)
        version, flags, session_id, device_id, server_eph, server_nonce = SERVER_HELLO_PREFIX.unpack_from(
            server_hello
        )
        self.assertEqual((version, flags, device_id), (2, 0, public_key_bytes(self.device)))
        shared = self.client_ephemeral.exchange(X25519PublicKey.from_public_bytes(server_eph))
        keys = HKDF(
            algorithm=hashes.SHA256(), length=64, salt=self.client_nonce + server_nonce, info=HKDF_INFO
        ).derive(shared)
        metadata = TransportMetadata(KIND_ENCRYPTED, 9, 2, INNER_HEADER.size + len(FINISHED_PAYLOAD) + 16)
        plain = INNER_HEADER.pack(
            session_id, DIRECTION_CLIENT_TO_SERVER, 0, MSG_FINISHED, 0
        ) + FINISHED_PAYLOAD
        nonce = struct.pack(">Q", session_id)[:7] + bytes((DIRECTION_CLIENT_TO_SERVER,)) + struct.pack(">I", 0)
        ciphertext = ChaCha20Poly1305(keys[:32]).encrypt(nonce, plain, metadata.aad())
        record = channel.decrypt(ciphertext, metadata)
        self.assertEqual(record.payload, FINISHED_PAYLOAD)
        with self.assertRaises(ProtocolError):
            channel.decrypt(ciphertext, metadata)

    def test_aad_binds_transport_metadata(self) -> None:
        app_public = self.app.public_key()
        _, channel = ServerHandshake(self.device, {public_key_bytes(app_public): app_public}).accept(
            self.client_hello
        )
        bogus = b"x" * (INNER_HEADER.size + 16)
        with self.assertRaises(ProtocolError):
            channel.decrypt(bogus, TransportMetadata(KIND_ENCRYPTED, 1, 1, len(bogus)))

    def test_untrusted_or_modified_client_hello_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            ServerHandshake(self.device, {}).accept(self.client_hello)
        modified = bytearray(self.client_hello)
        modified[-1] ^= 1
        with self.assertRaises(ProtocolError):
            ServerHandshake(
                self.device, {public_key_bytes(self.app): self.app.public_key()}
            ).accept(bytes(modified))

    def test_versioned_keyring_manifest_supports_rotation_without_wire_change(self) -> None:
        public = public_key_bytes(self.app).hex()
        keyring = load_app_keyring(
            {
                "ROBAN_APP_KEYRING_JSON": (
                    '{"version":3,"minimum_accepted_version":2,"keys":{"'
                    + public
                    + '":"'
                    + public
                    + '"}}'
                )
            }
        )
        self.assertIn(bytes.fromhex(public), keyring)
        with self.assertRaises(IdentityError):
            load_app_keyring(
                {
                    "ROBAN_APP_KEYRING_JSON": (
                        '{"version":1,"minimum_accepted_version":2,"keys":{"'
                        + public
                        + '":"'
                        + public
                        + '"}}'
                    )
                }
            )

    def test_identity_dev_path_requires_explicit_switch_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity"
            raw = self.device.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
            path.write_text(raw.hex(), encoding="ascii")
            path.chmod(0o600)
            with self.assertRaises(IdentityError):
                load_device_identity({"ROBAN_DEV_IDENTITY_FILE": str(path)})
            loaded = load_device_identity(
                {"ROBAN_ALLOW_DEV_KEYS": "1", "ROBAN_DEV_IDENTITY_FILE": str(path)}
            )
            self.assertEqual(public_key_bytes(loaded), public_key_bytes(self.device))
            path.chmod(0o644)
            with self.assertRaises(IdentityError):
                load_device_identity(
                    {"ROBAN_ALLOW_DEV_KEYS": "1", "ROBAN_DEV_IDENTITY_FILE": str(path)}
                )


if __name__ == "__main__":
    unittest.main()
