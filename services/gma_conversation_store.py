"""Kho hội thoại native của Gemini Web (gma/) — tiếp nối thay vì phát lại.

Học từ Gemini-FastAPI (Nativu5/luuquangvu — cùng hệ với fork gemini-webapi
đang dùng): sau mỗi lượt trả lời, lưu metadata [cid, rid, rcid] của cuộc chat
native trên gemini.google.com kèm hash toàn bộ lịch sử messages. Lượt sau,
khớp PREFIX DÀI NHẤT của messages mới với hash đã lưu → chỉ gửi phần tin nhắn
còn lại vào đúng cuộc chat cũ (client.start_chat(metadata=...)), thay vì phát
lại cả transcript thành một prompt khổng lồ.

Lợi ích: payload không phình theo lịch sử, giữ nguyên ngữ cảnh server-side của
Gemini (nhớ cả ảnh/tệp đã gửi những lượt trước), đỡ chạm trần ký tự. Khớp sai
hoặc metadata chết thì caller rơi về phát lại như cũ — kho chỉ là tối ưu.

Khác bản gốc: dùng sqlite (stdlib) thay LMDB để không thêm dependency; hash
bằng json.dumps(sort_keys) thay orjson. Hai tầng khớp giữ nguyên tinh thần:
  - strict: chuẩn hoá nhẹ (NFC, CRLF→LF, strip, bỏ khối [ToolCalls] nội tuyến)
  - fuzzy : hạ chữ thường + bỏ toàn bộ khoảng trắng/dấu câu ASCII — chịu được
    client trim/sửa whitespace khi phát lại lịch sử.

Lưu ý vận hành (từ README Gemini-FastAPI): tài khoản Google nên bật
"Gemini Apps activity" thì cuộc chat native mới bền — tắt nó thì Google có thể
quên metadata bất kỳ lúc nào (khi đó ta tự rơi về phát lại, không hỏng).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import string
import threading
import time
import unicodedata
from typing import Any, Optional

# Giữ hồ sơ 14 ngày (Gemini phía Google còn giữ lâu hơn); trần số dòng để file
# không phình vô hạn trên máy chủ chạy nhiều tháng.
TTL_GIAY = 14 * 24 * 3600
TRAN_SO_DONG = 4000

_KHOI_TOOLCALLS = re.compile(r"\[ToolCalls\].*?\[/ToolCalls\]", re.DOTALL | re.IGNORECASE)
_BANG_XOA_FUZZY = {ord(c): None for c in (string.whitespace + string.punctuation)}


def _chuan_hoa(text: str, fuzzy: bool = False) -> str:
    t = unicodedata.normalize("NFC", str(text or ""))
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    # Khối tool-call nội tuyến vô hình với hash: bản phát lại nhúng nó vào chữ,
    # bản client giữ trong tool_calls — hai dạng phải khớp nhau.
    t = _KHOI_TOOLCALLS.sub("", t)
    if fuzzy:
        return t.lower().translate(_BANG_XOA_FUZZY)
    return t.strip()


def _canon_args(arguments: Any) -> str:
    s = str(arguments or "")
    try:
        return json.dumps(json.loads(s), sort_keys=True, ensure_ascii=False)
    except Exception:
        return s


def _hash_tin(msg: dict, fuzzy: bool) -> str:
    content = msg.get("content")
    if isinstance(content, list):
        manh = []
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "text":
                manh.append(_chuan_hoa(p.get("text") or "", fuzzy))
            elif p.get("type") == "image_url":
                url = str(((p.get("image_url") or {}).get("url")) or "")
                manh.append("[image:%s]" % hashlib.sha256(url.encode("utf-8")).hexdigest()[:16])
        noi_dung = "\n".join(m for m in manh if m)
    else:
        noi_dung = _chuan_hoa(content or "", fuzzy)

    goi = [str(msg.get("role") or "user"), noi_dung]
    calls = msg.get("tool_calls") or []
    if calls:
        # Bỏ id (tuỳ client sinh lại), giữ (name, arguments) — sắp xếp để
        # thứ tự call không làm lệch hash.
        cap = sorted(
            (str((c.get("function") or {}).get("name") or ""),
             _canon_args((c.get("function") or {}).get("arguments")))
            for c in calls if isinstance(c, dict)
        )
        goi.append(json.dumps(cap, sort_keys=True, ensure_ascii=False))
    raw = json.dumps(goi, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _hash_day(model: str, hash_tins: list[str]) -> str:
    raw = "\x00".join([str(model or "")] + list(hash_tins))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class KhoHoiThoaiGma:
    """Bảng sqlite: strict_hash (PK) / fuzzy_hash → (profile, metadata, so_tin)."""

    def __init__(self, duong_dan: str) -> None:
        self._lock = threading.Lock()
        self._con = sqlite3.connect(duong_dan, check_same_thread=False)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS hoi_thoai ("
            " strict_hash TEXT PRIMARY KEY,"
            " fuzzy_hash  TEXT NOT NULL,"
            " profile     TEXT NOT NULL,"
            " model       TEXT NOT NULL,"
            " metadata    TEXT NOT NULL,"
            " so_tin      INTEGER NOT NULL,"
            " cap_nhat    REAL NOT NULL)"
        )
        self._con.execute(
            "CREATE INDEX IF NOT EXISTS idx_hoi_thoai_fuzzy ON hoi_thoai(fuzzy_hash)"
        )
        self._con.execute(
            "CREATE INDEX IF NOT EXISTS idx_hoi_thoai_cap_nhat ON hoi_thoai(cap_nhat)"
        )
        self._con.commit()

    # ── ghi ──────────────────────────────────────────────────────────────
    def luu(self, messages: list, model: str, profile: str,
            metadata: list) -> bool:
        """Lưu (lịch sử ĐÃ GỒM câu trả lời assistant) → metadata cuộc chat native.

        metadata thiếu cid (phần tử 0) coi như không có gì để tiếp nối — bỏ qua.
        """
        meta = list(metadata or [])
        if not meta or not meta[0] or not messages:
            return False
        strict = _hash_day(model, [_hash_tin(m, False) for m in messages])
        fuzzy = _hash_day(model, [_hash_tin(m, True) for m in messages])
        now = time.time()
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO hoi_thoai"
                " (strict_hash, fuzzy_hash, profile, model, metadata, so_tin, cap_nhat)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (strict, fuzzy, str(profile or ""), str(model or ""),
                 json.dumps(meta, ensure_ascii=False), len(messages), now),
            )
            # Dọn TTL + trần số dòng ngay trong lượt ghi (rẻ nhờ index cap_nhat).
            self._con.execute(
                "DELETE FROM hoi_thoai WHERE cap_nhat < ?", (now - TTL_GIAY,))
            self._con.execute(
                "DELETE FROM hoi_thoai WHERE strict_hash IN ("
                " SELECT strict_hash FROM hoi_thoai"
                " ORDER BY cap_nhat DESC LIMIT -1 OFFSET ?)",
                (TRAN_SO_DONG,),
            )
            self._con.commit()
        return True

    # ── đọc ──────────────────────────────────────────────────────────────
    def tim(self, messages: list, model: str) -> Optional[dict]:
        """Khớp prefix DÀI NHẤT của messages với hội thoại đã lưu.

        Trả {"profile", "metadata", "so_tin", "strict_hash"} hoặc None.
        Chỉ cắt tại ranh giới tin assistant (hội thoại lưu luôn kết thúc bằng
        assistant); ưu tiên prefix dài trước, mỗi độ dài thử strict rồi fuzzy.
        """
        if not isinstance(messages, list) or len(messages) < 2:
            return None
        h_strict = [_hash_tin(m, False) for m in messages]
        h_fuzzy = [_hash_tin(m, True) for m in messages]
        for cuoi in range(len(messages), 1, -1):
            if str(messages[cuoi - 1].get("role") or "") != "assistant":
                continue
            for cot, day in (("strict_hash", h_strict), ("fuzzy_hash", h_fuzzy)):
                khoa = _hash_day(model, day[:cuoi])
                with self._lock:
                    row = self._con.execute(
                        "SELECT strict_hash, profile, metadata, so_tin FROM hoi_thoai"
                        " WHERE %s = ? ORDER BY cap_nhat DESC LIMIT 1" % cot,
                        (khoa,),
                    ).fetchone()
                if not row:
                    continue
                try:
                    meta = json.loads(row[2])
                except Exception:
                    continue
                if not meta or not meta[0]:
                    continue
                return {"strict_hash": row[0], "profile": row[1],
                        "metadata": meta, "so_tin": cuoi}
        return None

    def xoa(self, strict_hash: str) -> None:
        with self._lock:
            self._con.execute(
                "DELETE FROM hoi_thoai WHERE strict_hash = ?", (strict_hash,))
            self._con.commit()


_kho: Optional[KhoHoiThoaiGma] = None
_kho_lock = threading.Lock()


def kho_gma() -> KhoHoiThoaiGma:
    """Singleton, DB đặt tại {DATA_DIR}/gma_conversations.db (bền qua restart)."""
    global _kho
    with _kho_lock:
        if _kho is None:
            import os
            from services.config import DATA_DIR
            _kho = KhoHoiThoaiGma(os.path.join(str(DATA_DIR), "gma_conversations.db"))
        return _kho
