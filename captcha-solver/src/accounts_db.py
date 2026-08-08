"""SQLite storage for Google account credentials (email, password, TOTP secret).

Database is stored at /data/accounts.db (outside the repo).
DO NOT commit this file or its data to git.

`password` và `totp_secret` được mã hoá tại chỗ bằng AES-256-GCM khi
`VAULT_MASTER_KEY` có mặt (xem `vault.py`). Chưa đặt khoá thì vẫn ghi chữ
thường như cũ và có log cảnh báo — bắt buộc biến môi trường sẽ làm container
không lên được sau khi cập nhật.

Bản ghi cũ chưa mã hoá vẫn đọc được, và tự mã hoá ở lần GHI kế tiếp.
"""

from __future__ import annotations

import sqlite3
import os
from typing import Optional

from . import vault

_DB_PATH = os.environ.get("ACCOUNTS_DB", "/data/accounts.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    c = sqlite3.connect(_DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    c = _conn()
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            totp_secret TEXT NOT NULL DEFAULT '',
            label TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.commit()
    c.close()


def list_accounts() -> list[dict]:
    """Danh sách tài khoản — KHÔNG kèm mật khẩu lẫn hạt giống TOTP.

    Bản cũ ghi chú "without password for safety" nhưng vẫn trả `totp_secret`.
    Hạt giống TOTP không phải "mã 6 số": nó SINH RA mọi mã 6 số từ nay về sau,
    nên lộ nó là mất luôn yếu tố thứ hai chứ không chỉ một lần đăng nhập. Ở đây
    chỉ trả cờ `has_totp` — đủ cho giao diện, không đủ để mạo danh.
    """
    c = _conn()
    rows = c.execute(
        "SELECT id, email, totp_secret, label, created_at, updated_at FROM accounts ORDER BY email"
    ).fetchall()
    c.close()
    ra = []
    for r in rows:
        d = dict(r)
        d["has_totp"] = bool(str(d.pop("totp_secret", "") or "").strip())
        ra.append(d)
    return ra


def get_account(email: str) -> Optional[dict]:
    """Bản ghi đầy đủ, đã giải mã. Chỉ dùng cho luồng đăng nhập thật."""
    c = _conn()
    row = c.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    goc = str(d.get("email") or "")
    d["password"] = vault.giai_ma(d.get("password") or "", goc, "password")
    d["totp_secret"] = vault.giai_ma(d.get("totp_secret") or "", goc, "totp_secret")
    return d


def resolve_account(profile_or_email: str) -> Optional[dict]:
    """Tìm credential theo EMAIL chính xác, hoặc theo PROFILE NAME (google-benbap2011,
    chatgpt-benbap2011, claude-web-benbap2011...) bằng cách bỏ tiền tố dịch vụ rồi
    khớp localpart email. Nhờ vậy MỘT Google account đã lưu phục vụ MỌI profile dịch
    vụ cùng localpart → reuse không cần nhập lại mật khẩu."""
    if not profile_or_email:
        return None
    acct = get_account(profile_or_email)          # khớp email chính xác
    if acct:
        return acct
    name = profile_or_email.strip().lower()
    for pfx in ("google-", "chatgpt-web-", "chatgpt-", "gemini-web-", "gemini-",
                "claude-web-", "claude-", "codex-", "github-"):
        if name.startswith(pfx):
            name = name[len(pfx):]
            break
    name = name.replace("-", "").replace(".", "")
    if not name:
        return None
    for a in list_accounts():
        local = str(a.get("email") or "").split("@")[0].lower().replace(".", "").replace("-", "")
        if local == name:
            return get_account(a["email"])
    return None


def save_account(email: str, password: str, totp_secret: str = "", label: str = "") -> dict:
    """Insert or update an account. Returns the saved row (without password)."""
    # Mã hoá TRƯỚC khi chạm SQL — không để giá trị thường đi vào câu lệnh,
    # vì SQLite ghi cả câu lệnh vào WAL.
    mk = vault.ma_hoa(password, email, "password")
    tt = vault.ma_hoa(totp_secret, email, "totp_secret")
    c = _conn()
    existing = c.execute("SELECT id FROM accounts WHERE email = ?", (email,)).fetchone()
    if existing:
        c.execute(
            """UPDATE accounts
               SET password = ?, totp_secret = ?, label = ?, updated_at = CURRENT_TIMESTAMP
               WHERE email = ?""",
            (mk, tt, label, email),
        )
    else:
        c.execute(
            "INSERT INTO accounts (email, password, totp_secret, label) VALUES (?, ?, ?, ?)",
            (email, mk, tt, label),
        )
    c.commit()
    row = c.execute("SELECT id, email, totp_secret, label, created_at, updated_at FROM accounts WHERE email = ?", (email,)).fetchone()
    c.close()
    if not row:
        return {}
    d = dict(row)
    d["has_totp"] = bool(str(d.pop("totp_secret", "") or "").strip())
    return d


def delete_account(email: str) -> bool:
    c = _conn()
    # `rowcount` nằm trên CON TRỎ, không nằm trên kết nối. Bản cũ đọc
    # `c.rowcount` nên ném AttributeError ngay TRƯỚC `c.commit()` — lệnh xoá
    # không bao giờ được ghi xuống, tài khoản vẫn nguyên trong kho rồi lần đồng
    # bộ sau lại nạp về, trông y như hệ thống "tự thêm tài khoản free".
    # Đo trên máy chủ 05/08: xoá smarthomebenbap@gmail.com trả HTTP 500, tới
    # 19:06 tài khoản đó xuất hiện lại với "Thêm 1 free".
    try:
        cur = c.execute("DELETE FROM accounts WHERE email = ?", (email,))
        deleted = cur.rowcount > 0
        c.commit()
    finally:
        c.close()
    return deleted


# Initialize on import
init_db()
