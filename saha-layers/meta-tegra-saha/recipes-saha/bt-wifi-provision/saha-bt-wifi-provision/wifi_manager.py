#!/usr/bin/env python3
"""NetworkManager WiFi helpers via nmcli."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from typing import Any, Callable


class WifiError(Exception):
    """Raised when nmcli fails."""


_NMCLI_LOCK = threading.RLock()


def _split_terse(line: str) -> list[str]:
    """Split nmcli terse output while honoring its backslash escaping."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


def _signal_percent(value: str) -> int:
    try:
        return max(0, min(100, int(value or "0")))
    except ValueError:
        return 0


def _run_nmcli(args: list[str], timeout: int = 60) -> str:
    cmd = ["nmcli", *args]
    try:
        with _NMCLI_LOCK:
            completed = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or str(exc)).strip()
        raise WifiError(message or "nmcli command failed") from exc
    except subprocess.TimeoutExpired as exc:
        raise WifiError("nmcli command timed out") from exc
    except OSError as exc:
        raise WifiError(f"unable to run nmcli: {exc}") from exc
    return completed.stdout


def _wifi_device() -> str | None:
    output = _run_nmcli(["-t", "-f", "DEVICE,TYPE,STATE", "dev", "status"])
    for line in output.splitlines():
        parts = _split_terse(line)
        if len(parts) < 3:
            continue
        device, dev_type, _state = parts[0], parts[1], parts[2]
        if dev_type == "wifi" and device:
            return device
    return None


def _active_connection() -> dict[str, str]:
    output = _run_nmcli(["-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show", "--active"])
    for line in output.splitlines():
        parts = _split_terse(line)
        if len(parts) < 4:
            continue
        name, uuid, conn_type, device = parts[0], parts[1], parts[2], parts[3]
        if conn_type == "802-11-wireless" and device:
            return {"name": name, "uuid": uuid, "device": device}
    return {}


def _ipv4_fields(device: str) -> dict[str, str]:
    output = _run_nmcli(["-t", "-f", "IP4.ADDRESS,IP4.GATEWAY,IP4.DNS", "dev", "show", device])
    addresses: list[str] = []
    gateway = ""
    dns: list[str] = []
    for line in output.splitlines():
        if line.startswith("IP4.ADDRESS"):
            value = line.split(":", 1)[1]
            if value:
                addresses.append(value.split("/", 1)[0])
        elif line.startswith("IP4.GATEWAY"):
            gateway = line.split(":", 1)[1]
        elif line.startswith("IP4.DNS"):
            dns.append(line.split(":", 1)[1])
    return {
        "ip": addresses[0] if addresses else "",
        "addresses": addresses,
        "gateway": gateway,
        "dns": dns,
    }


def get_wifi_status() -> dict[str, Any]:
    device = _wifi_device()
    if not device:
        return {
            "connected": False,
            "ssid": "",
            "interface": "",
            "ip": "",
            "gateway": "",
            "dns": [],
            "signal": 0,
            "security": "",
        }

    active = _active_connection()
    connected = active.get("device") == device
    ssid = active.get("name", "") if connected else ""
    signal = 0
    security = ""

    wifi_output = _run_nmcli(["-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "dev", "wifi"])
    for line in wifi_output.splitlines():
        parts = _split_terse(line)
        if len(parts) < 4:
            continue
        is_active, line_ssid, line_signal, line_security = parts[0], parts[1], parts[2], parts[3]
        if is_active == "yes" or (connected and line_ssid == ssid):
            ssid = line_ssid or ssid
            signal = _signal_percent(line_signal)
            security = line_security
            connected = True
            break

    ipv4 = _ipv4_fields(device) if connected else {"ip": "", "gateway": "", "dns": [], "addresses": []}
    return {
        "connected": connected,
        "ssid": ssid,
        "interface": device,
        "ip": ipv4["ip"],
        "addresses": ipv4["addresses"],
        "gateway": ipv4["gateway"],
        "dns": ipv4["dns"],
        "signal": signal,
        "signal_percent": signal,
        "security": security,
    }


def scan_wifi(limit: int = 20) -> dict[str, Any]:
    device = _wifi_device()
    if not device:
        raise WifiError("no WiFi device found")

    _run_nmcli(["dev", "wifi", "rescan", "ifname", device], timeout=30)
    output = _run_nmcli(["-t", "-f", "SSID,SIGNAL,SECURITY,FREQ", "dev", "wifi", "list", "ifname", device])

    networks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in output.splitlines():
        parts = _split_terse(line)
        if len(parts) < 4:
            continue
        ssid, signal_text, security, freq = parts[0], parts[1], parts[2], parts[3]
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        signal = _signal_percent(signal_text)
        networks.append(
            {
                "ssid": ssid,
                "signal": signal,
                "signal_percent": signal,
                "security": security,
                "frequency_mhz": int(freq) if freq.isdigit() else freq,
            }
        )
        if len(networks) >= limit:
            break

    networks.sort(key=lambda item: item["signal"], reverse=True)
    return {"networks": networks}


def connect_wifi(
    ssid: str,
    password: str | None = None,
    deadline_seconds: int = 90,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if not ssid:
        raise WifiError("ssid is required")
    deadline_seconds = max(5, min(int(deadline_seconds), 120))
    deadline = time.monotonic() + deadline_seconds
    device = _wifi_device()
    if not device:
        raise WifiError("no WiFi device found")

    args = ["dev", "wifi", "connect", ssid, "ifname", device]
    if password:
        args.extend(["password", password])
    if progress:
        progress("associating")
    try:
        _run_nmcli(args, timeout=max(1, int(deadline - time.monotonic())))
    except WifiError as exc:
        return {"state": "failed", "ssid": ssid, "error": str(exc), **get_wifi_status()}

    status: dict[str, Any] = {}
    if progress:
        progress("obtainingIp")
    while time.monotonic() < deadline:
        status = get_wifi_status()
        if status.get("connected") and status.get("ssid") == ssid and status.get("ip"):
            return {"state": "connected", "ssid": ssid, "error": "", **status}
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    return {
        "state": "failed",
        "ssid": ssid,
        "error": "connection deadline expired before matching SSID obtained IPv4",
        **status,
    }


def handle_command(
    payload: dict[str, Any], progress: Callable[[str], None] | None = None
) -> dict[str, Any]:
    cmd = str(payload.get("cmd", "")).strip().lower()
    if cmd == "status":
        return {"event": "status", **get_wifi_status()}
    if cmd == "scan":
        limit = int(payload.get("limit", 20))
        limit = max(1, min(limit, 30))
        return {"event": "scan", **scan_wifi(limit=limit)}
    if cmd == "connect":
        ssid = str(payload.get("ssid", "")).strip()
        password = payload.get("password")
        if password is not None:
            password = str(password)
        deadline_seconds = payload.get("deadline_seconds", 90)
        if isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, int):
            raise WifiError("deadline_seconds must be an integer")
        result = connect_wifi(ssid, password, deadline_seconds, progress)
        return {"event": "connect", **result}
    raise WifiError(f"unsupported cmd: {cmd or '<empty>'}")


def decode_json(data: bytes) -> dict[str, Any]:
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        raise WifiError("empty command payload")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WifiError("invalid JSON command") from exc
    if not isinstance(payload, dict):
        raise WifiError("command payload must be a JSON object")
    return payload


def encode_json(payload: dict[str, Any]) -> list[int]:
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return [ord(ch) for ch in text]
