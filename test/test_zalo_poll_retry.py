"""Vòng long-poll Zalo Bot: read-timeout = 'không có tin', KHÔNG phải lỗi.

getUpdates của Zalo Bot không hỗ trợ offset (xem `_next_offset`), nên khoảng nào
KHÔNG poll là khoảng có thể RƠI TIN. Bản cũ coi read-timeout của long-poll là
lỗi → `fails` tăng → backoff `min(2+fails,15)` lên tới 15s không poll → tin tới
trong 15s đó mất ('được 1 câu rồi thôi'). Read-timeout của long-poll chỉ nghĩa
'hết cửa sổ, chưa có tin' — phải poll lại NGAY.
"""
from __future__ import annotations

import os
import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import zalo_bot as zb  # noqa: E402


class GetUpdatesRong(unittest.TestCase):
    def test_ok_khong_phai_rong(self):
        self.assertFalse(zb._getupdates_rong({"ok": True, "result": []}))

    def test_408_la_rong(self):
        self.assertTrue(zb._getupdates_rong({"ok": False, "error_code": 408}))

    def test_read_timeout_la_rong(self):
        """Ca gây rơi tin: read-timeout KHÔNG kèm error_code."""
        self.assertTrue(zb._getupdates_rong(
            {"ok": False, "description": "The read operation timed out"}))

    def test_timeout_bat_ky_dang_chu_la_rong(self):
        for d in ("timed out", "Read timed out.", "connection timeout", "TIMEOUT"):
            self.assertTrue(zb._getupdates_rong({"ok": False, "description": d}), d)

    def test_loi_that_KHONG_phai_rong(self):
        """Lỗi mạng/5xx thật vẫn phải backoff, không được coi là 'hết cửa sổ'."""
        for r in ({"ok": False, "description": "Connection refused"},
                  {"ok": False, "error_code": 500, "description": "server error"},
                  {"ok": False, "description": "Bad gateway"}):
            self.assertFalse(zb._getupdates_rong(r), r)

    def test_vong_poll_dung_ham_nay_de_khong_backoff(self):
        """Chốt: vòng poll phân loại rỗng bằng `_getupdates_rong`, không phải chỉ 408."""
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "services" / "zalo_bot.py").read_text("utf-8")
        self.assertIn("trong = _getupdates_rong(r)", src)
        self.assertIn("time.sleep(1 if trong else min(2 + fails, 15))", src)


if __name__ == "__main__":
    unittest.main()
