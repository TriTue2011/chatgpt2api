"""Thông báo admin đa kênh — 3 loại rõ ràng:

1. ``account_log`` (📋) — mọi việc liên quan **provider / tài khoản**
   (Codex, ChatGPT, Claude, Gemini, free, refresh token, status, quota account…).
   Bật/tắt: account_log_notify_* + admin ``account_log_enabled`` (và 🔔).

2. ``system`` (🔔) — lỗi & cảnh báo **không** phải provider, **không** phải chat mới
   (lỗi model nhánh, vision, PDF, HA automation, blacklist…).
   Bật/tắt: telegram/zalo_notify_enabled + admin ``notify_enabled``
   (Zalo Cá Nhân: chỉ per-admin, không còn cờ kênh).

3. ``newchat`` (💬) — báo **chat/nhóm/user mới** (kèm tên bot, nhóm, user khi có).
   Bật/tắt: ``*_newchat_alert_enabled`` + admin ``newchat_alert_enabled``.
   Không dùng chung 🔔/📋.

Best-effort, không bao giờ raise.
"""
from __future__ import annotations

import re

from services.config import config

_ACCOUNT_LOG_KEYS = {
    "telegram": "account_log_notify_telegram",
    "zalo": "account_log_notify_zalo",
    "zalo_personal": "account_log_notify_zalo_personal",
}

# Heuristic: text provider → account_log (khi caller quên category).
# Tránh khớp nhầm "chatgpt2api LỖI" (tên app) — cần ngữ cảnh tài khoản.
_PROVIDER_HINT = re.compile(
    r"(?i)("
    r"📋|"
    r"provider\s*=|"
    r"\bprovider\b|"
    r"\bcodex\b|"
    r"\bclaude\b\s*[—\-]|"  # "Claude — profile"
    r"gemini[_\s]?(web|free|api)?\b.*?(account|tài|session|profile)|"
    r"chatgpt[_\s]?(free|web)?\b.*?(account|tài|email|token)|"
    r"opencode|providers?\.(codex|claude|gemini)|"
    r"refresh[_\s-]?token|sessionkey|session\s*key|"
    r"tài\s*khoản\s*(provider|codex|claude|gemini|chatgpt)|"
    r"account\s*(pool|status|log|recovery)|"
    r"khôi\s*phục|khoi\s*phuc|re-?login|onboard|"
    r"status\s*=\s*(active|disabled|error|limited)|"
    r"email\s*=\s*\S+@|"
    r"thêm\s+tài\s*khoản|xóa\s+tài\s*khoản|cập\s*nhật\s+tài\s*khoản"
    r")"
)

_NEWCHAT_HINT = re.compile(
    r"(?i)("
    r"🆕|"
    r"chat/nhóm\s*mới|nhóm\s*mới|chat\s*cá\s*nhân\s*mới|"
    r"thread\s*mới|báo\s*chat|"
    r"Chat\s*ID:|Thread\s*ID:|"
    r"chưa\s*cấp\s*phép|chưa\s*có\s*trong\s*danh\s*bạ|"
    r"Mã\s*danh\s*bạ"
    r")"
)


def _enabled(key: str, default: bool = True) -> bool:
    try:
        return bool(config.get().get(key, default))
    except Exception:
        return default


_ACCOUNT_UPDATE_LOG_KEYS = {
    "telegram": "account_update_log_notify_telegram",
    "zalo": "account_update_log_notify_zalo",
    "zalo_personal": "account_update_log_notify_zalo_personal",
}


def account_log_enabled(channel: str) -> bool:
    """Toggle log tài khoản provider theo kênh."""
    return _enabled(_ACCOUNT_LOG_KEYS.get(channel, "account_log_notify_enabled"), True)


def account_update_log_enabled(channel: str) -> bool:
    """Toggle log cập nhật tài khoản provider theo kênh."""
    return _enabled(_ACCOUNT_UPDATE_LOG_KEYS.get(channel, "account_update_log_notify_enabled"), True)


def classify_notify_category(text: str, category: str = "") -> str:
    """Chuẩn hóa category: account_log | account_update | system | newchat.

    Caller nên truyền đúng; heuristic chỉ vá khi category trống.
    """
    c = str(category or "").strip().lower()
    if c in {"account_update", "update_account"}:
        return "account_update"
    if c in {"account_log", "account", "provider", "log"}:
        if "Cập nhật tài khoản" in (text or ""):
            return "account_update"
        return "account_log"
    if c in {"newchat", "new_chat", "new-contact", "contact"}:
        return "newchat"
    if c in {"system", "error", "warn", "warning", "alert"}:
        return "system"
    t = text or ""
    # newchat trước (tin 🆕 có thể chứa "bot" nhưng không phải provider)
    if _NEWCHAT_HINT.search(t):
        return "newchat"
    if _PROVIDER_HINT.search(t):
        if "Cập nhật tài khoản" in t:
            return "account_update"
        return "account_log"
    return "system"


def notify_admin(text: str, *, category: str = "") -> None:
    """Gửi thông báo tới admin qua các kênh đang bật.

    category:
      - account_log → 📋 log provider
      - account_update → 🔄 log cập nhật tài khoản
      - system / "" → 🔔 lỗi & cảnh báo
      - newchat → 💬 chat/nhóm mới (thread ID)
    """
    cat = classify_notify_category(text, category)
    # Telegram
    if cat == "account_log":
        tg_ok = _enabled("telegram_notify_enabled") and account_log_enabled("telegram")
    elif cat == "account_update":
        tg_ok = _enabled("telegram_notify_enabled") and account_update_log_enabled("telegram")
    elif cat == "newchat":
        tg_ok = _enabled("telegram_notify_enabled")  # per-admin 💬 filter trong bot
    else:
        tg_ok = _enabled("telegram_notify_enabled")
    if tg_ok:
        try:
            from services.telegram_bot import notify_admin as _tg
            _tg(text, category=cat)
        except Exception:
            pass

    # Zalo Bot
    if cat == "account_log":
        zl_ok = _enabled("zalo_notify_enabled") and account_log_enabled("zalo")
    elif cat == "account_update":
        zl_ok = _enabled("zalo_notify_enabled") and account_update_log_enabled("zalo")
    else:
        zl_ok = _enabled("zalo_notify_enabled")
    if zl_ok:
        try:
            from services.zalo_bot import notify_admin as _zl
            _zl(text, category=cat)
        except Exception:
            pass

    # Zalo Cá Nhân
    if cat == "account_update":
        zp_ok = account_update_log_enabled("zalo_personal")
    else:
        zp_ok = True
    if zp_ok:
        try:
            from services.zalo_personal import notify_admin as _zp
            _zp(text, category=cat)
        except Exception:
            pass
