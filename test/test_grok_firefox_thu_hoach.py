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


def _ts(giay: int) -> bytes:
    """Timestamp protobuf {1: giây}."""
    out, v = bytearray(b"\x08"), giay
    while True:
        b, v = v & 0x7F, v >> 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def _quy_tuan_bytes(phan_tram: float, dau: int, cuoi: int) -> bytes:
    import struct
    a, b = _ts(dau), _ts(cuoi)
    cfg = b"\x0d" + struct.pack("<f", phan_tram) + b"\x22" + bytes([len(a)]) + a + b"\x2a" + bytes([len(b)]) + b
    msg = b"\x0a" + bytes([len(cfg)]) + cfg
    return b"\x00" + len(msg).to_bytes(4, "big") + msg


class HanMucTests(unittest.TestCase):
    """Theo grok2api + đo 02/10/2026 tài khoản miễn phí Main: auto 5/7, fast 0/30 (/ngày), Ảnh Pro 0, Video 720p 1."""

    def _tra(self, theo):
        import json

        def goi(cookies, duong, body, kieu="application/json"):
            if duong == "/rest/rate-limits":
                return json.dumps(theo[json.loads(body)["modelName"]]).encode()
            return theo.get(duong)
        return mock.patch.object(gf, "_goi_post", side_effect=goi)

    def test_goi_mien_phi_che_do_va_ve_anh(self):
        import json
        theo = {"auto": {"windowSizeSeconds": 86400, "remainingQueries": 5, "totalQueries": 7},
                "fast": {"windowSizeSeconds": 86400, "remainingQueries": 0, "waitTimeSeconds": 3600, "totalQueries": 30},
                "/rest/media/imagine/quota_info": json.dumps({
                    "image": None, "imageEdit": None, "video": None,
                    "imagePro": {"available": True, "remainingQueries": 0, "windowSizeSeconds": 86400,
                                 "nextAvailableAt": "2026-10-02T16:11:01.206245968Z"},
                    "video720p": {"available": True, "remainingQueries": 1, "windowSizeSeconds": 86400}}).encode()}
        with self._tra(theo):
            hm = gf.han_muc({"sso": "x"})
        self.assertEqual(hm["goi"], "Miễn phí")
        self.assertEqual([(m["ten"], m["con"], m["tong"]) for m in hm["ds"]],
                         [("Auto", 5, 7), ("Fast", 0, 30), ("Ảnh Pro", 0, 0), ("Video 720p", 1, 0)])
        self.assertIsNotNone(hm["ds"][1]["hoi_luc"])
        from datetime import datetime, timezone
        self.assertEqual(hm["ds"][2]["hoi_luc"], datetime(2026, 10, 2, 16, 11, 1, tzinfo=timezone.utc).timestamp())

    def test_goi_tra_phi_dung_quy_tuan(self):
        theo = {"auto": {"windowSizeSeconds": 7200, "remainingQueries": 40, "totalQueries": 50},
                "fast": {"windowSizeSeconds": 7200, "remainingQueries": 100, "totalQueries": 140},
                "/grok_api_v2.GrokBuildBilling/GetGrokCreditsConfig": _quy_tuan_bytes(37.5, 1790000000, 1790604800)}
        with self._tra(theo):
            hm = gf.han_muc({"sso": "x"})
        self.assertEqual(hm["goi"], "SuperGrok")
        self.assertEqual([(m["ten"], m["con"], m["tong"], m["cua_so"]) for m in hm["ds"]],
                         [("Tuần (chung)", 62, 100, 604800)])

    def test_tin_hieu_mau_thuan_lay_goi_thap(self):
        theo = {"auto": {"remainingQueries": 1, "totalQueries": 7}, "fast": {"remainingQueries": 1, "totalQueries": 140}}
        with self._tra(theo):
            self.assertEqual(gf.han_muc({"sso": "x"})["goi"], "Miễn phí")

    def test_quy_tuan_goi_mien_phi_rong(self):
        self.assertIsNone(gf.quy_tuan(b"", 0))
        self.assertIsNone(gf.quy_tuan(b"\x00\x00\x00\x00\x00", 0))

    def test_luu_tam_va_cay_tai_khoan_khong_cho_mang(self):
        gf._han_muc.clear()
        with mock.patch.object(gf, "doc_cookie_file", return_value={"sso": "x"}), \
                mock.patch.object(gf, "han_muc", return_value={"goi": "Miễn phí", "ds": [{"ten": "Fast"}]}) as hm, \
                mock.patch("threading.Thread") as th:
            self.assertIsNone(gf.han_muc_cua("grok-1", cho=False), "cây tài khoản: chưa có thì trả rỗng, không chờ")
            th.assert_called_once()
            gf._han_muc_dang.clear()
            self.assertEqual(gf.han_muc_cua("grok-1", cho=True)["ds"], [{"ten": "Fast"}])
            self.assertEqual(gf.han_muc_cua("grok-1", cho=True)["goi"], "Miễn phí")
            self.assertEqual(hm.call_count, 1, "trong 5 phút dùng bản lưu tạm")
        gf._han_muc.clear()
