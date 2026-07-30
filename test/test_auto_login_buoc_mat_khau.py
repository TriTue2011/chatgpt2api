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
        i = self.code.index("pwd_already")
        self.khuc = self.code[max(0, i - 600):i + 1200]

    def test_khong_con_gan_pwd_already_bang_clicked_tile(self):
        """Dòng gây lỗi phải biến mất khỏi MÃ (chú thích nhắc lại thì không tính)."""
        self.assertNotIn("pwd_already = clicked_tile", self.code)

    def test_luon_khoi_dau_bang_False(self):
        self.assertIn("pwd_already = False", self.khuc)

    def test_vong_do_o_mat_khau_khong_bi_bao_dieu_kien(self):
        """Bản cũ bọc vòng dò trong `if not pwd_already:` nên bấm tile là bỏ dò."""
        self.assertNotIn("if not pwd_already:", self.khuc)
        self.assertIn('input[type="password"]', self.khuc)

    def test_cho_lau_hon_khi_da_bam_tile(self):
        """Bấm tile xong trang cần thời gian điều hướng — chờ 2,5s là quá ngắn."""
        m = re.search(r"_cho\s*=\s*(\d+)\s*if\s*clicked_tile\s*else\s*(\d+)", self.khuc)
        self.assertIsNotNone(m, "không thấy thời gian chờ theo clicked_tile")
        dai, ngan = int(m.group(1)), int(m.group(2))
        self.assertGreater(dai, ngan)

    def test_bam_tile_ma_khong_thay_o_mat_khau_thi_ghi_log(self):
        """Ca này trước đây IM LẶNG đi tiếp rồi điền sai chỗ — phải để lại dấu."""
        self.assertIn("KHÔNG thấy ô mật khẩu", self.khuc)

    def test_con_nhanh_dien_email_de_roi_xuong(self):
        """Rơi xuống nhánh điền email là đường ĐÚNG khi tile không sang được
        màn hình mật khẩu — nhánh đó phải còn tồn tại."""
        self.assertIn('session.message = "Điền email..."', self.code)


if __name__ == "__main__":
    unittest.main()
