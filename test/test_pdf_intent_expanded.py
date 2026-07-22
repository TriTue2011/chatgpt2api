"""PDF intents: rag_knowledge / rag_teacher / word / excel."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import pdf_intent as pi
from services import pdf_to_excel as p2x


class PdfIntentParseTests(unittest.TestCase):
    def test_parse_numbers(self) -> None:
        all_i = pi.ALL_INTENTS
        self.assertEqual(pi.parse_intent("1", all_i), pi.RAG_KNOWLEDGE)
        self.assertEqual(pi.parse_intent("2", all_i), pi.RAG_TEACHER)
        self.assertEqual(pi.parse_intent("3", all_i), pi.WORD)
        self.assertEqual(pi.parse_intent("4", all_i), pi.EXCEL)
        # filtered: only word+excel → 1=word, 2=excel
        we = {pi.WORD, pi.EXCEL}
        self.assertEqual(pi.parse_intent("1", we), pi.WORD)
        self.assertEqual(pi.parse_intent("2", we), pi.EXCEL)

    def test_parse_keywords(self) -> None:
        self.assertEqual(pi.parse_intent("nạp rag kiến thức"), pi.RAG_KNOWLEDGE)
        self.assertEqual(pi.parse_intent("teacher sgk"), pi.RAG_TEACHER)
        self.assertEqual(pi.parse_intent("chuyển word"), pi.WORD)
        self.assertEqual(pi.parse_intent("excel bảng"), pi.EXCEL)
        self.assertEqual(pi.parse_intent("tóm tắt"), pi.RAG_KNOWLEDGE)  # legacy

    def test_teacher_meta(self) -> None:
        self.assertEqual(pi.parse_teacher_meta("5 toán"), {"grade": 5, "subject": "toan"})
        self.assertEqual(pi.parse_teacher_meta("lớp 9 văn"), {"grade": 9, "subject": "van"})
        self.assertEqual(pi.parse_teacher_meta("12 anh"), {"grade": 12, "subject": "anh"})
        self.assertIsNone(pi.parse_teacher_meta("toán thôi"))
        self.assertIsNone(pi.parse_teacher_meta("lớp 5"))

    def test_allowed_intents(self) -> None:
        self.assertEqual(pi.allowed_intents(None), pi.ALL_INTENTS)
        a = pi.allowed_intents({"rag", "word"})
        self.assertIn(pi.RAG_KNOWLEDGE, a)
        self.assertIn(pi.WORD, a)
        self.assertIn(pi.EXCEL, a)
        self.assertNotIn(pi.RAG_TEACHER, a)
        b = pi.allowed_intents({"teacher"})
        self.assertEqual(b, {pi.RAG_TEACHER})

    def test_ask_text_lists_options(self) -> None:
        t = pi.ask_text("a.pdf", pi.ALL_INTENTS)
        self.assertIn("kiến thức", t.lower())
        self.assertIn("teacher", t.lower())
        self.assertIn("Word", t)
        self.assertIn("Excel", t)

    def test_pending_stages(self) -> None:
        key = "test:pdf:1"
        pi.set_pending(key, b"%PDF-1.4 minimal", "t.pdf")
        self.assertTrue(pi.has_pending(key))
        p = pi.get_pending(key)
        self.assertEqual(p.get("stage"), "choose")
        pi.update_pending(key, stage="teacher_meta")
        self.assertEqual(pi.get_pending(key).get("stage"), "teacher_meta")
        pi.pop_pending(key)
        self.assertFalse(pi.has_pending(key))


class PdfToExcelTests(unittest.TestCase):
    def test_minimal_xlsx_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "t.xlsx"
            p2x._write_xlsx(out, [("S1", [["a", "b"], ["1", "2"]])])
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 100)

    def test_convert_missing(self) -> None:
        r = p2x.convert_pdf_to_xlsx("/no/such/file.pdf")
        self.assertFalse(r.get("ok"))

    def test_clean_table_drop_empty(self) -> None:
        rows = [
            ["A", "B", ""],
            ["1", "2", ""],
            ["", "", ""],
            ["1", "2", ""],  # dup of body after header — kept once header filter
        ]
        cleaned = p2x._clean_table(rows)
        # empty col dropped, empty row dropped
        self.assertTrue(all(len(r) == 2 for r in cleaned))
        self.assertTrue(all(any(c for c in r) for r in cleaned))

    def test_lines_to_columns(self) -> None:
        text = "Name    Age    City\nAlice   30     HN\nBob     25     HCM\n"
        rows = p2x._lines_to_columns(text)
        self.assertGreaterEqual(len(rows), 2)
        self.assertGreaterEqual(len(rows[0]), 2)

    def test_dedupe_fingerprint(self) -> None:
        t = [["H1", "H2"], ["a", "b"]]
        sheets = [("A", t), ("B", t)]  # same table twice
        cleaned = p2x._clean_all_sheets(sheets)
        self.assertEqual(len(cleaned), 1)

    def test_coerce_value(self) -> None:
        self.assertEqual(p2x._coerce_value("42"), 42)
        self.assertEqual(p2x._coerce_value("3,14"), 3.14)
        self.assertEqual(p2x._coerce_value("abc"), "abc")


if __name__ == "__main__":
    unittest.main()
