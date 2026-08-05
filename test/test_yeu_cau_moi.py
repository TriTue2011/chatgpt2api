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


class ApChoCaBaKenhTests(unittest.TestCase):
    """Cả ba kênh, cả hai nhánh chờ (tài liệu và ảnh) đều phải xét yêu cầu mới."""

    KENH = ("zalo_personal.py", "telegram_bot.py", "zalo_bot.py")

    def _src(self, tep: str) -> str:
        return (GOC / "services" / tep).read_text("utf-8")

    def test_moi_kenh_deu_goi_bo_nhan_dien(self):
        for tep in self.KENH:
            with self.subTest(tep=tep):
                self.assertIn("la_yeu_cau_moi", self._src(tep),
                              f"{tep} chưa xét yêu cầu mới")

    def test_moi_kenh_deu_dong_ca_hai_loai_ban_cho(self):
        for tep in self.KENH:
            with self.subTest(tep=tep):
                s = self._src(tep)
                self.assertIn("_pi.pop_pending(", s, f"{tep}: chưa đóng bản chờ tài liệu")
                self.assertIn("_phi.pop_pending_full(", s, f"{tep}: chưa đóng bản chờ ảnh")


class KhoaTaoVaTraPhaiKhopTests(unittest.TestCase):
    """Khoá lúc TẠO bản chờ phải khớp từng chữ với khoá lúc ĐỌC.

    Telegram và Zalo Bot viết tay khoá ở chỗ tạo thay vì dùng biến chung, nên khi
    thêm người gửi vào khoá đọc mà quên chỗ tạo thì tạo một đằng tra một nẻo:
    người dùng gửi tệp, chọn số, và không bao giờ ra gì.
    """

    def test_moi_khoa_ban_cho_deu_kem_nguoi_gui(self):
        import re
        for tep in ("telegram_bot.py", "zalo_bot.py"):
            src = (GOC / "services" / tep).read_text("utf-8")
            # Mọi chuỗi khoá bản chờ dạng f"tg:…" / f"zalo:…" có chat_id.
            for m in re.finditer(r'f"(tg|zalo):\{_bot_id\(\)\}:\{chat_id\}[^"]*"', src):
                with self.subTest(tep=tep, khoa=m.group(0)):
                    self.assertIn("user_id", m.group(0),
                                  f"{tep}: khoá bản chờ thiếu người gửi → lệch khoá")


if __name__ == "__main__":
    unittest.main()
