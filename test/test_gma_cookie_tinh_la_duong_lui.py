"""Cookie Gemini dán tay trong cấu hình là ĐƯỜNG LÙI, không phải đường chính.

`_get_cookies_ranked` bản cũ thấy có `psid` trong cấu hình là trả về đúng nó rồi
thoát — cả kho tài khoản không được ngó tới.

Đo thật 24/08/2026 trên máy chủ:

  · cấu hình có một psid tĩnh 153 ký tự, và nó ĐÃ CHẾT — log làm nóng ghi
    {"event": "gma_client_init", "psid_prefix": "g.a000BAmvH3", "auth": false}
    rồi {"event": "gma_prewarm_khach", "profile": "static-config"};
  · cùng file cấu hình liệt kê 9 profile Google thật, kho có 10 tài khoản
    gemini_web_api đều `active`.

Tức cả đường gma chạy bằng một cookie khách đã hỏng trong khi 9 tài khoản khoẻ
nằm không. Và cookie tĩnh mang profile "static-config" nên KHÔNG tự chữa được:
đường relogin chỉ nhận profile `google-*` (mới có creds đã lưu).
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")

import api.gemini_web as gw  # noqa: E402

PSID_TINH = "g.a000BAmvH3" + "t" * 40
PSID_KHO = "g.a000Awluv1" + "k" * 40


class _MoiTruong:
    """Cấu hình + kho tài khoản giả cho `_get_cookies_ranked`."""

    def __init__(self, cfg: dict, profiles: list[str], cookie_theo_profile: dict):
        self.cfg = cfg
        self.profiles = profiles
        self.cookie = cookie_theo_profile
        self.da_relogin: list[str] = []

    def __enter__(self):
        from services.account_service import account_service
        self._p = [
            mock.patch.object(gw, "_cfg", return_value=self.cfg),
            mock.patch.object(gw, "_profiles", return_value=self.profiles),
            mock.patch.object(gw, "_fetch_cookies_from_solver",
                              side_effect=lambda p: self.cookie.get(p, {})),
            mock.patch.object(gw, "_auth_status", {}),
            mock.patch.object(gw, "_rr_offset", [0]),
            mock.patch.object(account_service, "normalize_and_rank_accounts",
                              side_effect=lambda raw, **kw: raw),
            mock.patch("services.solver_selfheal.try_relogin",
                       side_effect=lambda url, key, loai, p: self.da_relogin.append(p)),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()


class KhoTruocCookieTinhSauTests(unittest.TestCase):
    CFG = {"psid": PSID_TINH, "psidts": "ts-tinh"}

    def test_co_tai_khoan_trong_kho_thi_dung_kho(self):
        with _MoiTruong(self.CFG, ["google-benbap"],
                        {"google-benbap": {"__Secure-1PSID": PSID_KHO,
                                           "__Secure-1PSIDTS": "ts-kho"}}):
            ra = gw._get_cookies_ranked()
        self.assertEqual([x[2] for x in ra], ["google-benbap"],
                         "cookie tĩnh chết vẫn chặn mất cả kho tài khoản khoẻ")

    def test_kho_khong_ra_gi_thi_moi_lui_ve_cookie_tinh(self):
        with _MoiTruong(self.CFG, ["google-benbap"], {"google-benbap": {}}):
            ra = gw._get_cookies_ranked()
        self.assertEqual(ra, [(PSID_TINH, "ts-tinh", "static-config")])

    def test_chi_cau_hinh_moi_psid_thi_van_chay_nhu_cu(self):
        """Ai không dùng captcha-solver, chỉ dán cookie tay, không được hỏng."""
        with _MoiTruong(self.CFG, [], {}):
            ra = gw._get_cookies_ranked()
        self.assertEqual(ra, [(PSID_TINH, "ts-tinh", "static-config")])

    def test_khong_co_cookie_tinh_va_kho_rong_thi_tra_rong(self):
        with _MoiTruong({}, [], {}):
            self.assertEqual(gw._get_cookies_ranked(), [])

    def test_kho_chet_thi_van_kich_hoat_dang_nhap_lai(self):
        """Lùi về cookie tĩnh không được nuốt mất bước tự chữa của kho."""
        with _MoiTruong(self.CFG, ["google-benbap"], {"google-benbap": {}}) as mt:
            gw._get_cookies_ranked()
        self.assertEqual(mt.da_relogin, ["google-benbap"])


if __name__ == "__main__":
    unittest.main()
