import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("saha-ollama-manager.py")
SPEC = importlib.util.spec_from_file_location("saha_ollama_manager", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class OllamaManagerTest(unittest.TestCase):
    def test_catalog_is_allowlisted_and_bounded(self):
        self.assertEqual(3, len(MODULE.CATALOG))
        self.assertEqual({item["id"] for item in MODULE.CATALOG}, MODULE.ALLOWED)
        with self.assertRaises(ValueError):
            MODULE.require_model({"model": "arbitrary/model:latest"})

    def test_activation_config_contains_only_selected_model(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "ollama.env"
            with patch.object(MODULE, "CONFIG_PATH", config):
                config.parent.mkdir(parents=True, exist_ok=True)
                temporary = config.with_suffix(".tmp")
                temporary.write_text("ROBAN_S2S_LLM_MODEL=qwen2.5:1.5b-instruct-q4_K_M\n", encoding="utf-8")
                temporary.replace(config)
                self.assertEqual("qwen2.5:1.5b-instruct-q4_K_M", MODULE.active_model())
                self.assertEqual(1, len(config.read_text(encoding="utf-8").splitlines()))

    def test_active_model_falls_back_to_packaged_default(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "missing.env"
            default_config = Path(directory) / "default.env"
            default_config.write_text("ROBAN_S2S_LLM_MODEL=gemma3:1b-it-q4_K_M\n", encoding="utf-8")
            with (
                patch.object(MODULE, "CONFIG_PATH", config),
                patch.object(MODULE, "DEFAULT_CONFIG_PATH", default_config),
            ):
                self.assertEqual("gemma3:1b-it-q4_K_M", MODULE.active_model())

    def test_cpu_size_catalog_values_are_positive(self):
        self.assertTrue(all(item["sizeBytes"] > 0 for item in MODULE.CATALOG))


if __name__ == "__main__":
    unittest.main()
