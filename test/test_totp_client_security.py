"""Client TOTP must use only one-time codes from the server."""
from __future__ import annotations

import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "web/src/components/account-totp-display.tsx").read_text(
    encoding="utf-8"
)


class TotpClientSecurityTests(unittest.TestCase):
    def test_khong_dung_hat_giong_cu_de_sinh_ma_tai_browser(self):
        self.assertNotIn("generateTotpCode", SOURCE)
        self.assertNotIn("getTotpSecret(email)", SOURCE)

    def test_doi_tai_khoan_xoa_o_nhap_va_lay_ma_tu_server(self):
        self.assertIn("donHatGiongCu(email);", SOURCE)
        self.assertIn("setSecret(\"\");", SOURCE)
        self.assertIn("void refresh();", SOURCE)
        self.assertIn("window.setInterval(() => { void refresh(); }, 5000)", SOURCE)


if __name__ == "__main__":
    unittest.main()
