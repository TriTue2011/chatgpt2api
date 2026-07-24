"""Phase A (P0): tool_compress, approval_gate, super_context — unit tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import tool_compress as tc  # noqa: E402
from services.agent import approval_gate as gate  # noqa: E402
from services.agent import super_context as sc  # noqa: E402
from services.agent import state  # noqa: E402
from services.agent import wiki as w  # noqa: E402
from services.config import config  # noqa: E402


class ToolCompressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tc._reset_for_tests(Path(self._tmp.name) / "cache")
        self._cfg = mock.patch.dict(
            config.data,
            {"agent_tool_compress": {
                "enabled": True,
                "min_bytes": 100,
                "max_chars": 400,
                "disk_cache": True,
                "max_cache_entries": 32,
            }},
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        tc._reset_for_tests()
        self._tmp.cleanup()

    def test_small_passthrough(self) -> None:
        s = "hello short"
        self.assertEqual(tc.compress(s, tool_name="home_status"), s)

    def test_large_compresses_and_retrieves(self) -> None:
        lines = [f"line {i} normal content padding xxx" for i in range(80)]
        lines[40] = "ERROR device offline critical"
        raw = "\n".join(lines)
        out = tc.compress(raw, tool_name="home_status")
        self.assertLess(len(out), len(raw))
        self.assertIn("⟦tc:", out)
        self.assertIn("expand_tool_result", out)
        self.assertIn("ERROR", out)
        # extract token
        import re
        m = re.search(r"⟦tc:([0-9a-f]+)⟧", out)
        self.assertIsNotNone(m)
        full = tc.retrieve(m.group(1))
        self.assertEqual(full, raw)

    def test_maybe_compress_result(self) -> None:
        big = "x" * 5000
        r = tc.maybe_compress_result({"text": big, "image_url": "http://x"}, tool_name="web")
        self.assertIn("image_url", r)
        self.assertLess(len(r["text"]), len(big))


class ApprovalGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        agent_dir = Path(self._tmp.name)
        gate._reset_for_tests(agent_dir)
        # point state approvals into temp
        self._state_approvals = mock.patch.object(
            state, "_APPROVALS_FILE", agent_dir / "approvals.json",
        )
        self._state_pending = mock.patch.object(state, "_pending", {})
        self._state_approvals.start()
        self._state_pending.start()
        state.clear_pending("u1")
        self._cfg = mock.patch.dict(
            config.data,
            {"agent_approval": {
                "enabled": True,
                "level": "supervised",
                "persist_pending": True,
                "ttl_seconds": 600,
            }},
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        self._state_approvals.stop()
        self._state_pending.stop()
        gate._reset_for_tests()
        self._tmp.cleanup()

    def test_supervised_needs_approval(self) -> None:
        self.assertTrue(gate.needs_approval("u1", "control_home", risk="change"))
        self.assertFalse(gate.needs_approval("u1", "home_status", risk="read"))

    def test_always_grant_skips(self) -> None:
        state.grant_always("u1", "control_home")
        self.assertFalse(gate.needs_approval("u1", "control_home", risk="change"))

    def test_full_level_no_prompt(self) -> None:
        with mock.patch.dict(config.data, {"agent_approval": {
            "enabled": True, "level": "full",
        }}):
            # Tool "change" thường (không thuộc _ALWAYS_CONFIRM) → full = không hỏi.
            self.assertFalse(gate.needs_approval("u1", "control_home", risk="change"))
            # send_to_contact/create_automation LUÔN hỏi kể cả full (an toàn).
            self.assertTrue(gate.needs_approval("u1", "send_to_contact", risk="change"))

    def test_readonly_blocks(self) -> None:
        with mock.patch.dict(config.data, {"agent_approval": {
            "enabled": True, "level": "readonly",
        }}):
            self.assertTrue(gate.is_blocked("control_home", risk="change"))
            self.assertFalse(gate.needs_approval("u1", "control_home", risk="change"))

    def test_pending_persist_and_format(self) -> None:
        gate.set_pending("u1", "control_home", {"command": "bật đèn"}, "bật đèn")
        p = gate.get_pending("u1")
        self.assertIsNotNone(p)
        self.assertEqual(p["capability"], "control_home")
        q = gate.format_proposal(
            "control_home", {"command": "bật đèn"},
            label="Điều khiển nhà",
        )
        self.assertIn("<<<ASK>>>", q)
        self.assertIn("ok", q.lower())
        gate.resolve("u1", "once", capability="control_home")
        self.assertIsNone(gate.get_pending("u1"))

    def test_summarize_send(self) -> None:
        s = gate.summarize_action(
            "send_to_contact",
            {"to": "Anh A", "message": "xin chào"},
        )
        self.assertIn("Anh A", s)
        self.assertIn("xin chào", s)


class SuperContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        wiki_dir = Path(self._tmp.name) / "wiki"
        w._reset_for_tests(wiki_dir)
        (wiki_dir / "notes").mkdir(parents=True)
        (wiki_dir / "notes" / "den-phong-khach.md").write_text(
            "# Đèn phòng khách\n\nentity light.living_room\n",
            encoding="utf-8",
        )
        (wiki_dir / "index.md").write_text("# index\n", encoding="utf-8")
        self._cfg = mock.patch.dict(
            config.data,
            {
                "agent_super_context": {
                    "enabled": True,
                    "max_chars": 2000,
                    "wiki_hits": 4,
                    "memory_lines": 4,
                    "history_hits": 0,
                },
                "agent_wiki": {"enabled": True},
            },
        )
        self._cfg.start()
        self._mem = mock.patch.object(
            state, "load_memory",
            return_value="- [2026-01-01] Đèn phòng khách là light.living_room\n",
        )
        self._prof = mock.patch.object(state, "load_user_profile", return_value="Tên: Chủ nhà")
        self._mem.start()
        self._prof.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        self._mem.stop()
        self._prof.stop()
        w._reset_for_tests()
        self._tmp.cleanup()

    def test_first_turn_detection(self) -> None:
        self.assertTrue(sc.is_first_turn([]))
        self.assertTrue(sc.is_first_turn([{"role": "user", "content": "hi"}]))
        self.assertFalse(sc.is_first_turn([
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "chào"},
        ]))

    def test_build_bundle_has_wiki_and_memory(self) -> None:
        bundle = sc.build_bundle("u1", "đèn phòng khách thế nào")
        self.assertIn("super context", bundle.lower())
        self.assertTrue(
            "wiki" in bundle.lower() or "trí nhớ" in bundle.lower() or "hồ sơ" in bundle.lower()
        )

    def test_maybe_attach_only_first_turn(self) -> None:
        sys0 = "SOUL"
        hist_old = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        out = sc.maybe_attach(sys0, "u1", "đèn", hist_old)
        self.assertEqual(out, sys0)
        out2 = sc.maybe_attach(sys0, "u1", "đèn phòng khách", [])
        self.assertIn("Ngữ cảnh chuẩn bị", out2)


if __name__ == "__main__":
    unittest.main()
