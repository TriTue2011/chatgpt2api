"""Bot vừa hỏi một câu MỞ thì câu trả lời không được coi là "yêu cầu mới".

Lỗi thật (chủ máy, Zalo Bot 04/09 10:38, có ảnh chụp màn hình):

  1. Người dùng gửi ảnh → bot hiện menu 1–7.
  2. Gõ "3" (Phân tích ảnh) → bot hỏi «em cần câu hỏi/yêu cầu cụ thể — ví dụ
     `mô tả ảnh` · `đọc chữ trong ảnh`».
  3. Trả lời «Mô tả ảnh và tìm kiếm thông tin» → chữ "tìm kiếm" khớp `_MENH_LENH`
     nên `la_yeu_cau_moi` trả True, bản chờ bị vứt, ẢNH MẤT, model quay ra bảo
     "Dạ anh gửi ảnh lên đây giúp em nhé".

Trớ trêu: câu trả lời chứa đúng ví dụ bot vừa gợi ý. Docstring của
`yeu_cau_moi` đã nói kiểu hỏng này khó chịu hơn hẳn bỏ sót, và
`facebook_page.py` đã né bằng cách không dùng cổng này — chỉ luồng ảnh/PDF là
còn sót.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.yeu_cau_moi import (  # noqa: E402
    la_yeu_cau_moi,
    nen_dong_ban_cho,
)

#: Đúng câu chủ máy đã gõ lúc 10:38.
CAU_THAT = "Mô tả ảnh và tìm kiếm thông tin"


class BuocHoiMoTests(unittest.TestCase):
    """Ở bước hỏi mở, MỌI câu tới đều là câu trả lời."""

    def test_cau_that_khong_lam_mat_ban_cho(self):
        self.assertFalse(nen_dong_ban_cho(CAU_THAT, "need_prompt"),
                         "câu trả lời cho câu hỏi mở không được đóng bản chờ")

    def test_teacher_meta_cung_duoc_bao_ve(self):
        self.assertFalse(nen_dong_ban_cho("gửi file cho nhóm A", "teacher_meta"))

    def test_cac_vi_du_bot_tu_goi_y_deu_an_toan(self):
        """Bot gợi ý gì thì người dùng gõ nấy — không câu nào được làm mất ảnh."""
        for c in ("mô tả ảnh", "đọc chữ trong ảnh", "ảnh có mấy người?",
                  "mô tả ảnh và tra cứu thêm", "đọc chữ trong ảnh rồi dịch giúp em",
                  "tóm tắt bài trong ảnh"):
            with self.subTest(c=c):
                self.assertFalse(nen_dong_ban_cho(c, "need_prompt"))


class BuocChonVanGiuCongTests(unittest.TestCase):
    """Ở bước `choose` cổng vẫn phải chạy — đừng sửa lỗi này thành lỗi kia."""

    def test_yeu_cau_moi_that_van_dong_ban_cho(self):
        self.assertTrue(nen_dong_ban_cho(CAU_THAT, "choose"))
        self.assertTrue(nen_dong_ban_cho("gửi file cho nhóm A", "choose"))
        self.assertTrue(nen_dong_ban_cho("bật đèn phòng khách giúp anh", "choose"))

    def test_khong_truyen_stage_thi_giu_hanh_vi_cu(self):
        """Mặc định (stage rỗng) phải y hệt `la_yeu_cau_moi` — không đổi ngầm."""
        for c in (CAU_THAT, "gửi file cho nhóm A", "1", "mô tả ảnh", ""):
            with self.subTest(c=c):
                self.assertEqual(nen_dong_ban_cho(c), la_yeu_cau_moi(c))

    def test_chon_so_van_khong_bi_coi_la_yeu_cau_moi(self):
        self.assertFalse(nen_dong_ban_cho("3", "choose"))


class MuiGioTrichDanTests(unittest.TestCase):
    """Giờ trong câu trích dẫn phải là giờ Việt Nam, không phụ thuộc TZ máy."""

    def test_ghim_gio_viet_nam(self):
        from services.agent import trich_dan as td
        # 2025-09-04 15:33:20 UTC = 22:33 giờ VN.
        self.assertEqual(td._luc(1757000000), " lúc 22:33 04/09/2025")

    def test_khong_co_moc_thi_rong(self):
        from services.agent import trich_dan as td
        self.assertEqual(td._luc(0), "")
        self.assertEqual(td._luc(None), "")


if __name__ == "__main__":
    unittest.main()
