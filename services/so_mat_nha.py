"""Sổ khuôn mặt — ai là ai, mặt lạ nào hay gặp, camera thấy ai lúc nào.

Cách nhận giống IRIS (github.com/anhnvme/facedetect, ``main.py``
``recognize_image_bytes``): mỗi người giữ vài vector tham chiếu, mặt mới so
cosine với TỪNG vector, lấy người giống nhất. Từ ngưỡng «có thể là» (40) trở
lên là ứng viên, từ ngưỡng «chắc» (55) là nhận luôn — dưới 40 là người lạ.

Khác IRIS ở ba chỗ, đều vì camera nhà khác ảnh tải lên tay:

* IRIS chỉ lấy mặt TO NHẤT trong ảnh. Camera phòng khách có cả nhà ngồi xem
  tivi, nên nhận diện ở đây trả MỌI mặt; chỉ lúc DẠY mới đòi một mặt rõ ràng.
* Mặt lạ gom thành CỤM (``mat_la``): cùng một người lạ đi qua cổng mười lần
  là một cụm mười lượt, không phải mười người — để «hỏi tên mặt lạ hay gặp»
  hỏi đúng một lần.
* Mỗi vector ghi kèm ``bo`` (bộ model đã tính nó). Vector buffalo_s và
  buffalo_l không so với nhau được, nên đổi bộ thì tính lại từ ảnh mặt đã lưu
  — y như IRIS ``rebuild_model_embeddings``.

Ảnh mặt là dữ liệu sinh trắc — chỉ nằm trong ``data/agent/khuon_mat/``, không
gửi model, không in ra log.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_DB_PATH = Path(DATA_DIR) / "agent" / "khuon_mat.sqlite"
_THU_MUC_ANH = Path(DATA_DIR) / "agent" / "khuon_mat"

#: Mặt nhỏ hơn ngần này (px, cạnh ngắn của hộp) thì vector kém tin — không dạy.
MAT_NHO_NHAT = 40
#: Dạy từ ảnh nhiều mặt: mặt to nhất phải to gấp ngần này mặt thứ hai mới chắc
#: là mặt người được nêu tên. Ngang nhau thì hỏi lại, không đoán.
TO_GAP = 2.0
#: Lề quanh hộp mặt khi cắt ảnh lưu — đủ rộng để dò lại mặt lúc đổi bộ model.
_LE = 0.6

_khoa = threading.RLock()
_conn: sqlite3.Connection | None = None
_bang: dict[str, Any] | None = None     # vector tham chiếu đã nạp, theo bộ model


class LoiSoMat(ValueError):
    """Không làm được — thông điệp đọc thẳng cho người dùng."""


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS nguoi ("
            " id TEXT PRIMARY KEY, ten TEXT NOT NULL, ghi_chu TEXT NOT NULL DEFAULT '',"
            " tao_luc REAL NOT NULL, lan_cuoi REAL, so_lan INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE IF NOT EXISTS mat ("
            " id TEXT PRIMARY KEY,"
            " nguoi_id TEXT NOT NULL REFERENCES nguoi(id) ON DELETE CASCADE,"
            " bo TEXT NOT NULL, vector BLOB NOT NULL, anh TEXT NOT NULL,"
            " diem_do REAL NOT NULL, nguon TEXT NOT NULL, tao_luc REAL NOT NULL);"
            "CREATE INDEX IF NOT EXISTS idx_mat_nguoi ON mat(nguoi_id);"
            "CREATE TABLE IF NOT EXISTS mat_la ("
            " id TEXT PRIMARY KEY, bo TEXT NOT NULL, vector BLOB NOT NULL,"
            " anh TEXT NOT NULL, diem_do REAL NOT NULL,"
            " so_lan INTEGER NOT NULL DEFAULT 1, lan_dau REAL NOT NULL,"
            " lan_cuoi REAL NOT NULL, camera TEXT NOT NULL DEFAULT '',"
            " da_hoi INTEGER NOT NULL DEFAULT 0, bo_qua INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE IF NOT EXISTS su_kien ("
            " id INTEGER PRIMARY KEY, ts REAL NOT NULL, camera TEXT NOT NULL,"
            " nguon TEXT NOT NULL, loai TEXT NOT NULL,"
            " nguoi_id TEXT, mat_la_id TEXT, do_giong REAL NOT NULL DEFAULT 0,"
            " hop TEXT NOT NULL DEFAULT '', anh TEXT NOT NULL DEFAULT '');"
            "CREATE INDEX IF NOT EXISTS idx_sk_ts ON su_kien(ts);"
            "CREATE INDEX IF NOT EXISTS idx_sk_nguoi ON su_kien(nguoi_id, ts);"
        )
        _conn = conn
    return _conn


def _ma() -> str:
    return uuid.uuid4().hex[:12]


def _gon_ten(ten: str) -> str:
    """Tên để so trùng: bỏ dấu, hạ chữ, gộp khoảng trắng."""
    from services.agent.vi_text import fold
    return " ".join(re.split(r"\s+", fold(ten).strip()))


def _vec_bytes(v) -> bytes:
    import numpy as np
    return np.asarray(v, np.float32).tobytes()


def _vec(b: bytes):
    import numpy as np
    return np.frombuffer(b, np.float32)


# ── Ảnh mặt ─────────────────────────────────────────────────────────────────

def _cat_mat(anh, hop: tuple[float, float, float, float]) -> bytes:
    """Cắt vùng mặt kèm lề rồi nén JPEG — đủ để dò lại mặt khi đổi bộ model."""
    import cv2

    cao, rong = anh.shape[:2]
    x1, y1, x2, y2 = hop
    le_x, le_y = (x2 - x1) * _LE, (y2 - y1) * _LE
    a, b = int(max(0, x1 - le_x)), int(max(0, y1 - le_y))
    c, d = int(min(rong, x2 + le_x)), int(min(cao, y2 + le_y))
    ok, buf = cv2.imencode(".jpg", anh[b:d, a:c], [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise LoiSoMat("không lưu được ảnh mặt")
    return buf.tobytes()


def _luu_anh(du_lieu: bytes, nhom: str) -> str:
    """Ghi ảnh mặt, trả đường dẫn TƯƠNG ĐỐI (trong sổ không giữ đường tuyệt đối)."""
    rel = f"{nhom}/{_ma()}.jpg"
    p = _THU_MUC_ANH / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(du_lieu)
    return rel


def duong_anh(rel: str) -> Path | None:
    """Đường tuyệt đối của ảnh mặt; chặn ``..`` — tên đi từ web vào."""
    if not rel or ".." in rel or rel.startswith("/"):
        return None
    p = _THU_MUC_ANH / rel
    return p if p.is_file() else None


def _xoa_anh(rel: str) -> None:
    p = duong_anh(rel)
    if p is not None:
        p.unlink(missing_ok=True)


# ── Vector tham chiếu ───────────────────────────────────────────────────────

def _mat_to_nhat(may, anh):
    """Mặt to nhất (theo diện tích) và mặt cỡ thứ hai — cho bước dò lại."""
    mats = sorted(may.do(anh), key=lambda m: -(m.rong * m.cao))
    return (mats[0] if mats else None), (mats[1] if len(mats) > 1 else None)


def _tinh_lai(conn: sqlite3.Connection, bang: str, may) -> int:
    """Tính lại vector của mọi dòng khác bộ model đang dùng. Trả số dòng hỏng."""
    from services import yolo_nha

    hong = 0
    for r in conn.execute(f"SELECT id, anh FROM {bang} WHERE bo != ?", (may.bo.ma,)).fetchall():  # noqa: S608
        p = duong_anh(r["anh"])
        try:
            anh = yolo_nha.doc_anh(p.read_bytes()) if p is not None else None
        except ValueError:
            anh = None
        mat = _mat_to_nhat(may, anh)[0] if anh is not None else None
        if mat is None:
            hong += 1
            logger.warning({"event": "so_mat_tinh_lai_hong", "bang": bang, "id": r["id"]})
            continue
        may.vector(anh, mat)
        conn.execute(f"UPDATE {bang} SET bo = ?, vector = ?, diem_do = ? WHERE id = ?",  # noqa: S608
                     (may.bo.ma, _vec_bytes(mat.vector), mat.diem, r["id"]))
    conn.commit()
    return hong


def _nap_bang() -> dict[str, Any]:
    """Ma trận vector tham chiếu của bộ model hiện tại (tính lại dòng lệch bộ)."""
    global _bang
    import numpy as np

    from services import nhin_nha

    bo = nhin_nha.bo_mat().ma
    with _khoa:
        if _bang is not None and _bang["bo"] == bo:
            return _bang
        conn = _db()
        lech = conn.execute("SELECT COUNT(*) FROM mat WHERE bo != ?", (bo,)).fetchone()[0]
        lech_la = conn.execute("SELECT COUNT(*) FROM mat_la WHERE bo != ?", (bo,)).fetchone()[0]
        if lech or lech_la:
            may = nhin_nha.mat()
            hong = _tinh_lai(conn, "mat", may) + _tinh_lai(conn, "mat_la", may)
            logger.info({"event": "so_mat_doi_bo", "bo": bo, "mat": lech,
                         "mat_la": lech_la, "hong": hong})
        rows = conn.execute(
            "SELECT m.id, m.nguoi_id, n.ten, m.vector FROM mat m "
            "JOIN nguoi n ON n.id = m.nguoi_id WHERE m.bo = ?", (bo,)).fetchall()
        la = conn.execute("SELECT id, vector FROM mat_la WHERE bo = ? AND bo_qua = 0",
                          (bo,)).fetchall()
        _bang = {
            "bo": bo,
            "nguoi_id": [r["nguoi_id"] for r in rows],
            "ten": [r["ten"] for r in rows],
            "ma_tran": (np.vstack([_vec(r["vector"]) for r in rows]) if rows
                        else np.zeros((0, 512), np.float32)),
            "la_id": [r["id"] for r in la],
            "la_ma_tran": (np.vstack([_vec(r["vector"]) for r in la]) if la
                           else np.zeros((0, 512), np.float32)),
        }
        return _bang


def _bo_bang() -> None:
    global _bang
    with _khoa:
        _bang = None


def khop(vector) -> dict[str, Any]:
    """So một vector với sổ. Trả ``{nguoi_id, ten, do_giong, loai}``.

    ``loai``: ``quen`` (≥ ngưỡng chắc), ``co_the`` (≥ ngưỡng có thể), ``la``.
    Người lạ vẫn trả ``do_giong`` của người giống nhất để web hiển thị.
    """
    import numpy as np

    from services import nhin_nha

    bang = _nap_bang()
    co_the, chac = nhin_nha.nguong_mat()
    if not bang["nguoi_id"]:
        return {"nguoi_id": None, "ten": None, "do_giong": 0.0, "loai": "la"}
    diem = np.clip(bang["ma_tran"] @ np.asarray(vector, np.float32), 0.0, None) * 100.0
    i = int(diem.argmax())
    d = float(diem[i])
    if d < co_the:
        return {"nguoi_id": None, "ten": None, "do_giong": round(d, 1), "loai": "la"}
    return {"nguoi_id": bang["nguoi_id"][i], "ten": bang["ten"][i],
            "do_giong": round(d, 1), "loai": "quen" if d >= chac else "co_the"}


# ── Người ───────────────────────────────────────────────────────────────────

def _tim_nguoi_theo_ten(conn: sqlite3.Connection, ten: str) -> sqlite3.Row | None:
    gon = _gon_ten(ten)
    for r in conn.execute("SELECT * FROM nguoi").fetchall():
        if _gon_ten(r["ten"]) == gon:
            return r
    return None


def _them_mat(conn: sqlite3.Connection, nguoi_id: str, may, anh, mat, nguon: str) -> str:
    rel = _luu_anh(_cat_mat(anh, mat.hop), "nguoi")
    ma = _ma()
    conn.execute(
        "INSERT INTO mat (id, nguoi_id, bo, vector, anh, diem_do, nguon, tao_luc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ma, nguoi_id, may.bo.ma, _vec_bytes(mat.vector), rel, mat.diem, nguon, time.time()))
    return ma


def day(ten: str, du_lieu_anh: bytes, *, nguon: str = "chat", ep: bool = False) -> dict[str, Any]:
    """Dạy: ảnh này là mặt của ``ten``. Người chưa có thì tạo, có rồi thì thêm mặt.

    Ném ``LoiSoMat`` khi ảnh không dạy được — không thấy mặt, mặt quá nhỏ, nhiều
    mặt ngang cỡ, hoặc mặt đã giống hẳn một NGƯỜI KHÁC (trừ khi ``ep``: dạy nhầm
    người là làm hỏng cả hai người trong sổ, nên phải hỏi lại trước).
    """
    from services import nhin_nha, yolo_nha

    ten = " ".join(str(ten or "").split())
    if not ten:
        raise LoiSoMat("Chưa có tên người trong ảnh.")
    if len(ten) > 60:
        raise LoiSoMat("Tên dài quá — tối đa 60 ký tự.")
    try:
        anh = yolo_nha.doc_anh(du_lieu_anh)
    except ValueError as exc:
        raise LoiSoMat("Không đọc được ảnh.") from exc

    may = nhin_nha.mat()
    mat, thu_hai = _mat_to_nhat(may, anh)
    if mat is None:
        raise LoiSoMat("Không thấy khuôn mặt nào trong ảnh.")
    if thu_hai is not None and mat.rong * mat.cao < TO_GAP * thu_hai.rong * thu_hai.cao:
        raise LoiSoMat("Ảnh có nhiều khuôn mặt cỡ ngang nhau — gửi ảnh chỉ có mặt "
                       f"{ten} (hoặc mặt {ten} to rõ nhất) ạ.")
    if min(mat.rong, mat.cao) < MAT_NHO_NHAT:
        raise LoiSoMat(f"Mặt trong ảnh nhỏ quá ({int(min(mat.rong, mat.cao))} px) — "
                       "gửi ảnh chụp gần hơn ạ.")
    may.vector(anh, mat)

    kq = khop(mat.vector)
    with _khoa:
        conn = _db()
        cu = _tim_nguoi_theo_ten(conn, ten)
        if (not ep and kq["loai"] == "quen" and kq["nguoi_id"]
                and (cu is None or kq["nguoi_id"] != cu["id"])):
            raise LoiSoMat(f"Mặt này giống «{kq['ten']}» tới {kq['do_giong']:.0f}/100 — "
                           f"chắc chắn đây là {ten} chứ ạ?")
        moi = cu is None
        nguoi_id = _ma() if moi else cu["id"]
        if moi:
            conn.execute("INSERT INTO nguoi (id, ten, tao_luc) VALUES (?, ?, ?)",
                         (nguoi_id, ten, time.time()))
        _them_mat(conn, nguoi_id, may, anh, mat, nguon)
        conn.commit()
        so_mat = conn.execute("SELECT COUNT(*) FROM mat WHERE nguoi_id = ?",
                              (nguoi_id,)).fetchone()[0]
        _bo_bang()
    logger.info({"event": "so_mat_day", "nguoi_id": nguoi_id, "moi": moi,
                 "so_mat": so_mat, "nguon": nguon})
    return {"nguoi_id": nguoi_id, "ten": ten if moi else cu["ten"], "nguoi_moi": moi,
            "so_mat": so_mat, "diem_do": round(mat.diem, 3)}


def nhan_dien(du_lieu_anh: bytes) -> dict[str, Any]:
    """Mọi khuôn mặt trong ảnh kèm người giống nhất. Trái sang phải.

    Trả ``{"rong", "cao", "mat": [{hop, diem_do, nguoi_id, ten, do_giong, loai,
    nho}]}``. ``nho=True``: mặt dưới ``MAT_NHO_NHAT`` px — kết quả kém tin.
    """
    from services import nhin_nha, yolo_nha

    try:
        anh = yolo_nha.doc_anh(du_lieu_anh)
    except ValueError as exc:
        raise LoiSoMat("Không đọc được ảnh.") from exc
    return nhan_dien_anh(anh, nhin_nha.mat())


def nhan_dien_anh(anh, may) -> dict[str, Any]:
    """Như ``nhan_dien`` nhưng nhận sẵn ảnh BGR và bộ máy (cho luồng canh camera)."""
    cao, rong = anh.shape[:2]
    ra = []
    for m in sorted(may.phan_tich(anh), key=lambda m: m.hop[0]):
        ra.append({"hop": [round(x) for x in m.hop], "diem_do": round(m.diem, 3),
                   "nho": min(m.rong, m.cao) < MAT_NHO_NHAT,
                   "vector": m.vector, **khop(m.vector)})
    return {"rong": rong, "cao": cao, "mat": ra}


def danh_sach_nguoi() -> list[dict[str, Any]]:
    with _khoa:
        rows = _db().execute(
            "SELECT n.*, COUNT(m.id) AS so_mat, MIN(m.anh) AS anh FROM nguoi n "
            "LEFT JOIN mat m ON m.nguoi_id = n.id GROUP BY n.id ORDER BY n.ten").fetchall()
    return [{"id": r["id"], "ten": r["ten"], "ghi_chu": r["ghi_chu"], "so_mat": r["so_mat"],
             "anh": r["anh"] or "", "lan_cuoi": r["lan_cuoi"], "so_lan": r["so_lan"],
             "tao_luc": r["tao_luc"]} for r in rows]


def mat_cua(nguoi_id: str) -> list[dict[str, Any]]:
    with _khoa:
        rows = _db().execute("SELECT id, anh, diem_do, nguon, tao_luc FROM mat "
                             "WHERE nguoi_id = ? ORDER BY tao_luc", (nguoi_id,)).fetchall()
    return [dict(r) for r in rows]


def tim_nguoi(ten: str) -> dict[str, Any] | None:
    with _khoa:
        r = _tim_nguoi_theo_ten(_db(), ten)
    return dict(r) if r else None


def doi_ten(nguoi_id: str, ten: str) -> bool:
    ten = " ".join(str(ten or "").split())
    if not ten or len(ten) > 60:
        raise LoiSoMat("Tên phải có từ 1 tới 60 ký tự.")
    with _khoa:
        conn = _db()
        trung = _tim_nguoi_theo_ten(conn, ten)
        if trung is not None and trung["id"] != nguoi_id:
            raise LoiSoMat(f"Đã có người tên «{trung['ten']}».")
        n = conn.execute("UPDATE nguoi SET ten = ? WHERE id = ?", (ten, nguoi_id)).rowcount
        conn.commit()
        _bo_bang()
    return bool(n)


def xoa_nguoi(nguoi_id: str) -> bool:
    """Xoá người, mọi mặt của họ và ảnh trên đĩa. Sự kiện cũ giữ lại, mất tên."""
    with _khoa:
        conn = _db()
        anh = [r["anh"] for r in conn.execute("SELECT anh FROM mat WHERE nguoi_id = ?",
                                              (nguoi_id,)).fetchall()]
        n = conn.execute("DELETE FROM nguoi WHERE id = ?", (nguoi_id,)).rowcount
        conn.execute("UPDATE su_kien SET nguoi_id = NULL WHERE nguoi_id = ?", (nguoi_id,))
        conn.commit()
        _bo_bang()
    for rel in anh:
        _xoa_anh(rel)
    return bool(n)


def xoa_mat(mat_id: str) -> bool:
    with _khoa:
        conn = _db()
        r = conn.execute("SELECT anh FROM mat WHERE id = ?", (mat_id,)).fetchone()
        if r is None:
            return False
        conn.execute("DELETE FROM mat WHERE id = ?", (mat_id,))
        conn.commit()
        _bo_bang()
    _xoa_anh(r["anh"])
    return True


def _reset_for_tests() -> None:
    global _conn
    with _khoa:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn = None
        _bo_bang()
