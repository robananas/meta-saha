#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(os.environ.get("SAHA_BOARD_STATUS_DIR", "/run/saha/board-status"))
SOCKET_PATH = RUNTIME_DIR / "events.sock"
SNAPSHOT_PATH = RUNTIME_DIR / "snapshot.json"
EVENTS_PATH = RUNTIME_DIR / "events.jsonl"
BOOT_ID_PATH = Path(os.environ.get("SAHA_BOOT_ID_PATH", "/proc/sys/kernel/random/boot_id"))
MAX_EVENTS = int(os.environ.get("SAHA_BOARD_STATUS_MAX_EVENTS", "500"))
POLL_SECONDS = float(os.environ.get("SAHA_BOARD_STATUS_POLL_SECONDS", "2"))
SENSITIVE_KEYS = ("password", "token", "secret", "credential", "private", "session_key", "matter_code")

DEFAULT_NODES = {
    "boot": "unknown",
    "bluetooth": "waiting",
    "ble": "disconnected",
    "wifi": "unconfigured",
    "docker": "waiting_for_network",
    "matter_server": "stopped",
    "home_assistant": "unavailable",
    "ha_credentials": "waiting",
    "ha_matter": "waiting_server",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "<redacted>" if any(part in str(key).lower() for part in SENSITIVE_KEYS) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def read_boot_id() -> str:
    return BOOT_ID_PATH.read_text(encoding="utf-8").strip()


def command_output(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def command_succeeds(command: list[str]) -> bool:
    return command_output(command) is not None


def tcp_reachable(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


class BoardStatus:
    def __init__(self) -> None:
        self.boot_id = read_boot_id()
        self.seq = 0
        self.events: list[dict[str, Any]] = []
        self.snapshot: dict[str, Any] = {
            "bootId": self.boot_id,
            "startedAt": utc_now(),
            "uptimeMs": 0,
            "overallStatus": "booting",
            "nodes": {
                component: {
                    "component": component,
                    "state": state,
                    "level": "info",
                    "updatedAt": None,
                    "updatedMonotonicMs": None,
                    "errorCode": None,
                    "detail": None,
                }
                for component, state in DEFAULT_NODES.items()
            },
            "lastEvent": None,
            "lastSeq": 0,
        }
        if not self._restore_current_boot():
            self.emit("boot", "booting", detail={"source": "saha-board-status"})

    def _restore_current_boot(self) -> bool:
        try:
            snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict) or snapshot.get("bootId") != self.boot_id:
                return False
            restored_events: list[dict[str, Any]] = []
            for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines():
                value = json.loads(line)
                if isinstance(value, dict) and value.get("bootId") == self.boot_id and isinstance(value.get("seq"), int):
                    restored_events.append(value)
            last_seq = snapshot.get("lastSeq", 0)
            if not isinstance(last_seq, int) or last_seq < 0:
                return False
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        self.snapshot = snapshot
        self.events = sorted(restored_events, key=lambda event: event["seq"])[-MAX_EVENTS:]
        self.seq = max([last_seq, *(event["seq"] for event in self.events)])
        for component, state in DEFAULT_NODES.items():
            self.snapshot.setdefault("nodes", {}).setdefault(
                component,
                {"component": component, "state": state, "level": "info", "updatedAt": None, "updatedMonotonicMs": None, "errorCode": None, "detail": None},
            )
        self.persist()
        return True

    def emit(
        self,
        component: str,
        state: str,
        *,
        level: str = "info",
        error_code: str | None = None,
        detail: Any = None,
    ) -> dict[str, Any]:
        component = str(component).strip()
        state = str(state).strip()
        if not component or not state:
            raise ValueError("component and state are required")
        if level not in {"info", "warning", "error"}:
            raise ValueError("level must be info, warning or error")
        sanitized_detail = redact(detail)
        current = self.snapshot["nodes"].get(component)
        if current and all(
            (
                current.get("state") == state,
                current.get("level") == level,
                current.get("errorCode") == (str(error_code) if error_code else None),
                current.get("detail") == sanitized_detail,
            )
        ):
            return self.snapshot.get("lastEvent") or current
        self.seq += 1
        event = {
            "bootId": self.boot_id,
            "seq": self.seq,
            "monotonicMs": monotonic_ms(),
            "timestamp": utc_now(),
            "component": component,
            "state": state,
            "level": level,
            "errorCode": str(error_code) if error_code else None,
            "detail": sanitized_detail,
        }
        self.events.append(event)
        self.events = self.events[-MAX_EVENTS:]
        node = self.snapshot["nodes"].setdefault(component, {"component": component})
        node.update(
            state=state,
            level=level,
            updatedAt=event["timestamp"],
            updatedMonotonicMs=event["monotonicMs"],
            errorCode=event["errorCode"],
            detail=event["detail"],
        )
        self.snapshot["lastEvent"] = event
        self.snapshot["lastSeq"] = self.seq
        self._update_overall()
        self.persist()
        return event

    def _update_overall(self) -> None:
        states = {key: value.get("state") for key, value in self.snapshot["nodes"].items()}
        levels = {value.get("level") for value in self.snapshot["nodes"].values()}
        if "error" in levels and states.get("wifi") != "connected":
            overall = "error"
        elif states.get("wifi") != "connected":
            overall = "awaiting_network"
        elif states.get("home_assistant") not in {"initialized", "http_ready"}:
            overall = "starting"
        elif "error" in levels or "warning" in levels:
            overall = "partial"
        else:
            overall = "ready"
        self.snapshot["overallStatus"] = overall

    def persist(self) -> None:
        self.snapshot["uptimeMs"] = max(0, monotonic_ms())
        atomic_write(SNAPSHOT_PATH, json.dumps(self.snapshot, ensure_ascii=False, separators=(",", ":")) + "\n")
        atomic_write(EVENTS_PATH, "".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n" for event in self.events))

    def reconcile(self) -> None:
        bluetooth_ready = command_succeeds(["systemctl", "is-active", "--quiet", "bluetooth.service"])
        bluetooth_state = "adapter_ready"
        try:
            advertisement = json.loads(Path("/run/saha/ble-advertisement-status.json").read_text(encoding="utf-8"))
            if advertisement.get("advertising") is True:
                bluetooth_state = "advertising"
            elif advertisement.get("lease_token"):
                bluetooth_state = "paused"
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            pass
        credentials_ready = Path("/data/saha/homeassistant/app-credentials.json").is_file()
        home_assistant_ready = tcp_reachable(8123)
        bootstrap_ready = command_succeeds(
            ["systemctl", "is-active", "--quiet", "saha-homeassistant-bootstrap.service"]
        )
        checks = {
            "bluetooth": (bluetooth_state, bluetooth_ready),
            "docker": ("ready", command_succeeds(["systemctl", "is-active", "--quiet", "saha-docker-compose.service"])),
            "matter_server": ("healthy", command_output(["docker", "inspect", "--format", "{{.State.Health.Status}}", "matter-server"]) == "healthy"),
            "home_assistant": ("initialized" if credentials_ready and bootstrap_ready else "http_ready", home_assistant_ready),
            "ha_credentials": ("ready", credentials_ready),
        }
        for component, (ready_state, ready) in checks.items():
            current = self.snapshot["nodes"][component]["state"]
            ready_states = {ready_state}
            if component == "bluetooth":
                ready_states.update({"advertising", "paused"})
            if component == "home_assistant":
                ready_states.add("initialized")
            if ready and current not in ready_states:
                self.emit(component, ready_state, detail={"source": "health_check"})
            elif not ready and component == "matter_server" and current == "healthy":
                self.emit(component, "stopped", level="warning", error_code="HEALTH_CHECK_FAILED")
            elif not ready and component == "home_assistant" and current in {"http_ready", "initialized"}:
                self.emit(component, "unavailable", level="warning", error_code="HEALTH_CHECK_FAILED")

        wifi_output = command_output(["nmcli", "-t", "-f", "GENERAL.STATE", "device", "show", "wlan0"])
        wifi_connected = wifi_output is not None and "100 (connected)" in wifi_output
        wifi_state = self.snapshot["nodes"]["wifi"]["state"]
        if wifi_connected and wifi_state in {"unconfigured", "disconnected"}:
            self.emit("wifi", "connected", detail={"source": "health_check"})
        if self.snapshot["nodes"]["boot"]["state"] != "ready":
            self.emit("boot", "ready", detail={"source": "initial_health_check"})
        self.persist()


def parse_message(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("event must be an object")
    return value


def run_daemon() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(RUNTIME_DIR, 0o755)
    try:
        SOCKET_PATH.unlink()
    except FileNotFoundError:
        pass
    status = BoardStatus()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(str(SOCKET_PATH))
    os.chmod(SOCKET_PATH, 0o666)
    server.settimeout(POLL_SECONDS)
    try:
        while True:
            try:
                message = parse_message(server.recv(65535))
                status.emit(
                    message.get("component", ""),
                    message.get("state", ""),
                    level=message.get("level", "info"),
                    error_code=message.get("errorCode"),
                    detail=message.get("detail"),
                )
            except socket.timeout:
                status.reconcile()
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
                continue
    finally:
        server.close()
        try:
            SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass


def emit_cli(arguments: argparse.Namespace) -> None:
    detail = json.loads(arguments.detail) if arguments.detail else None
    payload = {
        "component": arguments.component,
        "state": arguments.state,
        "level": arguments.level,
        "errorCode": arguments.error_code,
        "detail": detail,
    }
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        client.sendto(json.dumps(payload, separators=(",", ":")).encode("utf-8"), str(SOCKET_PATH))
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("daemon")
    emit_parser = subparsers.add_parser("emit")
    emit_parser.add_argument("component")
    emit_parser.add_argument("state")
    emit_parser.add_argument("--level", choices=("info", "warning", "error"), default="info")
    emit_parser.add_argument("--error-code")
    emit_parser.add_argument("--detail")
    arguments = parser.parse_args()
    if arguments.command == "daemon":
        run_daemon()
    else:
        emit_cli(arguments)


if __name__ == "__main__":
    main()
