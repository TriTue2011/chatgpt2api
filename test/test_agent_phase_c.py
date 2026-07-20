"""Phase C: model hints, run journal, email allowlist, calendar ICS parse."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import model_hints as mh  # noqa: E402
from services.agent import run_journal as rj  # noqa: E402
from services import email_channel as ec  # noqa: E402
from services import calendar_connector as cal  # noqa: E402
from services.config import config  # noqa: E402


class ModelHintsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._cfg = mock.patch.dict(
            config.data,
            {
                "telegram_ai_model": "cx/main",
                "agent_model_hints": {
                    "enabled": True,
                    "chat": "cx/chat",
                    "burst": "gma/flash",
                    "reason": "claude/sonnet",
                },
                "agent_branches": {"code": "claude/code", "vision": "gma/vision"},
            },
            clear=False,
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()

    def test_resolve_hints(self) -> None:
        self.assertEqual(mh.resolve("burst"), "gma/flash")
        self.assertEqual(mh.resolve("reason"), "claude/sonnet")
        self.assertEqual(mh.resolve("chat"), "cx/chat")
        self.assertEqual(mh.resolve("code"), "claude/code")
        self.assertEqual(mh.resolve("unknown"), "cx/chat")

    def test_disabled_falls_to_main(self) -> None:
        with mock.patch.dict(config.data, {"agent_model_hints": {"enabled": False}}):
            self.assertEqual(mh.resolve("burst"), "cx/main")


class RunJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        rj._reset_for_tests(Path(self._tmp.name) / "runs.sqlite")
        self._cfg = mock.patch.dict(
            config.data, {"agent_run_journal": {"enabled": True, "max_rows": 50}},
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        rj._reset_for_tests()
        self._tmp.cleanup()

    def test_log_and_list(self) -> None:
        rid = rj.log_run(
            user_id="tg_1",
            user_text="bật đèn",
            reply_text="Đã bật",
            model="cx/auto",
            hint="reason",
            tools=["control_home"],
            steps=1,
            duration_ms=120,
            status="ok",
        )
        self.assertTrue(rid)
        rows = rj.list_runs(limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel"], "tg")
        self.assertEqual(rows[0]["tools"], ["control_home"])
        st = rj.stats(24)
        self.assertEqual(st["total"], 1)
        got = rj.get_run(rid)
        self.assertIsNotNone(got)
        self.assertEqual(got["user_text"], "bật đèn")


class EmailAllowTests(unittest.TestCase):
    def test_fail_closed_and_star(self) -> None:
        with mock.patch.dict(config.data, {"email_channel": {
            "enabled": True, "user": "a@b.com", "allowed_senders": [],
        }}):
            self.assertFalse(ec._allowed("x@y.com"))
        with mock.patch.dict(config.data, {"email_channel": {
            "enabled": True, "user": "a@b.com", "allowed_senders": ["*"],
        }}):
            self.assertTrue(ec._allowed("x@y.com"))
        with mock.patch.dict(config.data, {"email_channel": {
            "enabled": True, "user": "a@b.com",
            "allowed_senders": ["friend@gmail.com", "@family.com"],
        }}):
            self.assertTrue(ec._allowed("friend@gmail.com"))
            self.assertTrue(ec._allowed("a@family.com"))
            self.assertFalse(ec._allowed("stranger@evil.com"))

    def test_user_id_stable(self) -> None:
        a = ec._user_id_for("Me@Example.com")
        b = ec._user_id_for("me@example.com")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("email_"))


class ThreadFilterCoreToolsTests(unittest.TestCase):
    """wiki_digest/goals/expand phải có group; expand luôn trong schema khi filter."""

    def test_group_map(self) -> None:
        from services.agent import capabilities as caps
        self.assertEqual(caps.group_of("wiki_digest"), "wiki")
        self.assertEqual(caps.group_of("goals"), "memory")
        self.assertIn("expand_tool_result", caps._CORE_TOOLS)

    def test_schema_keeps_core_when_filtered(self) -> None:
        from services.agent import capabilities as caps
        # Thread chỉ wiki — không memory
        names = {s["function"]["name"] for s in caps.tools_schema({"wiki"})}
        self.assertIn("wiki_digest", names)
        self.assertIn("wiki_search", names)
        self.assertNotIn("goals", names)  # memory group
        self.assertIn("expand_tool_result", names)  # core always

    def test_schema_goals_with_memory(self) -> None:
        from services.agent import capabilities as caps
        names = {s["function"]["name"] for s in caps.tools_schema({"memory"})}
        self.assertIn("goals", names)
        self.assertIn("expand_tool_result", names)
        self.assertNotIn("wiki_digest", names)


class CalendarParseTests(unittest.TestCase):
    def test_parse_vevent(self) -> None:
        ics = (
            "BEGIN:VCALENDAR\n"
            "BEGIN:VEVENT\n"
            "DTSTART:20300101T100000\n"
            "DTEND:20300101T110000\n"
            "SUMMARY:Họp gia đình\n"
            "LOCATION:Nhà\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )
        events = cal._parse_events(ics)
        self.assertEqual(len(events), 1)
        self.assertIn("Họp", events[0]["summary"])
        text = cal.format_events(events)
        self.assertIn("Lịch", text)


if __name__ == "__main__":
    unittest.main()
