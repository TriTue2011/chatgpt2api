"""Telegram message emphasis (numbers / units / key facts).

Platform limits (Bot API regular messages):
  - Bold, italic, code — YES
  - Custom font / text color — NO

Settings hierarchy (most specific wins for *enabled*):
  admin_entry.emphasis_enabled  →  bot.emphasis_*  →  telegram_emphasis_* (channel)
"""

from __future__ import annotations

import re
from typing import Any

# Number with optional thousand sep / decimal, optional unit suffix
_NUM_UNIT = re.compile(
    r"(?<![*\w./@#])"
    r"("
    r"-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|"
    r"-?\d+(?:[.,]\d+)?"
    r")"
    r"("
    r"\s*(?:°C|℃|°F|%|kWh|Wh|kW|W|V|A|Ah|mA|lux|hPa|ppm|μg/m³|ug/m3|"
    r"phút|phut|giờ|gio|giây|giay|ms|s|kg|g|km|m|cm|mm|₫|đ|VND|USD|\$)"
    r")?"
    r"(?![\w*/])",
    re.IGNORECASE,
)

# Label: value  → bold the value (thông tin chính)
_KEY_VALUE = re.compile(
    r"(?m)^(\s*(?:[-*•]\s*)?(?:"
    r"Nhiệt\s*độ|Độ\s*ẩm|Độ\s*ẩm|Humidity|Temp(?:erature)?|"
    r"Trạng\s*thái|Status|Pin|Battery|Điện\s*áp|Dòng|Công\s*suất|"
    r"Áp\s*suất|Chất\s*lượng\s*KK|AQI|PM2\.?5|PM10|"
    r"Giá|Số\s*dư|Tổng|Còn\s*lại|Mức|"
    r"[A-ZÀ-Ỵ][\wÀ-ỹ ]{1,28}"
    r")\s*[:：]\s*)"
    r"(?![\*`*_])"
    r"([^\n*`]{1,80}?)"
    r"(\s*)$",
    re.IGNORECASE,
)

# Standalone status tokens
_STATUS = re.compile(
    r"(?<![*\w])("
    r"bật|tắt|mở|đóng|online|offline|bình\s*thường|cảnh\s*báo|"
    r"nguy\s*hiểm|tốt|xấu|trung\s*bình|on|off|open|closed|ok|lỗi|error"
    r")(?![\w*])",
    re.IGNORECASE,
)

_ALREADY_MD = re.compile(r"(\*\*.+?\*\*|`[^`]+`|__.+?__)", re.DOTALL)


def _cfg_get() -> dict[str, Any]:
    try:
        from services.config import config
        return config.get() or {}
    except Exception:
        return {}


def _style_of(v: object, default: str = "bold") -> str:
    s = str(v or default).strip().lower()
    return s if s in {"bold", "code", "bold_code"} else default


def channel_emphasis_settings(cfg: dict | None = None) -> dict[str, Any]:
    c = cfg if isinstance(cfg, dict) else _cfg_get()
    return {
        "enabled": bool(c.get("telegram_emphasis_enabled", True)),
        "numbers": bool(c.get("telegram_emphasis_numbers", True)),
        "units": bool(c.get("telegram_emphasis_units", True)),
        "key_info": bool(c.get("telegram_emphasis_key_info", True)),
        "style": _style_of(c.get("telegram_emphasis_style")),
    }


def bot_emphasis_defaults(bot: dict | None, cfg: dict | None = None) -> dict[str, Any]:
    """Bot-level defaults (used for non-admin chats + as inherit base)."""
    base = channel_emphasis_settings(cfg)
    if not isinstance(bot, dict):
        return base
    out = dict(base)
    if "emphasis_enabled" in bot:
        out["enabled"] = bool(bot.get("emphasis_enabled"))
    if "emphasis_numbers" in bot:
        out["numbers"] = bool(bot.get("emphasis_numbers"))
    if "emphasis_units" in bot:
        out["units"] = bool(bot.get("emphasis_units"))
    if "emphasis_key_info" in bot:
        out["key_info"] = bool(bot.get("emphasis_key_info"))
    if bot.get("emphasis_style"):
        out["style"] = _style_of(bot.get("emphasis_style"), out["style"])
    return out


def resolve_emphasis_settings(
    *,
    bot: dict | None = None,
    chat_id: str | int | None = None,
    cfg: dict | None = None,
) -> dict[str, Any]:
    """Settings for a send target: admin_entry override → bot → channel."""
    st = bot_emphasis_defaults(bot, cfg)
    cid = str(chat_id or "").strip()
    if not cid or not isinstance(bot, dict):
        return st
    try:
        from services.admin_workspace import admin_entries
        for e in admin_entries(bot):
            if str(e.get("chat_id") or "").strip() != cid:
                continue
            # Per-admin thread master switch (only *enabled*; style/flags from bot/channel)
            # Per-admin full settings (UI lưu đầy đủ trên mỗi entry)
            if "emphasis_enabled" in e:
                st["enabled"] = bool(e.get("emphasis_enabled"))
            if "emphasis_numbers" in e:
                st["numbers"] = bool(e.get("emphasis_numbers"))
            if "emphasis_units" in e:
                st["units"] = bool(e.get("emphasis_units"))
            if "emphasis_key_info" in e:
                st["key_info"] = bool(e.get("emphasis_key_info"))
            if e.get("emphasis_style"):
                st["style"] = _style_of(e.get("emphasis_style"), st["style"])
            break
    except Exception:
        pass
    return st


# Back-compat alias
def emphasis_settings(cfg: dict | None = None) -> dict[str, Any]:
    return channel_emphasis_settings(cfg)


def _wrap(fragment: str, style: str) -> str:
    frag = (fragment or "").strip()
    if not frag:
        return fragment or ""
    if style == "code":
        return f"`{frag}`"
    if style == "bold_code":
        return f"**`{frag}`**"
    return f"**{frag}**"


def emphasize_text(
    text: str,
    *,
    settings: dict | None = None,
    bot: dict | None = None,
    chat_id: str | int | None = None,
) -> str:
    """Wrap numbers / units / key facts. Pass bot+chat_id for per-admin toggle."""
    t = text or ""
    if not t:
        return t
    if settings is None:
        st = resolve_emphasis_settings(bot=bot, chat_id=chat_id)
    else:
        st = settings
    if not st.get("enabled"):
        return t
    if not (st.get("numbers") or st.get("units") or st.get("key_info")):
        return t
    style = str(st.get("style") or "bold")

    parts: list[str] = []
    pos = 0
    for m in _ALREADY_MD.finditer(t):
        if m.start() > pos:
            parts.append(_emphasize_plain(t[pos:m.start()], st, style))
        parts.append(m.group(0))
        pos = m.end()
    if pos < len(t):
        parts.append(_emphasize_plain(t[pos:], st, style))
    return "".join(parts)


def _emphasize_plain(plain: str, st: dict, style: str) -> str:
    if not plain:
        return plain
    out = plain

    if st.get("key_info"):
        def kv_repl(m: re.Match) -> str:
            label, val, tail = m.group(1), (m.group(2) or "").strip(), m.group(3) or ""
            if not val or val.startswith("**") or val.startswith("`"):
                return m.group(0)
            # Don't wrap ultra-long prose values
            if len(val) > 60:
                return m.group(0)
            return f"{label}{_wrap(val, style)}{tail}"

        out = _KEY_VALUE.sub(kv_repl, out)

        def st_repl(m: re.Match) -> str:
            return _wrap(m.group(1), style)

        out = _STATUS.sub(st_repl, out)

    if st.get("numbers") or st.get("units"):
        def num_repl(m: re.Match) -> str:
            num, unit = m.group(1) or "", m.group(2) or ""
            if unit and st.get("units"):
                return _wrap(f"{num}{unit}", style)
            if st.get("numbers"):
                return _wrap(f"{num}{unit}", style) if unit and st.get("units") else (
                    _wrap(num, style) + (unit or "")
                )
            return m.group(0)

        out = _NUM_UNIT.sub(num_repl, out)

    return out
