"""Privacy gate P0–P2 tests."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class PrivacyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        from services.privacy_gate import vault
        vault().clear_session("t1")
        vault().clear_session("default")
        vault().clear_session("log")

    def test_password_labeled_redacted(self) -> None:
        from services.privacy_gate import redact_text, resolve_secret_ref, vault

        raw = "đăng nhập user A mk: SuperSecret99!"
        out = redact_text(raw, session_id="t1")
        self.assertNotIn("SuperSecret99!", out)
        self.assertIn("⟦", out)
        # extract ref
        import re
        m = re.search(r"⟦[^⟧]+⟧", out)
        self.assertIsNotNone(m)
        resolved = resolve_secret_ref(m.group(0), session_id="t1")
        self.assertEqual(resolved, "SuperSecret99!")

    def test_jwt_and_sk_redacted(self) -> None:
        from services.privacy_gate import redact_text

        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        sk = "sk-abcdefghijklmnopqrstuvwxyz0123456789"
        out = redact_text(f"token {jwt} key {sk}", session_id="t1")
        self.assertNotIn(jwt, out)
        self.assertNotIn(sk, out)

    def test_email_phone_pii(self) -> None:
        from services.privacy_gate import redact_text

        out = redact_text(
            "liên hệ a.b@example.com hoặc 0912345678",
            session_id="t1",
        )
        self.assertNotIn("a.b@example.com", out)
        self.assertNotIn("0912345678", out)

    def test_apply_to_body(self) -> None:
        from services.privacy_gate import apply_to_body

        body = {
            "user": "u1",
            "messages": [
                {"role": "user", "content": "password: MyPass1234"},
            ],
        }
        out = apply_to_body(body)
        content = out["messages"][0]["content"]
        self.assertNotIn("MyPass1234", content)
        self.assertEqual(out.get("_privacy_session"), "u1")

    def test_scrub_for_log(self) -> None:
        from services.privacy_gate import scrub_for_log

        s = scrub_for_log("user said password: leakme99")
        self.assertNotIn("leakme99", s)

    def test_resolve_in_tool_args(self) -> None:
        from services.privacy_gate import redact_text, resolve_secret_ref

        red = redact_text("mk: Abcdef12", session_id="tool")
        # full string may have prefix "mk: ⟦...⟧"
        import re
        ref = re.search(r"⟦[^⟧]+⟧", red).group(0)
        self.assertEqual(resolve_secret_ref(ref, session_id="tool"), "Abcdef12")


if __name__ == "__main__":
    unittest.main()
