"""Markdown → Zalo RTF styles (cùng mô hình Smarthome Black / HA zalo_bot).

Zalo personal API ``sendMessageByAccount`` nhận::

    {"msg": "plain", "styles": [{"start": 0, "len": 5, "st": "c_f27806,b"}], "ttl": 0}

- ``start`` / ``len`` tính theo UTF-16 (JS), không phải len Python thuần.
- Màu: red / orange / yellow / green (token ``c_…``) + bold.
"""
from __future__ import annotations

import re
from typing import Any

# Màu Zalo (giống HA integration smarthomeblack/zalo_bot)
ZALO_COLORS: dict[str, str] = {
    "red": "c_db342e",
    "orange": "c_f27806",
    "yellow": "c_f7b503",
    "green": "c_15a85f",
    "gold": "c_f7b503",  # alias gần yellow/gold
}

HEADING_STYLES: dict[int, str] = {
    1: "f_20,b",
    2: "f_18,b",
    3: "b",
    4: "f_13",
    5: "f_13",
    6: "f_13",
}


def _js_len(s: str) -> int:
    """Độ dài UTF-16 (JS) — emoji > U+FFFF tính 2."""
    n = 0
    for ch in s:
        n += 2 if ord(ch) >= 0x10000 else 1
    return n


def _py_to_js_pos(text: str, py_pos: int) -> int:
    return _js_len(text[: max(0, py_pos)])


def _resolve_color_token(color: str | None) -> str | None:
    """None/off/none → không ép màu; else token ``c_xxx,b``."""
    if not color:
        return None
    c = str(color).strip().lower()
    if c in ("", "off", "none", "default"):
        return None
    tok = ZALO_COLORS.get(c)
    if tok:
        return f"{tok},b"
    # passthrough raw zalo style
    return c


def markdown_to_zalo_message(
    text: str,
    *,
    color: str | None = "orange",
    size: str | None = "normal",
) -> dict[str, Any]:
    """Convert markdown-ish LLM text → {msg, styles} cho Zalo personal (zca-js).

    Hỗ trợ: **bold**, *italic*, ~~strike~~, ``code``, # headings, > quote, [t](url).
    size: normal | big → thêm ``f_18`` (TextStyle.Big trong zca-js).
    """
    if not text or not isinstance(text, str):
        return {"msg": str(text or ""), "styles": []}

    matched: list[tuple[int, int, str, str]] = []  # start, end, content, style_token
    stack: list[tuple[str, int, str]] = []  # marker, pos, kind
    i = 0
    n = len(text)

    while i < n:
        # link [text](url) → keep URL plain
        if text[i] == "[":
            close_br = text.find("](", i)
            if close_br != -1:
                close_pr = text.find(")", close_br + 2)
                if close_pr != -1:
                    url = text[close_br + 2 : close_pr]
                    matched.append((i, close_pr + 1, url, ""))
                    i = close_pr + 1
                    continue

        # *** bold+italic
        if i + 2 < n and text[i : i + 3] == "***":
            if stack and stack[-1][2] == "bi":
                _, open_pos, _ = stack.pop()
                content = text[open_pos + 3 : i]
                matched.append((open_pos, i + 3, content, "b,i"))
            else:
                stack.append(("***", i, "bi"))
            i += 3
            continue

        # headings
        if text[i] == "#" and (i == 0 or text[i - 1] == "\n"):
            level = 0
            j = i
            while j < n and text[j] == "#":
                level += 1
                j += 1
            if j < n and text[j] == " ":
                j += 1
                end = text.find("\n", j)
                if end < 0:
                    end = n
                content = text[j:end]
                st = HEADING_STYLES.get(level, "i")
                matched.append((i, end, content, st))
                i = end
                continue

        # blockquote
        if text[i] == ">" and (i == 0 or text[i - 1] == "\n"):
            j = i + 1
            if j < n and text[j] == " ":
                j += 1
            end = text.find("\n", j)
            if end < 0:
                end = n
            content = text[j:end]
            matched.append((i, end, content, "i"))
            i = end
            continue

        # inline code
        if text[i] == "`":
            j = text.find("`", i + 1)
            if j != -1:
                content = text[i + 1 : j]
                matched.append((i, j + 1, content, "i"))
                i = j + 1
                continue

        if i + 1 < n and text[i : i + 2] == "**":
            if stack and stack[-1][2] == "b":
                _, open_pos, _ = stack.pop()
                content = text[open_pos + 2 : i]
                matched.append((open_pos, i + 2, content, "b"))
            else:
                stack.append(("**", i, "b"))
            i += 2
            continue

        if i + 1 < n and text[i : i + 2] == "~~":
            if stack and stack[-1][2] == "s":
                _, open_pos, _ = stack.pop()
                content = text[open_pos + 2 : i]
                matched.append((open_pos, i + 2, content, "s"))
            else:
                stack.append(("~~", i, "s"))
            i += 2
            continue

        if i + 1 < n and text[i : i + 2] == "__":
            if stack and stack[-1][2] == "u":
                _, open_pos, _ = stack.pop()
                content = text[open_pos + 2 : i]
                matched.append((open_pos, i + 2, content, "u"))
            else:
                stack.append(("__", i, "u"))
            i += 2
            continue

        if text[i] == "*":
            if stack and stack[-1][2] == "i":
                _, open_pos, _ = stack.pop()
                content = text[open_pos + 1 : i]
                matched.append((open_pos, i + 1, content, "i"))
            else:
                stack.append(("*", i, "i"))
            i += 1
            continue

        i += 1

    if not matched:
        return {"msg": text, "styles": []}

    matched.sort(key=lambda m: m[0])
    parts: list[str] = []
    styles: list[dict[str, Any]] = []
    offset = 0
    last_end = 0
    for orig_start, orig_end, content, token in matched:
        parts.append(text[last_end:orig_start])
        out_start = orig_start - offset
        styles.append({"start": out_start, "len": len(content), "st": token})
        parts.append(content)
        offset += (orig_end - orig_start) - len(content)
        last_end = orig_end
    parts.append(text[last_end:])
    final_msg = "".join(parts)

    # Python pos → JS UTF-16
    for s in styles:
        frag = final_msg[s["start"] : s["start"] + s["len"]]
        s["start"] = _py_to_js_pos(final_msg, s["start"])
        s["len"] = _js_len(frag)

    # color + size override on bold (incl heading bold)
    # zca-js TextStyle: Bold=b, Orange=c_f27806, Big=f_18, Small=f_13
    override = _resolve_color_token(color)
    size_tok = None
    sz = str(size or "normal").strip().lower()
    if sz in {"big", "large", "xlarge", "lg", "xl", "f_18", "f_20"}:
        size_tok = "f_18"
    elif sz in {"small", "sm", "f_13"}:
        size_tok = "f_13"
    if override or size_tok:
        for s in styles:
            tokens = [t for t in (s["st"].split(",") if s["st"] else []) if t]
            is_boldish = "b" in tokens or any(t.startswith("f_") for t in tokens)
            if not is_boldish:
                continue
            new_tokens: list[str] = []
            for t in tokens:
                if t == "b" and override:
                    new_tokens.extend(x for x in override.split(",") if x)
                else:
                    new_tokens.append(t)
            if size_tok and size_tok not in new_tokens:
                new_tokens.append(size_tok)
            seen: set[str] = set()
            cleaned: list[str] = []
            for t in new_tokens:
                if t not in seen:
                    seen.add(t)
                    cleaned.append(t)
            s["st"] = ",".join(cleaned)

    styles = [s for s in styles if s.get("st")]
    return {"msg": final_msg, "styles": styles}


def config_markdown_color() -> str:
    """Màu mặc định từ config (top-level hoặc zalo_personal)."""
    try:
        from services.config import config
        c = config.get()
        zp = c.get("zalo_personal") if isinstance(c.get("zalo_personal"), dict) else {}
        for src in (zp, c):
            if not isinstance(src, dict):
                continue
            for key in ("markdown_color", "zalo_markdown_color"):
                v = str(src.get(key) or "").strip().lower()
                if v:
                    return v
        if c.get("zalo_markdown_enabled") is False:
            return "none"
    except Exception:
        pass
    return "orange"


def config_markdown_enabled() -> bool:
    try:
        from services.config import config
        c = config.get()
        zp = c.get("zalo_personal") if isinstance(c.get("zalo_personal"), dict) else {}
        for src in (zp, c):
            if not isinstance(src, dict):
                continue
            if "markdown_enabled" in src:
                v = src.get("markdown_enabled")
                if isinstance(v, str):
                    return v.strip().lower() in {"1", "true", "yes", "on"}
                return bool(v)
    except Exception:
        pass
    return True
