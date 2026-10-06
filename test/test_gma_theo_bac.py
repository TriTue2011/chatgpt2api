"""Gemini web THEO BẬC: Pro cho việc khó, flash cho việc vừa, lite cho việc nhẹ; hết hạn mức thì lùi bậc.

Chủ máy 06/10/2026: "sắp tới các tài khoản google free chỉ dùng được lite, làm cơ chế dùng các tài khoản pro, dùng
các model flash trước rồi quay về lite nếu hết quota"; "pro cho công việc khó, flash cho việc vừa, lite …". Hạng
từng tài khoản tự dò bằng registry RIÊNG của nó; hết hạn mức chỉ nghỉ ĐÚNG bậc đó trên tài khoản đó.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import api.gemini_web as g  # noqa: E402

#: Tài khoản Pro thấy cả ba; tài khoản miễn phí chỉ thấy lite.
HANG = {"psidA": {"gemini-3-pro", "gemini-3-flash", "gemini-flash-lite"}, "psidB": {"gemini-flash-lite"}}


class _Model:
    def __init__(self, ten: str):
        self.ten, self.is_available = ten, True


class _Client:
    def __init__(self, psid: str):
        self.psid = psid

    def resolve_model(self, spec):
        if spec not in HANG[self.psid]:
            raise ValueError(spec)
        return _Model(spec)

    def start_chat(self, **_k):
        return object()


class TheoBacTests(unittest.TestCase):
    def setUp(self):
        g._NGHI_BAC.clear()
        self.addCleanup(g._NGHI_BAC.clear)
        self.het: set[tuple[str, str]] = set()     # (psid, model) đang hết hạn mức
        self.goi: list[tuple[str, str]] = []

        def _sinh(client, p, files, model, **_k):
            self.goi.append((client.psid, model.ten))
            if (client.psid, model.ten) in self.het:
                raise RuntimeError("QUOTA_EXHAUSTED: hết lượt")
            return f"trả lời bằng {model.ten}"

        for ten, gia in (("_get_cookies_ranked", lambda required_features=None: [("psidA", "", "pA"), ("psidB", "", "pB")]),
                         ("_get_client", lambda psid, psidts: _Client(psid)),
                         ("_generate_text", _sinh), ("_prepare_files", lambda msgs: []),
                         ("_cleanup", lambda fs: None), ("_tim_tiep_noi", lambda msgs, ten: None),
                         ("_luu_tiep_noi", lambda *a, **k: None)):
            p = mock.patch.object(g, ten, side_effect=gia)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("services.account_service.account_service.record_profile_quota_failure")
        self.ha_hang = p.start()
        self.addCleanup(p.stop)

    def _hoi(self, model: str) -> str:
        kq = g.handle_gemini_web_api_chat(model, [{"role": "user", "content": "phân tích giúp"}], False, {})
        self.assertEqual(model, kq["model"])
        return kq["choices"][0]["message"]["content"]

    def test_viec_kho_dung_pro_cua_tai_khoan_co_pro(self):
        self.assertEqual("trả lời bằng gemini-3-pro", self._hoi("gma/kho"))

    def test_pro_het_han_muc_thi_lui_flash_va_chi_nghi_dung_bac_pro(self):
        self.het.add(("psidA", "gemini-3-pro"))
        self.assertEqual("trả lời bằng gemini-3-flash", self._hoi("gma/kho"))
        self.assertIn(("pA", "pro"), g._NGHI_BAC)
        self.assertNotIn(("pA", "flash"), g._NGHI_BAC)
        self.ha_hang.assert_not_called()          # không hạ hạng CẢ tài khoản như đường không bậc
        # Lượt sau không gõ lại Pro của tài khoản đang nghỉ.
        self.goi.clear()
        self._hoi("gma/kho")
        self.assertNotIn(("psidA", "gemini-3-pro"), self.goi)

    def test_flash_het_thi_ve_lite_tai_khoan_mien_phi_van_dung_duoc(self):
        self.het.update({("psidA", "gemini-3-flash"), ("psidA", "gemini-flash-lite")})
        self.assertEqual("trả lời bằng gemini-flash-lite", self._hoi("gma/vua"))
        self.assertEqual(("psidB", "gemini-flash-lite"), self.goi[-1])

    def test_viec_nhe_chi_dung_lite(self):
        self.assertEqual("trả lời bằng gemini-flash-lite", self._hoi("gma/nhe"))

    def test_model_thuong_van_nhu_cu(self):
        kq = g.handle_gemini_web_api_chat("gma/flash", [{"role": "user", "content": "chào"}], False, {})
        self.assertEqual("trả lời bằng gemini-3-flash", kq["choices"][0]["message"]["content"])
