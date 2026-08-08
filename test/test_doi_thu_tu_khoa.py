"""Đổi thứ tự khoá trong pool phải làm phía MÁY CHỦ, theo chỉ số.

Trước đây web GET toàn bộ config, tự xáo mảng `api_keys` rồi POST lại. Cách đó
chỉ chạy được khi trình duyệt cầm được giá trị khoá thật — đúng thứ vừa bị bỏ
đi khi che secret. Không chuyển sang chỉ số thì bật cờ che là nút "đưa lên #1"
thành nút không làm gì, IM LẶNG: mảng khoá tới nơi thành nhãn `is_set`, bộ lọc
ghi bỏ qua, giao diện vẫn báo thành công.

Kiểu hỏng im lặng đó là thứ đã tốn nhiều thời gian nhất trong dự án này, nên
nó có test riêng.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

CAU_HINH = {
    "providers": {
        "gemini_free": {"enabled": True,
                        "api_key": "khoa-A",
                        "api_keys": ["khoa-A", "khoa-B", "khoa-C"]},
        "serper": {"api_key": "chi-mot-khoa"},
    },
}


def _xao(khoa: list[str], index: int, action: str) -> list[str]:
    """Cùng phép biến đổi với endpoint — giữ ở đây để test độc lập tầng HTTP."""
    ra = list(khoa)
    muc = ra.pop(index)
    if action == "promote":
        ra.insert(0, muc)
    else:
        ra.append(muc)
    return ra


class PhepXaoTests(unittest.TestCase):
    def test_dua_len_dau(self):
        self.assertEqual(_xao(["A", "B", "C"], 2, "promote"), ["C", "A", "B"])

    def test_day_xuong_cuoi(self):
        self.assertEqual(_xao(["A", "B", "C"], 0, "demote"), ["B", "C", "A"])

    def test_dua_len_dau_cai_dang_dau_thi_khong_doi(self):
        self.assertEqual(_xao(["A", "B", "C"], 0, "promote"), ["A", "B", "C"])


class QuaConfigUpdateTests(unittest.TestCase):
    """Ghi thật qua `config.update` — nhánh merge của `api_keys` khá rắc rối."""

    def setUp(self):
        from services.config import config
        self.config = config
        self._data_cu = config.data
        self._save_cu = config._save
        config.data = copy.deepcopy(CAU_HINH)
        config._save = lambda: None
        self.addCleanup(self._tra_lai)

    def _tra_lai(self):
        self.config.data = self._data_cu
        self.config._save = self._save_cu

    def _goi(self, pid: str, index: int, action: str):
        cfg = (self.config.data.get("providers") or {}).get(pid) or {}
        khoa = list(cfg.get("api_keys") or [])
        if not khoa and str(cfg.get("api_key") or "").strip():
            khoa = [str(cfg["api_key"]).strip()]
        khoa = _xao(khoa, index, action)
        self.config.update({"providers": {pid: {"api_keys": khoa, "api_key": khoa[0]}}})
        return khoa

    def test_thu_tu_moi_duoc_luu_va_api_key_don_theo_cung(self):
        self._goi("gemini_free", 2, "promote")
        g = self.config.data["providers"]["gemini_free"]
        self.assertEqual(g["api_keys"], ["khoa-C", "khoa-A", "khoa-B"])
        self.assertEqual(g["api_key"], "khoa-C",
                         "api_key đơn không theo kịp api_keys[0]")

    def test_khong_lam_mat_khoa_nao(self):
        self._goi("gemini_free", 0, "demote")
        self.assertEqual(sorted(self.config.data["providers"]["gemini_free"]["api_keys"]),
                         ["khoa-A", "khoa-B", "khoa-C"])

    def test_khong_dung_provider_khac(self):
        self._goi("gemini_free", 1, "promote")
        self.assertEqual(self.config.data["providers"]["serper"]["api_key"],
                         "chi-mot-khoa")

    def test_provider_chi_co_api_key_don_van_xao_duoc(self):
        khoa = self._goi("serper", 0, "promote")
        self.assertEqual(khoa, ["chi-mot-khoa"])


class NoiGoiTests(unittest.TestCase):
    def test_endpoint_ton_tai_va_khong_tra_khoa_ve(self):
        src = (GOC / "api/system.py").read_text(encoding="utf-8")
        self.assertIn('@router.post("/api/providers/{provider_id}/keys/reorder")', src)
        i = src.index("async def doi_thu_tu_khoa")
        than = src[i:i + 2200]
        self.assertIn('return {"ok": True, "count": len(khoa)}', than,
                      "phản hồi không được mang giá trị khoá về trình duyệt")
        self.assertIn("require_admin(authorization)", than)

    def test_index_ngoai_pham_vi_bi_tu_choi(self):
        src = (GOC / "api/system.py").read_text(encoding="utf-8")
        i = src.index("async def doi_thu_tu_khoa")
        self.assertIn("ngoài phạm vi", src[i:i + 2200])

    def test_web_khong_con_tu_xao_mang_khoa(self):
        """Còn sót đường cũ thì bật cờ che là nó hỏng im lặng trở lại."""
        src = (GOC / "web/src/app/accounts/page.tsx").read_text(encoding="utf-8")
        i = src.index("handleReorderProviderKey")
        than = src[i:i + 1400]
        self.assertIn("/keys/reorder", than)
        self.assertNotIn("cfg.api_keys = keysArr", than,
                         "web vẫn tự xáo mảng khoá tại chỗ")


if __name__ == "__main__":
    unittest.main()
