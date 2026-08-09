"""Có ô nhập email thì ĐIỀN, đừng đi bấm tile vô hình.

SỰ CỐ 09/08/2026 — và đây là gốc của cả chuỗi hỏng hôm nay.

Chủ máy bấm "Chỉ đăng nhập" cho `nguyenvanviet210290@gmail.com`, nhìn noVNC rồi
báo "nằm im 1 chỗ". Ảnh màn hình cho thấy trang đang ở
`accounts.google.com/v3/signin/identifier` với ô "Email hoặc số điện thoại"
**TRỐNG TRƠN**, trong khi ứng dụng báo "RUNNING — Đang vào ô mật khẩu…".

Log máy chủ cùng lúc đó:

    auto_login: bấm lại vào mail lần 125 (google-nguyenvanviet210290)

125 lần "bấm lại vào mail" mà chưa từng gõ nổi một ký tự vào ô email.

NGUYÊN NHÂN

`_bam_lai_vao_mail()` dò TILE trước, điền ô sau. Nhánh dò tile thứ hai nhận bất
kỳ phần tử nào có `innerText` CHỨA email — và KHÔNG kiểm phần tử đó có hiển thị
không. Trên màn identifier vẫn có phần tử ẩn dính chuỗi email, nên nó `click()`
trúng một thứ vô hình (không xảy ra gì), trả về True, và nhánh điền email không
bao giờ chạy. Vòng lặp quay đủ 420 giây rồi kết luận:

    "không vào được ô mật khẩu (Google chặn hoặc đổi giao diện)"

Thông báo đổ cho Google, trong khi lỗi nằm ở chính mình.

VÌ SAO NÓ KÉO SẬP CẢ THANG KHÔI PHỤC

Tầng T3 của `recover_provider_account` gọi `_freshen_google` → chính luồng này.
Nên MỌI lượt tự khôi phục tài khoản Google đều trượt với cùng một lý do sai,
rồi báo "KHÔNG tự khôi phục được → đăng nhập tay qua noVNC" cho những tài khoản
mà máy đáng lẽ tự chữa được.

CÁCH SỬA

Đảo thứ tự: có ô nhập thì điền (màn identifier), không có ô nhập mới tìm tile
(màn "Chọn tài khoản") — hai màn đó loại trừ nhau nên thứ tự này không mơ hồ.
Và nhánh tile bắt buộc kiểm hiển thị thật (`offsetParent` + kích thước > 0).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
NGUON = (GOC / "captcha-solver/src/auto_login.py").read_text(encoding="utf-8")

DAU = NGUON.index("async def _bam_lai_vao_mail")
THAN = NGUON[DAU:NGUON.index("_CAPTCHA_SELECTORS", DAU)]


class ThuTuUuTienTests(unittest.TestCase):
    def test_dien_o_email_TRUOC_khi_tim_tile(self):
        """Đây chính là ca đã hỏng: ô email hiện ra mà đi bấm tile."""
        vi_tri_dien = THAN.index("press_sequentially")
        vi_tri_tile = THAN.index("data-identifier")
        self.assertLess(vi_tri_dien, vi_tri_tile,
                        "phải điền ô email trước; dò tile trước là nuốt mất "
                        "nhánh điền và quay vòng vô ích tới hết ngân sách")

    def test_van_con_nhanh_tile_cho_man_chon_tai_khoan(self):
        """Không được vứt tile: màn 'Chọn tài khoản' không có ô nhập nào."""
        self.assertIn("data-identifier", THAN)
        self.assertIn("e.click()", THAN)


class TileBatBuocHienThiTests(unittest.TestCase):
    def test_ca_hai_nhanh_tile_deu_kiem_hien_thi(self):
        js = THAN[THAN.index("(em) => {"):]
        self.assertIn("offsetParent", js, "phải kiểm phần tử có hiển thị không")
        self.assertIn("getBoundingClientRect", js,
                      "offsetParent thôi chưa đủ: phần tử kích thước 0 vẫn lọt")
        # Nhánh khớp theo innerText là nhánh đã gây sự cố — nó phải gọi hàm kiểm
        # hiển thị trước khi click.
        i = js.index("innerText")
        truoc = js[max(0, i - 200):i]
        self.assertIn("hien(e)", truoc,
                      "nhánh khớp innerText vẫn bấm được phần tử ẩn")

    def test_ham_kiem_doi_ca_chieu_rong_va_cao(self):
        js = THAN[THAN.index("(em) => {"):]
        i = js.index("const hien")
        than_ham = js[i:i + 260]
        self.assertIn("r.width > 0", than_ham)
        self.assertIn("r.height > 0", than_ham)


class GhiLaiBaiHocTests(unittest.TestCase):
    def test_docstring_ghi_ro_so_do_va_hau_qua(self):
        """Bài học đắt nhất của lần này: thông báo đổ lỗi cho Google trong khi
        lỗi ở mình. Phải ghi lại, nếu không lần sau lại đi sửa nhầm phía Google.
        """
        doc = THAN[:THAN.index('"""', THAN.index('"""') + 3)]
        self.assertIn("125", doc, "ghi lại con số đo được")
        self.assertIn("ẩn", doc, "ghi lại rằng phần tử ẩn là thủ phạm")


if __name__ == "__main__":
    unittest.main()
