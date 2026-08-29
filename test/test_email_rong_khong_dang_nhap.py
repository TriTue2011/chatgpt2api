"""Email rỗng thì DỪNG, đừng bấm "Tiếp theo" trên ô trống.

SỰ CỐ 29/08/2026 — ba tài khoản Google báo "KHÔNG tự khôi phục được", tin nhắn
đổ lý do cho "Google đang bắt CAPTCHA". Ảnh noVNC cho thấy trang đang ở
`accounts.google.com/v3/signin/identifier` với ô "Email hoặc số điện thoại"
TRỐNG TRƠN và lỗi đỏ "Hãy nhập email hoặc số điện thoại" — tức đã bấm
"Tiếp theo" trên một form rỗng.

Log máy chủ (container c2a), hồ sơ google-smarthomebenbap0610:

    00:31:23  chatgpt_login: nuked profile google-smarthomebenbap0610
    00:31:32  auto_login: clicked account tile for  on chooser screen   ← email TRỐNG
    00:31:42  auto_login: bấm lại vào mail lần 1  (url=…/v3/signin/identifier?…dsh=s-301406688:…)
    00:37:53  auto_login: bấm lại vào mail lần 40 (url=…/v3/signin/identifier?…dsh=s-301406688:…)

Chuỗi `dsh=` không đổi suốt 40 lượt: trang chưa hề tải lại lần nào.

NGUYÊN NHÂN

`main.py::bu_credential` bù MẬT KHẨU và HẠT GIỐNG TOTP từ kho khi request gửi
rỗng, nhưng KHÔNG bù email. Bộ khôi phục gọi onboard với cả ba trường rỗng, nên
ra khỏi hàm đó là mật khẩu THẬT + email RỖNG. Hai hệ quả nối nhau:

  · `start_chatgpt_onboard` có lá chắn "không mật khẩu thì đừng xoá hồ sơ" (vá
    09/08/2026). Mật khẩu vừa được bù nên lá chắn không nổ → nhánh dưới XOÁ hồ
    sơ, mất luôn phiên Google đang sống.
  · `do_google_login_steps` chạy với `session.email == ""`: đoạn dò tile so
    `innerText.includes("")` nên luôn đúng (bấm trúng phần tử đầu tiên gặp
    được), và `press_sequentially("")` gõ đúng 0 ký tự rồi vẫn bấm "Tiếp theo".

Bốn mươi lượt nộp form rỗng trong bảy phút mới là thứ khiến Google bung
reCAPTCHA. Captcha là HẬU QUẢ của lỗi tự động, không phải Google chặn tài khoản.

CÁCH SỬA

1. `bu_credential` bù luôn email, cùng bản ghi với mật khẩu — vá một chỗ cho cả
   sáu đường onboard (auto-login, multi, gemini-web, openai-native, claude-web,
   chatgpt).
2. `do_google_login_steps` từ chối chạy khi email rỗng, thay vì quay 420 giây
   rồi đổ lỗi cho Google.
3. `_bam_lai_vao_mail` đọc lại ô email và chỉ bấm "Tiếp theo" khi giá trị đã
   thật sự nằm trong ô.
"""
from __future__ import annotations

import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
MAIN = (GOC / "captcha-solver/src/main.py").read_text(encoding="utf-8")
AUTO = (GOC / "captcha-solver/src/auto_login.py").read_text(encoding="utf-8")


class BuCredentialTests(unittest.TestCase):
    """Email phải được bù từ kho y như mật khẩu."""

    def test_tra_ve_ba_gia_tri_gom_email(self):
        self.assertIn("def bu_credential(req) -> tuple[str, str, str]:", MAIN,
                      "bu_credential phải trả (email, mật khẩu, hạt giống)")

    def test_lay_email_tu_kho_khi_request_gui_rong(self):
        than = MAIN[MAIN.index("def bu_credential"):MAIN.index("class TwoFactorCodeReq")]
        self.assertIn('acct.get("email")', than,
                      "phải đọc email từ bản ghi trong kho, không chỉ mật khẩu/TOTP")

    def test_moi_duong_onboard_dung_email_da_bu(self):
        """Cả sáu đường onboard phải dùng email đã bù, không phải req.email thô."""
        self.assertNotIn("email=req.email", MAIN,
                         "còn nơi truyền thẳng req.email — nơi đó vẫn đăng nhập "
                         "được với email rỗng")
        self.assertEqual(MAIN.count("email_tk, mat_khau, hat_giong = bu_credential(req)"), 6,
                         "phải đủ sáu đường onboard cùng bù credential")


class ChanEmailRongTests(unittest.TestCase):
    """Không người gọi nào được đẩy lượt đăng nhập rỗng vào trang Google."""

    def setUp(self):
        dau = AUTO.index("async def do_google_login_steps")
        self.than = AUTO[dau:AUTO.index("async def _bam_lai_vao_mail", dau)]

    def test_co_chot_chan_email_rong(self):
        self.assertIn('if not (session.email or "").strip():', self.than,
                      "thiếu chốt chặn email rỗng ở đầu do_google_login_steps")

    def test_chan_TRUOC_khi_do_tile(self):
        """Đây chính là ca đã hỏng: includes('') luôn đúng nên bấm bừa."""
        vi_tri_chan = self.than.index('if not (session.email or "").strip():')
        vi_tri_tile = self.than.index("data-identifier")
        self.assertLess(vi_tri_chan, vi_tri_tile,
                        "phải dừng TRƯỚC đoạn dò tile; chặn sau là đã bấm bừa rồi")


class KiemOEmailTruocKhiBamTests(unittest.TestCase):
    """Gõ xong không đồng nghĩa giá trị đã nằm trong ô."""

    def setUp(self):
        dau = AUTO.index("async def _bam_lai_vao_mail")
        self.than = AUTO[dau:AUTO.index("_CAPTCHA_SELECTORS", dau)]

    def test_doc_lai_o_email(self):
        self.assertIn("input_value", self.than,
                      "phải đọc lại ô email sau khi gõ")

    def test_doc_lai_TRUOC_khi_bam_tiep_theo(self):
        vi_tri_doc = self.than.index("input_value")
        vi_tri_bam = self.than.index("_safe_click")
        self.assertLess(vi_tri_doc, vi_tri_bam,
                        "phải kiểm ô email TRƯỚC khi bấm 'Tiếp theo'; bấm rồi "
                        "mới kiểm là đã nộp form trống")

    def test_khong_bam_khi_o_chua_dung_email(self):
        self.assertIn("return False", self.than[self.than.index("input_value"):],
                      "ô chưa nhận đủ chữ thì phải bỏ lượt, không bấm Tiếp theo")


if __name__ == "__main__":
    unittest.main()
