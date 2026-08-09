"""Lượt onboard treo phải tự dừng và NHẢ hồ sơ, không giữ trình duyệt mãi.

SỰ CỐ 09/08/2026. Chủ máy: "xong lỗi cũng không thấy đóng workspace lại, giữ
lâu quá".

Đo trên máy chủ đúng lúc đó:

    /v1/chatgpt/google-nguyenvanviet210290/onboard-status
      state=running  elapsed=608s
      msg="Đã bấm lại vào mail lần 172 — chờ ô mật khẩu..."

    ps: chrome user-data-dir=.../google-nguyenvanviet210290 sống 279s+
    auto-login-status: state=failed "Hồ sơ đang bận — chưa tới lượt"

Ba dòng đó ghép lại thành một câu chuyện: lượt onboard kẹt trong vòng
bấm-lại-vào-mail, giữ khoá hồ sơ; lượt đăng nhập của người dùng chờ hết 120 giây
rồi bỏ cuộc; trình duyệt vẫn nằm trên noVNC.

HAI LỖI KHÁC NHAU, PHẢI SỬA CẢ HAI

1. Vì sao nó kẹt — nhánh điền email bị nhánh tile vô hình nuốt mất. Đã sửa ở
   `test_dien_email_truoc_khi_bam_tile.py`.

2. Vì sao kẹt lại kéo dài mãi — KHÔNG có trần thời gian cho cả lượt. Các bước
   con đều có hạn riêng nhưng cộng dồn được: 608 giây vẫn chạy, dù vòng
   vào-ô-mật-khẩu chỉ có 420 giây. Bên gọi `_cgf_onboard_once` bỏ cuộc sau 180
   giây nhưng tác vụ không biết, cứ chạy tiếp và giữ khoá.

Sửa lỗi 1 mà bỏ lỗi 2 thì lần sau kẹt vì lý do khác lại giữ hồ sơ y như vậy.

TẠI SAO KHÔNG DÙNG `asyncio.wait_for` BỌC CẢ TÁC VỤ

Vì phải TẠM DỪNG đồng hồ khi phiên đang chờ NGƯỜI (`need_code`, `need_captcha`,
`need_tap`). Cắt ngang lúc người đang gõ captcha trên noVNC là phá đúng việc
mình vừa nhờ họ làm.
"""
from __future__ import annotations

import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
NGUON = (GOC / "captcha-solver/src/chatgpt_login.py").read_text(encoding="utf-8")

DAU = NGUON.index("async def _chay_onboard_co_han")
THAN = NGUON[DAU:NGUON.index("async def _nuke_profile", DAU)]


class CoTranThoiGianTests(unittest.TestCase):
    def test_tac_vu_duoc_boc_boi_ham_co_han(self):
        """`start_chatgpt_onboard` không được spawn thẳng `_run_onboard_v2` nữa."""
        i = NGUON.index("def start_chatgpt_onboard")
        khuc = NGUON[i:NGUON.index("_NGAN_SACH_ONBOARD_S", i)]
        self.assertIn("_chay_onboard_co_han", khuc)
        self.assertNotIn("asyncio.create_task(_run_onboard_v2", khuc,
                         "spawn thẳng là mất trần thời gian")

    def test_tran_thoi_gian_dai_hon_ngan_sach_buoc_con(self):
        """Phải dài hơn 420s (vòng vào-ô-mật-khẩu) để không cắt oan lượt đang
        chạy bình thường, nhưng vẫn hữu hạn."""
        import re
        m = re.search(r"_NGAN_SACH_ONBOARD_S = ([\d.]+)", NGUON)
        self.assertIsNotNone(m)
        gia_tri = float(m.group(1))
        self.assertGreater(gia_tri, 420.0)
        self.assertLessEqual(gia_tri, 900.0, "trần quá cao thì coi như không có")


class KhongCatNgangKhiChoNguoiTests(unittest.TestCase):
    def test_co_danh_sach_trang_thai_cho_nguoi(self):
        for st in ("need_code", "need_captcha", "need_tap"):
            self.assertIn(st, NGUON[NGUON.index("_CHO_NGUOI"):
                                    NGUON.index("_CHO_NGUOI") + 200])

    def test_dang_cho_nguoi_thi_dat_lai_dong_ho(self):
        i = THAN.index("_CHO_NGUOI")
        khuc = THAN[i:i + 240]
        self.assertIn("han = time.time()", khuc,
                      "chờ người thì phải gia hạn, không được đếm giờ")
        self.assertIn("continue", khuc)


class LuonNhaHoSoTests(unittest.TestCase):
    def test_dong_ho_so_trong_finally(self):
        """Đây là điểm mấu chốt: đường bị huỷ KHÔNG chạy tới đoạn đóng của
        `_run_onboard_v2`, nên phải đóng ở đây."""
        i = THAN.index("finally:")
        khuc = THAN[i:]
        self.assertIn("close_profile", khuc)

    def test_ket_thuc_phien_bang_trang_thai_that(self):
        """Bỏ nguyên state='running' là giao diện quay mãi và tầng khôi phục
        không biết đường nào mà lần."""
        i = THAN.index("finally:")
        khuc = THAN[i:]
        self.assertIn('session.state = "failed"', khuc)
        self.assertIn("session.completed_at", khuc)

    def test_noi_ro_ly_do_trong_error(self):
        i = THAN.index("session.error")
        khuc = THAN[i:i + 300]
        self.assertIn("nhả trình duyệt", khuc,
                      "phải nói rõ đã nhả hồ sơ, vì đó là hệ quả người vận hành cần biết")


if __name__ == "__main__":
    unittest.main()
