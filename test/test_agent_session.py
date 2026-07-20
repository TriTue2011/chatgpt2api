"""Unit tests for agent session store + compaction (no live model)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import session as sess  # noqa: E402
from services.agent import compaction as compact  # noqa: E402
from services.config import config  # noqa: E402


class AgentSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db = Path(self._tmp.name) / "sessions.sqlite"
        sess._reset_for_tests(db)
        self._cfg = mock.patch.dict(
            config.data,
            {"agent_session": {
                "enabled": True,
                "max_history": 6,
                "max_stored": 50,
                "compact_after": 8,
                "keep_tail": 4,
            }},
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        sess._reset_for_tests()
        self._tmp.cleanup()

    def test_save_and_load_history(self) -> None:
        msgs = [
            {"role": "user", "content": "xin chào"},
            {"role": "assistant", "content": "dạ chào anh"},
            {"role": "user", "content": "thời tiết thế nào"},
            {"role": "assistant", "content": "hôm nay nắng"},
        ]
        sess.save_history("tg_1", msgs)
        loaded = sess.load_history("tg_1")
        self.assertEqual(len(loaded), 4)
        self.assertEqual(loaded[0]["content"], "xin chào")
        self.assertEqual(loaded[-1]["content"], "hôm nay nắng")

    def test_load_respects_max_history_tail(self) -> None:
        msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
                for i in range(20)]
        sess.save_history("u2", msgs)
        loaded = sess.load_history("u2")
        self.assertEqual(len(loaded), 6)  # max_history
        self.assertEqual(loaded[-1]["content"], "m19")

    def test_summary_roundtrip(self) -> None:
        sess.set_summary("u3", "Đã nói về đèn phòng khách.")
        self.assertIn("đèn", sess.load_summary("u3"))

    def test_append_and_search(self) -> None:
        sess.append_turn("u4", "user", "Nhớ giúp em đặt hẹn khám răng thứ Hai")
        sess.append_turn("u4", "assistant", "Dạ em nhớ lịch khám răng ạ")
        sess.append_turn("u4", "user", "thời tiết Hà Nội")
        hits = sess.search("u4", "khám răng")
        self.assertTrue(hits)
        self.assertTrue(any("khám" in h["content"] for h in hits))

    def test_clear_history(self) -> None:
        sess.save_history("u5", [{"role": "user", "content": "hi"}])
        sess.set_summary("u5", "old")
        sess.clear_history("u5")
        self.assertEqual(sess.load_history("u5"), [])
        self.assertEqual(sess.load_summary("u5"), "")

    def test_maybe_compact_short_circuits(self) -> None:
        short = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        self.assertIsNone(compact.maybe_compact("u6", short))

    def test_maybe_compact_runs_and_keeps_tail(self) -> None:
        long = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn-{i} special-{i}"}
            for i in range(12)
        ]
        with mock.patch.object(compact, "summarize", return_value="- Đã nói 12 lượt chat."):
            out = compact.maybe_compact("u7", long)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(len(out), 4)  # keep_tail
        self.assertEqual(out[-1]["content"], "turn-11 special-11")
        self.assertIn("12 lượt", sess.load_summary("u7"))
        # Active history on disk is the tail
        self.assertEqual(len(sess.load_history("u7")), 4)


if __name__ == "__main__":
    unittest.main()
