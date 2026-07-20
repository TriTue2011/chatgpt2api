"""SQLite storage for Google account credentials (email, password, TOTP secret).

Database is stored at /data/accounts.db (outside the repo).
DO NOT commit this file or its data to git.
"""

from __future__ import annotations

import sqlite3
import os
from typing import Optional

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
    """Return all saved accounts (without password for safety)."""
    c = _conn()
    rows = c.execute(
        "SELECT id, email, totp_secret, label, created_at, updated_at FROM accounts ORDER BY email"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_account(email: str) -> Optional[dict]:
    """Get full account including password."""
    c = _conn()
    row = c.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
    c.close()
    return dict(row) if row else None


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
    c = _conn()
    existing = c.execute("SELECT id FROM accounts WHERE email = ?", (email,)).fetchone()
    if existing:
        c.execute(
            """UPDATE accounts
               SET password = ?, totp_secret = ?, label = ?, updated_at = CURRENT_TIMESTAMP
               WHERE email = ?""",
            (password, totp_secret, label, email),
        )
    else:
        c.execute(
            "INSERT INTO accounts (email, password, totp_secret, label) VALUES (?, ?, ?, ?)",
            (email, password, totp_secret, label),
        )
    c.commit()
    row = c.execute("SELECT id, email, totp_secret, label, created_at, updated_at FROM accounts WHERE email = ?", (email,)).fetchone()
    c.close()
    return dict(row) if row else {}


def delete_account(email: str) -> bool:
    c = _conn()
    c.execute("DELETE FROM accounts WHERE email = ?", (email,))
    deleted = c.rowcount > 0
    c.commit()
    c.close()
    return deleted


# Initialize on import
init_db()
