"""Câu chấm «hh» trong nhóm học hỏi phải tới được bot — kể cả khi nhóm TẮT AI.

SỰ CỐ 13/09/2026 16:51. Chủ máy gõ «hh 91 đúng» vào nhóm "AI học hỏi". Tin tới
máy chủ (log nhận tin có đủ), nhưng câu #91 vẫn "chờ chấm" và bot không đáp.
Nhóm đó tắt AI trong «Lọc thread» (`ai_off_for` = True, chưa tick nhóm quyền
nào), mà cổng chấm `_nhom_hoc_hoi` lại nằm trong `_process_ai` — SAU cổng tắt AI.

Test cũ gọi thẳng `_nhom_hoc_hoi` nên vẫn đạt: hàm đúng, chỗ cắm sai. Test này
đi qua `handle_event` như tin thật.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class DuongVaoNhomHocHoiTests(unittest.TestCase):

    def _chay(self, *, sender: str, text: str = "hh 91 đúng", dap: str | None = "Em ghi rồi: #91 đúng."):
        import services.zalo_personal as zp

        ev = {"account_id": "acc1", "thread_id": "nhom_hoc_hoi", "sender_id": sender,
              "display_name": "Việt", "is_self": False, "text": text, "msg_id": "m1",
              "thread_type": 1, "mentions": [], "chat_name": "AI học hỏi"}
        goi = {"cham": 0, "ai": 0, "gui": []}

        def cham(e, thread, t):
            goi["cham"] += 1
            return dap

        with mock.patch.object(zp, "_parse_event", return_value=ev), \
             mock.patch.object(zp, "_dedup", return_value=False), \
             mock.patch.object(zp, "forward_to_ha"), \
             mock.patch("services.channel_activity.is_blacklisted", return_value=False), \
             mock.patch("services.channel_activity.record"), \
             mock.patch("services.channel_contacts.upsert"), \
             mock.patch("services.agent.capabilities.mention_required_for", return_value=(True, "@bot")), \
             mock.patch("services.agent.capabilities.forward_keyword_for", return_value=""), \
             mock.patch("services.agent.capabilities.forward_event", return_value=False), \
             mock.patch("services.agent.capabilities.ai_off_for", return_value=True), \
             mock.patch.object(zp, "_admin_thread_ids_for_account", return_value={"chu_may"}), \
             mock.patch.object(zp, "_nhom_hoc_hoi", side_effect=cham), \
             mock.patch.object(zp, "send_message", side_effect=lambda *a, **k: goi["gui"].append(a)), \
             mock.patch.object(zp, "_process_ai", side_effect=lambda e: goi.__setitem__("ai", goi["ai"] + 1)):
            zp.handle_event({}, "message")
        return goi

    def test_nhom_TAT_AI_van_cham_duoc_va_bot_dap(self):
        goi = self._chay(sender="chu_may")
        self.assertEqual(goi["cham"], 1, "câu chấm phải tới cổng chấm dù nhóm tắt AI")
        self.assertEqual(goi["gui"], [("nhom_hoc_hoi", "Em ghi rồi: #91 đúng.", 1)])
        self.assertEqual(goi["ai"], 0)

    def test_nguoi_KHONG_phai_admin_thi_khong_cham(self):
        """Đường này bỏ qua cổng lọc người, nên phải có cổng người riêng."""
        goi = self._chay(sender="nguoi_la")
        self.assertEqual(goi["cham"], 0)
        self.assertEqual(goi["gui"], [])

    def test_tin_khong_phai_cau_cham_di_tiep_nhu_cu(self):
        """Cổng chấm trả None (không phải kênh học hỏi / tin tag bot) → đi tiếp
        tới cổng tắt AI như mọi tin khác."""
        goi = self._chay(sender="chu_may", text="@bot bật đèn", dap=None)
        self.assertEqual(goi["cham"], 1)
        self.assertEqual(goi["gui"], [])
        self.assertEqual(goi["ai"], 0, "nhóm tắt AI thì vẫn im")


if __name__ == "__main__":
    unittest.main()
