"""Vòng 2FA phải NÓI ĐƯỢC nó đang nhìn trang nào — và biết captcha sau mật khẩu.

SỰ CỐ 12/09/2026. Một lượt đăng nhập Google: ô "Tôi không phải là người máy" đã
tự tích xong lúc 21:34:42, luồng vào tới ô mật khẩu lúc 21:34:44, rồi chết lúc
21:39:39. Bốn phút ở giữa chỉ để lại đúng ba dòng log lặp lại:

    method-picker options=[]
    method-picker visible but no Authenticator selector matched
    method-picker visible but no Tap selector matched

BA LỖI CHỒNG NHAU, cả ba đều là "không ghi lại thứ đã nhìn thấy":

1. Câu log KHẲNG ĐỊNH SAI. "method-picker visible" nằm ở cuối hàm và in ra mỗi
   khi không bộ chọn nào khớp — hàm chưa bao giờ kiểm bảng chọn có hiện hay
   không. Người đọc log (và cả máy) tin rằng bảng chọn đang hiện mà chỉ hỏng ở
   khâu bộ chọn, trong khi `options=[]` nói ngược lại: trang KHÔNG có lấy một
   dòng `li`/`div[role=link]` nào, tức không hề có bảng chọn.

2. Vòng 2FA không ghi trang. Không URL, không trạng thái — nên hỏng vì captcha,
   vì đứng nguyên ở màn mật khẩu, hay vì bảng chọn lạ đều để lại log y hệt nhau.

3. Vòng trước-mật-khẩu biết xử lý `/challenge/recaptcha`; vòng 2FA thì KHÔNG có
   nhánh nào. Google bung captcha sau mật khẩu là vòng quay đủ 240 giây rồi
   chết với lý do "Hết 4 phút mà chưa hoàn tất 2FA", không ai biết vướng gì.

Test đọc THẲNG mã nguồn, theo đúng nếp của `test_login_bi_evict_va_recaptcha.py`
và `test_auto_login_buoc_mat_khau.py`: thứ cần khoá là vài quyết định logic nằm
gọn trong một vòng lặp, dựng Playwright giả cho việc đó là đổi một phép đo chắc
chắn lấy một phép đo phụ thuộc mock.
"""
from __future__ import annotations

import pathlib
import unittest

NGUON = (pathlib.Path(__file__).resolve().parents[1]
         / "captcha-solver" / "src" / "auto_login.py").read_text("utf-8")


def _than(nguon: str, tu: str, den: str) -> str:
    i = nguon.index(tu)
    return nguon[i:nguon.index(den, i)]


def _bo_chu_thich(khuc: str) -> str:
    """Bỏ dòng chú thích: chú thích của bản vá có NHẮC LẠI câu cũ để giải
    thích, nên tìm nguyên văn sẽ bắt phải chính chú thích đó."""
    return "\n".join(d for d in khuc.splitlines()
                     if not d.lstrip().startswith("#"))


VONG_2FA = _than(NGUON, "# ── 2FA poll loop ──", "async def _run(")
MA = _bo_chu_thich(VONG_2FA)


class KhongKhangDinhBangChonDangHienTests(unittest.TestCase):
    """Log chỉ được nói thứ nó đã kiểm."""

    def test_khong_con_cau_noi_picker_visible(self):
        self.assertNotIn("picker visible", _bo_chu_thich(NGUON),
                         "câu này khẳng định bảng chọn đang hiện trong khi hàm "
                         "chưa hề kiểm — chính nó làm đọc nhầm lượt 21:35–21:39")

    def test_van_con_ghi_lai_cac_dong_doc_duoc(self):
        """Bỏ lời khẳng định sai thì vẫn phải giữ dấu vết thật."""
        self.assertIn("method-picker options=%r", NGUON)


class VongHaiFAGhiLaiTrangDangNhinTests(unittest.TestCase):
    """Mỗi vòng phải ghi được: trang nào, mấy dòng chọn, có khung captcha không."""

    def test_co_ghi_duong_trang(self):
        self.assertIn("trang=%s", MA,
                      "không ghi trang thì lần hỏng sau lại phải đoán")

    def test_ghi_duong_dan_chu_khong_ghi_query(self):
        """Query mang `TL=` là mã phiên — không được rơi vào log."""
        self.assertIn("urlparse(page.url", MA)
        self.assertIn(".path", MA)

    def test_chi_ghi_khi_co_DOI(self):
        """Vòng quay 2 giây/lượt; ghi mỗi lượt là lấp log bằng bản sao."""
        self.assertIn("dau_van != dau_van_truoc", MA)

    def test_dem_so_dong_chon_va_khung_captcha(self):
        self.assertIn("so_dong_chon", MA)
        self.assertIn('iframe[src*="/recaptcha/"]', MA)


class KhongDoBangChonKhiTrangKhongCoDongNaoTests(unittest.TestCase):
    """0 dòng chọn = không có bảng chọn. Dò tiếp chỉ tốn giờ và đẻ log sai."""

    def test_co_cong_chan_truoc_khi_goi_ba_ham_do(self):
        self.assertIn("if not picker_clicked and so_dong_chon > 0:", MA)

    def test_cong_chan_dung_TRUOC_loi_goi_dau_tien(self):
        self.assertLess(MA.index("so_dong_chon > 0"),
                        MA.index("_pick_authenticator_method"))


class ReCaptchaSauMatKhauPhaiCoNhanhTests(unittest.TestCase):
    """Vòng trước-mật-khẩu có nhánh captcha; vòng này cũng phải có.

    Các phép đo dưới đây soi thẳng THÂN VÒNG 2FA (`MA`) chứ không cắt ra một
    lát con. Đo A/B 12/09/2026: bản đầu cắt lát bằng `_than(...)` ngay trong
    thân lớp, nên chạy trên mã CŨ (chưa có nhánh) thì `.index()` ném
    ValueError lúc pytest thu thập — cả module vỡ và 12 phép đo còn lại không
    bao giờ chạy. Thiếu tính năng phải làm ĐỎ TỪNG phép đo, không phải làm
    hỏng cả lượt chạy.
    """

    def test_tu_tich_o_bang_dung_ham_da_chay_that(self):
        self.assertIn("tich_o_recaptcha", MA,
                      "hàm này đã tích được thật lúc 21:34 — dùng lại, "
                      "đừng viết bộ dò thứ hai")

    def test_chi_thu_DUNG_MOT_LAN(self):
        """Đấm vòng vòng chỉ càng giống bot, đúng thứ làm Google siết thêm."""
        self.assertIn("captcha_sau_mk_da_thu = True", MA)
        self.assertLess(MA.index("captcha_sau_mk_da_thu = True"),
                        MA.index("tich_o_recaptcha"))

    def test_hong_thi_gan_need_captcha_chu_khong_quay_im_lang(self):
        self.assertIn('"need_captcha"', MA,
                      "need_captcha nằm trong _CAN_NGUOI nên bên khôi phục bỏ "
                      "ngay và báo chủ máy ra noVNC, thay vì quay hết 240 giây")

    def test_chi_chay_khi_THAT_SU_thay_khung_captcha(self):
        """Nhánh này bám vào một phép đo, không phải một phỏng đoán: không có
        khung reCAPTCHA trên trang thì nó không bao giờ chạy."""
        self.assertIn("if co_khung_captcha and not captcha_sau_mk_da_thu:", MA)


class LyDoHetGioPhaiChiRaTrangTests(unittest.TestCase):
    """"Hết 4 phút" một mình không nói được gì.

    Neo vào chuỗi CÓ TRONG CẢ HAI bản ("Hết 4 phút") rồi mới soi phần sau, để
    bản thiếu thông tin đỏ ở đúng phép đo thay vì ném ValueError.
    """

    LOI = _than(NGUON, "Hết 4 phút mà chưa hoàn tất 2FA", "session.completed_at")

    def test_kem_trang_va_so_dong_chon(self):
        self.assertIn("trang=", self.LOI)
        self.assertIn("so_dong_chon", self.LOI)
        self.assertIn("co_khung_captcha", self.LOI)


if __name__ == "__main__":
    unittest.main()
