"""Câu nói kích hoạt năng lực khác → đóng bản chờ cũ, chạy việc mới.

Quy tắc chủ máy chốt 05/08. Nhận diện CỐ Ý HẸP: nhận nhầm một câu trả lời thành
yêu cầu mới thì người dùng mất bản chờ và phải gửi lại tệp — khó chịu hơn hẳn so
với bỏ sót.
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.yeu_cau_moi import la_yeu_cau_moi as la_moi  # noqa: E402


class NhanRaYeuCauMoiTests(unittest.TestCase):

    def test_cac_lenh_thuoc_nang_luc_khac(self):
        for c in ("gửi file bao-cao.docx cho nhóm A",
                  "gửi tin cho anh Hùng giúp em",
                  "bật đèn phòng khách lên",
                  "tắt điều hoà phòng ngủ đi",
                  "bây giờ là mấy giờ rồi",
                  "nhắc tôi lúc 8 giờ tối mai",
                  "tra cứu giúp em giá vàng",
                  "thời tiết Hà Nội ngày mai thế nào",
                  "lưu lên kho đám mây giúp em"):
            with self.subTest(c=c):
                self.assertTrue(la_moi(c), f"bỏ sót yêu cầu mới: {c}")


class KhongNhanNhamCauTraLoiTests(unittest.TestCase):
    """Đây là phía nguy hiểm — nhận nhầm là người dùng mất bản chờ."""

    def test_chon_so_trong_menu(self):
        for c in ("1", "2", "3", "1. Nạp RAG kiến thức", "chọn 2"):
            with self.subTest(c=c):
                self.assertFalse(la_moi(c))

    def test_tra_loi_bang_tu_khoa(self):
        for c in ("phân tích", "nạp rag kiến thức", "chuyển word", "tóm tắt"):
            with self.subTest(c=c):
                self.assertFalse(la_moi(c))

    def test_lop_va_mon_cho_rag_teacher(self):
        for c in ("lớp 4 toán", "lớp 5 tiếng việt", "sgk lớp 1 toán"):
            with self.subTest(c=c):
                self.assertFalse(la_moi(c))

    def test_mo_ta_anh_muon_tao(self):
        """Mô tả ảnh là câu tự do — không được nhận nhầm thành mệnh lệnh."""
        for c in ("một con mèo đang ngủ trên ghế sofa màu xanh",
                  "cảnh hoàng hôn trên biển có thuyền buồm"):
            with self.subTest(c=c):
                self.assertFalse(la_moi(c))

    def test_cau_rong_hoac_qua_ngan(self):
        for c in ("", "  ", "ok", "gửi", "ừ"):
            with self.subTest(c=c):
                self.assertFalse(la_moi(c))


class ApVaoLuongZalopTests(unittest.TestCase):
    """Cả hai nhánh chờ (tài liệu và ảnh) đều phải xét yêu cầu mới trước."""

    def test_hai_nhanh_deu_dong_ban_cho_cu(self):
        src = (GOC / "services" / "zalo_personal.py").read_text("utf-8")
        self.assertIn("_la_moi_pdf(text)", src, "nhánh tài liệu chưa xét yêu cầu mới")
        self.assertIn("_la_moi(text)", src, "nhánh ảnh chưa xét yêu cầu mới")
        self.assertIn("_pi.pop_pending(pkey)", src)
        self.assertIn("_phi.pop_pending_full(pkey)", src)


if __name__ == "__main__":
    unittest.main()
