"""Nhận diện thread Zalo Cá Nhân — tên đúng user ID, admin = permitted."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services import zalo_personal as zp


class ExtractUserNameTests(unittest.TestCase):
    def test_prefers_zalo_name_over_local_display_name(self) -> None:
        """Live zca: displayName=biệt danh local, zaloName=tên Zalo thật."""
        info = {
            "changed_profiles": {
                "6643404425553198601": {
                    "userId": "6643404425553198601",
                    "displayName": "BotNhatoi",
                    "zaloName": "Nguyễn Việt",
                },
            }
        }
        name = zp._extract_user_name(
            info, "6643404425553198601", skip_ids={"475796162066271393"}
        )
        self.assertEqual(name, "Nguyễn Việt")

    def test_prefers_profile_matching_thread_id(self) -> None:
        info = {
            "changed_profiles": {
                "475796162066271393": {
                    "displayName": "Me",
                    "zaloName": "MeZalo",
                },
                "6643404425553198601": {
                    "displayName": "LocalNick",
                    "zaloName": "Nguyễn Việt",
                },
            }
        }
        name = zp._extract_user_name(
            info, "6643404425553198601", skip_ids={"475796162066271393"}
        )
        self.assertEqual(name, "Nguyễn Việt")

    def test_skips_own_account_when_only_other_is_target(self) -> None:
        info = {
            "changed_profiles": {
                "111": {"displayName": "MeBot"},
                "222": {"displayName": "Friend"},
            }
        }
        # When want_id matches Friend
        self.assertEqual(
            zp._extract_user_name(info, "222", skip_ids={"111"}),
            "Friend",
        )

    def test_does_not_return_own_name_as_fallback_from_map(self) -> None:
        """Nhiều profile, không khớp want_id → rỗng (không lấy BotNhatoi)."""
        info = {
            "changed_profiles": {
                "111": {"displayName": "BotNhatoi"},
                "999": {"displayName": "SomeoneElse"},
            }
        }
        self.assertEqual(
            zp._extract_user_name(info, "6643", skip_ids={"111"}),
            "",
        )

    def test_single_other_profile_ok(self) -> None:
        info = {
            "changed_profiles": {
                "111": {"displayName": "MeBot"},
                "222": {"displayName": "OnlyFriend"},
            }
        }
        # want missing from map — only one non-skip → OnlyFriend
        self.assertEqual(
            zp._extract_user_name(info, "000", skip_ids={"111"}),
            "OnlyFriend",
        )


class AdminThreadPermissionTests(unittest.TestCase):
    def test_admin_entries_grant_permission(self) -> None:
        fake = {
            "zalo_personal_account_admins": {
                "475796162066271393": {
                    "admin_thread": "6643404425553198601",
                    "admin_entries": [
                        {
                            "chat_id": "6643404425553198601",
                            "name": "Nguyễn Việt",
                            "kind": "private",
                        }
                    ],
                }
            },
            "zalo_personal_chat_ids": [],
        }
        with patch.object(zp, "_cfg", return_value=fake):
            self.assertTrue(
                zp._is_admin_thread("475796162066271393", "6643404425553198601")
            )
            self.assertFalse(
                zp._is_admin_thread("475796162066271393", "999")
            )
            ids = zp._admin_thread_ids_for_account("475796162066271393")
            self.assertIn("6643404425553198601", ids)


if __name__ == "__main__":
    unittest.main()
