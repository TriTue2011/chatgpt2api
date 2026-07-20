"""API Giáo viên tiểu học — status, search, import PDF SGK, memory."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Header, Query, UploadFile
from fastapi.concurrency import run_in_threadpool

from api.support import require_admin


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
        """Copy seed SGK/workspace nếu thiếu file (không ghi đè file đã có)."""
        require_admin(authorization)
        from services.agent import teacher_workspace as tw

        tw._seeded = False  # type: ignore[attr-defined]
        tw._ensure_seeded()
        return {"ok": True, "kb": tw.status_public(), "workspaces": len(tw.list_workspaces())}

    @router.post("/api/teacher/import-sgk")
    async def teacher_import_sgk(
        file: UploadFile = File(...),
        grade: int = Form(...),
        subject: str = Form(...),
        mode: str = Form(default="append"),
        title: str = Form(default=""),
        authorization: str | None = Header(default=None),
    ):
        """Upload PDF SGK → markdown lớp 1–5 · toan|van|anh.

        mode=append|replace. PDF scan cần gateway OCR vision.
        """
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

    return router
