"""Nhật ký kích hoạt thiết bị: mỗi lần bot BẬT / TẮT / HỎI / KHÔNG LÀM (và lần người tự bật tắt), kèm nguồn
kích hoạt (cảm biến, ngoại vi), điều kiện lúc đó và lý do.

Chủ máy 30/09/2026: "Thêm lịch sử kích hoạt thiết bị, kèm thêm nguyên nhân (thiết bị, ngoại vi, điều kiện)
tắt hay bật, hoặc không thực hiện, thời gian nào". Cùng ngày, câu "sao con tôi đi từ phòng học ra phòng khách
mà không bật đèn trần" phải lần qua bốn nguồn (lịch sử cảm biến, sổ dự đoán, mô hình học, nhật ký container đã
mất khi khởi động lại) vì lần bot IM không để lại dấu vết nào.

Khuôn theo `du_doan_nha`: SQLite WAL trong DATA_DIR, một kết nối, khoá. Ghi không bao giờ ném lỗi — nhật ký
hỏng không được làm hỏng việc bật tắt.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR
from utils.log import logger

_DB_PATH = Path(DATA_DIR) / "agent" / "nhat_ky_kich_hoat.sqlite"
_conn: Optional[sqlite3.Connection] = None
_khoa = threading.Lock()

#: Giữ ngần này ngày.
GIU_NGAY = 14
#: Cứ ngần này lần ghi thì dọn bản cũ một lần.
DON_MOI = 500
KET_QUA = ("lam", "hoi", "khong", "nguoi")
_dem = 0


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS nhat_ky ("
            " id INTEGER PRIMARY KEY,"
            " ts REAL NOT NULL,"
            " thiet_bi TEXT NOT NULL,"
            " hanh_dong TEXT NOT NULL,"      # on | off
            " ket_qua TEXT NOT NULL,"        # lam | hoi | khong | nguoi
            " nguon TEXT NOT NULL DEFAULT '',"   # cảm biến / ngoại vi / luật đã kích hoạt
            " ly_do TEXT NOT NULL DEFAULT '',"
            " dieu_kien TEXT)")              # JSON: giờ, độ sáng, xác suất…
        conn.execute("CREATE INDEX IF NOT EXISTS nhat_ky_ts ON nhat_ky(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS nhat_ky_tb ON nhat_ky(thiet_bi, ts)")
        _conn = conn
    return _conn


def ghi(thiet_bi: str, hanh_dong: str, ket_qua: str, *, nguon: str = "", ly_do: str = "",
        dieu_kien: dict[str, Any] | None = None, luc: float | None = None) -> None:
    """Ghi một lần xét. Không bao giờ ném lỗi."""
    global _dem
    try:
        luc = float(luc or time.time())
        with _khoa:
            db = _db()
            db.execute("INSERT INTO nhat_ky(ts, thiet_bi, hanh_dong, ket_qua, nguon, ly_do, dieu_kien)"
                       " VALUES (?,?,?,?,?,?,?)",
                       (luc, str(thiet_bi), str(hanh_dong), str(ket_qua), str(nguon or "")[:200],
                        str(ly_do or "")[:300],
                        json.dumps(dieu_kien, ensure_ascii=False, default=str)[:2000] if dieu_kien else None))
            _dem += 1
            if _dem % DON_MOI == 1:
                db.execute("DELETE FROM nhat_ky WHERE ts < ?", (time.time() - GIU_NGAY * 86400,))
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "nhat_ky_kich_hoat_loi", "error": str(exc)[:200]})


def doc(thiet_bi: str | None = None, *, gio: float = 24, ket_qua: str | None = None,
        gioi_han: int = 300) -> list[dict[str, Any]]:
    """Các lần xét trong ``gio`` giờ qua, mới nhất trước."""
    sql = "SELECT * FROM nhat_ky WHERE ts >= ?"
    tham: list[Any] = [time.time() - float(gio) * 3600]
    if thiet_bi:
        sql += " AND thiet_bi = ?"
        tham.append(thiet_bi)
    if ket_qua:
        sql += " AND ket_qua = ?"
        tham.append(ket_qua)
    sql += " ORDER BY ts DESC LIMIT ?"
    tham.append(max(1, min(int(gioi_han), 2000)))
    with _khoa:
        rows = _db().execute(sql, tham).fetchall()
    ra = []
    for r in rows:
        d = dict(r)
        try:
            d["dieu_kien"] = json.loads(d["dieu_kien"]) if d.get("dieu_kien") else {}
        except ValueError:
            d["dieu_kien"] = {}
        ra.append(d)
    return ra


def luat_chet(so_ngay: float = 5.0, toi_thieu_chan: int = 20) -> dict[str, list[int]]:
    """{thiết bị: [số trường hợp duyệt CHẾT]} — luật khớp nguồn (được xét) nhưng bị điều kiện chặn ≥ ``toi_thieu_chan``
    lần mà KHÔNG lần nào làm được trong ``so_ngay``. Dùng cho lịch tự đánh giá: luật chết thì giải lại (chủ máy
    04/10/2026: "bót định kỳ học lại, đánh giá để tối ưu")."""
    import re as _re
    from collections import defaultdict
    lam: dict[tuple[str, int], int] = defaultdict(int)
    chan: dict[tuple[str, int], int] = defaultdict(int)
    with _khoa:
        rows = _db().execute(
            "SELECT thiet_bi, ket_qua, ly_do FROM nhat_ky WHERE ts >= ? AND ly_do LIKE '%trường hợp duyệt #%'",
            (time.time() - float(so_ngay) * 86400,)).fetchall()
    for r in rows:
        m = _re.search(r"trường hợp duyệt #(\d+)", str(r["ly_do"] or ""))
        if not m:
            continue
        khoa = (str(r["thiet_bi"]), int(m.group(1)))
        if r["ket_qua"] == "lam":
            lam[khoa] += 1
        elif r["ket_qua"] == "khong" and "chưa đủ điều kiện" in str(r["ly_do"] or ""):
            chan[khoa] += 1
    ra: dict[str, list[int]] = defaultdict(list)
    for (tb, so), n in chan.items():
        if n >= toi_thieu_chan and lam.get((tb, so), 0) == 0:
            ra[tb].append(so)
    return {tb: sorted(set(ds)) for tb, ds in ra.items()}


def luat_dao_dong(so_ngay: float = 7.0, cua_so_giay: float = 300.0, toi_thieu: int = 3) -> dict[str, dict[int, int]]:
    """{thiết bị: {số luật: số lần}} — luật BẬT mà bị đảo lại (tắt) trong ``cua_so_giay`` giây, ≥ ``toi_thieu`` lần.
    Bật rồi phải tắt ngay = bật quá sớm (người đi ngang, không ở lại). Bot tự thấy từ nhật ký, không cần ai chấm —
    chủ máy 04/10/2026: "bot tự hiểu và đánh giá có chu kỳ để giảm dần sai lầm". Chỉ tính lần bot TỰ làm (lam)."""
    import re as _re
    from collections import defaultdict
    with _khoa:
        rows = _db().execute(
            "SELECT ts, thiet_bi, hanh_dong, ly_do FROM nhat_ky WHERE ket_qua='lam' AND ts >= ? ORDER BY thiet_bi, ts",
            (time.time() - float(so_ngay) * 86400,)).fetchall()
    theo_tb: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    for r in rows:
        theo_tb[str(r["thiet_bi"])].append((float(r["ts"]), str(r["hanh_dong"]), str(r["ly_do"] or "")))
    ra: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for tb, ev in theo_tb.items():
        for i in range(len(ev) - 1):
            ts, hd, ly = ev[i]
            ts2, hd2, _ = ev[i + 1]
            if hd == "on" and hd2 == "off" and ts2 - ts <= cua_so_giay:
                m = _re.search(r"trường hợp duyệt #(\d+)", ly)
                if m:
                    ra[tb][int(m.group(1))] += 1
    return {tb: {s: n for s, n in d.items() if n >= toi_thieu} for tb, d in ra.items()
            if any(n >= toi_thieu for n in d.values())}


def _reset_for_tests(duong: Path) -> None:
    global _conn, _DB_PATH, _dem
    if _conn is not None:
        _conn.close()
    _conn, _DB_PATH, _dem = None, duong, 0
