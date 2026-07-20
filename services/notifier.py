"""Thông báo admin đa kênh — gửi CẢ Telegram lẫn Zalo, mỗi kênh bật/tắt riêng.

Trước đây mọi nơi gọi thẳng `telegram_bot.notify_admin` (chỉ Telegram). Giờ tất
cả đi qua `notifier.notify_admin` để fan-out sang cả Zalo, có toggle riêng:
- `telegram_notify_enabled` (mặc định True)
- `zalo_notify_enabled` (mặc định True)

Log tài khoản provider (thêm/xóa, JWT/RT chết, các bước khôi phục T0–T3 của
ChatGPT free / Codex / Gemini web / Flow…) gọi với `category="account_log"` —
mỗi kênh có thêm toggle con riêng, fallback về key cũ
`account_log_notify_enabled` (config.get() đã chuẩn hóa sẵn):
- `account_log_notify_telegram`
- `account_log_notify_zalo`
- `account_log_notify_zalo_personal`

Best-effort, không bao giờ raise (thông báo hỏng không được làm gãy luồng chính).
"""
from __future__ import annotations

from services.config import config

_ACCOUNT_LOG_KEYS = {
    "telegram": "account_log_notify_telegram",
    "zalo": "account_log_notify_zalo",
    "zalo_personal": "account_log_notify_zalo_personal",
}


def _enabled(key: str) -> bool:
    try:
        return bool(config.get().get(key, True))
    except Exception:
        return True


def account_log_enabled(channel: str) -> bool:
    """Toggle log tài khoản provider theo kênh (telegram/zalo/zalo_personal)."""
    return _enabled(_ACCOUNT_LOG_KEYS.get(channel, "account_log_notify_enabled"))


def notify_admin(text: str, *, category: str = "") -> None:
    """Gửi thông báo tới admin qua các kênh đang bật.

    category="account_log" → mỗi kênh xét thêm toggle log tài khoản riêng
    (ngoài toggle thông báo tổng của kênh đó).
    """
    is_account_log = category == "account_log"
    # category truyền xuống từng kênh — mỗi BOT trong kênh còn toggle riêng
    # (notify_admin_enabled / account_log_enabled trên từng bot record).
    if _enabled("telegram_notify_enabled") and (
        not is_account_log or account_log_enabled("telegram")
    ):
        try:
            from services.telegram_bot import notify_admin as _tg
            _tg(text, category=category)
        except Exception:
            pass
    if _enabled("zalo_notify_enabled") and (
        not is_account_log or account_log_enabled("zalo")
    ):
        try:
            from services.zalo_bot import notify_admin as _zl
            _zl(text, category=category)
        except Exception:
            pass
    # Zalo Cá Nhân: tự kiểm tra zalo_personal_notify_enabled (mặc định TẮT)
    # + zalo_personal_admin_thread bên trong notify_admin.
    if not is_account_log or account_log_enabled("zalo_personal"):
        try:
            from services.zalo_personal import notify_admin as _zp
            _zp(text)
        except Exception:
            pass
