"""Write-back deduplication IDs need enough entropy for untrusted questions."""
from __future__ import annotations

import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "vn-mcp-hub/src/kb/writeback.py").read_text(
    encoding="utf-8"
)


class WritebackKeyStrengthTests(unittest.TestCase):
    def test_khong_dung_md5_cat_ngan_lam_khoa_dedup(self):
        self.assertNotIn("hashlib.md5", SOURCE)
        self.assertIn("hashlib.blake2s", SOURCE)
        self.assertIn("digest_size=16", SOURCE)


if __name__ == "__main__":
    unittest.main()
