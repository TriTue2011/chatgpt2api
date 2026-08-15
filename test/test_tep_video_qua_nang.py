"""Tệp video quá nặng: nói đúng lý do, và lời mời gửi link phải có hiệu lực.

Ca thật 16/08/2026 trên bot Zalo:

    01:03:07  người dùng gửi .mp4 (Zalo khai fileSize = 291.706.414 byte)
    01:03:12  bot: "Không tải được tệp (quá 250MB hoặc mạng lỗi). Video
              YouTube thì gửi em link sẽ nhanh hơn nhiều ạ."
    01:04:00  người dùng gửi đúng link YouTube như bot mời
    01:04:08  bot: "Anh muốn em xử lý video theo hướng nào ạ? Ví dụ: Tóm tắt…"

Ba chỗ hỏng nằm sau đoạn hội thoại đó:

1. Cỡ tệp Zalo khai trong ``content.params`` bị bỏ đi lúc dựng sự kiện, nên
   bot không biết trước là quá cỡ — nó tải đủ 250 MB rồi mới bỏ dở.
2. Vì không biết, câu trả lời phải đoán giữa hai nguyên nhân ("quá 250MB HOẶC
   mạng lỗi"), trong khi máy chủ đã ghi rõ "Nội dung vượt trần 262144000 byte".
3. Bot mời gửi link, người dùng gửi link, rồi câu đó rơi xuống LLM và bị hỏi
   lại — lời mời của chính bot thành lời hứa suông.
"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import zalo_personal as zp  # noqa: E402

TEP = ("YTSave_YouTube_Best-of-Elsa-and-Anna-s-Magical-Moments-"
       "_Media_ekFm9Y-lsAc_002_720p.mp4")
LINK = "https://www.youtube.com/watch?v=ekFm9Y-lsAc&t=1204s"
PKEY = "zalop:acc1:thread1:nguoi1"


class TestCoTepTuSuKien(unittest.TestCase):
    """Cỡ tệp phải đi được từ webhook Zalo vào sự kiện."""

    def _su_kien(self, params) -> dict:
        return zp._parse_event({
            "threadId": "thread1", "type": "0", "_accountId": "acc1",
            "data": {"uidFrom": "nguoi1", "msgType": "share.file",
                     "msgId": "m1",
                     "content": {"href": "https://example.com/a.mp4",
                                 "title": TEP, "params": params}},
        })

    def test_doc_duoc_fileSize_dang_chuoi_JSON(self) -> None:
        ev = self._su_kien(json.dumps({"fileSize": "291706414", "fileExt": "mp4"}))
        self.assertEqual(ev["attachment_size"], 291706414)
        self.assertEqual(ev["file_name"], TEP)

    def test_params_hong_thi_coi_nhu_khong_biet_co(self) -> None:
        self.assertEqual(self._su_kien("{không phải json")["attachment_size"], 0)
        self.assertEqual(self._su_kien(None)["attachment_size"], 0)


class TestSoMoiGuiLink(unittest.TestCase):
    def setUp(self) -> None:
        zp._MOI_LINK.clear()

    def tearDown(self) -> None:
        zp._MOI_LINK.clear()

    def test_moi_roi_thi_dang_cho_trong_han(self) -> None:
        self.assertFalse(zp._dang_cho_link(PKEY))
        zp._moi_gui_link(PKEY)
        self.assertTrue(zp._dang_cho_link(PKEY))

    def test_het_han_thi_thoi_va_don_so(self) -> None:
        zp._moi_gui_link(PKEY)
        with mock.patch.object(zp.time, "time",
                               return_value=zp.time.time() + zp._MOI_LINK_TTL + 1):
            self.assertFalse(zp._dang_cho_link(PKEY))
        self.assertNotIn(PKEY, zp._MOI_LINK)

    def test_moi_nguoi_mot_so_rieng(self) -> None:
        zp._moi_gui_link(PKEY)
        self.assertFalse(zp._dang_cho_link("zalop:acc1:thread1:nguoi_khac"))


class TestLinkSauLoiMoi(unittest.TestCase):
    """Link gửi sau lời mời phải mở menu dịch, không rơi xuống LLM."""

    def setUp(self) -> None:
        zp._MOI_LINK.clear()
        from services import dich_cho as dc
        dc.pop_pending(PKEY)

    def tearDown(self) -> None:
        zp._MOI_LINK.clear()
        from services import dich_cho as dc
        dc.pop_pending(PKEY)

    def test_link_mo_menu_dich_va_ghi_ban_cho(self) -> None:
        from services import dich_cho as dc

        zp._moi_gui_link(PKEY)
        self.assertTrue(zp._dang_cho_link(PKEY))

        # Đúng nhánh mà _process_ai chạy: còn hạn + là link video → set_pending.
        from services import video_dich as vd
        self.assertTrue(vd.la_link_video(LINK), "link YouTube phải nhận ra được")
        dc.set_pending(PKEY, url=vd.la_link_video(LINK), ten=LINK)

        pend = dc.get_pending(PKEY)
        self.assertIsNotNone(pend)
        self.assertIn("youtube.com", str((pend or {}).get("url") or ""))
        self.assertIn("🎬", dc.menu_buoc(PKEY))


if __name__ == "__main__":
    unittest.main()
