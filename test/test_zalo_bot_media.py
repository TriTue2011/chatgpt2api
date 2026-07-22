"""Zalo Bot media surface: sendPhoto + sendVoice only (no file send)."""
from __future__ import annotations

import unittest
from unittest import mock

from services import zalo_bot as zb


class ZaloBotMediaTests(unittest.TestCase):
    def test_send_photo_payload(self) -> None:
        with mock.patch.object(zb, "_api_call", return_value={"ok": True}) as api, \
             mock.patch.object(zb, "_ensure_public_photo_url", return_value="https://example.com/a.png"):
            r = zb.send_photo("chat1", "https://example.com/a.png", caption="hi")
            self.assertTrue(r.get("ok"))
            api.assert_called_once()
            method, data = api.call_args[0][0], api.call_args[0][1]
            self.assertEqual(method, "sendPhoto")
            self.assertEqual(data["chat_id"], "chat1")
            self.assertEqual(data["photo"], "https://example.com/a.png")
            self.assertEqual(data["caption"], "hi")

    def test_send_photo_rejects_no_public_url(self) -> None:
        with mock.patch.object(zb, "_ensure_public_photo_url", return_value=None), \
             mock.patch.object(zb, "_api_call") as api:
            r = zb.send_photo("c", "/images/x.png")
            self.assertFalse(r.get("ok"))
            api.assert_not_called()

    def test_send_voice_payload(self) -> None:
        with mock.patch.object(zb, "_api_call", return_value={"ok": True}) as api:
            r = zb.send_voice("u1", "https://example.com/v.aac")
            self.assertTrue(r.get("ok"))
            method, data = api.call_args[0][0], api.call_args[0][1]
            self.assertEqual(method, "sendVoice")
            self.assertEqual(data["chat_id"], "u1")
            self.assertEqual(data["voice_url"], "https://example.com/v.aac")

    def test_no_docx_helper(self) -> None:
        self.assertFalse(hasattr(zb, "_serve_docx_link"))

    def test_pdf_word_intent_no_file_send(self) -> None:
        pending = {"path": "/tmp/x.pdf", "name": "x.pdf"}
        with mock.patch.object(zb, "send_message") as sm, \
             mock.patch.object(zb, "_api_call", return_value={"ok": True}), \
             mock.patch("os.unlink"):
            zb._do_pdf_intent("c1", pending, "word")
            sm.assert_called()
            msg = sm.call_args[0][1]
            self.assertIn("không gửi file", msg.lower())
            self.assertNotIn("http", msg.lower())

    def test_extract_voice_url(self) -> None:
        self.assertEqual(zb._extract_voice_url({"voice_url": "https://x/a.aac"}), "https://x/a.aac")
        self.assertEqual(
            zb._extract_voice_url({"voice": {"url": "https://x/b.aac"}}),
            "https://x/b.aac",
        )


if __name__ == "__main__":
    unittest.main()
