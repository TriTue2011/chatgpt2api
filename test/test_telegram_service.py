"""Unit tests for services.telegram (format / updates / rich / client helpers)."""

from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from services.telegram.format import (
    clip,
    escape_html,
    escape_markdown_v2,
    llm_to_html,
    llm_to_legacy_markdown,
    split_message,
)
from services.telegram.updates import (
    UpdateDedupe,
    detect_bot_mention,
    extract_message,
    is_duplicate_update,
    match_bot_by_secret,
    message_context,
    update_kind,
    webhook_secret_for,
)
from services.telegram.rich import (
    draft_stream_id,
    input_rich_message,
    markdown_to_blocks,
)
from services.telegram.auto_format import choose_format, strip_for_plain
from services.telegram.client import TelegramClient, _retry_after_seconds
from services.telegram.constants import MAX_MESSAGE_LENGTH


class TestFormat(unittest.TestCase):
    def test_legacy_bold(self):
        self.assertIn("*hello*", llm_to_legacy_markdown("**hello**"))

    def test_html_bold_and_escape(self):
        out = llm_to_html("**a <b>** and `x`")
        self.assertIn("<b>", out)
        self.assertIn("&lt;", out)  # angle brackets escaped once
        self.assertNotIn("&amp;lt;", out)
        self.assertIn("<code>x</code>", out)

    def test_escape_mdv2(self):
        s = escape_markdown_v2("a_b*c")
        self.assertIn(r"\_", s)
        self.assertIn(r"\*", s)

    def test_split_long(self):
        text = ("para one.\n\n" * 200) + ("x" * 500)
        chunks = split_message(text, prefer=800, limit=MAX_MESSAGE_LENGTH)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), MAX_MESSAGE_LENGTH)

    def test_clip(self):
        self.assertEqual(len(clip("a" * 100, 10)), 10)


class TestUpdates(unittest.TestCase):
    def test_webhook_secret_charset(self):
        s = webhook_secret_for("123:ABC-def")
        self.assertTrue(s.startswith("t"))
        self.assertTrue(all(c.isalnum() or c in "_-" for c in s))

    def test_match_bot(self):
        tok = "99:secret"
        bots = [{"token": tok, "enabled": True}, {"token": "1:x", "enabled": True}]
        sec = webhook_secret_for(tok)
        b = match_bot_by_secret(bots, sec)
        self.assertEqual(b["token"], tok)

    def test_match_single_lenient(self):
        bots = [{"token": "1:a", "enabled": True}]
        b = match_bot_by_secret(bots, "wrong")
        self.assertEqual(b["token"], "1:a")

    def test_dedupe(self):
        d = UpdateDedupe()
        self.assertFalse(d.is_duplicate("b1", 10))
        self.assertTrue(d.is_duplicate("b1", 10))
        self.assertFalse(d.is_duplicate("b1", 11))

    def test_update_kind_and_message(self):
        u = {"update_id": 1, "message": {"message_id": 2, "chat": {"id": 3, "type": "private"},
                                         "text": "hi", "from": {"id": 9, "first_name": "A"}}}
        self.assertEqual(update_kind(u), "message")
        m = extract_message(u)
        ctx = message_context(m)
        self.assertEqual(ctx["chat_id"], "3")
        self.assertEqual(ctx["text"], "hi")

    def test_detect_mention(self):
        msg = {
            "text": "hello @MyBot",
            "entities": [{"type": "mention", "offset": 6, "length": 6}],
            "from": {"id": 1},
            "chat": {"id": 2, "type": "group"},
        }
        self.assertTrue(detect_bot_mention(msg, bot_username="mybot", bot_id="99"))


class TestRich(unittest.TestCase):
    def test_markdown_blocks(self):
        md = "# Title\n\nHello **world**\n\n- a\n- b\n\n```py\nprint(1)\n```"
        blocks = markdown_to_blocks(md)
        types = [b.get("type") for b in blocks]
        self.assertIn("section_heading", types)
        self.assertIn("list", types)
        self.assertIn("preformatted", types)

    def test_input_rich_message(self):
        m = input_rich_message(markdown="**hi**")
        self.assertIn("blocks", m)
        self.assertTrue(draft_stream_id("c", 1) > 0)


class TestClient(unittest.TestCase):
    def test_retry_after(self):
        self.assertEqual(_retry_after_seconds({"parameters": {"retry_after": 3}}), 3.0)

    def test_call_empty_token(self):
        c = TelegramClient("")
        r = c.call("getMe")
        self.assertFalse(r.get("ok"))

    def test_call_json_ok(self):
        c = TelegramClient("1:tok")
        fake = MagicMock()
        fake.read.return_value = b'{"ok":true,"result":{"id":1}}'
        fake.__enter__ = lambda s: s
        fake.__exit__ = lambda *a: None
        with patch("urllib.request.urlopen", return_value=fake):
            r = c.call("getMe")
        self.assertTrue(r.get("ok"))

    def test_keyboard_builders(self):
        kb = TelegramClient.inline_keyboard([
            [TelegramClient.inline_button("A", callback_data="a")],
        ])
        self.assertIn("inline_keyboard", kb)
        rk = TelegramClient.reply_keyboard([["yes", "no"]])
        self.assertTrue(rk["resize_keyboard"])

    def test_send_message_auto_html_path(self):
        c = TelegramClient("1:tok")
        calls = []

        def fake_call(method, data=None, **kw):
            calls.append(method)
            return {"ok": True, "result": {"message_id": 1}}

        c.call = fake_call  # type: ignore
        r = c.send_message_auto(1, "Nhiệt độ **29°C**, ẩm **86%**.")
        self.assertTrue(r and r[-1].get("ok"))
        self.assertEqual(r[-1].get("_c2a_format"), "html")
        self.assertIn("sendMessage", calls)

    def test_send_message_auto_rich_fallback_html(self):
        c = TelegramClient("1:tok")

        def fake_call(method, data=None, **kw):
            if method == "sendRichMessage":
                return {"ok": False, "description": "not supported"}
            return {"ok": True, "result": {}}

        c.call = fake_call  # type: ignore
        long = "# A\n\n# B\n\n" + ("- item\n" * 8) + ("para " * 200)
        r = c.send_message_auto(1, long)
        self.assertEqual(r[-1].get("_c2a_format"), "html")


class TestEmphasis(unittest.TestCase):
    def test_bold_temp(self):
        from services.telegram.emphasis import emphasize_text
        out = emphasize_text(
            "Ngoài trời 29°C, ẩm 86%.",
            settings={"enabled": True, "numbers": True, "units": True, "key_info": False, "style": "bold"},
        )
        self.assertIn("**29°C**", out)
        self.assertIn("**86%**", out)

    def test_key_info(self):
        from services.telegram.emphasis import emphasize_text
        out = emphasize_text(
            "Nhiệt độ: 30\nTrạng thái: bật",
            settings={"enabled": True, "numbers": False, "units": False, "key_info": True, "style": "bold"},
        )
        self.assertIn("**30**", out)
        self.assertIn("**bật**", out)

    def test_per_admin_toggle(self):
        from services.telegram.emphasis import emphasize_text, resolve_emphasis_settings
        bot = {
            "emphasis_enabled": True,
            "emphasis_numbers": True,
            "emphasis_units": True,
            "emphasis_key_info": True,
            "admin_entries": [
                {"chat_id": "111", "emphasis_enabled": False},
                {"chat_id": "222", "emphasis_enabled": True},
            ],
        }
        st_off = resolve_emphasis_settings(bot=bot, chat_id="111")
        self.assertFalse(st_off["enabled"])
        st_on = resolve_emphasis_settings(bot=bot, chat_id="222")
        self.assertTrue(st_on["enabled"])
        raw = "29°C"
        self.assertEqual(emphasize_text(raw, bot=bot, chat_id="111"), raw)
        self.assertIn("**", emphasize_text(raw, bot=bot, chat_id="222"))

    def test_skip_when_disabled(self):
        from services.telegram.emphasis import emphasize_text
        raw = "Ngoài trời 29°C"
        self.assertEqual(
            emphasize_text(raw, settings={"enabled": False, "numbers": True, "units": True, "key_info": True, "style": "bold"}),
            raw,
        )

    def test_no_double_wrap(self):
        from services.telegram.emphasis import emphasize_text
        raw = "Ngoài trời **29°C**"
        out = emphasize_text(
            raw,
            settings={"enabled": True, "numbers": True, "units": True, "key_info": False, "style": "bold"},
        )
        self.assertEqual(out.count("**"), 2)


class TestAutoFormat(unittest.TestCase):
    def test_plain_short(self):
        c = choose_format("xin chào")
        self.assertEqual(c.mode, "plain")

    def test_html_bold(self):
        c = choose_format("Ngoài trời **29°C**, độ ẩm **86%**.")
        self.assertEqual(c.mode, "html")

    def test_rich_table(self):
        md = (
            "| Day | Temp |\n"
            "| --- | ---- |\n"
            "| Mon | 30   |\n"
            "| Tue | 28   |\n\n"
            "# Forecast\n\n"
            + ("detail line about weather " * 40)
        )
        c = choose_format(md)
        self.assertEqual(c.mode, "rich")

    def test_rich_multi_heading(self):
        md = "# One\n\n" + ("x" * 200) + "\n\n# Two\n\n" + ("y" * 200) + "\n\n- a\n- b\n- c\n- d\n- e\n"
        c = choose_format(md)
        self.assertEqual(c.mode, "rich")

    def test_strip_plain(self):
        self.assertEqual(strip_for_plain("**hi**"), "hi")


if __name__ == "__main__":
    unittest.main()
