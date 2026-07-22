"""Text formatting & splitting for Telegram Bot API.

- Legacy Markdown (parse_mode=Markdown) — used by existing bot path
- HTML (recommended for LLM output)
- MarkdownV2 (strict escape)
- Chunk split under 4096 after entities

Refs: https://core.telegram.org/bots/api#formatting-options
"""

from __future__ import annotations

import html
import re
from typing import Iterable

from services.telegram.constants import (
    MAX_CAPTION_LENGTH,
    MAX_MESSAGE_LENGTH,
    SAFE_CAPTION_LENGTH,
    SAFE_MESSAGE_LENGTH,
)

_MD_BOLD_DOUBLE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_BOLD_UNDER_DOUBLE = re.compile(r"__(.+?)__", re.DOTALL)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MD_STRIKE = re.compile(r"~~(.+?)~~", re.DOTALL)
_MD_CODE_FENCE = re.compile(r"```(?:\w+)?\n?(.*?)```", re.DOTALL)
_MD_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_ITALIC_STAR = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")

# MarkdownV2 must-escape outside entities
_MDV2_SPECIAL = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


# ── Escape ───────────────────────────────────────────────────────────────────

def escape_html(text: str) -> str:
    """Escape for parse_mode=HTML (only <>&)."""
    return html.escape(text or "", quote=False)


def escape_markdown_v2(text: str) -> str:
    """Escape for parse_mode=MarkdownV2 (legacy Markdown is different)."""
    if not text:
        return ""
    return _MDV2_SPECIAL.sub(r"\\\1", text)


def escape_markdown_legacy(text: str) -> str:
    """Escape for parse_mode=Markdown (legacy): \\ _ * ` [ outside entities."""
    if not text:
        return ""
    out = []
    for ch in text:
        if ch in r"\_*`[":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


# ── LLM markdown → Telegram ──────────────────────────────────────────────────

def llm_to_legacy_markdown(text: str) -> str:
    """Convert common LLM markdown → Telegram legacy Markdown.

    **bold** → *bold*, drop headings, strip ~~strike~~.
    Does not guarantee parse success (LLM may still unbalance markers).
    """
    if not text:
        return text
    out = _MD_BOLD_DOUBLE.sub(r"*\1*", text)
    out = _MD_BOLD_UNDER_DOUBLE.sub(r"*\1*", out)
    out = _MD_HEADING.sub("", out)
    out = _MD_STRIKE.sub(r"\1", out)
    return out


def llm_to_html(text: str) -> str:
    """Best-effort LLM markdown → Telegram HTML.

    Protect structured spans as placeholders → escape plain text → reinject
    tags (so user ``<`` never becomes a real tag mid-parse).
    """
    if not text:
        return ""

    store: list[str] = []

    def _ph(html_snippet: str) -> str:
        store.append(html_snippet)
        return f"\x00PH{len(store) - 1}\x00"

    work = text
    # Fenced code
    work = _MD_CODE_FENCE.sub(
        lambda m: _ph(f"<pre>{escape_html((m.group(1) or '').rstrip())}</pre>"),
        work,
    )
    work = _MD_INLINE_CODE.sub(
        lambda m: _ph(f"<code>{escape_html(m.group(1) or '')}</code>"),
        work,
    )
    work = _MD_LINK.sub(
        lambda m: _ph(
            f'<a href="{escape_html(m.group(2) or "").replace(chr(34), "%22")}">'
            f"{escape_html(m.group(1) or '')}</a>"
        ),
        work,
    )
    work = _MD_HEADING.sub("", work)
    work = _MD_BOLD_DOUBLE.sub(
        lambda m: _ph(f"<b>{escape_html(m.group(1))}</b>"), work,
    )
    work = _MD_BOLD_UNDER_DOUBLE.sub(
        lambda m: _ph(f"<b>{escape_html(m.group(1))}</b>"), work,
    )
    work = _MD_STRIKE.sub(
        lambda m: _ph(f"<s>{escape_html(m.group(1))}</s>"), work,
    )
    work = _MD_ITALIC_STAR.sub(
        lambda m: _ph(f"<i>{escape_html(m.group(1))}</i>"), work,
    )

    # Escape residual plain (placeholders use \x00 which html.escape keeps)
    work = escape_html(work)
    # Placeholders themselves got escaped? \x00 is not special in html.escape.
    for i, snip in enumerate(store):
        work = work.replace(f"\x00PH{i}\x00", snip)
    return work


# ── Length helpers ────────────────────────────────────────────────────────────

def clip(text: str, limit: int = SAFE_MESSAGE_LENGTH, suffix: str = "…") -> str:
    t = text or ""
    if len(t) <= limit:
        return t
    keep = max(0, limit - len(suffix))
    return t[:keep] + suffix


def clip_caption(text: str, limit: int = SAFE_CAPTION_LENGTH) -> str:
    return clip(text, limit)


def split_message(
    text: str,
    *,
    limit: int = MAX_MESSAGE_LENGTH,
    prefer: int = SAFE_MESSAGE_LENGTH,
) -> list[str]:
    """Split long text into Telegram-safe chunks.

    Prefers paragraph/newline/space boundaries. Hard-splits if a single
    paragraph exceeds ``limit``.
    """
    t = (text or "").strip()
    if not t:
        return []
    if len(t) <= prefer:
        return [t]

    chunks: list[str] = []
    rest = t
    while rest:
        if len(rest) <= prefer:
            chunks.append(rest)
            break
        window = rest[:prefer]
        # Prefer double newline, then single, then space
        cut = window.rfind("\n\n")
        if cut < prefer // 3:
            cut = window.rfind("\n")
        if cut < prefer // 3:
            cut = window.rfind(" ")
        if cut < prefer // 3:
            cut = prefer
        piece = rest[:cut].rstrip()
        if not piece:
            piece = rest[:prefer]
            cut = prefer
        # Hard guarantee under MAX
        if len(piece) > limit:
            piece = piece[:limit]
            cut = len(piece)
        chunks.append(piece)
        rest = rest[cut:].lstrip("\n")
    return chunks or [clip(t, limit)]


def iter_chunks(text: str, **kwargs) -> Iterable[str]:
    return split_message(text, **kwargs)
