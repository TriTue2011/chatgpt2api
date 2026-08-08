"""Gửi MỘT khoá đơn không bao giờ được xoá cả pool khoá.

SỰ CỐ THẬT 08/08/2026 — mất 4 trong 5 khoá Gemini của chủ máy.

Trang Search gửi `{api_key: <khoá đầu>, model: …}` khi bấm Lưu, không kèm
`api_keys`. `_normalize_multi_api_keys` dựng `api_keys=[khoá đó]` từ khoá đơn,
rồi nhánh đầu của `_merge_provider_config` tưởng đó là "danh sách mới có một
phần tử" và ghi đè cả pool.

Người dùng chỉ bấm Lưu ở màn hình tìm kiếm — không đụng gì tới khoá, không có
cảnh báo nào, và chỉ phát hiện ra khi mở lại trang Cài đặt. Ba khoá lấy lại
được từ `config.json.bak-0731`; khoá thứ tư thêm sau mốc sao lưu nên mất hẳn.

Đây là kiểu hỏng tệ nhất trong nhóm: im lặng, mất dữ liệu, và do một thao tác
chẳng liên quan gây ra.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.config import _merge_provider_config as gop  # noqa: E402

POOL = {"enabled": True, "model": "m",
        "api_key": "k1", "api_keys": ["k1", "k2", "k3", "k4", "k5"]}


class MotKhoaDonKhongXoaPoolTests(unittest.TestCase):
    def test_dung_kich_ban_da_gay_su_co(self):
        """`{api_key: <khoá đầu>, model}` — đúng payload trang Search từng gửi."""
        ra = gop(POOL, {"enabled": True, "api_key": "k1", "model": "m"})
        self.assertEqual(ra["api_keys"], ["k1", "k2", "k3", "k4", "k5"])

    def test_khoa_don_KHAC_thi_them_vao_dau_chu_khong_thay_the(self):
        ra = gop(POOL, {"api_key": "kMOI"})
        self.assertEqual(ra["api_keys"], ["kMOI", "k1", "k2", "k3", "k4", "k5"])
        self.assertEqual(ra["api_key"], "kMOI")

    def test_khong_nhac_gi_toi_khoa_thi_giu_nguyen(self):
        self.assertEqual(gop(POOL, {"model": "m2"})["api_keys"], POOL["api_keys"])

    def test_gui_RO_danh_sach_thi_moi_duoc_thay(self):
        """Sửa pool là hành động tường minh — chỉ `api_keys` mới làm được."""
        self.assertEqual(gop(POOL, {"api_keys": ["a", "b"]})["api_keys"], ["a", "b"])

    def test_gui_danh_sach_MOT_phan_tu_van_duoc_thay(self):
        """Người dùng xoá bớt còn một khoá là ý định thật, phải tôn trọng."""
        self.assertEqual(gop(POOL, {"api_keys": ["chi-mot"]})["api_keys"], ["chi-mot"])

    def test_apiKeys_camelCase_cung_duoc_coi_la_tuong_minh(self):
        self.assertEqual(gop(POOL, {"apiKeys": ["a"]})["api_keys"], ["a"])

    def test_provider_chua_co_pool_thi_khoa_don_van_tao_duoc(self):
        ra = gop({"enabled": True}, {"api_key": "k1"})
        self.assertEqual(ra["api_keys"], ["k1"])

    def test_danh_sach_RONG_khong_xoa_pool(self):
        """`api_keys: []` từ một form chưa nạp xong không được là lệnh xoá."""
        self.assertEqual(gop(POOL, {"api_keys": []})["api_keys"], POOL["api_keys"])

    def test_api_key_luon_khop_phan_tu_dau(self):
        for moi in ({"api_key": "k3"}, {"api_keys": ["k9", "k8"]}):
            ra = gop(POOL, moi)
            self.assertEqual(ra["api_key"], ra["api_keys"][0],
                             f"api_key lệch khỏi api_keys[0] với {moi}")


class TrangSearchKhongCon_GuiKhoaGeminiTests(unittest.TestCase):
    """Nguồn phát của sự cố đã bị gỡ ở 041ef4a — chốt để không quay lại."""

    def test_tab_search_khong_gui_KHOA_gemini(self):
        """Tab Search ĐƯỢC gửi `search_model` (trường của riêng nó), nhưng
        TUYỆT ĐỐI không kèm `api_key`/`api_keys` — đó là đường đã mất 4 khoá."""
        src = (GOC / "web/src/app/search/page.tsx").read_text(encoding="utf-8")
        i = src.index("gemini_free: {")
        khoi = src[i:i + 200]
        self.assertNotIn("api_key", khoi)
        self.assertIn("search_model", khoi)

    def test_tab_search_khong_con_o_nhap_khoa_gemini(self):
        src = (GOC / "web/src/app/search/page.tsx").read_text(encoding="utf-8")
        self.assertNotIn("setGeminiKey", src)


if __name__ == "__main__":
    unittest.main()
