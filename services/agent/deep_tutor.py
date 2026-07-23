"""Deep Tutor — native multi-step tutoring inside c2a (no external DeepTutor app).

Uses existing teacher SGK/RAG + LLM via runtime.call_model. Designed for
Telegram / Zalo / dashboard agent — same process as the gateway.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MODES = frozenset({"explain", "solve", "quiz", "review", "plan"})


def _sgk_context(grade: int | None, subject: str, topic: str, workspace: str) -> str:
    try:
        from services.agent import teacher as teach
        from services.agent import teacher_workspace as tw

        if not teach.is_enabled():
            return ""
        q = (topic or "").strip() or "tổng quan"
        g = int(grade or 0) or None
        sub = (subject or "toan").strip().lower()
        ws = (workspace or "").strip()
        hits = []
        if hasattr(teach, "search_sgk"):
            try:
                hits = teach.search_sgk(
                    query=q, grade=g, subject=sub, workspace=ws, top_k=4,
                ) or []
            except TypeError:
                # older signature
                hits = []
        if not hits and hasattr(tw, "search"):
            try:
                hits = tw.search(q, workspace_id=ws or None, top_k=4) or []
            except Exception:
                hits = []
        if isinstance(hits, str):
            return hits[:4000]
        if isinstance(hits, list):
            parts = []
            for h in hits[:4]:
                if isinstance(h, dict):
                    parts.append(str(h.get("text") or h.get("content") or h)[:1200])
                else:
                    parts.append(str(h)[:1200])
            return "\n---\n".join(parts)[:4500]
    except Exception as exc:
        logger.warning("deep_tutor sgk: %s", exc)
    return ""


def _memory_context(workspace: str, student: str) -> str:
    try:
        from services.agent import teacher_workspace as tw
        ws = (workspace or "").strip()
        st = (student or "default").strip() or "default"
        if hasattr(tw, "get_memory"):
            mem = tw.get_memory(ws, st) if ws else None
            if mem:
                return json.dumps(mem, ensure_ascii=False)[:1500]
    except Exception:
        pass
    return ""


def run(
    *,
    question: str,
    mode: str = "explain",
    grade: int | None = None,
    subject: str = "toan",
    topic: str = "",
    workspace: str = "",
    student: str = "",
    channel: str = "",
) -> dict[str, Any]:
    """Run one deep-tutor turn. Returns {"text": ...}."""
    q = (question or "").strip()
    if not q:
        return {"text": "Anh/chị hỏi chủ đề / bài cần học giúp em nhé 📚"}

    mode_l = (mode or "explain").strip().lower()
    if mode_l not in _MODES:
        mode_l = "explain"

    sgk = _sgk_context(grade, subject, topic or q, workspace)
    mem = _memory_context(workspace, student)

    mode_instructions = {
        "explain": (
            "Giảng Socratic: hỏi–đáp ngắn, ví dụ gần gũi, KHÔNG dump lý thuyết. "
            "Chia bước nhỏ; cuối hỏi 1 câu kiểm tra hiểu."
        ),
        "solve": (
            "Giải bài từng bước (I do → We do). Che đáp án cuối đến khi HS thử. "
            "Chỉ ra misconception nếu có."
        ),
        "quiz": (
            "Ra 3–5 câu ngắn (đánh số). Ghi rõ đáp án ẩn dạng "
            "[ĐÁP ÁN ẨN: ...] để HS tự làm trước."
        ),
        "review": (
            "Ôn theo điểm yếu trong memory (nếu có). Tóm tắt + 2 bài luyện."
        ),
        "plan": (
            "Lập lộ trình học 1 tuần: mục tiêu, ngày 1–7, tài liệu SGK gợi ý."
        ),
    }

    system = (
        "Bạn là giáo viên AI của hệ thống ChatGPT2API (Deep Tutor nội bộ). "
        "Tiếng Việt rõ ràng, thân thiện. Không bịa số liệu SGK. "
        f"Chế độ: {mode_l}. {mode_instructions[mode_l]}"
    )
    user_parts = [
        f"Câu hỏi / yêu cầu HS: {q}",
        f"Lớp: {grade or '?'} | Môn: {subject or '?'} | Chủ đề: {topic or '?'}",
    ]
    if workspace:
        user_parts.append(f"Workspace: {workspace}")
    if mem:
        user_parts.append(f"Memory học sinh:\n{mem}")
    if sgk:
        user_parts.append(f"Ngữ cảnh KB/SGK (tham khảo, có thể không đủ):\n{sgk}")
    else:
        user_parts.append(
            "Không có đoạn KB SGK — giảng theo kiến thức chung, "
            "nói rõ đây không phải trích trang SGK."
        )

    try:
        from services.agent.branches import branch_model
        from services.agent.runtime import call_model, content_of

        model = branch_model("teacher", channel) or branch_model("default", channel)
        # fallback common models
        if not model:
            model = "cx/auto"
        resp = call_model(
            model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": "\n\n".join(user_parts)},
            ],
            timeout=120,
            max_tokens=1800,
        )
        if resp.get("error"):
            return {"text": f"Deep Tutor lỗi model ({resp['error']}). Thử lại giúp em nhé."}
        text = (content_of(resp) or "").strip()
        if not text:
            return {"text": "Em chưa soạn được bài — anh/chị hỏi lại cụ thể hơn nhé."}
        footer = (
            "\n\n— _Deep Tutor (c2a)_ · "
            f"mode=`{mode_l}` · có thể gọi `teacher_grade` / `teacher_memory` tiếp."
        )
        return {"text": text + footer}
    except Exception as exc:
        logger.warning("deep_tutor run: %s", exc)
        return {"text": f"Deep Tutor lỗi: {exc}"}
