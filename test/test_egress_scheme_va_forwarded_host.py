"""Chặn scheme lạ ở URL admin cấu hình (webhook/MCP hub) và chống giả
X-Forwarded-Host khi dựng URL media.

Báo cáo bảo mật 07/08:
- webhook forward / MCP hub URL urlopen thẳng → file:// biến thành đường đọc
  file / SSRF khi admin token lộ. Cho phép LAN (HA/n8n) nhưng chặn scheme lạ.
- resolve_image_base_url tin x-forwarded-host client gửi → API phát URL trỏ
  host tuỳ ý. Allowlist security.trusted_hosts để chặn host giả.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class IsHttpUrlTests(unittest.TestCase):
    def test_cho_phep_lan_chan_scheme_la(self):
        from services.net_guard import is_http_url
        self.assertTrue(is_http_url("http://172.16.10.200/webhook"))
        self.assertTrue(is_http_url("https://n8n.local/hook"))
        self.assertFalse(is_http_url("file:///etc/passwd"))
        self.assertFalse(is_http_url("gopher://x"))
        self.assertFalse(is_http_url("ftp://h/f"))
        self.assertFalse(is_http_url(""))
        self.assertFalse(is_http_url("http://"))


class _FakeURL:
    scheme = "https"
    netloc = "127.0.0.1:3030"


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers
        self.url = _FakeURL()


class ForwardedHostTests(unittest.TestCase):
    def _resolve(self, headers, cfg):
        from services.config import config
        from api.support import resolve_image_base_url
        with mock.patch.object(config, "get", return_value=cfg):
            return resolve_image_base_url(_FakeRequest(headers))

    def test_khong_allowlist_giu_hanh_vi_cu(self):
        url = self._resolve(
            {"x-forwarded-host": "evil.example", "x-forwarded-proto": "https"}, {})
        self.assertEqual(url, "https://evil.example",
                         "chưa cấu hình allowlist thì giữ hành vi cũ (tunnel/LAN)")

    def test_allowlist_bo_host_gia(self):
        url = self._resolve(
            {"x-forwarded-host": "evil.example", "host": "real.local",
             "x-forwarded-proto": "https"},
            {"security": {"trusted_hosts": ["real.local"]}})
        self.assertEqual(url, "https://real.local",
                         "forwarded-host ngoài allowlist bị bỏ, dùng host thật")

    def test_allowlist_giu_host_hop_le(self):
        url = self._resolve(
            {"x-forwarded-host": "app.mydomain.com", "x-forwarded-proto": "https"},
            {"security": {"trusted_hosts": ["app.mydomain.com"]}})
        self.assertEqual(url, "https://app.mydomain.com")


if __name__ == "__main__":
    unittest.main()
