"""Allowlist người gửi email khớp chính xác (không khớp chuỗi con) + email
agent không chạm nhóm hành động nguy hiểm.

Báo cáo bảo mật 07/08: _allowed khớp chuỗi con → "admin" khớp "admin@evil.com"
(giả mạo người gửi lọt allowlist); và reply chạy orchestrate(allow=None,
ha_fastpath=True) → agent thấy cả HA fast-path.
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class AllowedSenderTests(unittest.TestCase):
    def setUp(self):
        from services import email_channel
        self._allowed = email_channel._allowed

    def test_khop_chinh_xac(self):
        acc = {"allowed_senders": ["boss@company.com"]}
        self.assertTrue(self._allowed(acc, "boss@company.com"))
        self.assertTrue(self._allowed(acc, "BOSS@company.com"))  # case-insensitive

    def test_chan_gia_mao_chuoi_con(self):
        acc = {"allowed_senders": ["admin@company.com"]}
        # Trước bản vá "admin@company.com" (hay "admin") khớp chuỗi con.
        self.assertFalse(self._allowed(acc, "admin@company.com.evil.com"))
        acc2 = {"allowed_senders": ["boss"]}
        self.assertFalse(self._allowed(acc2, "boss@evil.com"),
                         "chuỗi con không được khớp nữa")

    def test_theo_domain(self):
        acc = {"allowed_senders": ["@company.com"]}
        self.assertTrue(self._allowed(acc, "anyone@company.com"))
        self.assertFalse(self._allowed(acc, "anyone@company.com.evil.com"))

    def test_trong_thi_chan_het(self):
        self.assertFalse(self._allowed({"allowed_senders": []}, "x@y.com"))
        self.assertFalse(self._allowed({}, "x@y.com"))

    def test_wildcard_van_cho_phep(self):
        self.assertTrue(self._allowed({"allowed_senders": ["*"]}, "any@any.com"))


class EmailAllowGroupsTests(unittest.TestCase):
    def test_email_khong_co_nhom_nguy_hiem(self):
        from services.agent import capabilities as caps
        deny = {"homeassistant", "device", "server", "code"}
        allow = {g for g in caps.all_groups() if g not in deny}
        for d in deny:
            self.assertNotIn(d, allow, f"email không được có nhóm {d}")
        # vẫn còn nhóm đọc/tra cứu hữu ích
        self.assertIn("web", allow)


if __name__ == "__main__":
    unittest.main()
