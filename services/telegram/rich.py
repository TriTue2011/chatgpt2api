"""Helpers for Bot API Rich Messages (10.1+).

Builds InputRichMessage payloads from simple markdown / plain text so the
gateway can opt into sendRichMessage / sendRichMessageDraft without hand-
writing full block trees every time.

Docs: https://core.telegram.org/bots/features#rich-messages
     https://core.telegram.org/bots/api#sendrichmessage

Note: field names follow Telegram's InputRichMessage schema. If Telegram
extends the schema, prefer raw dicts via TelegramClient.send_rich_message.
"""

from __future__ import annotations

import re
from typing import Any

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_UL = re.compile(r"^[-*]\s+(.*)$")
_OL = re.compile(r"^(\d+)[.)]\s+(.*)$")
_FENCE = re.compile(r"^```(\w+)?\s*$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")


def plain_paragraph(text: str) -> dict[str, Any]:
    return {
        "type": "paragraph",
        "text": _inline_rich_text(text),
    }


def heading_block(text: str, level: int = 1) -> dict[str, Any]:
    return {
        "type": "section_heading",
        "level": max(1, min(6, int(level))),
        "text": _inline_rich_text(text),
    }


def preformatted_block(code: str, language: str | None = None) -> dict[str, Any]:
    blk: dict[str, Any] = {
        "type": "preformatted",
        "text": code or "",
    }
    if language:
        blk["language"] = language
    return blk


def divider_block() -> dict[str, Any]:
    return {"type": "divider"}


def list_block(items: list[str], *, ordered: bool = False) -> dict[str, Any]:
    return {
        "type": "list",
        "ordered": bool(ordered),
        "items": [
            {"text": _inline_rich_text(it)} for it in items if str(it).strip()
        ],
    }


def thinking_block(text: str = "…") -> dict[str, Any]:
    """InputRichBlockThinking — useful while streaming drafts."""
    return {
        "type": "thinking",
        "text": _inline_rich_text(text),
    }


def blockquote_block(text: str) -> dict[str, Any]:
    return {
        "type": "block_quotation",
        "text": _inline_rich_text(text),
    }


def table_block(
    headers: list[str],
    rows: list[list[str]],
) -> dict[str, Any]:
    """Simple table → InputRichBlockTable-ish structure."""
    head_cells = [{"text": _inline_rich_text(h)} for h in headers]
    body = []
    for row in rows:
        body.append([{"text": _inline_rich_text(c)} for c in row])
    return {
        "type": "table",
        "header": head_cells,
        "rows": body,
    }


def input_rich_message(
    *,
    markdown: str | None = None,
    blocks: list[dict] | None = None,
    parse_mode: str | None = "markdown",
) -> dict[str, Any]:
    """Build InputRichMessage.

    Prefer ``markdown`` (GFM-ish) when the client supports rich markdown
    field; also always attach structured ``blocks`` when we can parse them
    so either path works as the API evolves.
    """
    msg: dict[str, Any] = {}
    if markdown is not None:
        # API accepts markdown/html content on InputRichMessage (10.1+)
        key = "markdown" if (parse_mode or "").lower().startswith("mark") else "html"
        msg[key] = markdown
    if blocks is not None:
        msg["blocks"] = blocks
    elif markdown:
        msg["blocks"] = markdown_to_blocks(markdown)
    return msg


def markdown_to_blocks(text: str) -> list[dict[str, Any]]:
    """Coarse GFM → list of rich blocks (paragraph / heading / list / code)."""
    if not text:
        return []
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[dict[str, Any]] = []
    i = 0
    para: list[str] = []
    list_items: list[str] = []
    list_ordered = False

    def flush_para() -> None:
        nonlocal para
        if para:
            blocks.append(plain_paragraph("\n".join(para).strip()))
            para = []

    def flush_list() -> None:
        nonlocal list_items, list_ordered
        if list_items:
            blocks.append(list_block(list_items, ordered=list_ordered))
            list_items = []
            list_ordered = False

    while i < len(lines):
        line = lines[i]
        fm = _FENCE.match(line.strip())
        if fm:
            flush_para()
            flush_list()
            lang = fm.group(1) or None
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not _FENCE.match(lines[i].strip()):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1  # closing fence
            blocks.append(preformatted_block("\n".join(code_lines), lang))
            continue

        if not line.strip():
            flush_para()
            flush_list()
            i += 1
            continue

        hm = _HEADING.match(line)
        if hm:
            flush_para()
            flush_list()
            blocks.append(heading_block(hm.group(2).strip(), len(hm.group(1))))
            i += 1
            continue

        um = _UL.match(line.strip())
        if um:
            flush_para()
            if list_items and list_ordered:
                flush_list()
            list_ordered = False
            list_items.append(um.group(1))
            i += 1
            continue

        om = _OL.match(line.strip())
        if om:
            flush_para()
            if list_items and not list_ordered:
                flush_list()
            list_ordered = True
            list_items.append(om.group(2))
            i += 1
            continue

        if line.strip().startswith(">"):
            flush_para()
            flush_list()
            q = line.strip().lstrip(">").strip()
            blocks.append(blockquote_block(q))
            i += 1
            continue

        if line.strip() in {"---", "***", "___"}:
            flush_para()
            flush_list()
            blocks.append(divider_block())
            i += 1
            continue

        flush_list()
        para.append(line)
        i += 1

    flush_para()
    flush_list()
    return blocks or [plain_paragraph(text)]


def _inline_rich_text(text: str) -> Any:
    """Minimal rich text: plain string or list of spans.

    Telegram RichText accepts nested structures; we emit a simple string when
    no markers, else a list of {type,text} / string parts for bold/code.
    """
    s = text or ""
    if not _BOLD.search(s) and not _CODE.search(s):
        return s

    parts: list[Any] = []
    pos = 0
    # Combined scan
    pattern = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
    for m in pattern.finditer(s):
        if m.start() > pos:
            parts.append(s[pos:m.start()])
        if m.group(1) is not None:
            parts.append({"type": "bold", "text": m.group(1)})
        else:
            parts.append({"type": "code", "text": m.group(2)})
        pos = m.end()
    if pos < len(s):
        parts.append(s[pos:])
    return parts if parts else s


def draft_stream_id(*parts: Any) -> int:
    """Stable positive int draft_id from chat/message keys (31-bit)."""
    h = 0
    for p in parts:
        h = (h * 131 + hash(str(p))) & 0x7FFFFFFF
    return h or 1
