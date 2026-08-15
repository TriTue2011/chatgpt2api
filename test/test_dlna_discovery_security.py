"""Ràng buộc an toàn cho DLNA discovery (SSDP là dữ liệu mạng không tin cậy)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.voice import speakers


class SSDPDiscoverySecurityTests(unittest.TestCase):
    def test_location_phai_dung_ip_da_tra_loi(self):
        good = "http://192.168.10.24:8200/device.xml"
        self.assertEqual(speakers._ssdp_location_cua_sender(good, "192.168.10.24"), good)

        for location in (
            "http://127.0.0.1:80/api/settings",
            "http://169.254.169.254/latest/meta-data",
            "http://192.168.10.99/device.xml",
            "file:///etc/passwd",
            "http://user:pass@192.168.10.24/device.xml",
        ):
            self.assertEqual(speakers._ssdp_location_cua_sender(location, "192.168.10.24"), "")

    def test_control_url_phai_o_cung_thiet_bi_voi_description(self):
        location = "http://192.168.10.24:8200/device.xml"
        self.assertTrue(speakers._dlna_control_cung_thiet_bi(
            location, "http://192.168.10.24:1400/MediaRenderer/AVTransport/Control"))
        self.assertFalse(speakers._dlna_control_cung_thiet_bi(
            location, "http://127.0.0.1:80/api/settings"))
        self.assertFalse(speakers._dlna_control_cung_thiet_bi(
            location, "https://192.168.10.25/control"))


if __name__ == "__main__":
    unittest.main()
