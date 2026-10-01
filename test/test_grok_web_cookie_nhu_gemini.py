"""Grok web lấy cookie như Gemini: hồ sơ solver trước, file json là đường lùi.

Không gọi mạng. Không đọc cookie thật.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")

import api.grok_web as gw  # noqa: E402


class CheDoTests(unittest.TestCase):
    def test_trong_va_auto_ve_fast(self):
        self.assertEqual(gw.che_do(""), "fast")
        self.assertEqual(gw.che_do("auto"), "fast")
        self.assertEqual(gw.che_do("fast"), "fast")

    def test_expert_giu_expert(self):
        self.assertEqual(gw.che_do("expert"), "expert")
        self.assertEqual(gw.che_do("grok-chat-heavy"), "heavy")


class HopVanBanTests(unittest.TestCase):
    def test_ghep_role(self):
        text = gw.hop_van_ban([
            {"role": "user", "content": "xin chao"},
            {"role": "assistant", "content": [{"type": "text", "text": "chao"}]},
        ])
        self.assertIn("[user]\nxin chao", text)
        self.assertIn("[assistant]\nchao", text)


class CookieTests(unittest.TestCase):
    def test_bo_profile_placeholder(self):
        with mock.patch.object(gw, "_cfg", return_value={
            "profiles": ["a-default", "grok-ben", "b_default"],
        }), mock.patch("services.account_service.account_service") as acc:
            acc.list_accounts.return_value = []
            self.assertEqual(gw._profiles(), ["grok-ben"])

    def test_file_thang_khong_hoi_chrome(self):
        with mock.patch.object(gw, "_fetch_solver", return_value={"sso": "solver"}) as lay, \
                mock.patch.object(gw, "_file_cookies", return_value={"sso": "file"}):
            self.assertEqual(gw.tai_cookie()["sso"], "file")
            lay.assert_not_called()

    def test_khong_ho_so_thi_doc_file(self):
        with mock.patch.object(gw, "_profiles", return_value=[]), \
                mock.patch.object(gw, "_file_cookies", return_value={"sso": "file"}):
            self.assertEqual(gw.tai_cookie()["sso"], "file")

    def test_khong_co_sso_thi_bao(self):
        with mock.patch.object(gw, "_profiles", return_value=[]), \
                mock.patch.object(gw, "_file_cookies", return_value={}):
            with self.assertRaises(RuntimeError):
                gw.tai_cookie()
