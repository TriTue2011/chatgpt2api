"""Tests for HA multi-signal rank + GMA stuck-limited revive."""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class HaIntentRankTests(unittest.TestCase):
    def test_rank_prefers_area_in_query(self) -> None:
        from services.ha_intent_rank import rank_candidates

        # Labels include area (as production does: friendly + area)
        cands = [
            ("den khach phong khach", ("light.khach", "light", "Đèn khách")),
            ("den ngu phong ngu", ("light.ngu", "light", "Đèn ngủ")),
        ]
        hit = rank_candidates("bat den phong ngu", cands, service="HassTurnOn")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.payload[0], "light.ngu")

    def test_margin_rejects_close_scores(self) -> None:
        from services.ha_intent_rank import rank_candidates

        # Nearly identical labels → low margin → None
        cands = [
            ("den a", ("light.a", "light", "A")),
            ("den a", ("light.b", "light", "A")),
        ]
        hit = rank_candidates("bat den a", cands, service="HassTurnOn", min_margin=0.5)
        # same label different payload with high margin requirement
        self.assertIsNone(hit)

    def test_opposing_services(self) -> None:
        from services.ha_intent_rank import services_are_opposing

        self.assertTrue(services_are_opposing("HassTurnOn", "HassTurnOff"))
        self.assertFalse(services_are_opposing("HassTurnOn", "HassTurnOn"))


class GmaQuotaDetectTests(unittest.TestCase):
    def test_fake_limit_resets_text_ignored(self) -> None:
        from api.gemini_web import _looks_like_real_gma_quota

        self.assertFalse(
            _looks_like_real_gma_quota(
                "Your limit will reset tomorrow. I can't draw that.",
                has_files=False,
            )
        )

    def test_real_limit_phrase(self) -> None:
        from api.gemini_web import _looks_like_real_gma_quota

        self.assertTrue(
            _looks_like_real_gma_quota(
                "You've reached your limit for today.",
                has_files=False,
            )
        )


class ReviveStuckLimitedTests(unittest.TestCase):
    def test_revive_old_gma_limited(self) -> None:
        from services.account_service import AccountService

        svc = AccountService.__new__(AccountService)
        svc._lock = __import__("threading").Lock()
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        svc._accounts = {
            "google-stuck": {
                "access_token": "google-stuck",
                "type": "gemini_web_api",
                "email": "google-stuck",
                "status": "limited",
                "quota": 0,
                "restore_at": None,
                "last_quota_exhausted_at": old,
                "last_used_at": None,
            }
        }
        with mock.patch.object(svc, "_save_accounts"), mock.patch.object(
            svc, "_normalize_account", side_effect=lambda x: x,
        ):
            revived = svc.revive_stuck_limited(max_age_hours=24.0)
        self.assertIn("google-stuck", revived)
        self.assertEqual(svc._accounts["google-stuck"]["status"], "active")


if __name__ == "__main__":
    unittest.main()
