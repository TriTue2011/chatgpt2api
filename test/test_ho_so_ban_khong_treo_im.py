"""Hồ sơ đang bận thì báo ngay, không nằm im ở "Đang mở Chrome".

SỰ CỐ 09/08/2026. Chủ máy bấm "Chỉ đăng nhập" cho
`nguyenvanviet210290@gmail.com` rồi hỏi "tại sao chỉ đăng nhập lại ra chatgpt".

Đo trên máy chủ lúc đó:

    auto-login-status: state=starting | "Đang mở Chrome (headful → noVNC)"
                       elapsed=366s | error=None
    ps aux: 10 tiến trình chrome, user-data-dir=.../google-nguyenvanviet210290
    log:    cgf_onboard_request_failed profile=google-nguyenvanviet210290
            error=Read timed out (read timeout=180)

Tức là: một lượt khôi phục ChatGPT free đã chiếm hồ sơ đó và mở chatgpt.com
(bên gọi hết hạn chờ 180s rồi bỏ cuộc, nhưng tác vụ máy chủ vẫn chạy nên vẫn
giữ khoá). Lượt đăng nhập của người dùng nằm im trong `pool.get()` — nó chờ
khoá VÔ HẠN — suốt hơn 6 phút, trong khi giao diện vẫn hiện "Đang đăng nhập…".

Hai cái làm người dùng hiểu sai: trạng thái không phân biệt được "đang chạy" với
"đang bị chặn", và noVNC chiếu TOÀN BỘ màn hình X nên cửa sổ ChatGPT của việc
kia hiện ra như thể là của lượt đăng nhập.

CÁCH SỬA: `pool.get(cho_toi_da=…)` chờ có hạn rồi ném `HoSoDangBan`; luồng đăng
nhập bắt lấy và kết thúc với lý do đọc được. Mặc định `cho_toi_da=None` giữ
nguyên hành vi chờ vô hạn cho mọi nơi gọi cũ.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))

NGUON_POOL = (GOC / "captcha-solver/src/browser_pool.py").read_text(encoding="utf-8")
NGUON_LOGIN = (GOC / "captcha-solver/src/auto_login.py").read_text(encoding="utf-8")


def _than_ham(nguon: str, ten: str, het: str) -> str:
    return nguon[nguon.index(ten):nguon.index(het, nguon.index(ten))]


class CoCheChoCoHanTests(unittest.TestCase):
    """Kiểm CHÍNH cơ chế: chờ có hạn trên khoá đang bị giữ.

    Không import được `browser_pool` ở máy dev (thiếu patchright/cloakbrowser),
    nên phần hành vi kiểm trên đúng nguyên thuỷ mà nó dùng — `asyncio.Lock` +
    `asyncio.wait_for`. Điều cần chắc: hết giờ thì ném, và khoá KHÔNG bị hỏng
    (lần acquire bị huỷ không được âm thầm chiếm khoá — nếu hỏng thì hồ sơ kẹt
    vĩnh viễn, tệ hơn hẳn bệnh đang chữa).
    """

    def test_het_gio_thi_nem_va_khoa_van_lanh(self):
        async def chay():
            khoa = asyncio.Lock()
            await khoa.acquire()                      # việc khác đang giữ

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(khoa.acquire(), timeout=0.05)

            self.assertTrue(khoa.locked(), "khoá phải vẫn do người giữ đầu nắm")
            khoa.release()
            # Nhả xong thì người sau phải lấy được ngay — chứng minh lần chờ hụt
            # không để lại rác trong hàng đợi.
            await asyncio.wait_for(khoa.acquire(), timeout=0.5)
            self.assertTrue(khoa.locked())
        asyncio.run(chay())

    def test_khong_bi_ban_thi_lay_duoc_ngay(self):
        async def chay():
            khoa = asyncio.Lock()
            await asyncio.wait_for(khoa.acquire(), timeout=0.05)
            self.assertTrue(khoa.locked())
        asyncio.run(chay())


class PoolTests(unittest.TestCase):
    def test_co_lop_ngoai_le_rieng(self):
        self.assertIn("class HoSoDangBan", NGUON_POOL)
        i = NGUON_POOL.index("class HoSoDangBan")
        self.assertIn("đang bận", NGUON_POOL[i:i + 700])

    def test_get_cho_co_han_va_nem_dung_lop(self):
        than = _than_ham(NGUON_POOL, "    async def get(", "    async def close_profile")
        self.assertIn("cho_toi_da", than)
        self.assertIn("asyncio.wait_for(lock.acquire()", than)
        self.assertIn("raise HoSoDangBan", than)

    def test_mac_dinh_van_cho_vo_han(self):
        """Mọi nơi gọi cũ không truyền `cho_toi_da` phải giữ nguyên hành vi."""
        than = _than_ham(NGUON_POOL, "    async def get(", "    async def close_profile")
        self.assertIn("cho_toi_da: float | None = None", than)
        self.assertIn("if cho_toi_da is None:", than)

    def test_van_nha_khoa_khi_thoat(self):
        """Đổi `async with lock` sang acquire/release tay là chỗ dễ rò khoá —
        rò một lần là hồ sơ đó chết vĩnh viễn."""
        than = _than_ham(NGUON_POOL, "    async def get(", "    async def close_profile")
        self.assertIn("finally:", than)
        self.assertIn("lock.release()", than)


class LuongDangNhapTests(unittest.TestCase):
    def test_dang_nhap_truyen_han_cho(self):
        self.assertIn("cho_toi_da=", NGUON_LOGIN)

    def test_bat_HoSoDangBan_va_ket_thuc_co_ly_do(self):
        i = NGUON_LOGIN.index("except HoSoDangBan")
        than = NGUON_LOGIN[i:i + 700]
        self.assertIn('session.state = "failed"', than,
                      "phải kết thúc phiên, không để nguyên 'starting'")
        self.assertIn("bận", than, "lý do phải nói rõ là bận, không phải lỗi chung chung")
        self.assertIn("Thử lại sau", than)

    def test_khong_con_goi_get_khong_han_o_luong_dang_nhap(self):
        """Chỗ này chính là nơi đã kẹt 366 giây."""
        i = NGUON_LOGIN.index('session.message = "Đang mở Chrome (headful → noVNC)"')
        than = NGUON_LOGIN[i:i + 1200]
        self.assertIn("cho_toi_da=", than)


if __name__ == "__main__":
    unittest.main()
