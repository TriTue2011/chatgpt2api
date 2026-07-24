"""classify_notify_category — 3 nhóm thông báo admin."""
import unittest

from services.notifier import classify_notify_category


class ClassifyTests(unittest.TestCase):
    def test_explicit_categories(self) -> None:
        self.assertEqual(classify_notify_category("x", "account_log"), "account_log")
        self.assertEqual(classify_notify_category("x", "account_update"), "account_update")
        self.assertEqual(classify_notify_category("x", "system"), "system")
        self.assertEqual(classify_notify_category("x", "newchat"), "newchat")
        self.assertEqual(classify_notify_category("x", "provider"), "account_log")

    def test_provider_heuristic(self) -> None:
        self.assertEqual(
            classify_notify_category(
                "📋 Codex: Cập nhật tài khoản provider=codex, email=a@b.com",
            ),
            "account_update",
        )
        self.assertEqual(
            classify_notify_category(
                "📋 Codex: Thêm tài khoản provider=codex, email=a@b.com",
            ),
            "account_log",
        )
        self.assertEqual(
            classify_notify_category("✅ Claude — profile1\nKhôi phục xong"),
            "account_log",
        )

    def test_newchat_heuristic(self) -> None:
        self.assertEqual(
            classify_notify_category(
                "🆕 Nhóm mới → bot **x**\n• Chat ID: `123`\n• User ID người gửi: `9`",
            ),
            "newchat",
        )

    def test_system_errors(self) -> None:
        self.assertEqual(
            classify_notify_category("⚠️ chatgpt2api LỖI\n• Model: AI text"),
            "system",
        )
        self.assertEqual(
            classify_notify_category("🚫 Đã thêm blacklist Telegram"),
            "system",
        )


if __name__ == "__main__":
    unittest.main()
