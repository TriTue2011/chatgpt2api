"""Bot zca-js chạy trên CHÍNH tài khoản chủ: tin chủ tự gõ bị isSelf.

Mặc định bỏ tin isSelf (chống bot trả lời chính nó → lặp). Khi thread bật
`reply_to_self` + có keyword tag, tin CHỦ TỰ GÕ có tag được xử lý; câu bot tự
sinh (văn xuôi, không tag) vẫn bị bỏ nên không lặp.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class ReplyToSelfReaderTests(unittest.TestCase):
    """`reply_to_self_for` đọc cờ + keyword từ thread_mention_filters."""

    def _cfg(self, rec):
        return {"thread_mention_filters": {"zalop:acc1:th1": rec}}

    def test_bat_va_co_keyword(self):
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get",
                        return_value=self._cfg({"reply_to_self": True, "keyword": "@bot"})):
            on, kw = caps.reply_to_self_for("zalop", "acc1", "th1")
        self.assertTrue(on)
        self.assertEqual(kw, "@bot")

    def test_bat_nhung_keyword_rong_coi_nhu_tat(self):
        # Chốt chống lặp: không keyword thì không có gì phân biệt tin chủ với câu
        # bot tự sinh → phải TẮT dù cờ bật.
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get",
                        return_value=self._cfg({"reply_to_self": True, "keyword": ""})):
            on, kw = caps.reply_to_self_for("zalop", "acc1", "th1")
        self.assertFalse(on)

    def test_khong_cau_hinh_thi_tat(self):
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get", return_value={}):
            self.assertEqual(caps.reply_to_self_for("zalop", "acc1", "th1"), (False, ""))


class SelfMessageGateTests(unittest.TestCase):
    """Cổng isSelf trong handle_event: chỉ cho tin chủ CÓ TAG khi bật cờ."""

    def _run(self, *, is_self, text, reply_to_self, keyword):
        import services.zalo_personal as zp
        ev = {"account_id": "acc1", "thread_id": "th1", "sender_id": "acc1",
              "is_self": is_self, "text": text, "msg_id": "m1", "thread_type": 0,
              "mentions": []}
        called = {"ai": False}
        with mock.patch.object(zp, "_parse_event", return_value=ev), \
             mock.patch.object(zp, "_dedup", return_value=False), \
             mock.patch.object(zp, "forward_to_ha"), \
             mock.patch("services.channel_activity.is_blacklisted", return_value=False), \
             mock.patch("services.channel_activity.record"), \
             mock.patch("services.agent.capabilities.mention_required_for", return_value=(False, "")), \
             mock.patch("services.agent.capabilities.forward_event", return_value=False), \
             mock.patch("services.agent.capabilities.reply_to_self_for",
                        return_value=(bool(reply_to_self and keyword), keyword)), \
             mock.patch.object(zp, "_process_ai", side_effect=lambda e: called.__setitem__("ai", True)):
            zp.handle_event({}, "message")
        return called["ai"]

    def test_tin_chu_co_tag_bat_co_thi_xu_ly(self):
        self.assertTrue(self._run(is_self=True, text="@bot vụ cháy sao rồi",
                                  reply_to_self=True, keyword="@bot"))

    def test_tin_chu_khong_tag_thi_bo(self):
        self.assertFalse(self._run(is_self=True, text="chào cả nhà",
                                   reply_to_self=True, keyword="@bot"))

    def test_cau_bot_tu_sinh_khong_tag_khong_lap(self):
        # Câu bot vừa gửi (isSelf, văn xuôi không tag) → bỏ → không lặp.
        self.assertFalse(self._run(is_self=True, text="Dạ vụ cháy đã dập tắt ạ 😊",
                                   reply_to_self=True, keyword="@bot"))

    def test_khong_bat_co_thi_tin_chu_bi_bo(self):
        self.assertFalse(self._run(is_self=True, text="@bot sao rồi",
                                   reply_to_self=False, keyword="@bot"))

    def test_tin_nguoi_khac_van_xu_ly_binh_thuong(self):
        import services.zalo_personal as zp
        ev = {"account_id": "acc1", "thread_id": "th1", "sender_id": "other",
              "is_self": False, "text": "chào bot", "msg_id": "m2", "thread_type": 0,
              "mentions": []}
        called = {"ai": False}
        with mock.patch.object(zp, "_parse_event", return_value=ev), \
             mock.patch.object(zp, "_dedup", return_value=False), \
             mock.patch.object(zp, "forward_to_ha"), \
             mock.patch("services.channel_activity.is_blacklisted", return_value=False), \
             mock.patch("services.channel_activity.record"), \
             mock.patch("services.agent.capabilities.mention_required_for", return_value=(False, "")), \
             mock.patch("services.agent.capabilities.forward_event", return_value=False), \
             mock.patch.object(zp, "_process_ai", side_effect=lambda e: called.__setitem__("ai", True)):
            zp.handle_event({}, "message")
        self.assertTrue(called["ai"])


if __name__ == "__main__":
    unittest.main()
