"""Tin khôi phục Claude phải khớp sự thật.

12/09/2026 chủ máy nhận liền hai tin cho google-benbap115: "✅ Khôi phục xong"
rồi "❌ Không lấy được session" — "Hai cái trái ngược nhau". Tin ✅ gửi ngay khi
solver trả một session, mà đó là đúng session claude.ai vừa từ chối.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class _Tra:
    def __init__(self, code: int, key: str = "") -> None:
        self.status_code = code
        self._key = key
        self.text = ""

    def json(self) -> dict:
        return {"session_key": self._key}


class BaoKhoiPhucClaudeTest(unittest.TestCase):
    def setUp(self) -> None:
        import api.claude as c

        self.c = c
        for bang in (c._solver_key_cache, c._relogin_cooldown, c._cho_xac_nhan,
                     c._claude_notify_at, c._profile_by_session):
            bang.clear()
        self.tin: list[str] = []
        for p in (mock.patch("services.captcha.captcha_base", return_value="http://solver"),
                  mock.patch("api.gemini_web._store_profiles", return_value=[]),
                  mock.patch("services.account_recovery._freshen_google", return_value=False),
                  mock.patch.object(c.time, "sleep", return_value=None),
                  mock.patch("services.notifier.notify_admin",
                             side_effect=lambda text, **k: self.tin.append(text))):
            p.start()
            self.addCleanup(p.stop)

    def _solver(self, sau_dang_nhap: str):
        """Solver giả: /session trả "cu"; sau khi gọi relogin thì trả `sau_dang_nhap`."""
        trang = {"key": "cu"}
        gia = mock.Mock()
        gia.get.side_effect = lambda url, **k: _Tra(200, trang["key"])

        def post(url, **k):
            trang["key"] = sau_dang_nhap
            return _Tra(200)
        gia.post.side_effect = post
        return mock.patch.object(self.c, "requests", gia)

    def _lay(self) -> str:
        cfg = {"captcha_solver_url": "http://solver", "profiles": ["google-benbap115"]}
        return self.c._fetch_session_key_from_solver(cfg, excluded_keys={"cu"})

    def test_LAY_LAI_DUNG_SESSION_VUA_BI_TU_CHOI_thi_KHONG_BAO_KHOI_PHUC_XONG(self) -> None:
        with self._solver("cu"):
            self.assertEqual(self._lay(), "")
        self.assertFalse(any("✅" in t for t in self.tin), self.tin)
        loi = [t for t in self.tin if "❌" in t]
        self.assertEqual(len(loi), 1)
        self.assertIn("đúng session vừa bị claude.ai từ chối", loi[0])

    def test_SESSION_MOI_chi_BAO_XONG_khi_DA_TRA_LOI_DUOC(self) -> None:
        with self._solver("moi"):
            self.assertEqual(self._lay(), "moi")
        self.assertEqual(self.tin, [], "lấy được session chưa phải là đã khôi phục")
        self.c._bao_khoi_phuc_that("moi")
        self.assertEqual(len([t for t in self.tin if "✅" in t]), 1)
        self.c._bao_khoi_phuc_that("moi")
        self.assertEqual(len([t for t in self.tin if "✅" in t]), 1, "báo một lần thôi")

    def test_STREAM_bao_XONG_khi_NHAN_CHUNK_DAU(self) -> None:
        self.c._cho_xac_nhan["moi"] = "google-benbap115"
        gen = self.c._bao_khi_chay_duoc(iter([{"a": 1}, {"a": 2}]), "moi")
        self.assertEqual(self.tin, [], "chưa đọc chunk nào thì chưa gửi yêu cầu thật")
        self.assertEqual(list(gen), [{"a": 1}, {"a": 2}])
        self.assertEqual(len([t for t in self.tin if "✅" in t]), 1)


if __name__ == "__main__":
    unittest.main()
