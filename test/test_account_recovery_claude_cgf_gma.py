"""Kiểm phiên + khôi phục giống Flow cho Claude / ChatGPT free / Gemini web.

Ba provider này nói chuyện thẳng bằng HTTP (cookie/JWT đã có) — không cần mở
trình duyệt cho bước KIỂM, khác Flow (`check-project` luôn mở trang). Chỉ khi
kiểm ra 'mat' mới chạm `_freshen_google` (dùng chung với Flow, không đổi).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import services.account_recovery as ar


class _Tra:
    def __init__(self, status_code: int, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = ""

    def json(self):
        return self._payload


class ClaudeVerifyTest(unittest.TestCase):
    def test_KHONG_CO_KHOA_TRA_MAT(self) -> None:
        self.assertEqual(ar._claude_verify(""), "mat")

    def test_200_CO_ORG_TRA_OK(self) -> None:
        with mock.patch("curl_cffi.requests.get", return_value=_Tra(200, [{"uuid": "x"}])):
            self.assertEqual(ar._claude_verify("sk"), "ok")

    def test_401_TRA_MAT(self) -> None:
        with mock.patch("curl_cffi.requests.get", return_value=_Tra(401)):
            self.assertEqual(ar._claude_verify("sk"), "mat")

    def test_429_TRA_BAN(self) -> None:
        with mock.patch("curl_cffi.requests.get", return_value=_Tra(429)):
            self.assertEqual(ar._claude_verify("sk"), "ban")

    def test_LOI_MANG_TRA_CHUA_RO(self) -> None:
        with mock.patch("curl_cffi.requests.get", side_effect=TimeoutError("x")):
            self.assertEqual(ar._claude_verify("sk"), "chua_ro")


class ClaudeSessionTrangThaiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._p = mock.patch.object(ar, "_solver_cfg", return_value=("http://solver", "k"))
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_SOLVER_404_TRA_MAT(self) -> None:
        with mock.patch("requests.get", return_value=SimpleNamespace(status_code=404)):
            self.assertEqual(ar._claude_session_trang_thai("google-a"), "mat")

    def test_SOLVER_429_TRA_BAN(self) -> None:
        with mock.patch("requests.get", return_value=SimpleNamespace(status_code=429)):
            self.assertEqual(ar._claude_session_trang_thai("google-a"), "ban")

    def test_SOLVER_LOI_MANG_TRA_CHUA_RO(self) -> None:
        with mock.patch("requests.get", side_effect=ConnectionError("x")):
            self.assertEqual(ar._claude_session_trang_thai("google-a"), "chua_ro")

    def test_CO_SESSION_KEY_thi_VERIFY_TIEP(self) -> None:
        tra = SimpleNamespace(status_code=200, json=lambda: {"session_key": "sk-thật"})
        with mock.patch("requests.get", return_value=tra), \
             mock.patch.object(ar, "_claude_verify", return_value="ok") as v:
            self.assertEqual(ar._claude_session_trang_thai("google-a"), "ok")
        v.assert_called_once_with("sk-thật")


class ClaudeRecoverAndNotifyTest(unittest.TestCase):
    def setUp(self) -> None:
        for bang in (ar._last_attempt,):
            bang.clear()
        ar._glogin_captcha_until = 0.0
        ar._glogin_captcha_profile = ""
        self._n = mock.patch.object(ar, "_notify")
        self.notify = self._n.start()
        self.addCleanup(self._n.stop)

    def test_DA_OK_thi_BAO_XONG_NGAY_KHONG_DANG_NHAP(self) -> None:
        freshen = mock.patch.object(ar, "_freshen_google", side_effect=AssertionError("không cần đăng nhập"))
        with mock.patch.object(ar, "_claude_session_trang_thai", return_value="ok"), freshen:
            ar.claude_recover_and_notify("google-benbap115", reason="test")
        tin = "".join(c.args[0] for c in self.notify.call_args_list)
        self.assertIn("✅ Claude", tin)

    def test_MAT_ROI_DANG_NHAP_OK_thi_BAO_XONG(self) -> None:
        # T0=mat, T1 (2 lượt)=mat,mat, T2 freshen OK, T3-1=ok.
        with mock.patch.object(ar, "_claude_session_trang_thai",
                               side_effect=["mat", "mat", "mat", "ok"]), \
             mock.patch.object(ar, "_freshen_google", return_value=True), \
             mock.patch.object(ar.time, "sleep", return_value=None):
            ar.claude_recover_and_notify("google-benbap115", reason="test")
        tin = "".join(c.args[0] for c in self.notify.call_args_list)
        self.assertIn("✅ Claude", tin)
        self.assertIn("đăng nhập Google", tin)


class CgfSessionTrangThaiTest(unittest.TestCase):
    def test_KHONG_CO_JWT_TRONG_KHO_TRA_MAT(self) -> None:
        with mock.patch("services.account_service.account_service") as svc, \
             mock.patch("services.account_service.account_group", return_value="free"):
            svc._accounts = {}
            self.assertEqual(ar._cgf_session_trang_thai("a@gmail.com"), "mat")

    def test_CO_JWT_VA_GOI_DUOC_TRA_OK(self) -> None:
        acc = {"email": "a@gmail.com"}
        with mock.patch("services.account_service.account_service") as svc, \
             mock.patch("services.account_service.account_group", return_value="free"), \
             mock.patch("services.openai_backend_api.OpenAIBackendAPI") as Api:
            svc._accounts = {"eyJabc": acc}
            Api.return_value.list_models.return_value = {}
            self.assertEqual(ar._cgf_session_trang_thai("a@gmail.com"), "ok")

    def test_401_TRA_MAT(self) -> None:
        acc = {"email": "a@gmail.com"}
        with mock.patch("services.account_service.account_service") as svc, \
             mock.patch("services.account_service.account_group", return_value="free"), \
             mock.patch("services.openai_backend_api.OpenAIBackendAPI") as Api:
            svc._accounts = {"eyJabc": acc}
            Api.return_value.list_models.side_effect = RuntimeError("models failed: status=401, body=")
            self.assertEqual(ar._cgf_session_trang_thai("a@gmail.com"), "mat")

    def test_LOI_MANG_TRA_CHUA_RO(self) -> None:
        acc = {"email": "a@gmail.com"}
        with mock.patch("services.account_service.account_service") as svc, \
             mock.patch("services.account_service.account_group", return_value="free"), \
             mock.patch("services.openai_backend_api.OpenAIBackendAPI") as Api:
            svc._accounts = {"eyJabc": acc}
            Api.return_value.list_models.side_effect = TimeoutError("mạng lỗi")
            self.assertEqual(ar._cgf_session_trang_thai("a@gmail.com"), "chua_ro")


class GmaSessionTrangThaiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._p = mock.patch.object(ar, "_solver_cfg", return_value=("http://solver", "k"))
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_404_KHONG_COOKIE_TRA_MAT(self) -> None:
        with mock.patch("requests.get", return_value=SimpleNamespace(status_code=404)):
            self.assertEqual(ar._gma_session_trang_thai("google-a"), "mat")

    def test_429_TRA_BAN(self) -> None:
        with mock.patch("requests.get", return_value=SimpleNamespace(status_code=429)):
            self.assertEqual(ar._gma_session_trang_thai("google-a"), "ban")

    def test_CO_COOKIE_VA_AUTHENTICATED_TRA_OK(self) -> None:
        with mock.patch("requests.get", return_value=SimpleNamespace(status_code=200)), \
             mock.patch.object(ar, "_gma_authenticated", return_value=True):
            self.assertEqual(ar._gma_session_trang_thai("google-a"), "ok")

    def test_CO_COOKIE_NHUNG_CHUA_XAC_THUC_TRA_MAT(self) -> None:
        with mock.patch("requests.get", return_value=SimpleNamespace(status_code=200)), \
             mock.patch.object(ar, "_gma_authenticated", return_value=False):
            self.assertEqual(ar._gma_session_trang_thai("google-a"), "mat")


if __name__ == "__main__":
    unittest.main()
