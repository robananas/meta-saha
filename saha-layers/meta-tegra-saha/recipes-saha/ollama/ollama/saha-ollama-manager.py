#!/usr/bin/env python3
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal

Stage = Literal["stt", "llm", "tts"]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
STATE_ROOT = Path(os.environ.get("SAHA_MODEL_MANAGER_STATE", "/data/model-cache/s2s-model-manager"))
MODEL_ROOT = Path(os.environ.get("SAHA_MODEL_ROOT", "/data/models/s2s"))
SELECTION_PATH = Path(os.environ.get("SAHA_MODEL_SELECTION", "/data/model-config/s2s/selection.json"))
LEGACY_CONFIG_PATH = Path(os.environ.get("SAHA_OLLAMA_CONFIG", "/data/model-config/s2s/ollama.env"))
TASKS_PATH = STATE_ROOT / "downloads.json"
NETWORK_PROBE_URL = os.environ.get("SAHA_MODEL_PROBE_URL", "https://huggingface.co/")
STAGES: tuple[Stage, ...] = ("stt", "llm", "tts")


@dataclass(frozen=True)
class ArtifactSpec:
    url: str
    sha256: str
    filename: str
    size_bytes: int
    required_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterSpec:
    name: str
    protocol: str
    activation: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    stage: Stage
    label: str
    description: str
    backend: str
    adapter: AdapterSpec
    languages: tuple[str, ...]
    quantization: str | None
    disk_bytes: int
    memory_bytes: int
    artifacts: tuple[ArtifactSpec, ...]
    validation_status: str


@dataclass(frozen=True)
class DownloadState:
    model_id: str
    status: str
    bytes_completed: int = 0
    bytes_total: int = 0
    bytes_per_second: float = 0.0
    eta_seconds: float | None = None
    error: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    updated_at: float = 0.0


@dataclass(frozen=True)
class StageSelection:
    model_id: str
    adapter: str
    config: dict[str, Any]


@dataclass(frozen=True)
class PipelineSelection:
    version: int
    stages: dict[Stage, StageSelection]


OLLAMA_ADAPTER = AdapterSpec("openai-compatible-chat", "ollama", (("base_url", "http://127.0.0.1:11434/v1"),))
FUNASR_ADAPTER = AdapterSpec(
    "funasr-paraformer-official-v0.2.10",
    "local-bundle",
    (
        ("model_path", "/models/stt/funasr-paraformer-zh"),
        ("warmup_audio_path", "/models/stt/funasr-paraformer-zh/example/asr_example.wav"),
        ("device", "cuda"),
    ),
)
QWEN3_TTS_ADAPTER = AdapterSpec(
    "qwen3-tts-0.6b-customvoice-edgellm-v0.9.1",
    "local-bundle",
    (
        ("model_path", "/models/tts/qwen3-tts-0.6b-customvoice"),
        ("command", ("python", "-m", "roban_voice_s2s.qwen3_tts_cli", "--model-path", "{model_path}", "--output", "{output}")),
        ("speaker", "serena"),
        ("language", "Chinese"),
        ("timeout_seconds", 180),
    ),
)
# The production catalog is a release gate, not a candidate list. Only models with
# retained Orin R39.2/CUDA 13.2 evidence belong here.
CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec(
        "funasr-paraformer-zh",
        "stt",
        "FunASR Paraformer 中文",
        "speech-to-speech 0.2.10 官方 handler；真实中文 warmup，Orin CUDA 实测",
        "funasr",
        FUNASR_ADAPTER,
        ("zh",),
        None,
        888_917_289,
        4_263_718_912,
        (ArtifactSpec("", "5bba782a5e9196166233b9ab12ba04cadff9ef9212b4ff6153ed9290ff679025", "snapshot", 888_917_289, ("model.pt", "config.yaml", "tokens.json", "example/asr_example.wav")),),
        "verified-orin-r39.2-cuda13.2",
    ),
    ModelSpec("qwen2.5:1.5b-instruct-q4_K_M", "llm", "Qwen 2.5 1.5B", "Orin 实测中文低延迟模型", "openai-compatible", OLLAMA_ADAPTER, ("zh", "en"), "Q4_K_M", 986_061_892, 1_500_000_000, (), "verified-orin-r39.2-cuda13.2"),
    ModelSpec(
        "qwen3-tts-0.6b-customvoice",
        "tts",
        "Qwen3-TTS 0.6B CustomVoice",
        "NVIDIA TensorRT Edge-LLM v0.9.1；Orin sm87 中文合成与 FunASR 回识别实测",
        "tensorrt-edgellm",
        QWEN3_TTS_ADAPTER,
        ("zh", "en"),
        "FP16",
        2_147_483_648,
        4_340_000_000,
        (ArtifactSpec("", "", "engine-bundle", 2_147_483_648, ("talker/llm.engine", "talker/config.json", "code_predictor/llm.engine", "code2wav/code2wav.engine")),),
        "verified-orin-r39.2-cuda13.2",
    ),
)
BY_ID = {item.id: item for item in CATALOG}
ALLOWED = frozenset(BY_ID)
DOWNLOADS: dict[str, DownloadState] = {}
DOWNLOAD_LOCK = threading.RLock()
PAUSE_EVENTS: dict[str, threading.Event] = {}


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    temporary.replace(path)


def _state_dict(state: DownloadState) -> dict[str, Any]:
    value = dataclasses.asdict(state)
    return {
        "modelId": value["model_id"], "status": value["status"],
        "bytesCompleted": value["bytes_completed"], "bytesTotal": value["bytes_total"],
        "bytesPerSecond": value["bytes_per_second"], "etaSeconds": value["eta_seconds"],
        "error": value["error"], "etag": value["etag"],
        "lastModified": value["last_modified"], "updatedAt": value["updated_at"],
    }


def persist_downloads() -> None:
    with DOWNLOAD_LOCK:
        payload = {model: _state_dict(state) for model, state in DOWNLOADS.items()}
    _atomic_json(TASKS_PATH, {"version": 1, "downloads": payload})


def set_download(model: str, **changes: Any) -> DownloadState:
    with DOWNLOAD_LOCK:
        old = DOWNLOADS.get(model, DownloadState(model, "idle"))
        state = dataclasses.replace(old, updated_at=time.time(), **changes)
        DOWNLOADS[model] = state
    persist_downloads()
    return state


def load_downloads() -> list[str]:
    try:
        body = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    interrupted: list[str] = []
    for model, value in body.get("downloads", {}).items():
        if model not in ALLOWED or not isinstance(value, dict):
            continue
        status = str(value.get("status", "error"))
        if status in {"starting", "downloading"}:
            status = "paused"
            interrupted.append(model)
        DOWNLOADS[model] = DownloadState(
            model, status, int(value.get("bytesCompleted", 0)), int(value.get("bytesTotal", 0)),
            0.0, None, value.get("error"), value.get("etag"), value.get("lastModified"),
            float(value.get("updatedAt", 0)),
        )
    return interrupted


def ollama_request(path: str, payload: dict[str, Any] | None = None, timeout: int = 30):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(f"{OLLAMA_URL}{path}", data=data, headers={"Content-Type": "application/json"}, method="GET" if data is None else "POST")
    return urllib.request.urlopen(request, timeout=timeout)


def installed_ollama_models() -> set[str]:
    try:
        with ollama_request("/api/tags", timeout=5) as response:
            body = json.load(response)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return set()
    return {str(model.get("name", "")) for model in body.get("models", [])}


def selection_for(spec: ModelSpec) -> StageSelection:
    config = dict(spec.adapter.activation)
    if spec.adapter.protocol == "ollama":
        config["model"] = spec.id
    else:
        config.setdefault("model_path", f"/models/{spec.stage}/{spec.id}")
    return StageSelection(spec.id, spec.adapter.name, config)


def read_selection() -> PipelineSelection:
    try:
        body = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
        stages: dict[Stage, StageSelection] = {}
        for stage, value in body.get("stages", {}).items():
            if stage not in STAGES or not isinstance(value, dict):
                continue
            model_id = value.get("modelId")
            adapter = value.get("adapter")
            config = value.get("config")
            spec = BY_ID.get(model_id)
            if spec and spec.stage == stage and adapter == spec.adapter.name and isinstance(config, dict):
                stages[stage] = StageSelection(model_id, adapter, config)
        return PipelineSelection(int(body.get("version", 1)), stages)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return PipelineSelection(1, {})


def selection_dict(selection: PipelineSelection) -> dict[str, Any]:
    return {"version": selection.version, "stages": {stage: {"modelId": value.model_id, "adapter": value.adapter, "config": value.config} for stage, value in selection.stages.items()}}


def active_model() -> str | None:
    selected = read_selection().stages.get("llm")
    return selected.model_id if selected else None


def model_installed(spec: ModelSpec, ollama_models: set[str] | None = None) -> bool:
    if spec.adapter.protocol == "ollama":
        return spec.id in (ollama_models if ollama_models is not None else installed_ollama_models())
    destination = MODEL_ROOT / spec.stage / spec.id
    return destination.is_dir() and all((destination / required).is_file() for artifact in spec.artifacts for required in artifact.required_files)


def catalog_response() -> dict[str, Any]:
    stages = {stage: [] for stage in STAGES}
    for spec in CATALOG:
        stages[spec.stage].append({
            "id": spec.id, "stage": spec.stage, "label": spec.label, "description": spec.description,
            "backend": spec.backend, "adapter": spec.adapter.name, "languages": list(spec.languages),
            "quantization": spec.quantization, "diskBytes": spec.disk_bytes, "memoryBytes": spec.memory_bytes,
            "validationStatus": spec.validation_status,
        })
    return {"version": 1, "stages": stages}


def models_status() -> dict[str, Any]:
    selection = read_selection()
    ollama_models = installed_ollama_models()
    with DOWNLOAD_LOCK:
        downloads = dict(DOWNLOADS)
    stages: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        selected = selection.stages.get(stage)
        active = selected.model_id if selected else None
        models = [spec for spec in CATALOG if spec.stage == stage]
        stages[stage] = {
            "activeModel": active,
            "models": [
                {
                    "id": spec.id,
                    "installed": model_installed(spec, ollama_models),
                    "active": spec.id == active,
                    "compatible": selected is None or (selected.model_id == spec.id and selected.adapter == spec.adapter.name),
                    "download": _state_dict(downloads[spec.id]) if spec.id in downloads else None,
                }
                for spec in models
            ],
        }
    return {"version": 1, "stages": stages}


def legacy_model_status() -> dict[str, Any]:
    status = models_status()["stages"]["llm"]
    labels = {spec.id: spec for spec in CATALOG}
    return {"activeModel": status["activeModel"], "models": [
        {"id": item["id"], "label": labels[item["id"]].label, "description": labels[item["id"]].description,
         "sizeBytes": labels[item["id"]].disk_bytes, "installed": item["installed"], "active": item["active"],
         "download": item["download"]} for item in status["models"]]}


def pipeline_readiness() -> dict[str, Any]:
    selection = read_selection()
    ollama_models = installed_ollama_models()
    checks = []
    for stage in STAGES:
        selected = selection.stages.get(stage)
        model_id = selected.model_id if selected else None
        spec = BY_ID.get(model_id or "")
        installed = bool(spec and model_installed(spec, ollama_models))
        compatible = bool(spec and spec.stage == stage and selected and selected.adapter == spec.adapter.name)
        ready = installed and compatible
        reason = None if ready else ("not_selected" if not model_id else "not_installed" if not installed else "incompatible")
        checks.append({"stage": stage, "ready": ready, "modelId": model_id, "installed": installed, "compatible": compatible, "reason": reason})
    ready = all(check["ready"] for check in checks)
    return {"status": "ready" if ready else "not_ready", "ready": ready, "checks": checks}


def pull_ollama_model(model: str) -> None:
    pause = PAUSE_EVENTS.setdefault(model, threading.Event())
    previous_time = time.monotonic()
    previous_bytes = 0
    ewma = 0.0
    try:
        with ollama_request("/api/pull", {"model": model, "stream": True}, timeout=3600) as response:
            for raw in response:
                if pause.is_set():
                    set_download(model, status="paused", bytes_per_second=0.0, eta_seconds=None)
                    return
                event = json.loads(raw)
                completed = int(event.get("completed", 0) or 0)
                total = int(event.get("total", 0) or 0)
                now = time.monotonic()
                elapsed = max(now - previous_time, 0.001)
                instant = max(completed - previous_bytes, 0) / elapsed
                ewma = instant if ewma == 0 else 0.25 * instant + 0.75 * ewma
                eta = (total - completed) / ewma if total > completed and ewma > 0 else None
                set_download(model, status="downloading", bytes_completed=completed, bytes_total=total,
                             bytes_per_second=ewma, eta_seconds=eta, error=None)
                previous_time, previous_bytes = now, completed
        total = max(DOWNLOADS.get(model, DownloadState(model, "success")).bytes_total, 1)
        set_download(model, status="success", bytes_completed=total, bytes_total=total, bytes_per_second=0.0, eta_seconds=0.0, error=None)
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
        set_download(model, status="error", bytes_per_second=0.0, eta_seconds=None, error=str(error))


def start_download(model: str) -> bool:
    with DOWNLOAD_LOCK:
        current = DOWNLOADS.get(model)
        if current and current.status in {"starting", "downloading"}:
            return False
    PAUSE_EVENTS.setdefault(model, threading.Event()).clear()
    set_download(model, status="starting", error=None, bytes_per_second=0.0, eta_seconds=None)
    threading.Thread(target=pull_ollama_model, args=(model,), daemon=True, name=f"model-download-{model}").start()
    return True


def pause_download(model: str) -> None:
    PAUSE_EVENTS.setdefault(model, threading.Event()).set()
    set_download(model, status="paused", bytes_per_second=0.0, eta_seconds=None)


def require_model(body: dict[str, Any], stage: str | None = None) -> ModelSpec:
    model = body.get("modelId", body.get("model"))
    if not isinstance(model, str) or model not in ALLOWED:
        raise ValueError("model is not in the allowlisted catalog")
    spec = BY_ID[model]
    requested_stage = body.get("stage", stage)
    if requested_stage is not None and requested_stage != spec.stage:
        raise ValueError("model does not belong to the requested stage")
    return spec


def activate(spec: ModelSpec) -> None:
    if not model_installed(spec):
        raise RuntimeError("model is not installed")
    old = read_selection()
    stages = dict(old.stages)
    stages[spec.stage] = selection_for(spec)
    _atomic_json(SELECTION_PATH, selection_dict(PipelineSelection(1, stages)))
    if spec.stage == "llm":
        LEGACY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = LEGACY_CONFIG_PATH.with_suffix(".tmp")
        temporary.write_text(f"ROBAN_S2S_LLM_MODEL={spec.id}\n", encoding="utf-8")
        os.chmod(temporary, 0o640)
        temporary.replace(LEGACY_CONFIG_PATH)
    try:
        subprocess.run(["systemctl", "try-restart", "saha-s2s.service"], check=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        _atomic_json(SELECTION_PATH, selection_dict(old))
        raise


def network_status() -> dict[str, Any]:
    wifi: dict[str, Any] = {"connected": False, "signalPercent": None, "ssid": None}
    try:
        result = subprocess.run(["nmcli", "-t", "-f", "ACTIVE,SIGNAL,SSID", "device", "wifi"], capture_output=True, text=True, timeout=5, check=True)
        for line in result.stdout.splitlines():
            if line.startswith("yes:"):
                _, signal, ssid = line.split(":", 2)
                wifi = {"connected": True, "signalPercent": int(signal), "ssid": ssid}
                break
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    started = time.monotonic()
    source = {"reachable": False, "latencyMs": None, "url": NETWORK_PROBE_URL, "error": None}
    try:
        request = urllib.request.Request(NETWORK_PROBE_URL, method="HEAD")
        with urllib.request.urlopen(request, timeout=5):
            pass
        source.update(reachable=True, latencyMs=round((time.monotonic() - started) * 1000, 1))
    except (OSError, urllib.error.URLError) as error:
        source["error"] = str(error)
    with DOWNLOAD_LOCK:
        rates = [state.bytes_per_second for state in DOWNLOADS.values() if state.status == "downloading"]
    return {"wifi": wifi, "modelSource": source, "downloadBytesPerSecond": sum(rates), "checkedAt": time.time()}


class Handler(BaseHTTPRequestHandler):
    server_version = "SahaS2SModelManager/2.0"

    def send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self) -> dict[str, Any]:
        value = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
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
            routes = {
                "/health": lambda: {"status": "ok"}, "/v1/catalog": catalog_response,
                "/v1/models/status": models_status, "/v1/models": legacy_model_status,
                "/v1/pipeline/readiness": pipeline_readiness, "/v1/network/status": network_status,
            }
            function = routes.get(self.path)
            self.send_json(200, function()) if function else self.send_json(404, {"error": "not found"})
        except (OSError, urllib.error.URLError, ValueError) as error:
            self.send_json(503, {"error": str(error)})

    def do_POST(self) -> None:
        try:
            body = self.read_json()
            spec = require_model(body)
            if self.path in {"/v1/models/download", "/v1/models/pull", "/v1/models/resume"}:
                started = start_download(spec.id)
                self.send_json(202, {"modelId": spec.id, "model": spec.id, "status": "starting" if started else "already_downloading"})
            elif self.path == "/v1/models/pause":
                pause_download(spec.id)
                self.send_json(200, {"modelId": spec.id, "status": "paused"})
            elif self.path == "/v1/models/activate":
                activate(spec)
                self.send_json(200, {"modelId": spec.id, "model": spec.id, "stage": spec.stage, "status": "active"})
            else:
                self.send_json(404, {"error": "not found"})
        except (json.JSONDecodeError, ValueError) as error:
            self.send_json(400, {"error": str(error)})
        except RuntimeError as error:
            self.send_json(409, {"error": str(error)})
        except (OSError, subprocess.SubprocessError, urllib.error.URLError) as error:
            self.send_json(503, {"error": str(error)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"saha-s2s-model-manager: {format % args}", flush=True)


def main() -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    for stage in STAGES:
        (MODEL_ROOT / stage).mkdir(parents=True, exist_ok=True)
    interrupted = load_downloads()
    for model in interrupted:
        start_download(model)
    address = os.environ.get("SAHA_MODEL_MANAGER_HOST", os.environ.get("SAHA_OLLAMA_MANAGER_HOST", "0.0.0.0"))
    port = int(os.environ.get("SAHA_MODEL_MANAGER_PORT", os.environ.get("SAHA_OLLAMA_MANAGER_PORT", "11435")))
    ThreadingHTTPServer((address, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
