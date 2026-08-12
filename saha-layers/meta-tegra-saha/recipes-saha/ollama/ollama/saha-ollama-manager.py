#!/usr/bin/env python3
from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import math
import re
import os
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Literal

Stage = Literal["stt", "llm", "tts", "speaker"]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
STATE_ROOT = Path(os.environ.get("SAHA_MODEL_MANAGER_STATE", "/data/model-cache/s2s-model-manager"))
MODEL_ROOT = Path(os.environ.get("SAHA_MODEL_ROOT", "/data/models/s2s"))
SELECTION_PATH = Path(os.environ.get("SAHA_MODEL_SELECTION", "/data/model-config/s2s/selection.json"))
PIPELINE_MODE_PATH = Path(os.environ.get("SAHA_PIPELINE_MODE", "/data/model-config/s2s/pipeline-mode.json"))
PIPELINE_MODE_TRANSACTION_PATH = Path(os.environ.get("SAHA_PIPELINE_MODE_TRANSACTION", "/data/model-config/s2s/pipeline-mode-transaction.json"))
S2S_TOKEN_PATH = Path(os.environ.get("SAHA_S2S_TOKEN_PATH", "/data/model-secrets/s2s/sub2api.token"))
DASHSCOPE_API_KEY_PATH = Path(os.environ.get("SAHA_DASHSCOPE_API_KEY_PATH", "/data/model-secrets/s2s/dashscope-api-key"))
DASHSCOPE_WORKSPACE_ID_PATH = Path(os.environ.get("SAHA_DASHSCOPE_WORKSPACE_ID_PATH", "/data/model-config/s2s/dashscope-workspace-id"))
SPEAKER_TRANSACTION_PATH = Path(os.environ.get("SAHA_SPEAKER_TRANSACTION", "/data/model-config/s2s/speaker-transaction.json"))
LEGACY_CONFIG_PATH = Path(os.environ.get("SAHA_OLLAMA_CONFIG", "/data/model-config/s2s/ollama.env"))
TASKS_PATH = STATE_ROOT / "downloads.json"
VOICE_ROOT = Path(os.environ.get("SAHA_VOICE_ROOT", "/data/model-config/s2s/voices"))
VOICE_TEMP_ROOT = Path(os.environ.get("SAHA_VOICE_TEMP_ROOT", "/data/model-config/s2s/voice-temp"))
S2S_TRANSCRIBE_URL = os.environ.get("SAHA_S2S_TRANSCRIBE_URL", "http://127.0.0.1:8765/v1/voice-references/transcribe")
S2S_SPEAKER_PROFILE_URL = os.environ.get("SAHA_S2S_SPEAKER_PROFILE_URL", "http://127.0.0.1:8765/v1/speaker/profile")
SPEAKER_TRANSACTION_TTL_SECONDS = int(os.environ.get("SAHA_SPEAKER_TRANSACTION_TTL_SECONDS", "300"))
MAX_VOICE_UPLOAD_BYTES = 8 * 1024 * 1024
VOICE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
REFERENCE_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
ALLOWED_VOICE_MIME = frozenset({"audio/wav", "audio/x-wav", "audio/mp4", "audio/m4a", "audio/mpeg", "audio/aac", "audio/webm", "audio/ogg"})
NETWORK_PROBE_URL = os.environ.get("SAHA_MODEL_PROBE_URL", "https://www.baidu.com/")
STAGES: tuple[Stage, ...] = ("stt", "llm", "tts", "speaker")
CORE_STAGES: tuple[Stage, ...] = ("stt", "llm", "tts")


@dataclass(frozen=True)
class ArtifactSpec:
    url: str
    sha256: str
    filename: str
    size_bytes: int
    required_files: tuple[str, ...] = ()
    archive_root: str | None = None


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
    source: str | None = None
    license_notice: str | None = None
    compatible: bool = True
    download_available: bool = True
    compatibility_reason: str | None = None


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


OLLAMA_ADAPTER = AdapterSpec(
    "openai-compatible-chat",
    "ollama",
    (("base_url", "http://127.0.0.1:11434/v1"), ("keep_alive", "30m")),
)
FUNASR_ADAPTER = AdapterSpec(
    "funasr-paraformer-official-v0.2.10",
    "local-bundle",
    (
        ("model_path", "/models/stt/funasr-paraformer-zh"),
        ("warmup_audio_path", "/models/stt/funasr-paraformer-zh/example/asr_example.wav"),
        ("device", "cuda"),
    ),
)
SHERPA_STT_ADAPTER = AdapterSpec(
    "sherpa-onnx-paraformer",
    "local-bundle",
    (("model_path", "/models/stt"), ("num_threads", 4), ("provider", "cpu")),
)
SHERPA_VITS_ADAPTER = AdapterSpec(
    "sherpa-onnx-vits-zh",
    "local-bundle",
    (("model_path", "/models/tts"), ("num_threads", 4), ("provider", "cpu")),
)
COSYVOICE_ADAPTER = AdapterSpec(
    "cosyvoice3-official-sidecar",
    "cosyvoice-sidecar",
    (("base_url", "http://127.0.0.1:8766"), ("voice_id", "builtin-ruoban"), ("timeout_seconds", 60), ("model_path", "/models/tts/cosyvoice3/Fun-CosyVoice3-0.5B-2512")),
)
COSYVOICE_MODEL_ID = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
COSYVOICE_REVISION = "e0dfdde37d9a6acdc3cf92d51acfeea069003a9b"
COSYVOICE_HEALTH_URL = os.environ.get("SAHA_COSYVOICE_HEALTH_URL", "http://127.0.0.1:8766/health")
COSYVOICE_PREPROCESS_URL = os.environ.get("SAHA_COSYVOICE_PREPROCESS_URL", "http://127.0.0.1:8766/v1/voices/preprocess")
S2S_READY_URL = os.environ.get("SAHA_S2S_READY_URL", "http://127.0.0.1:8765/ready")
GROK_ENDPOINT = "https://api.roban.ai/v1"
GROK_MODEL = "grok-voice-latest"
QWEN_MODEL = "qwen-audio-3.0-realtime-flash"
QWEN_REGION = "cn-beijing"
PIPELINE_MODES = frozenset({"local", "realtime"})
REALTIME_PROVIDERS = frozenset({"qwen", "grok"})
WORKSPACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
PIPELINE_MUTATION_LOCK = threading.RLock()


class PipelineModeConflict(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.public_message = message


class PipelineModeServiceError(RuntimeError):
    pass


class PipelineModeRollbackError(PipelineModeServiceError):
    pass


MATCHA_ADAPTER = AdapterSpec(
    "sherpa-onnx-matcha-zh-en",
    "local-artifacts",
    (("model_path", "/models/tts/matcha-icefall-zh-en"), ("num_threads", 4), ("provider", "cpu")),
)
WESPEAKER_REVISION = "acf623ad8ca746e50baa432255cf8fc57c669c45"
WESPEAKER_FRONTEND_VERSION = "kaldi-fbank-hamming-v1"
WESPEAKER_SHA256 = "b50810498b5bcf5773d086f6993d344476bd0c88b566a41e8d801aaf8461efad"
WESPEAKER_ADAPTER = AdapterSpec(
    "wespeaker-campp-onnx",
    "local-external-artifact",
    (("model_path", "/models/speaker/wespeaker-campp/campplus.onnx"), ("model_version", f"{WESPEAKER_REVISION}+{WESPEAKER_FRONTEND_VERSION}"), ("provider", "cpu"), ("sample_rate", 16000), ("threshold", 0.65)),
)
TITANET_ADAPTER = AdapterSpec(
    "nemo-titanet-large",
    "local-external-artifact",
    (("model_path", "/models/speaker/titanet-large/titanet-large.nemo"), ("model_version", "external-unverified"), ("device", "cpu"), ("sample_rate", 16000)),
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
    ModelSpec(
        "sherpa-onnx-paraformer-zh",
        "stt",
        "Sherpa ONNX Paraformer 中文",
        "已验证的本地中文 Paraformer；低内存、低延迟，可与 FunASR 随时切换",
        "sherpa-onnx",
        SHERPA_STT_ADAPTER,
        ("zh",),
        "INT8",
        82_837_061,
        512_000_000,
        (ArtifactSpec("", "", "paraformer-bundle", 82_837_061, ("model.int8.onnx", "tokens.txt")),),
        "verified-orin-r39.2-cuda13.2",
    ),
    ModelSpec("qwen2.5:1.5b-instruct-q4_K_M", "llm", "Qwen 2.5 1.5B", "Orin 实测中文低延迟模型", "openai-compatible", OLLAMA_ADAPTER, ("zh", "en"), "Q4_K_M", 986_061_892, 1_500_000_000, (), "verified-orin-r39.2-cuda13.2"),
    ModelSpec(
        "cosyvoice3-0.5b-2512",
        "tts",
        "CosyVoice 3 官方 0.5B",
        f"官方 AutoModel FP16；固定 revision {COSYVOICE_REVISION[:12]}；仅限测试板实验使用",
        "cosyvoice",
        COSYVOICE_ADAPTER,
        ("zh", "en"),
        "FP16",
        11_767_984_206,
        9_000_000_000,
        (ArtifactSpec("", "", "snapshot", 11_767_984_206, ("REVISION", "manifest.sha256", "cosyvoice3.yaml", "llm.pt", "flow.pt", "hift.pt", "speech_tokenizer_v3.onnx", "CosyVoice-BlankEN/model.safetensors")),),
        "verified-test-board-orin-r39.2-cuda13.2",
        compatible=True,
        download_available=False,
        compatibility_reason=(
            f"Experimental test-board activation only: official revision {COSYVOICE_REVISION}; "
            "recursive manifest, CUDA cold start, sidecar lifecycle, synthesis, voice selection, and Sherpa rollback verified"
        ),
    ),
    ModelSpec(
        "sherpa-onnx-vits-zh",
        "tts",
        "Sherpa ONNX VITS 中文",
        "已验证的本地中文 VITS；Qwen3-TTS 在 stateful Code2Wav 正确性门禁通过前不对生产可见",
        "sherpa-onnx",
        SHERPA_VITS_ADAPTER,
        ("zh",),
        None,
        121_100_803,
        512_000_000,
        (ArtifactSpec("", "", "vits-bundle", 121_100_803, ("model.onnx", "tokens.txt", "lexicon.txt")),),
        "verified-orin-r39.2-cuda13.2",
    ),
    ModelSpec(
        "matcha-icefall-zh-en",
        "tts",
        "Matcha TTS 中英双语",
        "Matcha + Vocos 16 kHz；权重来源明确但模型专用许可不明确，仅在 Orin 门禁通过后开放",
        "sherpa-onnx",
        MATCHA_ADAPTER,
        ("zh", "en"),
        None,
        132_916_686,
        1_000_000_000,
        (
            ArtifactSpec(
                "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/matcha-icefall-zh-en.tar.bz2",
                "271b804af570400d3bcdcb53bf6e53cc9f75180ee763b9f13eb5eaf2b0d086ef",
                "matcha-icefall-zh-en.tar.bz2",
                79_033_838,
                ("model-steps-3.onnx", "lexicon.txt", "tokens.txt", "espeak-ng-data", "phone-zh.fst", "date-zh.fst", "number-zh.fst"),
                "matcha-icefall-zh-en",
            ),
            ArtifactSpec(
                "https://github.com/k2-fsa/sherpa-onnx/releases/download/vocoder-models/vocos-16khz-univ.onnx",
                "b599142a1fb8ff03de3e84ac35ff537c619e56f4267a6fe894851a42844acf9e",
                "vocos-16khz-univ.onnx",
                53_882_848,
                ("vocos-16khz-univ.onnx",),
            ),
        ),
        "verified-orin-r39.2-cuda13.2",
        "k2-fsa/sherpa-onnx release assets; acoustic weights originate from ModelScope dengcunqin/matcha_tts_zh_en_20251010",
        "Model-specific weight license is unclear. User accepted testing risk; do not represent as commercially cleared.",
    ),
    ModelSpec(
        "wespeaker-campp",
        "speaker",
        "WeSpeaker CAM++",
        "官方 VoxCeleb 16 kHz CAM++ ONNX；测试板实验声纹验证",
        "wespeaker",
        WESPEAKER_ADAPTER,
        ("zh",),
        None,
        29_292_449,
        256_000_000,
        (ArtifactSpec("https://hf-mirror.com/Wespeaker/wespeaker-voxceleb-campplus/resolve/acf623ad8ca746e50baa432255cf8fc57c669c45/voxceleb_CAM%2B%2B.onnx", WESPEAKER_SHA256, "campplus.onnx", 29_292_449, ("campplus.onnx",)),),
        "verified-test-board-experimental-threshold",
        f"Wespeaker/wespeaker-voxceleb-campplus revision {WESPEAKER_REVISION}",
        "Apache-2.0 model card and repository metadata; preserve attribution.",
        True,
        False,
        "Pre-provisioned official artifact; 0.65 is an experimental test-board threshold pending broader cohort calibration",
    ),
    ModelSpec(
        "titanet-large",
        "speaker",
        "NVIDIA TitaNet-Large",
        "NeMo TitaNet-Large；需要本地固定 checkpoint 和已验证的 Jetson NeMo 运行环境",
        "nemo",
        TITANET_ADAPTER,
        ("multi",),
        None,
        0,
        0,
        (ArtifactSpec("", "", "titanet-large.nemo", 0, ("titanet-large.nemo",)),),
        "external-artifact-required-incompatible",
        "NVIDIA NeMo TitaNet-Large; exact checkpoint revision, size, and SHA-256 are not yet verified locally",
        "Model is commonly documented as CC-BY-4.0; verify the exact checkpoint's model card and attribution before redistribution.",
        False,
        False,
        "pinned checkpoint metadata, NeMo/Jetson compatibility, and board validation are required",
    ),
)
BY_ID = {item.id: item for item in CATALOG}
ALLOWED = frozenset(BY_ID)
DOWNLOADS: dict[str, DownloadState] = {}
DOWNLOAD_LOCK = threading.RLock()
PAUSE_EVENTS: dict[str, threading.Event] = {}


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: Any, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            os.chmod(temporary, mode if mode is not None else (0o644 if path == SELECTION_PATH else 0o640))
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _durable_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(path.parent)


def serialized_pipeline_mutation(function):
    @functools.wraps(function)
    def locked(*args, **kwargs):
        with PIPELINE_MUTATION_LOCK:
            return function(*args, **kwargs)
    return locked


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
                if stage == "tts" and adapter == COSYVOICE_ADAPTER.name:
                    voice_id = config.get("voice_id")
                    if not isinstance(voice_id, str) or not VOICE_ID_PATTERN.fullmatch(voice_id):
                        continue
                    config = {key: item for key, item in config.items() if key != "voice_path"}
                stages[stage] = StageSelection(model_id, adapter, config)
        version = int(body.get("version", 1))
        if version not in {1, 2} or (version == 1 and "speaker" in stages):
            return PipelineSelection(1, {stage: selected for stage, selected in stages.items() if stage in CORE_STAGES})
        return PipelineSelection(version, stages)
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
    destination = _artifact_destination(spec)
    if not destination.is_dir() or not all((destination / required).is_file() for artifact in spec.artifacts for required in artifact.required_files):
        return False
    if spec.id == "cosyvoice3-0.5b-2512":
        try:
            if (destination / "REVISION").read_text(encoding="utf-8").strip() != COSYVOICE_REVISION:
                return False
            manifest = destination / "manifest.sha256"
            if not manifest.is_file():
                return False
            subprocess.run(["sha256sum", "-c", manifest.name], cwd=destination, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return False
    if spec.id == "wespeaker-campp":
        model = destination / "campplus.onnx"
        return model.stat().st_size == spec.disk_bytes and _sha256(model) == WESPEAKER_SHA256
    return True


def catalog_response() -> dict[str, Any]:
    stages = {stage: [] for stage in STAGES}
    for spec in CATALOG:
        stages[spec.stage].append({
            "id": spec.id, "stage": spec.stage, "label": spec.label, "description": spec.description,
            "backend": spec.backend, "adapter": spec.adapter.name, "languages": list(spec.languages),
            "quantization": spec.quantization, "diskBytes": spec.disk_bytes, "memoryBytes": spec.memory_bytes,
            "validationStatus": spec.validation_status, "source": spec.source, "licenseNotice": spec.license_notice,
            "compatible": spec.compatible, "downloadAvailable": spec.download_available,
            "compatibilityReason": spec.compatibility_reason,
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
                    "compatible": spec.compatible,
                    "downloadAvailable": spec.download_available,
                    "compatibilityReason": spec.compatibility_reason,
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
    ready = all(check["ready"] for check in checks if check["stage"] in CORE_STAGES)
    return {"status": "ready" if ready else "not_ready", "ready": ready, "checks": checks}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract_tar(archive: Path, destination: Path, archive_root: str | None) -> None:
    destination_resolved = destination.resolve()
    with tarfile.open(archive, mode="r:*") as source:
        members = source.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"unsafe tar member: {member.name}")
            target = (destination / Path(*path.parts)).resolve()
            if target != destination_resolved and destination_resolved not in target.parents:
                raise ValueError(f"tar member escapes destination: {member.name}")
        source.extractall(destination, members=members, filter="data")
    if archive_root:
        extracted_root = destination / archive_root
        if not extracted_root.is_dir():
            raise ValueError(f"archive root missing: {archive_root}")
        for child in extracted_root.iterdir():
            child.replace(destination / child.name)
        extracted_root.rmdir()


def _artifact_destination(spec: ModelSpec) -> Path:
    model_path = dict(spec.adapter.activation).get("model_path")
    if isinstance(model_path, str) and model_path.startswith("/models/"):
        relative = Path(model_path).relative_to("/models")
        required = {name for artifact in spec.artifacts for name in artifact.required_files}
        if relative.name in required:
            relative = relative.parent
        return MODEL_ROOT / relative
    return MODEL_ROOT / spec.stage / spec.id


def _validate_staged_artifacts(spec: ModelSpec, staged: Path) -> None:
    for artifact in spec.artifacts:
        for required in artifact.required_files:
            path = staged / required
            if not path.exists() or (path.is_file() and path.stat().st_size == 0):
                raise ValueError(f"required installed artifact missing: {required}")


def _download_artifact(spec: ModelSpec, artifact: ArtifactSpec, offset: int, total_bytes: int, pause: threading.Event) -> int:
    cache = STATE_ROOT / "artifacts" / spec.id
    cache.mkdir(parents=True, exist_ok=True)
    partial = cache / f"{artifact.filename}.part"
    completed = partial.stat().st_size if partial.is_file() else 0
    headers = {"Range": f"bytes={completed}-"} if completed else {}
    request = urllib.request.Request(artifact.url, headers=headers)
    started = time.monotonic()
    initial = completed
    with urllib.request.urlopen(request, timeout=60) as response:
        if completed and response.status != 206:
            completed = 0
            initial = 0
            partial.unlink(missing_ok=True)
        mode = "ab" if completed else "wb"
        with partial.open(mode) as output:
            while True:
                if pause.is_set():
                    raise InterruptedError("download paused")
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                completed += len(chunk)
                elapsed = max(time.monotonic() - started, 0.001)
                rate = max(completed - initial, 0) / elapsed
                aggregate = offset + completed
                set_download(
                    spec.id,
                    status="downloading",
                    bytes_completed=aggregate,
                    bytes_total=total_bytes,
                    bytes_per_second=rate,
                    eta_seconds=(total_bytes - aggregate) / rate if rate else None,
                    error=None,
                )
    if completed != artifact.size_bytes:
        raise ValueError(f"artifact size mismatch for {artifact.filename}: expected {artifact.size_bytes}, got {completed}")
    actual = _sha256(partial)
    if actual != artifact.sha256:
        raise ValueError(f"artifact SHA-256 mismatch for {artifact.filename}: expected {artifact.sha256}, got {actual}")
    return completed


def pull_artifact_model(model: str) -> None:
    spec = BY_ID[model]
    pause = PAUSE_EVENTS.setdefault(model, threading.Event())
    total_bytes = sum(artifact.size_bytes for artifact in spec.artifacts)
    staging = _artifact_destination(spec).with_name(f".{spec.id}.installing")
    try:
        completed = 0
        for artifact in spec.artifacts:
            completed += _download_artifact(spec, artifact, completed, total_bytes, pause)
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        cache = STATE_ROOT / "artifacts" / spec.id
        for artifact in spec.artifacts:
            downloaded = cache / f"{artifact.filename}.part"
            if artifact.archive_root:
                _safe_extract_tar(downloaded, staging, artifact.archive_root)
            else:
                shutil.copy2(downloaded, staging / artifact.filename)
        _validate_staged_artifacts(spec, staging)
        destination = _artifact_destination(spec)
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup = destination.with_name(f".{destination.name}.previous")
        shutil.rmtree(backup, ignore_errors=True)
        if destination.exists():
            destination.replace(backup)
        staging.replace(destination)
        shutil.rmtree(backup, ignore_errors=True)
        set_download(model, status="success", bytes_completed=total_bytes, bytes_total=total_bytes, bytes_per_second=0.0, eta_seconds=0.0, error=None)
    except InterruptedError:
        shutil.rmtree(staging, ignore_errors=True)
        set_download(model, status="paused", bytes_per_second=0.0, eta_seconds=None)
    except (OSError, ValueError, tarfile.TarError, urllib.error.URLError) as error:
        shutil.rmtree(staging, ignore_errors=True)
        set_download(model, status="error", bytes_per_second=0.0, eta_seconds=None, error=str(error))


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
    spec = BY_ID[model]
    if not spec.download_available:
        raise RuntimeError(spec.compatibility_reason or "model requires an externally supplied artifact")
    with DOWNLOAD_LOCK:
        current = DOWNLOADS.get(model)
        if current and current.status in {"starting", "downloading"}:
            return False
    PAUSE_EVENTS.setdefault(model, threading.Event()).clear()
    set_download(model, status="starting", error=None, bytes_per_second=0.0, eta_seconds=None)
    target = pull_ollama_model if BY_ID[model].adapter.protocol == "ollama" else pull_artifact_model
    threading.Thread(target=target, args=(model,), daemon=True, name=f"model-download-{model}").start()
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


def wait_ready(url: str, timeout: int, expected_mode: str | None = None, expected_generation: int | None = None, expected_provider: str | None = None) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body = json.load(response)
            ready = body.get("status") in {"ready", "ok"} or body.get("ready") is True
            if ready and expected_mode is not None:
                if (body.get("effectiveMode") != expected_mode or
                        body.get("effectiveProvider") != expected_provider or
                        body.get("effectiveGeneration") != expected_generation):
                    raise RuntimeError("S2S readiness does not match the requested pipeline provider generation")
            if ready:
                return body
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(2)
    raise RuntimeError(f"service did not become ready: {url}: {last_error}")


def _pipeline_config(mode: str, provider: str | None, generation: int) -> dict[str, Any]:
    return {"version": 2, "mode": mode, "provider": provider, "generation": generation}


def _normalize_pipeline_config(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise RuntimeError("persisted pipeline mode is invalid")
    generation = body.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise RuntimeError("persisted pipeline mode is invalid")
    if body.get("version") == 1:
        legacy_mode = body.get("mode")
        if legacy_mode == "local":
            return _pipeline_config("local", None, generation)
        if legacy_mode == "grok":
            return _pipeline_config("realtime", "grok", generation)
    if body.get("version") == 2:
        mode, provider = body.get("mode"), body.get("provider")
        if mode == "local" and provider is None:
            return _pipeline_config(mode, provider, generation)
        if mode == "realtime" and provider in REALTIME_PROVIDERS:
            return _pipeline_config(mode, provider, generation)
    raise RuntimeError("persisted pipeline mode is invalid")


def read_pipeline_mode() -> dict[str, Any]:
    try:
        return _normalize_pipeline_config(json.loads(PIPELINE_MODE_PATH.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return _pipeline_config("local", None, 0)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("persisted pipeline mode is invalid") from error


def _nonempty_regular_file(path: Path) -> bool:
    try:
        stat = path.stat()
        return path.is_file() and not path.is_symlink() and stat.st_size > 0 and not stat.st_mode & 0o027
    except OSError:
        return False


def token_configured() -> bool:
    return _nonempty_regular_file(S2S_TOKEN_PATH)


def qwen_key_configured() -> bool:
    return _nonempty_regular_file(DASHSCOPE_API_KEY_PATH)


def qwen_workspace_configured() -> bool:
    try:
        if not _nonempty_regular_file(DASHSCOPE_WORKSPACE_ID_PATH):
            return False
        workspace_id = DASHSCOPE_WORKSPACE_ID_PATH.read_text(encoding="utf-8")
        if workspace_id.endswith("\n"):
            workspace_id = workspace_id[:-1]
        return bool(WORKSPACE_ID_PATTERN.fullmatch(workspace_id))
    except OSError:
        return False


def provider_catalog() -> dict[str, dict[str, Any]]:
    qwen_configured = qwen_key_configured() and qwen_workspace_configured()
    return {
        "qwen": {
            "available": qwen_configured, "configured": qwen_configured,
            "reason": None if qwen_configured else "configuration_missing",
            "model": QWEN_MODEL, "region": QWEN_REGION, "label": "Qwen Realtime",
        },
        "grok": {
            "available": False, "configured": token_configured(),
            "reason": "balance_unavailable", "model": GROK_MODEL,
            "region": "global", "label": "Grok Voice",
        },
    }


def _safe_readiness_error(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    code, message = value.get("code"), value.get("message")
    if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", code):
        return None
    if not isinstance(message, str) or not 1 <= len(message) <= 256 or "http" in message.lower():
        return None
    return {"code": code, "message": message}


def _read_readiness_response() -> dict[str, Any]:
    try:
        with urllib.request.urlopen(S2S_READY_URL, timeout=5) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code != 503:
            raise
        return json.load(error)


def pipeline_mode_response() -> dict[str, Any]:
    configured = read_pipeline_mode()
    effective_mode = effective_provider = None
    effective_generation = None
    status = "error"
    error = None
    try:
        readiness = _read_readiness_response()
        candidate_mode = readiness.get("effectiveMode")
        candidate_provider = readiness.get("effectiveProvider")
        candidate_generation = readiness.get("effectiveGeneration")
        valid_provider = (candidate_mode == "local" and candidate_provider is None) or (candidate_mode == "realtime" and candidate_provider in REALTIME_PROVIDERS)
        if candidate_mode not in PIPELINE_MODES or not valid_provider or isinstance(candidate_generation, bool) or not isinstance(candidate_generation, int):
            raise RuntimeError("S2S readiness is missing effective pipeline provider generation")
        effective_mode, effective_provider, effective_generation = candidate_mode, candidate_provider, candidate_generation
        status = "ready" if readiness.get("ready") is True or readiness.get("status") in {"ready", "ok"} else "not_ready"
        error = _safe_readiness_error(readiness.get("error"))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, urllib.error.URLError):
        error = {"code": "readiness_unavailable", "message": "S2S readiness is unavailable or invalid"}
    return {
        "mode": configured["mode"], "provider": configured["provider"], "generation": configured["generation"],
        "effectiveMode": effective_mode, "effectiveProvider": effective_provider, "effectiveGeneration": effective_generation,
        "status": status, "error": error, "providers": provider_catalog(),
    }


def _load_pipeline_mode_transaction() -> dict[str, Any] | None:
    try:
        transaction = json.loads(PIPELINE_MODE_TRANSACTION_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("persisted pipeline mode transaction is invalid") from error
    if not isinstance(transaction, dict) or transaction.get("version") not in {1, 2}:
        raise RuntimeError("persisted pipeline mode transaction is invalid")
    old, replacement = transaction.get("old"), transaction.get("replacement")
    if transaction["version"] == 1:
        old = {"version": 1, **old} if isinstance(old, dict) else old
        replacement = {"version": 1, **replacement} if isinstance(replacement, dict) else replacement
    return {"version": 2, "old": _normalize_pipeline_config(old), "replacement": _normalize_pipeline_config(replacement)}


def _restart_for_pipeline_mode(configured: dict[str, Any], check: bool = True) -> None:
    run_s2s_command("restart", timeout=180)
    if check:
        wait_ready(S2S_READY_URL, 180, configured["mode"], configured["generation"], configured["provider"])


def _rollback_pipeline_mode(transaction: dict[str, Any]) -> None:
    old = _normalize_pipeline_config(transaction["old"])
    try:
        _atomic_json(PIPELINE_MODE_PATH, old)
        _restart_for_pipeline_mode(old)
        _durable_unlink(PIPELINE_MODE_TRANSACTION_PATH)
    except BaseException as error:
        try:
            run_s2s_command("restart", timeout=180)
        except (OSError, subprocess.SubprocessError):
            pass
        raise PipelineModeRollbackError("pipeline mode rollback failed") from error


def recover_pipeline_mode_transaction() -> None:
    with PIPELINE_MUTATION_LOCK:
        transaction = _load_pipeline_mode_transaction()
        if transaction is not None:
            _rollback_pipeline_mode(transaction)


@serialized_pipeline_mutation
def set_pipeline_mode(body: dict[str, Any]) -> dict[str, Any]:
    if body == {"mode": "local"}:
        requested_mode, requested_provider = "local", None
    elif body == {"mode": "realtime", "provider": "qwen"}:
        requested_mode, requested_provider = "realtime", "qwen"
    elif set(body) == {"mode", "provider"} and body.get("mode") == "realtime" and body.get("provider") == "grok":
        raise PipelineModeConflict("provider_unavailable", "Grok is unavailable because balance is unavailable")
    else:
        raise ValueError("request must be exactly {mode: local} or {mode: realtime, provider: qwen}")
    if requested_provider == "qwen" and not (qwen_key_configured() and qwen_workspace_configured()):
        raise PipelineModeConflict("configuration_missing", "Qwen key and workspace configuration are required")
    old = read_pipeline_mode()
    try:
        stored_version = json.loads(PIPELINE_MODE_PATH.read_text(encoding="utf-8")).get("version")
    except FileNotFoundError:
        stored_version = 2
    except (OSError, json.JSONDecodeError, AttributeError):
        stored_version = None
    if requested_mode == old["mode"] and requested_provider == old["provider"] and stored_version == 2:
        return pipeline_mode_response()
    replacement = _pipeline_config(requested_mode, requested_provider, old["generation"] + 1)
    transaction = {"version": 2, "old": old, "replacement": replacement}
    transaction_persisted = False
    try:
        _atomic_json(PIPELINE_MODE_TRANSACTION_PATH, transaction, mode=0o600)
        transaction_persisted = True
        _atomic_json(PIPELINE_MODE_PATH, replacement)
        _restart_for_pipeline_mode(replacement)
        _durable_unlink(PIPELINE_MODE_TRANSACTION_PATH)
    except PipelineModeRollbackError:
        raise
    except BaseException as error:
        if transaction_persisted:
            _rollback_pipeline_mode(transaction)
        raise PipelineModeServiceError("pipeline mode activation failed") from error
    return pipeline_mode_response()


def run_s2s_command(command: str, timeout: int = 360) -> None:
    subprocess.run(["saha-s2s", command], check=True, timeout=timeout)


def selection_uses_cosyvoice(selection: PipelineSelection) -> bool:
    selected = selection.stages.get("tts")
    return bool(selected and selected.adapter == COSYVOICE_ADAPTER.name)


def with_active_voice(selection: StageSelection) -> StageSelection:
    if selection.adapter != COSYVOICE_ADAPTER.name:
        return selection
    voices = voices_response()
    users = [voice["voiceId"] for voice in voices["voices"] if voice.get("kind") == "user"]
    active = voices.get("activeVoiceId")
    if active not in users:
        active = users[0] if users else None
    if not isinstance(active, str):
        raise RuntimeError("CosyVoice activation requires an installed user voice profile")
    return StageSelection(selection.model_id, selection.adapter, {**selection.config, "voice_id": active})


def prepare_cosy_voice(voice_id: str) -> None:
    reload_request = urllib.request.Request(
        COSYVOICE_PREPROCESS_URL.rsplit("/", 1)[0] + "/reload",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(reload_request, timeout=30):
        pass
    preprocess_request = urllib.request.Request(
        COSYVOICE_PREPROCESS_URL,
        data=json.dumps({"voice_id": voice_id}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(preprocess_request, timeout=120):
        pass


def restart_s2s(check: bool = True) -> None:
    try:
        run_s2s_command("restart", timeout=180)
    except (OSError, subprocess.SubprocessError):
        if check:
            raise
        return
    if check:
        wait_ready(S2S_READY_URL, 180)


@serialized_pipeline_mutation
def activate(spec: ModelSpec) -> None:
    if not spec.compatible:
        raise RuntimeError(spec.compatibility_reason or "model is not compatible with this release")
    if not model_installed(spec):
        raise RuntimeError("model is not installed")
    old = read_selection()
    old_uses_cosyvoice = selection_uses_cosyvoice(old)
    new_uses_cosyvoice = spec.adapter.protocol == "cosyvoice-sidecar" or (spec.stage != "tts" and old_uses_cosyvoice)
    sidecar_started = False
    selection_written = False
    try:
        if new_uses_cosyvoice and not old_uses_cosyvoice:
            sidecar_started = True
            run_s2s_command("cosy-start")
            health = wait_ready(COSYVOICE_HEALTH_URL, 300)
            if health.get("revision") != COSYVOICE_REVISION:
                raise RuntimeError("CosyVoice sidecar revision mismatch")

        stages = dict(old.stages)
        stages[spec.stage] = with_active_voice(selection_for(spec)) if spec.stage == "tts" else selection_for(spec)
        replacement = PipelineSelection(2 if "speaker" in stages else old.version, stages)
        if spec.stage == "tts" and spec.adapter.protocol == "cosyvoice-sidecar":
            prepare_cosy_voice(stages["tts"].config["voice_id"])

        _atomic_json(SELECTION_PATH, selection_dict(replacement))
        selection_written = True
        if spec.stage == "llm":
            LEGACY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = LEGACY_CONFIG_PATH.with_suffix(".tmp")
            temporary.write_text(f"ROBAN_S2S_LLM_MODEL={spec.id}\n", encoding="utf-8")
            os.chmod(temporary, 0o640)
            temporary.replace(LEGACY_CONFIG_PATH)
        restart_s2s()
    except BaseException:
        if selection_written:
            _atomic_json(SELECTION_PATH, selection_dict(old))
            try:
                restart_s2s()
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass
        if sidecar_started and not old_uses_cosyvoice:
            try:
                run_s2s_command("cosy-stop")
            except (OSError, subprocess.SubprocessError):
                pass
        raise

    if old_uses_cosyvoice and not selection_uses_cosyvoice(replacement):
        run_s2s_command("cosy-stop")


def _speaker_threshold(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("threshold must be a finite number between 0 and 1")
    threshold = float(value)
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be a finite number between 0 and 1")
    return threshold


def _speaker_default_threshold() -> float:
    return _speaker_threshold(dict(WESPEAKER_ADAPTER.activation)["threshold"])


def _runtime_speaker_profile() -> dict[str, Any]:
    request = urllib.request.Request(S2S_SPEAKER_PROFILE_URL, method="GET")
    deadline = time.monotonic() + 30
    while True:
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = json.load(response)
            break
        except (urllib.error.URLError, OSError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    if not isinstance(body, dict):
        raise RuntimeError("S2S returned an invalid speaker profile response")
    profile = body.get("profile", body)
    if not isinstance(profile, dict):
        raise RuntimeError("S2S returned an invalid speaker profile response")
    enrolled = profile.get("enrolled")
    model_id = profile.get("modelId", profile.get("model_id"))
    model_version = profile.get("modelVersion", profile.get("model_version"))
    profile_id = profile.get("profileId", profile.get("profile_id"))
    if not isinstance(enrolled, bool):
        raise RuntimeError("S2S speaker profile uses an unsupported legacy response")
    if enrolled:
        if not isinstance(model_id, str) or not model_id or not isinstance(model_version, str) or not model_version:
            raise RuntimeError("S2S speaker profile uses an unsupported legacy response")
        if not isinstance(profile_id, str) or not profile_id:
            raise RuntimeError("S2S enrolled speaker profile is missing profileId")
    else:
        if model_id is not None and (not isinstance(model_id, str) or not model_id):
            raise RuntimeError("S2S returned an invalid speaker modelId")
        if model_version is not None and (not isinstance(model_version, str) or not model_version):
            raise RuntimeError("S2S returned an invalid speaker modelVersion")
        if profile_id is not None and (not isinstance(profile_id, str) or not profile_id):
            raise RuntimeError("S2S returned an invalid speaker profileId")
    result: dict[str, Any] = {"profileId": profile_id, "modelId": model_id, "modelVersion": model_version, "enrolled": enrolled}
    created_at = profile.get("createdAt", profile.get("created_at"))
    if isinstance(created_at, str) and created_at:
        result["createdAt"] = created_at
    elif isinstance(created_at, (int, float)) and not isinstance(created_at, bool) and math.isfinite(float(created_at)):
        result["createdAt"] = float(created_at)
    return result


def _selection_from_dict(body: Any) -> PipelineSelection:
    if not isinstance(body, dict) or not isinstance(body.get("stages"), dict):
        raise RuntimeError("persisted speaker transaction has an invalid old selection")
    stages: dict[Stage, StageSelection] = {}
    for stage, value in body["stages"].items():
        if stage not in STAGES or not isinstance(value, dict):
            raise RuntimeError("persisted speaker transaction has an invalid old selection")
        model_id, adapter, config = value.get("modelId"), value.get("adapter"), value.get("config")
        if not isinstance(model_id, str) or not isinstance(adapter, str) or not isinstance(config, dict):
            raise RuntimeError("persisted speaker transaction has an invalid old selection")
        stages[stage] = StageSelection(model_id, adapter, config)
    version = body.get("version")
    if not isinstance(version, int):
        raise RuntimeError("persisted speaker transaction has an invalid old selection")
    return PipelineSelection(version, stages)


def _load_speaker_transaction() -> dict[str, Any] | None:
    try:
        transaction = json.loads(SPEAKER_TRANSACTION_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("persisted speaker transaction is invalid") from error
    if not isinstance(transaction, dict):
        raise RuntimeError("persisted speaker transaction is invalid")
    _selection_from_dict(transaction.get("oldSelection"))
    return transaction


def _rollback_speaker_transaction(transaction: dict[str, Any]) -> None:
    old = _selection_from_dict(transaction.get("oldSelection"))
    _atomic_json(SELECTION_PATH, selection_dict(old))
    try:
        restart_s2s()
    except BaseException:
        restart_s2s(check=False)
        raise
    SPEAKER_TRANSACTION_PATH.unlink(missing_ok=True)


def _read_speaker_transaction(now: float | None = None) -> dict[str, Any] | None:
    transaction = _load_speaker_transaction()
    if transaction is None:
        return None
    if float(transaction.get("expiresAt", 0)) <= (time.time() if now is None else now):
        _rollback_speaker_transaction(transaction)
        return None
    return transaction


@serialized_pipeline_mutation
def speaker_status(now: float | None = None) -> dict[str, Any]:
    transaction = _read_speaker_transaction(now)
    selected = read_selection().stages.get("speaker")
    configured = selected.config.get("threshold") if selected else None
    threshold = _speaker_threshold(configured) if configured is not None else None
    if transaction:
        state = "pending_enrollment"
    elif selected:
        profile = _runtime_speaker_profile()
        state = "enforcing" if profile["enrolled"] else "pending_enrollment"
    else:
        state = "disabled"
    result: dict[str, Any] = {"status": state, "configuredThreshold": threshold, "defaultThreshold": _speaker_default_threshold()}
    if transaction:
        result["transaction"] = {key: transaction[key] for key in ("transactionId", "modelId", "threshold", "createdAt", "expiresAt")}
    return result


def _profile_identity(profile: dict[str, Any]) -> dict[str, Any] | None:
    if not profile["enrolled"]:
        return None
    return {key: profile[key] for key in ("profileId", "modelId", "modelVersion", "createdAt") if key in profile}


@serialized_pipeline_mutation
def prepare_speaker(body: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    if _read_speaker_transaction(now):
        raise RuntimeError("a speaker enrollment transaction is already pending")
    model_id = body.get("modelId", "wespeaker-campp")
    spec = BY_ID.get(model_id) if isinstance(model_id, str) else None
    if not spec or spec.stage != "speaker" or not spec.compatible:
        raise ValueError("modelId must identify a compatible speaker model")
    if not model_installed(spec):
        raise RuntimeError("speaker model is not installed")
    threshold = _speaker_threshold(body.get("threshold", dict(spec.adapter.activation).get("threshold", _speaker_default_threshold())))
    old = read_selection()
    previous_profile = _runtime_speaker_profile()
    if previous_profile["modelId"] != spec.id or previous_profile["modelVersion"] != dict(spec.adapter.activation).get("model_version"):
        previous_identity = None
    else:
        previous_identity = _profile_identity(previous_profile)
    created_at = time.time() if now is None else now
    transaction = {
        "version": 1, "transactionId": uuid.uuid4().hex, "modelId": spec.id, "threshold": threshold,
        "previousProfile": previous_identity, "oldSelection": selection_dict(old),
        "createdAt": created_at, "expiresAt": created_at + SPEAKER_TRANSACTION_TTL_SECONDS,
    }
    _atomic_json(SPEAKER_TRANSACTION_PATH, transaction, mode=0o600)
    selected = selection_for(spec)
    selected = StageSelection(selected.model_id, selected.adapter, {**selected.config, "threshold": threshold, "enrollment_pending": True})
    try:
        _write_speaker_selection(old, selected)
    except BaseException:
        SPEAKER_TRANSACTION_PATH.unlink(missing_ok=True)
        raise
    return {key: transaction[key] for key in ("transactionId", "modelId", "threshold", "createdAt", "expiresAt")}


@serialized_pipeline_mutation
def abort_speaker(transaction_id: str | None = None, now: float | None = None) -> bool:
    transaction = _read_speaker_transaction(now)
    if not transaction:
        return False
    if transaction_id is not None and transaction_id != transaction.get("transactionId"):
        raise ValueError("transactionId does not match the pending speaker transaction")
    _rollback_speaker_transaction(transaction)
    return True


def _write_speaker_selection(old: PipelineSelection, selected: StageSelection | None) -> None:
    stages = dict(old.stages)
    if selected is None:
        stages.pop("speaker", None)
    else:
        stages["speaker"] = selected
    replacement = PipelineSelection(2 if "speaker" in stages else 1, stages)
    _atomic_json(SELECTION_PATH, selection_dict(replacement))
    try:
        restart_s2s()
    except BaseException:
        _atomic_json(SELECTION_PATH, selection_dict(old))
        restart_s2s(check=False)
        raise


@serialized_pipeline_mutation
def commit_speaker(transaction_id: str, now: float | None = None) -> dict[str, Any]:
    transaction = _read_speaker_transaction(now)
    if not transaction:
        raise RuntimeError("speaker enrollment transaction is missing or expired")
    if transaction_id != transaction.get("transactionId"):
        raise ValueError("transactionId does not match the pending speaker transaction")
    current_profile = _runtime_speaker_profile()
    spec = BY_ID[transaction["modelId"]]
    expected_version = dict(spec.adapter.activation).get("model_version")
    if not current_profile["enrolled"] or current_profile["modelId"] != spec.id or current_profile["modelVersion"] != expected_version:
        raise RuntimeError("S2S speaker profile is not enrolled for the prepared model")
    old = read_selection()
    pending = old.stages.get("speaker")
    if not pending or pending.model_id != spec.id:
        raise RuntimeError("speaker enrollment selection is no longer active")
    config = {key: value for key, value in pending.config.items() if key not in {"enrollment_pending", "enabled", "profile"}}
    config["threshold"] = _speaker_threshold(transaction["threshold"])
    _write_speaker_selection(old, StageSelection(pending.model_id, pending.adapter, config))
    SPEAKER_TRANSACTION_PATH.unlink(missing_ok=True)
    return speaker_status(now)


@serialized_pipeline_mutation
def update_speaker_threshold(value: Any) -> dict[str, Any]:
    threshold = _speaker_threshold(value)
    old = read_selection()
    selected = old.stages.get("speaker")
    if not selected:
        raise RuntimeError("speaker profile is not configured")
    replacement = StageSelection(selected.model_id, selected.adapter, {**selected.config, "threshold": threshold})
    _write_speaker_selection(old, replacement)
    return speaker_status()


@serialized_pipeline_mutation
def deactivate_speaker() -> None:
    old = read_selection()
    if "speaker" not in old.stages:
        return
    _write_speaker_selection(old, None)


def _voice_profile(voice_id: str) -> dict[str, Any]:
    if not VOICE_ID_PATTERN.fullmatch(voice_id):
        raise ValueError("invalid voiceId")
    directory = VOICE_ROOT / voice_id
    try:
        profile = json.loads((directory / "profile.json").read_text(encoding="utf-8"))
        wav = directory / "reference.wav"
        if not wav.is_file() or profile.get("voiceId") != voice_id or profile.get("wavSha256") != _sha256(wav):
            raise ValueError("voice profile integrity check failed")
        return profile
    except (FileNotFoundError, OSError, json.JSONDecodeError) as error:
        raise ValueError("voice profile does not exist") from error


def voices_response() -> dict[str, Any]:
    voices = []
    if VOICE_ROOT.is_dir():
        for directory in sorted(VOICE_ROOT.iterdir()):
            if not directory.is_dir() or not VOICE_ID_PATTERN.fullmatch(directory.name):
                continue
            try:
                profile = _voice_profile(directory.name)
                voices.append({key: profile.get(key) for key in ("voiceId", "name", "kind", "promptText", "durationSeconds", "source", "replaceable", "createdAt")})
            except ValueError:
                continue
    selection = read_selection().stages.get("tts")
    active = selection.config.get("voice_id") if selection and selection.adapter == COSYVOICE_ADAPTER.name else None
    return {"version": 1, "activeVoiceId": active, "voices": voices}


def stage_voice_upload(content_type: str, payload: bytes) -> dict[str, Any]:
    if content_type not in ALLOWED_VOICE_MIME:
        raise ValueError("unsupported reference audio MIME type")
    if not payload or len(payload) > MAX_VOICE_UPLOAD_BYTES:
        raise ValueError("reference audio must contain 1 byte to 8 MiB")
    request = urllib.request.Request(S2S_TRANSCRIBE_URL, data=payload, headers={"Content-Type": content_type}, method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.load(response)
    reference_id = str(result.get("referenceId", ""))
    if not REFERENCE_ID_PATTERN.fullmatch(reference_id):
        raise RuntimeError("S2S returned an invalid referenceId")
    return result


def create_voice(body: dict[str, Any]) -> dict[str, Any]:
    reference_id = str(body.get("referenceId", ""))
    if not REFERENCE_ID_PATTERN.fullmatch(reference_id):
        raise ValueError("invalid referenceId")
    name = str(body.get("name", "")).strip()
    prompt_text = str(body.get("promptText", "")).strip()
    if not 1 <= len(name) <= 40 or not 1 <= len(prompt_text) <= 500:
        raise ValueError("name must be 1-40 characters and promptText 1-500 characters")
    source = VOICE_TEMP_ROOT / f"{reference_id}.wav"
    if not source.is_file() or source.is_symlink():
        raise ValueError("reference has expired or does not exist")
    voice_id = f"user-{hashlib.sha256((reference_id + name).encode()).hexdigest()[:16]}"
    staging = VOICE_ROOT / f".{voice_id}.installing"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(mode=0o750, parents=True)
    shutil.copy2(source, staging / "reference.wav")
    os.chmod(staging / "reference.wav", 0o640)
    import wave
    with wave.open(str(staging / "reference.wav"), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000 or not 5 <= duration <= 10:
            raise ValueError("reference must be canonical 5-10 second 16 kHz mono PCM16 WAV")
    profile = {"version": 1, "voiceId": voice_id, "name": name, "kind": "user", "promptText": prompt_text, "durationSeconds": round(duration, 3), "wavSha256": _sha256(staging / "reference.wav"), "source": "user-recording", "replaceable": False, "createdAt": int(time.time())}
    _atomic_json(staging / "profile.json", profile)
    os.chmod(staging / "profile.json", 0o640)
    destination = VOICE_ROOT / voice_id
    if destination.exists():
        raise ValueError("voice profile already exists")
    staging.replace(destination)
    source.unlink(missing_ok=True)
    return profile


@serialized_pipeline_mutation
def select_voice(voice_id: str) -> dict[str, Any]:
    profile = _voice_profile(voice_id)
    selection = read_selection()
    tts = selection.stages.get("tts")
    if not tts or tts.adapter != COSYVOICE_ADAPTER.name:
        raise RuntimeError("CosyVoice must be the active TTS before selecting a voice")
    stages = dict(selection.stages)
    stages["tts"] = StageSelection(tts.model_id, tts.adapter, {**tts.config, "voice_id": voice_id})
    try:
        prepare_cosy_voice(voice_id)
        _atomic_json(SELECTION_PATH, selection_dict(PipelineSelection(selection.version, stages)))
        restart_s2s()
    except BaseException:
        _atomic_json(SELECTION_PATH, selection_dict(selection))
        restart_s2s(check=False)
        raise
    return profile


def delete_voice(voice_id: str) -> None:
    profile = _voice_profile(voice_id)
    if profile.get("kind") == "builtin":
        raise ValueError("built-in voice cannot be deleted")
    active = voices_response()["activeVoiceId"]
    if active == voice_id:
        raise RuntimeError("active voice cannot be deleted")
    shutil.rmtree(VOICE_ROOT / voice_id)


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
            match = re.fullmatch(r"/v1/voices/([a-z0-9][a-z0-9._-]{0,63})/preview", self.path)
            if match:
                profile = _voice_profile(match.group(1))
                payload = (VOICE_ROOT / profile["voiceId"] / "reference.wav").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(payload)
                return
            routes = {
                "/health": lambda: {"status": "ok"}, "/v1/catalog": catalog_response,
                "/v1/models/status": models_status, "/v1/models": legacy_model_status,
                "/v1/pipeline/readiness": pipeline_readiness, "/v1/pipeline/mode": pipeline_mode_response,
                "/v1/network/status": network_status, "/v1/voices": voices_response,
                "/v1/speaker/status": speaker_status,
            }
            function = routes.get(self.path)
            self.send_json(200, function()) if function else self.send_json(404, {"error": "not found"})
        except (OSError, urllib.error.URLError, ValueError) as error:
            self.send_json(503, {"error": str(error)})

    def do_POST(self) -> None:
        try:
            if self.path == "/v1/voices/upload":
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                length = int(self.headers.get("Content-Length", "0"))
                if length > MAX_VOICE_UPLOAD_BYTES:
                    self.send_json(413, {"error": "reference audio exceeds 8 MiB"})
                    return
                self.send_json(200, stage_voice_upload(content_type, self.rfile.read(length)))
                return
            body = self.read_json()
            if self.path == "/v1/pipeline/mode":
                self.send_json(200, set_pipeline_mode(body))
                return
            if self.path == "/v1/voices":
                self.send_json(201, create_voice(body))
                return
            if self.path == "/v1/voices/select":
                self.send_json(200, select_voice(str(body.get("voiceId", ""))))
                return
            if self.path == "/v1/voices/delete":
                delete_voice(str(body.get("voiceId", "")))
                self.send_json(200, {"status": "deleted"})
                return
            if self.path in {"/v1/speaker/setup/prepare", "/v1/speaker/prepare"}:
                self.send_json(201, prepare_speaker(body))
                return
            if self.path in {"/v1/speaker/setup/commit", "/v1/speaker/commit"}:
                transaction_id = body.get("transactionId")
                if not isinstance(transaction_id, str) or not transaction_id:
                    raise ValueError("transactionId is required")
                self.send_json(200, commit_speaker(transaction_id))
                return
            if self.path in {"/v1/speaker/setup/abort", "/v1/speaker/abort"}:
                transaction_id = body.get("transactionId")
                if transaction_id is not None and not isinstance(transaction_id, str):
                    raise ValueError("transactionId must be a string")
                self.send_json(200, {"status": "aborted", "aborted": abort_speaker(transaction_id)})
                return
            if self.path == "/v1/speaker/threshold":
                self.send_json(200, update_speaker_threshold(body.get("threshold")))
                return
            if self.path == "/v1/speaker/deactivate" or (self.path == "/v1/models/deactivate" and body.get("stage") == "speaker"):
                deactivate_speaker()
                self.send_json(200, speaker_status())
                return
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
        except PipelineModeConflict as error:
            self.send_json(409, {"error": {"code": error.code, "message": error.public_message}})
        except PipelineModeRollbackError:
            self.send_json(503, {"error": {"code": "pipeline_mode_rollback_failed", "message": "Pipeline mode rollback failed"}})
        except PipelineModeServiceError:
            self.send_json(503, {"error": {"code": "pipeline_mode_activation_failed", "message": "Pipeline mode activation failed"}})
        except RuntimeError as error:
            self.send_json(409, {"error": str(error)})
        except (OSError, subprocess.SubprocessError, urllib.error.URLError) as error:
            self.send_json(503, {"error": str(error)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"saha-s2s-model-manager: {format % args}", flush=True)


def restore_selected_sidecars() -> None:
    if selection_uses_cosyvoice(read_selection()):
        run_s2s_command("cosy-start")
        health = wait_ready(COSYVOICE_HEALTH_URL, 300)
        if health.get("revision") != COSYVOICE_REVISION:
            run_s2s_command("cosy-stop")
            raise RuntimeError("selected CosyVoice revision does not match the pinned release")


def main() -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    VOICE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chmod(VOICE_ROOT, 0o750)
    VOICE_TEMP_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    for stage in STAGES:
        (MODEL_ROOT / stage).mkdir(parents=True, exist_ok=True)
    recover_pipeline_mode_transaction()
    interrupted = load_downloads()
    for model in interrupted:
        start_download(model)
    restore_selected_sidecars()
    address = os.environ.get("SAHA_MODEL_MANAGER_HOST", os.environ.get("SAHA_OLLAMA_MANAGER_HOST", "0.0.0.0"))
    port = int(os.environ.get("SAHA_MODEL_MANAGER_PORT", os.environ.get("SAHA_OLLAMA_MANAGER_PORT", "11435")))
    ThreadingHTTPServer((address, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
