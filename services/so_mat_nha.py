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
from collections import Counter
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
#: Hai mẫu của cùng một người giống nhau từ mức này (0–100) thì là một mặt
#: chụp lại, không giữ cả hai.
NGUONG_TRUNG = 92.0
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
        # Vector của TỪNG lượt gặp (24/09/2026) — dọn «Mặt khác» so theo lượt,
        # không theo vector trung bình của cụm. `bo` rỗng = chưa bù.
        cot = {r[1] for r in conn.execute("PRAGMA table_info(su_kien)")}
        if "vector" not in cot:
            conn.execute("ALTER TABLE su_kien ADD COLUMN vector BLOB")
        if "bo" not in cot:
            conn.execute("ALTER TABLE su_kien ADD COLUMN bo TEXT NOT NULL DEFAULT ''")
        conn.commit()
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

def _doc_anh_su_kien(url: str) -> bytes | None:
    """Đọc ảnh của một lượt gặp từ thư viện ảnh camera.

    ``su_kien.anh`` là URL đầy đủ do ``canh_camera_nha._luu_anh_bao`` sinh, dạng
    ``…/images/YYYY/MM/DD/camera_mat_*.jpg``. Chỉ nhận đúng dạng ấy và chỉ đọc
    BÊN TRONG thư mục ảnh: đây là chuỗi lấy từ cơ sở dữ liệu, nên phải chặn đường
    dẫn lạ thay vì tin nó.
    """
    from urllib.parse import urlsplit

    from services.config import config

    duong = urlsplit(str(url or "")).path
    dau = "/images/"
    if not duong.startswith(dau):
        return None
    goc = config.images_dir.resolve()
    tep = (config.images_dir / duong[len(dau):]).resolve()
    if goc not in tep.parents or not tep.is_file():
        return None
    return tep.read_bytes()


def _do_them_cua_so(may, anh):
    """Dò lại bằng cửa sổ cỡ đầu vào của bộ dò, khi dò cả ảnh không ra mặt.

    Bộ dò luôn thu ảnh về 640. Ảnh chụp cả người thì mặt chiếm ít, thu xong
    mặt biến mất — đúng ảnh «mặt mở» đã lưu trước đây. Cửa sổ 640 giữ nguyên
    cỡ mặt. Toạ độ trả về là của ảnh gốc.
    """
    import numpy as np

    cao, rong = anh.shape[:2]
    cua = 640
    if max(cao, rong) <= int(cua * 1.2):
        return []
    buoc = cua // 2
    thay = []
    so_cua = 0
    y = 0
    while y < cao and so_cua < 12:
        x = 0
        while x < rong and so_cua < 12:
            manh = anh[y:y + cua, x:x + cua]
            if manh.shape[0] >= 80 and manh.shape[1] >= 80:
                so_cua += 1
                for m in may.do(manh):
                    x1, y1, x2, y2 = m.hop
                    m.hop = (x1 + x, y1 + y, x2 + x, y2 + y)
                    m.moc = np.asarray(m.moc, np.float32) + np.array([x, y], np.float32)
                    thay.append(m)
            if x + cua >= rong:
                break
            x += buoc
        if y + cua >= cao:
            break
        y += buoc
    return thay


def _mat_to_nhat(may, anh, *, cua_so: bool = True):
    """Mặt to nhất (theo diện tích) và mặt cỡ thứ hai — cho bước dò lại.

    ``cua_so=False`` khi tính lại vector đã lưu: ảnh hỏng thì một lần dò là
    đủ, không quét thêm mười hai cửa sổ cho mỗi dòng.
    """
    mats = list(may.do(anh)) if anh is not None else []
    if not mats and cua_so and anh is not None:
        mats = _do_them_cua_so(may, anh)
    mats.sort(key=lambda m: -(m.rong * m.cao))
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
        mat = _mat_to_nhat(may, anh, cua_so=False)[0] if anh is not None else None
        if mat is None:
            hong += 1
            # Đánh dấu đúng bộ model này đã thử và hỏng. Lần nạp sau không dò
            # lại cùng ảnh — đo trên máy chủ 23/09/2026: 22 cụm mặt khác hỏng
            # bị dò lại mỗi lần bấm, nút xong mà việc không chạy.
            conn.execute(
                f"UPDATE {bang} SET bo = ? WHERE id = ?",  # noqa: S608
                (f"{may.bo.ma}#hong", r["id"]))
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
        # Dòng ``bộ#hong`` là ảnh đã thử với đúng bộ này và không ra mặt.
        lech = conn.execute(
            "SELECT COUNT(*) FROM mat WHERE bo != ? AND bo != ?",
            (bo, f"{bo}#hong")).fetchone()[0]
        lech_la = conn.execute(
            "SELECT COUNT(*) FROM mat_la WHERE bo != ? AND bo != ?",
            (bo, f"{bo}#hong")).fetchone()[0]
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
            "tran_khac": None,
        }
        ids = _bang["nguoi_id"]
        if len(set(ids)) >= 2:
            a = np.asarray(ids)
            diem = _bang["ma_tran"] @ _bang["ma_tran"].T * 100.0
            _bang["tran_khac"] = float(diem[a[:, None] != a[None, :]].max())
        return _bang


# NGƯỠNG "CÓ THỂ" TỰ CHỈNH THEO CAMERA NHÀ (chủ máy 24/09/2026: "không so sánh
# khuôn mặt khi nhận được khuôn mặt mới, trùng của ai thì cho vào lịch sử người
# đó"). IRIS (anhnvme/facedetect) dùng 40/55 nhưng dặn "calibrate them against
# the actual cameras". Đo 24/09/2026 trên 17 ảnh mẫu (buffalo_l, đều cắt từ
# camera): hai ảnh CÙNG người giống 14–57, hai người KHÁC nhau cao nhất 29 — ở
# 40, phần lớn lượt của người nhà rơi vào «Mặt khác» (9 cụm ≥40 và 22 cụm 30–40
# kiểm bằng mắt: từ 35 trở lên gần như đều đúng người, dưới 35 bắt đầu sai).
# Nguyên tắc thay cho con số: ngưỡng nằm TRÊN mọi cặp khác người đã biết một
# biên an toàn; không vượt cấu hình, không dưới sàn. Thêm mẫu là tự tính lại.
_BIEN_AN_TOAN = 6.0
_SAN_CO_THE = 30.0


def nguong_hieu_luc(bang: dict[str, Any] | None = None) -> tuple[float, float]:
    """``(có thể là, chắc chắn)`` dùng thật — mọi nơi so mặt đều gọi hàm này."""
    from services import nhin_nha

    co_the, chac = nhin_nha.nguong_mat()
    tran = (bang or _nap_bang()).get("tran_khac")
    if tran is not None:
        co_the = min(co_the, max(_SAN_CO_THE, tran + _BIEN_AN_TOAN))
    return co_the, max(co_the, chac)


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

    bang = _nap_bang()
    co_the, chac = nguong_hieu_luc(bang)
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


def _bo_ban_trung(conn: sqlite3.Connection, nguoi_id: str) -> list[str]:
    """Xoá mẫu trùng của một người. Giữ bản cũ hơn, bỏ bản thêm sau.

    Trả đường ảnh của các mẫu đã xoá để người gọi xoá file.
    """
    import numpy as np

    from services import nhin_nha

    rows = conn.execute(
        "SELECT id, vector, anh FROM mat WHERE nguoi_id = ? AND bo = ? ORDER BY tao_luc",
        (nguoi_id, nhin_nha.bo_mat().ma)).fetchall()
    giu: list = []
    bo: list[str] = []
    for r in rows:
        v = _vec(r["vector"])
        if any(float(np.dot(v, u)) * 100.0 >= NGUONG_TRUNG for u in giu):
            conn.execute("DELETE FROM mat WHERE id = ?", (r["id"],))
            if r["anh"]:
                bo.append(r["anh"])
        else:
            giu.append(v)
    return bo


def day(ten: str, du_lieu_anh: bytes, *, nguon: str = "chat", ep: bool = False,
        xet_lai: bool = True) -> dict[str, Any]:
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
    if 0.0 < mat.chuan < may.bo.chuan_toi_thieu:
        # Mẫu dạy xấu hỏng việc nhận cả người ấy về sau (xem `BoMat.chuan_toi_thieu`).
        raise LoiSoMat("Mặt trong ảnh mờ, cúi hoặc bị che quá — máy không nhận ra được. "
                       "Gửi ảnh nhìn rõ mặt hơn ạ.")

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
        truoc = conn.execute("SELECT COUNT(*) FROM mat WHERE nguoi_id = ?",
                             (nguoi_id,)).fetchone()[0]
        _them_mat(conn, nguoi_id, may, anh, mat, nguon)
        anh_trung = _bo_ban_trung(conn, nguoi_id)
        conn.commit()
        so_mat = conn.execute("SELECT COUNT(*) FROM mat WHERE nguoi_id = ?",
                              (nguoi_id,)).fetchone()[0]
        _bo_bang()
    for rel in anh_trung:
        _xoa_anh(rel)
    trung = so_mat <= truoc
    # Chỉ xét lại mặt khác khi sổ mẫu thực sự đổi. Ảnh trùng không đổi kết quả
    # mà quét hết cụm làm nút bấm đứng lâu rồi tưởng là không xử lý.
    xet = xet_lai_mat_la() if xet_lai and not trung else []
    logger.info({"event": "so_mat_day", "nguoi_id": nguoi_id, "moi": moi,
                 "so_mat": so_mat, "nguon": nguon, "trung": trung, "xet_lai": len(xet)})
    return {"nguoi_id": nguoi_id, "ten": ten if moi else cu["ten"], "nguoi_moi": moi,
            "so_mat": so_mat, "diem_do": round(mat.diem, 3), "trung": trung,
            "xet_lai": len(xet)}


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


def _moc_ra(moc) -> list[list[float]]:
    """Năm điểm mốc thành số. Mốc giả trong test (một chuỗi tên) thì bỏ."""
    try:
        if len(moc) != 5:
            return []
        return [[float(p[0]), float(p[1])] for p in moc]
    except (TypeError, ValueError, IndexError):
        return []


def nhan_dien_anh(anh, may) -> dict[str, Any]:
    """Như ``nhan_dien`` nhưng nhận sẵn ảnh BGR và bộ máy (cho luồng canh camera)."""
    cao, rong = anh.shape[:2]
    ra = []
    for m in sorted(may.phan_tich(anh), key=lambda m: m.hop[0]):
        ra.append({"hop": [round(x) for x in m.hop], "diem_do": round(m.diem, 3),
                   "nho": min(m.rong, m.cao) < MAT_NHO_NHAT,
                   "mo": 0.0 < m.chuan < may.bo.chuan_toi_thieu,
                   "vector": m.vector, "moc": _moc_ra(m.moc), **khop(m.vector)})
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
    bang = _nap_bang()
    co_the, _ = nguong_hieu_luc(bang)
    with _khoa:
        conn = _db()
        if bang["la_id"]:
            diem = np.clip(bang["la_ma_tran"] @ v, 0.0, None) * 100.0
            i = int(diem.argmax())
            if float(diem[i]) >= co_the:
                ma = bang["la_id"][i]
                # KHÔNG cộng dồn vector: trung bình nhiều mặt mờ trôi về «mặt
                # trung bình» rồi hút mọi người (đo 24/09/2026). Vector cụm là
                # một mặt thật — mặt đầu tiên, `don_mat_la` đổi sang medoid.
                n = conn.execute("UPDATE mat_la SET lan_cuoi = ?, camera = ? WHERE id = ?",
                                 (time.time(), camera, ma)).rowcount
                if n:
                    conn.commit()
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
                anh: str = "", ts: float | None = None, vector=None) -> dict[str, Any]:
    """Ghi MỘT lượt gặp, tăng số lượt của người/cụm tương ứng.

    ``vector``: vector của chính mặt ấy — để `don_mat_la` so theo từng lượt.
    """
    import json

    from services import nhin_nha

    ts = float(ts or time.time())
    bo = nhin_nha.bo_mat().ma if vector is not None else ""
    with _khoa:
        conn = _db()
        cur = conn.execute(
            "INSERT INTO su_kien (ts, camera, nguon, loai, nguoi_id, mat_la_id, do_giong, hop, anh, "
            "vector, bo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, camera, nguon, loai, nguoi_id, mat_la_id, float(do_giong or 0),
             json.dumps([round(float(x)) for x in hop]), anh or "",
             _vec_bytes(vector) if vector is not None else None, bo))
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


def chuyen_su_kien(su_kien_id: int, ten: str, *, day_luon: bool = True) -> dict[str, Any]:
    """Gán lại MỘT lượt gặp trong lịch sử cho đúng người.

    Khác `dat_ten_mat_la` (ghi đè hàng loạt mọi lượt của một cụm như một tác dụng
    phụ): ở đây chủ nhà nhìn đúng một tấm ảnh rồi khẳng định đó là ai, nên sửa
    đúng dòng ấy. Vì thế `chuyen_mat` KHÔNG đụng lịch sử, còn hàm này thì có.

    Dời luôn số lượt gặp giữa hai người để `nguoi.so_lan` không đếm sai.
    """
    ten = " ".join(str(ten or "").split())
    if not ten:
        raise LoiSoMat("Chưa có tên người cho lượt gặp này.")
    if len(ten) > 60:
        raise LoiSoMat("Tên dài quá — tối đa 60 ký tự.")
    with _khoa:
        conn = _db()
        r = conn.execute("SELECT nguoi_id, mat_la_id, ts, anh FROM su_kien WHERE id = ?",
                         (int(su_kien_id),)).fetchone()
        if r is None:
            raise LoiSoMat(f"Không có lượt gặp số {su_kien_id}.")
        cu = _tim_nguoi_theo_ten(conn, ten)
        moi = cu is None
        nguoi_id = _ma() if moi else cu["id"]
        if moi:
            conn.execute("INSERT INTO nguoi (id, ten, tao_luc) VALUES (?, ?, ?)",
                         (nguoi_id, ten, time.time()))
        if r["nguoi_id"] and r["nguoi_id"] != nguoi_id:
            conn.execute("UPDATE nguoi SET so_lan = MAX(0, so_lan - 1) WHERE id = ?",
                         (r["nguoi_id"],))
            # `lan_cuoi` phải tính LẠI, không chỉ trừ lượt: nếu lượt vừa gán đi
            # đúng là lần gặp gần nhất của người cũ thì ô «gặp lần cuối» sẽ còn
            # trỏ vào một lượt không còn là của họ. Hết lượt thì thành NULL —
            # `danh_sach_nguoi` vốn cho phép rỗng.
            conn.execute("UPDATE nguoi SET lan_cuoi = "
                         "(SELECT MAX(ts) FROM su_kien WHERE nguoi_id = ? AND id != ?) "
                         "WHERE id = ?", (r["nguoi_id"], int(su_kien_id), r["nguoi_id"]))
        # Lượt này vốn đang tính cho một CỤM người lạ; nay đã biết là người quen
        # thì phải trả lượt lại cho cụm. Quên chỗ này thì `nen_hoi_mat_la` — vốn
        # quyết định hỏi tên đúng theo `so_lan` — sẽ hỏi sớm hơn mức đáng.
        if r["mat_la_id"]:
            conn.execute("UPDATE mat_la SET so_lan = MAX(0, so_lan - 1) WHERE id = ?",
                         (r["mat_la_id"],))
            # Và tính lại `lan_cuoi` của cụm vì cùng lý do — nó vừa hiện trên web
            # vừa là khoá xếp thứ tự (`danh_sach_mat_la` sắp theo `lan_cuoi`).
            # Cột này NOT NULL nên hết lượt thì lùi về `lan_dau`, khác `nguoi`.
            conn.execute("UPDATE mat_la SET lan_cuoi = COALESCE("
                         "(SELECT MAX(ts) FROM su_kien WHERE mat_la_id = ? AND id != ?), lan_dau) "
                         "WHERE id = ?", (r["mat_la_id"], int(su_kien_id), r["mat_la_id"]))
        if r["nguoi_id"] != nguoi_id:
            conn.execute("UPDATE nguoi SET so_lan = so_lan + 1, "
                         "lan_cuoi = MAX(COALESCE(lan_cuoi, 0), ?) WHERE id = ?",
                         (r["ts"], nguoi_id))
        conn.execute("UPDATE su_kien SET nguoi_id = ?, mat_la_id = NULL, loai = 'quen' "
                     "WHERE id = ?", (nguoi_id, int(su_kien_id)))
        conn.commit()
        _bo_bang()
    ten_that = ten if moi else cu["ten"]
    nguoi_cu = r["nguoi_id"]
    # `day_luon` tách lịch sử khỏi dữ liệu nhận diện. Tắt thì chỉ sửa dòng lịch
    # sử. Bật thì ảnh này vào mẫu của người đúng, và mẫu của người cũ nào đang
    # kéo nhầm mặt này thì bỏ — đó là lý do lần sau còn nhận sai.
    da_day, day_loi, bo_mau, trung = False, "", None, False
    if day_luon and r["anh"]:
        try:
            du_lieu = _doc_anh_su_kien(r["anh"])
            if du_lieu is None:
                day_loi = "không đọc được ảnh của lượt này"
            else:
                hoc = day(ten_that, du_lieu, nguon="camera", ep=True)
                trung = bool(hoc.get("trung"))
                da_day = not trung
                if da_day and nguoi_cu and nguoi_cu != nguoi_id:
                    vec = _vector_anh(du_lieu)
                    if vec is not None:
                        bo_mau = bo_mau_gay_nham(vec, nguoi_cu)
        except Exception as exc:
            day_loi = str(exc)[:120]
            logger.info({"event": "so_mat_chuyen_su_kien_day_loi", "loi": day_loi})
    logger.info({"event": "so_mat_chuyen_su_kien", "nguoi_moi": moi, "da_day": da_day,
                 "trung": trung, "bo_mau": bo_mau})
    return {"nguoi_id": nguoi_id, "ten": ten_that, "nguoi_moi": moi,
            "da_day": da_day, "day_loi": day_loi, "bo_mau": bo_mau, "trung": trung}


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
    # Vector là dữ liệu sinh trắc và là bytes — không đi ra API/web.
    return [{k: r[k] for k in r.keys() if k not in ("vector", "bo")} for r in rows]


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


def _vector_anh(du_lieu: bytes):
    """Vector mặt to nhất trong ảnh, hoặc None nếu không dò ra."""
    from services import nhin_nha, yolo_nha

    try:
        anh = yolo_nha.doc_anh(du_lieu)
    except ValueError:
        return None
    may = nhin_nha.mat()
    mat, _ = _mat_to_nhat(may, anh)
    if mat is None:
        return None
    may.vector(anh, mat)
    return mat.vector


def bo_mau_gay_nham(vector, nguoi_id: str) -> str | None:
    """Bỏ một ảnh mẫu của người vừa bị nhận nhầm, nếu ảnh đó giống mặt này.

    Chỉ bỏ mẫu gần nhất và chỉ khi độ giống đạt ngưỡng «có thể». Mẫu không
    liên quan thì giữ. Trả mã ảnh đã bỏ.
    """
    import numpy as np

    from services import nhin_nha

    v = np.asarray(vector, np.float32)
    co_the, _ = nguong_hieu_luc()
    with _khoa:
        rows = _db().execute(
            "SELECT id, vector FROM mat WHERE nguoi_id = ? AND bo = ?",
            (nguoi_id, nhin_nha.bo_mat().ma)).fetchall()
    if not rows:
        return None
    diem = sorted(((float(np.dot(_vec(r["vector"]), v)) * 100.0, r["id"]) for r in rows),
                  reverse=True)
    d, ma = diem[0]
    if d < co_the:
        return None
    xoa_mat(ma)
    return ma


def _gan_cum_vao_nguoi(ma: str, nguoi_id: str) -> tuple[int, str | None]:
    """Chuyển mọi lượt của cụm sang người, rồi xoá cụm. Trả (số lượt, ảnh cụm)."""
    with _khoa:
        conn = _db()
        la = conn.execute("SELECT lan_cuoi, anh FROM mat_la WHERE id = ?", (ma,)).fetchone()
        if la is None:
            return 0, None
        n = conn.execute(
            "UPDATE su_kien SET nguoi_id = ?, mat_la_id = NULL, loai = 'quen' WHERE mat_la_id = ?",
            (nguoi_id, ma)).rowcount
        if n:
            conn.execute(
                "UPDATE nguoi SET so_lan = so_lan + ?, "
                "lan_cuoi = MAX(COALESCE(lan_cuoi, 0), ?) WHERE id = ?",
                (n, la["lan_cuoi"], nguoi_id))
        conn.execute("DELETE FROM mat_la WHERE id = ?", (ma,))
        conn.commit()
        _bo_bang()
    return n, la["anh"]


# ── Dọn «Mặt khác» theo TỪNG LƯỢT GẶP ──────────────────────────────────────
#
# Chủ máy 24/09/2026: "tách mặt sai be bét… trùng của ai thì cho vào lịch sử
# người đó". Đo trên dữ liệu thật cùng ngày (570 lượt tính lại vector từ ảnh):
#
# * Cụm cũ giữ MỘT vector trung bình cộng dồn. Trung bình nhiều mặt mờ trôi về
#   «mặt trung bình»: cụm 44 lượt và cụm 28 lượt của HAI người khác nhau giống
#   nhau 67/100, nên gộp/xét theo vector cụm là trộn vợ, chồng, con vào một.
# * Từng mặt riêng lẻ thì khác hẳn: hai người khác nhau hiếm khi vượt 35.
#   Gom lượt gặp bằng điểm TRUNG BÌNH giữa các cặp (average linkage) ở ngưỡng
#   hiệu lực: bốn cụm lớn nhất đúng bốn người nhà, không cụm nào lẫn hai người
#   có tên; tường (bộ dò cũ bắt nhầm) tự thành cụm riêng.
# * Mỗi lượt lạ còn phải qua kNN: giống người ấy nhất theo ba mốc gần nhất và
#   đạt ngưỡng. Kiểm bỏ-một-ra trên 117 lượt «quen»: 117 đúng, 0 sai.
#
# MỐC chỉ là mẫu trong sổ và lượt «quen». Lượt do bước này chuyển về người ghi
# «co_the» nên KHÔNG thành mốc — không có vòng tự khẳng định (cùng bẫy `do_ai`
# của tầng học nhà).

#: Số lượt gần nhất (mỗi loại) đem ra gom một lần — n² bộ nhớ, dưới một giây.
_DON_TOI_DA = 1500
#: kNN: trung bình ba mốc giống nhất của mỗi người.
_K_GAN = 3
#: Cụm chỉ được coi là của một người khi người ấy chiếm ngần này phần mốc.
_DA_SO = 0.8
#: Cứ ngần này giây lúc rảnh thì bảo trì một lần; còn lượt chưa bù thì mau hơn.
BAO_TRI_GIAY = 300.0
BAO_TRI_KHI_BU_GIAY = 30.0
#: Mỗi lần bù ngần này lượt: đo 24/09/2026 trên máy chủ 0,65 giây/lượt, nên một
#: lần bù giữ luồng nhận mặt chừng sáu giây — người vừa tới không phải chờ lâu.
_BU_MOI_LAN = 10


def _gom_trung_binh(x, nguong: float) -> list[list[int]]:
    """Gom hàng của ``x`` (vector đơn vị) bằng average linkage, dừng dưới ``nguong``.

    Cập nhật Lance–Williams trên ma trận điểm: hai nhóm gộp thì điểm của nhóm
    mới với nhóm khác là trung bình có trọng số theo cỡ. KHÔNG nối chuỗi — A
    giống B, B giống C chưa đủ để A là C.
    """
    import numpy as np

    n = len(x)
    if n == 0:
        return []
    d = (x @ x.T * 100.0).astype(np.float64)
    np.fill_diagonal(d, -np.inf)
    co = np.ones(n)
    nhom: list[list[int]] = [[i] for i in range(n)]
    while n > 1:
        i, j = divmod(int(d.argmax()), n)
        if d[i, j] < nguong:
            break
        d[i, :] = (d[i, :] * co[i] + d[j, :] * co[j]) / (co[i] + co[j])
        d[:, i] = d[i, :]
        d[i, i] = -np.inf
        d[j, :] = -np.inf
        d[:, j] = -np.inf
        co[i] += co[j]
        nhom[i] += nhom[j]
        nhom[j] = []
    return [g for g in nhom if g]


def _vector_luot(may, anh):
    """Vector của mặt trong ảnh một lượt gặp đã lưu, hoặc None.

    Ảnh mới là mặt đã căn thẳng lấp đầy khung — bộ dò cần thấy cả viền quanh
    mặt, nên không ra thì đệm viền rồi dò lại. Ảnh cũ chụp cả người có thể lọt
    mặt người đứng cạnh: cùng luật với lúc dạy (`TO_GAP`), mặt to nhất phải to
    gấp đôi mặt thứ hai, không thì không đoán.
    """
    import cv2

    from services.khuon_mat_nha import moc_la_mat

    mat, thu_hai = _mat_to_nhat(may, anh, cua_so=False)
    if mat is None:
        cao, rong = anh.shape[:2]
        anh = cv2.copyMakeBorder(anh, cao // 2, cao // 2, rong // 2, rong // 2,
                                 cv2.BORDER_CONSTANT, value=0)
        mat, thu_hai = _mat_to_nhat(may, anh, cua_so=False)
    if mat is None or not moc_la_mat(mat.hop, mat.moc):
        return None
    if thu_hai is not None and mat.rong * mat.cao < TO_GAP * thu_hai.rong * thu_hai.cao:
        return None
    v = may.vector(anh, mat)
    # Mặt không nhận được (tường, gáy — xem `BoMat.chuan_toi_thieu`) không vào gom cụm.
    return None if 0.0 < mat.chuan < may.bo.chuan_toi_thieu else v


def bu_vector_su_kien(gioi_han: int = _BU_MOI_LAN) -> int:
    """Tính vector cho lượt gặp chưa có (ghi trước khi lưu vector, hoặc khác bộ
    model) từ ảnh đã lưu, mới nhất trước. Ảnh hỏng đánh dấu ``bộ#hong`` để không
    thử lại. Trả số lượt đã xử lý — 0 là đã bù xong."""
    from services import nhin_nha, yolo_nha

    may = nhin_nha.mat()
    bo = may.bo.ma
    with _khoa:
        rows = _db().execute(
            "SELECT id, anh FROM su_kien WHERE anh != '' AND bo != ? AND bo != ? "
            "ORDER BY ts DESC LIMIT ?", (bo, f"{bo}#hong", int(gioi_han))).fetchall()
    kq = []
    for r in rows:
        du_lieu = _doc_anh_su_kien(r["anh"])
        try:
            anh = yolo_nha.doc_anh(du_lieu) if du_lieu else None
        except ValueError:
            anh = None
        kq.append((r["id"], _vector_luot(may, anh) if anh is not None else None))
    if kq:
        with _khoa:
            conn = _db()
            for ma, v in kq:
                if v is None:
                    conn.execute("UPDATE su_kien SET bo = ? WHERE id = ?", (f"{bo}#hong", ma))
                else:
                    conn.execute("UPDATE su_kien SET bo = ?, vector = ? WHERE id = ?",
                                 (bo, _vec_bytes(v), ma))
            conn.commit()
    return len(kq)


def don_mat_la() -> dict[str, Any]:
    """Chuyển lượt «Mặt khác» (và «có thể là» của người khác) về đúng người, rồi
    xếp lại các lượt lạ còn lại thành cụm mỗi cụm một người.

    Chỉ đụng lượt đã có vector của bộ model hiện tại, và không đụng cụm chủ nhà
    đã bấm bỏ qua. Trả ``{"ve_nguoi": [{"ten", "so_luot"}], "cum": số cụm lạ}``.
    """
    import numpy as np

    bang = _nap_bang()
    bo = bang["bo"]
    co_the, _chac = nguong_hieu_luc(bang)
    with _khoa:
        conn = _db()
        moc = conn.execute(
            "SELECT nguoi_id, vector FROM su_kien WHERE loai = 'quen' AND nguoi_id IS NOT NULL "
            "AND bo = ? ORDER BY ts DESC LIMIT ?", (bo, _DON_TOI_DA)).fetchall()
        luot = conn.execute(
            "SELECT s.id, s.nguoi_id, s.mat_la_id, s.ts, s.vector FROM su_kien s "
            "LEFT JOIN mat_la m ON m.id = s.mat_la_id "
            "WHERE s.bo = ? AND ((s.mat_la_id IS NOT NULL AND m.bo_qua = 0) OR s.loai = 'co_the') "
            "ORDER BY s.ts DESC LIMIT ?", (bo, _DON_TOI_DA)).fetchall()
        ten = dict(conn.execute("SELECT id, ten FROM nguoi").fetchall())
    if not luot:
        return {"ve_nguoi": [], "cum": 0}
    nhan = list(bang["nguoi_id"]) + [r["nguoi_id"] for r in moc]
    x_moc = np.vstack([bang["ma_tran"], *[_vec(r["vector"]) for r in moc]]) if nhan else \
        np.zeros((0, 512), np.float32)
    x_luot = np.vstack([_vec(r["vector"]) for r in luot])
    so_moc = len(nhan)
    nhom = _gom_trung_binh(np.vstack([x_moc, x_luot]), co_the)

    nhan_arr = np.asarray(nhan)
    nguoi = sorted(set(nhan))
    diem = x_luot @ x_moc.T * 100.0 if so_moc else np.zeros((len(luot), 0))

    def knn(k: int) -> tuple[str | None, float]:
        tot, cao = None, -1.0
        for p in nguoi:
            d = np.sort(diem[k, nhan_arr == p])[::-1][:_K_GAN]
            if len(d) and float(d.mean()) > cao:
                tot, cao = p, float(d.mean())
        return tot, cao

    chuyen: list[tuple[int, str, float]] = []      # (chỉ số lượt, người, điểm)
    nhom_la: list[list[int]] = []
    for g in nhom:
        cua_moc = [nhan[i] for i in g if i < so_moc]
        ca = [i - so_moc for i in g if i >= so_moc]
        chu = None
        if cua_moc:
            p, so = Counter(cua_moc).most_common(1)[0]
            chu = p if so >= _DA_SO * len(cua_moc) else None
        con: list[int] = []
        for k in ca:
            if chu is not None:
                p, d = knn(k)
                if p == chu and d >= co_the:
                    if luot[k]["nguoi_id"] != chu:
                        chuyen.append((k, chu, d))
                    continue
            if luot[k]["mat_la_id"]:
                con.append(k)
        if con:
            nhom_la.append(con)

    ve: Counter = Counter()
    anh_xoa: list[str] = []
    with _khoa:
        conn = _db()
        for k, p, d in chuyen:
            r = luot[k]
            conn.execute("UPDATE su_kien SET nguoi_id = ?, mat_la_id = NULL, loai = 'co_the', "
                         "do_giong = ? WHERE id = ?", (p, round(d, 1), r["id"]))
            if r["nguoi_id"]:
                conn.execute("UPDATE nguoi SET so_lan = MAX(0, so_lan - 1) WHERE id = ?",
                             (r["nguoi_id"],))
            conn.execute("UPDATE nguoi SET so_lan = so_lan + 1, "
                         "lan_cuoi = MAX(COALESCE(lan_cuoi, 0), ?) WHERE id = ?", (r["ts"], p))
            ve[p] += 1
        # Lượt lạ còn lại: mỗi nhóm một cụm. Nhóm lớn chọn trước cụm cũ chứa nhiều
        # lượt của nó nhất; cụm cũ đã có chủ thì nhóm sau lập cụm mới — cụm trộn
        # hai người được TÁCH, không chỉ được gộp.
        da_chon: set[str] = set()
        cham: set[str] = {luot[k]["mat_la_id"] for g in nhom_la for k in g}
        cham |= {luot[k]["mat_la_id"] for k, _p, _d in chuyen if luot[k]["mat_la_id"]}
        for g in sorted(nhom_la, key=len, reverse=True):
            dem = Counter(luot[k]["mat_la_id"] for k in g)
            dich = next((m for m, _ in dem.most_common() if m not in da_chon), None)
            v = x_luot[g]
            giua = g[int((v @ v.T).sum(axis=1).argmax())]      # medoid: không trôi
            if dich is None:
                dich = _ma()
                du_lieu = _doc_anh_su_kien(_anh_luot(conn, luot[giua]["id"]))
                cu = conn.execute("SELECT anh FROM mat_la WHERE id = ?",
                                  (luot[giua]["mat_la_id"],)).fetchone()
                anh = _luu_anh(du_lieu, "la") if du_lieu else (cu["anh"] if cu else "")
                conn.execute(
                    "INSERT INTO mat_la (id, bo, vector, anh, diem_do, so_lan, lan_dau, lan_cuoi, camera) "
                    "VALUES (?, ?, ?, ?, 0, 0, ?, ?, '')",
                    (dich, bo, _vec_bytes(x_luot[giua]), anh,
                     min(luot[k]["ts"] for k in g), max(luot[k]["ts"] for k in g)))
            else:
                conn.execute("UPDATE mat_la SET vector = ? WHERE id = ?",
                             (_vec_bytes(x_luot[giua]), dich))
            da_chon.add(dich)
            conn.executemany("UPDATE su_kien SET mat_la_id = ? WHERE id = ?",
                             [(dich, luot[k]["id"]) for k in g])
            cham.add(dich)
        for m in cham:
            n, dau, cuoi = conn.execute(
                "SELECT COUNT(*), MIN(ts), MAX(ts) FROM su_kien WHERE mat_la_id = ?", (m,)).fetchone()
            if n:
                conn.execute("UPDATE mat_la SET so_lan = ?, lan_dau = ?, lan_cuoi = ? WHERE id = ?",
                             (n, dau, cuoi, m))
            else:
                r = conn.execute("SELECT anh FROM mat_la WHERE id = ?", (m,)).fetchone()
                if r is not None:
                    anh_xoa.append(r["anh"])
                    conn.execute("DELETE FROM mat_la WHERE id = ?", (m,))
        conn.commit()
        _bo_bang()
    for rel in anh_xoa:
        if rel:
            _xoa_anh(rel)
    ra = [{"ten": ten.get(p, p), "so_luot": n} for p, n in ve.most_common()]
    if ra:
        logger.info({"event": "so_mat_don_mat_la", "ve_nguoi": sum(ve.values()),
                     "cum": len(nhom_la)})
    return {"ve_nguoi": ra, "cum": len(nhom_la)}


def _anh_luot(conn: sqlite3.Connection, su_kien_id: int) -> str:
    r = conn.execute("SELECT anh FROM su_kien WHERE id = ?", (su_kien_id,)).fetchone()
    return r["anh"] if r else ""


def xet_lai_mat_la() -> list[dict[str, Any]]:
    """Sau khi sổ mẫu đổi: lượt «Mặt khác» nào giờ là của một người thì vào lịch
    sử người đó. Cùng đường với bảo trì định kỳ (`don_mat_la`) — không còn xét
    theo vector trung bình của cụm (xem khối chú thích ở trên)."""
    return don_mat_la()["ve_nguoi"]


def bao_tri() -> dict[str, Any]:
    """Việc nền lúc rảnh: bù vector cho lượt cũ, rồi dọn «Mặt khác»."""
    bu = bu_vector_su_kien()
    return {"bu_vector": bu, **don_mat_la()}


def chuyen_ve_khac(su_kien_id: int, *, hoc: bool = True) -> dict[str, Any]:
    """Đưa một lượt lịch sử về «Mặt khác». Học thì bỏ mẫu của người cũ gây nhầm."""
    with _khoa:
        conn = _db()
        r = conn.execute("SELECT nguoi_id, ts, anh FROM su_kien WHERE id = ?",
                         (int(su_kien_id),)).fetchone()
        if r is None:
            raise LoiSoMat(f"Không có lượt gặp số {su_kien_id}.")
        nguoi_cu = r["nguoi_id"]
        if nguoi_cu:
            conn.execute("UPDATE nguoi SET so_lan = MAX(0, so_lan - 1) WHERE id = ?", (nguoi_cu,))
            conn.execute("UPDATE nguoi SET lan_cuoi = "
                         "(SELECT MAX(ts) FROM su_kien WHERE nguoi_id = ? AND id != ?) "
                         "WHERE id = ?", (nguoi_cu, int(su_kien_id), nguoi_cu))
        conn.execute("UPDATE su_kien SET nguoi_id = NULL, mat_la_id = NULL, loai = 'la' "
                     "WHERE id = ?", (int(su_kien_id),))
        conn.commit()
        _bo_bang()
    bo_mau = None
    if hoc and nguoi_cu and r["anh"]:
        du_lieu = _doc_anh_su_kien(r["anh"])
        vec = _vector_anh(du_lieu) if du_lieu else None
        if vec is not None:
            bo_mau = bo_mau_gay_nham(vec, nguoi_cu)
    return {"nguoi_id": None, "ten": None, "da_day": False, "bo_mau": bo_mau}


def dat_ten_mat_la(ma: str, ten: str, *, hoc: bool = True) -> dict[str, Any]:
    """Mặt khác này là ``ten``.

    ``hoc`` bật: ảnh cụm vào dữ liệu nhận diện rồi xét lại các cụm còn lại.
    ``hoc`` tắt: chỉ đưa các lượt chụp vào lịch sử của người đó.
    """
    ten = " ".join(str(ten or "").split())
    if not ten:
        raise LoiSoMat("Chưa có tên người cho mặt này.")
    r = mat_la(ma)
    if r is None:
        raise LoiSoMat(f"Không có mặt lạ mã «{ma}».")
    kq: dict[str, Any] = {"nguoi_id": "", "ten": ten, "nguoi_moi": False, "so_mat": 0, "xet_lai": 0}
    if hoc:
        p = duong_anh(r["anh"])
        if p is None:
            raise LoiSoMat("Ảnh của mặt lạ này đã mất, không dạy được.")
        # ep=True: chính chủ nhà vừa nói đây là ai — không hỏi lại «giống người khác».
        kq = day(ten, p.read_bytes(), nguon="camera", ep=True, xet_lai=False)
    else:
        with _khoa:
            conn = _db()
            cu = _tim_nguoi_theo_ten(conn, ten)
            moi = cu is None
            nguoi_id = _ma() if moi else cu["id"]
            if moi:
                conn.execute("INSERT INTO nguoi (id, ten, tao_luc) VALUES (?, ?, ?)",
                             (nguoi_id, ten, time.time()))
                conn.commit()
            kq = {"nguoi_id": nguoi_id, "ten": ten if moi else cu["ten"],
                  "nguoi_moi": moi, "so_mat": 0, "xet_lai": 0}
    # `day` có thể đã xét lại và chuyển cụm này. Còn thì chuyển nốt.
    if mat_la(ma) is not None:
        n, rel = _gan_cum_vao_nguoi(ma, kq["nguoi_id"])
        if rel:
            _xoa_anh(rel)
        kq = {**kq, "so_luot": n}
    else:
        kq = {**kq, "so_luot": 0}
    if hoc and not kq.get("trung"):
        kq = {**kq, "xet_lai": len(xet_lai_mat_la())}
    return kq


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
