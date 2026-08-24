"""Làm nóng thấy tài khoản Gemini là KHÁCH thì chữa ngay, đừng chờ ai đó dính lỗi.

Cookie phiên Google chết thì việc xoay `__Secure-1PSIDTS` (mỗi ~600 giây) không
cứu được gì — phải đăng nhập lại, và hệ thống có sẵn đường đó
(`services.account_recovery.gma_recover_and_notify` gọi captcha-solver).

Nhưng đường chữa chỉ nổ khi một request THẬT hỏng. Đo thật 24/08/2026 lúc 09:30
trên máy chủ: bước làm nóng lúc khởi động init xong tài khoản, ghi log

    {"event": "gma_client_init", "psid_prefix": "g.a000BAmvH3", "auth": false}

rồi đi tiếp. Tức hệ thống đã BIẾT tài khoản hỏng mà vẫn để người dùng đầu tiên
rơi vào đó ăn một lần lỗi.

Hai điều khoá ở đây: thấy khách thì gọi chữa, và tài khoản khoẻ thì tuyệt đối
không gọi (mỗi lần chữa là captcha-solver mở một trình duyệt thật).
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")

import api.gemini_web as gw  # noqa: E402

PSID_KHACH = "g.a000BAmvH3" + "x" * 40
PSID_KHOE = "g.a000Awluv1" + "y" * 40


class _LamNong:
    """Chạy prewarm_clients với pool giả, trả về các profile đã gọi chữa."""

    def __init__(self, creds, auth_theo_key: dict):
        self.creds = creds
        self.auth = auth_theo_key
        self.da_chua: list[str] = []

    def __enter__(self):
        self._p = [
            mock.patch.object(gw, "_get_cookies_ranked", return_value=self.creds),
            mock.patch.object(gw, "_get_client", side_effect=lambda psid, psidts: object()),
            mock.patch.object(gw, "_clients", {}),
            mock.patch.object(gw, "_auth_status", self.auth),
            mock.patch.object(gw, "_tu_chua_phien_nen",
                              side_effect=lambda profile, exc: self.da_chua.append(profile)),
            # Không nghỉ giữa các lần init cho test chạy nhanh.
            mock.patch.object(gw.time, "sleep", return_value=None),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()


class ThayKhachThiChuaTests(unittest.TestCase):
    def test_tai_khoan_khach_duoc_goi_chua_ngay(self):
        with _LamNong([(PSID_KHACH, "ts", "google-benbap")],
                      {PSID_KHACH[:32]: (0.0, False)}) as ln:
            gw.prewarm_clients()
        self.assertEqual(ln.da_chua, ["google-benbap"])

    def test_tai_khoan_khoe_thi_khong_dong_toi(self):
        """Gọi chữa oan là captcha-solver mở một trình duyệt thật, không rẻ."""
        with _LamNong([(PSID_KHOE, "ts", "google-tot")],
                      {PSID_KHOE[:32]: (0.0, True)}) as ln:
            gw.prewarm_clients()
        self.assertEqual(ln.da_chua, [])

    def test_khong_doc_duoc_trang_thai_thi_cung_khong_chua(self):
        """Chỉ chữa khi CHẮC CHẮN là khách; không biết thì để yên."""
        with _LamNong([(PSID_KHOE, "ts", "google-la")], {}) as ln:
            gw.prewarm_clients()
        self.assertEqual(ln.da_chua, [])

    def test_pool_nhieu_tai_khoan_chi_chua_dung_cai_hong(self):
        with _LamNong(
            [(PSID_KHOE, "ts", "google-tot"), (PSID_KHACH, "ts", "google-hong")],
            {PSID_KHOE[:32]: (0.0, True), PSID_KHACH[:32]: (0.0, False)},
        ) as ln:
            gw.prewarm_clients()
        self.assertEqual(ln.da_chua, ["google-hong"])


class ChiProfileCoCredsTests(unittest.TestCase):
    """`_tu_chua_phien_nen` tự bỏ qua profile không phải `google-*`."""

    def test_profile_khong_phai_google_thi_khong_goi_recover(self):
        goi: list[str] = []
        with mock.patch("services.account_recovery.gma_recover_and_notify",
                        side_effect=lambda *a, **kw: goi.append(a[0])):
            gw._tu_chua_phien_nen("gemini-web-default", RuntimeError("khách"))
        self.assertEqual(goi, [])


if __name__ == "__main__":
    unittest.main()
