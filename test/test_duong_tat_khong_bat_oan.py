"""Hai đường tắt của trợ lý không được cướp câu nói thường.

Đo thật trên Zalo cá nhân chiều 24/08/2026, khi chủ máy đang phàn nàn rằng bấm
mã mục "E1" không ra tin:

  16:55:52  "Nhầm à E1 tin tức mà"
            → khớp chữ "tin tức" ⇒ đường tắt BẢN TIN đem NGUYÊN VĂN câu ấy đi
              tra tin ⇒ "Chưa tìm thấy tin nào về 'Nhầm E1 mà'". Người dùng sửa
              lưng bot thì bị bot tra cứu chính lời sửa lưng.

  16:58:42  "Em xem lại nhé, em trả lời anh tin tức hôm nay có E1, anh chọn sao
             không trả lời"
            → khớp đủ ba dấu hiệu của đường tắt THƯ VIỆN MEDIA (động từ "xem" ·
              dấu hiệu kho "xem lại" · từ chỉ loại "anh") ⇒ bot gửi về một tấm
              ảnh trong thư viện, giữa cuộc nói chuyện về tin tức. Chữ "anh" ở
              đây là ĐẠI TỪ XƯNG HÔ, không phải "ảnh" gõ thiếu dấu.

Cả hai đường tắt đều đúng khi bắt trúng, nên bản sửa phải giữ nguyên phần bắt
trúng — mỗi ca chặn đi kèm một ca đối chứng vẫn phải chạy.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent.orchestrator import (  # noqa: E402
    _la_yeu_cau_tin_tuc, _tat_lay_media,
)


class BanTinKhongCuopCauPhanNanTests(unittest.TestCase):
    def test_cau_noi_ve_ban_tin_cu_khong_phai_xin_tin_moi(self):
        for cau in ("Nhầm à E1 tin tức mà",
                    "tin tức sao không thấy",
                    "em trả lời tin tức thiếu rồi",
                    "anh hỏi tin tức mà",
                    "tin tức có lựa chọn E1 mà"):
            self.assertIsNone(_la_yeu_cau_tin_tuc(cau), f"cướp mất: {cau!r}")

    def test_cau_xin_tin_that_van_vao_duong_tat(self):
        self.assertEqual(_la_yeu_cau_tin_tuc("Tin tức hôm nay"), "moi")
        self.assertEqual(_la_yeu_cau_tin_tuc("bản tin sáng nay"), "moi")
        self.assertEqual(_la_yeu_cau_tin_tuc("tin nóng"), "moi")
        self.assertEqual(_la_yeu_cau_tin_tuc("tin tức hôm qua"), "ngay")


class ThuVienMediaKhongCuopDaiTuAnhTests(unittest.TestCase):
    def test_dai_tu_anh_trong_cau_co_dau_khong_thanh_yeu_cau_anh(self):
        cau = ("Em xem lại nhé, em trả lời anh tin tức hôm nay có E1, "
               "anh chọn sao không trả lời")
        self.assertIsNone(_tat_lay_media(cau))

    def test_cau_co_dau_van_xin_duoc_anh_khi_viet_dung_chinh_ta(self):
        ra = _tat_lay_media("Gửi anh 3 ảnh mới nhất trong thư viện ảnh")
        self.assertIsNotNone(ra)
        self.assertEqual(ra["kind"], "image")
        self.assertEqual(ra["so_luong"], 3)
        self.assertEqual(ra["scope"], "all")

    def test_cau_go_khong_dau_van_hieu_anh_la_anh(self):
        """Bỏ hẳn "anh" khỏi bộ từ khoá là mất luôn người gõ không dấu."""
        ra = _tat_lay_media("cho anh xem 3 anh moi nhat trong thu vien")
        self.assertIsNotNone(ra)
        self.assertEqual(ra["kind"], "image")

    def test_loai_media_khac_khong_bi_anh_huong(self):
        ra = _tat_lay_media("cho anh xem lại video vừa tạo")
        self.assertIsNotNone(ra)
        self.assertEqual(ra["kind"], "video")


if __name__ == "__main__":
    unittest.main()
