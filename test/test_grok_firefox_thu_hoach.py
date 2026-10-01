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


class _CauHinh:
    """providers.grok_web trong bộ nhớ + DATA_DIR tạm — không đụng cấu hình thật."""

    def __init__(self, thu: str, cfg: dict | None = None):
        self.cfg = dict(cfg or {})
        self.thu = Path(thu)
        self.vas = [
            mock.patch.object(gf, "_cfg", side_effect=lambda: self.cfg),
            mock.patch.object(gf, "_luu_cfg", side_effect=self._luu),
            mock.patch.object(gf, "_data", return_value=self.thu),
            mock.patch.object(gf, "_pid_mo", return_value=None),
        ]

    def _luu(self, c):
        self.cfg = c

    def __enter__(self):
        for v in self.vas:
            v.start()
        return self

    def __exit__(self, *a):
        for v in self.vas:
            v.stop()


class TaiKhoanTests(unittest.TestCase):
    """Chủ máy 01/10/2026: Grok phải như các provider khác — danh sách tài khoản có thứ tự, thêm/bật/xoá."""

    def test_ho_so_cu_thanh_tai_khoan_dau(self):
        with tempfile.TemporaryDirectory() as thu, _CauHinh(thu) as ch, \
                mock.patch.object(gf, "thong_tin_phien", return_value={"email": "a@b.c"}):
            cu = Path(thu) / "grok_firefox"
            cu.mkdir()
            (cu / "cookies.sqlite").write_bytes(b"x")
            (Path(thu) / "grok_web_cookies.json").write_text('{"sso": "s"}')
            ds = gf.tai_khoan()
            self.assertEqual([(a["profile"], a["label"], a["email"]) for a in ds], [("grok-1", "Main", "a@b.c")])
            self.assertTrue((Path(thu) / "grok_ho_so" / "grok-1" / "cookies.sqlite").is_file())
            self.assertEqual(gf.doc_cookie_file("grok-1"), {"sso": "s"})
            self.assertFalse(cu.exists())
            self.assertTrue(ch.cfg["enabled"])

    def test_them_bat_tat_thu_tu_xoa(self):
        with tempfile.TemporaryDirectory() as thu, _CauHinh(thu) as ch:
            a, b = gf.them(), gf.them("Phụ")
            self.assertEqual((a["profile"], a["label"], b["profile"], b["label"]), ("grok-1", "Main", "grok-2", "Phụ"))
            gf.bat_tat("grok-1", False)
            self.assertEqual([x["profile"] for x in gf.dang_bat()], ["grok-2"])
            gf.doi_thu_tu(["grok-2", "grok-1"])
            self.assertEqual([x["profile"] for x in gf.tai_khoan()], ["grok-2", "grok-1"])
            with self.assertRaises(ValueError):
                gf.doi_thu_tu(["grok-2"])
            gf.ho_so("grok-2").mkdir(parents=True)
            gf.xoa("grok-2")
            self.assertEqual([x["profile"] for x in ch.cfg["accounts"]], ["grok-1"])
            self.assertFalse(gf.ho_so("grok-2").exists())
            with self.assertRaises(ValueError):
                gf.xoa("../grok-1")


class LamMoiTests(unittest.TestCase):
    def test_phien_con_song_thi_tat_firefox_khong_mo_lai(self):
        with mock.patch.object(gf, "doc_cookie_file", return_value={"sso": "a"}), \
                mock.patch.object(gf, "phien_song", return_value=True), \
                mock.patch.object(gf, "tat") as tat, \
                mock.patch.object(gf, "mo") as mo:
            ra = gf.lam_moi("grok-1")
        self.assertEqual(ra["sso"], "a")
        tat.assert_called_once_with("grok-1")
        mo.assert_not_called()
