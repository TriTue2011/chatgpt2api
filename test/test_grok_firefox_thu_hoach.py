"""Firefox Grok chỉ để lấy cookie. Không mở trình duyệt trong test."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")

import api.grok_firefox as gf  # noqa: E402


class DocCookieTests(unittest.TestCase):
    def test_bo_cf_chl_giu_clearance_va_sso(self):
        with tempfile.TemporaryDirectory() as thu:
            profile = Path(thu)
            db = profile / "cookies.sqlite"
            con = sqlite3.connect(db)
            con.execute(
                "CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT, lastAccessed INTEGER)"
            )
            con.executemany(
                "INSERT INTO moz_cookies VALUES (?,?,?,?)",
                [
                    (".grok.com", "sso", "phien", 2),
                    (".grok.com", "cf_clearance", "cua", 2),
                    (".grok.com", "cf_chl_rc_ni", "chan", 2),
                    (".grok.com", "sso", "cu", 1),
                ],
            )
            con.commit()
            con.close()
            ra = gf.doc_cookie_sqlite(profile)
        self.assertEqual(ra["sso"], "phien")
        self.assertEqual(ra["cf_clearance"], "cua")
        self.assertNotIn("cf_chl_rc_ni", ra)


class LamMoiTests(unittest.TestCase):
    def test_phien_con_song_thi_tat_firefox_khong_mo_lai(self):
        with mock.patch.object(gf, "doc_cookie_file", return_value={"sso": "a"}), \
                mock.patch.object(gf, "phien_song", return_value=True), \
                mock.patch.object(gf, "tat") as tat, \
                mock.patch.object(gf, "mo") as mo, \
                mock.patch.object(gf, "_chuyen_ho_so_tam"):
            ra = gf.lam_moi()
        self.assertEqual(ra["sso"], "a")
        tat.assert_called_once()
        mo.assert_not_called()
