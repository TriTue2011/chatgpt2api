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


def chuyen_mat(mat_id: str, ten: str) -> dict[str, Any]:
    """Chuyển MỘT khuôn mặt sang người khác — đường sửa khi nhận nhầm.

    Mặt vào sổ qua ``dat_ten_mat_la`` (chủ nhà đặt tên cho một cụm camera gom
    được), mà cụm có thể lẫn người: đo 17/09/2026 trên 60 cụm thật, 4 cụm có
    ảnh bên trong chỉ giống nhau 18–25 điểm. Đặt nhầm là chuyện có thật, nên
    phải có đường sửa.

    Đổi chủ chứ không xoá-rồi-dạy-lại: ảnh camera không chụp lại được, xoá đi
    là mất hẳn. Người chưa có thì tạo. KHÔNG đụng ``su_kien`` cũ — chúng ghi
    việc ĐÃ xảy ra lúc ấy, sửa lại là viết lại lịch sử.
    """
    ten = " ".join(str(ten or "").split())
    if not ten:
        raise LoiSoMat("Chưa có tên người nhận khuôn mặt này.")
    if len(ten) > 60:
        raise LoiSoMat("Tên dài quá — tối đa 60 ký tự.")
    with _khoa:
        conn = _db()
        r = conn.execute("SELECT nguoi_id FROM mat WHERE id = ?", (mat_id,)).fetchone()
        if r is None:
            raise LoiSoMat(f"Không có khuôn mặt mã «{mat_id}».")
        cu = _tim_nguoi_theo_ten(conn, ten)
        moi = cu is None
        nguoi_id = _ma() if moi else cu["id"]
        if moi:
            conn.execute("INSERT INTO nguoi (id, ten, tao_luc) VALUES (?, ?, ?)",
                         (nguoi_id, ten, time.time()))
        conn.execute("UPDATE mat SET nguoi_id = ? WHERE id = ?", (nguoi_id, mat_id))
        conn.commit()
        so_mat = conn.execute("SELECT COUNT(*) FROM mat WHERE nguoi_id = ?",
                              (nguoi_id,)).fetchone()[0]
        con_lai = conn.execute("SELECT COUNT(*) FROM mat WHERE nguoi_id = ?",
                               (r["nguoi_id"],)).fetchone()[0]
        _bo_bang()
    logger.info({"event": "so_mat_chuyen_mat", "nguoi_moi": moi, "cu_con_lai": con_lai})
    return {"nguoi_id": nguoi_id, "ten": ten if moi else cu["ten"], "nguoi_moi": moi,
            "so_mat": so_mat, "cu_con_lai": con_lai}


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


# ── Mặt lạ (cụm) và sự kiện camera ──────────────────────────────────────────

#: Tâm cụm nhận vector mới với trọng số tối đa ngần này lượt: vẫn theo kịp khi
#: người đó đổi kiểu tóc, nhưng một khung xấu không kéo lệch hẳn cụm.
_TRONG_SO_CUM = 10
#: Hỏi tên một mặt lạ tối đa ngần này lần — cùng mức với `so_ten_nha._HOI_TOI_DA`.
HOI_TOI_DA = 3


def gom_mat_la(vector, anh, hop, camera: str) -> tuple[str, bool]:
    """Xếp một mặt lạ vào cụm giống nhất (từ ngưỡng «có thể là»), không có thì tạo.

    Trả ``(mã cụm, cụm mới?)``. KHÔNG tăng số lượt — lượt tính ở ``ghi_su_kien``,
    vì một lượt đứng trước camera là nhiều khung mà chỉ là một lần gặp.
    """
    import numpy as np

    from services import nhin_nha

    v = np.asarray(vector, np.float32)
    co_the, _ = nhin_nha.nguong_mat()
    bang = _nap_bang()
    with _khoa:
        conn = _db()
        if bang["la_id"]:
            diem = np.clip(bang["la_ma_tran"] @ v, 0.0, None) * 100.0
            i = int(diem.argmax())
            if float(diem[i]) >= co_the:
                ma = bang["la_id"][i]
                r = conn.execute("SELECT so_lan, vector FROM mat_la WHERE id = ?", (ma,)).fetchone()
                if r is not None:
                    tam = _vec(r["vector"]) * min(max(int(r["so_lan"]), 1), _TRONG_SO_CUM) + v
                    tam = (tam / np.linalg.norm(tam)).astype(np.float32)
                    conn.execute("UPDATE mat_la SET vector = ?, lan_cuoi = ?, camera = ? WHERE id = ?",
                                 (_vec_bytes(tam), time.time(), camera, ma))
                    conn.commit()
                    bang["la_ma_tran"][i] = tam
                    return ma, False
        ma = _ma()
        now = time.time()
        conn.execute(
            "INSERT INTO mat_la (id, bo, vector, anh, diem_do, so_lan, lan_dau, lan_cuoi, camera) "
            "VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?)",
            (ma, nhin_nha.bo_mat().ma, _vec_bytes(v), _luu_anh(_cat_mat(anh, hop), "la"),
             now, now, camera))
        conn.commit()
        _bo_bang()
    return ma, True


def ghi_su_kien(camera: str, nguon: str, loai: str, *, nguoi_id: str | None = None,
                mat_la_id: str | None = None, do_giong: float = 0.0, hop=(),
                anh: str = "", ts: float | None = None) -> dict[str, Any]:
    """Ghi MỘT lượt gặp, tăng số lượt của người/cụm tương ứng."""
    import json

    ts = float(ts or time.time())
    with _khoa:
        conn = _db()
        cur = conn.execute(
            "INSERT INTO su_kien (ts, camera, nguon, loai, nguoi_id, mat_la_id, do_giong, hop, anh) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, camera, nguon, loai, nguoi_id, mat_la_id, float(do_giong or 0),
             json.dumps([round(float(x)) for x in hop]), anh or ""))
        if nguoi_id:
            conn.execute("UPDATE nguoi SET lan_cuoi = ?, so_lan = so_lan + 1 WHERE id = ?",
                         (ts, nguoi_id))
        if mat_la_id:
            conn.execute("UPDATE mat_la SET so_lan = so_lan + 1, lan_cuoi = ? WHERE id = ?",
                         (ts, mat_la_id))
        conn.commit()
        ma = cur.lastrowid
    return {"id": ma, "ts": ts, "camera": camera, "nguon": nguon, "loai": loai,
            "nguoi_id": nguoi_id, "mat_la_id": mat_la_id}


def su_kien_gan(so_gio: float = 24.0, *, camera: str = "", nguoi_id: str = "",
                gioi_han: int = 50) -> list[dict[str, Any]]:
    """Sự kiện camera trong ``so_gio`` giờ qua, mới nhất trước, kèm tên người."""
    dk, tham = ["s.ts >= ?"], [time.time() - float(so_gio) * 3600]
    if camera:
        dk.append("s.camera = ?")
        tham.append(camera)
    if nguoi_id:
        dk.append("s.nguoi_id = ?")
        tham.append(nguoi_id)
    with _khoa:
        rows = _db().execute(
            "SELECT s.*, n.ten FROM su_kien s LEFT JOIN nguoi n ON n.id = s.nguoi_id "
            f"WHERE {' AND '.join(dk)} ORDER BY s.ts DESC LIMIT ?",  # noqa: S608 — chỉ ghép tên cột cố định
            (*tham, int(gioi_han))).fetchall()
    return [dict(r) for r in rows]


def mat_la(ma: str) -> dict[str, Any] | None:
    with _khoa:
        r = _db().execute("SELECT id, anh, so_lan, lan_dau, lan_cuoi, camera, da_hoi, bo_qua "
                          "FROM mat_la WHERE id = ?", (ma,)).fetchone()
    return dict(r) if r else None


def danh_sach_mat_la(*, ca_bo_qua: bool = False) -> list[dict[str, Any]]:
    with _khoa:
        rows = _db().execute(
            "SELECT id, anh, so_lan, lan_dau, lan_cuoi, camera, da_hoi, bo_qua FROM mat_la "
            + ("" if ca_bo_qua else "WHERE bo_qua = 0 ") + "ORDER BY lan_cuoi DESC").fetchall()
    return [dict(r) for r in rows]


def anh_su_kien_cua(mat_la_id: str, gioi_han: int = 8) -> list[str]:
    """Ảnh của TỪNG lượt gặp thuộc một cụm, mới nhất trước.

    Cụm chỉ giữ MỘT ảnh đại diện (``mat_la.anh``, chụp lúc cụm ra đời), nên nhìn
    vào đó không thể biết cụm có đang trộn hai người hay không. Ảnh từng lượt
    nằm ở ``su_kien.anh``; gom theo cụm thì soi được — đo 17/09/2026 trên 60 cụm
    thật: 4 cụm có ảnh trong cùng một cụm chỉ giống nhau 18–25 điểm, tức lẫn
    người.

    Trả nguyên giá trị ``su_kien.anh`` (URL tuyệt đối do luồng canh ghi); bên
    gọi tự đổi sang đường dẫn đĩa. Ảnh này nằm trong kho ảnh CHUNG, không phải
    kho khuôn mặt, nên bị dọn sau ``image_retention_days`` ngày — thư viện của
    cụm thưa dần theo thời gian, còn ảnh đại diện thì ở lại.
    """
    with _khoa:
        rows = _db().execute(
            "SELECT anh FROM su_kien WHERE mat_la_id = ? AND anh != '' "
            "ORDER BY ts DESC LIMIT ?", (mat_la_id, max(1, int(gioi_han)))).fetchall()
    return [r["anh"] for r in rows]


def nen_hoi_mat_la(ma: str, sau_so_lan: int) -> bool:
    """Hỏi tên khi đủ ``sau_so_lan`` lượt; mỗi lần hỏi rồi thì đợi thêm chừng ấy lượt.

    3, 6, 9 lượt với mặc định — hỏi tối đa ``HOI_TOI_DA`` lần, rồi thôi hẳn: nài
    mãi một người không ai nhận là làm phiền (cùng lý lẽ `so_ten_nha`).
    """
    r = mat_la(ma)
    if not r or r["bo_qua"] or int(r["da_hoi"]) >= HOI_TOI_DA:
        return False
    return int(r["so_lan"]) >= max(1, int(sau_so_lan)) * (int(r["da_hoi"]) + 1)


def danh_dau_da_hoi(ma: str) -> None:
    with _khoa:
        conn = _db()
        conn.execute("UPDATE mat_la SET da_hoi = da_hoi + 1 WHERE id = ?", (ma,))
        conn.commit()


def thoi_hoi_mat_la(ma: str) -> bool:
    """Chủ nhà bảo «người lạ, đừng hỏi nữa» — cụm vẫn giữ để gộp lượt, nhưng im."""
    with _khoa:
        conn = _db()
        n = conn.execute("UPDATE mat_la SET bo_qua = 1 WHERE id = ?", (ma,)).rowcount
        conn.commit()
        _bo_bang()
    return bool(n)


def dat_ten_mat_la(ma: str, ten: str) -> dict[str, Any]:
    """Mặt lạ này là ``ten``: dạy mặt từ ảnh cụm, chuyển mọi lượt cũ sang người đó."""
    r = mat_la(ma)
    if r is None:
        raise LoiSoMat(f"Không có mặt lạ mã «{ma}».")
    p = duong_anh(r["anh"])
    if p is None:
        raise LoiSoMat("Ảnh của mặt lạ này đã mất, không dạy được.")
    # ep=True: chính chủ nhà vừa nói đây là ai — không hỏi lại «giống người khác».
    kq = day(ten, p.read_bytes(), nguon="camera", ep=True)
    with _khoa:
        conn = _db()
        n = conn.execute("UPDATE su_kien SET nguoi_id = ?, mat_la_id = NULL, loai = 'quen' "
                         "WHERE mat_la_id = ?", (kq["nguoi_id"], ma)).rowcount
        conn.execute("UPDATE nguoi SET so_lan = so_lan + ?, lan_cuoi = MAX(COALESCE(lan_cuoi, 0), ?) "
                     "WHERE id = ?", (n, r["lan_cuoi"], kq["nguoi_id"]))
        conn.execute("DELETE FROM mat_la WHERE id = ?", (ma,))
        conn.commit()
        _bo_bang()
    _xoa_anh(r["anh"])
    return {**kq, "so_luot": n}


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
