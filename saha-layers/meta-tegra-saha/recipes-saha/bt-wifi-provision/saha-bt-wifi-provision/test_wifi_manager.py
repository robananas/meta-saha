#!/usr/bin/env python3

from __future__ import annotations

import unittest
from unittest.mock import patch

import wifi_manager


class WifiManagerTests(unittest.TestCase):
    def test_nmcli_escape_parser(self) -> None:
        self.assertEqual(
            wifi_manager._split_terse(r"Cafe\:Guest:80:WPA2"),
            ["Cafe:Guest", "80", "WPA2"],
        )
        self.assertEqual(wifi_manager._split_terse(r"back\\slash:x"), [r"back\slash", "x"])

    def test_signal_percent_is_clamped(self) -> None:
        self.assertEqual(wifi_manager._signal_percent("-1"), 0)
        self.assertEqual(wifi_manager._signal_percent("47"), 47)
        self.assertEqual(wifi_manager._signal_percent("101"), 100)
        self.assertEqual(wifi_manager._signal_percent("bad"), 0)

    @patch("wifi_manager.time.sleep")
    @patch("wifi_manager.time.monotonic", side_effect=[0, 0, 1, 2, 6])
    @patch("wifi_manager.get_wifi_status", return_value={"connected": True, "ssid": "A", "ip": ""})
    @patch("wifi_manager._run_nmcli", return_value="")
    @patch("wifi_manager._wifi_device", return_value="wlan0")
    def test_connect_deadline_requires_ip(self, *_mocks: object) -> None:
        result = wifi_manager.connect_wifi("A", "pw", 5)
        self.assertEqual(result["state"], "failed")
        self.assertIn("deadline", result["error"])

    @patch("wifi_manager.get_wifi_status", return_value={"connected": True, "ssid": "A", "ip": "1.2.3.4"})
    @patch("wifi_manager._run_nmcli", return_value="")
    @patch("wifi_manager._wifi_device", return_value="wlan0")
    def test_connect_reports_only_real_coarse_stages(self, *_mocks: object) -> None:
        stages: list[str] = []
        result = wifi_manager.connect_wifi("A", "pw", 5, stages.append)
        self.assertEqual(result["state"], "connected")
        self.assertEqual(stages, ["associating", "obtainingIp"])
        self.assertNotIn("authenticating", stages)


if __name__ == "__main__":
    unittest.main()
