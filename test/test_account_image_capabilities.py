from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.account_service import AccountService
from services.storage.json_storage import JSONStorageBackend
from utils.helper import anonymize_token


class AccountCapabilityTests(unittest.TestCase):
    def test_unknown_quota_accounts_are_available_only_when_not_throttled(self) -> None:
        # Nhãn trạng thái đã chuyển hẳn sang tiếng Anh — xem `_STATUS_MIGRATION`
        # trong account_service. Mọi dòng trong pool đều đi qua
        # `_normalize_account` nên tới đây không còn nhãn tiếng Trung nào.
        self.assertFalse(
            AccountService._is_image_account_available(
                {"status": "limited", "image_quota_unknown": True, "quota": 0}
            )
        )
        self.assertTrue(
            AccountService._is_image_account_available(
                {"status": "active", "image_quota_unknown": True, "quota": 0}
            )
        )

    def test_mark_image_result_does_not_consume_unknown_quota(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            service = AccountService(JSONStorageBackend(Path(tmp_dir) / "accounts.json"))
            service.add_accounts(["token-1"])
            service.update_account(
                "token-1",
                {
                    "status": "active",
                    "quota": 0,
                    "image_quota_unknown": True,
                },
            )

            updated = service.mark_image_result("token-1", success=True)

            self.assertIsNotNone(updated)
            self.assertEqual(updated["quota"], 0)
            self.assertEqual(updated["status"], "active")
            self.assertTrue(updated["image_quota_unknown"])


class TokenLogTests(unittest.TestCase):
    def test_anonymize_token_hides_raw_value(self) -> None:
        token = "super-secret-token"
        token_ref = anonymize_token(token)

        self.assertTrue(token_ref.startswith("token:"))
        self.assertNotIn(token, token_ref)


# AuthServiceTests đã TÁCH sang test/test_auth_service.py (giữ file này thuần
# về account/image capabilities).


if __name__ == "__main__":
    unittest.main()
