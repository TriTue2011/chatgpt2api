"""Tra từ điển Anh–Việt tại chỗ — services/tu_dien.py.

Dựng một SQLite tí hon đúng lược đồ của kho thật (4 bảng: words, definitions,
word_definitions, pronunciations) nên test chạy được mà không cần tệp 44 MB.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.config as cfg
from services import tu_dien as td

_LUOC_DO = """
CREATE TABLE words (id INTEGER PRIMARY KEY, word TEXT NOT NULL,
                    lang_code TEXT NOT NULL DEFAULT 'vi');
CREATE TABLE definitions (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          definition TEXT NOT NULL, pos TEXT, sub_pos TEXT,
                          definition_lang TEXT DEFAULT 'vi');
CREATE TABLE word_definitions (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               word_id INTEGER NOT NULL,
                               definition_id INTEGER NOT NULL, example TEXT);
CREATE TABLE pronunciations (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             word_id INTEGER NOT NULL, ipa TEXT NOT NULL,
                             region TEXT);
"""

#: (từ, IPA, [(nghĩa VI, mã từ loại, câu ví dụ)])
_MUC = [
    ("stroke", "/strəʊk/", [("Cú, cú đánh, đòn.", "N", "A powerful stroke."),
                            ("Đột quỵ.", "N", "He suffered a sudden stroke."),
                            ("Vuốt ve.", "V", "He stroked the cat.")]),
    ("run", "/rʌn/", [("Chạy.", "V", "They run fast.")]),
    ("city", "", [("Thành phố.", "N", "")]),
    ("stop", "", [("Dừng lại.", "V", "")]),
]


class TuDienTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._data = Path(self._tmp.name)
        (self._data / "tudien").mkdir(parents=True)
        db = sqlite3.connect(self._data / "tudien" / "en-vi.db")
        db.executescript(_LUOC_DO)
        for wid, (tu, ipa, nghia) in enumerate(_MUC, start=1):
            db.execute("INSERT INTO words (id, word, lang_code) VALUES (?,?,'en')",
                       (wid, tu))
            if ipa:
                db.execute("INSERT INTO pronunciations (word_id, ipa, region) "
                           "VALUES (?,?,'RP')", (wid, ipa))
            for vi, pos, vd in nghia:
                cur = db.execute(
                    "INSERT INTO definitions (definition, pos) VALUES (?,?)", (vi, pos))
                db.execute("INSERT INTO word_definitions (word_id, definition_id, "
                           "example) VALUES (?,?,?)", (wid, cur.lastrowid, vd))
        db.commit()
        db.close()
        self._cu = cfg.DATA_DIR
        cfg.DATA_DIR = self._data

    def tearDown(self) -> None:
        cfg.DATA_DIR = self._cu
        self._tmp.cleanup()

    def test_co_tu_dien(self):
        self.assertTrue(td.co_tu_dien("en"))
        self.assertFalse(td.co_tu_dien("ja"))   # chưa có tệp cho tiếng này

    def test_tra_ra_moi_nghia_khong_chon_ho(self):
        ra = td.tra("stroke")
        self.assertEqual(ra["tu"], "stroke")
        self.assertEqual(ra["ipa"], "/strəʊk/")
        self.assertEqual([n["vi"] for n in ra["nghia"]],
                         ["Cú, cú đánh, đòn.", "Đột quỵ.", "Vuốt ve."])

    def test_tu_loai_doi_sang_nhan_viet(self):
        ra = td.tra("stroke")
        self.assertEqual(ra["nghia"][0]["tu_loai"], "danh từ")
        self.assertEqual(ra["nghia"][2]["tu_loai"], "động từ")

    def test_cau_vi_du_di_kem(self):
        self.assertEqual(td.tra("stroke")["nghia"][1]["vi_du"],
                         "He suffered a sudden stroke.")

    def test_hoa_thuong_va_khoang_trang_khong_anh_huong(self):
        self.assertEqual(len(td.tra("  STROKE ")["nghia"]), 3)

    # ── dạng chia: kho tra theo TỪ GỐC ──────────────────────────────────────
    def test_so_nhieu_tra_ve_dang_goc(self):
        ra = td.tra("strokes")
        self.assertEqual(ra["tu"], "stroke")
        self.assertEqual(ra["goc"], "strokes")   # UI nói rõ đã đổi dạng

    def test_duoi_ing_va_phu_am_gap_doi(self):
        self.assertEqual(td.tra("running")["tu"], "run")
        self.assertEqual(td.tra("stopped")["tu"], "stop")

    def test_duoi_ies_ve_y(self):
        self.assertEqual(td.tra("cities")["tu"], "city")

    def test_dang_dung_thi_khong_doi(self):
        self.assertNotIn("goc", td.tra("stroke"))

    # ── không có thì im lặng, không làm đứt lượt dịch ───────────────────────
    def test_khong_co_tu_tra_rong(self):
        ra = td.tra("khongcotutunay")
        self.assertEqual(ra["nghia"], [])

    def test_tu_rong_tra_rong(self):
        self.assertEqual(td.tra("   ")["nghia"], [])

    def test_thieu_tep_tu_dien_thi_tat(self):
        (self._data / "tudien" / "en-vi.db").unlink()
        self.assertFalse(td.co_tu_dien("en"))
        self.assertEqual(td.tra("stroke")["nghia"], [])

    def test_tep_hong_khong_nem_loi(self):
        (self._data / "tudien" / "en-vi.db").write_text("không phải sqlite")
        self.assertEqual(td.tra("stroke")["nghia"], [])


if __name__ == "__main__":
    unittest.main()
