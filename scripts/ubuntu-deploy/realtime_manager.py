#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import subprocess
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MODE = Path(os.environ.get("SAHA_PIPELINE_MODE", "/var/lib/roban-ubuntu/model-config/s2s/pipeline-mode.json"))
SETTINGS = Path(os.environ.get("SAHA_REALTIME_SETTINGS", "/var/lib/roban-ubuntu/model-config/s2s/realtime-settings.json"))
KEY = Path(os.environ.get("SAHA_DASHSCOPE_API_KEY_PATH", "/etc/roban-ubuntu/s2s-secrets/dashscope-api-key"))
WORKSPACE = Path(os.environ.get("SAHA_DASHSCOPE_WORKSPACE_ID_PATH", "/var/lib/roban-ubuntu/model-config/s2s/dashscope-workspace-id"))
HOST = os.environ.get("SAHA_MODEL_MANAGER_HOST", "0.0.0.0")
PORT = int(os.environ.get("SAHA_MODEL_MANAGER_PORT", "11435"))


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temporary, path)


def s2s_ready() -> dict[str, Any]:
    try:
        return json.load(urllib.request.urlopen("http://127.0.0.1:8765/ready", timeout=5))
    except Exception:
        return {"ready": False, "status": "unavailable"}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        value = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value

    def do_GET(self) -> None:
        mode = read_json(MODE, {"mode": "realtime", "provider": "qwen", "generation": 1})
        settings = read_json(SETTINGS, {})
        configured = KEY.is_file() and KEY.stat().st_size > 0
        routes: dict[str, Any] = {
            "/health": {"status": "ok", "mode": "cloud-only"},
            "/v1/catalog": {"models": [], "cloudOnly": True},
            "/v1/models/status": {"models": [], "cloudOnly": True},
            "/v1/pipeline/readiness": s2s_ready(),
            "/v1/pipeline/mode": mode,
            "/v1/realtime/settings": settings,
            "/v1/network/status": {"online": True, "hostname": socket.gethostname()},
            "/v1/voices": {"voices": [], "cloudOnly": True},
            "/v1/speaker/status": {"enabled": False, "cloudOnly": True},
            "/v1/providers": {"qwen": {"available": True, "configured": configured, "workspaceConfigured": WORKSPACE.is_file()}},
        }
        self.send_json(200, routes[self.path]) if self.path in routes else self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            body = self.read_json()
            if self.path == "/v1/pipeline/mode":
                requested = body.get("mode", "realtime")
                provider = body.get("provider", "qwen")
                if requested != "realtime" or provider != "qwen":
                    self.send_json(409, {"error": {"code": "cloud_only", "message": "Only Qwen Realtime is installed"}})
                    return
                current = read_json(MODE, {"generation": 0})
                value = {"mode": "realtime", "provider": "qwen", "generation": int(current.get("generation", 0)) + 1}
                write_json(MODE, value)
                subprocess.run(["systemctl", "restart", "roban-edge.service"], check=True, timeout=120)
                self.send_json(200, value)
                return
            if self.path == "/v1/realtime/settings":
                body["provider"] = "qwen"
                write_json(SETTINGS, body)
                subprocess.run(["systemctl", "restart", "roban-edge.service"], check=True, timeout=120)
                self.send_json(200, body)
                return
            self.send_json(409, {"error": {"code": "cloud_only", "message": "Local models, speakers, and custom voices are not installed"}})
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            self.send_json(503, {"error": str(error)})

    def log_message(self, format: str, *args: Any) -> None:
        print("roban-realtime-manager: " + format % args, flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
