"""Quyền + chọn giọng Giáo viên tiểu học."""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import teacher as t  # noqa: E402


class TeacherDetectLangTests(unittest.TestCase):
    def test_vietnamese_marks(self) -> None:
        self.assertEqual(t.detect_lang("Hôm nay học phép cộng"), "vi")

    def test_english_words(self) -> None:
        self.assertEqual(
            t.detect_lang("cat dog bird apple banana orange school"), "en")


class TeacherVoiceTests(unittest.TestCase):
    def test_voice_for_text_uses_cfg(self) -> None:
        with mock.patch.object(t, "_cfg", return_value={
            "voice_vi": "vieneu:A", "voice_en": "kokoro:af",
        }):
            self.assertEqual(t.voice_for_text("xin chào các em"), "vieneu:A")
            self.assertEqual(
                t.voice_for_text("hello world apple banana school friend"),
                "kokoro:af")


class TeacherPermissionTests(unittest.TestCase):
    def test_disabled_blocks(self) -> None:
        with mock.patch.object(t, "is_enabled", return_value=False):
            self.assertFalse(t.can_use_teacher("tg", "b", "c"))

    def test_no_filter_allows(self) -> None:
        with mock.patch.object(t, "is_enabled", return_value=True), \
                mock.patch("services.agent.capabilities.allowed_groups_for_bot",
                           return_value=None):
            self.assertTrue(t.can_use_teacher("tg", "b", "c"))

    def test_filter_requires_teacher_group(self) -> None:
        with mock.patch.object(t, "is_enabled", return_value=True), \
                mock.patch("services.agent.capabilities.allowed_groups_for_bot",
                           return_value={"homeassistant", "tts_reply"}):
            self.assertFalse(t.can_use_teacher("tg", "b", "c"))
        with mock.patch.object(t, "is_enabled", return_value=True), \
                mock.patch("services.agent.capabilities.allowed_groups_for_bot",
                           return_value={"teacher", "skills"}):
            self.assertTrue(t.can_use_teacher("tg", "b", "c"))

    def test_speak_needs_master_toggle(self) -> None:
        with mock.patch.object(t, "speak_to_speaker_enabled", return_value=False), \
                mock.patch.object(t, "can_use_teacher", return_value=True):
            self.assertFalse(t.can_teacher_speak("tg", "b", "c"))


class TeacherWorkspaceTests(unittest.TestCase):
    def test_search_sgk_all_grades(self) -> None:
        from services.agent import teacher_workspace as tw

        tw._seeded = False
        for g in (1, 2, 3, 4, 5, 6, 9, 10, 12):
            text = tw.search_sgk("học", grade=g, subject="toan", top_k=1)
            self.assertIn(f"Lớp {g}", text, msg=f"grade {g}")

    def test_search_sgk_toan_lop2(self) -> None:
        from services.agent import teacher_workspace as tw

        tw._seeded = False
        text = tw.search_sgk("trừ có mượn", grade=2, subject="toan", top_k=2)
        self.assertIn("Lớp 2", text)
        self.assertTrue("mượn" in text.lower() or "Trừ" in text)

    def test_workspaces_thirty_six(self) -> None:
        from services.agent import teacher_workspace as tw

        tw._seeded = False
        # Force merge new grades even if old 15-ws file exists
        defaults = tw._default_workspaces()
        self.assertEqual(len(defaults), 36)
        rows = tw.list_workspaces()
        # After seed/merge should have at least default keys available via re-seed
        tw._seeded = False
        if tw._WS_PATH.exists():
            # merge path
            tw._ensure_seeded()
        rows = tw.list_workspaces()
        ids = {r["id"] for r in rows}
        self.assertIn("lop1-van", ids)
        self.assertIn("lop2-toan", ids)
        self.assertIn("lop9-toan", ids)
        self.assertIn("lop12-anh", ids)

    def test_list_sgk_index(self) -> None:
        from services.agent import teacher_workspace as tw

        tw._seeded = False
        idx = tw.list_sgk_index()
        self.assertIn("Lớp 1", idx)
        self.assertIn("Lớp 5", idx)
        self.assertIn("Toán", idx)

    def test_import_pdf_appends_md(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock

        from services.agent import teacher_workspace as tw

        tw._seeded = False
        tw._ensure_seeded()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-fake")
            tmp = f.name
        try:
            with mock.patch(
                "services.pdf_intent.extract_markdown",
                return_value="## Bai cong\n\nBa cong hai bang nam.\n",
            ):
                r = tw.import_sgk_pdf(
                    tmp, grade=1, subject="toan", mode="append", source_name="test.pdf",
                )
            self.assertTrue(r.get("ok"), r)
            self.assertEqual(r.get("workspace"), "lop1-toan")
            dest = Path(r["path"])
            self.assertTrue(dest.is_file())
            body = dest.read_text(encoding="utf-8")
            self.assertIn("Bai cong", body)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_student_memory_roundtrip(self) -> None:
        from services.agent import teacher_workspace as tw

        tw._seeded = False
        out = tw.memory_add(
            "lop3-van", "hs_demo",
            weak_topic="chính tả hỏi ngã",
            note="Buổi 1: còn nhầm hỏi/ngã",
        )
        self.assertIn("chính tả", out)
        got = tw.memory_get("lop3-van", "hs_demo")
        self.assertIn("Điểm yếu", got)

    def test_quiz_and_grade_math(self) -> None:
        from services.agent import teacher_assess as ta
        from services.agent import teacher_workspace as tw

        tw._seeded = False
        quiz = ta.make_quiz(grade=2, subject="toan", topic="cộng", n=3)
        self.assertEqual(len(quiz["questions"]), 3)
        self.assertTrue(quiz["quiz_id"])
        # objective grade
        r = ta.grade_answer(
            question="Tính 3+2",
            student_answer="5",
            answer_hint="5",
            subject="toan",
            use_llm=False,
        )
        self.assertEqual(r["score_0_10"], 10)
        r2 = ta.grade_answer(
            question="Tính 3+2",
            student_answer="7",
            answer_hint="5",
            subject="toan",
            use_llm=False,
        )
        self.assertLess(r2["score_0_10"], 10)


if __name__ == "__main__":
    unittest.main()
