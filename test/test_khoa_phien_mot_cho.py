"""Khoá phiên Telegram phải tính ở ĐÚNG MỘT CHỖ — nút bấm và tin nhắn cùng khoá.

Lỗi dựng lại được trên mã cũ: đường TIN NHẮN dựng khoá tại chỗ
(`f"{chat}#{topic}:u{uid}"`) rồi đưa cho `orchestrate`, còn đường BẤM NÚT
(`_handle_callback_query`) lại tra `ask_choices.get_pending(chat_id)` bằng
chat_id trần. Trong nhóm hai khoá KHÁC nhau → nút bấm không tìm thấy lựa chọn
nào rồi `return` trong im lặng: người dùng bấm nút, không có gì xảy ra, không có
lỗi nào để tìm.

Kèm luôn tính chất phạm vi: người bấm không tiêu được lựa chọn đang chờ của
người khác trong cùng nhóm.
"""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.telegram_bot as tg  # noqa: E402

GOC = pathlib.Path(__file__).resolve().parents[1]


class KhoaPhien(unittest.TestCase):
    def test_chat_1_1_giu_khoa_cu(self):
        """Đổi khoá chat 1-1 là mất sạch lịch sử/persona/approval đang có."""
        self.assertEqual(tg.khoa_phien("555", "", "555"), "555")
        self.assertEqual(tg.khoa_phien("555"), "555")

    def test_nhom_tach_theo_nguoi(self):
        self.assertEqual(tg.khoa_phien("-100", "", "9"), "-100:u9")

    def test_topic_vao_khoa_va_topic_thang_nhom(self):
        self.assertEqual(tg.khoa_phien("-100", "7", "9"), "-100#7:u9")
        self.assertNotEqual(tg.khoa_phien("-100", "7", "9"),
                            tg.khoa_phien("-100", "8", "9"))

    def test_tat_group_user_isolation_thi_khong_kem_nguoi(self):
        from services.config import config
        with mock.patch.object(type(config), "group_user_isolation",
                               new_callable=mock.PropertyMock,
                               return_value=False, create=True):
            self.assertEqual(tg.khoa_phien("-100", "", "9"), "-100")

    def test_khong_biet_nguoi_gui_thi_ve_khoa_nhom(self):
        self.assertEqual(tg.khoa_phien("-100", "", ""), "-100")


class NutBamDungKhoaVoiTinNhan(unittest.TestCase):
    """Chốt hồi quy: cả hai đường phải đi qua `khoa_phien`, không dựng tại chỗ."""

    def test_ca_hai_duong_deu_goi_khoa_phien(self):
        src = (GOC / "services" / "telegram_bot.py").read_text("utf-8")
        self.assertIn("_skey = khoa_phien(chat_id, _cur_topic(), user_id)", src)
        self.assertIn("skey = khoa_phien(chat_id, topic_id, user_id)", src)
        # Không còn nơi nào dựng khoá phiên bằng tay.
        self.assertNotIn('_skey = f"{_skey_base}:u{user_id}"', src)

    def test_callback_khong_con_tra_bang_chat_id_tran(self):
        src = (GOC / "services" / "telegram_bot.py").read_text("utf-8")
        self.assertNotIn("_ask.get_pending(chat_id)", src)
        self.assertNotIn("_ask.clear_pending(chat_id)", src)

    def test_bo_dem_fallback_cung_theo_phien(self):
        """Orchestrator lỗi → bộ đệm hội thoại vẫn không được trộn giữa người."""
        src = (GOC / "services" / "telegram_bot.py").read_text("utf-8")
        self.assertIn('key = f"tg_{khoa_phien(chat_id, _cur_topic(), user_id)}"', src)


class NutBamKhongTieuLuaChonCuaNguoiKhac(unittest.TestCase):
    def setUp(self):
        from services.agent import ask_choices as ask
        self.ask = ask
        for k in ("-100:u9", "-100:u10"):
            ask.clear_pending(k)
            self.addCleanup(ask.clear_pending, k)

    def test_lua_chon_luu_theo_phien_thi_nguoi_khac_khong_tra_ra(self):
        self.ask.set_pending("-100:u9", [{"label": "Flow", "send": "flow"}])
        self.assertTrue(self.ask.get_pending(tg.khoa_phien("-100", "", "9")))
        self.assertFalse(self.ask.get_pending(tg.khoa_phien("-100", "", "10")))

    def test_khoa_cu_chat_id_tran_khong_tra_ra_gi(self):
        """Chính là lý do nút bấm trong nhóm im lặng ở bản cũ."""
        self.ask.set_pending("-100:u9", [{"label": "Flow", "send": "flow"}])
        self.assertFalse(self.ask.get_pending("-100"))


if __name__ == "__main__":
    unittest.main()
