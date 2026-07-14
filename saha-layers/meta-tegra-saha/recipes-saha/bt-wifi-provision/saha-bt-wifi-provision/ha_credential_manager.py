#!/usr/bin/env python3
"""Read, validate, and refresh board-owned Home Assistant credentials."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CREDENTIAL_PATH = Path("/var/lib/saha/homeassistant/app-credentials.json")
TOKEN_URL = "http://127.0.0.1:8123/auth/token"
MAX_PAYLOAD_BYTES = 16 * 1024
REFRESH_SKEW_MS = 5 * 60 * 1000
_LOCK = threading.RLock()


class HaCredentialError(RuntimeError):
    """Raised when board credentials cannot be safely returned."""


def _validate(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or value.get("tokenType") != "Bearer"
    ):
        raise HaCredentialError("HA credentials unavailable")
    required_strings = (
        "baseUrl",
        "clientId",
        "accessToken",
        "refreshToken",
        "ownerUsername",
        "ownerPassword",
        "updatedAt",
    )
    for key in required_strings:
        if not isinstance(value.get(key), str) or not value[key]:
            raise HaCredentialError("HA credentials unavailable")
    expires_at = value.get("expiresAt")
    if not isinstance(expires_at, (int, float)) or expires_at <= 0:
        raise HaCredentialError("HA credentials unavailable")
    return value


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _write(value: dict[str, Any]) -> None:
    parent = CREDENTIAL_PATH.parent
    os.chmod(parent, 0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=".app-credentials.", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, CREDENTIAL_PATH)
        _fsync_directory(parent)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _refresh(value: dict[str, Any]) -> dict[str, Any]:
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": value["refreshToken"],
            "client_id": value["clientId"],
        }
    ).encode()
    request_value = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request_value, timeout=10) as response:
            token = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HaCredentialError("HA credential refresh unavailable") from exc

    if (
        not isinstance(token, dict)
        or not isinstance(token.get("access_token"), str)
        or not isinstance(token.get("expires_in"), (int, float))
        or token["expires_in"] <= 0
    ):
        raise HaCredentialError("HA credential refresh unavailable")

    updated = {
        **value,
        "accessToken": token["access_token"],
        "refreshToken": token.get("refresh_token") or value["refreshToken"],
        "expiresAt": int(time.time() * 1000 + token["expires_in"] * 1000),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write(updated)
    return updated


def get_credential_payload() -> bytes:
    with _LOCK:
        try:
            value = _validate(
                json.loads(CREDENTIAL_PATH.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise HaCredentialError("HA credentials unavailable") from exc
        os.chmod(CREDENTIAL_PATH, 0o600)

        if value["expiresAt"] <= int(time.time() * 1000) + REFRESH_SKEW_MS:
            value = _refresh(value)

        payload = json.dumps(
            value,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise HaCredentialError("HA credentials unavailable")
        return payload
