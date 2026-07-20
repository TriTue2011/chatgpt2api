"""SuperContext — deterministic preflight context for the first turn.

On the first assistant-less turn of a conversation, assemble a bounded
context bundle (wiki hits, memory lines, user profile, recent session
summary) and inject it into the system prompt so the model is not cold.

No LLM scout (cost + latency); pure retrieval. Fail-open on any error.

Config (``agent_super_context``)::

    enabled: bool (default True)
    max_chars: int (default 1800)
    wiki_hits: int (default 4)
    memory_lines: int (default 6)
    history_hits: int (default 3)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from services.config import config

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[\wÀ-ỹ]{2,}", re.UNICODE)
_STOP = {
    "anh", "chị", "em", "của", "là", "có", "không", "cho", "với", "và",
    "the", "and", "for", "you", "me", "please", "ơi", "ạ", "nhé", "giúp",
    "làm", "được", "rồi", "này", "kia", "thế", "nào", "gì", "sao", "vậy",
}


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_super_context")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def max_chars() -> int:
    try:
        return max(400, int(_cfg().get("max_chars") or 1800))
    except (TypeError, ValueError):
        return 1800


def wiki_hits() -> int:
    try:
        return max(1, min(10, int(_cfg().get("wiki_hits") or 4)))
    except (TypeError, ValueError):
        return 4


def memory_lines() -> int:
    try:
        return max(1, min(20, int(_cfg().get("memory_lines") or 6)))
    except (TypeError, ValueError):
        return 6


def history_hits() -> int:
    try:
        return max(0, min(10, int(_cfg().get("history_hits") or 3)))
    except (TypeError, ValueError):
        return 3


def is_first_turn(history: list[dict[str, Any]] | None) -> bool:
    """True when there is no prior assistant message in this session tail."""
    if not history:
        return True
    return not any(
        (m.get("role") or "") == "assistant"
        for m in history
        if isinstance(m, dict)
    )


def _keywords(text: str, *, limit: int = 10) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for w in _WORD_RE.findall((text or "").lower()):
        if w in _STOP or len(w) < 2:
            continue
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def _match_memory_lines(memory: str, words: list[str], *, limit: int) -> list[str]:
    if not memory or not words:
        # still return a few recent facts
        lines = [ln.strip() for ln in memory.splitlines() if ln.strip().startswith("-")]
        return lines[-limit:] if lines else []
    scored: list[tuple[int, str]] = []
    for ln in memory.splitlines():
        s = ln.strip()
        if not s.startswith("-"):
            continue
        low = s.lower()
        score = sum(1 for w in words if w in low)
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    if scored:
        return [s for _, s in scored[:limit]]
    lines = [ln.strip() for ln in memory.splitlines() if ln.strip().startswith("-")]
    return lines[-limit:]


def build_bundle(
    user_id: str,
    user_text: str,
    *,
    allow: set[str] | None = None,
) -> str:
    """Assemble prepared context. Empty string if nothing useful."""
    if not is_enabled():
        return ""
    words = _keywords(user_text)
    sections: list[str] = []
    budget = max_chars()

    # 1) Session summary (durable compaction)
    try:
        from services.agent import session as sess
        summary = (sess.load_summary(user_id) or "").strip()
        if summary:
            sections.append("### Tóm tắt hội thoại trước\n" + summary[:500])
    except Exception as exc:
        logger.debug("super_context: summary: %s", exc)

    # 2) User profile
    try:
        from services.agent import state
        prof = (state.load_user_profile(user_id) or "").strip()
        if prof:
            sections.append("### Hồ sơ người này\n" + prof[:400])
    except Exception as exc:
        logger.debug("super_context: profile: %s", exc)

    # 3) Memory facts matching keywords
    try:
        from services.agent import state
        mem = state.load_memory(limit_chars=6000)
        lines = _match_memory_lines(mem, words, limit=memory_lines())
        if lines:
            sections.append("### Trí nhớ liên quan\n" + "\n".join(lines)[:700])
    except Exception as exc:
        logger.debug("super_context: memory: %s", exc)

    # 4) Wiki search
    wiki_allowed = allow is None or "wiki" in allow or "memory" in allow
    # group name for wiki tools is likely under a group — check capabilities
    if allow is not None:
        try:
            from services.agent import capabilities as caps
            wiki_allowed = any(
                caps.group_of(n) in allow
                for n in ("wiki_search", "wiki_read", "ingest")
            )
        except Exception:
            wiki_allowed = True
    if wiki_allowed and words:
        try:
            from services.agent import wiki as w
            if w.is_enabled():
                hits = w.search(" ".join(words[:6]), limit=wiki_hits())
                if not hits:
                    hits = [
                        {"slug": h["slug"], "title": h["title"], "snippet": ""}
                        for h in w.list_recent(limit=min(3, wiki_hits()))
                    ]
                if hits:
                    lines = []
                    for h in hits:
                        lines.append(
                            f"- `{h.get('slug')}` {h.get('title')}: "
                            f"{(h.get('snippet') or '')[:120]}"
                        )
                    sections.append("### Wiki gợi ý\n" + "\n".join(lines)[:700])
        except Exception as exc:
            logger.debug("super_context: wiki: %s", exc)

    # 5) Calendar (ICS) upcoming events
    try:
        from services import calendar_connector as cal
        cal_block = cal.prompt_block()
        if cal_block.strip():
            sections.append(cal_block[:600])
    except Exception as exc:
        logger.debug("super_context: calendar: %s", exc)

    # 6) History search for this user
    if words and history_hits() > 0:
        try:
            from services.agent import session as sess
            if sess.is_enabled():
                hits = sess.search(user_id, " ".join(words[:5]), limit=history_hits())
                if hits:
                    lines = []
                    for h in hits:
                        role = h.get("role") or "?"
                        content = (h.get("content") or "")[:120]
                        lines.append(f"- ({role}) {content}")
                    sections.append("### Chat cũ liên quan\n" + "\n".join(lines)[:500])
        except Exception as exc:
            logger.debug("super_context: history: %s", exc)

    if not sections:
        return ""

    body = "\n\n".join(sections)
    if len(body) > budget:
        body = body[: budget - 20] + "\n…"
    return (
        "## Ngữ cảnh chuẩn bị (super context — chỉ tham khảo)\n"
        "Đã quét wiki/trí nhớ/hội thoại trước khi trả lời. "
        "Không bịa thêm; nếu không liên quan thì bỏ qua.\n\n"
        + body
    )


def maybe_attach(
    system_prompt: str,
    user_id: str,
    user_text: str,
    history_before: list[dict[str, Any]] | None,
    *,
    allow: set[str] | None = None,
) -> str:
    """If first turn, append super-context block to system prompt."""
    try:
        if not is_enabled() or not is_first_turn(history_before):
            return system_prompt
        bundle = build_bundle(user_id, user_text, allow=allow)
        if not bundle.strip():
            return system_prompt
        return (system_prompt or "").rstrip() + "\n\n" + bundle
    except Exception as exc:
        logger.warning("super_context: attach failed: %s", exc)
        return system_prompt
