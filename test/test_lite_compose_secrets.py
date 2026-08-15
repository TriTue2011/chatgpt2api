"""Lite Compose must never boot with example credentials."""
from __future__ import annotations

import unittest
from pathlib import Path


COMPOSE_LITE = (Path(__file__).resolve().parents[1] / "docker-compose.lite.yml").read_text(
    encoding="utf-8"
)


class LiteComposeSecretsTests(unittest.TestCase):
    def test_credential_bat_buoc_phai_fail_fast_khi_thieu(self):
        self.assertNotIn("CHATGPT2API_AUTH_KEY=sk-your-secret-key", COMPOSE_LITE)
        self.assertNotIn("CHATGPT_TOKEN_1=your_chatgpt_token_here", COMPOSE_LITE)
        self.assertIn("${CHATGPT2API_AUTH_KEY:?", COMPOSE_LITE)
        self.assertIn("${CHATGPT_TOKEN_1:?", COMPOSE_LITE)


if __name__ == "__main__":
    unittest.main()
