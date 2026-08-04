"""Nhật ký nhóm — lưu MỌI tin nhận được để tóm tắt / tìm "việc nhắc tới tôi".

Tách bạch với việc TRẢ LỜI: bot vẫn chỉ trả lời khi được tag, nhưng ghi lại mọi
tin nghe được (nếu phạm vi đó BẬT ghi). Chỉ chạy được ở kênh nghe được tin
không-tag (Zalo Cá Nhân; Telegram sau khi tắt privacy mode).

Nguyên tắc:
* **Mặc định TẮT.** Không phạm vi nào ghi cho tới khi chủ máy bật riêng
  (`chatlog_settings`). Lưu lời người khác nên phải opt-in.
* Hạn giữ / bật-tắt / nén đặt ĐỘC LẬP theo phạm vi, kế thừa HẸP thắng RỘNG
  (người → topic → nhóm → kênh → mặc định) — như «Lọc thread».
* Khoá theo NHÓM (`scope.khoa_nhat_ky`, bỏ người gửi) — sổ chung cả nhóm để tóm
  tắt được cả cuộc trò chuyện. Đọc đi theo kết nối bộ nhớ (`nhat_ky_doc_them`).
* Chỉ ghi CHỮ. Tự dọn theo ngày + trần số tin. Không raise (lỗi ghi ≠ mất tin
  của luồng chat).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR, config

_DB_PATH = Path(DATA_DIR) / "agent" / "chatlog.sqlite"
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

_MAC_DINH_NGAY = 30        # hạn giữ mặc định (khi phạm vi bật mà không nêu số ngày)
_TRAN_TIN = 20000          # trần số tin mỗi phạm vi (van an toàn)
_MENTION_ALL = "@all"

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    _TZ = timezone(timedelta(hours=7))


def _fold(s: str) -> str:
    from services.agent.vi_text import fold
    return fold(s)


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chatlog ("
            " id INTEGER PRIMARY KEY,"
            " scope TEXT NOT NULL,"       # scope.khoa_nhat_ky (cấp nhóm)
            " ts REAL NOT NULL,"
            " day TEXT NOT NULL,"          # YYYY-MM-DD giờ VN (lọc theo ngày)
            " sender_id TEXT,"
            " sender_name TEXT,"
            " text TEXT NOT NULL,"
            " text_fold TEXT,"             # bỏ dấu để khớp không phụ thuộc dấu
            " mentions_fold TEXT)"         # người-được-nhắc, đã bỏ dấu, cách nhau ' '
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chatlog_scope_day"
                     " ON chatlog(scope, day)")
        conn.commit()
        _conn = conn
    return _conn


# ── Cấu hình theo phạm vi (mặc định TẮT, kế thừa hẹp→rộng) ────────────────────

def _cac_khoa_cai_dat(kenh: str, chat: str, topic: str, user: str) -> list[str]:
    """Khoá cấu hình từ HẸP tới RỘNG (dừng ở khoá đầu tiên có bản ghi).

    'plat:chat#topic:user' → 'plat:chat#topic' → 'plat:chat:user' →
    'plat:chat' → 'plat'. (Không kèm bot/account cho v1 — chat id đủ phân biệt.)
    """
    ct = f"{chat}#{topic}" if topic else chat
    out: list[str] = []
    if user:
        if topic:
            out.append(f"{kenh}:{chat}#{topic}:{user}")
        out.append(f"{kenh}:{chat}:{user}")
    if topic:
        out.append(f"{kenh}:{chat}#{topic}")
    out.append(f"{kenh}:{chat}")
    out.append(kenh)
    # bỏ trùng, giữ thứ tự
    seen: set[str] = set()
    return [k for k in out if not (k in seen or seen.add(k))]


def cai_dat(kenh: str, chat: str, topic: str = "", user: str = "") -> dict:
    """Cấu hình ghi nhật ký hiệu lực cho một phạm vi. Mặc định TẮT.

    Trả {enabled, retention_days, compact}. Đọc `chatlog_settings` (dict khoá
    'plat:chat[#topic][:user]' → {enabled, retention_days, compact}).
    """
    mac_dinh = {"enabled": False, "retention_days": _MAC_DINH_NGAY, "compact": False}
    try:
        cfg = config.get().get("chatlog_settings")
    except Exception:
        cfg = None
    if not isinstance(cfg, dict) or not cfg:
        return mac_dinh
    for k in _cac_khoa_cai_dat(kenh, chat, topic, user):
        v = cfg.get(k)
        if isinstance(v, dict):
            try:
                rd = int(v.get("retention_days") if v.get("retention_days") is not None
                         else _MAC_DINH_NGAY)
            except (TypeError, ValueError):
                rd = _MAC_DINH_NGAY
            return {"enabled": bool(v.get("enabled", False)),
                    "retention_days": max(0, rd),
                    "compact": bool(v.get("compact", False))}
    return mac_dinh


# ── Ghi ──────────────────────────────────────────────────────────────────────

def _mentions_fold(text: str, mentions: list[str] | None) -> str:
    """Chuỗi người-được-nhắc đã bỏ dấu, cách nhau bởi ' ' để so khớp.

    Gồm: các mention nền tảng đưa vào (mentions), '@all' nếu tin tag cả nhóm, và
    các cụm '@tên' bắt được trong text. Bỏ dấu để "@Việt" khớp "viet".
    """
    toks: list[str] = []
    for m in (mentions or []):
        m = str(m or "").strip()
        if m:
            toks.append(_fold(m))
    low = (text or "").lower()
    if "@all" in low or "@mọi người" in low or _fold(low).find("@moi nguoi") >= 0:
        toks.append(_MENTION_ALL)
    for m in re.findall(r"@([\wÀ-ỹ][\wÀ-ỹ. ]{0,30})", text or ""):
        f = _fold(m).strip()
        if f:
            toks.append(f)
    # bỏ trùng
    seen: set[str] = set()
    return " ".join(t for t in toks if not (t in seen or seen.add(t)))


def ghi(user_id: str, *, sender_id: str = "", sender_name: str = "",
        text: str = "", mentions: list[str] | None = None) -> bool:
    """Ghi một tin vào nhật ký NẾU phạm vi này bật. Trả True nếu đã ghi.

    Không raise. Chỉ ghi CHỮ (text rỗng → bỏ qua).
    """
    text = (text or "").strip()
    if not text:
        return False
    try:
        from services.agent.scope import tach_khoa_phien, khoa_nhat_ky
        sc = tach_khoa_phien(user_id)
        if not sc.chat:
            return False
        st = cai_dat(sc.kenh, sc.chat, sc.topic, sc.actor)
        if not st["enabled"]:
            return False
        scope_key = khoa_nhat_ky(user_id)
        now = time.time()
        day = datetime.fromtimestamp(now, _TZ).strftime("%Y-%m-%d")
        with _lock:
            db = _db()
            db.execute(
                "INSERT INTO chatlog (scope, ts, day, sender_id, sender_name,"
                " text, text_fold, mentions_fold) VALUES (?,?,?,?,?,?,?,?)",
                (scope_key, now, day, str(sender_id or ""), str(sender_name or ""),
                 text[:4000], _fold(text)[:4000],
                 _mentions_fold(text, mentions)[:1000]),
            )
            _don(db, scope_key, st["retention_days"])
            db.commit()
        return True
    except Exception:
        return False  # không bao giờ làm chết luồng chat


def _don(db: sqlite3.Connection, scope_key: str, retention_days: int) -> None:
    """Xoá tin quá hạn ngày + quá trần số tin của phạm vi này."""
    if retention_days > 0:
        cutoff = (datetime.now(_TZ) - timedelta(days=retention_days)).strftime("%Y-%m-%d")
        db.execute("DELETE FROM chatlog WHERE scope=? AND day < ?", (scope_key, cutoff))
    rows = db.execute(
        "SELECT id FROM chatlog WHERE scope=? ORDER BY ts DESC LIMIT -1 OFFSET ?",
        (scope_key, _TRAN_TIN),
    ).fetchall()
    if rows:
        ids = [r[0] for r in rows]
        db.execute(f"DELETE FROM chatlog WHERE id IN ({','.join('?' * len(ids))})", ids)


# ── Đọc ──────────────────────────────────────────────────────────────────────

def _scopes_doc(user_id: str) -> list[str]:
    """Phạm vi nhật ký đọc được: của mình + mượn qua kết nối bộ nhớ."""
    from services.agent.scope import khoa_nhat_ky, nhat_ky_doc_them
    return [khoa_nhat_ky(user_id), *nhat_ky_doc_them(user_id)]


def _hom_nay() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def doc_ngay(user_id: str, day: str | None = None,
             limit: int = 500) -> list[dict[str, Any]]:
    """Tin trong nhật ký của một NGÀY (mặc định hôm nay), gồm phạm vi kết nối."""
    day = (day or _hom_nay()).strip()[:10]
    scopes = _scopes_doc(user_id)
    if not scopes:
        return []
    try:
        with _lock:
            ph = ",".join("?" * len(scopes))
            rows = _db().execute(
                f"SELECT ts, sender_name, sender_id, text FROM chatlog"
                f" WHERE scope IN ({ph}) AND day=? ORDER BY ts LIMIT ?",
                (*scopes, day, max(1, min(limit, 2000))),
            ).fetchall()
    except Exception:
        return []
    return [{"ts": r[0], "sender": r[1] or r[2], "text": r[3]} for r in rows]


def nhac_toi(user_id: str, me: str, *, ngay: int = 7,
             limit: int = 200) -> list[dict[str, Any]]:
    """Tin NHẮC TỚI `me` trong `ngay` ngày gần nhất, gồm phạm vi kết nối.

    `me` = tên/uid; khớp không dấu với cột mentions_fold (hoặc '@all').
    """
    scopes = _scopes_doc(user_id)
    me_f = _fold(me).strip()
    if not scopes or not me_f:
        return []
    tu_ngay = (datetime.now(_TZ) - timedelta(days=max(1, ngay))).strftime("%Y-%m-%d")
    try:
        with _lock:
            ph = ",".join("?" * len(scopes))
            rows = _db().execute(
                f"SELECT ts, day, sender_name, sender_id, text, mentions_fold"
                f" FROM chatlog WHERE scope IN ({ph}) AND day >= ?"
                f" ORDER BY ts DESC LIMIT ?",
                (*scopes, tu_ngay, max(1, min(limit, 1000))),
            ).fetchall()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for ts, day, sname, sid, text, mf in rows:
        toks = (mf or "").split()
        if _MENTION_ALL in toks or any(me_f == t or me_f in t or t in me_f for t in toks):
            out.append({"ts": ts, "day": day, "sender": sname or sid, "text": text})
    return out


def _reset_for_tests(db_path: Path | None = None) -> None:
    global _conn, _DB_PATH
    _conn = None
    if db_path is not None:
        _DB_PATH = db_path
