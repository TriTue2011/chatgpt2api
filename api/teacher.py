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
    # Lớp KHAI TAY — chỉ dùng khi công thức năm sinh không đúng (học lại, học
    # vượt, vào lớp 1 muộn). Để 0 = tự suy từ birth_year.
    grade: int = 0
    birth_year: int | None = None
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

    @router.get("/api/teacher/autofill")
    async def teacher_autofill_status(authorization: str | None = Header(default=None)):
        """Tiến độ tự tìm/nạp SGK + cài đặt định kỳ."""
        require_admin(authorization)
        from services import sgk_autofill_scheduler as sched
        from services.agent import sgk_autofill as af
        st = sched.status()
        st["combos"] = len(af.combos())
        return st

    @router.post("/api/teacher/autofill/start")
    async def teacher_autofill_start(
        payload: dict | None = None,
        authorization: str | None = Header(default=None),
    ):
        """Chạy NGAY (nền). ``skip_done=false`` để nạp đè thứ đã có."""
        require_admin(authorization)
        from services.agent import sgk_autofill as af
        body = payload or {}
        return af.start(
            kind=str(body.get("kind") or "sgk"),
            skip_done=bool(body.get("skip_done", True)),
            grades=body.get("grades") or None,
            subjects=body.get("subjects") or None,
        )

    @router.post("/api/teacher/autofill/stop")
    async def teacher_autofill_stop(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.agent import sgk_autofill as af
        return af.stop()

    @router.post("/api/teacher/autofill/settings")
    async def teacher_autofill_settings(
        payload: dict,
        authorization: str | None = Header(default=None),
    ):
        """Bật/tắt + chu kỳ (ngày) cho lần quét định kỳ."""
        require_admin(authorization)
        from services.config import config
        if "enabled" in payload:
            config.data["sgk_autofill_enabled"] = bool(payload.get("enabled"))
        if "interval_days" in payload:
            try:
                d = int(payload.get("interval_days") or 7)
            except (TypeError, ValueError):
                d = 7
            config.data["sgk_autofill_interval_days"] = max(1, min(365, d))
        config._save()
        from services import sgk_autofill_scheduler as sched
        return {"ok": True, "enabled": sched.is_enabled(),
                "interval_days": sched.interval_seconds() / 86400.0}

    @router.post("/api/teacher/import-url")
    async def teacher_import_url(
        payload: dict,
        authorization: str | None = Header(default=None),
    ):
        """Nạp SGK từ MỘT đường dẫn dán vào — nhận 3 dạng:

        1. Link đọc sách taphuan  (.../doc-sach/sgk-...)      → ảnh → PDF → RAG
        2. Link chi tiết taphuan  (.../chi-tiet-sach/...)     → tự tìm link đọc
        3. Link PDF trực tiếp     (http...pdf)                → tải thẳng

        Dạng 1 và 2 đi đường khối trang (rẻ ~20 lần); dạng 3 dùng lại
        sgk_fetch.fetch_and_ingest có sẵn (đã chặn SSRF qua net_guard).
        """
        require_admin(authorization)
        url = str(payload.get("url") or "").strip()
        grade = int(payload.get("grade") or 0)
        subject = str(payload.get("subject") or "").strip()
        mode = str(payload.get("mode") or "append")
        # Nạp tay: xoá bản PDF NGAY KHI RAG vào được. RAG hỏng thì giữ lại để nạp
        # lại, khỏi tải + OCR lần nữa. Truyền keep_pdf=false nếu muốn không lưu
        # một giây nào.
        drop_pdf = bool(payload.get("drop_pdf_on_rag_ok", True))
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "URL phải bắt đầu bằng http:// hoặc https://"}
        if not grade or not subject:
            return {"ok": False, "error": "thiếu lớp hoặc môn"}

        from services.agent import sgk_fetch as sf
        from services.agent import sgk_taphuan as tp

        # PHẢI chạy trong threadpool. Nạp một cuốn SGK là tải hàng trăm ảnh
        # trang rồi dựng PDF — hàng chục phút. Gọi thẳng trong `async def` là
        # chặn event loop, và chặn event loop thì CẢ gateway đứng hình: bot
        # câm, web UI treo, mọi kênh chết theo cho tới khi nạp xong.
        # (/api/teacher/import-sgk bên dưới vốn đã làm đúng như vậy.)
        # Loại tài liệu cho PDF NGOÀI taphuan. Trước đây cứng "sgk", nên dán link
        # một PDF bất kỳ — chương trình GDPT, đề thi, tài liệu tham khảo — cũng
        # vào kho SGK mang nhãn SGK, rồi bot trích nó như thể là sách học sinh.
        # Link taphuan thì KHÔNG lấy giá trị này: `doc_kind()` đọc được loại thật
        # từ slug, chính xác hơn người dùng chọn tay.
        kind_in = str(payload.get("kind") or "sgk").strip().lower()
        if kind_in not in ("sgk", "sgv", "vbt", "tap_huan", "other"):
            return {"ok": False,
                    "error": f"loại tài liệu không hợp lệ: {kind_in!r} "
                             "(sgk / sgv / vbt / tap_huan / other)"}

        def _run() -> dict:
            if "taphuan.nxbgd.vn" in url:
                readers = [url] if "/doc-sach/" in url else tp.reader_urls(url)
                if not readers:
                    return {"ok": False,
                            "error": "không tìm thấy link đọc sách trong trang này"}
                return tp.import_reader(readers[0], grade=grade, subject=subject,
                                        mode=mode, drop_pdf_on_rag_ok=drop_pdf)
            return sf.fetch_and_ingest(grade, subject, url, kind=kind_in,
                                       drop_pdf_on_rag_ok=drop_pdf)

        return await run_in_threadpool(_run)

    @router.get("/api/teacher/pages")
    async def teacher_pages_list(authorization: str | None = Header(default=None)):
        """Các quyển ĐÃ có bản đồ trang → ảnh (để giảng bài hiện ảnh đi cùng chữ).

        Chỉ trả metadata + số trang, KHÔNG kèm 186 URL mỗi quyển.
        """
        require_admin(authorization)
        from services.agent import sgk_taphuan as tp
        rows = await run_in_threadpool(tp.list_page_manifests)
        return {"ok": True, "total": len(rows), "books": rows}

    @router.get("/api/teacher/pages/{slug}")
    async def teacher_pages_one(
        slug: str,
        page: int = Query(default=0),
        authorization: str | None = Header(default=None),
    ):
        """Bản đồ trang của một quyển, hoặc ảnh của ĐÚNG một trang.

        `page` đếm theo thứ tự ảnh trong tệp — đúng con số trong mốc
        `<<<TRANG n>>>` của chữ đã nạp, nên giao diện giảng bài đọc chunk RAG ra
        số trang rồi hỏi thẳng ảnh tương ứng.
        """
        require_admin(authorization)
        from services.agent import sgk_taphuan as tp
        if page > 0:
            url = await run_in_threadpool(tp.page_image_url, slug, page)
            if not url:
                return {"ok": False, "error": f"không có ảnh trang {page} của {slug}"}
            return {"ok": True, "slug": slug, "page": page, "url": url}
        rec = await run_in_threadpool(tp.get_page_manifest, slug)
        if not rec:
            return {"ok": False, "error": f"chưa có bản đồ trang cho {slug}"}
        return {"ok": True, **rec}

    @router.get("/api/teacher/storage")
    async def teacher_storage(authorization: str | None = Header(default=None)):
        """PDF/markdown đang chiếm bao nhiêu — để quyết có xoá PDF hay không."""
        require_admin(authorization)
        from services.agent import sgk_bulk as sb
        # Threadpool: quét cây imports/ có thể hàng nghìn file.
        return await run_in_threadpool(sb.storage_report)

    @router.delete("/api/teacher/pdfs")
    async def teacher_purge_pdfs(
        grade: int = Query(default=0),
        authorization: str | None = Header(default=None),
    ):
        """Xoá bản PDF đã lưu. KHÔNG đụng markdown SGK và RAG.

        An toàn vì PDF chỉ là bản lưu để audit: markdown theo chương/bài và
        chunks trong Chroma đã tách khỏi nó từ lúc nạp. `grade=0` = mọi lớp.
        """
        require_admin(authorization)
        from services.agent import sgk_bulk as sb
        return await run_in_threadpool(sb.purge_pdfs, grade=grade or None)

    @router.get("/api/teacher/bulk")
    async def teacher_bulk_status(authorization: str | None = Header(default=None)):
        """Tiến độ nạp SGK hàng loạt."""
        require_admin(authorization)
        from services.agent import sgk_bulk as sb
        st = sb.read_state()
        return {"ok": True, "running": sb.is_running(), "state": st,
                "summary": sb.summary(st)}

    @router.get("/api/teacher/bulk/plan")
    async def teacher_bulk_plan(
        grades: str = Query(default=""),
        all_sets: bool = Query(default=True),
        authorization: str | None = Header(default=None),
    ):
        """Xem SẼ nạp những quyển nào (chưa nạp gì) — kiểm trước khi chạy thật.

        Mỗi lớp là một lượt cào danh mục taphuan nên gọi cả 12 lớp mất vài chục
        giây; vì vậy chạy trong threadpool và nên truyền `grades` khi thử.
        """
        require_admin(authorization)
        from services.agent import sgk_bulk as sb
        gs = [int(x) for x in grades.replace(" ", "").split(",") if x.isdigit()] or None
        items = await run_in_threadpool(sb.plan, gs, all_sets=all_sets)
        usable = [x for x in items if not x.get("skip")]
        return {"ok": True, "total": len(usable),
                "unrecognised": [x.get("slug") for x in items if x.get("skip")],
                "books": usable}

    @router.post("/api/teacher/bulk/start")
    async def teacher_bulk_start(
        payload: dict | None = None,
        authorization: str | None = Header(default=None),
    ):
        """Chạy NỀN việc nạp toàn bộ SGK. Trả ngay, theo dõi ở GET /bulk.

        Body: {grades?: [1,2], all_sets?: true, kinds?: ["sgk","sgv","vbt"],
               keep_pdf?: false, max_pages?: 0, skip_done?: true,
               dry_run?: false}

        `keep_pdf` mặc định FALSE ở đây (khác mặc định của hàm): nạp cả hai bộ
        sách là hàng chục GB PDF chỉ để audit, mà tra cứu đi qua .md + RAG.
        `skip_done` mặc định TRUE nên chạy lại là đi tiếp, không nạp lại quyển đã
        xong.
        `kinds` mặc định chỉ `sgk`. Thêm `sgv` (sách giáo viên — gợi ý soạn giảng)
        và `vbt` (vở bài tập — mẫu ra đề) sẽ nhân số tài liệu lên khoảng ba lần,
        mỗi loại vào một collection riêng.
        """
        require_admin(authorization)
        from services.agent import sgk_bulk as sb
        b = payload or {}
        gs = b.get("grades")
        kinds = b.get("kinds")
        return sb.start(
            grades=[int(x) for x in gs] if isinstance(gs, list) and gs else None,
            all_sets=bool(b.get("all_sets", True)),
            kinds=([str(x) for x in kinds] if isinstance(kinds, list) and kinds
                   else sb.DEFAULT_KINDS),
            keep_pdf=bool(b.get("keep_pdf", False)),
            max_pages=int(b.get("max_pages") or 0),
            skip_done=bool(b.get("skip_done", True)),
            dry_run=bool(b.get("dry_run", False)),
        )

    @router.post("/api/teacher/bulk/stop")
    async def teacher_bulk_stop(authorization: str | None = Header(default=None)):
        """Dừng SAU KHI xong quyển đang chạy (không cắt giữa quyển làm mất công)."""
        require_admin(authorization)
        from services.agent import sgk_bulk as sb
        return sb.stop()

    @router.get("/api/teacher/taphuan/books")
    async def teacher_taphuan_books(
        grade: int = Query(...),
        authorization: str | None = Header(default=None),
    ):
        """Danh mục SGK 1 lớp trên kho chính thức taphuan.nxbgd.vn."""
        require_admin(authorization)
        from services.agent import sgk_taphuan as tp
        # Threadpool: list_books cào web taphuan (nhiều giây tới cả phút), chặn
        # event loop là treo cả gateway.
        books = await run_in_threadpool(tp.list_books, int(grade))
        return {"grade": int(grade), "count": len(books), "books": books}

    @router.post("/api/teacher/taphuan/import")
    async def teacher_taphuan_import(
        payload: dict,
        authorization: str | None = Header(default=None),
    ):
        """Nạp SGK 1 lớp–môn thẳng từ taphuan (ảnh từng trang → PDF → RAG).

        ``dry_run=true`` chỉ liệt kê sẽ nạp gì. ``max_pages`` giới hạn số trang
        mỗi quyển — nên dùng khi chạy thử, vì mỗi trang là một lượt OCR vision.
        """
        require_admin(authorization)
        from services.agent import sgk_taphuan as tp
        # Threadpool: nạp cả quyển là tải ảnh từng trang + OCR, rất lâu. Chạy
        # thẳng trong `async def` sẽ chặn event loop và treo cả gateway.
        def _run() -> dict:
            return tp.import_book(
                int(payload.get("grade") or 0),
                str(payload.get("subject") or ""),
                max_pages=int(payload.get("max_pages") or 0),
                mode=str(payload.get("mode") or "append"),
                dry_run=bool(payload.get("dry_run")),
            )

        return await run_in_threadpool(_run)

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

        # Threadpool: cả hai hàm đều ĐỌC FILE .md của SGK (không lọc lớp–môn thì
        # quét cả 36 file, mỗi file có thể vài MB). Chạy thẳng trong `async def`
        # là chặn event loop → bot câm, web treo. Cùng loại với /imports bên dưới.
        if not (q or "").strip():
            return {"ok": True, "text": await run_in_threadpool(tw.list_sgk_index)}
        text = await run_in_threadpool(
            tw.search_sgk,
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

    @router.get("/api/teacher/subjects")
    async def teacher_subjects(authorization: str | None = Header(default=None)):
        """Danh mục môn: toàn bộ mã môn + môn của TỪNG LỚP.

        Có endpoint này để web UI không phải khai lại danh sách môn trong TS —
        khai hai nơi thì thêm môn ở backend mà dropdown vẫn thiếu.
        """
        require_admin(authorization)
        from services.agent import teacher_workspace as tw
        return {
            "ok": True,
            "subjects": [
                {"id": s, "label": tw.SUBJECT_LABEL.get(s, s)} for s in tw.SUBJECTS
            ],
            "by_grade": {str(g): list(tw.subjects_for(g)) for g in tw.GRADES},
        }

    @router.get("/api/teacher/imports")
    async def teacher_list_imports(
        grade: int = Query(default=0),
        subject: str = Query(default=""),
        limit: int = Query(default=40),
        authorization: str | None = Header(default=None),
    ):
        """Danh sách PDF đã import + markdown SGK theo lớp/môn.

        Không truyền grade/subject ⇒ trả markdown của CẢ 12 lớp × 3 môn.

        PHẢI chạy threadpool: `list_imports` đọc TOÀN VĂN từng file .md để đếm
        ký tự/số mục, và quét `rglob("*.pdf")` cả cây imports. Gọi không lọc là
        đọc 36 file SGK (mỗi file có thể vài MB) — chạy thẳng trong `async def`
        thì suốt lúc đó event loop bị chặn: bot câm, web treo, mọi kênh chết.
        Bản cũ luôn được gọi kèm filter nên chỉ đọc 1 file, đủ nhanh để không
        ai thấy — nhưng đó là may, không phải đúng.
        """
        require_admin(authorization)
        from services.agent import teacher_workspace as tw
        return await run_in_threadpool(
            tw.list_imports,
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
                drop_pdf_on_rag_ok=True,
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
            birth_year=body.birth_year,
        )
        # Trả kèm lớp đã suy để UI khỏi phải tính lại — và để người dùng thấy
        # NGAY là năm sinh vừa nhập ra lớp mấy, thay vì lưu xong mới biết sai.
        return {"ok": True, "profile": {**p, **tp.resolve_grade(p)}}

    @router.patch("/api/teacher/students/{student_key}")
    async def students_update(
        student_key: str,
        payload: dict,
        authorization: str | None = Header(default=None),
    ):
        """Sửa hồ sơ học sinh. `grade: null` = BỎ khai tay, quay về suy năm sinh.

        Cần PATCH riêng vì POST coi `grade=0` là "không truyền" nên không có
        cách nào xoá lớp khai tay.
        """
        require_admin(authorization)
        from fastapi import HTTPException

        from services.agent import teacher_path as tp
        allowed = {"display_name", "birth_year", "grade", "notes"}
        fields = {k: v for k, v in (payload or {}).items() if k in allowed}
        if not fields:
            raise HTTPException(400, f"không có trường nào để sửa (cho phép: "
                                     f"{', '.join(sorted(allowed))})")
        p = tp.update_profile(student_key, **fields)
        if p is None:
            raise HTTPException(404, f"không có học sinh '{student_key}'")
        return {"ok": True, "profile": {**p, **tp.resolve_grade(p)}}

    @router.delete("/api/teacher/students/{student_key}")
    async def students_delete(
        student_key: str,
        wipe_memory: bool = Query(default=True),
        authorization: str | None = Header(default=None),
    ):
        """Xoá hồ sơ + placement + lộ trình của MỘT học sinh.

        `wipe_memory=true` (mặc định) xoá luôn ghi chú/adaptive của học sinh đó
        trong các workspace — nếu không thì tạo lại trùng tên sẽ thừa hưởng dữ
        liệu của người cũ.
        """
        require_admin(authorization)
        from services.agent import teacher_path as tp
        return {"ok": True, **tp.delete_student(student_key, wipe_memory=wipe_memory)}

    @router.get("/api/teacher/school-year")
    async def teacher_school_year(authorization: str | None = Header(default=None)):
        """Năm học đang xét + cách suy lớp từ năm sinh (để UI giải thích cho user)."""
        require_admin(authorization)
        from services.agent import teacher_path as tp
        sy = tp.school_year_start()
        return {
            "ok": True,
            "school_year_start": sy,
            "school_year": f"{sy}–{sy + 1}",
            "cutoff_month": tp.SCHOOL_YEAR_CUTOFF_MONTH,
            "formula": "lớp = năm_học_bắt_đầu − năm_sinh − 5",
            "example": {"birth_year": sy - 6, "grade": 1},
        }

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
