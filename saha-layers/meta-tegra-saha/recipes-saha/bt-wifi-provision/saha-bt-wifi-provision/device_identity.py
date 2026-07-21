#!/usr/bin/env python3
"""Load Roban device identity and trusted application public keys."""

from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path
from typing import Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

IDENTITY_FILE_ENV = "ROBAN_DEVICE_IDENTITY_FILE"
APP_KEYRING_JSON_ENV = "ROBAN_APP_KEYRING_JSON"
APP_KEYRING_FILE_ENV = "ROBAN_APP_KEYRING_FILE"
DEV_IDENTITY_FILE_ENV = "ROBAN_DEV_IDENTITY_FILE"
ALLOW_DEV_KEYS_ENV = "ROBAN_ALLOW_DEV_KEYS"


class IdentityError(RuntimeError):
    """Identity material is absent, malformed, or unsafe."""


def _decode_key(value: str) -> bytes:
    value = value.strip()
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        try:
            raw = base64.b64decode(value, validate=True)
        except ValueError as exc:
            raise IdentityError("key must be 32-byte hex or base64") from exc
    if len(raw) != 32:
        raise IdentityError("key must decode to exactly 32 bytes")
    return raw


def _read_root_only(path: Path, *, permit_non_root: bool = False) -> bytes:
    try:
        info = path.stat()
    except OSError as exc:
        raise IdentityError(f"cannot stat identity file {path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise IdentityError("identity path is not a regular file")
    if not permit_non_root and info.st_uid != 0:
        raise IdentityError("production identity file must be owned by root")
    if info.st_mode & 0o077:
        raise IdentityError("identity file must not grant group/other permissions")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise IdentityError(f"cannot read identity file {path}: {exc}") from exc


def load_device_identity(environ: Mapping[str, str] | None = None) -> Ed25519PrivateKey:
    env = os.environ if environ is None else environ
    path_text = env.get(IDENTITY_FILE_ENV, "").strip()
    permit_non_root = False
    if not path_text and env.get(ALLOW_DEV_KEYS_ENV) == "1":
        path_text = env.get(DEV_IDENTITY_FILE_ENV, "").strip()
        permit_non_root = True
    if not path_text:
        raise IdentityError(f"{IDENTITY_FILE_ENV} is required")
    data = _read_root_only(Path(path_text), permit_non_root=permit_non_root).strip()
    if data.startswith(b"-----BEGIN"):
        try:
            key = serialization.load_pem_private_key(data, password=None)
        except (TypeError, ValueError) as exc:
            raise IdentityError("invalid PEM device identity") from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise IdentityError("device identity is not Ed25519")
        return key
    try:
        return Ed25519PrivateKey.from_private_bytes(_decode_key(data.decode("ascii")))
    except UnicodeDecodeError as exc:
        raise IdentityError("raw identity must use hex or base64 text") from exc


def load_app_keyring(environ: Mapping[str, str] | None = None) -> dict[bytes, Ed25519PublicKey]:
    env = os.environ if environ is None else environ
    inline = env.get(APP_KEYRING_JSON_ENV, "").strip()
    filename = env.get(APP_KEYRING_FILE_ENV, "").strip()
    if bool(inline) == bool(filename):
        raise IdentityError(f"set exactly one of {APP_KEYRING_JSON_ENV} or {APP_KEYRING_FILE_ENV}")
    try:
        document = json.loads(inline if inline else Path(filename).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityError("cannot load application keyring JSON") from exc
    if not isinstance(document, dict) or not document:
        raise IdentityError("application keyring must be a non-empty JSON object")
    if "keys" in document:
        version = document.get("version")
        minimum = document.get("minimum_accepted_version")
        keys = document.get("keys")
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or version < minimum
            or not isinstance(keys, dict)
            or not keys
        ):
            raise IdentityError("invalid versioned application keyring manifest")
        document = keys
    result: dict[bytes, Ed25519PublicKey] = {}
    for key_id, public_value in document.items():
        if not isinstance(key_id, str) or not isinstance(public_value, str):
            raise IdentityError("keyring ids and values must be strings")
        key_id_bytes = _decode_key(key_id)
        public_bytes = _decode_key(public_value)
        result[key_id_bytes] = Ed25519PublicKey.from_public_bytes(public_bytes)
    return result


def public_key_bytes(key: Ed25519PrivateKey | Ed25519PublicKey) -> bytes:
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
