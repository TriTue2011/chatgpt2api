"""Unit tests for dead-account multi-tier recovery scheduler."""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import codex_error_recovery_scheduler as sch  # noqa: E402


class DeadRecoveryHelpers(unittest.TestCase):
    def test_is_recoverable_group_codex(self) -> None:
        with mock.patch(
            "services.account_service.account_group", return_value="codex",
        ):
            self.assertEqual(
                sch._is_recoverable_group({"type": "codex", "email": "a@b.com"}),
                "codex",
            )
        # JWT + refresh_token without group still counts as codex-ish
        with mock.patch(
            "services.account_service.account_group", return_value="",
        ):
            self.assertEqual(
                sch._is_recoverable_group({
                    "access_token": "eyJhbGciOiJSUzI1NiJ9.xx.yy",
                    "refresh_token": "rt.1",
                    "email": "x@y.com",
                }),
                "codex",
            )

    def test_list_dead_filters_status(self) -> None:
        fake = {
            "tok1": {"status": "error", "type": "codex", "email": "e@x.com",
                     "refresh_token": "rt"},
            "tok2": {"status": "active", "type": "codex", "email": "a@x.com"},
            "tok3": {"status": "disabled", "type": "codex", "email": "d@x.com"},
            "tok4": {"status": "error", "type": "other", "email": "o@x.com"},
        }
        with mock.patch("services.account_service.account_service") as svc:
            svc._lock = mock.MagicMock()
            svc._lock.__enter__ = mock.Mock(return_value=None)
            svc._lock.__exit__ = mock.Mock(return_value=False)
            svc._accounts = fake
            with mock.patch(
                "services.account_service.account_group",
                side_effect=lambda a: "codex" if "codex" in str(a.get("type")) else "other",
            ):
                dead = sch._list_dead_accounts()
        emails = {d.get("email") for d in dead}
        self.assertIn("e@x.com", emails)
        self.assertIn("d@x.com", emails)
        self.assertNotIn("a@x.com", emails)
        self.assertNotIn("o@x.com", emails)


if __name__ == "__main__":
    unittest.main()
