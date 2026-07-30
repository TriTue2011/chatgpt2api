"""Đăng nhập Google tự động — KHÔNG được suy "đã có ô mật khẩu" từ việc bấm tile.

Bản cũ: ``pwd_already = clicked_tile`` — bấm được tile tài khoản là tin luôn rằng
ô mật khẩu đã hiện, rồi BỎ HẲN bước điền email.

Đo thật 30/07 (benbap2011@gmail.com):

    clicked account tile for benbap2011@gmail.com on chooser screen
    password field assumed/present — skipping email step (SSO pick)
    after email, url=…/v3/signin/identifier?…        ← VẪN Ở BƯỚC EMAIL
    captcha detected for google-benbap2011

Nó điền mật khẩu khi trang còn ở bước email → Google thấy hành vi lạ → bung
captcha. Người dùng gõ tay chỉ đăng nhập bình thường thì KHÔNG bị captcha, tức
captcha là HẬU QUẢ của lỗi tự động, không phải Google chặn tài khoản.

Test này đọc THẲNG mã nguồn thay vì dựng Playwright giả: điều cần khoá là một
quyết định logic (luôn dò ô mật khẩu thật), và nó nằm gọn trong vài dòng. Dựng
trình duyệt giả cho một phép đo như vậy là đổi một phép đo chắc chắn thành một
phép đo phụ thuộc mock.
"""
from __future__ import annotations

import pathlib
import re
import unittest

NGUON = pathlib.Path(__file__).resolve().parents[1] / "captcha-solver" / "src" / "auto_login.py"


class TestKhongSuyTuTile(unittest.TestCase):
    def setUp(self):
        self.src = NGUON.read_text("utf-8")
        # BỎ dòng chú thích trước khi soi: chú thích của bản vá có NHẮC LẠI dòng
        # cũ để giải thích, nên tìm chuỗi trên nguyên văn sẽ bắt phải chính chú
        # thích đó và báo "chưa vá" trong khi đã vá.
        self.code = "\n".join(l for l in self.src.splitlines()
                              if not l.lstrip().startswith("#"))
        i = self.code.index("pwd_deadline = time.time()")
        self.khuc = self.code[i:i + 3000]

    def test_khong_con_gan_pwd_already_bang_clicked_tile(self):
        """Dòng gây lỗi phải biến mất khỏi MÃ (chú thích nhắc lại thì không tính)."""
        self.assertNotIn("pwd_already = clicked_tile", self.code)

    def test_khong_con_bien_suy_dien_nao(self):
        """Không còn cờ "coi như đã có ô mật khẩu" — mỗi vòng dò lại trên trang."""
        self.assertNotIn("pwd_already", self.code)

    def test_moi_vong_deu_do_o_mat_khau_that(self):
        self.assertIn("pwd_input = await _pwd_visible(", self.khuc)
        self.assertIn("_PWD_SELECTORS", self.code)
        self.assertIn("async def _pwd_visible", self.code)
        self.assertIn('input[type="password"]', self.code)

    def test_chi_dien_mat_khau_khi_da_co_o_that(self):
        """Điền mật khẩu phải nằm SAU khi vòng đã bắt được ô thật."""
        self.assertLess(self.code.index("pwd_input = await _pwd_visible("),
                        self.code.index("await pwd_input.press_sequentially(password"))
        self.assertIn("if pwd_input is None:", self.code)

    def test_do_lai_nhieu_vong_thay_vi_mot_lan_cho_dai(self):
        """Bấm tile xong trang cần thời gian điều hướng. Bản cũ giải quyết bằng
        MỘT lần chờ dài (8000ms) rồi kết luận; giờ là dò lại mỗi vòng suốt cả
        giai đoạn nên không cần đoán thời gian chờ."""
        m = re.search(r"_VAO_O_MAT_KHAU_S = ([\d.]+)", self.code)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(float(m.group(1)), 420.0)
        self.assertIn("while time.time() < pwd_deadline", self.code)

    def test_bam_lai_vao_mail_co_ghi_log(self):
        """Ca này trước đây IM LẶNG đi tiếp rồi điền sai chỗ — phải để lại dấu."""
        self.assertIn("bấm lại vào mail lần", self.code)

    def test_con_nhanh_dien_email_khi_khong_co_tile(self):
        """Không có tile thì vẫn phải điền email + Tiếp theo."""
        i = self.code.index("async def _bam_lai_vao_mail")
        khuc = self.code[i:i + 2600]
        self.assertIn('input#identifierId', khuc)
        self.assertIn("press_sequentially(session.email", khuc)


if __name__ == "__main__":
    unittest.main()
