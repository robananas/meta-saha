import hashlib
import importlib.util
import io
import json
import tarfile
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
        self.assertEqual({"stt", "llm", "tts", "speaker"}, set(catalog["stages"]))
        self.assertEqual(["funasr-paraformer-zh", "sherpa-onnx-paraformer-zh"], [item["id"] for item in catalog["stages"]["stt"]])
        self.assertEqual("funasr-paraformer-official-v0.2.10", catalog["stages"]["stt"][0]["adapter"])
        self.assertEqual("sherpa-onnx-paraformer", catalog["stages"]["stt"][1]["adapter"])
        self.assertEqual(["qwen2.5:1.5b-instruct-q4_K_M"], [item["id"] for item in catalog["stages"]["llm"]])
        self.assertEqual(["cosyvoice3-0.5b-2512", "sherpa-onnx-vits-zh", "matcha-icefall-zh-en"], [item["id"] for item in catalog["stages"]["tts"]])
        cosyvoice = catalog["stages"]["tts"][0]
        self.assertEqual("cosyvoice3-official-sidecar", cosyvoice["adapter"])
        self.assertEqual("candidate-orin-r39.2-cuda13.2", cosyvoice["validationStatus"])
        self.assertFalse(cosyvoice["compatible"])
        self.assertFalse(cosyvoice["downloadAvailable"])
        self.assertIn(MODULE.COSYVOICE_REVISION, cosyvoice["compatibilityReason"])
        self.assertEqual("sherpa-onnx-vits-zh", catalog["stages"]["tts"][1]["adapter"])
        matcha = catalog["stages"]["tts"][2]
        self.assertEqual("sherpa-onnx-matcha-zh-en", matcha["adapter"])
        self.assertEqual("verified-orin-r39.2-cuda13.2", matcha["validationStatus"])
        self.assertIn("license is unclear", matcha["licenseNotice"])
        self.assertEqual(["wespeaker-campp", "titanet-large"], [item["id"] for item in catalog["stages"]["speaker"]])
        self.assertTrue(all(not item["compatible"] for item in catalog["stages"]["speaker"]))
        self.assertTrue(all(not item["downloadAvailable"] for item in catalog["stages"]["speaker"]))
        self.assertTrue(all(item["validationStatus"] == "verified-orin-r39.2-cuda13.2" for stage in (catalog["stages"]["stt"], catalog["stages"]["llm"]) for item in stage))
        with self.assertRaises(ValueError):
            MODULE.require_model({"modelId": "arbitrary/model:latest"})

    def test_empty_selection_is_not_ready_without_ollama(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "SELECTION_PATH", Path(directory) / "missing.json"), patch.object(MODULE, "LEGACY_CONFIG_PATH", Path(directory) / "missing.env"), patch.object(MODULE, "installed_ollama_models", return_value=set()):
            readiness = MODULE.pipeline_readiness()
        self.assertFalse(readiness["ready"])
        self.assertEqual("not_ready", readiness["status"])
        self.assertEqual(["not_selected"] * 3, [check["reason"] for check in readiness["checks"]])

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
        self.assertEqual(list(MODULE.CORE_STAGES), [check["stage"] for check in readiness["checks"]])

    def test_external_speaker_artifacts_cannot_be_downloaded_or_activated(self):
        spec = MODULE.BY_ID["wespeaker-campp"]
        with self.assertRaisesRegex(RuntimeError, "verified artifact metadata"):
            MODULE.start_download(spec.id)
        with self.assertRaisesRegex(RuntimeError, "verified artifact metadata"):
            MODULE.activate(spec)

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

    def test_cosyvoice_candidate_cannot_activate_before_board_gates(self):
        old = MODULE.PipelineSelection(1, {"tts": MODULE.selection_for(MODULE.BY_ID["sherpa-onnx-vits-zh"])})
        commands = []
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "SELECTION_PATH", Path(directory) / "selection.json"), patch.object(MODULE, "read_selection", return_value=old), patch.object(MODULE, "model_installed", return_value=True), patch.object(MODULE, "run_s2s_command", side_effect=lambda command, timeout=360: commands.append(command)):
            with self.assertRaisesRegex(RuntimeError, MODULE.COSYVOICE_REVISION):
                MODULE.activate(MODULE.BY_ID["cosyvoice3-0.5b-2512"])
        self.assertEqual([], commands)

    def test_switching_away_stops_cosyvoice_after_s2s_ready(self):
        old = MODULE.PipelineSelection(1, {"tts": MODULE.selection_for(MODULE.BY_ID["cosyvoice3-0.5b-2512"])})
        commands = []
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "SELECTION_PATH", Path(directory) / "selection.json"), patch.object(MODULE, "read_selection", return_value=old), patch.object(MODULE, "model_installed", return_value=True), patch.object(MODULE, "run_s2s_command", side_effect=lambda command, timeout=360: commands.append(command)), patch.object(MODULE, "wait_ready", return_value={"ready": True}), patch.object(MODULE.subprocess, "run"):
            MODULE.activate(MODULE.BY_ID["sherpa-onnx-vits-zh"])
        self.assertEqual(["cosy-stop"], commands)

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
        self.assertFalse(next(item for item in status["stages"]["tts"]["models"] if item["id"] == "cosyvoice3-0.5b-2512")["compatible"])
        self.assertTrue(all(not item["compatible"] for item in status["stages"]["speaker"]["models"]))

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
        self.assertFalse(status["stages"]["tts"]["models"][0]["compatible"])
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

        with patch.object(MODULE, "read_selection", return_value=old), patch.object(MODULE, "_voice_profile", return_value=profile), patch.object(MODULE, "_atomic_json") as atomic, patch.object(MODULE.urllib.request, "urlopen", side_effect=urlopen), patch.object(MODULE.subprocess, "run") as run:
            with self.assertRaisesRegex(OSError, "preprocess failed"):
                MODULE.select_voice("user-test")

        self.assertTrue(opened[0][0].endswith("/v1/voices/reload"))
        self.assertTrue(opened[1][0].endswith("/v1/voices/preprocess"))
        self.assertEqual(MODULE.selection_dict(old), atomic.call_args_list[-1].args[1])
        run.assert_called_once_with(["systemctl", "try-restart", "saha-s2s.service"], check=False, timeout=180)

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
