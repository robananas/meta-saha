#!/usr/bin/env python3
"""Idempotently bootstrap Home Assistant and persist board-owned credentials."""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = "http://127.0.0.1:8123"
CLIENT_ID = "http://localhost:8123/"
STATE_DIR = Path("/var/lib/saha/homeassistant")
CREDENTIAL_PATH = STATE_DIR / "app-credentials.json"
PENDING_PATH = STATE_DIR / "bootstrap-pending.json"
WAIT_SECONDS = 300
REFRESH_SKEW_MS = 5 * 60 * 1000
LOG = logging.getLogger("saha-homeassistant-bootstrap")


class BootstrapError(RuntimeError):
    """Raised for recoverable bootstrap failures without secret details."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def request(
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    token: str | None = None,
    content_type: str = "application/json",
) -> Any:
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = "Bearer " + token
    request_value = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request_value, timeout=10) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        # OAuth/login error bodies can reflect submitted fields, so never include them.
        raise BootstrapError(
            f"{path} failed with HTTP {exc.code}", status_code=exc.code
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BootstrapError(
            f"{path} request failed: {exc.__class__.__name__}"
        ) from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"{path} returned invalid JSON") from exc


def post_json(
    path: str,
    payload: dict[str, Any],
    token: str | None = None,
) -> Any:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return request(path, method="POST", body=body, token=token)


def get_onboarding() -> list[dict[str, Any]]:
    try:
        value = request("/api/onboarding")
    except BootstrapError as exc:
        if exc.status_code == 404:
            return [
                {"step": "user", "done": True},
                {"step": "core_config", "done": True},
                {"step": "analytics", "done": True},
                {"step": "integration", "done": True},
            ]
        raise
    if not isinstance(value, list):
        raise BootstrapError("onboarding status is not a list")
    return [item for item in value if isinstance(item, dict)]


def exchange(fields: dict[str, str], client_id: str = CLIENT_ID) -> dict[str, Any]:
    form = urllib.parse.urlencode({**fields, "client_id": client_id}).encode()
    value = request(
        "/auth/token",
        method="POST",
        body=form,
        content_type="application/x-www-form-urlencoded",
    )
    if not isinstance(value, dict) or not isinstance(value.get("access_token"), str):
        raise BootstrapError("token endpoint response is invalid")
    return value


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE_DIR, 0o700)


def fsync_state_dir() -> None:
    directory_fd = os.open(STATE_DIR, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    ensure_state_dir()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=STATE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
        fsync_state_dir()
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def remove_pending() -> None:
    try:
        PENDING_PATH.unlink()
    except FileNotFoundError:
        return
    fsync_state_dir()


def read_json_file(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"{label} cannot be read or parsed") from exc


def validate_credentials(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or value.get("tokenType") != "Bearer"
    ):
        raise BootstrapError("credential file schema is invalid")
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
            raise BootstrapError(f"credential file field {key} is invalid")
    expires_at = value.get("expiresAt")
    if not isinstance(expires_at, (int, float)) or expires_at <= 0:
        raise BootstrapError("credential file expiresAt is invalid")
    return value


def validate_pending(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != 1:
        raise BootstrapError("pending bootstrap file schema is invalid")
    for key in ("ownerUsername", "ownerPassword", "clientId", "createdAt"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise BootstrapError(f"pending bootstrap field {key} is invalid")
    if value["clientId"] != CLIENT_ID:
        raise BootstrapError("pending bootstrap clientId is invalid")
    return value


def load_pending() -> dict[str, Any] | None:
    if not PENDING_PATH.exists():
        return None
    os.chmod(PENDING_PATH, 0o600)
    return validate_pending(read_json_file(PENDING_PATH, "pending bootstrap file"))


def create_pending() -> dict[str, Any]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_"
    pending = {
        "version": 1,
        "ownerUsername": "roban_owner_" + secrets.token_hex(6),
        "ownerPassword": "".join(secrets.choice(alphabet) for _ in range(40)),
        "clientId": CLIENT_ID,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    atomic_write_json(PENDING_PATH, pending)
    return pending


def credentials_from_token(
    token: dict[str, Any],
    pending: dict[str, Any],
) -> dict[str, Any]:
    refresh_token = token.get("refresh_token")
    expires_in = token.get("expires_in")
    if (
        not isinstance(refresh_token, str)
        or not refresh_token
        or not isinstance(expires_in, (int, float))
        or expires_in <= 0
    ):
        raise BootstrapError("initial token response is incomplete")
    return {
        "version": 1,
        "baseUrl": BASE_URL,
        "clientId": pending["clientId"],
        "accessToken": token["access_token"],
        "refreshToken": refresh_token,
        "tokenType": "Bearer",
        "expiresAt": int(time.time() * 1000 + expires_in * 1000),
        "ownerUsername": pending["ownerUsername"],
        "ownerPassword": pending["ownerPassword"],
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "credentialGeneration": 1,
    }


def persist_completed_credentials(
    token: dict[str, Any],
    pending: dict[str, Any],
) -> dict[str, Any]:
    credentials = credentials_from_token(token, pending)
    atomic_write_json(CREDENTIAL_PATH, credentials)
    remove_pending()
    return credentials


def recover_token_with_login(account: dict[str, Any]) -> dict[str, Any]:
    """Recover OAuth tokens using HA's standard local auth login flow."""
    flow = post_json(
        "/auth/login_flow",
        {
            "client_id": account["clientId"],
            "handler": ["homeassistant", None],
            "redirect_uri": account["clientId"],
            "type": "authorize",
        },
    )
    flow_id = flow.get("flow_id") if isinstance(flow, dict) else None
    if not isinstance(flow_id, str) or not flow_id:
        raise BootstrapError("login flow creation response is invalid")

    result = post_json(
        f"/auth/login_flow/{urllib.parse.quote(flow_id, safe='')}",
        {
            "client_id": account["clientId"],
            "username": account["ownerUsername"],
            "password": account["ownerPassword"],
        },
    )
    auth_code = result.get("result") if isinstance(result, dict) else None
    if (
        not isinstance(result, dict)
        or result.get("type") != "create_entry"
        or not isinstance(auth_code, str)
        or not auth_code
    ):
        raise BootstrapError("login flow did not return an authorization code")
    return exchange(
        {"grant_type": "authorization_code", "code": auth_code},
        account["clientId"],
    )


def credentials_from_recovery(
    token: dict[str, Any], credentials: dict[str, Any]
) -> dict[str, Any]:
    refresh_token = token.get("refresh_token")
    expires_in = token.get("expires_in")
    if (
        not isinstance(refresh_token, str)
        or not refresh_token
        or not isinstance(expires_in, (int, float))
        or expires_in <= 0
    ):
        raise BootstrapError("recovery token response is incomplete")
    return {
        **credentials,
        "accessToken": token["access_token"],
        "refreshToken": refresh_token,
        "expiresAt": int(time.time() * 1000 + expires_in * 1000),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "credentialGeneration": int(credentials.get("credentialGeneration", 1)) + 1,
    }


def refresh(credentials: dict[str, Any]) -> dict[str, Any]:
    try:
        token = exchange(
            {
                "grant_type": "refresh_token",
                "refresh_token": credentials["refreshToken"],
            },
            credentials["clientId"],
        )
    except BootstrapError as exc:
        if exc.status_code != 400:
            raise
        LOG.warning("stored Home Assistant refresh credential was rejected; recovering")
        token = recover_token_with_login(credentials)
        updated = credentials_from_recovery(token, credentials)
        atomic_write_json(CREDENTIAL_PATH, updated)
        return updated

    expires_in = token.get("expires_in")
    if not isinstance(expires_in, (int, float)) or expires_in <= 0:
        raise BootstrapError("refresh response expires_in is invalid")
    updated = {
        **credentials,
        "accessToken": token["access_token"],
        "refreshToken": token.get("refresh_token") or credentials["refreshToken"],
        "expiresAt": int(time.time() * 1000 + expires_in * 1000),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    atomic_write_json(CREDENTIAL_PATH, updated)
    return updated


def wait_ready() -> list[dict[str, Any]]:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            return get_onboarding()
        except BootstrapError:
            time.sleep(2)
    raise BootstrapError("Home Assistant did not become ready within 300 seconds")


def step_done(steps: list[dict[str, Any]], name: str) -> bool:
    return any(
        item.get("step") == name and item.get("done") is True for item in steps
    )


def complete_remaining(
    credentials: dict[str, Any],
    steps: list[dict[str, Any]],
) -> None:
    access_token = credentials["accessToken"]
    if not step_done(steps, "core_config"):
        post_json("/api/onboarding/core_config", {}, access_token)
        LOG.info("completed Home Assistant core_config onboarding")

    steps = get_onboarding()
    if not step_done(steps, "analytics"):
        post_json("/api/onboarding/analytics", {}, access_token)
        LOG.info("completed Home Assistant analytics onboarding")

    steps = get_onboarding()
    if not step_done(steps, "integration"):
        try:
            post_json(
                "/api/onboarding/integration",
                {
                    "client_id": credentials["clientId"],
                    "redirect_uri": credentials["clientId"],
                },
                access_token,
            )
            LOG.info("completed Home Assistant integration onboarding")
        except BootstrapError:
            # Credentials are already durable; this version-sensitive step is retryable.
            LOG.warning("Home Assistant integration onboarding is not yet complete")


def bootstrap_new_user(
    pending: dict[str, Any],
) -> dict[str, Any]:
    user = post_json(
        "/api/onboarding/users",
        {
            "name": "Roban Owner",
            "username": pending["ownerUsername"],
            "password": pending["ownerPassword"],
            "client_id": pending["clientId"],
            "language": "zh-Hans",
        },
    )
    auth_code = user.get("auth_code") if isinstance(user, dict) else None
    if not isinstance(auth_code, str) or not auth_code:
        raise BootstrapError("user onboarding did not return an authorization code")
    token = exchange(
        {"grant_type": "authorization_code", "code": auth_code},
        pending["clientId"],
    )
    return persist_completed_credentials(token, pending)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ensure_state_dir()
    steps = wait_ready()

    if CREDENTIAL_PATH.exists():
        credentials = validate_credentials(
            read_json_file(CREDENTIAL_PATH, "credential file")
        )
        os.chmod(CREDENTIAL_PATH, 0o600)
        # A crash after replacing credentials but before pending unlink is harmless.
        remove_pending()
        if credentials["expiresAt"] <= int(time.time() * 1000) + REFRESH_SKEW_MS:
            credentials = refresh(credentials)
            LOG.info("refreshed Home Assistant access credential")
        complete_remaining(credentials, steps)
        LOG.info("Home Assistant bootstrap state is ready")
        return

    pending = load_pending()
    if step_done(steps, "user"):
        if pending is None:
            raise BootstrapError(
                "Home Assistant is initialized but board credential and pending files are missing"
            )
        token = recover_token_with_login(pending)
        credentials = persist_completed_credentials(token, pending)
        LOG.info("recovered and persisted Home Assistant owner credentials")
        complete_remaining(credentials, get_onboarding())
        return

    if pending is None:
        pending = create_pending()
        LOG.info("persisted pending Home Assistant bootstrap state")
    credentials = bootstrap_new_user(pending)
    LOG.info("created and persisted Home Assistant owner credentials")
    complete_remaining(credentials, get_onboarding())


if __name__ == "__main__":
    try:
        main()
    except BootstrapError as exc:
        LOG.error("bootstrap failed: %s", exc)
        raise SystemExit(1) from None
