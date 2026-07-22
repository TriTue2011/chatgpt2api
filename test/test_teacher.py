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

    def test_model_speak_vs_write(self) -> None:
        with mock.patch.object(t, "_cfg", return_value={
            "model_speak": "fast/speak",
            "model_write": "strong/write",
        }):
            self.assertEqual(t.model_speak(), "fast/speak")
            self.assertEqual(t.model_write(), "strong/write")
            self.assertEqual(t.model_for("speak"), "fast/speak")
            self.assertEqual(t.model_for("write"), "strong/write")
            self.assertEqual(t.model_for("tts"), "fast/speak")

    def test_english_skill_models(self) -> None:
        with mock.patch.object(t, "_cfg", return_value={
            "model_speak": "fb/speak",
            "model_write": "fb/write",
            "english": {
                "models": {
                    "grammar": "en/grammar",
                    "listening": "en/listen",
                    "speaking": "en/speak",
                    "reading": "en/read",
                    "writing": "en/write",
                },
            },
        }):
            self.assertEqual(t.model_for_english_skill("grammar"), "en/grammar")
            self.assertEqual(t.model_for_english_skill("listening"), "en/listen")
            self.assertEqual(t.model_for_english_skill("speaking"), "en/speak")
            self.assertEqual(t.model_for_english_skill("reading"), "en/read")
            self.assertEqual(t.model_for_english_skill("writing"), "en/write")
            self.assertEqual(t.model_for_english_skill("past"), "en/grammar")
            self.assertEqual(t.model_for("nói"), "en/speak")
        # empty skill → fallback speak/write
        with mock.patch.object(t, "_cfg", return_value={
            "model_speak": "fb/speak",
            "model_write": "fb/write",
            "english": {"models": {}},
        }):
            self.assertEqual(t.model_for_english_skill("listening"), "fb/speak")
            self.assertEqual(t.model_for_english_skill("writing"), "fb/write")


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
        quiz = ta.make_quiz(grade=2, subject="toan", topic="trừ có mượn", n=3)
        self.assertEqual(len(quiz["questions"]), 3)
        self.assertTrue(quiz["quiz_id"])
        # Phải là bài tính thật, không dán đoạn SGK
        for q in quiz["questions"]:
            p = q["prompt"]
            self.assertRegex(p, r"\d+\s*[−+\-×÷*]\s*\d+|Tính:", msg=p)
            self.assertNotIn("Gợi ý nội dung", p)
            self.assertTrue(str(q.get("answer_hint") or "").strip())
        # chấm theo đáp án sinh ra
        q0 = quiz["questions"][0]
        r = ta.grade_answer(
            question=q0["prompt"],
            student_answer=str(q0["answer_hint"]),
            answer_hint=str(q0["answer_hint"]),
            subject="toan",
            use_llm=False,
        )
        self.assertEqual(r["score_0_10"], 10)
        self.assertTrue(r.get("praise"))
        r2 = ta.grade_answer(
            question=q0["prompt"],
            student_answer="99999",
            answer_hint=str(q0["answer_hint"]),
            subject="toan",
            use_llm=False,
        )
        self.assertLess(r2["score_0_10"], 10)

    def test_progressive_hints_levels(self) -> None:
        from services.agent import teacher_assess as ta

        h1 = ta.progressive_hints(
            question="Tính 12 chia 3", student_attempt="", level=1, subject="toan",
        )
        self.assertEqual(h1["level"], 1)
        self.assertFalse(h1["spoiler"])
        self.assertIn("level 1", h1["text"].lower())
        h3 = ta.progressive_hints(
            question="Tính 12 chia 3",
            student_attempt="4",
            answer_hint="4",
            level=3,
            subject="toan",
        )
        self.assertTrue(h3["spoiler"])
        self.assertGreaterEqual(len(h3["hints"]), 2)

    def test_make_check_one_question(self) -> None:
        from services.agent import teacher_assess as ta
        from services.agent import teacher_workspace as tw

        tw._seeded = False
        c = ta.make_check(grade=8, subject="toan", topic="phương trình")
        self.assertTrue(c.get("check_id"))
        self.assertTrue(c.get("question"))
        self.assertIn("Kiểm tra hiểu", c.get("text") or "")

    def test_lesson_plan_and_tts_verbalize(self) -> None:
        from services.agent import teacher as teach

        plan = teach.build_lesson_plan(
            grade=2, subject="toan", topic="phép trừ có mượn",
            objective="Trừ có mượn trong phạm vi 100",
            student_weak="quên mượn",
        )
        self.assertIn("Giáo án", plan)
        self.assertIn("giao-vien-tieu-hoc", plan)
        self.assertIn("teacher_hint", plan)
        self.assertEqual(teach.skill_for_grade(7), "giao-vien-thcs")
        self.assertEqual(teach.skill_for_grade(11), "giao-vien-thpt")
        spoken = teach.verbalize_for_tts("3 × 4 = 12 · 50%")
        self.assertIn("nhân", spoken)
        self.assertIn("bằng", spoken)
        self.assertIn("phần trăm", spoken)
        self.assertNotIn("×", spoken)

    def test_rubric_bands(self) -> None:
        from services.agent import teacher_assess as ta

        b = ta.rubric_band(9, subject="van")
        self.assertEqual(b["band"], "Xuất sắc")
        b2 = ta.rubric_band(4, subject="anh")
        self.assertIn(b2["band"], ("Weak", "Fair", "Yếu", "Trung bình"))
        help_text = ta.format_rubric_help("van")
        self.assertIn("Rubric", help_text)

    def test_adaptive_three_correct_harder(self) -> None:
        from services.agent import teacher_classroom as tc

        ws, st = "lop2-toan", "test_adapt_hs"
        # reset by writing easy start
        d = tc._load_adapt(ws, st)
        d["level"] = "medium"
        d["streak_correct"] = 0
        d["streak_wrong"] = 0
        tc._write_json(tc._adapt_path(ws, st), d)
        for _ in range(3):
            tc.record_answer_result(ws, st, correct=True, score=10)
        self.assertEqual(tc.adaptive_level(ws, st), "hard")
        for _ in range(3):
            tc.record_answer_result(ws, st, correct=False, score=2)
        self.assertEqual(tc.adaptive_level(ws, st), "medium")

    def test_classroom_lesson_and_assignment(self) -> None:
        from services.agent import teacher_classroom as tc
        from services.agent import teacher_workspace as tw

        tw._seeded = False
        lesson = tc.create_lesson(
            title="Trừ có mượn",
            body_text="Khi trừ hàng đơn vị không đủ thì mượn 1 chục.",
            tts_script="Khi trừ không đủ thì mượn một chục.",
            grade=2, subject="toan",
        )
        self.assertTrue(lesson["id"])
        asg = tc.create_assignment(
            title="BT trừ",
            grade=2, subject="toan", topic="trừ", n=2,
            difficulty="easy", student_key="hs_test",
        )
        self.assertEqual(len(asg["questions"]), 2)
        # student view hides hints
        sv = tc.get_assignment(asg["id"], for_student=True)
        self.assertIsNotNone(sv)
        assert sv is not None
        self.assertNotIn("answer_hint", sv["questions"][0])
        answers = {q["id"]: "1" for q in asg["questions"]}
        sub = tc.submit_assignment(asg["id"], answers, student_key="hs_test", use_llm=False)
        self.assertTrue(sub.get("ok"))
        self.assertIn("average_0_10", sub)
        dash = tc.parent_dashboard(workspace_id="lop2-toan", student_key="hs_test", weeks=2)
        self.assertTrue(dash.get("ok"))

    def test_pdf_chapter_headings(self) -> None:
        from services.agent import teacher_workspace as tw

        md = tw._md_from_pdf_text(
            "Chương 1\nPhép cộng\n\nNội dung a.\n\nBài 2\nLuyện tập\nNội dung b.",
            title="SGK test",
        )
        self.assertIn("## Chương 1", md)
        self.assertIn("## Bài 2", md)
        self.assertGreaterEqual(md.count("## "), 2)

    def test_delete_lesson_and_assignment(self) -> None:
        from services.agent import teacher_classroom as tc

        lesson = tc.create_lesson(
            title="tmp", body_text="x", grade=2, subject="toan",
        )
        self.assertTrue(tc.delete_lesson(lesson["id"]).get("ok"))
        self.assertIsNone(tc.get_lesson(lesson["id"]))
        asg = tc.create_assignment(
            title="tmp bt", grade=2, subject="toan", topic="cộng", n=1,
            difficulty="easy",
        )
        self.assertTrue(tc.delete_assignment(asg["id"]).get("ok"))
        self.assertIsNone(tc.get_assignment(asg["id"]))

    def test_ai_draft_fallback_no_llm(self) -> None:
        from services.agent import teacher_classroom as tc

        # use_ai=False → generator, luôn có câu
        d = tc.ai_draft_assignment(
            grade=2, subject="van", topic="chính tả", n=2,
            difficulty="easy", use_ai=False,
        )
        self.assertTrue(d.get("ok"))
        self.assertEqual(len(d.get("questions") or []), 2)
        lesson = tc.ai_draft_lesson(grade=2, subject="toan", topic="cộng")
        self.assertTrue(lesson.get("ok"))
        self.assertTrue(lesson.get("body_text"))

    def test_english_comprehensive_by_grade(self) -> None:
        from services.agent import teacher_assess as ta
        from services.agent import teacher_english as te

        sm = te.english_skill_map(8)
        self.assertEqual(sm["band"], "thcs")
        self.assertTrue(sm["skills"])
        # primary
        q2 = ta.make_quiz(grade=2, subject="anh", topic="animals", n=4, difficulty="easy")
        skills2 = {x.get("skill") or x.get("source") for x in q2["questions"]}
        self.assertTrue(any("animal" in str(s) or "en:" in str(s) for s in skills2))
        for x in q2["questions"]:
            self.assertTrue(x.get("prompt"))
            self.assertTrue(str(x.get("answer_hint") or "").strip())
            self.assertNotIn("Gợi ý nội dung", x["prompt"])
        # thcs grammar
        q8 = ta.make_quiz(grade=8, subject="anh", topic="past simple", n=3)
        self.assertEqual(len(q8["questions"]), 3)
        self.assertTrue(
            any(
                "Past" in x["prompt"] or "past" in x["prompt"].lower()
                or "went" in str(x.get("answer_hint"))
                or "Grammar" in x["prompt"]
                for x in q8["questions"]
            )
        )
        # thpt
        q11 = ta.make_quiz(grade=11, subject="anh", topic="conditional", n=2)
        self.assertTrue(q11["questions"][0]["prompt"])
        self.assertIn("Accuracy", te.english_rubric_detailed())


class TeacherPathPlacementTests(unittest.TestCase):
    """Placement + lộ trình: lưu độc lập theo học sinh."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        from services.agent import teacher_path as tp

        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name) / "students"
        self._root.mkdir(parents=True, exist_ok=True)
        self._patch = mock.patch.object(tp, "_ROOT", self._root)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_profiles_independent(self) -> None:
        from services.agent import teacher_path as tp

        a = tp.get_or_create_profile("hs_an", display_name="An", grade=3)
        b = tp.get_or_create_profile("hs_binh", display_name="Bình", grade=5)
        self.assertEqual(a["display_name"], "An")
        self.assertEqual(b["display_name"], "Bình")
        self.assertNotEqual(a["student_key"], b["student_key"])
        rows = tp.list_students()
        keys = {r["student_key"] for r in rows}
        self.assertIn("hs_an", keys)
        self.assertIn("hs_binh", keys)

    def test_delete_student(self) -> None:
        from services.agent import teacher_path as tp

        tp.get_or_create_profile("hs_del", display_name="Xóa", grade=2)
        self.assertIsNotNone(tp.get_profile("hs_del"))
        r = tp.delete_student("hs_del")
        self.assertTrue(r.get("ok"))
        self.assertIsNone(tp.get_profile("hs_del"))
        keys = {x["student_key"] for x in tp.list_students()}
        self.assertNotIn("hs_del", keys)
        r2 = tp.delete_student("hs_del")
        self.assertFalse(r2.get("ok"))

    def test_strands_by_subject(self) -> None:
        from services.agent import teacher_path as tp

        math = tp.strands_for("toan", 4)
        van = tp.strands_for("van", 4)
        anh = tp.strands_for("anh", 8)
        self.assertTrue(any(s["id"] == "nhan" for s in math))
        self.assertTrue(any(s["id"] == "chinhta" for s in van))
        self.assertEqual({s["id"] for s in anh}, {
            "grammar", "listening", "speaking", "reading", "writing",
        })

    def test_placement_submit_builds_roadmap_weak_first(self) -> None:
        from services.agent import teacher_path as tp

        start = tp.start_placement(
            student_key="hs_cam", subject="toan", grade=3, n_per_strand=1,
        )
        self.assertTrue(start.get("ok"))
        self.assertTrue(start.get("questions"))
        pid = start["placement_id"]
        # all wrong-ish answers → weak strands
        answers = {q["id"]: "???" for q in start["questions"]}
        result = tp.submit_placement(pid, answers, student_key="hs_cam")
        self.assertTrue(result.get("ok"))
        self.assertIn("roadmap", result)
        rm = result["roadmap"]
        self.assertEqual(rm["student_key"], "hs_cam")
        self.assertEqual(rm["subject"], "toan")
        # high priority remediate should appear before low review
        priorities = [
            s.get("priority") for s in rm["steps"] if s.get("priority")
        ]
        if "high" in priorities and "low" in priorities:
            self.assertLess(priorities.index("high"), priorities.index("low"))
        # files isolated under student dir
        pl = tp.get_placement("hs_cam", "toan")
        self.assertIsNotNone(pl)
        self.assertEqual(pl["student_key"], "hs_cam")
        # other student not polluted
        self.assertIsNone(tp.get_placement("hs_other", "toan"))

    def test_two_students_different_roadmaps(self) -> None:
        from services.agent import teacher_path as tp

        for sk, grade in (("hs_a", 5), ("hs_b", 5)):
            st = tp.start_placement(
                student_key=sk, subject="van", grade=grade, n_per_strand=1,
            )
            ans = {q["id"]: "x" for q in st["questions"]}
            tp.submit_placement(st["placement_id"], ans, student_key=sk)
        ra = tp.get_roadmap("hs_a", "van")
        rb = tp.get_roadmap("hs_b", "van")
        self.assertIsNotNone(ra)
        self.assertIsNotNone(rb)
        self.assertEqual(ra["student_key"], "hs_a")
        self.assertEqual(rb["student_key"], "hs_b")
        # separate on-disk paths
        path_a = self._root / "hs_a" / "roadmap" / "van.json"
        path_b = self._root / "hs_b" / "roadmap" / "van.json"
        self.assertTrue(path_a.is_file())
        self.assertTrue(path_b.is_file())

    def test_advance_roadmap_step(self) -> None:
        from services.agent import teacher_path as tp

        tp.get_or_create_profile("hs_adv", grade=4)
        # default roadmap without placement
        rm = tp.build_roadmap("hs_adv", "toan", grade=4)
        sid = rm["steps"][0]["id"]
        out = tp.advance_roadmap_step("hs_adv", "toan", sid, done=True)
        self.assertTrue(out.get("ok"))
        self.assertGreaterEqual(out["roadmap"]["steps_done"], 1)

    def test_pedagogy_dict(self) -> None:
        from services.agent import teacher_path as tp

        for sub in ("toan", "van", "anh"):
            p = tp.pedagogy_for(sub)
            self.assertIn("name", p)
            self.assertIn("diagnostic", p)
            self.assertIn("path", p)
            self.assertIn("session", p)

    def test_apply_practice_advances_on_high_score(self) -> None:
        from services.agent import teacher_path as tp

        st = tp.start_placement(
            student_key="hs_adv2", subject="toan", grade=3, n_per_strand=1,
        )
        answers = {q["id"]: "???" for q in st["questions"]}
        tp.submit_placement(st["placement_id"], answers, student_key="hs_adv2")
        focus = tp.current_focus("hs_adv2", "toan")
        self.assertTrue(focus.get("ok"))
        old = focus.get("title")
        # high score → advance
        r = tp.apply_practice_result(
            "hs_adv2", "toan",
            average_0_10=9.0,
            topic=str(focus.get("topic") or ""),
            step_id=str(focus.get("step_id") or ""),
        )
        self.assertTrue(r.get("ok"))
        self.assertEqual(r.get("action"), "advance")
        self.assertNotEqual(r.get("new_focus"), old)

    def test_apply_practice_remediate_on_low_score(self) -> None:
        from services.agent import teacher_path as tp

        st = tp.start_placement(
            student_key="hs_low", subject="van", grade=4, n_per_strand=1,
        )
        answers = {q["id"]: "x" for q in st["questions"]}
        tp.submit_placement(st["placement_id"], answers, student_key="hs_low")
        focus = tp.current_focus("hs_low", "van")
        r = tp.apply_practice_result(
            "hs_low", "van",
            average_0_10=3.0,
            step_id=str(focus.get("step_id") or ""),
        )
        self.assertEqual(r.get("action"), "remediate")
        rm = r["roadmap"]
        # current step should still be high priority
        sid = rm.get("current_step_id")
        step = next(s for s in rm["steps"] if s["id"] == sid)
        self.assertEqual(step.get("priority"), "high")


class TeacherClassroomRoadmapHookTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        from services.agent import teacher_path as tp
        from services.agent import teacher_classroom as tc

        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self._root = base / "students"
        self._root.mkdir()
        self._class = base / "classroom"
        self._class.mkdir()
        self._p1 = mock.patch.object(tp, "_ROOT", self._root)
        self._p1.start()
        # classroom dirs
        self._p2 = mock.patch.object(tc, "_ROOT", self._class)
        self._p2.start()
        self._p3 = mock.patch.object(tc, "_LESSONS", self._class / "lessons")
        self._p3.start()
        self._p4 = mock.patch.object(tc, "_ASSIGN", self._class / "assignments")
        self._p4.start()
        self._p5 = mock.patch.object(tc, "_SUBS", self._class / "submissions")
        self._p5.start()
        self._p6 = mock.patch.object(tc, "_ADAPT", self._class / "adaptive")
        self._p6.start()

    def tearDown(self) -> None:
        for p in (self._p1, self._p2, self._p3, self._p4, self._p5, self._p6):
            p.stop()
        self._tmp.cleanup()

    def test_create_assignment_from_roadmap_topic(self) -> None:
        from services.agent import teacher_path as tp
        from services.agent import teacher_classroom as tc

        st = tp.start_placement(
            student_key="hs_rm", subject="toan", grade=3, n_per_strand=1,
        )
        tp.submit_placement(
            st["placement_id"],
            {q["id"]: "0" for q in st["questions"]},
            student_key="hs_rm",
        )
        focus = tp.current_focus("hs_rm", "toan")
        asg = tc.create_assignment(
            title="",
            grade=3,
            subject="toan",
            topic="",
            student_key="hs_rm",
            n=2,
            difficulty="easy",
            from_roadmap=True,
        )
        self.assertTrue(asg.get("from_roadmap"))
        self.assertTrue(asg.get("topic"))
        self.assertEqual(asg.get("roadmap_step_id"), focus.get("step_id"))
        # submit should update roadmap
        answers = {q["id"]: str(q.get("answer_hint") or "1") for q in asg["questions"]}
        with mock.patch(
            "services.agent.teacher_assess.grade_answer",
            return_value={
                "score_0_10": 9,
                "correct": True,
                "feedback": "ok",
            },
        ):
            sub = tc.submit_assignment(asg["id"], answers, student_key="hs_rm", use_llm=False)
        self.assertTrue(sub.get("ok"))
        self.assertIn("roadmap_update", sub)
        self.assertEqual(sub["roadmap_update"].get("action"), "advance")

    def test_parent_dashboard_includes_path(self) -> None:
        from services.agent import teacher_path as tp
        from services.agent import teacher_classroom as tc

        st = tp.start_placement(
            student_key="hs_ph", subject="anh", grade=6, n_per_strand=1,
        )
        tp.submit_placement(
            st["placement_id"],
            {q["id"]: "a" for q in st["questions"]},
            student_key="hs_ph",
        )
        dash = tc.parent_dashboard(student_key="hs_ph", weeks=2)
        self.assertTrue(dash.get("ok"))
        self.assertGreaterEqual(dash.get("count") or 0, 1)
        row = next(
            (s for s in dash["students"] if s["student_key"] == "hs_ph"),
            dash["students"][0],
        )
        self.assertIn("path", row)
        self.assertIn("anh", row["path"])
        self.assertTrue(row["path"]["anh"].get("current_focus"))


if __name__ == "__main__":
    unittest.main()
