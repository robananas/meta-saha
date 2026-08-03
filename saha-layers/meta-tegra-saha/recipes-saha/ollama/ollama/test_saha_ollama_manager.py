import importlib.util
import json
import tempfile
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
        self.assertEqual({"stt", "llm", "tts"}, set(catalog["stages"]))
        self.assertEqual(["funasr-paraformer-zh"], [item["id"] for item in catalog["stages"]["stt"]])
        self.assertEqual("funasr-paraformer-official-v0.2.10", catalog["stages"]["stt"][0]["adapter"])
        self.assertEqual(["qwen2.5:1.5b-instruct-q4_K_M"], [item["id"] for item in catalog["stages"]["llm"]])
        self.assertTrue(all(item["validationStatus"] == "verified-orin-r39.2-cuda13.2" for stage in catalog["stages"].values() for item in stage))
        with self.assertRaises(ValueError):
            MODULE.require_model({"modelId": "arbitrary/model:latest"})

    def test_empty_selection_is_not_ready_without_ollama(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "SELECTION_PATH", Path(directory) / "missing.json"), patch.object(MODULE, "LEGACY_CONFIG_PATH", Path(directory) / "missing.env"), patch.object(MODULE, "installed_ollama_models", return_value=set()):
            readiness = MODULE.pipeline_readiness()
        self.assertFalse(readiness["ready"])
        self.assertEqual("not_ready", readiness["status"])
        self.assertEqual(["not_selected"] * 3, [check["reason"] for check in readiness["checks"]])

    def test_selection_is_atomic_and_legacy_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            selection = Path(directory) / "selection.json"
            legacy = Path(directory) / "ollama.env"
            with patch.object(MODULE, "SELECTION_PATH", selection), patch.object(MODULE, "LEGACY_CONFIG_PATH", legacy), patch.object(MODULE, "model_installed", return_value=True), patch.object(MODULE.subprocess, "run"):
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
                                "model": "qwen2.5:1.5b-instruct-q4_K_M",
                            },
                        }
                    },
                },
                json.loads(selection.read_text()),
            )
            self.assertEqual("ROBAN_S2S_LLM_MODEL=qwen2.5:1.5b-instruct-q4_K_M\n", legacy.read_text())

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

    def test_download_state_has_rate_and_eta_contract(self):
        state = MODULE.DownloadState("qwen2.5:1.5b-instruct-q4_K_M", "downloading", 50, 100, 25.0, 2.0)
        body = MODULE._state_dict(state)
        self.assertEqual(25.0, body["bytesPerSecond"])
        self.assertEqual(2.0, body["etaSeconds"])


if __name__ == "__main__":
    unittest.main()
