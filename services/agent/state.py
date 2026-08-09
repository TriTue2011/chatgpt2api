"""Agent state — persona, memory, user profiles, approval allowlist.

The "who am I / what can I do / what am I allowed / what do I remember" state
that shapes every conversation (mirrors OpenClaw/Hermes SOUL.md + MEMORY.md +
USER.md + command allowlist). Everything persists under ``DATA_DIR/agent`` so it
survives restarts and image rebuilds (the dir is on the bind mount).

Files:
    agent/soul.md            — persona + capability list (seeded from package)
    agent/MEMORY.md          — durable family facts
    agent/users/<uid>.md     — per-user profile
    agent/approvals.json     — {user_id: {capability: "always"}} remembered grants

Pending approvals (a change action proposed but not yet confirmed) are kept
in-memory per user — they are ephemeral by nature (the next message resolves
them), so they are NOT persisted.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR

logger = logging.getLogger(__name__)

_AGENT_DIR = Path(DATA_DIR) / "agent"
_USERS_DIR = _AGENT_DIR / "users"
_SOUL_FILE = _AGENT_DIR / "soul.md"
_MEMORY_FILE = _AGENT_DIR / "MEMORY.md"
_ENVIRONMENT_FILE = _AGENT_DIR / "ENVIRONMENT.md"
_APPROVALS_FILE = _AGENT_DIR / "approvals.json"
# FIX4 (audit 2026-07): FTS5 index cho toàn bộ MEMORY.md (không chỉ đuôi
# file như load_memory) — reuse pattern session.py (turns_fts): content=
# external table, content_rowid=id, tokenize='unicode61'.
_MEMORY_DB_PATH = _AGENT_DIR / "memory_fts.sqlite"
# Trí nhớ THEO PHẠM VI: mỗi phạm vi một file + một index riêng (xem
# services/agent/scope.py). Tên file là BĂM của khoá phạm vi — không phải khoá
# đã "làm sạch": bản nháp trước bỏ dấu phân cách nên `a.b@x.com` và `ab@x.com`
# ra cùng một file, rò dữ liệu giữa hai người.
_MEMORY_SCOPE_DIR = _AGENT_DIR / "memory"

# Package-shipped default persona used to seed soul.md on first run.
_DEFAULT_SOUL = Path(__file__).with_name("soul.md")

_lock = threading.RLock()
# đường dẫn index → connection (mỗi phạm vi một index, không migration schema)
_mem_conn: dict[str, sqlite3.Connection] = {}
_MEM_WORD_RE = re.compile(r"[\wÀ-ỹ]{2,}", re.UNICODE)

# user_id -> {"capability": str, "args": dict, "summary": str, "ts": float}
# A change action the model proposed; resolved when the user confirms/denies.
_pending: dict[str, dict[str, Any]] = {}


def _ensure_dirs() -> None:
    try:
        _AGENT_DIR.mkdir(parents=True, exist_ok=True)
        _USERS_DIR.mkdir(parents=True, exist_ok=True)
        _MEMORY_SCOPE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # never let a state hiccup break the agent
        logger.warning("agent.state: mkdir failed: %s", exc)


# ── Persona ────────────────────────────────────────────────────────────────

def load_soul() -> str:
    """Return the persona text, seeding soul.md from the package on first use."""
    _ensure_dirs()
    try:
        if _SOUL_FILE.exists():
            return _SOUL_FILE.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("agent.state: read soul failed: %s", exc)
    # Seed from the packaged default.
    try:
        text = _DEFAULT_SOUL.read_text(encoding="utf-8")
        _SOUL_FILE.write_text(text, encoding="utf-8")
        return text
    except Exception as exc:
        logger.warning("agent.state: seed soul failed: %s", exc)
        return "Em là Tiểu Vy, trợ lý gia đình. Trả lời tiếng Việt, ngắn gọn, ấm áp."


# ── Environment map (servers/containers/services — read-only for the agent) ──

def load_environment(limit_chars: int = 2500) -> str:
    """Return the environment map (ENVIRONMENT.md). The agent only reads it;
    the owner (or a maintenance session) edits the file on the bind mount."""
    try:
        if _ENVIRONMENT_FILE.exists():
            return _ENVIRONMENT_FILE.read_text(encoding="utf-8")[:limit_chars]
    except Exception as exc:
        logger.warning("agent.state: read environment failed: %s", exc)
    return ""


# ── Memory (durable family facts) ────────────────────────────────────────────

def _memory_file(pham_vi: str = "") -> Path:
    """File trí nhớ của một phạm vi. Rỗng = MEMORY.md chung như trước.

    Đọc `_MEMORY_FILE` tại thời điểm gọi (không chụp sẵn) để test hiện có vẫn
    thay được đường dẫn bằng cách gán `state._MEMORY_FILE`.
    """
    if not pham_vi:
        return _MEMORY_FILE
    from services.agent.scope import bam_pham_vi
    return _MEMORY_SCOPE_DIR / f"{bam_pham_vi(pham_vi)}.md"


def load_memory(limit_chars: int = 4000, *, pham_vi: str = "",
                doc_them: list[str] | None = None) -> str:
    """Return recent durable memory (tail of MEMORY.md).

    `pham_vi` rỗng = kho chung (đường nội bộ, scheduler, và toàn bộ dữ liệu có
    từ trước). Có phạm vi thì đọc kho riêng CỘNG kho chung: fact cũ vẫn dùng
    được, fact mới của người khác thì không lọt sang — migration dữ liệu cũ là
    bước riêng chủ máy đã hoãn.

    `doc_them` = các phạm vi được ĐỌC THÊM nhờ kết nối bộ nhớ (xem
    scope.pham_vi_doc_them). Chỉ mở đường ĐỌC — ghi vẫn vào `pham_vi`.
    """
    def _doc(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8") if p.exists() else ""
        except Exception as exc:
            logger.warning("agent.state: read memory failed: %s", exc)
            return ""

    if not pham_vi:
        return _doc(_MEMORY_FILE)[-limit_chars:]
    phan = [_doc(_MEMORY_FILE)]
    phan += [_doc(_memory_file(k)) for k in (doc_them or []) if k]
    # Kho RIÊNG đứng cuối để nó chiếm phần đuôi khi phải cắt: điều chính mình
    # vừa dặn quan trọng hơn fact chung cũ và hơn fact mượn từ chỗ khác.
    phan.append(_doc(_memory_file(pham_vi)))
    return "".join(phan)[-limit_chars:]


def _norm_fact(s: str) -> str:
    """Chuẩn hóa 1 dòng fact để so trùng: bỏ prefix '- [ts] (who)', gộp khoảng
    trắng, bỏ dấu câu, lowercase."""
    import re as _re
    s = _re.sub(r"^\s*-\s*\[[^\]]*\]\s*(\([^)]*\)\s*)?", "", s or "")
    s = _re.sub(r"[^\w\s]", " ", s, flags=_re.UNICODE)
    return _re.sub(r"\s+", " ", s).strip().lower()


def _dong_tri_nho(pham_vi: str = "") -> list[str]:
    """Mọi dòng trí nhớ mà phạm vi này ĐƯỢC THẤY: kho riêng + kho chung.

    Bộ chặn trùng và bộ cập-nhật phải soi đúng tập này, không thì fact đã có
    trong kho chung lại bị thêm lần nữa vào kho riêng.
    """
    ra: list[str] = []
    for p in ({_MEMORY_FILE, _memory_file(pham_vi)} if pham_vi else {_MEMORY_FILE}):
        try:
            if p.exists():
                ra.extend(p.read_text(encoding="utf-8").splitlines())
        except Exception:
            continue
    return ra


def memory_contains(fact: str, threshold: float = 0.82, *, pham_vi: str = "") -> bool:
    """True nếu `fact` (hoặc gần trùng) ĐÃ có trong MEMORY.md — để chặn 'remember'
    đề xuất/lưu lại điều đã nhớ (model hay lôi nhầm ngữ cảnh, vd thông tin SSH).

    FIX3 (audit 2026-07): BỎ so khớp substring thô (nf in nl / nl in nf) — nó
    coi fact MỚI là trùng chỉ vì chuỗi của nó xuất hiện làm chuỗi con của một
    dòng CŨ, kể cả khi dòng cũ mang nghĩa NGƯỢC LẠI (vd fact mới "thích cà phê"
    lại khớp dòng cũ phủ định "không thích cà phê đá" vì "thích cà phê" là
    substring của nó) → fact mới bị coi là đã nhớ rồi và KHÔNG được ghi lại.
    Chỉ còn dựa vào ngưỡng Jaccard theo token (threshold mặc định 0.82)."""
    nf = _norm_fact(fact)
    if not nf:
        return False
    lines = _dong_tri_nho(pham_vi)
    if not lines:
        return False
    nf_tokens = set(nf.split())
    if not nf_tokens:
        return False
    for ln in lines:
        nl = _norm_fact(ln)
        if not nl:
            continue
        lt = set(nl.split())
        if not lt:
            continue
        union = len(nf_tokens | lt)
        if union and len(nf_tokens & lt) / union >= threshold:
            return True
    return False


def _do_giong(fact: str, pham_vi: str = "") -> tuple[float, str]:
    """(độ giống cao nhất, dòng khớp nhất) giữa `fact` và trí nhớ thấy được."""
    nf = _norm_fact(fact)
    if not nf:
        return 0.0, ""
    lines = _dong_tri_nho(pham_vi)
    if not lines:
        return 0.0, ""
    nf_tokens = set(nf.split())
    if not nf_tokens:
        return 0.0, ""
    cao, dong = 0.0, ""
    for ln in lines:
        lt = set(_norm_fact(ln).split())
        if not lt:
            continue
        union = len(nf_tokens | lt)
        if not union:
            continue
        r = len(nf_tokens & lt) / union
        if r > cao:
            cao, dong = r, ln
    return cao, dong


def nho_hoac_cap_nhat(fact: str, who: str = "", *,
                      nguong_trung: float = 0.97,
                      nguong_cap_nhat: float = 0.82,
                      pham_vi: str = "") -> str:
    """Ghi nhớ `fact`; nếu nó là BẢN CẬP NHẬT của một dòng cũ thì THAY dòng đó.

    Trả về 'trung' (y nguyên, không lưu) | 'cap_nhat' (đã thay dòng cũ) |
    'them' (điều mới, đã thêm).

    Vì sao phải có: bộ chặn trùng dùng độ giống token, và một lời dặn ĐƯỢC SỬA
    luôn gần trùng với chính lời dặn nó thay thế — càng nhắc lại trung thực thì
    càng chắc bị coi là trùng rồi bỏ đi trong im lặng. Hệ quả: người dùng KHÔNG
    THỂ đổi điều bot đã nhớ.

    Đo thật 01/08: người dùng nói "Bỏ tóm tắt đi"; câu bot định lưu giống dòng cũ
    (dòng có "có tóm tắt ngắn") tới 0,955 — vượt ngưỡng 0,82 nên không lưu gì,
    trong khi bot vẫn đáp "Dạ được anh". Lượt sau bản tin vẫn có tóm tắt.
    """
    fact = (fact or "").strip()
    if not fact:
        return "trung"
    cao, dong_cu = _do_giong(fact, pham_vi)
    if cao >= nguong_trung:
        return "trung"
    if cao >= nguong_cap_nhat and dong_cu:
        _xoa_dong_tri_nho(dong_cu, pham_vi)
        append_memory(fact, who=who, pham_vi=pham_vi)
        return "cap_nhat"
    append_memory(fact, who=who, pham_vi=pham_vi)
    return "them"


def _xoa_dong_tri_nho(dong: str, pham_vi: str = "") -> None:
    """Bỏ một dòng khỏi file trí nhớ và khỏi FTS index (giữ hai bên khớp nhau).

    Xoá ở CẢ kho riêng và kho chung. Dòng cần thay có thể nằm ở kho chung (dữ
    liệu có từ trước khi tách phạm vi); chừa nó lại thì lời dặn mới và lời dặn cũ
    cùng tồn tại, và người dùng lại KHÔNG THỂ sửa điều bot đã nhớ — đúng cái lỗi
    `nho_hoac_cap_nhat` sinh ra để chữa.
    """
    with _lock:
        cac_file = [_MEMORY_FILE]
        if pham_vi:
            cac_file.append(_memory_file(pham_vi))
        for p in cac_file:
            try:
                if not p.exists():
                    continue
                cu = p.read_text(encoding="utf-8").splitlines()
                moi = [x for x in cu if x.strip() != dong.strip()]
                if len(moi) != len(cu):
                    p.write_text("\n".join(moi) + ("\n" if moi else ""),
                                 encoding="utf-8")
            except Exception as exc:
                logger.warning("agent.state: xoá dòng trí nhớ lỗi: %s", exc)
        for pv in ({"", pham_vi} if pham_vi else {""}):
            try:
                db = _mem_db(pv)
                rows = db.execute(
                    "SELECT id FROM memory_lines WHERE line = ?", (dong,),
                ).fetchall()
                for (rid,) in rows:
                    db.execute("DELETE FROM memory_fts WHERE rowid = ?", (rid,))
                    db.execute("DELETE FROM memory_lines WHERE id = ?", (rid,))
                db.commit()
            except Exception as exc:
                logger.warning("agent.state: xoá dòng khỏi FTS lỗi: %s", exc)


def append_memory(fact: str, who: str = "", *, pham_vi: str = "") -> None:
    """Append a durable fact (a change action — call only after approval)."""
    fact = (fact or "").strip()
    if not fact:
        return
    _ensure_dirs()
    stamp = time.strftime("%Y-%m-%d %H:%M")
    line = f"- [{stamp}]{f' ({who})' if who else ''} {fact}"
    tep = _memory_file(pham_vi)
    with _lock:
        try:
            with tep.open("a", encoding="utf-8") as f:
                f.write(line + chr(10))
        except Exception as exc:
            logger.warning("agent.state: append memory failed: %s", exc)
            return
        # FIX4 (audit 2026-07): đồng bộ FTS ngay khi thêm — chỉ thêm 1 dòng
        # (rẻ hơn nhiều so với rebuild toàn bộ mỗi lần append_memory).
        try:
            db = _mem_db(pham_vi)
            cur = db.execute(
                "INSERT INTO memory_lines (line) VALUES (?)", (line,),
            )
            rid = cur.lastrowid
            db.execute(
                "INSERT INTO memory_fts (rowid, line) VALUES (?,?)", (rid, line),
            )
            mtime = tep.stat().st_mtime
            db.execute(
                "INSERT INTO memory_meta (key, value) VALUES ('mtime', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(mtime),),
            )
            db.commit()
        except Exception as exc:
            logger.warning("agent.state: memory FTS sync failed: %s", exc)


def _mem_db_path(pham_vi: str = "") -> Path:
    if not pham_vi:
        return _MEMORY_DB_PATH
    from services.agent.scope import bam_pham_vi
    return _MEMORY_SCOPE_DIR / f"{bam_pham_vi(pham_vi)}.sqlite"


def _mem_db(pham_vi: str = "") -> sqlite3.Connection:
    """Kết nối SQLite cho FTS index của file trí nhớ — cùng pattern session.py
    (turns_fts): bảng gốc + virtual table fts5 content-linked.

    MỖI PHẠM VI MỘT INDEX RIÊNG thay vì thêm cột `scope` vào index đang có: index
    cũ đã tồn tại trên máy chủ, thêm cột là phải migration schema lúc khởi động.
    """
    duong = str(_mem_db_path(pham_vi))
    conn = _mem_conn.get(duong)
    if conn is None:
        _ensure_dirs()
        conn = sqlite3.connect(duong, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS memory_lines ("
            " id INTEGER PRIMARY KEY,"
            " line TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5("
            "line, content='memory_lines', content_rowid='id', "
            "tokenize='unicode61')"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS memory_meta ("
            " key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.commit()
        _mem_conn[duong] = conn
    return conn


def _rebuild_memory_index(pham_vi: str = "") -> None:
    """Xây lại toàn bộ FTS index từ file trí nhớ — dùng khi file mới hơn index
    (ai đó sửa tay MEMORY.md ngoài append_memory, hoặc lần đầu chưa có index)."""
    tep = _memory_file(pham_vi)
    if not tep.exists():
        return
    try:
        text = tep.read_text(encoding="utf-8")
        mtime = tep.stat().st_mtime
    except Exception as exc:
        logger.warning("agent.state: read memory for index failed: %s", exc)
        return
    lines = [ln for ln in text.splitlines() if ln.strip()]
    with _lock:
        db = _mem_db(pham_vi)
        try:
            db.execute("DELETE FROM memory_fts")
            db.execute("DELETE FROM memory_lines")
            for ln in lines:
                cur = db.execute(
                    "INSERT INTO memory_lines (line) VALUES (?)", (ln,),
                )
                rid = cur.lastrowid
                db.execute(
                    "INSERT INTO memory_fts (rowid, line) VALUES (?,?)",
                    (rid, ln),
                )
            db.execute(
                "INSERT INTO memory_meta (key, value) VALUES ('mtime', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(mtime),),
            )
            db.commit()
        except Exception as exc:
            logger.warning("agent.state: rebuild memory index failed: %s", exc)


def _sync_memory_index(pham_vi: str = "") -> None:
    """Rebuild-on-mismatch (cùng cách session.py xử lý lệch dữ liệu): nếu file
    trí nhớ mới hơn (hoặc khác) mtime đã lưu trong index, xây lại toàn bộ."""
    tep = _memory_file(pham_vi)
    if not tep.exists():
        return
    try:
        mtime = tep.stat().st_mtime
    except Exception:
        return
    try:
        with _lock:
            row = _mem_db(pham_vi).execute(
                "SELECT value FROM memory_meta WHERE key='mtime'"
            ).fetchone()
    except Exception as exc:
        logger.warning("agent.state: read memory index meta failed: %s", exc)
        row = None
    try:
        indexed = float(row[0]) if row and row[0] else -1.0
    except (TypeError, ValueError):
        indexed = -1.0
    if indexed < 0 or abs(mtime - indexed) > 0.001:
        _rebuild_memory_index(pham_vi)


def search_memory(query: str, *, limit: int = 6, pham_vi: str = "",
                  doc_them: list[str] | None = None) -> list[str]:
    """FIX4 (audit 2026-07): full-text search TOÀN BỘ file trí nhớ (không chỉ
    đuôi file ~4-6k ký tự như load_memory) — để một fact CŨ (quá khoảng
    40-80 dòng) vẫn được tìm thấy khi liên quan tới câu hỏi hiện tại. Dùng
    ADDITIVE cùng load_memory() (khối "gần đây" luôn có sẵn) — không thay
    thế hành vi hiện có, chỉ bổ sung khả năng tìm fact liên quan ở xa.

    Có `pham_vi` → tìm trong kho riêng, kho mượn theo kết nối, rồi kho chung —
    ĐÚNG tập mà load_memory cho thấy; không bao giờ chạm kho ngoài tập đó."""
    q = (query or "").strip()
    if not q:
        return []
    if not pham_vi:
        return _tim_trong_index(q, limit=limit)
    gop: list[str] = []
    for pv in [pham_vi, *(doc_them or []), ""]:
        for ln in _tim_trong_index(q, limit=limit, pham_vi=pv):
            if ln not in gop:
                gop.append(ln)
    return gop[:max(1, min(int(limit or 6), 20))]


def _tim_trong_index(query: str, *, limit: int = 6, pham_vi: str = "") -> list[str]:
    q = (query or "").strip()
    if not q or not _memory_file(pham_vi).exists():
        return []
    _sync_memory_index(pham_vi)
    words: list[str] = []
    seen: set[str] = set()
    for w in _MEM_WORD_RE.findall(q.lower()):
        if w in seen:
            continue
        seen.add(w)
        words.append(w)
        if len(words) >= 12:
            break
    if not words:
        return []
    fts_query = " OR ".join(f'"{w}"' for w in words)
    limit = max(1, min(int(limit or 6), 20))
    try:
        with _lock:
            rows = _mem_db(pham_vi).execute(
                "SELECT ml.line FROM memory_fts "
                "JOIN memory_lines ml ON ml.id = memory_fts.rowid "
                "WHERE memory_fts MATCH ? ORDER BY ml.id DESC LIMIT ?",
                (fts_query, limit),
            ).fetchall()
    except Exception as exc:
        logger.warning("agent.state: search_memory failed: %s", exc)
        return []
    return [r[0] for r in rows]


# ── Model specs (bot tự học tham số/form từng model — tự tiến hóa) ────────────
# data/agent/model_specs.json: { "<model_id>": {
#     "params":  [ {"key","label","options":[...],"default","arg"} ],  # từng field
#     "presets": [ {"label","values":{key:value}} ],                    # gói sẵn
#     "notes": str, "updated": str, "by": str } }
# Bot HỎI khi chưa biết; người dùng dạy → lưu → lần sau tự đưa lựa chọn + gọi đúng.
_MODEL_SPECS_FILE = _AGENT_DIR / "model_specs.json"


def load_model_specs() -> dict:
    try:
        if _MODEL_SPECS_FILE.exists():
            import json
            data = json.loads(_MODEL_SPECS_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("agent.state: read model_specs failed: %s", exc)
    return {}


def get_model_spec(model_id: str) -> dict | None:
    """Spec của model — khớp id chính xác, hoặc theo ĐUÔI (bỏ prefix provider) để
    'banana-pro' khớp 'flow/banana-pro'."""
    mid = str(model_id or "").strip()
    if not mid:
        return None
    specs = load_model_specs()
    if mid in specs and isinstance(specs[mid], dict):
        return specs[mid]
    tail = mid.split("/")[-1].lower()
    for k, v in specs.items():
        if isinstance(v, dict) and str(k).split("/")[-1].lower() == tail:
            return v
    return None


def set_model_spec(model_id: str, spec: dict, who: str = "") -> None:
    """Lưu/ghép spec cho model (dạy dần từng phần — merge với cái đã có)."""
    mid = str(model_id or "").strip()
    if not mid or not isinstance(spec, dict):
        return
    import json
    with _lock:
        specs = load_model_specs()
        prev = specs.get(mid) if isinstance(specs.get(mid), dict) else {}
        merged = {**prev, **{k: v for k, v in spec.items() if v is not None}}
        merged["updated"] = time.strftime("%Y-%m-%d %H:%M")
        if who:
            merged["by"] = who
        specs[mid] = merged
        try:
            _ensure_dirs()
            _MODEL_SPECS_FILE.write_text(
                json.dumps(specs, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("agent.state: write model_specs failed: %s", exc)


def delete_model_spec(model_id: str) -> bool:
    mid = str(model_id or "").strip()
    if not mid:
        return False
    import json
    with _lock:
        specs = load_model_specs()
        if mid not in specs:
            tail = mid.split("/")[-1].lower()
            mid = next((k for k in specs if str(k).split("/")[-1].lower() == tail), mid)
        if mid not in specs:
            return False
        specs.pop(mid, None)
        try:
            _MODEL_SPECS_FILE.write_text(
                json.dumps(specs, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("agent.state: delete model_spec failed: %s", exc)
            return False
    return True


# ── Per-user profile ─────────────────────────────────────────────────────────

def load_user_profile(user_id: str) -> str:
    try:
        p = _USERS_DIR / f"{_safe(user_id)}.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("agent.state: read user %s failed: %s", user_id, exc)
    return ""


def _safe(name: str) -> str:
    return "".join(c for c in str(name) if c.isalnum() or c in ("-", "_")) or "unknown"


# ── Approval allowlist (remembered "always allow") ───────────────────────────

def _load_approvals() -> dict[str, dict[str, str]]:
    try:
        if _APPROVALS_FILE.exists():
            data = json.loads(_APPROVALS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.warning("agent.state: read approvals failed: %s", exc)
    return {}


def is_approved(user_id: str, capability: str) -> bool:
    """True when the user has granted "always" for this capability."""
    with _lock:
        return _load_approvals().get(str(user_id), {}).get(capability) == "always"


def grant_always(user_id: str, capability: str) -> None:
    """Persist an "always allow" grant for (user, capability)."""
    _ensure_dirs()
    with _lock:
        data = _load_approvals()
        data.setdefault(str(user_id), {})[capability] = "always"
        try:
            _APPROVALS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        except Exception as exc:
            logger.warning("agent.state: write approvals failed: %s", exc)


def revoke(user_id: str, capability: str) -> None:
    with _lock:
        data = _load_approvals()
        if str(user_id) in data:
            data[str(user_id)].pop(capability, None)
            try:
                _APPROVALS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
            except Exception:
                pass


# ── Pending approval (ephemeral) ─────────────────────────────────────────────

def set_pending(user_id: str, capability: str, args: dict, summary: str) -> None:
    with _lock:
        _pending[str(user_id)] = {"capability": capability, "args": args,
                                  "summary": summary, "ts": time.time()}


def get_pending(user_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        p = _pending.get(str(user_id))
        # Expire stale proposals after 10 minutes.
        if p and time.time() - p.get("ts", 0) > 600:
            _pending.pop(str(user_id), None)
            return None
        return p


def clear_pending(user_id: str) -> None:
    with _lock:
        _pending.pop(str(user_id), None)
