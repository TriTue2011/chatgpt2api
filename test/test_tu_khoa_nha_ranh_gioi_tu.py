"""Nhận câu nhà thông minh theo TỪ, không theo chuỗi con.

Lỗi thật (đo trên main 14/09/2026): "giá chứng khoán hôm nay" bị `_is_smarthome_query`
nhận là lệnh nhà vì "khoá" nằm trong "khoán" — câu hỏi tra cứu mất công cụ MCP.
Cùng lớp: "log" trong "blog", "pin" trong "ping".
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.protocol import openai_v1_chat_complete as o  # noqa: E402


class TuKhoaNhaTheoTuTest(unittest.TestCase):
    def test_khong_khop_giua_tu_khac(self) -> None:
        for cau in ("giá chứng khoán hôm nay", "khoán việc cho thợ", "vào blog công nghệ xem gì", "ping google được không"):
            self.assertFalse(o._is_smarthome_query(cau), cau)

    def test_van_nhan_lenh_that_ke_ca_dau_cau_va_tieng_anh(self) -> None:
        for cau in ("tắt đèn phòng khách.", "bật quạt!", "khoá cửa chính", "mở khóa cửa", "set đèn 50%",
                    "turn on the light", "điều hoà phòng ngủ đang mấy độ", "Đèn bếp?"):
            self.assertTrue(o._is_smarthome_query(cau), cau)

    def test_chu_to_hop_dau_roi_van_nhan(self) -> None:
        import unicodedata

        self.assertTrue(o._is_smarthome_query(unicodedata.normalize("NFD", "tắt đèn")))
        self.assertFalse(o._is_smarthome_query(unicodedata.normalize("NFD", "giá chứng khoán")))


if __name__ == "__main__":
    unittest.main()
