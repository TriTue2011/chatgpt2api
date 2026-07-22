"""HA vision JSON must not be mangled by markdown strip."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.protocol.openai_v1_chat_complete import (  # noqa: E402
    _looks_like_json_payload,
    _strip_markdown_inline,
)


class HaJsonStripTests(unittest.TestCase):
    def test_json_preserved(self) -> None:
        j = (
            '{"humans_detected":1,"humans_detected_summary":"1 bé trai",'
            '"humans_detected_description":"đi vào phòng"}'
        )
        self.assertTrue(_looks_like_json_payload(j))
        out = _strip_markdown_inline(j)
        self.assertEqual(out.count("_"), j.count("_"))
        self.assertIn("humans_detected", out)
        self.assertIn('"humans_detected":1', out)

    def test_bold_still_stripped(self) -> None:
        self.assertEqual(_strip_markdown_inline("**tắt đèn**"), "tắt đèn")

    def test_fenced_json(self) -> None:
        j = '```json\n{"humans_detected":0,"humans_detected_summary":""}\n```'
        self.assertTrue(_looks_like_json_payload(j))


if __name__ == "__main__":
    unittest.main()
