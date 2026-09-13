"""`need_captcha` chỉ được báo khi THẬT SỰ cần người — và đã vào được thì phải biết.

SỰ CỐ 13/09/2026, đo trên máy chủ thật:

1. 13:05:07 hồ sơ Flow Spare 2 gặp reCAPTCHA. `auto_login` đặt `need_captcha`
   NGAY lúc thấy khung, rồi mới tự tích ô (xong 13:05:11), trang chuyển sang ô
   mật khẩu lúc 13:05:13. Bên khôi phục (`account_recovery._freshen_google`)
   hỏi trạng thái 5 giây một lần, đọc được `need_captcha` giữa chừng, bỏ cuộc,
   khoá MỌI lượt đăng nhập Google 6 giờ. Ba hồ sơ còn lại (Main, Spare 1,
   Backup) bị hoãn và nằm chết tới khi có người chạy tay lúc 13:29.

2. 13:29 hồ sơ Main đã vào tới trang `/` của Gemini sau mật khẩu, nhưng vòng
   2FA chỉ kiểm "đã đăng nhập" ở CUỐI vòng — sau khối dò bảng chọn. Trang
   Gemini có chữ "Tùy chọn khác", khối dò cứ bấm rồi `continue`, quay đủ 4 phút
   rồi báo `failed`. Phiên Flow kiểm lại ngay sau đó: `ok`.

Test này CHẠY THẬT vòng lặp trên một trang Google giả dựng lại đúng các cảnh
đã đo (trễ chuyển trang 2,0 giây, chữ "Tùy chọn khác" trên trang ứng dụng), với
đồng hồ giả để vòng 420 giây chạy xong tức thì. Test đọc mã nguồn thì không bắt
được lỗi 1: chuỗi `"need_captcha"` có mặt ở đúng chỗ, chỉ SAI THỜI ĐIỂM.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path

from test import _goi_captcha

NGUON_AUTO_LOGIN = Path(_goi_captcha._THU_MUC) / "auto_login.py"

TRANG_CAPTCHA = "https://accounts.google.com/v3/signin/challenge/recaptcha?TL=x"
TRANG_MAT_KHAU = "https://accounts.google.com/v3/signin/challenge/pwd?TL=x"
TRANG_GEMINI = "https://gemini.google.com/app"
TRANG_TOTP = "https://accounts.google.com/v3/signin/challenge/totp?TL=x"
O_MA = 'input[name="totpPin"]'
O_MAT_KHAU = ('input[type="password"]', 'input[name="Passwd"]',
              'input[autocomplete="current-password"]', 'input[name="password"]')
DONG_CHON = 'li[data-challengetype],div[data-challengetype],div[role="link"],li'


def _nap_auto_login():
    """Nạp `auto_login` với `browser_pool` và `solvers.recaptcha` giả.

    `browser_pool` kéo Playwright vào — máy chạy test không có, và vòng lặp cần
    đo không đụng tới nó."""
    _goi_captcha._dam_bao_goi()
    goi = _goi_captcha.TEN_GOI
    bp = types.ModuleType(f"{goi}.browser_pool")
    bp.HoSoDangBan = type("HoSoDangBan", (Exception,), {})
    bp.pool = object()
    sv = types.ModuleType(f"{goi}.solvers")
    sv.__path__ = []
    rc = types.ModuleType(f"{goi}.solvers.recaptcha")
    ten = f"{goi}._auto_login_duoi_test"
    cu = {k: sys.modules.get(k) for k in (bp.__name__, sv.__name__, rc.__name__, ten)}
    sys.modules.update({bp.__name__: bp, sv.__name__: sv, rc.__name__: rc})
    spec = importlib.util.spec_from_file_location(ten, NGUON_AUTO_LOGIN)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[ten] = mod
    spec.loader.exec_module(mod)
    return mod, rc, cu


class _Canh:
    """Trang Google giả chạy theo đồng hồ giả."""

    def __init__(self):
        self.gio = 1_000.0
        self.tich_xong_luc: float | None = None
        self.go_mat_khau_luc: float | None = None
        self.captcha_con_mai = False      # tích xong mà captcha vẫn không đi
        self.captcha_sau_mat_khau = False
        self.tich_sau_mk_xong_luc: float | None = None
        self.hoi_totp = False
        self.dien_ma_luc: float | None = None

    def url(self) -> str:
        if self.go_mat_khau_luc is not None:
            if self.captcha_sau_mat_khau and self.tich_sau_mk_xong_luc is None:
                return TRANG_CAPTCHA
            if self.hoi_totp and self.dien_ma_luc is None:
                return TRANG_TOTP
            return TRANG_GEMINI
        if self.tich_xong_luc is None or self.captcha_con_mai:
            return TRANG_CAPTCHA
        # Đo thật: tích xong 2,0 giây sau trang mới sang ô mật khẩu.
        return TRANG_CAPTCHA if self.gio < self.tich_xong_luc + 2.0 else TRANG_MAT_KHAU

    def cookies(self) -> list[dict]:
        return [{"name": "SID"}] if self.url() == TRANG_GEMINI else []


class _O:
    def __init__(self, canh: _Canh, sel: str):
        self.canh, self.sel = canh, sel

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def _co(self) -> bool:
        url = self.canh.url()
        if 'iframe[src*="/recaptcha/"]' in self.sel:
            return url == TRANG_CAPTCHA
        if self.sel in O_MAT_KHAU:
            return url == TRANG_MAT_KHAU
        if self.sel == O_MA:
            return url == TRANG_TOTP
        if self.sel == DONG_CHON:
            # Trang Gemini có sẵn `li` (đo 13:30: "9 dòng chọn"), nhưng KHÔNG có
            # dòng Authenticator/Nhấn Có nào — log thật: "no Tap row matched".
            return url == TRANG_GEMINI
        return False

    async def count(self):
        return (9 if self.sel == DONG_CHON else 1) if self._co() else 0

    async def is_visible(self, timeout=0):
        return self._co()

    async def inner_text(self, timeout=0):
        if self.sel != "body":
            return ""
        return {TRANG_CAPTCHA: "Xác minh danh tính của bạn",
                TRANG_MAT_KHAU: "Nhập mật khẩu",
                TRANG_GEMINI: "Gemini backup code gg Tùy chọn khác"}[self.canh.url()]

    async def click(self, timeout=0):
        if not self._co():
            raise TimeoutError(self.sel)

    async def fill(self, gia_tri="", *a, **k):
        if self.sel == O_MA and gia_tri:
            self.canh.dien_ma_luc = self.canh.gio

    async def press_sequentially(self, *a, **k):
        if self.sel in O_MAT_KHAU:
            self.canh.go_mat_khau_luc = self.canh.gio

    async def input_value(self, timeout=0):
        return ""


class _Trang:
    def __init__(self, canh: _Canh):
        self.canh = canh

    @property
    def url(self):
        return self.canh.url()

    def locator(self, sel):
        return _O(self.canh, sel)

    async def evaluate(self, js, *a):
        # Khối "Try another way" dò chữ trên TOÀN trang rồi bấm — trang Gemini
        # có "Tùy chọn khác" nên trên máy thật nó trả True (đo 13:30:43).
        if "tùy chọn khác" in js and "target.click()" in js:
            return "tùy chọn khác" in (await _O(self.canh, "body").inner_text()).lower()
        return False


class _Ctx:
    def __init__(self, trang: _Trang):
        self.pages = [trang]
        self.canh = trang.canh

    async def cookies(self):
        return self.canh.cookies()


def _chay(mod, rc, canh: _Canh, *, tich_duoc: bool, totp: str | None = None):
    """Chạy `do_google_login_steps`; trả (kết quả, [(giờ, trạng thái)])."""
    lich_su: list[tuple[float, str]] = []

    class Phien(mod.LoginSession):
        def __setattr__(self, k, v):
            if k == "state":
                lich_su.append((canh.gio, v))
            super().__setattr__(k, v)

    async def ngu(s):
        canh.gio += s

    async def tich_o(page):
        canh.gio += 3.9          # đo thật: 13:05:07,1 → 13:05:11,1
        if not tich_duoc:
            return False
        if canh.go_mat_khau_luc is not None:
            canh.tich_sau_mk_xong_luc = canh.gio
        else:
            canh.tich_xong_luc = canh.gio
        return True

    async def giai_am_thanh(page):
        raise RuntimeError("không giải được thử thách âm thanh")

    rc.tich_o_recaptcha = tich_o
    rc.solve_recaptcha_v2_tren_trang = giai_am_thanh
    that_async, that_time = mod.asyncio, mod.time
    that_pyotp, that_co = mod.pyotp, mod._HAS_PYOTP
    mod.asyncio = types.SimpleNamespace(
        **{**{k: getattr(asyncio, k) for k in dir(asyncio) if not k.startswith("_")},
           "sleep": ngu})
    mod.time = types.SimpleNamespace(time=lambda: canh.gio)
    # Máy chạy test có thể thiếu pyotp; mã sinh ra không quan trọng, chỉ cần có.
    mod.pyotp = types.SimpleNamespace(TOTP=lambda s: types.SimpleNamespace(now=lambda: "123456"))
    mod._HAS_PYOTP = True
    try:
        phien = Phien(profile="google-thu", email="thu@example.com", totp_secret=totp)
        trang = _Trang(canh)
        kq = asyncio.run(mod.do_google_login_steps(phien, trang, _Ctx(trang), "mat-khau-gia"))
    finally:
        mod.asyncio, mod.time = that_async, that_time
        mod.pyotp, mod._HAS_PYOTP = that_pyotp, that_co
    return kq, lich_su, phien


class _Nen(unittest.TestCase):
    def setUp(self):
        self.mod, self.rc, self._cu = _nap_auto_login()

    def tearDown(self):
        for k, v in self._cu.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


class KhongBaoCanNguoiKhiMayDangTuQuaTests(_Nen):

    def test_tich_o_xong_trang_tre_2_giay_thi_KHONG_bao_gio_bao_need_captcha(self):
        """Đúng ca 13:05 và 13:29: tích được, trang chuyển sau 2,0 giây."""
        kq, lich_su, _ = _chay(self.mod, self.rc, _Canh(), tich_duoc=True)
        self.assertTrue(kq)
        self.assertNotIn("need_captcha", [s for _, s in lich_su],
                         "bên khôi phục đọc được need_captcha là khoá mọi lượt "
                         "đăng nhập Google 6 giờ — trong khi máy đang tự qua")

    def test_tich_xong_ma_captcha_VAN_con_thi_moi_bao_can_nguoi(self):
        canh = _Canh()
        canh.captcha_con_mai = True
        kq, lich_su, _ = _chay(self.mod, self.rc, canh, tich_duoc=True)
        self.assertFalse(kq)
        luc = [g for g, s in lich_su if s == "need_captcha"]
        self.assertTrue(luc, "captcha không đi thì phải gọi người, không được im")
        self.assertGreaterEqual(luc[0] - canh.tich_xong_luc, self.mod_cho(),
                                "gọi người trước khi trang kịp chuyển là báo oan")

    def test_tu_qua_hong_thi_bao_can_nguoi_ngay_sau_lan_thu(self):
        canh = _Canh()
        kq, lich_su, _ = _chay(self.mod, self.rc, canh, tich_duoc=False)
        self.assertFalse(kq)
        trang_thai = [s for _, s in lich_su]
        self.assertIn("need_captcha", trang_thai)
        # Lần thử mất 3,9 giây từ giờ 1000 → trước mốc đó không được có.
        self.assertTrue(all(g >= 1_003.9 for g, s in lich_su if s == "need_captcha"),
                        "chưa thử xong đã gọi người")

    def test_captcha_SAU_mat_khau_tich_duoc_cung_khong_bao_can_nguoi(self):
        canh = _Canh()
        canh.captcha_sau_mat_khau = True
        kq, lich_su, _ = _chay(self.mod, self.rc, canh, tich_duoc=True)
        self.assertTrue(kq)
        self.assertNotIn("need_captcha", [s for _, s in lich_su])

    def mod_cho(self) -> float:
        # Mốc chờ chuyển trang nằm trong thân hàm; test giữ đúng số đã chốt.
        return 10.0


class CoTOTPThiKhongGoiNguoiNhapMaTests(_Nen):
    """Cùng lớp lỗi, ở `need_code`: máy tự điền TOTP được thì chưa cần người."""

    def test_co_TOTP_thi_KHONG_bao_need_code(self):
        canh = _Canh()
        canh.hoi_totp = True
        kq, lich_su, phien = _chay(self.mod, self.rc, canh, tich_duoc=True,
                                   totp="JBSWY3DPEHPK3PXP")
        self.assertTrue(kq, f"có TOTP mà không qua được: {phien.error}")
        self.assertIsNotNone(canh.dien_ma_luc, "máy phải tự điền mã")
        self.assertNotIn("need_code", [s for _, s in lich_su],
                         "need_code nằm trong _CAN_NGUOI — bên khôi phục bỏ cuộc "
                         "trong khi máy đang tự điền mã")

    def test_KHONG_co_TOTP_thi_van_bao_need_code_cho_nguoi(self):
        canh = _Canh()
        canh.hoi_totp = True
        kq, lich_su, _ = _chay(self.mod, self.rc, canh, tich_duoc=True, totp=None)
        self.assertFalse(kq)
        self.assertIn("need_code", [s for _, s in lich_su])


class VongHaiFANhanRaDaDangNhapTests(_Nen):

    def test_vao_toi_trang_Gemini_thi_xong_ngay_khong_quay_4_phut(self):
        canh = _Canh()
        kq, _, phien = _chay(self.mod, self.rc, canh, tich_duoc=True)
        self.assertTrue(kq, f"đã vào Gemini mà báo hỏng: {phien.error}")
        self.assertLess(canh.gio - canh.go_mat_khau_luc, 30,
                        "đã đăng nhập mà vòng 2FA vẫn quay — đúng ca Main 13:29")


if __name__ == "__main__":
    unittest.main()
