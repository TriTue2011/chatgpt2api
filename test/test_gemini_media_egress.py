"""Gemini native must not fetch client-controlled media outside net_guard."""

from __future__ import annotations

import base64
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import net_guard  # noqa: E402
from services.providers.gemini_free import _convert_request  # noqa: E402


class GeminiMediaEgressTests(unittest.TestCase):
    def test_external_media_goes_through_guard_before_inline_upload(self) -> None:
        url = "https://cdn.example.test/photo.png"
        with mock.patch.object(net_guard, "fetch_media", return_value=b"png") as fetch:
            contents, _system, _tools = _convert_request([
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": url}},
                ]},
            ], None)
        fetch.assert_called_once_with(url, timeout=60, max_bytes=50 * 1024 * 1024)
        part = contents[0]["parts"][0]["inlineData"]
        self.assertEqual(part["data"], base64.b64encode(b"png").decode())
        self.assertEqual(part["mimeType"], "image/png")

    def test_blocked_media_is_not_sent_to_gemini(self) -> None:
        url = "http://127.0.0.1:8000/internal.png"
        with mock.patch.object(net_guard, "fetch_media", side_effect=net_guard.BlockedURL("blocked")):
            contents, _system, _tools = _convert_request([
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": url}},
                ]},
            ], None)
        self.assertEqual(contents[0]["parts"], [{"text": ""}])


if __name__ == "__main__":
    unittest.main()
