import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("saha-ollama-manager.py")
SPEC = importlib.util.spec_from_file_location("saha_ollama_manager", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
import sys
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ModelManagerTest(unittest.TestCase):
    def setUp(self):
        MODULE.DOWNLOADS.clear()
        MODULE.PAUSE_EVENTS.clear()

    def test_catalog_is_immutable_allowlisted_and_stage_grouped(self):
        self.assertIsInstance(MODULE.CATALOG, tuple)
        self.assertEqual({item.id for item in MODULE.CATALOG}, MODULE.ALLOWED)
        catalog = MODULE.catalog_response()
        self.assertEqual({"stt", "llm", "tts", "speaker"}, set(catalog["stages"]))
        self.assertEqual(["funasr-paraformer-zh", "sherpa-onnx-paraformer-zh"], [item["id"] for item in catalog["stages"]["stt"]])
        self.assertEqual("funasr-paraformer-official-v0.2.10", catalog["stages"]["stt"][0]["adapter"])
        self.assertEqual("sherpa-onnx-paraformer", catalog["stages"]["stt"][1]["adapter"])
        self.assertEqual(["qwen2.5:1.5b-instruct-q4_K_M"], [item["id"] for item in catalog["stages"]["llm"]])
        self.assertEqual(["cosyvoice3-0.5b-2512", "sherpa-onnx-vits-zh", "matcha-icefall-zh-en"], [item["id"] for item in catalog["stages"]["tts"]])
        cosyvoice = catalog["stages"]["tts"][0]
        self.assertEqual("cosyvoice3-official-sidecar", cosyvoice["adapter"])
        self.assertEqual("verified-test-board-orin-r39.2-cuda13.2", cosyvoice["validationStatus"])
        self.assertTrue(cosyvoice["compatible"])
        self.assertFalse(cosyvoice["downloadAvailable"])
        self.assertIn(MODULE.COSYVOICE_REVISION, cosyvoice["compatibilityReason"])
        self.assertEqual("sherpa-onnx-vits-zh", catalog["stages"]["tts"][1]["adapter"])
        matcha = catalog["stages"]["tts"][2]
        self.assertEqual("sherpa-onnx-matcha-zh-en", matcha["adapter"])
        self.assertEqual("verified-orin-r39.2-cuda13.2", matcha["validationStatus"])
        self.assertIn("license is unclear", matcha["licenseNotice"])
        self.assertEqual(["wespeaker-campp", "titanet-large"], [item["id"] for item in catalog["stages"]["speaker"]])
        self.assertTrue(catalog["stages"]["speaker"][0]["compatible"])
        self.assertFalse(catalog["stages"]["speaker"][0]["downloadAvailable"])
        self.assertTrue(all(not item["downloadAvailable"] for item in catalog["stages"]["speaker"]))
        self.assertTrue(all(item["validationStatus"] == "verified-orin-r39.2-cuda13.2" for stage in (catalog["stages"]["stt"], catalog["stages"]["llm"]) for item in stage))
        with self.assertRaises(ValueError):
            MODULE.require_model({"modelId": "arbitrary/model:latest"})

    def test_empty_selection_is_not_ready_without_ollama(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "SELECTION_PATH", Path(directory) / "missing.json"), patch.object(MODULE, "LEGACY_CONFIG_PATH", Path(directory) / "missing.env"), patch.object(MODULE, "installed_ollama_models", return_value=set()):
            readiness = MODULE.pipeline_readiness()
        self.assertFalse(readiness["ready"])
        self.assertEqual("not_ready", readiness["status"])
        self.assertEqual(["not_selected"] * 4, [check["reason"] for check in readiness["checks"]])

    def test_wespeaker_profile_version_binds_official_frontend_contract(self):
        config = dict(MODULE.WESPEAKER_ADAPTER.activation)
        self.assertEqual(
            f"{MODULE.WESPEAKER_REVISION}+{MODULE.WESPEAKER_FRONTEND_VERSION}",
            config["model_version"],
        )

    def test_version_two_selection_accepts_optional_speaker(self):
        selection = MODULE.PipelineSelection(
            2,
            {
                "llm": MODULE.selection_for(MODULE.BY_ID["qwen2.5:1.5b-instruct-q4_K_M"]),
                "speaker": MODULE.selection_for(MODULE.BY_ID["wespeaker-campp"]),
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selection.json"
            path.write_text(json.dumps(MODULE.selection_dict(selection)))
            with patch.object(MODULE, "SELECTION_PATH", path):
                loaded = MODULE.read_selection()
        self.assertEqual(2, loaded.version)
        self.assertEqual("wespeaker-campp", loaded.stages["speaker"].model_id)

    def test_version_one_selection_ignores_speaker_stage(self):
        selection = MODULE.PipelineSelection(
            1,
            {
                "llm": MODULE.selection_for(MODULE.BY_ID["qwen2.5:1.5b-instruct-q4_K_M"]),
                "speaker": MODULE.selection_for(MODULE.BY_ID["wespeaker-campp"]),
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selection.json"
            path.write_text(json.dumps(MODULE.selection_dict(selection)))
            with patch.object(MODULE, "SELECTION_PATH", path):
                loaded = MODULE.read_selection()
        self.assertEqual(1, loaded.version)
        self.assertNotIn("speaker", loaded.stages)

    def test_speaker_is_not_part_of_core_pipeline_readiness(self):
        selection = MODULE.PipelineSelection(
            1,
            {stage: MODULE.selection_for(next(spec for spec in MODULE.CATALOG if spec.stage == stage)) for stage in MODULE.CORE_STAGES},
        )
        with patch.object(MODULE, "read_selection", return_value=selection), patch.object(MODULE, "model_installed", return_value=True), patch.object(MODULE, "installed_ollama_models", return_value=set()):
            readiness = MODULE.pipeline_readiness()
        self.assertTrue(readiness["ready"])
        self.assertEqual(list(MODULE.STAGES), [check["stage"] for check in readiness["checks"]])
        self.assertFalse(readiness["checks"][-1]["ready"])

    def test_wespeaker_is_preprovisioned_and_cannot_download(self):
        spec = MODULE.BY_ID["wespeaker-campp"]
        with self.assertRaisesRegex(RuntimeError, "Pre-provisioned"):
            MODULE.start_download(spec.id)
        self.assertTrue(spec.compatible)
        self.assertEqual(MODULE.WESPEAKER_SHA256, spec.artifacts[0].sha256)

    def test_selection_is_atomic_and_legacy_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            selection = Path(directory) / "selection.json"
            legacy = Path(directory) / "ollama.env"
            with patch.object(MODULE, "SELECTION_PATH", selection), patch.object(MODULE, "LEGACY_CONFIG_PATH", legacy), patch.object(MODULE, "model_installed", return_value=True), patch.object(MODULE, "wait_ready", return_value={"ready": True}), patch.object(MODULE.subprocess, "run"):
                MODULE.activate(MODULE.BY_ID["qwen2.5:1.5b-instruct-q4_K_M"])
                self.assertEqual("qwen2.5:1.5b-instruct-q4_K_M", MODULE.active_model())
            self.assertEqual(
                {
                    "version": 1,
                    "stages": {
                        "llm": {
                            "modelId": "qwen2.5:1.5b-instruct-q4_K_M",
                            "adapter": "openai-compatible-chat",
                            "config": {
                                "base_url": "http://127.0.0.1:11434/v1",
                                "keep_alive": "30m",
                                "model": "qwen2.5:1.5b-instruct-q4_K_M",
                            },
                        }
                    },
                },
                json.loads(selection.read_text()),
            )
            self.assertEqual("ROBAN_S2S_LLM_MODEL=qwen2.5:1.5b-instruct-q4_K_M\n", legacy.read_text())
            self.assertEqual(0o644, selection.stat().st_mode & 0o777)

    def test_pipeline_mode_v1_reads_as_v2_preserving_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pipeline-mode.json"
            for persisted, expected in (
                ({"version": 1, "mode": "local", "generation": 7}, {"version": 2, "mode": "local", "provider": None, "generation": 7}),
                ({"version": 1, "mode": "grok", "generation": 8}, {"version": 2, "mode": "realtime", "provider": "grok", "generation": 8}),
            ):
                path.write_text(json.dumps(persisted))
                with patch.object(MODULE, "PIPELINE_MODE_PATH", path):
                    self.assertEqual(expected, MODULE.read_pipeline_mode())

    def test_pipeline_mode_missing_defaults_qwen_realtime_without_token_disclosure(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            MODULE, "PIPELINE_MODE_PATH", Path(directory) / "missing.json"
        ), patch.object(MODULE, "S2S_TOKEN_PATH", Path(directory) / "missing.token"), patch.object(
            MODULE.urllib.request, "urlopen", side_effect=OSError("offline")
        ):
            response = MODULE.pipeline_mode_response()
        self.assertEqual("realtime", response["mode"])
        self.assertEqual(0, response["generation"])
        self.assertEqual("qwen", response["provider"])
        self.assertEqual({"qwen", "grok"}, set(response["providers"]))
        self.assertEqual(MODULE.QWEN_MODEL, response["providers"]["qwen"]["model"])
        self.assertEqual(MODULE.QWEN_REGION, response["providers"]["qwen"]["region"])
        self.assertEqual("qwen-audio-3.0-realtime-flash", response["providers"]["qwen"]["model"])
        self.assertEqual("balance_unavailable", response["providers"]["grok"]["reason"])
        self.assertNotIn("token", json.dumps(response).lower())
        self.assertNotIn("workspaceurl", json.dumps(response).lower())

    def test_pipeline_mode_readiness_error_is_sanitized(self):
        secret_detail = "https://private.invalid/path?token=secret"
        with tempfile.TemporaryDirectory() as directory, patch.object(
            MODULE, "PIPELINE_MODE_PATH", Path(directory) / "missing.json"
        ), patch.object(MODULE, "S2S_TOKEN_PATH", Path(directory) / "missing.token"), patch.object(
            MODULE.urllib.request, "urlopen", side_effect=OSError(secret_detail)
        ):
            response = MODULE.pipeline_mode_response()
        self.assertEqual(
            {"code": "readiness_unavailable", "message": "S2S readiness is unavailable or invalid"},
            response["error"],
        )
        self.assertNotIn(secret_detail, json.dumps(response))

    def test_token_configured_uses_metadata_without_reading_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "sub2api.token"
            token.write_bytes(b"secret-that-must-not-be-read-or-returned")
            token.chmod(0o600)
            with patch.object(MODULE, "S2S_TOKEN_PATH", token), patch.object(
                Path, "read_bytes", side_effect=AssertionError("token contents must not be read")
            ), patch.object(Path, "read_text", side_effect=AssertionError("token contents must not be read")):
                self.assertTrue(MODULE.token_configured())

    def test_pipeline_mode_accepts_only_exact_mode_schema(self):
        for body in ({}, {"mode": "other"}, {"mode": "local", "provider": None}, {"mode": "local", "token": "secret"}, {"mode": "realtime"}, {"mode": "realtime", "provider": "unknown"}, {"mode": "realtime", "provider": "qwen", "endpoint": "https://evil.invalid"}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                MODULE.set_pipeline_mode(body)
        with self.assertRaises(MODULE.PipelineModeConflict) as raised:
            MODULE.set_pipeline_mode({"mode": "realtime", "provider": "grok"})
        self.assertEqual("provider_unavailable", raised.exception.code)

    def test_qwen_requires_independent_safe_operator_files_without_state_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mode = root / "pipeline-mode.json"
            mode.write_text(json.dumps({"version": 2, "mode": "local", "provider": None, "generation": 3}))
            key, workspace = root / "key", root / "workspace"
            with patch.object(MODULE, "PIPELINE_MODE_PATH", mode), patch.object(MODULE, "DASHSCOPE_API_KEY_PATH", key), patch.object(MODULE, "DASHSCOPE_WORKSPACE_ID_PATH", workspace):
                with self.assertRaises(MODULE.PipelineModeConflict):
                    MODULE.set_pipeline_mode({"mode": "realtime", "provider": "qwen"})
                self.assertEqual(3, json.loads(mode.read_text())["generation"])
                key.write_text("secret")
                key.chmod(0o600)
                for invalid in ("bad.name", "bad/name", "bad:name", "bad%name", "bad name", "_bad", "a" * 129):
                    workspace.write_text(invalid)
                    workspace.chmod(0o600)
                    self.assertFalse(MODULE.qwen_workspace_configured())
                workspace.write_text("ws_real_123")
                workspace.chmod(0o644)
                self.assertFalse(MODULE.qwen_workspace_configured())
                workspace.chmod(0o600)
                self.assertTrue(MODULE.qwen_workspace_configured())

    def test_pipeline_mode_structured_503_retains_effective_fields_and_safe_error(self):
        readiness = {"status": "not_ready", "ready": False, "effectiveMode": "realtime", "effectiveProvider": "qwen", "effectiveGeneration": 4, "error": {"code": "provider_connecting", "message": "Provider is connecting"}}
        with patch.object(MODULE, "read_pipeline_mode", return_value={"version": 2, "mode": "realtime", "provider": "qwen", "generation": 4}), patch.object(MODULE, "_read_readiness_response", return_value=readiness), patch.object(MODULE, "provider_catalog", return_value={}):
            response = MODULE.pipeline_mode_response()
        self.assertEqual("qwen", response["effectiveProvider"])
        self.assertEqual(4, response["effectiveGeneration"])
        self.assertEqual("not_ready", response["status"])
        self.assertEqual(readiness["error"], response["error"])

    def test_pipeline_mode_switch_persists_generation_and_validates_effective_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key, workspace = root / "dashscope-api-key", root / "dashscope-workspace-id"
            key.write_text("operator-secret\n")
            workspace.write_text("ws_real_123\n")
            key.chmod(0o600)
            workspace.chmod(0o600)
            mode = root / "pipeline-mode.json"
            transaction = root / "pipeline-mode-transaction.json"
            with patch.object(MODULE, "PIPELINE_MODE_PATH", mode), patch.object(
                MODULE, "PIPELINE_MODE_TRANSACTION_PATH", transaction
            ), patch.object(MODULE, "DASHSCOPE_API_KEY_PATH", key), patch.object(
                MODULE, "DASHSCOPE_WORKSPACE_ID_PATH", workspace
            ), patch.object(MODULE, "run_s2s_command") as restart, patch.object(
                MODULE, "wait_ready", return_value={"ready": True}
            ) as ready, patch.object(MODULE, "pipeline_mode_response", return_value={"mode": "realtime", "provider": "qwen", "generation": 1}):
                response = MODULE.set_pipeline_mode({"mode": "realtime", "provider": "qwen"})
            persisted = json.loads(mode.read_text())
        self.assertEqual({"mode": "realtime", "provider": "qwen", "generation": 1}, response)
        self.assertEqual({"version": 2, "mode": "realtime", "provider": "qwen", "generation": 1}, persisted)
        self.assertFalse(transaction.exists())
        restart.assert_called_once_with("restart", timeout=180)
        ready.assert_called_once_with(MODULE.S2S_READY_URL, 180, "realtime", 1, "qwen")

    def test_pipeline_mode_failed_effective_validation_rolls_back_and_restarts_old_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mode = root / "pipeline-mode.json"
            mode.write_text(json.dumps({"version": 1, "mode": "local", "generation": 4}))
            transaction = root / "pipeline-mode-transaction.json"
            key, workspace = root / "dashscope-api-key", root / "dashscope-workspace-id"
            key.write_text("operator-secret")
            workspace.write_text("ws_real_123")
            key.chmod(0o600)
            workspace.chmod(0o600)
            with patch.object(MODULE, "PIPELINE_MODE_PATH", mode), patch.object(
                MODULE, "PIPELINE_MODE_TRANSACTION_PATH", transaction
            ), patch.object(MODULE, "DASHSCOPE_API_KEY_PATH", key), patch.object(
                MODULE, "DASHSCOPE_WORKSPACE_ID_PATH", workspace
            ), patch.object(MODULE, "_restart_for_pipeline_mode", side_effect=[RuntimeError("mismatch with secret URL"), None]) as restart:
                with self.assertRaisesRegex(MODULE.PipelineModeServiceError, "activation failed") as raised:
                    MODULE.set_pipeline_mode({"mode": "realtime", "provider": "qwen"})
                self.assertNotIn("secret URL", str(raised.exception))
            persisted = json.loads(mode.read_text())
        self.assertEqual({"version": 2, "mode": "local", "provider": None, "generation": 4}, persisted)
        self.assertFalse(transaction.exists())
        self.assertEqual("qwen", restart.call_args_list[0].args[0]["provider"])
        self.assertEqual("local", restart.call_args_list[1].args[0]["mode"])

    def test_pipeline_mode_crash_recovery_rolls_back_persisted_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mode = root / "pipeline-mode.json"
            mode.write_text(json.dumps({"version": 1, "mode": "grok", "generation": 2}))
            transaction = root / "pipeline-mode-transaction.json"
            transaction.write_text(json.dumps({
                "version": 1,
                "old": {"mode": "local", "generation": 1},
                "replacement": {"mode": "grok", "generation": 2},
            }))
            with patch.object(MODULE, "PIPELINE_MODE_PATH", mode), patch.object(
                MODULE, "PIPELINE_MODE_TRANSACTION_PATH", transaction
            ), patch.object(MODULE, "_restart_for_pipeline_mode") as restart:
                MODULE.recover_pipeline_mode_transaction()
            persisted = json.loads(mode.read_text())
        self.assertEqual({"version": 2, "mode": "local", "provider": None, "generation": 1}, persisted)
        self.assertFalse(transaction.exists())
        restart.assert_called_once_with({"version": 2, "mode": "local", "provider": None, "generation": 1})

    def test_pipeline_mutations_share_one_process_wide_lock(self):
        functions = (
            MODULE.set_pipeline_mode,
            MODULE.activate,
            MODULE.prepare_speaker,
            MODULE.speaker_status,
            MODULE.abort_speaker,
            MODULE.commit_speaker,
            MODULE.update_speaker_threshold,
            MODULE.deactivate_speaker,
            MODULE.select_voice,
        )
        for function in functions:
            with self.subTest(function=function.__name__):
                self.assertIsNotNone(getattr(function, "__wrapped__", None))

        entered = threading.Event()
        finished = threading.Event()

        @MODULE.serialized_pipeline_mutation
        def mutation():
            entered.set()
            finished.set()

        MODULE.PIPELINE_MUTATION_LOCK.acquire()
        try:
            thread = threading.Thread(target=mutation)
            thread.start()
            time.sleep(0.02)
            self.assertFalse(entered.is_set())
        finally:
            MODULE.PIPELINE_MUTATION_LOCK.release()
        thread.join(timeout=1)
        self.assertTrue(finished.is_set())

    def test_atomic_json_fsyncs_file_and_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch.object(MODULE.os, "fsync", wraps=MODULE.os.fsync) as fsync:
                MODULE._atomic_json(path, {"value": 1})
            self.assertEqual({"value": 1}, json.loads(path.read_text()))
            self.assertGreaterEqual(fsync.call_count, 2)

    def test_cosyvoice_activation_starts_sidecar_and_checks_revision(self):
        old = MODULE.PipelineSelection(1, {"tts": MODULE.selection_for(MODULE.BY_ID["sherpa-onnx-vits-zh"])})
        commands = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "SELECTION_PATH", Path(directory) / "selection.json"), patch.object(MODULE, "read_selection", return_value=old), patch.object(MODULE, "model_installed", return_value=True), patch.object(MODULE, "voices_response", return_value={"activeVoiceId": "user-test", "voices": [{"voiceId": "user-test", "kind": "user"}]}), patch.object(MODULE, "run_s2s_command", side_effect=lambda command, timeout=360: commands.append(command)), patch.object(MODULE, "wait_ready", side_effect=[{"status": "ok", "revision": MODULE.COSYVOICE_REVISION}, {"ready": True}]), patch.object(MODULE.urllib.request, "urlopen", return_value=Response()), patch.object(MODULE.subprocess, "run"):
            MODULE.activate(MODULE.BY_ID["cosyvoice3-0.5b-2512"])
        self.assertEqual(["cosy-start", "restart"], commands)

    def test_cosyvoice_activation_requires_user_voice_and_stops_new_sidecar(self):
        old = MODULE.PipelineSelection(1, {"tts": MODULE.selection_for(MODULE.BY_ID["sherpa-onnx-vits-zh"])})
        commands = []
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "SELECTION_PATH", Path(directory) / "selection.json"), patch.object(MODULE, "read_selection", return_value=old), patch.object(MODULE, "model_installed", return_value=True), patch.object(MODULE, "voices_response", return_value={"activeVoiceId": None, "voices": []}), patch.object(MODULE, "run_s2s_command", side_effect=lambda command, timeout=360: commands.append(command)), patch.object(MODULE, "wait_ready", return_value={"status": "ok", "revision": MODULE.COSYVOICE_REVISION}):
            with self.assertRaisesRegex(RuntimeError, "user voice"):
                MODULE.activate(MODULE.BY_ID["cosyvoice3-0.5b-2512"])
        self.assertEqual(["cosy-start", "cosy-stop"], commands)

    def test_cosyvoice_preprocess_failure_does_not_write_selection(self):
        old = MODULE.PipelineSelection(1, {"tts": MODULE.selection_for(MODULE.BY_ID["sherpa-onnx-vits-zh"])})
        commands = []
        with patch.object(MODULE, "read_selection", return_value=old), patch.object(MODULE, "model_installed", return_value=True), patch.object(MODULE, "voices_response", return_value={"activeVoiceId": "user-test", "voices": [{"voiceId": "user-test", "kind": "user"}]}), patch.object(MODULE, "run_s2s_command", side_effect=lambda command, timeout=360: commands.append(command)), patch.object(MODULE, "wait_ready", return_value={"status": "ok", "revision": MODULE.COSYVOICE_REVISION}), patch.object(MODULE, "prepare_cosy_voice", side_effect=OSError("preprocess failed")), patch.object(MODULE, "_atomic_json") as atomic:
            with self.assertRaisesRegex(OSError, "preprocess failed"):
                MODULE.activate(MODULE.BY_ID["cosyvoice3-0.5b-2512"])
        atomic.assert_not_called()
        self.assertEqual(["cosy-start", "cosy-stop"], commands)

    def test_cosyvoice_s2s_failure_restores_selection_and_old_runtime(self):
        old = MODULE.PipelineSelection(1, {"tts": MODULE.selection_for(MODULE.BY_ID["sherpa-onnx-vits-zh"])})
        commands = []
        with patch.object(MODULE, "read_selection", return_value=old), patch.object(MODULE, "model_installed", return_value=True), patch.object(MODULE, "voices_response", return_value={"activeVoiceId": "user-test", "voices": [{"voiceId": "user-test", "kind": "user"}]}), patch.object(MODULE, "run_s2s_command", side_effect=lambda command, timeout=360: commands.append(command)), patch.object(MODULE, "wait_ready", return_value={"status": "ok", "revision": MODULE.COSYVOICE_REVISION}), patch.object(MODULE, "prepare_cosy_voice"), patch.object(MODULE, "_atomic_json") as atomic, patch.object(MODULE, "restart_s2s", side_effect=[RuntimeError("s2s failed"), None]) as restart:
            with self.assertRaisesRegex(RuntimeError, "s2s failed"):
                MODULE.activate(MODULE.BY_ID["cosyvoice3-0.5b-2512"])
        self.assertEqual(MODULE.selection_dict(old), atomic.call_args_list[-1].args[1])
        self.assertEqual(2, restart.call_count)
        self.assertEqual(["cosy-start", "cosy-stop"], commands)

    def test_switching_away_stops_cosyvoice_after_s2s_ready(self):
        old = MODULE.PipelineSelection(1, {"tts": MODULE.selection_for(MODULE.BY_ID["cosyvoice3-0.5b-2512"])})
        commands = []
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "SELECTION_PATH", Path(directory) / "selection.json"), patch.object(MODULE, "read_selection", return_value=old), patch.object(MODULE, "model_installed", return_value=True), patch.object(MODULE, "run_s2s_command", side_effect=lambda command, timeout=360: commands.append(command)), patch.object(MODULE, "wait_ready", return_value={"ready": True}), patch.object(MODULE.subprocess, "run"):
            MODULE.activate(MODULE.BY_ID["sherpa-onnx-vits-zh"])
        self.assertEqual(["restart", "cosy-stop"], commands)

    def test_persisted_inflight_download_is_scheduled_to_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            tasks = Path(directory) / "downloads.json"
            tasks.write_text(json.dumps({"version": 1, "downloads": {"qwen2.5:1.5b-instruct-q4_K_M": {"status": "downloading", "bytesCompleted": 42, "bytesTotal": 100}}}))
            with patch.object(MODULE, "TASKS_PATH", tasks):
                interrupted = MODULE.load_downloads()
            state = MODULE.DOWNLOADS["qwen2.5:1.5b-instruct-q4_K_M"]
            self.assertEqual(["qwen2.5:1.5b-instruct-q4_K_M"], interrupted)
            self.assertEqual("paused", state.status)
            self.assertEqual(42, state.bytes_completed)

    def test_status_survives_unavailable_ollama(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "SELECTION_PATH", Path(directory) / "missing.json"), patch.object(MODULE, "LEGACY_CONFIG_PATH", Path(directory) / "missing.env"), patch.object(MODULE, "installed_ollama_models", return_value=set()):
            status = MODULE.models_status()
        self.assertIsNone(status["stages"]["llm"]["activeModel"])
        self.assertTrue(all(not item["installed"] for item in status["stages"]["llm"]["models"]))
        compatible_core = [
            item
            for stage_name, stage in status["stages"].items()
            if stage_name in MODULE.CORE_STAGES
            for item in stage["models"]
            if item["id"] != "cosyvoice3-0.5b-2512"
        ]
        self.assertTrue(all(item["compatible"] for item in compatible_core))
        self.assertTrue(next(item for item in status["stages"]["tts"]["models"] if item["id"] == "cosyvoice3-0.5b-2512")["compatible"])
        self.assertTrue(next(item for item in status["stages"]["speaker"]["models"] if item["id"] == "wespeaker-campp")["compatible"])

    def test_status_marks_selected_local_adapters_compatible(self):
        selection = MODULE.PipelineSelection(
            1,
            {
                "stt": MODULE.selection_for(MODULE.BY_ID["funasr-paraformer-zh"]),
                "tts": MODULE.selection_for(MODULE.BY_ID["sherpa-onnx-vits-zh"]),
            },
        )
        with patch.object(MODULE, "read_selection", return_value=selection), patch.object(MODULE, "model_installed", return_value=True), patch.object(MODULE, "installed_ollama_models", return_value=set()):
            status = MODULE.models_status()
        self.assertTrue(status["stages"]["stt"]["models"][0]["compatible"])
        self.assertTrue(status["stages"]["stt"]["models"][1]["compatible"])
        self.assertTrue(status["stages"]["tts"]["models"][0]["compatible"])
        self.assertTrue(status["stages"]["tts"]["models"][1]["compatible"])

    def test_voice_profile_integrity_and_selection_only_persist_voice_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            voices = root / "voices"
            voice = voices / "user-test"
            voice.mkdir(parents=True)
            wav = voice / "reference.wav"
            wav.write_bytes(b"RIFF-test")
            profile = {"version": 1, "voiceId": "user-test", "name": "测试", "kind": "user", "promptText": "测试文本", "durationSeconds": 6, "wavSha256": MODULE._sha256(wav), "source": "user-recording", "replaceable": False, "createdAt": 1}
            (voice / "profile.json").write_text(json.dumps(profile))
            selection = MODULE.PipelineSelection(1, {"tts": MODULE.StageSelection("cosyvoice3-0.5b-2512", MODULE.COSYVOICE_ADAPTER.name, {"base_url": "http://127.0.0.1:8766", "voice_id": "user-test"})})
            with patch.object(MODULE, "VOICE_ROOT", voices), patch.object(MODULE, "read_selection", return_value=selection):
                response = MODULE.voices_response()
            self.assertEqual("user-test", response["activeVoiceId"])
            self.assertNotIn("path", json.dumps(MODULE.selection_dict(selection)))
            (voice / "reference.wav").write_bytes(b"tampered")
            with patch.object(MODULE, "VOICE_ROOT", voices):
                with self.assertRaisesRegex(ValueError, "integrity"):
                    MODULE._voice_profile("user-test")

    def test_voice_upload_accepts_audio_mpeg_into_decode_path(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        request = None

        def urlopen(captured, timeout):
            nonlocal request
            request = captured
            self.assertEqual(120, timeout)
            return Response()

        with patch.object(MODULE.urllib.request, "urlopen", side_effect=urlopen), patch.object(
            MODULE.json, "load", return_value={"referenceId": "a" * 32}
        ):
            result = MODULE.stage_voice_upload("audio/mpeg", b"encoded-audio")

        self.assertEqual("a" * 32, result["referenceId"])
        self.assertEqual("audio/mpeg", request.headers["Content-type"])
        self.assertEqual(b"encoded-audio", request.data)

    def test_forged_audio_mpeg_is_rejected_by_decode_path(self):
        with patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=MODULE.urllib.error.HTTPError(
                MODULE.S2S_TRANSCRIBE_URL, 400, "audio decode failed", {}, None
            ),
        ):
            with self.assertRaises(MODULE.urllib.error.HTTPError) as raised:
                MODULE.stage_voice_upload("audio/mpeg", b"not audio")
        self.assertEqual(400, raised.exception.code)

    def test_voice_upload_rejects_mime_size_and_path_ids(self):
        with self.assertRaisesRegex(ValueError, "MIME"):
            MODULE.stage_voice_upload("application/octet-stream", b"x")
        with self.assertRaisesRegex(ValueError, "8 MiB"):
            MODULE.stage_voice_upload("audio/wav", b"x" * (MODULE.MAX_VOICE_UPLOAD_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "voiceId"):
            MODULE._voice_profile("../../etc/passwd")

    def test_voice_selection_reloads_sidecar_and_rolls_back_runtime(self):
        old = MODULE.PipelineSelection(1, {"tts": MODULE.StageSelection("cosyvoice3-0.5b-2512", MODULE.COSYVOICE_ADAPTER.name, {"voice_id": "builtin-ruoban"})})
        profile = {"voiceId": "user-test"}
        opened = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def urlopen(request, timeout):
            opened.append((request.full_url, timeout))
            if request.full_url.endswith("/preprocess"):
                raise OSError("preprocess failed")
            return Response()

        with patch.object(MODULE, "read_selection", return_value=old), patch.object(MODULE, "_voice_profile", return_value=profile), patch.object(MODULE, "_atomic_json") as atomic, patch.object(MODULE.urllib.request, "urlopen", side_effect=urlopen), patch.object(MODULE, "run_s2s_command") as run:
            with self.assertRaisesRegex(OSError, "preprocess failed"):
                MODULE.select_voice("user-test")

        self.assertTrue(opened[0][0].endswith("/v1/voices/reload"))
        self.assertTrue(opened[1][0].endswith("/v1/voices/preprocess"))
        self.assertEqual(MODULE.selection_dict(old), atomic.call_args_list[-1].args[1])
        run.assert_called_once_with("restart", timeout=180)

    def test_speaker_prepare_persists_old_selection_and_activates_pending_gate(self):
        old = MODULE.PipelineSelection(1, {"llm": MODULE.selection_for(MODULE.BY_ID["qwen2.5:1.5b-instruct-q4_K_M"])})
        runtime = {"profileId": None, "modelId": "wespeaker-campp", "modelVersion": dict(MODULE.WESPEAKER_ADAPTER.activation)["model_version"], "enrolled": False}
        captured = []
        with tempfile.TemporaryDirectory() as directory:
            transaction_path = Path(directory) / "speaker-transaction.json"
            with patch.object(MODULE, "SPEAKER_TRANSACTION_PATH", transaction_path), patch.object(
                MODULE, "model_installed", return_value=True
            ), patch.object(MODULE, "read_selection", return_value=old), patch.object(
                MODULE, "_runtime_speaker_profile", return_value=runtime
            ), patch.object(MODULE, "_write_speaker_selection", side_effect=lambda previous, selected: captured.append((previous, selected))), patch.object(
                MODULE.uuid, "uuid4", return_value=type("Uuid", (), {"hex": "transaction-1"})()
            ):
                prepared = MODULE.prepare_speaker({"modelId": "wespeaker-campp", "threshold": 0.0}, now=100)
            transaction = json.loads(transaction_path.read_text())
            transaction_mode = transaction_path.stat().st_mode & 0o777
        self.assertEqual("transaction-1", prepared["transactionId"])
        self.assertEqual(MODULE.selection_dict(old), transaction["oldSelection"])
        self.assertIsNone(transaction["previousProfile"])
        self.assertEqual(0o600, transaction_mode)
        self.assertTrue(captured[0][1].config["enrollment_pending"])
        self.assertEqual(0.0, captured[0][1].config["threshold"])
        self.assertNotIn("profile", captured[0][1].config)

    def test_speaker_abort_and_expiry_restore_old_selection_and_restart(self):
        old = MODULE.PipelineSelection(1, {"llm": MODULE.selection_for(MODULE.BY_ID["qwen2.5:1.5b-instruct-q4_K_M"])})
        transaction = {"version": 1, "transactionId": "tx", "modelId": "wespeaker-campp", "threshold": 0.65, "previousProfile": None, "oldSelection": MODULE.selection_dict(old), "createdAt": 1, "expiresAt": 9}
        for expired in (False, True):
            with self.subTest(expired=expired), tempfile.TemporaryDirectory() as directory:
                transaction_path = Path(directory) / "speaker-transaction.json"
                selection_path = Path(directory) / "selection.json"
                transaction_path.write_text(json.dumps(transaction))
                with patch.object(MODULE, "SPEAKER_TRANSACTION_PATH", transaction_path), patch.object(
                    MODULE, "SELECTION_PATH", selection_path
                ), patch.object(MODULE, "restart_s2s") as restart:
                    if expired:
                        self.assertEqual("disabled", MODULE.speaker_status(now=10)["status"])
                    else:
                        self.assertTrue(MODULE.abort_speaker("tx", now=2))
                self.assertEqual(MODULE.selection_dict(old), json.loads(selection_path.read_text()))
                self.assertFalse(transaction_path.exists())
                restart.assert_called_once_with()

    def test_speaker_status_requires_an_enrolled_runtime_profile_to_enforce(self):
        selected = MODULE.StageSelection("wespeaker-campp", MODULE.WESPEAKER_ADAPTER.name, {"threshold": 0.65})
        selection = MODULE.PipelineSelection(2, {"speaker": selected})
        with patch.object(MODULE, "read_selection", return_value=selection), patch.object(
            MODULE, "_read_speaker_transaction", return_value=None
        ), patch.object(MODULE, "_runtime_speaker_profile", return_value={
            "enrolled": False,
            "profileId": None,
            "modelId": "wespeaker-campp",
            "modelVersion": "v1",
        }):
            self.assertEqual("pending_enrollment", MODULE.speaker_status()["status"])

    def test_speaker_threshold_accepts_boundaries_and_rejects_non_finite_values(self):
        self.assertEqual(0.0, MODULE._speaker_threshold(0))
        self.assertEqual(1.0, MODULE._speaker_threshold(1))
        for value in (-0.01, 1.01, float("nan"), float("inf"), True, "0.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MODULE._speaker_threshold(value)

    def test_speaker_commit_keeps_only_catalog_config_and_threshold(self):
        old = MODULE.PipelineSelection(2, {"speaker": MODULE.StageSelection("wespeaker-campp", MODULE.WESPEAKER_ADAPTER.name, {**dict(MODULE.WESPEAKER_ADAPTER.activation), "threshold": 1.0, "enrollment_pending": True})})
        runtime = {"profileId": "speaker-1", "modelId": "wespeaker-campp", "modelVersion": dict(MODULE.WESPEAKER_ADAPTER.activation)["model_version"], "enrolled": True, "createdAt": 101.0}
        transaction = {"version": 1, "transactionId": "tx", "modelId": "wespeaker-campp", "threshold": 1.0, "previousProfile": None, "oldSelection": {"version": 1, "stages": {}}, "createdAt": 100, "expiresAt": 400}
        captured = []
        with tempfile.TemporaryDirectory() as directory:
            transaction_path = Path(directory) / "speaker-transaction.json"
            transaction_path.write_text(json.dumps(transaction))
            with patch.object(MODULE, "SPEAKER_TRANSACTION_PATH", transaction_path), patch.object(
                MODULE, "_runtime_speaker_profile", return_value=runtime
            ), patch.object(MODULE, "read_selection", return_value=old), patch.object(
                MODULE, "_write_speaker_selection", side_effect=lambda previous, selected: captured.append(selected)
            ), patch.object(MODULE, "speaker_status", return_value={"status": "enforcing"}):
                status = MODULE.commit_speaker("tx", now=101)
        self.assertEqual("enforcing", status["status"])
        self.assertFalse(transaction_path.exists())
        self.assertEqual(1.0, captured[0].config["threshold"])
        self.assertNotIn("enrollment_pending", captured[0].config)
        self.assertNotIn("profile", captured[0].config)
        self.assertNotIn("embedding", json.dumps(captured[0].config))

    def test_speaker_commit_allows_existing_matching_profile_retry(self):
        version = dict(MODULE.WESPEAKER_ADAPTER.activation)["model_version"]
        identity = {"profileId": "existing", "modelId": "wespeaker-campp", "modelVersion": version, "createdAt": 50.0}
        runtime = {**identity, "enrolled": True}
        pending = MODULE.PipelineSelection(2, {"speaker": MODULE.StageSelection("wespeaker-campp", MODULE.WESPEAKER_ADAPTER.name, {**dict(MODULE.WESPEAKER_ADAPTER.activation), "enrollment_pending": True})})
        transaction = {"version": 1, "transactionId": "retry", "modelId": "wespeaker-campp", "threshold": 0.65, "previousProfile": identity, "oldSelection": {"version": 1, "stages": {}}, "createdAt": 100, "expiresAt": 400}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transaction.json"
            path.write_text(json.dumps(transaction))
            with patch.object(MODULE, "SPEAKER_TRANSACTION_PATH", path), patch.object(MODULE, "_runtime_speaker_profile", return_value=runtime), patch.object(MODULE, "read_selection", return_value=pending), patch.object(MODULE, "_write_speaker_selection"), patch.object(MODULE, "speaker_status", return_value={"status": "enforcing"}):
                MODULE.commit_speaker("retry", now=101)
        self.assertFalse(path.exists())

    def test_speaker_selection_rolls_back_when_restart_fails(self):
        old = MODULE.PipelineSelection(1, {})
        selected = MODULE.StageSelection("wespeaker-campp", MODULE.WESPEAKER_ADAPTER.name, {"threshold": 0.7})
        with patch.object(MODULE, "_atomic_json") as atomic, patch.object(
            MODULE, "restart_s2s", side_effect=[RuntimeError("restart failed"), None]
        ) as restart:
            with self.assertRaisesRegex(RuntimeError, "restart failed"):
                MODULE._write_speaker_selection(old, selected)
        self.assertEqual(MODULE.selection_dict(old), atomic.call_args_list[-1].args[1])
        self.assertEqual(2, restart.call_count)

    def test_speaker_threshold_update_and_deactivate_remove_stage(self):
        speaker = MODULE.StageSelection("wespeaker-campp", MODULE.WESPEAKER_ADAPTER.name, {"threshold": 0.65})
        old = MODULE.PipelineSelection(2, {"speaker": speaker})
        captured = []
        with patch.object(MODULE, "read_selection", return_value=old), patch.object(
            MODULE, "_write_speaker_selection", side_effect=lambda _old, selected: captured.append(selected)
        ), patch.object(MODULE, "speaker_status", return_value={"status": "enforcing"}):
            MODULE.update_speaker_threshold(0.25)
            MODULE.deactivate_speaker()
        self.assertEqual(0.25, captured[0].config["threshold"])
        self.assertIsNone(captured[1])

    def test_runtime_profile_contract_accepts_disabled_response_without_model_identity(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        body = {"enabled": False, "enrolled": False, "model_id": None, "model_version": None}
        with patch.object(MODULE.urllib.request, "urlopen", return_value=Response()), patch.object(
            MODULE.json, "load", return_value=body
        ):
            self.assertEqual(
                {"profileId": None, "modelId": None, "modelVersion": None, "enrolled": False},
                MODULE._runtime_speaker_profile(),
            )

    def test_runtime_profile_contract_rejects_embedding_only_legacy_response(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch.object(MODULE.urllib.request, "urlopen", return_value=Response()), patch.object(
            MODULE.json, "load", return_value={"profileId": "old", "embedding": [0.1]}
        ):
            with self.assertRaisesRegex(RuntimeError, "legacy response"):
                MODULE._runtime_speaker_profile()

    def test_download_state_has_rate_and_eta_contract(self):
        state = MODULE.DownloadState("qwen2.5:1.5b-instruct-q4_K_M", "downloading", 50, 100, 25.0, 2.0)
        body = MODULE._state_dict(state)
        self.assertEqual(25.0, body["bytesPerSecond"])
        self.assertEqual(2.0, body["etaSeconds"])

    def test_safe_tar_extract_rejects_traversal_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, configure in (
                ("traversal.tar", lambda item: setattr(item, "name", "../escape")),
                ("link.tar", lambda item: (setattr(item, "type", tarfile.SYMTYPE), setattr(item, "linkname", "/etc/passwd"))),
            ):
                archive = root / name
                with tarfile.open(archive, "w") as output:
                    item = tarfile.TarInfo("file")
                    item.size = 1
                    configure(item)
                    output.addfile(item, io.BytesIO(b"x"))
                with self.assertRaises(ValueError):
                    MODULE._safe_extract_tar(archive, root / "out", None)

    def test_artifact_download_checks_sha_and_installs_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(b"vocoder")
            artifact = MODULE.ArtifactSpec(source.as_uri(), hashlib.sha256(b"vocoder").hexdigest(), "vocos.onnx", 7, ("vocos.onnx",))
            spec = MODULE.ModelSpec("test-local", "tts", "Test", "Test", "sherpa-onnx", MODULE.AdapterSpec("test", "local-artifacts", (("model_path", "/models/tts/test-local"),)), ("zh",), None, 7, 1, (artifact,), "hidden")
            with patch.dict(MODULE.BY_ID, {spec.id: spec}), patch.object(MODULE, "STATE_ROOT", root / "state"), patch.object(MODULE, "TASKS_PATH", root / "state" / "downloads.json"), patch.object(MODULE, "MODEL_ROOT", root / "models"):
                MODULE.pull_artifact_model(spec.id)
                destination = root / "models" / "tts" / "test-local" / "vocos.onnx"
                self.assertEqual(b"vocoder", destination.read_bytes())
                self.assertEqual("success", MODULE.DOWNLOADS[spec.id].status)

    def test_artifact_download_rejects_bad_sha_without_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(b"bad")
            artifact = MODULE.ArtifactSpec(source.as_uri(), "0" * 64, "model.onnx", 3, ("model.onnx",))
            spec = MODULE.ModelSpec("test-bad", "tts", "Test", "Test", "sherpa-onnx", MODULE.AdapterSpec("test", "local-artifacts", ()), ("zh",), None, 3, 1, (artifact,), "hidden")
            with patch.dict(MODULE.BY_ID, {spec.id: spec}), patch.object(MODULE, "STATE_ROOT", root / "state"), patch.object(MODULE, "TASKS_PATH", root / "state" / "downloads.json"), patch.object(MODULE, "MODEL_ROOT", root / "models"):
                MODULE.pull_artifact_model(spec.id)
                self.assertEqual("error", MODULE.DOWNLOADS[spec.id].status)
                self.assertFalse((root / "models" / "tts" / "test-bad").exists())


if __name__ == "__main__":
    unittest.main()
