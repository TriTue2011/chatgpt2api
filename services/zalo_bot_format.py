"""Zalo **Bot Platform** sendMessage formatting (bot.zapps.me).

Docs: https://bot.zapps.me/docs/apis/sendMessage/

Hai cách rich text (không dùng đồng thời):

1. ``parse_mode`` = ``markdown`` | ``html``
   - Markdown: ``**đậm**``, ``*nghiêng*``, ``{red}…{/red}`` / orange / yellow / green,
     ``{big}``, ``{underline}``, list, heading…
   - HTML: ``<b>``, ``style="color:…"`` (palette đóng)

2. ``text_styles``: offset UTF-16 + ``st`` = mảng mã
   (``b``, ``i``, ``c_db342e``, ``f_18``…)

Telegram **không** có màu chữ. Zalo Bot **có** màu (đóng: đỏ/cam/vàng/xanh + bold).

Module này: nhấn mạnh số liệu (reuse telegram.emphasis) → markdown Zalo
(+ optional bọc màu quanh đoạn đậm).
"""

from __future__ import annotations

import re
from typing import Any

# Màu markdown Zalo Bot (parse_mode) — đúng docs bot.zapps.me
ZALO_BOT_MD_COLORS = frozenset({"red", "orange", "yellow", "green"})
# Cỡ chữ markdown: docs chỉ có {big}; text_styles có f_13/15/18/20
ZALO_BOT_MD_SIZES = frozenset({"normal", "big", "small", "large", "xlarge"})

# text_styles color tokens (docs table)
ZALO_BOT_STYLE_COLORS: dict[str, str] = {
    "red": "c_db342e",
    "orange": "c_f27806",
    "yellow": "c_f7b503",
    "green": "c_15a85f",
    "default": "c_050a19",
}
# Map UI size → markdown tag (parse_mode) + gợi ý f_* (text_styles)
ZALO_BOT_SIZE_MD: dict[str, str | None] = {
    "normal": None,
    "small": None,       # markdown không có small — giữ thường
    "big": "big",
    "large": "big",
    "xlarge": "big",
}

_BOLD_SPAN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def _pick_from_layers(
    bot: dict | None,
    chat_id: str | None,
    keys: tuple[str, ...],
    channel_keys: tuple[str, ...] = (),
) -> object | None:
    """admin entry → bot → channel config; trả value thô đầu tiên có key."""
    if bot and chat_id:
        try:
            from services.admin_workspace import admin_entry_for_chat
            e = admin_entry_for_chat(bot, chat_id)
            if e:
                for k in keys:
                    if k in e and e.get(k) is not None and str(e.get(k)).strip() != "":
                        return e.get(k)
        except Exception:
            pass
    if isinstance(bot, dict):
        for k in keys:
            if k in bot and bot.get(k) is not None and str(bot.get(k)).strip() != "":
                return bot.get(k)
    if channel_keys:
        try:
            from services.config import config
            c = config.get() or {}
            for k in channel_keys:
                if c.get(k) is not None and str(c.get(k)).strip() != "":
                    return c.get(k)
        except Exception:
            pass
    return None


def resolve_zalo_bot_color(bot: dict | None = None, chat_id: str | None = None) -> str | None:
    """Màu nhấn mạnh: admin → bot → channel. none/off → không tô màu."""
    def _norm(v: object) -> str | None:
        c = str(v or "").strip().lower()
        if not c or c in {"off", "none", "default", "0", "false"}:
            return None
        if c in ZALO_BOT_MD_COLORS:
            return c
        if c in {"gold"}:
            return "yellow"
        return None

    raw = _pick_from_layers(
        bot, chat_id,
        ("markdown_color", "emphasis_color", "zalo_markdown_color"),
        ("zalo_markdown_color", "zalo_bot_markdown_color", "markdown_color"),
    )
    if raw is not None:
        return _norm(raw)
    return "orange"  # mặc định cam (Zalo hỗ trợ màu; Tele không)


def resolve_zalo_bot_size(bot: dict | None = None, chat_id: str | None = None) -> str:
    """Cỡ chữ: normal | big (markdown {big}). admin → bot → channel."""
    def _norm(v: object) -> str:
        s = str(v or "").strip().lower()
        if s in {"", "off", "none", "default", "normal", "medium", "md"}:
            return "normal"
        if s in {"big", "large", "lg", "xlarge", "xl", "f_18", "f_20"}:
            return "big"
        if s in {"small", "sm", "f_13"}:
            return "normal"  # markdown không có small
        if s in ZALO_BOT_MD_SIZES:
            return "big" if s in {"big", "large", "xlarge"} else "normal"
        return "normal"

    raw = _pick_from_layers(
        bot, chat_id,
        ("markdown_size", "emphasis_size", "text_size", "font_size"),
        ("zalo_markdown_size", "zalo_bot_markdown_size"),
    )
    if raw is not None:
        return _norm(raw)
    return "normal"


def wrap_bold_with_md_style(
    text: str,
    *,
    color: str | None = None,
    size: str = "normal",
) -> str:
    """Bọc mỗi ``**…**`` bằng ``{color}`` / ``{big}`` (parse_mode markdown)."""
    if not text:
        return text or ""
    use_color = color if color in ZALO_BOT_MD_COLORS else None
    use_big = ZALO_BOT_SIZE_MD.get(size or "normal") == "big"
    if not use_color and not use_big:
        return text

    def repl(m: re.Match) -> str:
        inner = m.group(0)  # keep **...**
        if use_big:
            inner = f"{{big}}{inner}{{/big}}"
        if use_color:
            inner = f"{{{use_color}}}{inner}{{/{use_color}}}"
        return inner

    return _BOLD_SPAN.sub(repl, text)


def wrap_bold_with_md_color(text: str, color: str | None) -> str:
    """Back-compat: chỉ màu."""
    return wrap_bold_with_md_style(text, color=color, size="normal")


def emphasize_for_zalo_bot(
    text: str,
    *,
    bot: dict | None = None,
    chat_id: str | int | None = None,
) -> str:
    """Emphasis số/đơn vị + màu + cỡ chữ (Zalo Bot markdown)."""
    body = text or ""
    try:
        from services.telegram.emphasis import emphasize_text
        body = emphasize_text(body, bot=bot, chat_id=chat_id)
    except Exception:
        pass
    cid = str(chat_id) if chat_id is not None else None
    color = resolve_zalo_bot_color(bot, cid)
    size = resolve_zalo_bot_size(bot, cid)
    body = wrap_bold_with_md_style(body, color=color, size=size)
    return body


def build_send_message_payload(
    chat_id: str,
    text: str,
    *,
    bot: dict | None = None,
    rich: bool = True,
    max_len: int = 1990,
) -> list[dict[str, Any]]:
    """Một hoặc nhiều payload sendMessage (cắt ≤2000).

    rich=True → parse_mode=markdown + emphasis/color.
    rich=False → plain text (notify hệ thống / fallback).
    """
    raw = (text or "...").strip() or "..."
    if rich:
        body = emphasize_for_zalo_bot(raw, bot=bot, chat_id=chat_id)
        parse_mode: str | None = "markdown"
    else:
        body = raw
        parse_mode = None

    chunks = [body[i : i + max_len] for i in range(0, len(body), max_len)] or ["..."]
    out: list[dict[str, Any]] = []
    for ch in chunks[:6]:
        p: dict[str, Any] = {"chat_id": str(chat_id), "text": ch}
        if parse_mode:
            p["parse_mode"] = parse_mode
        out.append(p)
    return out


def styles_personal_to_bot_api(styles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Đổi styles Zalo personal (``st`` string ``c_…,b``) → Bot API (``st`` array)."""
    out: list[dict[str, Any]] = []
    for s in styles or []:
        if not isinstance(s, dict):
            continue
        st = s.get("st")
        if isinstance(st, list):
            tokens = [str(x) for x in st if x]
        else:
            tokens = [t for t in str(st or "").split(",") if t]
        if not tokens:
            continue
        out.append({
            "start": int(s.get("start") or 0),
            "len": int(s.get("len") or 0),
            "st": tokens,
        })
    return out
