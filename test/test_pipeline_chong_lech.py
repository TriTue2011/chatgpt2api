"""Hai lỗi làm combo code SAI LỆCH — đo thật trên máy chủ 31/07/2026.

1. Khoá bảng nghỉ chỉ dùng tên model: `claude/auto` phân giải ra model 'auto' và
   `gma/auto` CŨNG ra 'auto'. Claude hết tài khoản ⇒ ghi nghỉ cho khoá 'auto' ⇒
   `gma/auto` bị bỏ qua với lý do "đang cooldown" dù Gemini Web vẫn sống. Combo
   âm thầm mất một model khoẻ.

2. Người kiểm trùng người viết: cấu hình thật `code_reviewer = cx/auto`, mà
   cx/auto cũng là bố #2 và con #2. Khi claude/auto chết, cx/auto làm CẢ BA vai
   và duyệt đạt ngay vòng 0 — tầng kiểm duyệt thành hình thức.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from services.protocol.openai_v1_chat_complete import _chon_nguoi_kiem, _khoa_nghi


class KhoaNghiPhaiCoProvider(unittest.TestCase):
    def test_hai_provider_cung_ten_model_khong_dung_chung_khoa(self):
        claude = SimpleNamespace(provider="claude", model="auto")
        gemini = SimpleNamespace(provider="gemini_web_api", model="auto")
        self.assertNotEqual(_khoa_nghi(claude), _khoa_nghi(gemini))
        self.assertEqual(_khoa_nghi(claude), "claude/auto")
        self.assertEqual(_khoa_nghi(gemini), "gemini_web_api/auto")

    def test_cung_provider_khac_model_van_tach_khoa(self):
        a = SimpleNamespace(provider="opencode", model="ling-3.0-flash-free")
        b = SimpleNamespace(provider="opencode", model="north-mini-code-free")
        self.assertNotEqual(_khoa_nghi(a), _khoa_nghi(b))

    def test_route_hong_thi_khong_ne(self):
        # Không được ném lỗi giữa lúc đang xử lý một lỗi khác.
        self.assertIsInstance(_khoa_nghi(object()), str)


def _gia_router(bang: dict[str, tuple[str, str]]):
    """Router giả: tên → (provider, model)."""
    def _route(ten: str):
        if ten not in bang:
            raise ValueError(f"không định tuyến được {ten}")
        p, m = bang[ten]
        return SimpleNamespace(provider=p, model=m)
    return SimpleNamespace(route=_route)


class NguoiKiemPhaiKhacNguoiViet(unittest.TestCase):
    BANG = {
        "claude/auto": ("claude", "auto"),
        "cx/auto": ("openai_oauth", "cx/auto"),
        "nv/openai/gpt-oss-120b": ("nvidia_nim", "openai/gpt-oss-120b"),
    }
    BO = ["claude/auto:text", "cx/auto:text", "nv/openai/gpt-oss-120b:text"]
    CON = ["claude/auto:text", "cx/auto:text"]

    def _goi(self, reviewer: str, model_con: str, ranh=True) -> str:
        with mock.patch(
            "services.protocol.openai_v1_chat_complete.backend_router",
            _gia_router(self.BANG),
        ), mock.patch(
            "services.protocol.openai_v1_chat_complete.model_cooldown.is_available",
            return_value=ranh,
        ):
            return _chon_nguoi_kiem("code", reviewer, model_con, self.BO, self.CON)

    def test_trung_thi_doi_sang_model_khac(self):
        # Người viết = cx/auto, cấu hình kiểm = cx/auto → phải đổi.
        moi = self._goi("cx/auto", "cx/auto")
        self.assertNotEqual(moi, "cx/auto")
        self.assertEqual(moi, "claude/auto")

    def test_khong_trung_thi_giu_nguyen(self):
        self.assertEqual(self._goi("cx/auto", "auto"), "cx/auto")

    def test_khong_con_ai_khac_thi_giu_nguoi_kiem_cu(self):
        # Mọi ứng viên đều đang nghỉ → thà kiểm thiên vị hơn không kiểm.
        self.assertEqual(self._goi("cx/auto", "cx/auto", ranh=False), "cx/auto")

    def test_khong_bat_kiem_thi_khong_bat_dau(self):
        self.assertEqual(self._goi("", "cx/auto"), "")


if __name__ == "__main__":
    unittest.main()
