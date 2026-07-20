"""Tests for multi-bot channel contacts + alert-once rules."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import channel_contacts as cc  # noqa: E402
from services.config import config  # noqa: E402


class ChannelContactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "contacts.json"
        cc._reset_for_tests(path)
        self._cfg = mock.patch.dict(
            config.data,
            {
                "telegram_bots": [{
                    "token": "111:AAA",
                    "chat_ids": ["999"],
                    "label": "Bot Nha",
                    "enabled": True,
                    "ha_fastpath": True,
                    "admin_thread": "",
                    "admin_thread_type": "0",
                    "ai_model": "",
                }],
                "thread_filters": {},
            },
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        cc._reset_for_tests()
        self._tmp.cleanup()

    def test_bot_label_from_config(self) -> None:
        self.assertEqual(cc.bot_label("tg", "111"), "Bot Nha")

    def test_stranger_alerts_once(self) -> None:
        ok1, rec = cc.should_alert_new(
            "tg", "111", "555", user_id="u1", display_name="La", text="hi",
        )
        self.assertTrue(ok1)
        self.assertFalse(rec.get("known"))
        cc.mark_notified(rec["key"])
        ok2, _ = cc.should_alert_new(
            "tg", "111", "555", user_id="u1", display_name="La", text="hi again",
        )
        self.assertFalse(ok2)

    def test_configured_chat_no_alert(self) -> None:
        # chat_id 999 is in bot chat_ids
        ok, rec = cc.should_alert_new(
            "tg", "111", "999", user_id="u9", display_name="Known", text="yo",
        )
        self.assertFalse(ok)
        self.assertTrue(rec.get("known"))

    def test_alias_makes_known(self) -> None:
        _, rec = cc.should_alert_new(
            "tg", "111", "777", user_id="u7", display_name="X", text="a",
        )
        cc.set_alias(rec["key"], "Anh A")
        ok, rec2 = cc.should_alert_new(
            "tg", "111", "777", user_id="u7", display_name="X", text="b",
        )
        self.assertFalse(ok)
        self.assertEqual(rec2.get("alias"), "Anh A")
        self.assertTrue(rec2.get("known"))

    def test_group_tag_required_blocks_alert(self) -> None:
        with mock.patch(
            "services.agent.capabilities.mention_required_for",
            return_value=(True, "@bot"),
        ):
            ok, _ = cc.should_alert_new(
                "tg", "111", "g1", is_group=True, tagged=False, text="hello",
            )
            self.assertFalse(ok)
            ok2, _ = cc.should_alert_new(
                "tg", "111", "g1", is_group=True, tagged=True, text="@bot hi",
            )
            # second call: already notified? first was false so not notified
            # tagged True should allow alert if not yet notified
            self.assertTrue(ok2)

    def test_resolve_alias(self) -> None:
        _, rec = cc.should_alert_new("tg", "111", "888", display_name="Z", text="z")
        cc.set_alias(rec["key"], "Chi B")
        hits = cc.resolve_alias("Chi B", platform="tg")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["chat_id"], "888")

    def test_parse_admin_rename(self) -> None:
        self.assertEqual(
            cc.parse_admin_rename("đặt tên 888 = Anh C"),
            ("888", "Anh C"),
        )


if __name__ == "__main__":
    unittest.main()
