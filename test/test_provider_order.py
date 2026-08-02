"""Provider cạn tài khoản thì xuống cuối, hồi thì về vị trí cũ.

Bối cảnh đo thật 02/08 trên máy chủ: combo `AI text` có `cx/gpt-5.5:text` ở vị
trí SỐ 1. Cả 7 tài khoản Codex cạn quota text, nên mỗi lượt chat đều bắt đầu
bằng việc đốt hết pool Codex rồi mới rơi xuống thành viên số 2.

Bất biến quan trọng nhất: KHÔNG hạ provider vì một cú 429 lẻ. Một 429 nghĩa là
MỘT tài khoản cạn, và provider tự xoay tài khoản khác — hạ ở đó là hạ oan cả
provider tốt nhất. Chỉ hạ khi provider báo hết credential.
"""
from __future__ import annotations

import os
import time
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.config import config  # noqa: E402
from services.provider_order import ProviderOrder, can_pool  # noqa: E402


def _sp(**over):
    base = {"enabled": True, "weighted": True, "provider_demote_seconds": 900}
    base.update(over)
    return mock.patch.dict(config.data, {"smart_pool": base})


class _R:
    """Đủ giống BackendRoute cho phép đo thứ tự."""
    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model

    def __repr__(self) -> str:      # cho thông báo lỗi đọc được
        return f"{self.provider}:{self.model}"


def _combo_ai_text() -> list[_R]:
    """Đúng hình dạng combo `AI text` thật (rút gọn): cx đứng đầu, nv xen giữa."""
    return [
        _R("openai_oauth", "gpt-5.5"),
        _R("nvidia_nim", "openai/gpt-oss-120b"),
        _R("opencode", "laguna-s-2.1-free"),
        _R("nvidia_nim", "mistralai/mistral-nemotron"),
        _R("gemini_free", "gemini-2.5-flash"),
    ]


# Không cho phép đo chạm vào pool thật — trả None = "provider không hỏi được pool".
_KHONG_POOL = mock.patch("services.provider_order._pool_con_song", return_value=None)


class NhanDienCanPoolTests(unittest.TestCase):
    """Nguyên văn các câu lỗi đang có trong kho code."""

    def test_nhan_cau_bao_het_credential(self):
        for msg in (
            "No Codex OAuth tokens available. Add via OAuth login or import 9router backup.",
            "All Gemini API keys rate limited. Try again later.",
            "All NVIDIA NIM API keys rate limited",
            "Agnes AI key not configured",
            "[tokenrouter] chưa có API key trong cấu hình",
            "no available image quota",
            "Agnes AI: Máy chủ đang bận (Service Busy) hoặc API Key bị giới hạn. (x)",
        ):
            self.assertTrue(can_pool(msg), msg)

    def test_KHONG_nhan_429_le_va_loi_thuong(self):
        for msg in (
            "Codex error 429: {\"error\":{\"type\":\"usage_limit_reached\"}}",
            "Codex OAuth token 401 after refresh",
            "payload too large",
            "Error 500: upstream boom",
            "read timeout",
            "",
        ):
            self.assertFalse(can_pool(msg), msg)


class HaXuongCuoiTests(unittest.TestCase):
    def test_429_le_KHONG_ha(self):
        po = ProviderOrder()
        with _sp(), _KHONG_POOL:
            po.record_failure("openai_oauth", 429, "Codex error 429: usage_limit_reached")
            self.assertFalse(po.is_demoted("openai_oauth"))

    def test_can_pool_thi_ha(self):
        po = ProviderOrder()
        with _sp(), _KHONG_POOL:
            po.record_failure("openai_oauth", 0, "No Codex OAuth tokens available.")
            self.assertTrue(po.is_demoted("openai_oauth"))

    def test_thu_tu_moi_day_provider_bi_ha_ra_cuoi(self):
        po = ProviderOrder()
        with _sp(), _KHONG_POOL:
            po.record_failure("openai_oauth", 0, "No Codex OAuth tokens available.")
            ra = po.reorder(_combo_ai_text())
        self.assertEqual([r.provider for r in ra], [
            "nvidia_nim", "opencode", "nvidia_nim", "gemini_free", "openai_oauth"])

    def test_khong_mat_route_nao(self):
        """Hạ là ĐỔI THỨ TỰ, không phải bỏ qua — combo vẫn đủ đường thoát."""
        po = ProviderOrder()
        goc = _combo_ai_text()
        with _sp(), _KHONG_POOL:
            po.record_failure("openai_oauth", 0, "No Codex OAuth tokens available.")
            po.record_failure("nvidia_nim", 0, "All NVIDIA NIM API keys rate limited")
            ra = po.reorder(goc)
        self.assertEqual(len(ra), len(goc))
        self.assertEqual(sorted(map(repr, ra)), sorted(map(repr, goc)))

    def test_giu_thu_tu_tuong_doi_trong_tung_nhom(self):
        po = ProviderOrder()
        with _sp(), _KHONG_POOL:
            po.record_failure("nvidia_nim", 0, "All NVIDIA NIM API keys rate limited")
            ra = po.reorder(_combo_ai_text())
        self.assertEqual([r.model for r in ra], [
            "gpt-5.5", "laguna-s-2.1-free", "gemini-2.5-flash",
            "openai/gpt-oss-120b", "mistralai/mistral-nemotron"])

    def test_khong_ha_gi_thi_thu_tu_y_nguyen(self):
        po = ProviderOrder()
        goc = _combo_ai_text()
        with _sp(), _KHONG_POOL:
            self.assertEqual([r.provider for r in po.reorder(goc)],
                             [r.provider for r in goc])


class VeViTriCuTests(unittest.TestCase):
    def test_thanh_cong_la_ve_ngay(self):
        po = ProviderOrder()
        with _sp(), _KHONG_POOL:
            po.record_failure("openai_oauth", 0, "No Codex OAuth tokens available.")
            po.record_success("openai_oauth")
            self.assertFalse(po.is_demoted("openai_oauth"))
            self.assertEqual(po.reorder(_combo_ai_text())[0].provider, "openai_oauth")

    def test_het_cua_so_thi_ve(self):
        po = ProviderOrder()
        with _sp(provider_demote_seconds=60), _KHONG_POOL:
            po.record_failure("gemini_free", 0, "All Gemini API keys rate limited.")
            self.assertTrue(po.is_demoted("gemini_free"))
            po._ha["gemini_free"].den_luc = time.time() - 1   # tua hết cửa sổ
            self.assertFalse(po.is_demoted("gemini_free"))

    def test_pool_hoi_thi_ve_NGAY_khong_cho_het_cua_so(self):
        """Đúng yêu cầu: 'chỉ cần nó khôi phục là đưa về vị trí đầu'."""
        po = ProviderOrder()
        with _sp(provider_demote_seconds=3600):
            with mock.patch("services.provider_order._pool_con_song", return_value=False):
                po.record_failure("openai_oauth", 0, "No Codex OAuth tokens available.")
                self.assertTrue(po.is_demoted("openai_oauth"))
            with mock.patch("services.provider_order._pool_con_song", return_value=True):
                self.assertFalse(po.is_demoted("openai_oauth"))
                self.assertEqual(po.reorder(_combo_ai_text())[0].provider, "openai_oauth")

    def test_provider_dung_api_key_thi_pool_khong_tra_loi_duoc(self):
        """gemini_free/nvidia_nim không có pool tài khoản → phải dựa cửa sổ giờ,
        chứ không được coi 'pool rỗng' là mãi mãi bị hạ."""
        from services.provider_order import _pool_con_song
        self.assertIsNone(_pool_con_song("gemini_free"))
        self.assertIsNone(_pool_con_song("nvidia_nim"))
        self.assertIsNone(_pool_con_song("opencode"))


class TatDuocTests(unittest.TestCase):
    def test_tat_smart_pool_thi_khong_doi_thu_tu(self):
        po = ProviderOrder()
        goc = _combo_ai_text()
        with _sp(enabled=True), _KHONG_POOL:
            po.record_failure("openai_oauth", 0, "No Codex OAuth tokens available.")
        with _sp(enabled=False), _KHONG_POOL:
            self.assertFalse(po.is_demoted("openai_oauth"))
            self.assertEqual([r.provider for r in po.reorder(goc)],
                             [r.provider for r in goc])


class TrangThaiTests(unittest.TestCase):
    def test_get_stats_bao_provider_dang_bi_ha(self):
        po = ProviderOrder()
        with _sp(), _KHONG_POOL:
            po.record_failure("openai_oauth", 0, "No Codex OAuth tokens available.")
            st = po.get_stats()
        self.assertEqual(st["so_provider_bi_ha"], 1)
        self.assertIn("openai_oauth", st["providers"])
        self.assertGreater(st["providers"]["openai_oauth"]["con_lai_giay"], 0)


class DuocNoiVaoVongComboTests(unittest.TestCase):
    def setUp(self):
        import pathlib
        nguon = (pathlib.Path(__file__).resolve().parents[1]
                 / "services" / "protocol" / "openai_v1_chat_complete.py")
        self.code = "\n".join(l for l in nguon.read_text("utf-8").splitlines()
                              if not l.lstrip().startswith("#"))

    def test_doi_thu_tu_TRUOC_khi_vao_vong(self):
        self.assertLess(self.code.index("routes = provider_order.reorder(routes)"),
                        self.code.index("for _route_idx, route in enumerate(routes):"))

    def test_ghi_nhan_ca_thanh_cong_va_that_bai(self):
        self.assertIn("provider_order.record_success(route.provider)", self.code)
        self.assertIn("provider_order.record_failure(route.provider,", self.code)


if __name__ == "__main__":
    unittest.main()
