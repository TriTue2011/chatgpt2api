"""Unit tests for agent workflows + wiki lite (mocked LLM)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import workflows as wf  # noqa: E402
from services.agent import wiki as wiki  # noqa: E402
from services.agent import capabilities as caps  # noqa: E402
from services.config import config  # noqa: E402
from services.usage_tracker import get_usage_daily  # noqa: E402
import services.usage_tracker as ut  # noqa: E402


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        wf._reset_for_tests(root)
        wf._seeded = True
        self._cfg = mock.patch.dict(
            config.data, {"agent_workflows": {"enabled": True, "max_steps": 5}},
        )
        self._cfg.start()
        (root / "demo.md").write_text(
            "---\n"
            "name: Demo pipeline\n"
            "description: Hai bước demo\n"
            "verify: true\n"
            "---\n"
            "\n"
            "## Bước 1: Thu thập\n"
            "Input: {{input}}\n"
            "Liệt kê ý chính.\n"
            "\n"
            "## Bước 2: Viết\n"
            "Từ {{prev}} viết tóm tắt ngắn.\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._cfg.stop()
        wf._reset_for_tests()
        self._tmp.cleanup()

    def test_parse_and_list(self) -> None:
        items = wf.list_workflows()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].slug, "demo")
        self.assertEqual(len(items[0].steps), 2)
        self.assertTrue(items[0].verify)

    def test_run_with_verify(self) -> None:
        calls = {"n": 0}

        def fake_call(model, messages, **kwargs):
            calls["n"] += 1
            # steps 1,2 then verify PASS
            if calls["n"] <= 2:
                content = f"Kết quả bước {calls['n']}"
            else:
                content = "VERDICT: PASS\nNOTE: Đủ ý."
            return {"choices": [{"message": {"content": content}}]}

        with mock.patch.object(wf, "call_model", side_effect=fake_call):
            out = wf.run("demo", "Báo cáo nhà sáng nay")
        self.assertTrue(out["ok"])
        self.assertIn("Kết quả bước 2", out["result"])
        self.assertTrue(out.get("verified"))
        self.assertGreaterEqual(calls["n"], 3)

    def test_handler_list(self) -> None:
        out = caps._h_run_workflow({}, {"user_id": "u"})
        self.assertIn("demo", out["text"])


class WikiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        wiki._reset_for_tests(root)
        self._cfg = mock.patch.dict(
            config.data,
            {"agent_wiki": {"enabled": True, "also_memory": False}},
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        wiki._reset_for_tests()
        self._tmp.cleanup()

    def test_ingest_search_read(self) -> None:
        def fake_call(model, messages, **kwargs):
            return {
                "choices": [{
                    "message": {
                        "content": (
                            "TITLE: Lịch khám răng\n"
                            "TAGS: suc-khoe, gia-dinh\n"
                            "SUMMARY: Hẹn khám răng thứ Hai 9h.\n"
                            "MEMORY: Khám răng thứ Hai 9h\n"
                        )
                    }
                }]
            }

        with mock.patch.object(wiki, "call_model", side_effect=fake_call):
            out = wiki.ingest(
                "Nhớ giúp: khám răng thứ Hai tuần sau lúc 9 giờ sáng tại nha khoa ABC.",
                title="",
                who="u1",
            )
        self.assertTrue(out["ok"])
        slug = out["slug"]
        hits = wiki.search("khám răng")
        self.assertTrue(hits)
        body = wiki.read(slug)
        assert body is not None
        self.assertIn("Lịch khám", body)

    def test_search_empty_query_lists_recent_via_handler(self) -> None:
        # Write a note without LLM
        wiki._ensure()
        p = wiki._NOTES_DIR / "manual-note.md"
        p.write_text("# Manual\n\nNội dung test\n", encoding="utf-8")
        out = caps._h_wiki_search({}, {"user_id": "u"})
        self.assertIn("manual-note", out["text"])


class UsageDailyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._path = Path(self._tmp.name) / "usage_log.jsonl"
        self._old = ut.USAGE_LOG_PATH
        ut.USAGE_LOG_PATH = self._path

    def tearDown(self) -> None:
        ut.USAGE_LOG_PATH = self._old
        self._tmp.cleanup()

    def test_fills_zeros(self) -> None:
        data = get_usage_daily(7)
        self.assertEqual(data["days"], 7)
        self.assertEqual(len(data["series"]), 7)
        self.assertEqual(data["totals"]["requests"], 0)

    def test_counts_today(self) -> None:
        import json
        import time
        entry = {
            "ts": time.time(),
            "model": "cx/auto",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "status": "success",
        }
        self._path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        data = get_usage_daily(3)
        self.assertGreaterEqual(data["totals"]["requests"], 1)
        self.assertGreaterEqual(data["totals"]["tokens"], 150)
        self.assertEqual(data["series"][-1]["requests"], 1)


if __name__ == "__main__":
    unittest.main()
