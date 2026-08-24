"""Câu lỗi "No Codex OAuth tokens available" phải nói rõ là tình huống nào.

Hai chuyện hoàn toàn khác nhau dùng chung một câu:

  1. Kho KHÔNG có tài khoản codex nào → cần người thêm tài khoản.
  2. Kho có đủ tài khoản khoẻ, nhưng chính request này đã thử hết (hoặc chúng
     đang nghỉ vì hết lượt) → không thiếu gì cả, chờ quota hồi là tự về.

Đo thật 24/08/2026 trên máy chủ: kho có 8 tài khoản codex, tất cả `active`,
token đều là JWT hợp lệ (dài 1.690–1.964 ký tự) — mà log vẫn ra đúng câu khuyên
"Add via OAuth login or import 9router backup". Đi theo câu đó là đi sai đường:
codex vốn là đường mặc định, hết lượt thì tụt xuống free rồi tự quay lại.

Ràng buộc phải giữ: cụm "No Codex OAuth tokens available" đứng đầu câu, vì
`services/provider_order.py` nhận diện "cạn cả pool" bằng chính cụm đó để hạ
provider xuống cuối danh sách.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")

from services.account_service import account_service  # noqa: E402
from services.provider_order import _CAN_POOL  # noqa: E402
from services.providers import openai_oauth  # noqa: E402


def _tai_khoan(token: str, **thay_doi) -> dict:
    ra = {"access_token": token, "type": "codex", "plan": "free",
          "status": "active", "email": "x@y.z"}
    ra.update(thay_doi)
    return ra


class _Kho:
    """Thay kho tài khoản trong bộ nhớ của account_service."""

    def __init__(self, items: list[dict]):
        self.items = {i["access_token"]: i for i in items}

    def __enter__(self):
        self._p = mock.patch.object(account_service, "_accounts", self.items)
        self._p.start()
        return self

    def __exit__(self, *a):
        self._p.stop()


def _loi(items: list[dict], da_thu: set[str] | None = None) -> str:
    with _Kho(items):
        with mock.patch.object(openai_oauth, "_is_openai_api_only", return_value=False):
            try:
                openai_oauth.codex_oauth.get_token_for_request(da_thu or set())
            except RuntimeError as exc:
                return str(exc)
    return ""


class KhoRongTests(unittest.TestCase):
    def test_khong_co_tai_khoan_nao_thi_van_bao_cach_them(self):
        loi = _loi([])
        self.assertIn("Add via OAuth login", loi)


class KhoDuTaiKhoanTests(unittest.TestCase):
    TOKEN = ["eyJ" + "a" * 50, "eyJ" + "b" * 50, "eyJ" + "c" * 50]

    def test_da_thu_het_trong_request_nay_thi_noi_dung_nhu_vay(self):
        items = [_tai_khoan(t) for t in self.TOKEN]
        loi = _loi(items, da_thu=set(self.TOKEN))
        self.assertNotIn("Add via OAuth login", loi,
                         "khuyên thêm tài khoản trong khi kho đang đủ")
        self.assertIn("3 tài khoản", loi)
        self.assertIn("3 đã thử", loi)

    def test_dang_nghi_vi_het_luot_thi_noi_la_het_luot(self):
        items = [_tai_khoan(t, status="limited") for t in self.TOKEN]
        loi = _loi(items)
        self.assertIn("3 đang nghỉ", loi)
        self.assertIn("chờ quota hồi", loi)

    def test_van_bi_bo_xep_thu_tu_nhan_ra_la_can_pool(self):
        """Đổi câu chữ mà không khớp nữa thì provider hết bị hạ — hỏng lặng lẽ."""
        loi = _loi([_tai_khoan(t) for t in self.TOKEN], da_thu=set(self.TOKEN))
        self.assertTrue(any(mau.search(loi) for mau in _CAN_POOL), loi)


if __name__ == "__main__":
    unittest.main()
