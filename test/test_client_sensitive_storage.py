"""Long-lived credentials must not be cached in browser localStorage."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ROOT / "web/src/app/settings/components/codex-onboard-card.tsx",
    ROOT / "web/src/app/accounts/components/account-import-dialog.tsx",
)


class ClientSensitiveStorageTests(unittest.TestCase):
    def test_khong_cache_app_password_imap_tren_browser(self):
        for path in SOURCES:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn('localStorage.getItem("codex_gmail', source, path)
            self.assertNotIn('localStorage.setItem("codex_gmail', source, path)

    def test_van_co_nguon_dien_san_imap_tu_may_chu(self):
        """Bỏ localStorage mà không thay bằng gì thì mỗi lần nhập hàng loạt lại
        phải gõ tay app-password. Cả hai màn đọc chung khoá cấu hình máy chủ."""
        for path in SOURCES:
            source = path.read_text(encoding="utf-8")
            self.assertIn("codex_imap_gmail_email", source, path)
            self.assertIn("codex_imap_gmail_app_password", source, path)


if __name__ == "__main__":
    unittest.main()
