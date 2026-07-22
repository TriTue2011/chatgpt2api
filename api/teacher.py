"""API Giáo viên — status, SGK, memory, lớp học web (bài giảng, bài tập, PH)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, Header, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.support import require_admin


class LessonIn(BaseModel):
    title: str = ""
    body_text: str = ""
    tts_script: str = ""
    grade: int = 5
    subject: str = "toan"
    workspace_id: str = ""
    student_key: str = ""


class AssignmentIn(BaseModel):
    title: str = ""
    grade: int = 5
    subject: str = "toan"
    topic: str = ""
    workspace_id: str = ""
    n: int = 5
    difficulty: str = "auto"
    student_key: str = ""
    lesson_id: str = ""
    questions: list[dict[str, Any]] | None = None
    from_roadmap: bool = False


class SubmitIn(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)
    student_key: str = "default"
    use_llm: bool = True


class AiLessonIn(BaseModel):
    grade: int = 5
    subject: str = "toan"
    topic: str = ""
    workspace_id: str = ""
    notes: str = ""
    save: bool = False
    student_key: str = ""
    from_roadmap: bool = False


class AiAssignmentIn(BaseModel):
    grade: int = 5
    subject: str = "toan"
    topic: str = ""
    n: int = 5
    difficulty: str = "medium"
    workspace_id: str = ""
    notes: str = ""
    use_ai: bool = True
    save: bool = False
    student_key: str = ""
    lesson_id: str = ""
    title: str = ""
    from_roadmap: bool = False


class PlacementStartIn(BaseModel):
    student_key: str = "hs1"
    subject: str = "toan"
    grade: int = 5
    display_name: str = ""
    n_per_strand: int = 2


class PlacementSubmitIn(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)
    student_key: str = ""


class RoadmapAdvanceIn(BaseModel):
    step_id: str
    done: bool = True


class StudentProfileIn(BaseModel):
    student_key: str
    display_name: str = ""
    grade: int = 0
    notes: str = ""


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/teacher/status")
    async def teacher_status(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.agent import teacher as teach
        from services.agent import teacher_workspace as tw

        st = teach.status_public()
        st["workspaces"] = tw.list_workspaces()
        st["kb"] = tw.status_public()
        return st

    @router.get("/api/teacher/search")
    async def teacher_search(
        q: str = Query(default=""),
        grade: int | None = Query(default=None),
        subject: str = Query(default=""),
        workspace: str = Query(default=""),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_workspace as tw

        if not (q or "").strip():
            return {"ok": True, "text": tw.list_sgk_index()}
        text = tw.search_sgk(
            q, grade=grade, subject=subject or None, workspace_id=workspace or "",
        )
        return {"ok": True, "text": text}

    @router.post("/api/teacher/reseed")
    async def teacher_reseed(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.agent import teacher_workspace as tw

        tw._seeded = False  # type: ignore[attr-defined]
        tw._ensure_seeded()
        return {"ok": True, "kb": tw.status_public(), "workspaces": len(tw.list_workspaces())}

    @router.get("/api/teacher/imports")
    async def teacher_list_imports(
        grade: int = Query(default=0),
        subject: str = Query(default=""),
        limit: int = Query(default=40),
        authorization: str | None = Header(default=None),
    ):
        """Danh sách PDF đã import + markdown SGK theo lớp/môn."""
        require_admin(authorization)
        from services.agent import teacher_workspace as tw
        return tw.list_imports(
            grade=grade or None,
            subject=subject or None,
            limit=limit,
        )

    @router.post("/api/teacher/import-sgk")
    async def teacher_import_sgk(
        file: UploadFile = File(...),
        grade: int = Form(...),
        subject: str = Form(...),
        mode: str = Form(default="append"),
        title: str = Form(default=""),
        authorization: str | None = Header(default=None),
    ):
        """Upload PDF SGK → markdown theo chương/bài (##) + đẩy RAG."""
        require_admin(authorization)
        from services.agent import teacher_workspace as tw

        data = await file.read()
        name = file.filename or "sgk.pdf"

        def _run() -> dict:
            return tw.import_sgk_bytes(
                data, name, grade=grade, subject=subject, mode=mode, title=title,
            )

        result = await run_in_threadpool(_run)
        if not result.get("ok"):
            from fastapi import HTTPException
            raise HTTPException(400, str(result.get("error") or "import failed"))
        # Báo admin thread khi phân tích xong + RAG
        try:
            from services.notifier import notify_admin
            mon = {"toan": "Toán", "van": "Văn/TV", "anh": "Anh"}.get(
                str(result.get("subject") or ""), str(result.get("subject") or "")
            )
            rag = result.get("rag") if isinstance(result.get("rag"), dict) else {}
            rag_line = ""
            if rag:
                if rag.get("ok"):
                    rag_line = (
                        f"\n· RAG `kb_giao_duc`: +{rag.get('chunks_added', 0)} chunks"
                        f" ({rag.get('batches', 0)} batch)"
                    )
                else:
                    err = str(rag.get("error") or (rag.get("errors") or [""])[0] or "lỗi")
                    rag_line = f"\n· RAG: thất bại — {err[:160]}"
            msg = (
                "✅ *Import SGK xong*\n"
                f"· File: `{result.get('source') or name}`\n"
                f"· Lớp {result.get('grade')} · {mon}\n"
                f"· Workspace: `{result.get('workspace')}`\n"
                f"· Mode: {result.get('mode')}\n"
                f"· Mục/chương (##): {result.get('chapters')}\n"
                f"· Ký tự markdown: {result.get('chars')}\n"
                f"· Lưu: `{result.get('path')}`"
                f"{rag_line}"
            )
            note = str(result.get("note") or result.get("warning") or "").strip()
            if note:
                msg += f"\n· Ghi chú: {note[:300]}"
            notify_admin(msg)
        except Exception:
            pass
        return result

    @router.get("/api/teacher/memory")
    async def teacher_memory_get(
        workspace: str = Query(...),
        student: str = Query(default="default"),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_workspace as tw
        return {"ok": True, "text": tw.memory_get(workspace, student)}

    @router.get("/api/teacher/rubric")
    async def teacher_rubric(
        subject: str = Query(default="van"),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_assess as ta
        return {"ok": True, "subject": subject, "text": ta.format_rubric_help(subject)}

    @router.get("/api/teacher/english/skills")
    async def english_skills(
        grade: int = Query(default=5),
        authorization: str | None = Header(default=None),
    ):
        """Map kỹ năng/topic Tiếng Anh theo lớp (UI gợi ý)."""
        require_admin(authorization)
        from services.agent import teacher_english as te
        return {"ok": True, **te.english_skill_map(grade)}

    # ── Parent dashboard ──────────────────────────────────────────────────
    @router.get("/api/teacher/dashboard")
    async def teacher_dashboard(
        workspace: str = Query(default=""),
        student: str = Query(default=""),
        weeks: int = Query(default=4),
        authorization: str | None = Header(default=None),
    ):
        """Dashboard PH: weak topics theo tuần + adaptive."""
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        return tc.parent_dashboard(
            workspace_id=workspace, student_key=student, weeks=weeks,
        )

    # ── Lessons (text + TTS) ──────────────────────────────────────────────
    @router.get("/api/teacher/lessons")
    async def lessons_list(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        return {"ok": True, "rows": tc.list_lessons()}

    @router.post("/api/teacher/lessons")
    async def lessons_create(
        body: LessonIn,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        if not (body.body_text or "").strip():
            from fastapi import HTTPException
            raise HTTPException(400, "Cần body_text (nội dung bài cho HS)")
        lesson = tc.create_lesson(
            title=body.title or "Bài học",
            body_text=body.body_text,
            tts_script=body.tts_script,
            grade=body.grade,
            subject=body.subject,
            workspace_id=body.workspace_id,
            student_key=body.student_key,
        )
        return {"ok": True, "lesson": lesson}

    @router.get("/api/teacher/lessons/{lesson_id}")
    async def lessons_get(
        lesson_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        from fastapi import HTTPException
        lesson = tc.get_lesson(lesson_id)
        if not lesson:
            raise HTTPException(404, "Không thấy bài học")
        return {"ok": True, "lesson": lesson}

    @router.delete("/api/teacher/lessons/{lesson_id}")
    async def lessons_delete(
        lesson_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        from fastapi import HTTPException
        r = tc.delete_lesson(lesson_id)
        if not r.get("ok"):
            raise HTTPException(404, str(r.get("error") or "Xóa thất bại"))
        return r

    # ── Assignments ───────────────────────────────────────────────────────
    @router.get("/api/teacher/assignments")
    async def assignments_list(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        return {"ok": True, "rows": tc.list_assignments()}

    @router.post("/api/teacher/assignments")
    async def assignments_create(
        body: AssignmentIn,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        asg = await run_in_threadpool(
            lambda: tc.create_assignment(
                title=body.title,
                grade=body.grade,
                subject=body.subject,
                topic=body.topic,
                workspace_id=body.workspace_id,
                n=body.n,
                difficulty=body.difficulty,
                student_key=body.student_key,
                lesson_id=body.lesson_id,
                questions=body.questions,
                from_roadmap=body.from_roadmap,
            )
        )
        return {"ok": True, "assignment": asg}

    @router.delete("/api/teacher/assignments/{assignment_id}")
    async def assignments_delete(
        assignment_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        from fastapi import HTTPException
        r = tc.delete_assignment(assignment_id)
        if not r.get("ok"):
            raise HTTPException(404, str(r.get("error") or "Xóa thất bại"))
        return r

    # ── AI soạn ───────────────────────────────────────────────────────────
    @router.post("/api/teacher/ai/lesson")
    async def ai_lesson(
        body: AiLessonIn,
        authorization: str | None = Header(default=None),
    ):
        """AI soạn bài giảng (text + TTS). save=true → lưu luôn.

        topic trống + student_key / from_roadmap → lấy current_focus lộ trình.
        """
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        use_rm = bool(body.from_roadmap or body.student_key)
        if not (body.topic or "").strip() and not use_rm and not (body.notes or "").strip():
            from fastapi import HTTPException
            raise HTTPException(
                400,
                "Cần topic, hoặc chọn học sinh có lộ trình (from_roadmap)",
            )

        draft = await run_in_threadpool(
            lambda: tc.ai_draft_lesson(
                grade=body.grade,
                subject=body.subject,
                topic=body.topic,
                workspace_id=body.workspace_id,
                notes=body.notes,
                student_key=body.student_key,
                from_roadmap=body.from_roadmap or use_rm,
            )
        )
        lesson = None
        if body.save and draft.get("ok"):
            lesson = tc.create_lesson(
                title=str(draft.get("title") or "Bài học"),
                body_text=str(draft.get("body_text") or ""),
                tts_script=str(draft.get("tts_script") or ""),
                grade=int(draft.get("grade") or body.grade),
                subject=str(draft.get("subject") or body.subject),
                workspace_id=body.workspace_id,
                student_key=body.student_key,
            )
        return {"ok": True, "draft": draft, "lesson": lesson}

    @router.post("/api/teacher/ai/assignment")
    async def ai_assignment(
        body: AiAssignmentIn,
        authorization: str | None = Header(default=None),
    ):
        """AI/generator soạn đề bài tập. save=true → tạo assignment luôn.

        topic trống + student_key / from_roadmap → sinh theo current_focus.
        """
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        topic = (body.topic or "").strip()
        use_rm = bool(body.from_roadmap or (body.student_key and not topic))
        if not topic and not use_rm:
            from fastapi import HTTPException
            raise HTTPException(
                400,
                "Cần topic, hoặc bật from_roadmap / chọn HS có lộ trình",
            )

        draft = await run_in_threadpool(
            lambda: tc.ai_draft_assignment(
                grade=body.grade,
                subject=body.subject,
                topic=topic,
                n=body.n,
                difficulty=body.difficulty,
                workspace_id=body.workspace_id,
                notes=body.notes,
                use_ai=body.use_ai,
                student_key=body.student_key,
                from_roadmap=body.from_roadmap or use_rm,
            )
        )
        assignment = None
        if body.save and draft.get("ok"):
            topic_final = str(draft.get("topic") or topic or "ôn tập")
            assignment = tc.create_assignment(
                title=body.title or str(draft.get("title") or f"BT {topic_final}"),
                grade=int(draft.get("grade") or body.grade),
                subject=str(draft.get("subject") or body.subject),
                topic=topic_final,
                workspace_id=body.workspace_id,
                n=body.n,
                difficulty=str(draft.get("difficulty") or body.difficulty),
                student_key=body.student_key,
                lesson_id=body.lesson_id,
                questions=list(draft.get("questions") or []),
                from_roadmap=bool(
                    draft.get("from_roadmap") or body.from_roadmap or use_rm
                ),
            )
        return {"ok": True, "draft": draft, "assignment": assignment}

    @router.get("/api/teacher/students/{student_key}/focus")
    async def student_focus(
        student_key: str,
        subject: str = Query(default="toan"),
        grade: int = Query(default=0),
        authorization: str | None = Header(default=None),
    ):
        """current_focus lộ trình — dùng UI sinh bài theo lộ trình."""
        require_admin(authorization)
        from services.agent import teacher_path as tp
        return tp.current_focus(student_key, subject, grade=grade, ensure=False)

    @router.get("/api/teacher/assignments/{assignment_id}")
    async def assignments_get(
        assignment_id: str,
        student_view: bool = Query(default=False),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        from fastapi import HTTPException
        asg = tc.get_assignment(assignment_id, for_student=student_view)
        if not asg:
            raise HTTPException(404, "Không thấy bài tập")
        return {"ok": True, "assignment": asg}

    @router.post("/api/teacher/assignments/{assignment_id}/submit")
    async def assignments_submit(
        assignment_id: str,
        body: SubmitIn,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        result = await run_in_threadpool(
            lambda: tc.submit_assignment(
                assignment_id,
                body.answers,
                student_key=body.student_key or "default",
                use_llm=body.use_llm,
            )
        )
        if not result.get("ok"):
            from fastapi import HTTPException
            raise HTTPException(400, str(result.get("error") or "submit failed"))
        return result

    @router.get("/api/teacher/assignments/{assignment_id}/submissions")
    async def assignments_submissions(
        assignment_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        return {
            "ok": True,
            "rows": tc.list_submissions(assignment_id),
            "assignment_id": assignment_id,
        }

    @router.get("/api/teacher/assignments/{assignment_id}/submissions/{student}")
    async def assignment_submission_detail(
        assignment_id: str,
        student: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        from fastapi import HTTPException
        s = tc.get_submission(assignment_id, student)
        if not s:
            raise HTTPException(404, "Chưa có bài nộp")
        return s

    @router.get("/api/teacher/adaptive")
    async def teacher_adaptive(
        workspace: str = Query(...),
        student: str = Query(default="default"),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_classroom as tc
        return {
            "ok": True,
            "level": tc.adaptive_level(workspace, student),
            "state": tc._load_adapt(workspace, student),
        }

    # ── Placement + roadmap (per-student independent) ─────────────────────
    @router.get("/api/teacher/pedagogy")
    async def teacher_pedagogy(
        subject: str = Query(default="toan"),
        authorization: str | None = Header(default=None),
    ):
        """Phương pháp dạy / placement theo môn (research-backed blurb)."""
        require_admin(authorization)
        from services.agent import teacher_path as tp
        return {"ok": True, "subject": subject, "pedagogy": tp.pedagogy_for(subject)}

    @router.get("/api/teacher/students")
    async def students_list(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.agent import teacher_path as tp
        return {"ok": True, "rows": tp.list_students()}

    @router.post("/api/teacher/students")
    async def students_upsert(
        body: StudentProfileIn,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_path as tp
        if not (body.student_key or "").strip():
            from fastapi import HTTPException
            raise HTTPException(400, "Cần student_key")
        p = tp.get_or_create_profile(
            body.student_key,
            display_name=body.display_name,
            grade=body.grade,
            notes=body.notes,
        )
        return {"ok": True, "profile": p}

    @router.get("/api/teacher/students/{student_key}")
    async def student_detail(
        student_key: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_path as tp
        return tp.student_dashboard(student_key)

    @router.delete("/api/teacher/students/{student_key}")
    async def student_delete(
        student_key: str,
        wipe_memory: bool = Query(default=True),
        authorization: str | None = Header(default=None),
    ):
        """Xóa hồ sơ HS độc lập (profile + placement + lộ trình + memory tùy chọn)."""
        require_admin(authorization)
        from services.agent import teacher_path as tp
        from fastapi import HTTPException
        r = tp.delete_student(student_key, wipe_memory=wipe_memory)
        if not r.get("ok"):
            raise HTTPException(404, str(r.get("error") or "Xóa thất bại"))
        return r

    @router.post("/api/teacher/placement/start")
    async def placement_start(
        body: PlacementStartIn,
        authorization: str | None = Header(default=None),
    ):
        """Tạo đề kiểm tra đầu vào (diagnostic multi-strand)."""
        require_admin(authorization)
        from services.agent import teacher_path as tp
        result = await run_in_threadpool(
            lambda: tp.start_placement(
                student_key=body.student_key,
                subject=body.subject,
                grade=body.grade,
                display_name=body.display_name,
                n_per_strand=body.n_per_strand,
            )
        )
        return result

    @router.post("/api/teacher/placement/{placement_id}/submit")
    async def placement_submit(
        placement_id: str,
        body: PlacementSubmitIn,
        authorization: str | None = Header(default=None),
    ):
        """Nộp placement → chấm + sinh lộ trình cá nhân."""
        require_admin(authorization)
        from services.agent import teacher_path as tp
        result = await run_in_threadpool(
            lambda: tp.submit_placement(
                placement_id,
                body.answers,
                student_key=body.student_key,
            )
        )
        if not result.get("ok"):
            from fastapi import HTTPException
            raise HTTPException(400, str(result.get("error") or "submit failed"))
        return result

    @router.get("/api/teacher/students/{student_key}/roadmap")
    async def student_roadmap(
        student_key: str,
        subject: str = Query(default="toan"),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_path as tp
        rm = tp.get_roadmap(student_key, subject)
        pl = tp.get_placement(student_key, subject)
        return {"ok": True, "roadmap": rm, "placement": pl}

    @router.post("/api/teacher/students/{student_key}/roadmap/rebuild")
    async def student_roadmap_rebuild(
        student_key: str,
        subject: str = Query(default="toan"),
        grade: int = Query(default=0),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_path as tp
        rm = tp.build_roadmap(student_key, subject, grade=grade)
        return {"ok": True, "roadmap": rm}

    @router.post("/api/teacher/students/{student_key}/roadmap/advance")
    async def student_roadmap_advance(
        student_key: str,
        body: RoadmapAdvanceIn,
        subject: str = Query(default="toan"),
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        from services.agent import teacher_path as tp
        r = tp.advance_roadmap_step(
            student_key, subject, body.step_id, done=body.done,
        )
        if not r.get("ok"):
            from fastapi import HTTPException
            raise HTTPException(400, str(r.get("error") or "advance failed"))
        return r

    return router
