"""Antigravity tự theo model THẬT của tài khoản — chủ máy 06/10/2026: "antigravity giờ model cũng đổi rồi, tôi cần
tự động cập nhật". Trước đó danh sách và mặc định là tên cố định (`gemini-3.1-pro-high`).

Chưa có tài khoản Antigravity nào trên máy chủ lúc viết — phản hồi Google dưới đây là giả, theo dạng
`v1internal:fetchAvailableModels` (models: {id: {quotaInfo: {remainingFraction}}}). Kiểm thật khi có tài khoản.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.providers import antigravity as ag  # noqa: E402

CO = {
    "gemini-3.5-pro-high": {"quotaInfo": {"remainingFraction": 0.8}},
    "gemini-3.5-pro-low": {"quotaInfo": {"remainingFraction": 0.8}},
    "gemini-3.1-pro-high": {"quotaInfo": {"remainingFraction": 0}},      # hết hạn mức
    "gemini-3.8-flash": {},
    "gemini-3.5-flash-lite": {},
    "claude-sonnet-4-6": {},
}


class ChonModelTests(unittest.TestCase):
    def test_ten_con_va_con_han_thi_giu(self):
        self.assertEqual("gemini-3.8-flash", ag.chon_model("gemini-3.8-flash", CO))

    def test_ten_bi_go_hoac_het_han_thi_lay_cung_dong_moi_nhat_cung_muc_nghi(self):
        self.assertEqual("gemini-3.5-pro-high", ag.chon_model("gemini-3.1-pro-high", CO))
        self.assertEqual("gemini-3.5-pro-low", ag.chon_model("gemini-3.0-pro-low", CO))
        self.assertEqual("gemini-3.8-flash", ag.chon_model("gemini-3.1-flash-high", CO))

    def test_ten_bac_theo_thang(self):
        self.assertEqual("gemini-3.5-pro-high", ag.chon_model("kho", CO))
        self.assertEqual("gemini-3.8-flash", ag.chon_model("vua", CO))
        self.assertEqual("gemini-3.5-flash-lite", ag.chon_model("nhe", CO))
        het_pro = {k: v for k, v in CO.items() if "pro" not in k}
        self.assertEqual("gemini-3.8-flash", ag.chon_model("kho", het_pro), "hết pro thì xuống flash")

    def test_goi_dich_danh_claude_hoac_chua_biet_danh_sach_thi_giu_nguyen(self):
        self.assertEqual("claude-opus-9", ag.chon_model("claude-opus-9", CO))
        self.assertEqual("gemini-3.1-pro-high", ag.chon_model("gemini-3.1-pro-high", {}))


class HoiDanhSachTests(unittest.TestCase):
    def setUp(self):
        ag._MODEL_DEM.clear()
        self.addCleanup(ag._MODEL_DEM.clear)

    def _tra(self, ma: int, body):
        r = mock.MagicMock()
        r.status_code, r.json.return_value = ma, body
        return r

    def test_doc_ca_dang_tu_dien_lan_danh_sach_va_dem(self):
        with mock.patch.object(ag.requests, "post", return_value=self._tra(200, {"models": {
                "models/gemini-3.8-flash": {"displayName": "Gemini 3.8 Flash"}}})) as p:
            self.assertEqual({"gemini-3.8-flash"}, set(ag.danh_sach_model({"access_token": "t1", "project_id": "p"})))
            ag.danh_sach_model({"access_token": "t1"})
            self.assertEqual(1, p.call_count, "lần hai lấy đệm")
        with mock.patch.object(ag.requests, "post", return_value=self._tra(200, {"models": [{"id": "gemini-4-pro"}]})):
            self.assertEqual({"gemini-4-pro"}, set(ag.danh_sach_model({"access_token": "t2"})))

    def test_khong_hoi_duoc_thi_rong(self):
        with mock.patch.object(ag.requests, "post", return_value=self._tra(403, {})):
            self.assertEqual({}, ag.danh_sach_model({"access_token": "t3"}))
