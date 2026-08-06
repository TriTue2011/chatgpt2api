from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.config import config  # noqa: E402
from services.provider_circuit import ProviderCircuit  # noqa: E402


def _sp(**over):
    base = {"enabled": True, "weighted": True, "sticky_ttl_seconds": 900,
            "circuit_threshold": 3, "circuit_open_seconds": 60}
    base.update(over)
    return mock.patch.dict(config.data, {"smart_pool": base})


class ProviderCircuitTests(unittest.TestCase):
    def test_opens_after_threshold_consecutive_failures(self) -> None:
        pc = ProviderCircuit()
        with _sp(circuit_threshold=3):
            self.assertTrue(pc.allow("opencode"))
            pc.record_failure("opencode", 500, "boom")
            pc.record_failure("opencode", 500, "boom")
            self.assertTrue(pc.allow("opencode"))  # chưa đạt ngưỡng
            pc.record_failure("opencode", 500, "boom")
            self.assertFalse(pc.allow("opencode"))  # mở mạch

    def test_success_closes_and_resets_streak(self) -> None:
        pc = ProviderCircuit()
        with _sp(circuit_threshold=2):
            pc.record_failure("cx", 429, "quota")
            pc.record_success("cx")
            pc.record_failure("cx", 429, "quota")
            self.assertTrue(pc.allow("cx"))  # streak đã reset — 1 fail chưa mở

    def test_413_does_not_count_as_failure(self) -> None:
        pc = ProviderCircuit()
        with _sp(circuit_threshold=1):
            pc.record_failure("chatgpt_free", 413, "payload too large")
            self.assertTrue(pc.allow("chatgpt_free"))

    def test_half_open_after_open_seconds_then_close_on_success(self) -> None:
        pc = ProviderCircuit()
        with _sp(circuit_threshold=1, circuit_open_seconds=60):
            pc.record_failure("gemini_free", 500, "x")
            self.assertFalse(pc.allow("gemini_free"))
            # Tua thời gian mở mạch về quá khứ → allow() chuyển half_open.
            pc._states["gemini_free"].opened_at -= 61
            self.assertTrue(pc.allow("gemini_free"))   # 1 request thăm dò
            self.assertFalse(pc.allow("gemini_free"))  # request khác vẫn chặn
            pc.record_success("gemini_free")
            self.assertTrue(pc.allow("gemini_free"))   # đóng hẳn

    def test_half_open_probe_failure_reopens(self) -> None:
        pc = ProviderCircuit()
        with _sp(circuit_threshold=3, circuit_open_seconds=60):
            for _ in range(3):
                pc.record_failure("kiro", 500, "x")
            pc._states["kiro"].opened_at -= 61
            self.assertTrue(pc.allow("kiro"))  # half_open
            pc.record_failure("kiro", 500, "x")
            self.assertFalse(pc.allow("kiro"))  # mở lại ngay

    def test_disabled_smart_pool_allows_everything(self) -> None:
        pc = ProviderCircuit()
        with _sp(enabled=False, circuit_threshold=1):
            pc.record_failure("opencode", 500, "x")
            self.assertTrue(pc.allow("opencode"))

    def test_get_stats_reports_open_providers(self) -> None:
        pc = ProviderCircuit()
        with _sp(circuit_threshold=1):
            pc.record_failure("opencode", 500, "boom")
            stats = pc.get_stats()
        self.assertEqual(stats["open_count"], 1)
        self.assertIn("opencode", stats["providers"])


class MachTheoNhomViecTests(unittest.TestCase):
    """Đếm riêng theo từng nhóm việc (tên combo).

    Yêu cầu của chủ máy 06/08: ChatGPT Free hỏng phần đính kèm nhiều ảnh thì
    nhánh Phân tích ảnh phải xoay sang model khác, còn nhánh Chat vẫn giữ nó —
    "chat vẫn bình thường nhé". Đếm chung một bộ là ba lượt ảnh lỗi làm trợ lý
    nhà mất provider số 1 trong 60 giây dù chat chưa lỗi lần nào.
    """

    def test_loi_o_nhanh_anh_khong_chan_nhanh_chat(self) -> None:
        pc = ProviderCircuit()
        with _sp(circuit_threshold=3):
            for _ in range(3):
                pc.record_failure("chatgpt_free", 400, "too many attachments",
                                  nhom="AI vision")
            self.assertFalse(pc.allow("chatgpt_free", nhom="AI vision"))
            self.assertTrue(pc.allow("chatgpt_free", nhom="AI text"))

    def test_thanh_cong_nhanh_nay_khong_dong_mach_nhanh_kia(self) -> None:
        pc = ProviderCircuit()
        with _sp(circuit_threshold=1):
            pc.record_failure("cx", 500, "x", nhom="AI vision")
            pc.record_success("cx", nhom="AI text")
            self.assertFalse(pc.allow("cx", nhom="AI vision"))

    def test_khong_khai_nhom_thi_dem_chung_nhu_cu(self) -> None:
        """Bỏ trống `nhom` phải giữ y hành vi cũ — không có loại việc để tách."""
        pc = ProviderCircuit()
        with _sp(circuit_threshold=2):
            pc.record_failure("nv", 500, "x")
            pc.record_failure("nv", 500, "x")
            self.assertFalse(pc.allow("nv"))

    def test_nhom_khong_lam_ro_ri_sang_khoa_chung(self) -> None:
        """Mạch của một nhóm KHÔNG được chặn lối gọi không khai nhóm, và ngược
        lại: hai bộ đếm phải rời nhau hẳn, không phải một bộ có tiền tố."""
        pc = ProviderCircuit()
        with _sp(circuit_threshold=1):
            pc.record_failure("agnes", 500, "x", nhom="AI vision")
            self.assertTrue(pc.allow("agnes"))
            pc.record_failure("agnes", 500, "x")
            self.assertFalse(pc.allow("agnes"))
            # Nhóm khác vẫn sạch dù khoá chung đã mở.
            self.assertTrue(pc.allow("agnes", nhom="AI text"))

    def test_stats_noi_ro_nhom_viec_nao(self) -> None:
        pc = ProviderCircuit()
        with _sp(circuit_threshold=1):
            pc.record_failure("chatgpt_free", 500, "boom", nhom="AI vision")
            stats = pc.get_stats()
        muc = stats["providers"]["chatgpt_free@AI vision"]
        self.assertEqual(muc["provider"], "chatgpt_free")
        self.assertEqual(muc["nhom_viec"], "AI vision")


class DauNoiVaoComboTests(unittest.TestCase):
    """Chốt phần ĐẤU NỐI: combo phải truyền tên combo làm nhóm việc.

    Tách được ở `provider_circuit` mà chỗ gọi quên truyền `nhom` thì mọi bài
    trên đây vẫn xanh còn máy thật vẫn dính lỗi cũ — đây là kiểu hỏng đã xảy ra
    thật trong dự án này (một hàm đúng, cắm sai chỗ).
    """

    def _nguon(self) -> str:
        from pathlib import Path
        p = (Path(__file__).resolve().parent.parent
             / "services" / "protocol" / "openai_v1_chat_complete.py")
        return p.read_text(encoding="utf-8")

    def test_moi_loi_goi_circuit_deu_khai_nhom(self) -> None:
        import re
        src = self._nguon()
        goi = [m.group(0) for m in re.finditer(
            r"provider_circuit\.(?:allow|record_success|record_failure)\([^\n]*", src)]
        self.assertTrue(goi, "không tìm thấy lời gọi provider_circuit nào")
        thieu = [g for g in goi if "nhom=" not in g]
        self.assertEqual(thieu, [], f"lời gọi chưa khai nhóm việc: {thieu}")


if __name__ == "__main__":
    unittest.main()
