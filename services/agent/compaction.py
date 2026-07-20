"""Conversation compaction — summarize older turns, keep a short tail.

When a user's in-memory/persisted history exceeds ``compact_after`` messages,
older turns are summarized into ``sessions.summary`` and only the recent tail
is kept. Failures are silent (chat continues with the untrimmed history).

Config (``agent_session``)::

    compact_after: int (default 20) — trigger when len(messages) >= this
    keep_tail: int (default 8) — messages kept after compaction
"""

from __future__ import annotations

import logging
from typing import Any

from services.agent import session as sess
from services.agent.runtime import call_model, content_of
from services.config import config

logger = logging.getLogger(__name__)

_COMPACT_MODEL_HINT = "cx/auto"


def _cfg() -> dict:
    raw = config.get().get("agent_session")
    return raw if isinstance(raw, dict) else {}


def compact_after() -> int:
    try:
        return max(6, int(_cfg().get("compact_after") or 20))
    except (TypeError, ValueError):
        return 20


def keep_tail() -> int:
    try:
        return max(2, int(_cfg().get("keep_tail") or 8))
    except (TypeError, ValueError):
        return 8


def _main_model() -> str:
    try:
        from services.agent import model_hints
        return model_hints.resolve("burst")
    except Exception:
        return str(config.get().get("telegram_ai_model") or "").strip() or _COMPACT_MODEL_HINT


def _format_turns(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for m in messages:
        role = "User" if m.get("role") == "user" else "Assistant"
        text = str(m.get("content") or "").strip()
        if not text:
            continue
        if len(text) > 600:
            text = text[:600] + "…"
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


def summarize(messages: list[dict[str, Any]], *, prev_summary: str = "") -> str:
    """Ask the main model for a short Vietnamese summary of older turns."""
    body = _format_turns(messages)
    if not body.strip():
        return prev_summary or ""
    prompt_parts = [
        "Tóm tắt ngắn gọn (tiếng Việt, gạch đầu dòng, tối đa 12 dòng) các điểm "
        "quan trọng trong đoạn hội thoại sau để trợ lý nhớ mạch chuyện sau này. "
        "Giữ: quyết định, sở thích, việc đang làm dở, nhắc hẹn, thiết bị/nhà. "
        "Bỏ: chào hỏi, filler, lặp lại.",
    ]
    if prev_summary.strip():
        prompt_parts.append(f"Tóm tắt cũ (gộp thêm nếu còn liên quan):\n{prev_summary.strip()}")
    prompt_parts.append(f"Hội thoại cần tóm tắt:\n{body}")
    resp = call_model(
        _main_model(),
        [{"role": "user", "content": "\n\n".join(prompt_parts)}],
        timeout=60,
        max_tokens=400,
        no_smart_home=True,
    )
    if resp.get("error"):
        logger.info("agent.compaction: summarize failed: %s", resp["error"])
        return prev_summary or ""
    text = content_of(resp).strip()
    return text[:2500] if text else (prev_summary or "")


def maybe_compact(user_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """If history is long, compact, persist, and return the new shorter list.

    Returns ``None`` when no compaction ran (caller should save history itself).
    On summarize failure returns ``None`` so the full history is kept.
    """
    if not sess.is_enabled() or not user_id:
        return None
    msgs = [m for m in (messages or []) if isinstance(m, dict)
            and m.get("role") in ("user", "assistant")]
    threshold = compact_after()
    tail_n = keep_tail()
    if len(msgs) < threshold or len(msgs) <= tail_n + 2:
        return None

    head = msgs[:-tail_n]
    tail = msgs[-tail_n:]
    prev = sess.load_summary(user_id)
    try:
        new_summary = summarize(head, prev_summary=prev)
    except Exception as exc:
        logger.warning("agent.compaction: %s", exc)
        return None

    if not new_summary:
        return None

    sess.set_summary(user_id, new_summary)
    sess.save_history(user_id, tail)
    logger.info(
        "agent.compaction: user=%s compacted %d→%d turns",
        user_id, len(msgs), len(tail),
    )
    return tail
