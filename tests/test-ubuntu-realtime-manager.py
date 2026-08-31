#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/ubuntu-deploy/realtime_manager.py"
SPEC = importlib.util.spec_from_file_location("ubuntu_realtime_manager", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RealtimeManagerContractTest(unittest.TestCase):
    def test_pipeline_mode_expands_disk_config_into_app_status_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mode = root / "mode.json"
            key = root / "key"
            workspace = root / "workspace"
            mode.write_text('{"version":2,"mode":"realtime","provider":"qwen","generation":3}')
            key.write_text("key")
            workspace.write_text("workspace")
            readiness = {
                "ready": True,
                "effectiveMode": "realtime",
                "effectiveProvider": "qwen",
                "effectiveGeneration": 3,
            }
            with (
                patch.object(MODULE, "MODE", mode),
                patch.object(MODULE, "KEY", key),
                patch.object(MODULE, "WORKSPACE", workspace),
                patch.object(MODULE, "s2s_ready", return_value=readiness),
            ):
                response = MODULE.pipeline_mode_response()

        self.assertNotIn("version", response)
        self.assertEqual("realtime", response["effectiveMode"])
        self.assertEqual("qwen", response["effectiveProvider"])
        self.assertEqual(3, response["effectiveGeneration"])
        self.assertEqual("ready", response["status"])
        self.assertEqual({"qwen", "grok"}, set(response["providers"]))
        self.assertNotIn("key", json.dumps(response).lower())

    def test_realtime_settings_adds_effective_runtime_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "generation": 2,
                        "model": "qwen-audio-3.0-realtime-flash",
                        "turnMode": "smart_turn",
                        "threshold": 0.5,
                        "silenceDurationMs": 800,
                        "voice": "longanqian",
                        "enableSpeechEmotion": True,
                        "maxHistoryTurns": 20,
                        "instructions": "简洁回答",
                    }
                )
            )
            readiness = {
                "ready": True,
                "effectiveRealtimeGeneration": 2,
                "effectiveRealtimeModel": "qwen-audio-3.0-realtime-flash",
            }
            with (
                patch.object(MODULE, "SETTINGS", settings),
                patch.object(MODULE, "s2s_ready", return_value=readiness),
            ):
                response = MODULE.realtime_settings_response()

        self.assertEqual(2, response["effectiveGeneration"])
        self.assertEqual("qwen-audio-3.0-realtime-flash", response["effectiveModel"])
        self.assertEqual("ready", response["status"])
        self.assertIsNone(response["error"])


if __name__ == "__main__":
    unittest.main()
