"""Admin workspace: multi-admin independent bot names + save pending."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import admin_workspace as aw  # noqa: E402
from services.config import config  # noqa: E402


class AdminWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        aw._reset_for_tests(Path(self._tmp.name) / "ws.json")
        self._cfg = mock.patch.dict(
            config.data,
            {
                "telegram_bots": [
                    {
                        "token": "111:A",
                        "label": "SysLabel",
                        "admin_threads": ["9001", "9002"],
                        "enabled": True,
                        "chat_ids": [],
                        "admin_thread": "9001",
                        "admin_thread_type": "0",
                        "ha_fastpath": True,
                        "ai_model": "",
                    },
                    {
                        "token": "222:B",
                        "label": "",
                        "admin_threads": ["9001"],
                        "enabled": True,
                        "chat_ids": [],
                        "admin_thread": "",
                        "admin_thread_type": "0",
                        "ha_fastpath": True,
                        "ai_model": "",
                    },
                ],
            },
        )
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        aw._reset_for_tests()
        self._tmp.cleanup()

    def test_multi_admins_on_bot(self) -> None:
        bot = config.data["telegram_bots"][0]
        ids = aw.admin_thread_ids(bot)
        self.assertEqual(ids, ["9001", "9002"])

    def test_bot_name_per_admin_independent(self) -> None:
        aw.set_bot_name("tg", "9001", "111", "Bot Nha Admin1")
        aw.set_bot_name("tg", "9002", "111", "Bot Shop Admin2")
        self.assertEqual(aw.bot_display_name("tg", "111", "9001"), "Bot Nha Admin1")
        self.assertEqual(aw.bot_display_name("tg", "111", "9002"), "Bot Shop Admin2")

    def test_handle_list_and_set_bot_name(self) -> None:
        r = aw.handle_admin_text("tg", "9001", "liệt kê bot")
        self.assertIsNotNone(r)
        assert r is not None
        self.assertIn("111", r)
        r2 = aw.handle_admin_text("tg", "9001", "đặt tên bot 111 = Nha Toi")
        self.assertIn("Nha Toi", r2 or "")
        self.assertEqual(aw.bot_display_name("tg", "111", "9001"), "Nha Toi")

    def test_save_contact_flow(self) -> None:
        contact = {
            "key": "tg:111:555",
            "bot_id": "111",
            "chat_id": "555",
            "user_id": "u1",
            "display_name": "Nguyen Van A",
            "kind": "user",
        }
        prompt = aw.start_save_prompt("tg", "9001", contact)
        self.assertIn("Lưu", prompt)
        # yes → show platform name in option 1
        r1 = aw.handle_admin_text("tg", "9001", "có")
        self.assertIn("Nguyen Van A", r1 or "")
        # pick 1 = platform person name
        r2 = aw.handle_admin_text("tg", "9001", "1")
        self.assertIn("Nguyen Van A", r2 or "")
        ws = aw.get_ws("tg", "9001")
        self.assertEqual(ws["contact_aliases"].get("tg:111:555"), "Nguyen Van A")
        # other admin independent
        ws2 = aw.get_ws("tg", "9002")
        self.assertNotIn("tg:111:555", ws2.get("contact_aliases") or {})

    def test_save_group_name_option(self) -> None:
        contact = {
            "key": "tg:111:-10099",
            "bot_id": "111",
            "chat_id": "-10099",
            "user_id": "u9",
            "display_name": "Member X",
            "chat_name": "Gia dinh Nha",
            "kind": "group",
        }
        aw.start_save_prompt("tg", "9001", contact)
        r1 = aw.handle_admin_text("tg", "9001", "có")
        self.assertIn("Member X", r1 or "")
        self.assertIn("Gia dinh Nha", r1 or "")
        self.assertIn("nhóm", (r1 or "").lower())
        r2 = aw.handle_admin_text("tg", "9001", "2")
        self.assertIn("Gia dinh Nha", r2 or "")
        ws = aw.get_ws("tg", "9001")
        self.assertEqual(ws["contact_aliases"].get("tg:111:-10099"), "Gia dinh Nha")


if __name__ == "__main__":
    unittest.main()
