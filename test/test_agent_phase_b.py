"""Phase B: wiki provenance/digest, goals, heartbeat — unit tests."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import wiki as w  # noqa: E402
from services.agent import goals as g  # noqa: E402
from services.agent import heartbeat as hb  # noqa: E402
from services.agent import capabilities as caps  # noqa: E402
from services.config import config  # noqa: E402


class WikiProvenanceDigestTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        w._reset_for_tests(root)
        self._cfg = mock.patch.dict(
            config.data,
            {"agent_wiki": {
                "enabled": True,
                "also_memory": False,
                "digest_enabled": True,
                "digest_hour": 0,
                "digest_llm": False,
            }},
        )
        self._cfg.start()
        self._sum = mock.patch.object(
            w, "_summarize",
            return_value={
                "title": "Đèn khách",
                "summary": "light.living_room",
                "tags": "nha, den",
                "memory_line": "",
            },
        )
        self._sum.start()

    def tearDown(self) -> None:
        self._sum.stop()
        self._cfg.stop()
        w._reset_for_tests()
        self._tmp.cleanup()

    def test_ingest_writes_frontmatter(self) -> None:
        out = w.ingest(
            "Ghi chú về đèn phòng khách entity light.living_room xx",
            who="tg_99",
            source="chat",
        )
        self.assertTrue(out["ok"])
        body = (Path(out["path"])).read_text(encoding="utf-8")
        self.assertTrue(body.startswith("---"))
        self.assertIn("content_hash:", body)
        self.assertIn("source: chat", body)
        self.assertIn("platform: tg", body)
        note = w.parse_note(Path(out["path"]))
        self.assertEqual(note["meta"].get("source"), "chat")
        self.assertTrue(len(str(note["meta"].get("content_hash") or "")) >= 8)

    def test_notes_for_day_and_digest(self) -> None:
        w.ingest("Nội dung đủ dài để thu nạp note một hai ba bốn", who="u1")
        day = w._now_vn().strftime("%Y-%m-%d")
        notes = w.notes_for_day(day)
        self.assertGreaterEqual(len(notes), 1)
        dig = w.build_daily_digest(day, force=True)
        self.assertTrue(dig["ok"])
        self.assertFalse(dig.get("skipped"))
        self.assertTrue(Path(dig["path"]).is_file())
        # second build without force skips rewrite
        dig2 = w.build_daily_digest(day, force=False)
        self.assertTrue(dig2.get("skipped"))
        self.assertTrue(w.digest_due_now() is False)  # file exists

    def test_wiki_digest_handler(self) -> None:
        w.ingest("Note test digest handler content long enough ok", who="u2")
        out = caps._h_wiki_digest({"op": "build", "force": True}, {"user_id": "u2"})
        self.assertIn("Digest", out["text"])


class GoalsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        db = Path(self._tmp.name) / "goals.sqlite"
        g._reset_for_tests(db)
        self._cfg = mock.patch.dict(
            config.data, {"agent_goals": {"enabled": True, "max_open": 5, "prompt_max": 3}},
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        g._reset_for_tests()
        self._tmp.cleanup()

    def test_add_list_done(self) -> None:
        row = g.add("u1", "Sửa đèn bếp", priority=2)
        self.assertEqual(row["status"], "open")
        rows = g.list_for("u1")
        self.assertEqual(len(rows), 1)
        g.set_status("u1", row["id"], "doing")
        g.set_status("u1", row["id"], "done")
        self.assertEqual(g.get("u1", row["id"])["status"], "done")

    def test_prompt_block(self) -> None:
        g.add("u1", "Goal A")
        g.add("u1", "Goal B", priority=5)
        block = g.prompt_block("u1")
        self.assertIn("Mục tiêu", block)
        self.assertIn("Goal", block)

    def test_handler_add_list(self) -> None:
        r = caps._h_goals({"op": "add", "title": "Mua sữa"}, {"user_id": "u9"})
        self.assertIn("Đã thêm", r["text"])
        r2 = caps._h_goals({"op": "list"}, {"user_id": "u9"})
        self.assertIn("Mua sữa", r2["text"])


class HeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        agent = Path(self._tmp.name)
        wiki = agent / "wiki"
        hb._reset_for_tests(agent)
        w._reset_for_tests(wiki)
        self._cfg = mock.patch.dict(
            config.data,
            {
                "agent_heartbeat": {
                    "enabled": True,
                    "tick_seconds": 60,
                    "admin_user_ids": [],
                    "max_acts_per_tick": 5,
                    "activity_log": True,
                },
                "agent_wiki": {
                    "enabled": True,
                    "also_memory": False,
                    "digest_enabled": True,
                    "digest_hour": 0,
                    "digest_llm": False,
                },
            },
        )
        self._cfg.start()
        self._sum = mock.patch.object(
            w, "_summarize",
            return_value={
                "title": "Note HB",
                "summary": "s",
                "tags": "t",
                "memory_line": "",
            },
        )
        self._sum.start()

    def tearDown(self) -> None:
        self._sum.stop()
        self._cfg.stop()
        hb._reset_for_tests()
        w._reset_for_tests()
        self._tmp.cleanup()

    def test_tick_writes_digest(self) -> None:
        w.ingest("Heartbeat note content is long enough here", who="u1")
        # ensure due
        self.assertTrue(w.digest_due_now())
        results = hb.tick_once()
        ids = {r["id"]: r for r in results}
        self.assertIn("wiki_daily_digest", ids)
        self.assertEqual(ids["wiki_daily_digest"]["decision"], "act")
        day = w._now_vn().strftime("%Y-%m-%d")
        self.assertTrue(w.digest_path(day).is_file())
        # second tick skips
        results2 = hb.tick_once()
        d2 = {r["id"]: r for r in results2}["wiki_daily_digest"]
        self.assertEqual(d2["decision"], "skip")

    def test_parse_user_tasks(self) -> None:
        (Path(self._tmp.name) / "HEARTBEAT.md").write_text(
            "# x\n[write] Gửi báo cáo\n[read] Check HA\n",
            encoding="utf-8",
        )
        tasks = hb._parse_tasks()
        texts = [t["text"] for t in tasks if not t.get("system")]
        self.assertTrue(any("báo cáo" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
