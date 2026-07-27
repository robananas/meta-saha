import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("saha-board-status.py")
spec = importlib.util.spec_from_file_location("saha_board_status", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class BoardStatusTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        module.RUNTIME_DIR = root
        module.SNAPSHOT_PATH = root / "snapshot.json"
        module.EVENTS_PATH = root / "events.jsonl"
        module.MAX_EVENTS = 3
        self.patches = [
            mock.patch.object(module, "read_boot_id", return_value="boot-test"),
            mock.patch.object(module, "utc_now", side_effect=lambda: "2026-07-27T10:00:00.000Z"),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temporary.cleanup()

    def test_bounds_events_and_updates_snapshot(self):
        status = module.BoardStatus()
        for index in range(5):
            status.emit("wifi", f"state-{index}")
        events = [json.loads(line) for line in module.EVENTS_PATH.read_text().splitlines()]
        snapshot = json.loads(module.SNAPSHOT_PATH.read_text())
        self.assertEqual(3, len(events))
        self.assertEqual("boot-test", snapshot["bootId"])
        self.assertEqual("state-4", snapshot["nodes"]["wifi"]["state"])
        self.assertEqual(6, snapshot["lastSeq"])

    def test_redacts_sensitive_detail_recursively(self):
        status = module.BoardStatus()
        event = status.emit("ble", "ready", detail={"password": "bad", "nested": {"accessToken": "bad"}, "safe": "ok"})
        self.assertEqual("<redacted>", event["detail"]["password"])
        self.assertEqual("<redacted>", event["detail"]["nested"]["accessToken"])
        self.assertEqual("ok", event["detail"]["safe"])

    def test_restores_sequence_and_history_during_same_boot(self):
        first = module.BoardStatus()
        first.emit("wifi", "connected")
        second = module.BoardStatus()
        event = second.emit("docker", "ready")
        self.assertEqual(3, event["seq"])
        self.assertEqual([1, 2, 3], [item["seq"] for item in second.events])

    def test_deduplicates_identical_state(self):
        status = module.BoardStatus()
        first = status.emit("ha_matter", "connected")
        second = status.emit("ha_matter", "connected")
        self.assertEqual(first["seq"], second["seq"])
        self.assertEqual(2, len(status.events))


if __name__ == "__main__":
    unittest.main()
