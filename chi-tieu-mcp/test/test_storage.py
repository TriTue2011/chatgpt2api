"""Test các hàm sửa/xoá/thống kê mới trong app/storage.py — DB tạm qua
tmp_path, không đụng data/chi_tieu.db thật (theo đúng pattern test_tools.py)."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _db_tam(tmp_path, monkeypatch):
    db_path = tmp_path / "chi_tieu_test.db"
    import app.storage as storage
    monkeypatch.setattr(storage, "DB_PATH", db_path)
    storage.khoi_tao_db()
    yield


def test_sua_chi_tieu_doi_so_tien():
    from app.storage import ghi_chi_tieu, sua_chi_tieu, danh_sach_chi_trong_thang
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000, "an trua")
    ok = sua_chi_tieu(id_khoan, so_tien=150_000)
    assert ok is True
    thang = datetime.now().strftime("%Y-%m")
    rows = danh_sach_chi_trong_thang(thang)
    assert rows[0]["so_tien"] == 150_000
    assert rows[0]["ghi_chu"] == "an trua"  # khong truyen ghi_chu thi giu nguyen


def test_sua_chi_tieu_doi_ghi_chu_va_hu():
    from app.storage import ghi_chi_tieu, sua_chi_tieu, danh_sach_chi_trong_thang
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000, "an trua")
    sua_chi_tieu(id_khoan, ghi_chu="an toi", hu_ma="huong_thu")
    thang = datetime.now().strftime("%Y-%m")
    rows = danh_sach_chi_trong_thang(thang)
    assert rows[0]["ghi_chu"] == "an toi"
    assert rows[0]["hu_ma"] == "huong_thu"
    assert rows[0]["so_tien"] == 100_000  # khong truyen so_tien thi giu nguyen


def test_sua_chi_tieu_id_khong_ton_tai():
    from app.storage import sua_chi_tieu
    assert sua_chi_tieu(999999, so_tien=1000) is False


def test_xoa_chi_tieu_thanh_cong():
    from app.storage import ghi_chi_tieu, xoa_chi_tieu, danh_sach_chi_trong_thang
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000)
    assert xoa_chi_tieu(id_khoan) is True
    thang = datetime.now().strftime("%Y-%m")
    assert danh_sach_chi_trong_thang(thang) == []


def test_xoa_chi_tieu_id_khong_ton_tai():
    from app.storage import xoa_chi_tieu
    assert xoa_chi_tieu(999999) is False


def test_danh_sach_chi_trong_thang_co_id():
    from app.storage import ghi_chi_tieu, danh_sach_chi_trong_thang
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000)
    thang = datetime.now().strftime("%Y-%m")
    rows = danh_sach_chi_trong_thang(thang)
    assert rows[0]["id"] == id_khoan


def test_ba_thang_lien_truoc_binh_thuong():
    from app.storage import ba_thang_lien_truoc
    assert ba_thang_lien_truoc("2026-09") == ["2026-08", "2026-07", "2026-06"]


def test_ba_thang_lien_truoc_qua_nam():
    from app.storage import ba_thang_lien_truoc
    assert ba_thang_lien_truoc("2026-01") == ["2025-12", "2025-11", "2025-10"]


def test_trung_binh_3_thang_truoc_tinh_dung():
    from app.storage import ghi_chi_tieu, trung_binh_chi_3_thang_truoc, db
    id1 = ghi_chi_tieu("thiet_yeu", 300_000)
    id2 = ghi_chi_tieu("thiet_yeu", 600_000)
    id3 = ghi_chi_tieu("thiet_yeu", 900_000)
    with db() as conn:
        conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?", ("2026-06-10T12:00:00", "2026-06", id1))
        conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?", ("2026-07-10T12:00:00", "2026-07", id2))
        conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?", ("2026-08-10T12:00:00", "2026-08", id3))
    assert trung_binh_chi_3_thang_truoc("2026-09") == 600_000


def test_trung_binh_3_thang_truoc_thang_thieu_du_lieu_tinh_la_0():
    from app.storage import ghi_chi_tieu, trung_binh_chi_3_thang_truoc, db
    id1 = ghi_chi_tieu("thiet_yeu", 300_000)
    with db() as conn:
        conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?", ("2025-12-10T12:00:00", "2025-12", id1))
    # thang truoc 2026-01 la 2025-10,11,12 -> chi 12 co du lieu (300k), con lai = 0
    assert trung_binh_chi_3_thang_truoc("2026-01") == 100_000


def test_trung_binh_3_thang_truoc_khong_co_du_lieu():
    from app.storage import trung_binh_chi_3_thang_truoc
    assert trung_binh_chi_3_thang_truoc("2026-09") == 0


def test_trung_binh_chi_theo_hu_3_thang_truoc():
    from app.storage import ghi_chi_tieu, trung_binh_chi_theo_hu_3_thang_truoc, db
    id1 = ghi_chi_tieu("thiet_yeu", 300_000)
    id2 = ghi_chi_tieu("huong_thu", 60_000)
    id3 = ghi_chi_tieu("thiet_yeu", 900_000)
    with db() as conn:
        conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?", ("2026-06-10T12:00:00", "2026-06", id1))
        conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?", ("2026-07-10T12:00:00", "2026-07", id2))
        conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?", ("2026-08-10T12:00:00", "2026-08", id3))
    ket_qua = trung_binh_chi_theo_hu_3_thang_truoc("2026-09")
    assert ket_qua["thiet_yeu"] == round((300_000 + 900_000) / 3)
    assert ket_qua["huong_thu"] == round(60_000 / 3)
    assert "du_phong" not in ket_qua


def test_ghi_thu_nhap_them_va_tong_trong_thang():
    from app.storage import ghi_thu_nhap_them, tong_thu_nhap_them_trong_thang
    ghi_thu_nhap_them("thuong quy", 2_000_000)
    ghi_thu_nhap_them("lam them", 500_000)
    thang = datetime.now().strftime("%Y-%m")
    assert tong_thu_nhap_them_trong_thang(thang) == 2_500_000


def test_tong_thu_nhap_them_khong_co_du_lieu():
    from app.storage import tong_thu_nhap_them_trong_thang
    assert tong_thu_nhap_them_trong_thang("2020-01") == 0


def test_danh_sach_thu_nhap_them_co_id_dung_du_lieu():
    from app.storage import ghi_thu_nhap_them, danh_sach_thu_nhap_them_trong_thang
    id_khoan = ghi_thu_nhap_them("thuong quy", 2_000_000)
    thang = datetime.now().strftime("%Y-%m")
    rows = danh_sach_thu_nhap_them_trong_thang(thang)
    assert rows[0]["id"] == id_khoan
    assert rows[0]["mo_ta"] == "thuong quy"
    assert rows[0]["so_tien"] == 2_000_000


def test_ghi_giao_dich_cong_ty_va_so_du():
    from app.storage import ghi_giao_dich_cong_ty, so_du_cong_ty
    ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "di cong tac")
    ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    assert so_du_cong_ty() == 4_700_000


def test_so_du_cong_ty_am_khi_chi_vuot_tam_ung():
    from app.storage import ghi_giao_dich_cong_ty, so_du_cong_ty
    ghi_giao_dich_cong_ty("tam_ung", 1_000_000, "ung it")
    ghi_giao_dich_cong_ty("chi", 1_500_000, "chi nhieu hon")
    assert so_du_cong_ty() == -500_000


def test_so_du_cong_ty_khong_co_giao_dich_la_0():
    from app.storage import so_du_cong_ty
    assert so_du_cong_ty() == 0


def test_danh_sach_giao_dich_cong_ty_dang_mo_dung_du_lieu():
    from app.storage import ghi_giao_dich_cong_ty, danh_sach_giao_dich_cong_ty_dang_mo
    id1 = ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "di cong tac")
    rows = danh_sach_giao_dich_cong_ty_dang_mo()
    assert len(rows) == 1
    assert rows[0]["id"] == id1
    assert rows[0]["loai"] == "tam_ung"
    assert rows[0]["so_tien"] == 5_000_000
    assert rows[0]["mo_ta"] == "di cong tac"


def test_giao_dich_cong_ty_theo_id_tra_ve_dung_dong():
    from app.storage import ghi_giao_dich_cong_ty, giao_dich_cong_ty_theo_id
    id1 = ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "di cong tac")
    hang = giao_dich_cong_ty_theo_id(id1)
    assert hang["so_tien"] == 5_000_000
    assert hang["giai_chi_id"] is None


def test_giao_dich_cong_ty_theo_id_khong_ton_tai_tra_ve_none():
    from app.storage import giao_dich_cong_ty_theo_id
    assert giao_dich_cong_ty_theo_id(999999) is None


def test_sua_giao_dich_cong_ty_doi_so_tien():
    from app.storage import ghi_giao_dich_cong_ty, sua_giao_dich_cong_ty, danh_sach_giao_dich_cong_ty_dang_mo
    id1 = ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    ok = sua_giao_dich_cong_ty(id1, so_tien=350_000)
    assert ok is True
    rows = danh_sach_giao_dich_cong_ty_dang_mo()
    assert rows[0]["so_tien"] == 350_000
    assert rows[0]["mo_ta"] == "taxi"  # khong truyen mo_ta thi giu nguyen


def test_sua_giao_dich_cong_ty_id_khong_ton_tai():
    from app.storage import sua_giao_dich_cong_ty
    assert sua_giao_dich_cong_ty(999999, so_tien=1000) is False


def test_xoa_giao_dich_cong_ty_thanh_cong():
    from app.storage import ghi_giao_dich_cong_ty, xoa_giao_dich_cong_ty, danh_sach_giao_dich_cong_ty_dang_mo
    id1 = ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    assert xoa_giao_dich_cong_ty(id1) is True
    assert danh_sach_giao_dich_cong_ty_dang_mo() == []


def test_xoa_giao_dich_cong_ty_id_khong_ton_tai():
    from app.storage import xoa_giao_dich_cong_ty
    assert xoa_giao_dich_cong_ty(999999) is False


def test_giai_chi_tinh_dung_tong_va_so_du():
    from app.storage import ghi_giao_dich_cong_ty, giai_chi
    ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "dot 1")
    ghi_giao_dich_cong_ty("tam_ung", 2_000_000, "dot 2")
    ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    ket_qua = giai_chi()
    assert ket_qua["tong_tam_ung"] == 7_000_000
    assert ket_qua["tong_chi"] == 300_000
    assert ket_qua["so_du"] == 6_700_000


def test_giai_chi_khoa_giao_dich_khong_sua_xoa_duoc_nua():
    from app.storage import (
        ghi_giao_dich_cong_ty, giai_chi, sua_giao_dich_cong_ty,
        xoa_giao_dich_cong_ty, giao_dich_cong_ty_theo_id,
    )
    id1 = ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    giai_chi()
    assert sua_giao_dich_cong_ty(id1, so_tien=999) is False
    assert xoa_giao_dich_cong_ty(id1) is False
    assert giao_dich_cong_ty_theo_id(id1)["giai_chi_id"] is not None


def test_giai_chi_mo_ky_moi_trong_sau_do():
    from app.storage import ghi_giao_dich_cong_ty, giai_chi, so_du_cong_ty, danh_sach_giao_dich_cong_ty_dang_mo
    ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "dot 1")
    giai_chi()
    assert so_du_cong_ty() == 0
    assert danh_sach_giao_dich_cong_ty_dang_mo() == []
    ghi_giao_dich_cong_ty("tam_ung", 1_000_000, "dot 2 (ky moi)")
    assert so_du_cong_ty() == 1_000_000


def test_giao_dich_theo_lan_giai_chi_tra_ve_dung_danh_sach():
    from app.storage import ghi_giao_dich_cong_ty, giai_chi, giao_dich_theo_lan_giai_chi
    id1 = ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "dot 1")
    id2 = ghi_giao_dich_cong_ty("chi", 300_000, "taxi")
    ket_qua = giai_chi()
    rows = giao_dich_theo_lan_giai_chi(ket_qua["id"])
    assert {r["id"] for r in rows} == {id1, id2}


def test_danh_sach_lan_giai_chi_tra_ve_lich_su():
    from app.storage import ghi_giao_dich_cong_ty, giai_chi, danh_sach_lan_giai_chi
    ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "dot 1")
    giai_chi()
    ds = danh_sach_lan_giai_chi()
    assert len(ds) == 1
    assert ds[0]["tong_tam_ung"] == 5_000_000


def test_lan_giai_chi_theo_id_ton_tai():
    from app.storage import ghi_giao_dich_cong_ty, giai_chi, lan_giai_chi_theo_id
    ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "dot 1")
    ket_qua = giai_chi()
    hang = lan_giai_chi_theo_id(ket_qua["id"])
    assert hang is not None
    assert hang["tong_tam_ung"] == 5_000_000


def test_lan_giai_chi_theo_id_khong_ton_tai():
    from app.storage import lan_giai_chi_theo_id
    assert lan_giai_chi_theo_id(999999) is None


def test_giai_chi_hai_lan_lien_tiep_tach_biet_hoan_toan():
    """Giao dịch của lần giải chi thứ 1 không được lẫn vào tổng của lần thứ 2."""
    from app.storage import ghi_giao_dich_cong_ty, giai_chi
    ghi_giao_dich_cong_ty("tam_ung", 5_000_000, "dot 1")
    ket_qua_1 = giai_chi()
    ghi_giao_dich_cong_ty("tam_ung", 1_000_000, "dot 2")
    ket_qua_2 = giai_chi()
    assert ket_qua_1["tong_tam_ung"] == 5_000_000
    assert ket_qua_2["tong_tam_ung"] == 1_000_000


def test_ghi_chi_phi_dac_biet_va_tong_trong_thang():
    from app.storage import ghi_chi_phi_dac_biet, tong_chi_phi_dac_biet_trong_thang
    ghi_chi_phi_dac_biet("2026-09", "hoc phi", 4_000_000)
    ghi_chi_phi_dac_biet("2026-09", "vien phi", 1_000_000)
    assert tong_chi_phi_dac_biet_trong_thang("2026-09") == 5_000_000


def test_tong_chi_phi_dac_biet_thang_khac_khong_bi_cong_nham():
    from app.storage import ghi_chi_phi_dac_biet, tong_chi_phi_dac_biet_trong_thang
    ghi_chi_phi_dac_biet("2026-09", "hoc phi", 4_000_000)
    assert tong_chi_phi_dac_biet_trong_thang("2026-08") == 0


def test_danh_sach_chi_phi_dac_biet_trong_thang():
    from app.storage import ghi_chi_phi_dac_biet, danh_sach_chi_phi_dac_biet_trong_thang
    id1 = ghi_chi_phi_dac_biet("2026-09", "hoc phi", 4_000_000)
    rows = danh_sach_chi_phi_dac_biet_trong_thang("2026-09")
    assert len(rows) == 1
    assert rows[0]["id"] == id1
    assert rows[0]["mo_ta"] == "hoc phi"
    assert rows[0]["so_tien"] == 4_000_000


def test_chi_phi_dac_biet_theo_id_khong_ton_tai():
    from app.storage import chi_phi_dac_biet_theo_id
    assert chi_phi_dac_biet_theo_id(999999) is None


def test_sua_chi_phi_dac_biet_doi_so_tien_va_mo_ta():
    from app.storage import ghi_chi_phi_dac_biet, sua_chi_phi_dac_biet, chi_phi_dac_biet_theo_id
    id1 = ghi_chi_phi_dac_biet("2026-09", "hoc phi", 4_000_000)
    ok = sua_chi_phi_dac_biet(id1, so_tien=4_500_000, mo_ta="hoc phi ky 1")
    assert ok is True
    hang = chi_phi_dac_biet_theo_id(id1)
    assert hang["so_tien"] == 4_500_000
    assert hang["mo_ta"] == "hoc phi ky 1"


def test_sua_chi_phi_dac_biet_id_khong_ton_tai():
    from app.storage import sua_chi_phi_dac_biet
    assert sua_chi_phi_dac_biet(999999, so_tien=1000) is False


def test_xoa_chi_phi_dac_biet_thanh_cong():
    from app.storage import ghi_chi_phi_dac_biet, xoa_chi_phi_dac_biet, chi_phi_dac_biet_theo_id
    id1 = ghi_chi_phi_dac_biet("2026-09", "hoc phi", 4_000_000)
    assert xoa_chi_phi_dac_biet(id1) is True
    assert chi_phi_dac_biet_theo_id(id1) is None


def test_xoa_chi_phi_dac_biet_id_khong_ton_tai():
    from app.storage import xoa_chi_phi_dac_biet
    assert xoa_chi_phi_dac_biet(999999) is False


def test_migrate_them_cot_thang_backfill_du_lieu_cu(tmp_path):
    """Mô phỏng DB CŨ (schema trước Tính năng A -- không có cột thang) có
    sẵn dữ liệu, xác nhận khoi_tao_db() migrate an toàn: thêm cột + backfill
    bằng substr(thoi_gian,1,7), không mất/hỏng dữ liệu, idempotent."""
    import sqlite3
    import app.storage as storage
    db_path = tmp_path / "db_cu.db"

    conn_cu = sqlite3.connect(db_path)
    conn_cu.execute("""
        CREATE TABLE chi_tieu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thoi_gian TEXT NOT NULL,
            hu_ma TEXT NOT NULL,
            so_tien INTEGER NOT NULL,
            ghi_chu TEXT DEFAULT '',
            nguon TEXT DEFAULT 'zalo'
        )
    """)
    conn_cu.execute(
        "INSERT INTO chi_tieu (thoi_gian, hu_ma, so_tien, ghi_chu) VALUES (?, ?, ?, ?)",
        ("2026-03-15T10:00:00", "thiet_yeu", 100_000, "an trua cu"),
    )
    conn_cu.execute("""
        CREATE TABLE thu_nhap_them (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thoi_gian TEXT NOT NULL,
            mo_ta TEXT DEFAULT '',
            so_tien INTEGER NOT NULL
        )
    """)
    conn_cu.execute(
        "INSERT INTO thu_nhap_them (thoi_gian, mo_ta, so_tien) VALUES (?, ?, ?)",
        ("2026-03-20T09:00:00", "thuong cu", 2_000_000),
    )
    conn_cu.commit()
    conn_cu.close()

    storage.DB_PATH = db_path
    storage.khoi_tao_db()  # migrate lan 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    hang_chi_tieu = conn.execute("SELECT thang, ghi_chu FROM chi_tieu").fetchone()
    assert hang_chi_tieu["thang"] == "2026-03"
    assert hang_chi_tieu["ghi_chu"] == "an trua cu"
    hang_thu_nhap = conn.execute("SELECT thang, mo_ta FROM thu_nhap_them").fetchone()
    assert hang_thu_nhap["thang"] == "2026-03"
    assert hang_thu_nhap["mo_ta"] == "thuong cu"
    conn.close()

    storage.khoi_tao_db()  # migrate lan 2 -- phai khong loi (idempotent)

    conn2 = sqlite3.connect(db_path)
    conn2.row_factory = sqlite3.Row
    hang_lai = conn2.execute("SELECT thang FROM chi_tieu").fetchone()
    assert hang_lai["thang"] == "2026-03"
    conn2.close()


def test_ghi_chi_tieu_thang_mac_dinh_tu_thoi_gian():
    """Nếu không truyền thang, storage.ghi_chi_tieu tự tính từ thoi_gian[:7]
    (hành vi lịch dương thuần -- chỉ dùng khi gọi trực tiếp storage.py,
    luồng thật qua tools.py luôn truyền tường minh)."""
    from app.storage import ghi_chi_tieu, danh_sach_chi_trong_thang
    from datetime import datetime
    id1 = ghi_chi_tieu("thiet_yeu", 100_000)
    thang_hien_tai = datetime.now().strftime("%Y-%m")
    rows = danh_sach_chi_trong_thang(thang_hien_tai)
    assert rows[0]["id"] == id1


def test_ghi_chi_tieu_thang_tuong_minh_duoc_tin_dung():
    """Truyền thang tường minh phải được lưu đúng, KHÔNG bị ghi đè bởi
    thoi_gian[:7] -- đây chính là cơ chế "đóng băng" cốt lõi của tính năng."""
    from app.storage import ghi_chi_tieu, danh_sach_chi_trong_thang
    id1 = ghi_chi_tieu("thiet_yeu", 100_000, thang="2026-05")
    rows_thang_5 = danh_sach_chi_trong_thang("2026-05")
    assert rows_thang_5[0]["id"] == id1
    from datetime import datetime
    rows_thang_hien_tai = danh_sach_chi_trong_thang(datetime.now().strftime("%Y-%m"))
    assert rows_thang_hien_tai == []  # KHONG nam trong thang thuc te ghi (dong bang theo tham so truyen vao)


def test_sua_chi_tieu_khong_lam_doi_thang_da_dong_bang():
    """sua_chi_tieu() sửa so_tien/ghi_chu/hu_ma KHÔNG được đụng cột thang --
    sửa 1 khoản chi đã ghi không được đổi nó sang "tháng" khác."""
    from app.storage import ghi_chi_tieu, sua_chi_tieu, danh_sach_chi_trong_thang
    id1 = ghi_chi_tieu("thiet_yeu", 100_000, thang="2026-05")
    sua_chi_tieu(id1, so_tien=200_000, ghi_chu="da sua", hu_ma="huong_thu")
    rows = danh_sach_chi_trong_thang("2026-05")
    assert len(rows) == 1
    assert rows[0]["id"] == id1
    assert rows[0]["so_tien"] == 200_000


def test_chi_tieu_theo_id_tra_ve_dung_dong():
    from app.storage import ghi_chi_tieu, chi_tieu_theo_id
    id_khoan = ghi_chi_tieu("thiet_yeu", 100_000, "an trua")
    dong = chi_tieu_theo_id(id_khoan)
    assert dong["hu_ma"] == "thiet_yeu"
    assert dong["so_tien"] == 100_000
    assert dong["ghi_chu"] == "an trua"


def test_chi_tieu_theo_id_khong_ton_tai_tra_ve_none():
    from app.storage import chi_tieu_theo_id
    assert chi_tieu_theo_id(999999) is None


def test_tach_chi_tieu_xoa_dong_goc_va_ghi_dong_moi():
    from app.storage import ghi_chi_tieu, tach_chi_tieu, chi_tieu_theo_id, danh_sach_chi_trong_thang
    id_goc = ghi_chi_tieu("thiet_yeu", 100_000, "sinh hoat")
    ids_moi = tach_chi_tieu(id_goc, [
        {"hu_ma": "thiet_yeu", "so_tien": 60_000, "ghi_chu": "an uong"},
        {"hu_ma": "huong_thu", "so_tien": 40_000, "ghi_chu": "giai tri"},
    ])
    assert len(ids_moi) == 2
    assert chi_tieu_theo_id(id_goc) is None  # dong goc da bi xoa
    thang = datetime.now().strftime("%Y-%m")
    rows = {r["id"]: r for r in danh_sach_chi_trong_thang(thang)}
    assert rows[ids_moi[0]]["hu_ma"] == "thiet_yeu"
    assert rows[ids_moi[0]]["so_tien"] == 60_000
    assert rows[ids_moi[1]]["hu_ma"] == "huong_thu"
    assert rows[ids_moi[1]]["so_tien"] == 40_000


def test_tach_chi_tieu_giu_nguyen_thoi_gian_va_thang_goc():
    from app.storage import ghi_chi_tieu, tach_chi_tieu, chi_tieu_theo_id
    id_goc = ghi_chi_tieu("thiet_yeu", 100_000, thang="2026-01")
    goc = chi_tieu_theo_id(id_goc)
    ids_moi = tach_chi_tieu(id_goc, [
        {"hu_ma": "thiet_yeu", "so_tien": 50_000, "ghi_chu": ""},
        {"hu_ma": "huong_thu", "so_tien": 50_000, "ghi_chu": ""},
    ])
    for id_moi in ids_moi:
        dong = chi_tieu_theo_id(id_moi)
        assert dong["thoi_gian"] == goc["thoi_gian"]
        assert dong["thang"] == "2026-01"
        assert dong["nguon"] == goc["nguon"]


def test_tach_chi_tieu_id_khong_ton_tai_tra_ve_none():
    from app.storage import tach_chi_tieu
    ket_qua = tach_chi_tieu(999999, [
        {"hu_ma": "thiet_yeu", "so_tien": 50_000, "ghi_chu": ""},
        {"hu_ma": "huong_thu", "so_tien": 50_000, "ghi_chu": ""},
    ])
    assert ket_qua is None


def test_sua_thu_nhap_them_doi_so_tien_mo_ta_id_la_tra_false():
    from app import storage
    id_khoan = storage.ghi_thu_nhap_them("thuong", 500_000, thang="2026-09")
    assert storage.sua_thu_nhap_them(id_khoan, so_tien=600_000, mo_ta="thuong quy 3") is True
    dong = storage.danh_sach_thu_nhap_them_trong_thang("2026-09")[0]
    assert (dong["so_tien"], dong["mo_ta"]) == (600_000, "thuong quy 3")
    assert storage.sua_thu_nhap_them(id_khoan, mo_ta="chi doi mo ta") is True
    assert storage.danh_sach_thu_nhap_them_trong_thang("2026-09")[0]["so_tien"] == 600_000
    assert storage.sua_thu_nhap_them(999_999, so_tien=1) is False


def test_xoa_thu_nhap_them():
    from app import storage
    id_khoan = storage.ghi_thu_nhap_them("thuong", 500_000, thang="2026-09")
    assert storage.xoa_thu_nhap_them(id_khoan) is True
    assert storage.danh_sach_thu_nhap_them_trong_thang("2026-09") == []
    assert storage.xoa_thu_nhap_them(id_khoan) is False


def _chen_chi(thoi_gian, hu_ma, so_tien, thang):
    from app import storage
    with storage.db() as ket_noi:
        ket_noi.execute(
            "INSERT INTO chi_tieu (thoi_gian, hu_ma, so_tien, ghi_chu, nguon, thang) VALUES (?, ?, ?, '', 'zalo', ?)",
            (thoi_gian, hu_ma, so_tien, thang),
        )


def test_tong_chi_theo_hu_trong_thang_chi_tinh_dung_nhan_ky():
    from app import storage
    _chen_chi("2026-09-06T08:00:00", "thiet_yeu", 100_000, "2026-09")
    _chen_chi("2026-09-20T08:00:00", "thiet_yeu", 50_000, "2026-09")
    _chen_chi("2026-09-21T08:00:00", "huong_thu", 30_000, "2026-09")
    _chen_chi("2026-09-03T08:00:00", "thiet_yeu", 999_000, "2026-08")  # trước ngày 5 = kỳ 08
    assert storage.tong_chi_theo_hu_trong_thang("2026-09") == {"thiet_yeu": 150_000, "huong_thu": 30_000}
    assert storage.tong_chi_theo_hu_trong_thang("2026-07") == {}


def test_tong_chi_theo_ngay_trong_thang_gom_theo_ngay_tang_dan():
    from app import storage
    _chen_chi("2026-09-22T14:54:19", "thiet_yeu", 10_000, "2026-09")
    _chen_chi("2026-09-06T08:00:00", "thiet_yeu", 100_000, "2026-09")
    _chen_chi("2026-09-22T09:00:00", "huong_thu", 5_000, "2026-09")
    _chen_chi("2026-09-03T08:00:00", "thiet_yeu", 999_000, "2026-08")
    assert storage.tong_chi_theo_ngay_trong_thang("2026-09") == [("2026-09-06", 100_000), ("2026-09-22", 15_000)]
