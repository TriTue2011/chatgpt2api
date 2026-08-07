"""Chống giả mạo IP qua X-Forwarded-For (rate-limit login) và giả cờ nội bộ
x_agent_internal (né Agent run journal).

Báo cáo bảo mật 07/08:
- login_guard tin X-Forwarded-For do client gửi → brute-force chỉ cần đổi header
  là thành "IP mới", vô hiệu hoá lockout. Mặc định phải dùng request.client.host.
- api/ai.py tin x_agent_internal từ payload client → user key hợp lệ tự gắn cờ
  để request bị đánh internal và bỏ qua run journal.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, headers=None, host="203.0.113.9"):
        self.headers = headers or {}
        self.client = _FakeClient(host)


class LoginGuardXffTests(unittest.TestCase):
    def setUp(self):
        from services import login_guard
        self.lg = login_guard

    def test_mac_dinh_bo_qua_xff_dung_client_host(self):
        from services.config import config
        with mock.patch.object(config, "get", return_value={}):
            req = _FakeRequest(headers={"x-forwarded-for": "1.2.3.4"}, host="10.0.0.5")
            ip = self.lg.client_ip_from_request(req)
        self.assertEqual(ip, "10.0.0.5", "mặc định phải dùng IP TCP thật, bỏ XFF")

    def test_bat_trust_thi_moi_dung_xff(self):
        from services.config import config
        with mock.patch.object(config, "get",
                               return_value={"security": {"trust_forwarded_for": True}}):
            req = _FakeRequest(headers={"x-forwarded-for": "1.2.3.4, 9.9.9.9"}, host="10.0.0.5")
            ip = self.lg.client_ip_from_request(req)
        self.assertEqual(ip, "1.2.3.4", "khi admin bật trust, dùng XFF đầu tiên")

    def test_khong_the_ne_lockout_bang_doi_xff(self):
        """Đổi XFF mỗi lần vẫn tính về CÙNG một IP (client.host) → lockout hiệu lực."""
        from services.config import config
        self.lg.reset_for_tests()
        with mock.patch.object(config, "get", return_value={}):
            for i in range(20):
                req = _FakeRequest(headers={"x-forwarded-for": f"5.5.5.{i}"}, host="10.0.0.7")
                ip = self.lg.client_ip_from_request(req)
                self.lg.record_failure(ip)
            # cùng client.host → đã bị lockout, không phải 20 IP khác nhau
            req = _FakeRequest(headers={"x-forwarded-for": "5.5.5.99"}, host="10.0.0.7")
            ip = self.lg.client_ip_from_request(req)
            with self.assertRaises(Exception):
                self.lg.check_allowed(ip)
        self.lg.reset_for_tests()


class InternalHeaderTests(unittest.TestCase):
    def test_header_khop_auth_key_moi_tin_co_internal(self):
        from api.ai import _internal_header_ok
        from services.config import config
        # auth_key lấy từ env CHATGPT2API_AUTH_KEY (đặt = 'test-auth' ở đầu file).
        key = config.auth_key
        self.assertTrue(key, "cần auth_key để kiểm")
        self.assertTrue(_internal_header_ok(
            _FakeRequest(headers={"x-agent-internal-key": key})))
        self.assertFalse(_internal_header_ok(
            _FakeRequest(headers={"x-agent-internal-key": "sai-hoan-toan"})))
        self.assertFalse(_internal_header_ok(_FakeRequest(headers={})))


if __name__ == "__main__":
    unittest.main()
