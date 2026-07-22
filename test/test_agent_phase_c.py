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

    def test_source_dest_and_ha_channel(self) -> None:
        rid = rj.log_run(
            user_id="ha_172.16.10.200",
            user_text='{"humans_detected":2}',
            reply_text='{"humans_detected":2,"humans_detected_summary":"1 phụ nữ, 1 bé trai"}',
            model="AI vision",
            hint="vision",
            status="ok",
            duration_ms=22000,
            source_kind="ha",
            source_account="Ben Bắp",
            source_peer="172.16.10.200",
            dest_provider="codex",
            dest_account="degaustgellert3920@outlook.com",
            dest_model="gpt-5.5",
            meta={"kind": "vision", "kind_label": "Phân tích ảnh", "groups": ["image"]},
        )
        self.assertTrue(rid)
        got = rj.get_run(rid)
        assert got is not None
        self.assertEqual(got["channel"], "ha")
        self.assertEqual(got["source_kind"], "ha")
        self.assertEqual(got["dest_provider"], "codex")
        self.assertEqual(got["hint"], "vision")
        self.assertEqual(got["meta"].get("kind"), "vision")
        self.assertIn("codex", got["to_label"])
        self.assertIn("ha", got["from_label"])
        rows = rj.list_runs(channel="ha", limit=5)
        self.assertTrue(any(r["id"] == rid for r in rows))
        st = rj.stats(24)
        self.assertIn("vision", st.get("by_kind") or {})

    def test_image_and_video_kinds(self) -> None:
        rid_img = rj.log_run(
            user_id="web_admin",
            user_text="a cat astronaut",
            reply_text="1 URL: https://example.com/cat.png",
            model="gpt-image-2",
            hint="image_gen",
            tools=["image_generations"],
            status="ok",
            duration_ms=4000,
            source_kind="web",
            meta={
                "kind": "image_gen",
                "kind_label": "Tạo ảnh",
                "groups": ["image"],
                "urls": ["https://example.com/cat.png"],
                "media_count": 1,
            },
        )
        rid_vid = rj.log_run(
            user_id="web_admin",
            user_text="ocean waves",
            reply_text="https://example.com/v.mp4",
            model="flow/veo-3.1-fast",
            hint="video_gen",
            tools=["video_generations"],
            status="ok",
            duration_ms=9000,
            source_kind="web",
            meta={
                "kind": "video_gen",
                "kind_label": "Tạo video",
                "groups": ["video"],
                "urls": ["https://example.com/v.mp4"],
            },
        )
        self.assertTrue(rid_img and rid_vid)
        rows = rj.list_runs(limit=10)
        kinds = {r["hint"] for r in rows}
        self.assertIn("image_gen", kinds)
        self.assertIn("video_gen", kinds)
        st = rj.stats(24)
        self.assertGreaterEqual(st.get("by_kind", {}).get("image_gen", 0), 1)
        self.assertGreaterEqual(st.get("by_kind", {}).get("video_gen", 0), 1)


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
