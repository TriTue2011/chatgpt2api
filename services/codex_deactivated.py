"""Xử lý tài khoản Codex bị vô hiệu hóa (OpenAI `account_deactivated`).

Khi refresh nhiều tầng (T3 bulk onboard) gặp trang 'Lỗi xác thực'
(`error_code=account_deactivated`):

1. Đánh dấu account ``status='deactivated'`` → codex_error_recovery_scheduler
   NGỪNG thử lại (nó chỉ quét status ``error``/``disabled``).
2. Báo admin qua kênh ``account_log`` + hỏi: nhắn ``xóa <email>`` / ``giữ <email>``.
3. Admin nhắn ``xóa <email>`` → xóa CẢ dòng trong ``config.codex_auto_list``
   (lưu đăng nhập hàng loạt) LẪN account trong pool. ``giữ <email>`` → bỏ pending.

Pending lưu bền ở ``data/agent/codex_deactivated_pending.json`` (sống qua restart).
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from utils.log import logger

_lock = threading.RLock()


class CodexAccountDeactivated(Exception):
    """Raise trong luồng recovery để short-circuit khi phát hiện account_deactivated."""

    def __init__(self, email: str):
        super().__init__(f"account_deactivated: {email}")
        self.email = email


def _pending_file() -> Path:
    from services.config import DATA_DIR
    return Path(DATA_DIR) / "agent" / "codex_deactivated_pending.json"


def _load_pending() -> dict[str, Any]:
    try:
        p = _pending_file()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_pending(data: dict[str, Any]) -> None:
    try:
        p = _pending_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning({"event": "codex_deact_pending_save_failed", "error": str(exc)[:120]})


def _notify(text: str) -> None:
    """Fan-out tới admin bots (category account_log, cùng gating account_recovery)
    + ghi Log tài khoản trong UI."""
    try:
        from services.notifier import notify_admin
        notify_admin(text, category="account_log")
    except Exception as exc:
        logger.warning({"event": "codex_deact_notify_failed", "error": str(exc)[:120]})
    try:
        from services.log_service import LOG_TYPE_ACCOUNT, log_service
        log_service.add(
            LOG_TYPE_ACCOUNT,
            (text or "").replace("\n", " · ")[:240],
            {"source": "codex_deactivated", "notify_bots": False},
        )
    except Exception:
        pass


def _mark_deactivated(email: str, token: str) -> str:
    """Đặt status='deactivated' cho mọi account cùng email (và token nếu có).
    Trả 1 token đại diện (để xóa sau)."""
    found = ""
    try:
        from services.account_service import account_service
        em = (email or "").strip().lower()
        with account_service._lock:
            for tok, acc in list(account_service._accounts.items()):
                if not isinstance(acc, dict):
                    continue
                same_token = bool(token) and tok == token
                same_email = bool(em) and str(acc.get("email") or "").strip().lower() == em
                if same_token or same_email:
                    acc["status"] = "deactivated"
                    found = found or tok
            account_service._save_accounts()
    except Exception as exc:
        logger.warning({"event": "codex_deact_mark_failed", "email": email, "error": str(exc)[:120]})
    return found or token


def handle_deactivated(email: str, token: str = "", reason: str = "") -> None:
    """Đánh dấu deactivated + báo admin + đăng ký pending 'xóa/giữ' (idempotent)."""
    email = (email or "").strip()
    if not email:
        return
    tok = _mark_deactivated(email, token)
    with _lock:
        data = _load_pending()
        data[email.lower()] = {
            "email": email,
            "token": tok,
            "reason": str(reason)[:160],
            "ts": time.time(),
        }
        _save_pending(data)
    logger.warning({"event": "codex_account_deactivated", "email": email[:80], "reason": str(reason)[:120]})
    _notify(
        f"⛔ Codex — {email}\n"
        f"Tài khoản đã bị XÓA/VÔ HIỆU HÓA (account_deactivated) — không thể khôi phục.\n"
        f"Đã đánh dấu 'deactivated' để ngừng thử lại.\n\n"
        f"Xóa khỏi danh sách đăng nhập hàng loạt + pool để tránh lặp lại lỗi?\n"
        f"→ Trả lời:  xóa {email}\n"
        f"→ Hoặc:     giữ {email}"
    )


# "xóa a@b.com" | "giữ a@b.com" (dấu/không dấu, hoa/thường)
_CMD_RE = re.compile(
    r"^\s*(x[óo]a|xoa|delete|remove|gi[ữu]|giu|keep)\s+(\S+@\S+)\s*$",
    re.IGNORECASE,
)


def try_resolve_admin_reply(user_text: str) -> Optional[str]:
    """Nếu text là 'xóa <email>' / 'giữ <email>' KHỚP một pending deactivated →
    thực hiện xóa (pool + codex_auto_list) hoặc bỏ pending. Trả câu xác nhận;
    None nếu không phải lệnh của luồng này (để orchestrator xử lý bình thường)."""
    m = _CMD_RE.match(user_text or "")
    if not m:
        return None
    verb = m.group(1).lower()
    email = m.group(2).strip()
    key = email.lower()
    with _lock:
        data = _load_pending()
        entry = data.get(key)
        if not entry:
            return None  # không có pending cho email này → không phải lệnh của ta
        keep = verb in ("giữ", "giu", "keep")
        data.pop(key, None)
        _save_pending(data)

    if keep:
        _notify(f"↩️ Codex — {email}\nĐã GIỮ lại (không xóa). Vẫn ở trạng thái 'deactivated'.")
        return f"Đã giữ lại {email} (không xóa), vẫn đánh dấu deactivated."

    removed_pool = _delete_from_pool(email, str(entry.get("token") or ""))
    removed_list = _delete_from_auto_list(email)
    _notify(
        f"🗑️ Codex — {email}\n"
        f"Đã XÓA: pool={removed_pool} account · "
        f"codex_auto_list={'đã xóa dòng' if removed_list else 'không thấy dòng'}."
    )
    return (
        f"Đã xóa {email}: pool ({removed_pool} account) + danh sách đăng nhập hàng loạt "
        f"({'đã xóa' if removed_list else 'không thấy dòng'})."
    )


def _delete_from_pool(email: str, token: str) -> int:
    try:
        from services.account_service import account_service
        em = (email or "").strip().lower()
        toks: list[str] = []
        with account_service._lock:
            for tok, acc in list(account_service._accounts.items()):
                if not isinstance(acc, dict):
                    continue
                if (token and tok == token) or (em and str(acc.get("email") or "").strip().lower() == em):
                    toks.append(tok)
        if not toks:
            return 0
        res = account_service.delete_accounts(toks)
        if isinstance(res, dict):
            return int(res.get("removed") or len(toks))
        return len(toks)
    except Exception as exc:
        logger.warning({"event": "codex_deact_pool_del_failed", "email": email, "error": str(exc)[:120]})
        return 0


def _delete_from_auto_list(email: str) -> bool:
    try:
        from services.config import config
        raw = str((config.data or {}).get("codex_auto_list") or "")
        if not raw:
            return False
        em = (email or "").strip().lower()
        kept: list[str] = []
        removed = False
        for ln in raw.splitlines():
            first = ln.strip()
            if not first:
                kept.append(ln)
                continue
            parts = first.split("|") if "|" in first else first.split(":")
            if parts and parts[0].strip().lower() == em:
                removed = True
                continue
            kept.append(ln)
        if removed:
            config.update({"codex_auto_list": "\n".join(kept)})
        return removed
    except Exception as exc:
        logger.warning({"event": "codex_deact_list_del_failed", "email": email, "error": str(exc)[:120]})
        return False
