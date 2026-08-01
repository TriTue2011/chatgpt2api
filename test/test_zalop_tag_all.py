"""Tag @All cả nhóm trên Zalo cá nhân.

zca-js hiểu mention {uid:'-1'} là 'nhắc mọi người' (đã xác minh trong thư viện:
type = uid=='-1' ? 1 : 0). Nhưng mention phải NEO vào một đoạn chữ có thật trong
tin, nên bot chèn '@All ' đầu tin rồi gắn {pos:0, uid:'-1', len:4}.

Ba chỗ dễ sai được khoá ở đây:
  * chỉ NHÓM (thread_type=1) mới tag — chat 1-1 chèn '@All' là vô nghĩa;
  * chèn '@All ' làm DỜI vị trí mọi vùng đậm đi 5 ('@All ' = 5 ký tự) — không
    dời thì chữ đậm tô lệch;
  * chỉ tag ở khúc ĐẦU (tin dài cắt nhiều khúc, không nhắc lại mỗi khúc).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import zalo_personal as zp


def _bat_payload():
    """Chặn _request, trả danh sách payload đã gửi."""
    goi: list[dict] = []

    def fake(method, path, payload=None, **k):
        goi.append(payload or {})
        return {"ok": True, "data": {"success": True}}
    return goi, fake


class TestTagAll(unittest.TestCase):
    def _gui(self, thread_id, text, ttype, mention_all):
        goi, fake = _bat_payload()
        with patch.object(zp, "_request", side_effect=fake), \
             patch.object(zp, "_account_for_send", return_value="acc1"):
            zp.send_message(thread_id, text, ttype, account="acc1",
                            mention_all=mention_all)
        return [g.get("message", {}) for g in goi]

    def test_nhom_co_prefix_va_mention(self):
        m = self._gui("g1", "cả nhà họp nhé", 1, True)[0]
        self.assertTrue(m["msg"].startswith("@All "))
        self.assertEqual(m["mentions"], [{"pos": 0, "uid": "-1", "len": 4}])

    def test_style_doi_dung_5(self):
        # 'cả nhà ' = 7 ký tự → 'họp' đậm ở vị trí 7; sau '@All ' phải là 12.
        m = self._gui("g1", "cả nhà **họp** nhé", 1, True)[0]
        starts = [s["start"] for s in m.get("styles", [])]
        self.assertIn(12, starts)

    def test_chat_1_1_khong_chen(self):
        m = self._gui("u1", "xin chào bạn", 0, True)[0]
        self.assertFalse(m["msg"].startswith("@All"))
        self.assertNotIn("mentions", m)

    def test_khong_bat_co_thi_nhu_cu(self):
        m = self._gui("g1", "tin thường", 1, False)[0]
        self.assertNotIn("mentions", m)
        self.assertEqual(m["msg"], "tin thường")

    def test_chi_khuc_dau_co_mention(self):
        # Tin dài > _MAX_LEN → nhiều khúc; chỉ khúc đầu mang @All.
        dai = ("dòng nội dung khá dài. " * 400).strip()
        parts = self._gui("g1", dai, 1, True)
        self.assertGreater(len(parts), 1, "phải cắt nhiều khúc")
        self.assertTrue(parts[0]["msg"].startswith("@All "))
        for p in parts[1:]:
            self.assertNotIn("mentions", p)
            self.assertFalse(p["msg"].startswith("@All"))


if __name__ == "__main__":
    unittest.main()
