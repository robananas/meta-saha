#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
CONFIG_PATH = Path(os.environ.get("SAHA_OLLAMA_CONFIG", "/data/model-config/s2s/ollama.env"))
DEFAULT_CONFIG_PATH = Path(os.environ.get("SAHA_OLLAMA_DEFAULT_CONFIG", "/etc/default/ollama"))
CATALOG = (
    {"id": "qwen2.5:1.5b-instruct-q4_K_M", "label": "Qwen 2.5 1.5B", "description": "中文低延迟，推荐默认模型", "sizeBytes": 986_000_000},
    {"id": "qwen2.5:3b-instruct-q4_K_M", "label": "Qwen 2.5 3B", "description": "质量更高，显存占用更大", "sizeBytes": 1_900_000_000},
    {"id": "gemma3:1b-it-q4_K_M", "label": "Gemma 3 1B", "description": "轻量通用模型", "sizeBytes": 815_000_000},
)
ALLOWED = {item["id"] for item in CATALOG}
DOWNLOADS: dict[str, dict[str, Any]] = {}
DOWNLOAD_LOCK = threading.Lock()


def ollama_request(path: str, payload: dict[str, Any] | None = None, timeout: int = 30):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{OLLAMA_URL}{path}", data=data, headers={"Content-Type": "application/json"}, method="GET" if data is None else "POST"
    )
    return urllib.request.urlopen(request, timeout=timeout)


def installed_models() -> set[str]:
    with ollama_request("/api/tags", timeout=5) as response:
        body = json.load(response)
    return {str(model.get("name", "")) for model in body.get("models", [])}


def active_model() -> str | None:
    for path in (CONFIG_PATH, DEFAULT_CONFIG_PATH):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("ROBAN_S2S_LLM_MODEL="):
                    return line.split("=", 1)[1].strip()
        except FileNotFoundError:
            continue
    return None


def model_status() -> dict[str, Any]:
    installed = installed_models()
    active = active_model()
    with DOWNLOAD_LOCK:
        downloads = {name: dict(value) for name, value in DOWNLOADS.items()}
    return {
        "activeModel": active,
        "models": [
            item | {"installed": item["id"] in installed, "active": item["id"] == active, "download": downloads.get(item["id"])}
            for item in CATALOG
        ],
    }


def pull_model(model: str) -> None:
    try:
        with ollama_request("/api/pull", {"model": model, "stream": True}, timeout=3600) as response:
            for raw in response:
                event = json.loads(raw)
                with DOWNLOAD_LOCK:
                    DOWNLOADS[model] = {
                        "status": str(event.get("status", "downloading")),
                        "completed": int(event.get("completed", 0) or 0),
                        "total": int(event.get("total", 0) or 0),
                        "error": None,
                    }
        with DOWNLOAD_LOCK:
            DOWNLOADS[model] = {"status": "success", "completed": 1, "total": 1, "error": None}
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
        with DOWNLOAD_LOCK:
            DOWNLOADS[model] = {"status": "error", "completed": 0, "total": 0, "error": str(error)}


def start_pull(model: str) -> bool:
    with DOWNLOAD_LOCK:
        current = DOWNLOADS.get(model)
        if current and current.get("status") not in {"success", "error"}:
            return False
        DOWNLOADS[model] = {"status": "starting", "completed": 0, "total": 0, "error": None}
    threading.Thread(target=pull_model, args=(model,), daemon=True, name=f"ollama-pull-{model}").start()
    return True


def require_model(body: dict[str, Any]) -> str:
    model = body.get("model")
    if not isinstance(model, str) or model not in ALLOWED:
        raise ValueError("model is not in the allowlisted catalog")
    return model


class Handler(BaseHTTPRequestHandler):
    server_version = "SahaOllamaManager/1.0"

    def send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        try:
            if self.path == "/health":
                self.send_json(200, {"status": "ok"})
            elif self.path == "/v1/models":
                self.send_json(200, model_status())
            else:
                self.send_json(404, {"error": "not found"})
        except (OSError, urllib.error.URLError, ValueError) as error:
            self.send_json(503, {"error": str(error)})

    def do_POST(self) -> None:
        try:
            body = self.read_json()
            model = require_model(body)
            if self.path == "/v1/models/pull":
                started = start_pull(model)
                self.send_json(202, {"model": model, "status": "starting" if started else "already_downloading"})
            elif self.path == "/v1/models/activate":
                if model not in installed_models():
                    self.send_json(409, {"error": "model is not installed"})
                    return
                CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                temporary = CONFIG_PATH.with_suffix(".tmp")
                temporary.write_text(f"ROBAN_S2S_LLM_MODEL={model}\n", encoding="utf-8")
                os.chmod(temporary, 0o640)
                temporary.replace(CONFIG_PATH)
                subprocess.run(["systemctl", "restart", "saha-s2s.service"], check=True, timeout=180)
                self.send_json(200, {"model": model, "status": "active"})
            else:
                self.send_json(404, {"error": "not found"})
        except (json.JSONDecodeError, ValueError) as error:
            self.send_json(400, {"error": str(error)})
        except (OSError, subprocess.SubprocessError, urllib.error.URLError) as error:
            self.send_json(503, {"error": str(error)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"saha-ollama-manager: {format % args}", flush=True)


def main() -> None:
    address = os.environ.get("SAHA_OLLAMA_MANAGER_HOST", "0.0.0.0")
    port = int(os.environ.get("SAHA_OLLAMA_MANAGER_PORT", "11435"))
    ThreadingHTTPServer((address, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
