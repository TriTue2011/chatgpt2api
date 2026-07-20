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


if __name__ == "__main__":
    unittest.main()
