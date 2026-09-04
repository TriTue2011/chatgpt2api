"""Ảnh trả về NHÚNG trong chữ phải ra ẢNH, không ra tệp Word chứa base64.

Lỗi thật 04/09 13:38 (Zalo cá nhân, chủ máy phát hiện): nhắn "Tạo ảnh em bé",
chọn model, rồi nhận về một tệp `.docx` 38 KB. Mở ra là chuỗi base64 hỏng.

Ba chỗ hỏng xếp chồng, mỗi chỗ đều "hợp lý cục bộ":

  1. Nhà cung cấp trả ảnh THẲNG trong chữ (`![image_1](data:image/png;base64,…)`)
     thay vì đặt vào khoá `image_url`.
  2. `tool_compress` nén mọi kết quả tool, không chừa ảnh → cắt base64 giữa
     chừng (còn 3.945 ký tự, độ dài không chia hết cho 4 → giải mã lỗi).
  3. Kênh chỉ tìm ảnh ở khoá `image_url`, không thấy nên gửi chữ; chữ 4.124 ký
     tự vượt ngưỡng nên rơi tiếp vào đường "đóng thành Word".

Ba test dưới khoá đúng ba chỗ đó.
"""
from __future__ import annotations

import base64
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import tool_compress as tc  # noqa: E402
from services import zalo_personal as zp  # noqa: E402


def _anh_that(n: int = 4000) -> str:
    """Chuỗi base64 của một khối byte mở đầu bằng chữ ký PNG."""
    return base64.b64encode(bytes.fromhex("89504e470d0a1a0a") + b"x" * n).decode()


def _van_ban_co_anh(n: int = 4000) -> str:
    return "Ảnh của anh đây ạ:\n![image_1](data:image/png;base64," + _anh_that(n) + ")"


class ToolCompressKhongDuocNenAnhTests(unittest.TestCase):
    """Base64 không phải văn xuôi — cắt cho ngắn là ảnh hỏng hẳn."""

    def test_van_ban_co_anh_thi_giu_nguyen(self):
        van = _van_ban_co_anh()
        self.assertGreater(len(van), tc.max_chars(), "phải đủ dài để bình thường bị nén")
        self.assertEqual(tc.compress(van, tool_name="ve_anh"), van)

    def test_nhan_dien_anh_nhung(self):
        self.assertTrue(tc.co_anh_nhung(_van_ban_co_anh()))
        self.assertTrue(tc.co_anh_nhung("x data:image/jpeg;base64,AAAA"))

    def test_van_ban_thuong_van_bi_nen_nhu_cu(self):
        """Chỉ chừa ảnh, không tắt nén cho mọi thứ."""
        dai = "Một câu rất dài. " * 800
        self.assertLess(len(tc.compress(dai, tool_name="doc_web")), len(dai))


class BocAnhNhungTests(unittest.TestCase):
    """Ảnh trong chữ phải được tách ra thành URL gửi được."""

    def test_boc_duoc_anh_va_lam_sach_chu(self):
        chu, anh = zp._boc_anh_nhung(_van_ban_co_anh())
        self.assertEqual(len(anh), 1)
        self.assertEqual(chu, "Ảnh của anh đây ạ:", "phải gỡ sạch cả cú pháp markdown")
        self.assertNotIn("data:image", chu)

    def test_khong_co_anh_thi_tra_nguyen(self):
        self.assertEqual(zp._boc_anh_nhung("câu thường"), ("câu thường", []))

    def test_base64_giai_ma_duoc_nhung_khong_phai_anh(self):
        """"abcQ" đúng bộ bốn nên giải mã ra 3 byte — nhưng không phải ảnh.

        Không kiểm magic bytes thì mình lưu 3 byte rác thành .png rồi gửi đi.
        """
        chu, anh = zp._boc_anh_nhung("Đây ạ: data:image/png;base64,abcQ")
        self.assertEqual(anh, [], "byte không phải ảnh thì đừng gửi")
        self.assertNotIn("data:image", chu, "chuỗi rác phải bị gỡ")

    def test_base64_bi_cat_cut_thi_bo(self):
        """Đúng ca 04/09: base64 bị nén cắt, độ dài không chia hết cho 4.

        Tuyệt đối KHÔNG tự đệm "=" cho đủ — đệm vào thì nó giải mã ra một mớ
        byte cụt và mình gửi đi một tấm ảnh hỏng.
        """
        cut = _anh_that(3000)[:-3]          # bẻ gãy bộ bốn
        chu, anh = zp._boc_anh_nhung("Đây ạ: data:image/png;base64," + cut)
        self.assertEqual(anh, [], "base64 cụt thì đừng dựng ảnh")
        self.assertNotIn("data:image", chu)


class KhongDongWordKhiConAnhTests(unittest.TestCase):
    """Lưới an toàn cuối: tệp .docx chứa base64 là rác thuần tuý."""

    def test_chu_con_base64_thi_khong_dong_word(self):
        rac = "x" * (zp.NGUONG_TRA_LOI_WORD + 200) + "data:image/png;base64,abcQ"
        self.assertFalse(zp._tra_loi_dai_ra_word("t", 0, rac))

    def test_chu_dai_binh_thuong_van_dong_word(self):
        """Không được tắt nhầm cả đường đóng Word đang chạy đúng."""
        from unittest.mock import patch
        dai = "Một đoạn văn dài. " * 400
        self.assertGreater(len(dai), zp.NGUONG_TRA_LOI_WORD)
        with patch.object(zp, "_serve_bytes", return_value=None) as gui:
            self.assertTrue(zp._tra_loi_dai_ra_word("t", 0, dai))
            self.assertTrue(gui.called)


if __name__ == "__main__":
    unittest.main()
