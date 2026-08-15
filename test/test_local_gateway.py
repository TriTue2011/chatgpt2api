"""Regression tests for the gateway's in-container address."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from services.local_gateway import gateway_base_url, gateway_v1_url
from services import net_guard


class LocalGatewayUrlTests(unittest.TestCase):
    def test_dung_APP_PORT_khi_khong_co_override(self):
        with patch.dict(os.environ, {"APP_PORT": "8080"}, clear=True):
            self.assertEqual(gateway_base_url(), "http://127.0.0.1:8080")
            self.assertEqual(gateway_v1_url(), "http://127.0.0.1:8080/v1")

    def test_override_co_chu_dich_vu_uu_tien_hon_APP_PORT(self):
        with patch.dict(os.environ, {
            "APP_PORT": "8080",
            "C2A_GATEWAY_URL": "http://gateway.internal:9090/",
        }, clear=True):
            self.assertEqual(gateway_base_url(), "http://gateway.internal:9090")

    def test_APP_PORT_loi_thi_quay_ve_cong_mac_dinh(self):
        with patch.dict(os.environ, {"APP_PORT": "not-a-port"}, clear=True):
            self.assertEqual(gateway_base_url(), "http://127.0.0.1:80")

    def test_tai_anh_noi_bo_dung_APP_PORT_khong_phai_cong_80(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"image"
        with patch.dict(os.environ, {"APP_PORT": "8080"}, clear=True), \
             patch("services.net_guard.urllib.request.urlopen", return_value=response) as fetch:
            self.assertEqual(
                net_guard.self_images_fetch("http://127.0.0.1:80/images/a.png"),
                b"image",
            )
        self.assertEqual(fetch.call_args.args[0], "http://127.0.0.1:8080/images/a.png")


if __name__ == "__main__":
    unittest.main()
