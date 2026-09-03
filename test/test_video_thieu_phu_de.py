"""Video KHÔNG có phụ đề sẵn thì phải tải về tự nghe, không văng lỗi tiếng Anh.

Đường tải-về-tự-nghe đã có sẵn trong ``video_giao``, nhưng nó chỉ chạy khi
``thieu_phu_de_san(r)`` đúng — mà hàm đó so khớp với ĐÚNG MỘT chuỗi lỗi chuẩn.
Trong khi đó ``dich_video`` lại trả nguyên văn lỗi của thư viện lấy phụ đề, nên
chuỗi không bao giờ khớp: đường tự nghe không chạy, và người dùng nhận nguyên
khối tiếng Anh "Could not retrieve a transcript… Subtitles are disabled".

Bộ test giữ ranh giới giữa hai nhóm lỗi:

  1. Chỉ thiếu PHỤ ĐỀ (tắt phụ đề, không có track hợp, hoặc đường lấy phụ đề bị
     chặn) → đổi sang lỗi chuẩn để tầng gọi tải video về nghe.
  2. Bản thân VIDEO hỏng (không tồn tại, id sai, chặn tuổi, không phát được) →
     giữ nguyên lỗi thật. Tải mấy trăm MB rồi vẫn hỏng là phí trắng.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import video_dich as vd


def _loi(ten: str, cha: type = Exception) -> Exception:
    """Dựng một lỗi mang đúng TÊN LỚP của thư viện, không cần cài thư viện."""
    return type(ten, (cha,), {})("chi tiết bằng tiếng Anh của thư viện")


class PhanLoaiLoiTests(unittest.TestCase):
    def test_tat_phu_de_la_chi_thieu_phu_de(self):
        self.assertTrue(vd._chi_thieu_phu_de(_loi("TranscriptsDisabled")))

    def test_khong_co_track_hop_la_chi_thieu_phu_de(self):
        self.assertTrue(vd._chi_thieu_phu_de(_loi("NoTranscriptFound")))

    def test_bi_chan_van_con_cua_tai_ve(self):
        # Chỉ đường LẤY PHỤ ĐỀ bị chặn; đường tải hình đi lối khác.
        for ten in ("IpBlocked", "RequestBlocked", "PoTokenRequired"):
            self.assertTrue(vd._chi_thieu_phu_de(_loi(ten)), ten)

    def test_video_hong_han_thi_khong_tai_ve(self):
        for ten in ("VideoUnavailable", "InvalidVideoId", "AgeRestricted",
                    "VideoUnplayable", "YouTubeRequestFailed"):
            self.assertFalse(vd._chi_thieu_phu_de(_loi(ten)), ten)

    def test_nhan_ra_ca_lop_con(self):
        # Thư viện có cây kế thừa; bắt theo tên trên cả MRO nên lớp con vẫn khớp.
        cha = type("TranscriptsDisabled", (Exception,), {})
        con = type("MotLoiRieng", (cha,), {})
        self.assertTrue(vd._chi_thieu_phu_de(con("x")))


class DichVideoTraLoiChuanTests(unittest.TestCase):
    """`dich_video` phải đổi lỗi "tắt phụ đề" thành lỗi CHUẨN, để `video_giao`
    nhận ra mà tải về tự nghe."""

    def _chay(self, exc: Exception) -> dict:
        with mock.patch.object(vd, "lay_phu_de", side_effect=exc):
            return vd.dich_video("https://www.youtube.com/watch?v=LGcGFU_Hi9U", "vi")

    def test_tat_phu_de_thi_bao_lỗi_chuan_va_kich_hoat_tu_nghe(self):
        r = self._chay(_loi("TranscriptsDisabled"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], vd.LOI_CHUA_CO_TIENG)
        self.assertTrue(vd.thieu_phu_de_san(r))   # đây là công tắc của đường tự nghe

    def test_video_hong_thi_giu_nguyen_loi_that(self):
        r = self._chay(_loi("VideoUnavailable"))
        self.assertFalse(r["ok"])
        self.assertIn("chi tiết bằng tiếng Anh", r["error"])
        self.assertFalse(vd.thieu_phu_de_san(r))  # đừng tải mấy trăm MB vô ích


if __name__ == "__main__":
    unittest.main()
