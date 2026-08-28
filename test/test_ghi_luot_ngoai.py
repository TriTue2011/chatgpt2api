"""Ghi lượt xử lý NGOÀI LLM (vd /dich) vào lịch sử — orchestrator.ghi_luot_ngoai.

Lỗi thật (Zalo 28/08): /dich xử lý thẳng, không vào lịch sử LLM; câu hỏi tiếp
("còn nghĩa khác không") mất ngữ cảnh, LLM bám chuyện cũ trả lời lạc đề.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import orchestrator as orc


class GhiLuotNgoaiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.uid = "zalo_testthread"
        orc._history.pop(self.uid, None)

    def tearDown(self) -> None:
        orc._history.pop(self.uid, None)

    def test_ghi_them_cap_user_assistant(self):
        orc.ghi_luot_ngoai(self.uid, "/dich stroke", "🌐 en → vi\nđột quỵ")
        hist = orc._get_history(self.uid)
        self.assertEqual(hist[-2], {"role": "user", "content": "/dich stroke"})
        self.assertEqual(hist[-1]["role"], "assistant")
        self.assertIn("đột quỵ", hist[-1]["content"])

    def test_cau_hoi_tiep_thay_duoc_ngu_canh_stroke(self):
        orc.ghi_luot_ngoai(self.uid, "/dich stroke", "🌐 en → vi\nđột quỵ")
        # câu hỏi tiếp sẽ được orchestrate append; ở đây kiểm lịch sử đã có stroke
        noi_dung = " ".join(str(t.get("content") or "") for t in orc._get_history(self.uid))
        self.assertIn("stroke", noi_dung)

    def test_rong_thi_khong_ghi(self):
        orc.ghi_luot_ngoai(self.uid, "", "có nội dung")
        orc.ghi_luot_ngoai(self.uid, "có nội dung", "")
        self.assertEqual(orc._history.get(self.uid, []), [])

    def test_khong_nem_loi_ra_ngoai(self):
        # user_id lạ / lịch sử hỏng cũng không được ném (lệnh đã trả lời xong)
        try:
            orc.ghi_luot_ngoai(self.uid, "a", "b")
        except Exception as e:
            self.fail(f"không được ném lỗi: {e}")


if __name__ == "__main__":
    unittest.main()
