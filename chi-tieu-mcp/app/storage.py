"""Lưu trữ SQLite cho chi tiêu — độc lập hoàn toàn với data dir của C2A."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from app.config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chi_tieu (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thoi_gian TEXT NOT NULL,          -- ISO 8601, giờ ghi nhận
    hu_ma TEXT NOT NULL,              -- mã hũ, vd 'thiet_yeu'
    so_tien INTEGER NOT NULL,         -- VNĐ, số nguyên dương
    ghi_chu TEXT DEFAULT '',
    nguon TEXT DEFAULT 'zalo',        -- kênh ghi nhận: zalo / manual
    thang TEXT NOT NULL DEFAULT ''    -- 'YYYY-MM', nhãn chu kỳ ĐÓNG BĂNG tại thời điểm ghi
);

CREATE TABLE IF NOT EXISTS canh_bao_da_gui (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thang TEXT NOT NULL,              -- 'YYYY-MM'
    hu_ma TEXT NOT NULL,
    nguong REAL NOT NULL,             -- 0.65 / 0.8 / 1.0
    thoi_gian TEXT NOT NULL,
    UNIQUE(thang, hu_ma, nguong)
);

CREATE TABLE IF NOT EXISTS thu_nhap_them (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thoi_gian TEXT NOT NULL,          -- ISO 8601, giờ ghi nhận
    mo_ta TEXT DEFAULT '',
    so_tien INTEGER NOT NULL,         -- VNĐ, số nguyên dương
    thang TEXT NOT NULL DEFAULT ''    -- 'YYYY-MM', nhãn chu kỳ ĐÓNG BĂNG tại thời điểm ghi
);

CREATE TABLE IF NOT EXISTS cong_ty_giao_dich (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thoi_gian TEXT NOT NULL,          -- ISO 8601
    loai TEXT NOT NULL CHECK(loai IN ('tam_ung', 'chi')),
    so_tien INTEGER NOT NULL,         -- VNĐ, số nguyên dương
    mo_ta TEXT NOT NULL,              -- bắt buộc khác rỗng (validate ở tools.py)
    giai_chi_id INTEGER               -- NULL = thuộc kỳ đang mở; khác NULL = đã khoá
);

CREATE TABLE IF NOT EXISTS giai_chi_cong_ty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thoi_gian TEXT NOT NULL,
    tong_tam_ung INTEGER NOT NULL,
    tong_chi INTEGER NOT NULL,
    so_du INTEGER NOT NULL            -- tong_tam_ung - tong_chi tại thời điểm giải chi
);

CREATE TABLE IF NOT EXISTS chi_phi_dac_biet (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thang TEXT NOT NULL,              -- 'YYYY-MM', tháng ÁP DỤNG (có thể khác tháng khai báo thật)
    mo_ta TEXT NOT NULL,
    so_tien INTEGER NOT NULL,         -- VNĐ, số nguyên dương
    thoi_gian TEXT NOT NULL           -- ISO 8601, giờ khai báo thật
);
CREATE INDEX IF NOT EXISTS idx_chi_phi_dac_biet_thang
    ON chi_phi_dac_biet (thang);
"""


def _connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def khoi_tao_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        _migrate_them_cot_thang(conn)


def _migrate_them_cot_thang(conn: sqlite3.Connection) -> None:
    """Thêm cột `thang` vào chi_tieu/thu_nhap_them cho DB đã tồn tại TRƯỚC
    khi tính năng chu kỳ lương tuỳ chỉnh ra đời (2 bảng này tạo lần đầu
    không có cột này, chỉ dựa vào thoi_gian). Idempotent -- kiểm tra cột đã
    tồn tại chưa qua PRAGMA table_info trước khi ALTER TABLE (ALTER TABLE
    ADD COLUMN báo lỗi nếu cột đã có). Backfill dữ liệu cũ bằng
    substr(thoi_gian,1,7) -- tương đương ngay_bat_dau_chu_ky=1 luôn đúng
    cho MỌI dữ liệu ghi trước khi khái niệm chu kỳ tồn tại. An toàn gọi lại
    nhiều lần (mỗi lần app khởi động)."""
    for bang in ("chi_tieu", "thu_nhap_them"):
        cot_hien_co = {row["name"] for row in conn.execute(f"PRAGMA table_info({bang})")}
        if "thang" not in cot_hien_co:
            conn.execute(f"ALTER TABLE {bang} ADD COLUMN thang TEXT NOT NULL DEFAULT ''")
        conn.execute(f"UPDATE {bang} SET thang = substr(thoi_gian, 1, 7) WHERE thang = ''")
    conn.execute("DROP INDEX IF EXISTS idx_chi_tieu_hu_thang")
    conn.execute("CREATE INDEX idx_chi_tieu_hu_thang ON chi_tieu (hu_ma, thang)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thu_nhap_them_thang ON thu_nhap_them (thang)")


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ghi_chi_tieu(hu_ma: str, so_tien: int, ghi_chu: str = "", nguon: str = "zalo",
                  thang: str | None = None) -> int:
    thoi_gian = datetime.now().isoformat(timespec="seconds")
    if thang is None:
        # Mac dinh lich duong thuan -- CHI dung khi goi truc tiep storage.py
        # (vd test). Luong that (tools.ghi_chi_tieu) LUON truyen tuong minh
        # qua jars.thang_hien_tai() -- storage.py KHONG import jars.py de
        # tranh circular import (jars.py da import storage.py).
        thang = thoi_gian[:7]
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO chi_tieu (thoi_gian, hu_ma, so_tien, ghi_chu, nguon, thang) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (thoi_gian, hu_ma, so_tien, ghi_chu, nguon, thang),
        )
        return cur.lastrowid


def tong_chi_trong_thang(hu_ma: str, thang: str) -> int:
    """thang dạng 'YYYY-MM'."""
    with db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(so_tien), 0) AS tong FROM chi_tieu "
            "WHERE hu_ma = ? AND thang = ?",
            (hu_ma, thang),
        ).fetchone()
        return int(row["tong"])


def danh_sach_chi_trong_thang(thang: str) -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            "SELECT id, hu_ma, so_tien, ghi_chu, thoi_gian FROM chi_tieu "
            "WHERE thang = ? ORDER BY thoi_gian DESC",
            (thang,),
        ).fetchall()


def tong_chi_theo_hu_trong_thang(thang: str) -> dict[str, int]:
    """{ma_hu: tổng đã chi} của 1 nhãn kỳ -- hũ không có khoản nào thì không
    có key. Dùng cho biểu đồ theo kỳ trên /ui."""
    with db() as conn:
        rows = conn.execute(
            "SELECT hu_ma, SUM(so_tien) AS tong FROM chi_tieu WHERE thang = ? "
            "GROUP BY hu_ma",
            (thang,),
        ).fetchall()
    return {r["hu_ma"]: int(r["tong"]) for r in rows}


def tong_chi_theo_ngay_trong_thang(thang: str) -> list[tuple[str, int]]:
    """[(ngày 'YYYY-MM-DD', tổng chi ngày đó)] của 1 nhãn kỳ, tăng dần theo
    ngày -- ngày lấy từ thoi_gian (giờ máy chủ, TZ Asia/Ho_Chi_Minh)."""
    with db() as conn:
        rows = conn.execute(
            "SELECT substr(thoi_gian, 1, 10) AS ngay, SUM(so_tien) AS tong FROM chi_tieu "
            "WHERE thang = ? GROUP BY ngay ORDER BY ngay",
            (thang,),
        ).fetchall()
    return [(r["ngay"], int(r["tong"])) for r in rows]


def da_gui_canh_bao(thang: str, hu_ma: str, nguong: float) -> bool:
    with db() as conn:
        row = conn.execute(
            "SELECT 1 FROM canh_bao_da_gui WHERE thang=? AND hu_ma=? AND nguong=?",
            (thang, hu_ma, nguong),
        ).fetchone()
        return row is not None


def danh_dau_da_gui_canh_bao(thang: str, hu_ma: str, nguong: float) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO canh_bao_da_gui (thang, hu_ma, nguong, thoi_gian) "
            "VALUES (?, ?, ?, ?)",
            (thang, hu_ma, nguong, datetime.now().isoformat(timespec="seconds")),
        )


def sua_chi_tieu(id: int, so_tien: int | None = None, ghi_chu: str | None = None,
                  hu_ma: str | None = None) -> bool:
    """Sửa 1 khoản chi đã ghi. Chỉ field nào truyền (khác None) mới bị đổi.
    Trả False nếu id không tồn tại (khi có ít nhất 1 field để sửa).
    Nếu không truyền field nào, trả True luôn (không kiểm tra id)."""
    truong = []
    gia_tri: list = []
    if so_tien is not None:
        truong.append("so_tien = ?")
        gia_tri.append(so_tien)
    if ghi_chu is not None:
        truong.append("ghi_chu = ?")
        gia_tri.append(ghi_chu)
    if hu_ma is not None:
        truong.append("hu_ma = ?")
        gia_tri.append(hu_ma)
    if not truong:
        return True  # khong co gi de sua, coi nhu thanh cong
    gia_tri.append(id)
    with db() as conn:
        cur = conn.execute(f"UPDATE chi_tieu SET {', '.join(truong)} WHERE id = ?", gia_tri)
        return cur.rowcount > 0


def xoa_chi_tieu(id: int) -> bool:
    with db() as conn:
        cur = conn.execute("DELETE FROM chi_tieu WHERE id = ?", (id,))
        return cur.rowcount > 0


def chi_tieu_theo_id(id: int) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute(
            "SELECT id, thoi_gian, hu_ma, so_tien, ghi_chu, nguon, thang "
            "FROM chi_tieu WHERE id = ?",
            (id,),
        ).fetchone()


def tach_chi_tieu(id: int, danh_sach: list[dict]) -> list[int] | None:
    """Xoá dòng chi_tieu `id`, ghi các dòng mới trong danh_sach (mỗi phần tử
    {'hu_ma', 'so_tien', 'ghi_chu'}), giữ nguyên thoi_gian/thang/nguon của
    dòng gốc. Trả None nếu id không tồn tại (không xoá/ghi gì). Atomic (1
    with db() duy nhất) -- KHÔNG validate danh_sach, tools.py phải validate
    trước khi gọi tới đây."""
    with db() as conn:
        goc = conn.execute(
            "SELECT thoi_gian, thang, nguon FROM chi_tieu WHERE id = ?", (id,)
        ).fetchone()
        if goc is None:
            return None
        conn.execute("DELETE FROM chi_tieu WHERE id = ?", (id,))
        ids_moi = []
        for muc in danh_sach:
            cur = conn.execute(
                "INSERT INTO chi_tieu (thoi_gian, hu_ma, so_tien, ghi_chu, nguon, thang) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (goc["thoi_gian"], muc["hu_ma"], muc["so_tien"], muc.get("ghi_chu", ""),
                 goc["nguon"], goc["thang"]),
            )
            ids_moi.append(cur.lastrowid)
        return ids_moi


def ba_thang_lien_truoc(thang: str) -> list[str]:
    """3 tháng liền TRƯỚC `thang` (dạng 'YYYY-MM'), thứ tự gần nhất trước."""
    nam, thang_so = int(thang[:4]), int(thang[5:7])
    ket_qua = []
    for _ in range(3):
        thang_so -= 1
        if thang_so == 0:
            thang_so, nam = 12, nam - 1
        ket_qua.append(f"{nam:04d}-{thang_so:02d}")
    return ket_qua


def trung_binh_chi_3_thang_truoc(thang: str) -> int:
    """Trung bình tổng chi TẤT CẢ hũ trong 3 tháng liền trước `thang`. Tháng
    nào chưa có khoản chi nào thì tính là 0 — không loại tháng đó khỏi trung bình."""
    tong = sum(
        r["so_tien"]
        for t in ba_thang_lien_truoc(thang)
        for r in danh_sach_chi_trong_thang(t)
    )
    return round(tong / 3)


def trung_binh_chi_theo_hu_3_thang_truoc(thang: str) -> dict[str, int]:
    """Trung bình chi từng hũ trong 3 tháng liền trước `thang`. Trả về
    {ma_hu: trung_binh_vnd}; hũ không có khoản chi nào trong cả 3 tháng thì
    KHÔNG xuất hiện trong dict (coi như 0 khi dùng — gọi .get(ma, 0))."""
    tong_theo_hu: dict[str, int] = {}
    for t in ba_thang_lien_truoc(thang):
        for r in danh_sach_chi_trong_thang(t):
            tong_theo_hu[r["hu_ma"]] = tong_theo_hu.get(r["hu_ma"], 0) + r["so_tien"]
    return {ma: round(tong / 3) for ma, tong in tong_theo_hu.items()}


def ghi_thu_nhap_them(mo_ta: str, so_tien: int, thang: str | None = None) -> int:
    thoi_gian = datetime.now().isoformat(timespec="seconds")
    if thang is None:
        thang = thoi_gian[:7]
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO thu_nhap_them (thoi_gian, mo_ta, so_tien, thang) VALUES (?, ?, ?, ?)",
            (thoi_gian, mo_ta, so_tien, thang),
        )
        return cur.lastrowid


def tong_thu_nhap_them_trong_thang(thang: str) -> int:
    """thang dạng 'YYYY-MM'."""
    with db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(so_tien), 0) AS tong FROM thu_nhap_them "
            "WHERE thang = ?",
            (thang,),
        ).fetchone()
        return int(row["tong"])


def danh_sach_thu_nhap_them_trong_thang(thang: str) -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            "SELECT id, mo_ta, so_tien, thoi_gian FROM thu_nhap_them "
            "WHERE thang = ? ORDER BY thoi_gian DESC",
            (thang,),
        ).fetchall()


def sua_thu_nhap_them(id: int, so_tien: int | None = None, mo_ta: str | None = None) -> bool:
    """Sửa 1 khoản thu nhập phát sinh. Chỉ field nào truyền (khác None) mới
    bị đổi. Trả False nếu id không tồn tại (khi có ít nhất 1 field để sửa);
    không truyền field nào thì trả True -- cùng quy ước sua_chi_tieu."""
    truong = []
    gia_tri: list = []
    if so_tien is not None:
        truong.append("so_tien = ?")
        gia_tri.append(so_tien)
    if mo_ta is not None:
        truong.append("mo_ta = ?")
        gia_tri.append(mo_ta)
    if not truong:
        return True
    gia_tri.append(id)
    with db() as conn:
        cur = conn.execute(
            f"UPDATE thu_nhap_them SET {', '.join(truong)} WHERE id = ?", gia_tri
        )
        return cur.rowcount > 0


def xoa_thu_nhap_them(id: int) -> bool:
    with db() as conn:
        cur = conn.execute("DELETE FROM thu_nhap_them WHERE id = ?", (id,))
        return cur.rowcount > 0


def ghi_giao_dich_cong_ty(loai: str, so_tien: int, mo_ta: str) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO cong_ty_giao_dich (thoi_gian, loai, so_tien, mo_ta, giai_chi_id) "
            "VALUES (?, ?, ?, ?, NULL)",
            (datetime.now().isoformat(timespec="seconds"), loai, so_tien, mo_ta),
        )
        return cur.lastrowid


def so_du_cong_ty() -> int:
    with db() as conn:
        row = conn.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN loai='tam_ung' THEN so_tien ELSE 0 END), 0) - "
            "COALESCE(SUM(CASE WHEN loai='chi' THEN so_tien ELSE 0 END), 0) AS so_du "
            "FROM cong_ty_giao_dich WHERE giai_chi_id IS NULL"
        ).fetchone()
        return int(row["so_du"])


def danh_sach_giao_dich_cong_ty_dang_mo() -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            "SELECT id, thoi_gian, loai, so_tien, mo_ta FROM cong_ty_giao_dich "
            "WHERE giai_chi_id IS NULL ORDER BY thoi_gian DESC"
        ).fetchall()


def giao_dich_cong_ty_theo_id(id: int) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute(
            "SELECT id, thoi_gian, loai, so_tien, mo_ta, giai_chi_id "
            "FROM cong_ty_giao_dich WHERE id = ?",
            (id,),
        ).fetchone()


def sua_giao_dich_cong_ty(id: int, so_tien: int | None = None, mo_ta: str | None = None) -> bool:
    """Sửa 1 giao dịch công ty. Chỉ field nào truyền (khác None) mới bị đổi.
    Chỉ sửa được nếu giao dịch đang ở kỳ MỞ (giai_chi_id IS NULL) -- WHERE
    clause tự chặn, không cần transaction riêng để kiểm tra trước.
    Trả False nếu id không tồn tại HOẶC đã bị khoá bởi 1 lần giải chi.
    Nếu không truyền field nào, trả True luôn (không kiểm tra id) -- cùng
    quy ước như sua_chi_tieu() hiện có, tầng gọi (API) phải tự chặn body
    rỗng trước khi tới đây nếu muốn phân biệt 404."""
    truong = []
    gia_tri: list = []
    if so_tien is not None:
        truong.append("so_tien = ?")
        gia_tri.append(so_tien)
    if mo_ta is not None:
        truong.append("mo_ta = ?")
        gia_tri.append(mo_ta)
    if not truong:
        return True
    gia_tri.append(id)
    with db() as conn:
        cur = conn.execute(
            f"UPDATE cong_ty_giao_dich SET {', '.join(truong)} "
            "WHERE id = ? AND giai_chi_id IS NULL",
            gia_tri,
        )
        return cur.rowcount > 0


def xoa_giao_dich_cong_ty(id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM cong_ty_giao_dich WHERE id = ? AND giai_chi_id IS NULL", (id,)
        )
        return cur.rowcount > 0


def giai_chi() -> dict:
    """Đóng kỳ tạm ứng công ty đang mở: tính tổng, insert 1 dòng
    giai_chi_cong_ty, rồi khoá (gán giai_chi_id) toàn bộ giao dịch đang mở --
    TẤT CẢ trong 1 `with db() as conn` để không bao giờ để nửa chừng (tính
    tổng xong nhưng khoá giao dịch thất bại thì rollback toàn bộ, không có
    trạng thái lưng chừng)."""
    with db() as conn:
        tong = conn.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN loai='tam_ung' THEN so_tien ELSE 0 END), 0) AS tong_tam_ung, "
            "COALESCE(SUM(CASE WHEN loai='chi' THEN so_tien ELSE 0 END), 0) AS tong_chi "
            "FROM cong_ty_giao_dich WHERE giai_chi_id IS NULL"
        ).fetchone()
        tong_tam_ung, tong_chi = int(tong["tong_tam_ung"]), int(tong["tong_chi"])
        so_du = tong_tam_ung - tong_chi
        cur = conn.execute(
            "INSERT INTO giai_chi_cong_ty (thoi_gian, tong_tam_ung, tong_chi, so_du) "
            "VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), tong_tam_ung, tong_chi, so_du),
        )
        giai_chi_id = cur.lastrowid
        conn.execute(
            "UPDATE cong_ty_giao_dich SET giai_chi_id = ? WHERE giai_chi_id IS NULL",
            (giai_chi_id,),
        )
        return {"id": giai_chi_id, "tong_tam_ung": tong_tam_ung, "tong_chi": tong_chi, "so_du": so_du}


def giao_dich_theo_lan_giai_chi(giai_chi_id: int) -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            "SELECT id, thoi_gian, loai, so_tien, mo_ta FROM cong_ty_giao_dich "
            "WHERE giai_chi_id = ? ORDER BY thoi_gian",
            (giai_chi_id,),
        ).fetchall()


def danh_sach_lan_giai_chi() -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            "SELECT id, thoi_gian, tong_tam_ung, tong_chi, so_du "
            "FROM giai_chi_cong_ty ORDER BY thoi_gian DESC"
        ).fetchall()


def lan_giai_chi_theo_id(id: int) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute(
            "SELECT id, thoi_gian, tong_tam_ung, tong_chi, so_du "
            "FROM giai_chi_cong_ty WHERE id = ?",
            (id,),
        ).fetchone()


def ghi_chi_phi_dac_biet(thang: str, mo_ta: str, so_tien: int) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO chi_phi_dac_biet (thang, mo_ta, so_tien, thoi_gian) "
            "VALUES (?, ?, ?, ?)",
            (thang, mo_ta, so_tien, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def tong_chi_phi_dac_biet_trong_thang(thang: str) -> int:
    with db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(so_tien), 0) AS tong FROM chi_phi_dac_biet "
            "WHERE thang = ?",
            (thang,),
        ).fetchone()
        return int(row["tong"])


def danh_sach_chi_phi_dac_biet_trong_thang(thang: str) -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            "SELECT id, thang, mo_ta, so_tien, thoi_gian FROM chi_phi_dac_biet "
            "WHERE thang = ? ORDER BY thoi_gian DESC",
            (thang,),
        ).fetchall()


def chi_phi_dac_biet_theo_id(id: int) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute(
            "SELECT id, thang, mo_ta, so_tien, thoi_gian FROM chi_phi_dac_biet "
            "WHERE id = ?",
            (id,),
        ).fetchone()


def sua_chi_phi_dac_biet(id: int, so_tien: int | None = None, mo_ta: str | None = None) -> bool:
    """Sửa 1 khai báo chi phí đặc biệt. Chỉ field nào truyền (khác None) mới
    bị đổi. Trả False nếu id không tồn tại (khi có ít nhất 1 field để sửa).
    Nếu không truyền field nào, trả True luôn (không kiểm tra id) -- cùng
    quy ước sua_chi_tieu/sua_giao_dich_cong_ty đã có."""
    truong = []
    gia_tri: list = []
    if so_tien is not None:
        truong.append("so_tien = ?")
        gia_tri.append(so_tien)
    if mo_ta is not None:
        truong.append("mo_ta = ?")
        gia_tri.append(mo_ta)
    if not truong:
        return True
    gia_tri.append(id)
    with db() as conn:
        cur = conn.execute(
            f"UPDATE chi_phi_dac_biet SET {', '.join(truong)} WHERE id = ?", gia_tri
        )
        return cur.rowcount > 0


def xoa_chi_phi_dac_biet(id: int) -> bool:
    with db() as conn:
        cur = conn.execute("DELETE FROM chi_phi_dac_biet WHERE id = ?", (id,))
        return cur.rowcount > 0
