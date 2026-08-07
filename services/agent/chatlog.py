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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chatlog_scope_ts"
                     " ON chatlog(scope, ts)")
        # Luật «tự nhắc»: ai nhắc tới `name` + có hẹn → nhắc `deliver_to` trước
        # các mốc lead_min. deliver_meta = bối cảnh GỬI chốt lúc đặt luật (bot/
        # account) để nhắc nền chạy ngoài ngữ cảnh tin vẫn gửi đúng chỗ.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS watch_rules ("
            " id TEXT PRIMARY KEY,"
            " deliver_to TEXT NOT NULL,"      # user_id nhận nhắc (thường là DM chủ)
            " name TEXT NOT NULL,"            # tên cần dò trong lời nhắc
            " name_fold TEXT NOT NULL,"       # tên đã bỏ dấu để so khớp
            " lead_min TEXT,"                 # json list phút-trước (vd [1440,60])
            " deliver_meta TEXT,"             # json bối cảnh gửi (bot_id/account…)
            " enabled INTEGER NOT NULL DEFAULT 1,"
            " last_scan_ts REAL,"             # con trỏ quét (chỉ xét tin mới hơn)
            " created_at REAL NOT NULL)"
        )
        # Chống tạo trùng: mỗi (luật, tin, mốc) chỉ đặt nhắc MỘT lần.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS nhac_da_tao ("
            " k TEXT PRIMARY KEY, created_at REAL NOT NULL)"
        )
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

    Trả {enabled, retention_days, compact, tag_only}. Đọc `chatlog_settings`
    (dict khoá 'plat:chat[#topic][:user]' → bản ghi cùng tên trường).

    `tag_only` — chủ máy chốt 07/08: ô «Tag bot» trong «Lọc nhật ký» chạy NGƯỢC
    CHIỀU các ô khác. Bỏ tick (mặc định) = ghi cả hội thoại KHÔNG tag; tick vào
    = SIẾT LẠI, chỉ tin có tag bot mới lưu.

    Vì sao mặc định là "ghi cả tin không tag" dù «Lọc thread» đang bắt buộc tag:
    **ghi ≠ trả lời**. Bot chỉ đáp khi được gọi tên, nhưng nhật ký nhóm sinh ra
    để có biên bản đầy đủ. Ba công tắc tag rời nhau hẳn — trả lời
    (`thread_mention_filters`), đẩy webhook (`thread_forward_filters.tag_mode`),
    và ghi nhật ký (`tag_only` ở đây) — đừng gộp.
    """
    mac_dinh = {"enabled": False, "retention_days": _MAC_DINH_NGAY,
                "compact": False, "tag_only": False, "groups": None}
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
            nh = v.get("groups")
            return {"enabled": bool(v.get("enabled", False)),
                    "retention_days": max(0, rd),
                    "compact": bool(v.get("compact", False)),
                    "tag_only": bool(v.get("tag_only", False)),
                    "groups": [str(x) for x in nh] if isinstance(nh, list) else None}
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
        text: str = "", mentions: list[str] | None = None,
        tagged: bool | None = None) -> bool:
    """Ghi một tin vào nhật ký NẾU phạm vi này bật. Trả True nếu đã ghi.

    Không raise. Chỉ ghi CHỮ (text rỗng → bỏ qua).

    `tagged` — tin này CÓ tag bot không. Chỉ dùng khi phạm vi bật `tag_only`.
    Bên gọi tự tính vì mỗi kênh nhận diện tag một kiểu (zca-js mentions, entity
    Telegram, @alias, từ khoá); `ghi()` chỉ có `mentions` thô nên không tự suy
    ra được "trong đám được nhắc có bot hay không".

    `tagged=None` + `tag_only` bật = KHÔNG BIẾT nên VẪN GHI. Chọn giữ tin thay
    vì bỏ tin: kênh nào quên truyền cờ thì hậu quả là nhật ký rộng hơn ý muốn —
    còn làm ngược lại thì nhật ký im lặng rỗng và không ai biết vì sao.
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
        if st.get("tag_only") and tagged is False:
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


# ── Đọc theo phạm vi để ĐỒNG BỘ LÊN ĐÁM MÂY ──────────────────────────────────
# Khác các hàm đọc ở trên: không đi theo kết nối bộ nhớ, không lọc người-được-
# nhắc. Đồng bộ là sao lưu NGUYÊN SỔ của đúng một phạm vi, nên phải đọc thô.

def cac_scope() -> list[str]:
    """Mọi phạm vi đang có tin trong nhật ký."""
    try:
        with _lock:
            rows = _db().execute("SELECT DISTINCT scope FROM chatlog").fetchall()
    except Exception:
        return []
    return [r[0] for r in rows if r[0]]


def ngay_va_dem(scope_key: str) -> dict[str, tuple[int, float]]:
    """{ngày: (số tin, ts mới nhất)} của một phạm vi.

    Dùng để biết một NGÀY có đổi gì kể từ lần đồng bộ trước hay không — đẩy lại
    nguyên tệp mỗi đêm cho những ngày không đổi là tốn băng thông vô ích.
    """
    try:
        with _lock:
            rows = _db().execute(
                "SELECT day, COUNT(*), MAX(ts) FROM chatlog WHERE scope=?"
                " GROUP BY day ORDER BY day", (str(scope_key),)).fetchall()
    except Exception:
        return {}
    return {r[0]: (int(r[1] or 0), float(r[2] or 0)) for r in rows if r[0]}


def doc_scope_ngay(scope_key: str, day: str) -> list[dict[str, Any]]:
    """Toàn bộ tin của một phạm vi trong một ngày, theo thứ tự thời gian."""
    try:
        with _lock:
            rows = _db().execute(
                "SELECT ts, day, sender_id, sender_name, text FROM chatlog"
                " WHERE scope=? AND day=? ORDER BY ts", (str(scope_key), str(day))
            ).fetchall()
    except Exception:
        return []
    return [{"ts": r[0], "ngay": r[1], "sender_id": r[2] or "",
             "sender": r[3] or r[2] or "", "text": r[4]} for r in rows]


# ── Luật «tự nhắc» + quét nền ────────────────────────────────────────────────

_LEAD_MAC_DINH = [1440, 60]     # nhắc trước 1 ngày và 1 giờ (phút)


def _leads(v: Any) -> list[int]:
    """Chuẩn hoá danh sách phút-trước; rỗng/hỏng → mặc định [1 ngày, 1 giờ]."""
    out: list[int] = []
    for x in (v if isinstance(v, list) else []):
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append(n)
    # bỏ trùng, nhắc mốc XA trước (sắp xếp giảm dần cho gọn)
    out = sorted(set(out), reverse=True)
    return out or list(_LEAD_MAC_DINH)


def _row_rule(r: tuple) -> dict[str, Any]:
    return {"id": r[0], "deliver_to": r[1], "name": r[2],
            "lead_min": _try_json_list(r[3]), "deliver_meta": _try_json_dict(r[4]),
            "enabled": bool(r[5]), "last_scan_ts": r[6]}


def _try_json_list(s: Any) -> list:
    try:
        v = json.loads(s) if s else []
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _try_json_dict(s: Any) -> dict:
    try:
        v = json.loads(s) if s else {}
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def luat_them(deliver_to: str, name: str, *, lead_min: Any = None,
              deliver_meta: dict | None = None) -> dict[str, Any] | None:
    """Đặt (hoặc cập nhật) luật tự nhắc cho `deliver_to`. Một tên = một luật."""
    deliver_to = str(deliver_to or "").strip()
    name = str(name or "").strip()
    if not deliver_to or not name:
        return None
    nf = _fold(name).strip()
    leads = _leads(lead_min)
    meta_json = json.dumps(deliver_meta or {}, ensure_ascii=False)
    now = time.time()
    with _lock:
        db = _db()
        old = db.execute(
            "SELECT id FROM watch_rules WHERE deliver_to=? AND name_fold=?",
            (deliver_to, nf)).fetchone()
        if old:
            rid = old[0]
            db.execute("UPDATE watch_rules SET name=?, lead_min=?, deliver_meta=?,"
                       " enabled=1 WHERE id=?",
                       (name, json.dumps(leads), meta_json, rid))
        else:
            rid = "wr_" + str(int(now * 1000))
            # last_scan_ts=0 → lần quét ĐẦU nhìn lại `nhin_lai_ngay` (sàn now-Nd),
            # bắt luôn hẹn vừa được nhắc mấy hôm trước mà còn sắp tới.
            db.execute(
                "INSERT INTO watch_rules (id, deliver_to, name, name_fold, lead_min,"
                " deliver_meta, enabled, last_scan_ts, created_at)"
                " VALUES (?,?,?,?,?,?,1,0,?)",
                (rid, deliver_to, name, nf, json.dumps(leads), meta_json, now))
        db.commit()
    return {"id": rid, "deliver_to": deliver_to, "name": name, "lead_min": leads}


def luat_ds(deliver_to: str) -> list[dict[str, Any]]:
    """Danh sách luật của một `deliver_to` (gồm cả luật đã tắt) — cho tool list."""
    deliver_to = str(deliver_to or "").strip()
    if not deliver_to:
        return []
    with _lock:
        rows = _db().execute(
            "SELECT id, deliver_to, name, lead_min, deliver_meta, enabled, last_scan_ts"
            " FROM watch_rules WHERE deliver_to=? ORDER BY created_at", (deliver_to,)
        ).fetchall()
    return [_row_rule(r) for r in rows]


def luat_tat(deliver_to: str, rid: str | None = None) -> int:
    """Tắt (xoá) một luật theo id, hoặc mọi luật của `deliver_to`. Trả số đã tắt."""
    deliver_to = str(deliver_to or "").strip()
    if not deliver_to:
        return 0
    with _lock:
        db = _db()
        if rid:
            cur = db.execute("DELETE FROM watch_rules WHERE deliver_to=? AND id=?",
                             (deliver_to, str(rid)))
        else:
            cur = db.execute("DELETE FROM watch_rules WHERE deliver_to=?", (deliver_to,))
        db.commit()
        return cur.rowcount or 0


def luat_tat_ca() -> list[dict[str, Any]]:
    """Mọi luật ĐANG BẬT (cho vòng quét nền)."""
    with _lock:
        rows = _db().execute(
            "SELECT id, deliver_to, name, lead_min, deliver_meta, enabled, last_scan_ts"
            " FROM watch_rules WHERE enabled=1").fetchall()
    return [_row_rule(r) for r in rows]


def _dat_con_tro(rid: str, ts: float) -> None:
    with _lock:
        db = _db()
        db.execute("UPDATE watch_rules SET last_scan_ts=? WHERE id=?", (ts, rid))
        db.commit()


def tin_nhac_moi(deliver_to: str, name: str, *, since_ts: float,
                 limit: int = 100) -> list[dict[str, Any]]:
    """Tin NHẮC TỚI `name` (hoặc @all) MỚI hơn `since_ts`, trong phạm vi đọc được
    của `deliver_to` (của mình + “Kết nối bộ nhớ”). Có `id` để chống tạo trùng."""
    scopes = _scopes_doc(deliver_to)
    me_f = _fold(name).strip()
    if not scopes or not me_f:
        return []
    try:
        with _lock:
            ph = ",".join("?" * len(scopes))
            rows = _db().execute(
                f"SELECT id, ts, sender_name, sender_id, text, mentions_fold"
                f" FROM chatlog WHERE scope IN ({ph}) AND ts > ?"
                f" ORDER BY ts LIMIT ?",
                (*scopes, float(since_ts), max(1, min(limit, 500))),
            ).fetchall()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for _id, ts, sname, sid, text, mf in rows:
        toks = (mf or "").split()
        if _MENTION_ALL in toks or any(me_f == t or me_f in t or t in me_f for t in toks):
            out.append({"id": _id, "ts": ts, "sender": sname or sid, "text": text})
    return out


def _da_tao(k: str) -> bool:
    with _lock:
        return _db().execute(
            "SELECT 1 FROM nhac_da_tao WHERE k=?", (k,)).fetchone() is not None


def _ghi_da_tao(k: str) -> None:
    with _lock:
        db = _db()
        db.execute("INSERT OR IGNORE INTO nhac_da_tao (k, created_at) VALUES (?,?)",
                   (k, time.time()))
        # dọn dấu vết quá cũ (>120 ngày) để bảng không phình
        db.execute("DELETE FROM nhac_da_tao WHERE created_at < ?",
                   (time.time() - 120 * 86400,))
        db.commit()


def _parse_iso(s: Any) -> float | None:
    """'YYYY-MM-DDTHH:MM[:SS]' (giờ VN) → epoch; hỏng → None."""
    t = str(s or "").strip()[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(t, fmt).replace(tzinfo=_TZ).timestamp()
        except ValueError:
            continue
    return None


def quet_nhac_hen(*, trich_hen: Any, tao_nhac: Any, now: float | None = None,
                  nhin_lai_ngay: int = 3) -> int:
    """Quét mọi luật: tin-nhắc-tới MỚI → nhờ `trich_hen` tìm mốc hẹn → đặt nhắc
    trước từng lead qua `tao_nhac`. Hàm THUẦN (bơm hai callable vào) để test được
    không cần LLM/DB nhắc thật.

    - `trich_hen(msgs) -> {msg_id: {"iso": str, "label": str} | None}`
    - `tao_nhac(deliver_to, text, when_ts, meta) -> None`  (raise được, sẽ bỏ qua)
    Trả về số lượt nhắc đã tạo.
    """
    now = now if now is not None else time.time()
    tao = 0
    for rule in luat_tat_ca():
        deliver_to = rule["deliver_to"]
        name = rule["name"]
        leads = _leads(rule.get("lead_min"))
        since = max(float(rule.get("last_scan_ts") or 0), now - nhin_lai_ngay * 86400)
        try:
            msgs = tin_nhac_moi(deliver_to, name, since_ts=since)
            got = trich_hen(msgs) if msgs else {}
            for m in msgs:
                info = (got or {}).get(m["id"])
                if not isinstance(info, dict):
                    continue
                appt = _parse_iso(info.get("iso"))
                if not appt or appt <= now:
                    continue
                nhan = str(info.get("label") or m["text"]).strip()[:200]
                khi = datetime.fromtimestamp(appt, _TZ).strftime("%H:%M %d/%m")
                for lead in leads:
                    fire = appt - lead * 60
                    if fire <= now:
                        continue
                    k = f"{rule['id']}:{m['id']}:{lead}"
                    if _da_tao(k):
                        continue
                    truoc = (f"{lead // 1440} ngày" if lead % 1440 == 0
                             else f"{lead // 60} giờ" if lead % 60 == 0
                             else f"{lead} phút")
                    txt = (f"⏰ Nhắc trước {truoc}: {nhan} — lúc {khi}. "
                           f"({m['sender']} có nhắc tới trong nhóm.)")
                    try:
                        tao_nhac(deliver_to, txt, fire, rule.get("deliver_meta") or {})
                        _ghi_da_tao(k)
                        tao += 1
                    except Exception:
                        pass
        finally:
            _dat_con_tro(rule["id"], now)
    return tao


def _reset_for_tests(db_path: Path | None = None) -> None:
    global _conn, _DB_PATH
    _conn = None
    if db_path is not None:
        _DB_PATH = db_path


def ghi_hoat_dong(user_id: str, *, nhom: str, mo_ta: str) -> bool:
    """Ghi một dòng HOẠT ĐỘNG của bot vào nhật ký (bot vừa làm gì).

    Khác `ghi()` — cái đó ghi LỜI NGƯỜI NÓI. Hai thứ vào chung một cuốn nhưng do
    hai công tắc khác nhau điều khiển, đúng như chủ máy chốt 07/08:

        21 ô chức năng  → lọc phần bot LÀM GÌ   (hàm này)
        ô Tag bot       → lọc LỜI NGƯỜI NÓI     (`ghi`)

    `nhom` là nhóm chức năng đã tính từ tool thật sự chạy
    (`capabilities.group_of`), không phải đoán theo từ khoá — orchestrator đã
    tính sẵn nên ở đây chỉ việc lọc.

    `groups` rỗng/thiếu = GHI HẾT. Cấu hình đang chạy không có trường này nên
    hành vi không đổi cho tới khi chủ máy chủ động bớt.
    """
    nhom = str(nhom or "").strip()
    if not nhom or nhom == "_ungrouped":
        return False
    try:
        from services.agent.scope import tach_khoa_phien
        sc = tach_khoa_phien(user_id)
        if not sc.chat:
            return False
        st = cai_dat(sc.kenh, sc.chat, sc.topic, sc.actor)
        if not st["enabled"]:
            return False
        cho_phep = st.get("groups")
        if isinstance(cho_phep, list) and nhom not in cho_phep:
            return False
    except Exception as exc:
        logger.debug("chatlog.ghi_hoat_dong bỏ qua: %s", exc)
        return False
    # Người gửi là chính bot: dòng hoạt động không phải lời của ai trong nhóm,
    # để trống sender thì lúc đọc lại không phân biệt được với tin người nói.
    return ghi(user_id, sender_id="bot", sender_name="bot",
               text=f"[{nhom}] {mo_ta}"[:400], tagged=True)
