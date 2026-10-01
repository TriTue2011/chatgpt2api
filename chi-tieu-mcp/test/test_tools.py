"""Test app/tools.py + storage.py bằng DB SQLite tạm, không đụng data/chi_tieu.db thật."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _db_tam(tmp_path, monkeypatch):
    db_path = tmp_path / "chi_tieu_test.db"
    jars_path = tmp_path / "jars_config.json"
    jars_path.write_text(json.dumps({
        "thu_nhap_thuc_linh_thang": 10_000_000,
        "hu": [
            {"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 50.0},
            {"ma": "huong_thu", "ten": "Hưởng Thụ", "ty_le_phan_tram": 10.0},
        ],
        "nguong_canh_bao": [0.65, 0.8, 1.0],
    }), encoding="utf-8")

    import app.config as config
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "JARS_CONFIG_PATH", jars_path)

    import app.storage as storage
    monkeypatch.setattr(storage, "DB_PATH", db_path)
    storage.khoi_tao_db()

    import app.jars as jars
    monkeypatch.setattr(jars, "JARS_CONFIG_PATH", jars_path)

    import app.pdf_cong_ty as pdf_cong_ty
    monkeypatch.setattr(pdf_cong_ty, "THU_MUC_PDF", tmp_path / "tam_ung_pdf")
    yield


def test_ghi_chi_tieu_hu_khong_ton_tai():
    from app.tools import ghi_chi_tieu
    ket_qua = ghi_chi_tieu("khong_co_hu_nay", 50_000)
    assert "loi" in ket_qua


def test_ghi_chi_tieu_thanh_cong_va_tinh_dung_han_muc():
    from app.tools import ghi_chi_tieu
    ket_qua = ghi_chi_tieu("thiet_yeu", 100_000, "an trua")
    assert ket_qua["da_ghi"] is True
    assert ket_qua["han_muc_thang"] == 5_000_000  # 50% cua 10tr
    assert ket_qua["da_chi_thang_nay"] == 100_000
    assert ket_qua["con_lai"] == 4_900_000
    assert ket_qua["trang_thai"] == "binh_thuong"


def test_ghi_chi_tieu_so_tien_am_bi_tu_choi():
    from app.tools import ghi_chi_tieu
    ket_qua = ghi_chi_tieu("thiet_yeu", -1000)
    assert "loi" in ket_qua


def test_ghi_chi_tieu_so_tien_qua_lon_bi_tu_choi():
    from app.tools import ghi_chi_tieu
    ket_qua = ghi_chi_tieu("thiet_yeu", 10**13)
    assert "loi" in ket_qua


def test_trang_thai_canh_bao_80_phan_tram():
    from app.tools import ghi_chi_tieu
    ghi_chi_tieu("huong_thu", 850_000)  # han muc hu nay = 1tr (10% cua 10tr)
    ket_qua = ghi_chi_tieu("huong_thu", 50_000)  # tong 900k = 90%
    assert ket_qua["trang_thai"] == "canh_bao_80"


def test_trang_thai_vuot_han_muc():
    from app.tools import ghi_chi_tieu
    ket_qua = ghi_chi_tieu("huong_thu", 1_200_000)
    assert ket_qua["trang_thai"] == "vuot_han_muc"


def test_xem_ngan_sach_tra_ve_du_cac_hu():
    from app.tools import ghi_chi_tieu, xem_ngan_sach
    ghi_chi_tieu("thiet_yeu", 200_000)
    ket_qua = xem_ngan_sach()
    ma_cac_hu = {h["ma"] for h in ket_qua["hu"]}
    assert ma_cac_hu == {"thiet_yeu", "huong_thu"}
    hu_thiet_yeu = next(h for h in ket_qua["hu"] if h["ma"] == "thiet_yeu")
    assert hu_thiet_yeu["da_chi"] == 200_000
    assert hu_thiet_yeu["ty_le_phan_tram"] == 50.0


def test_de_xuat_dieu_chinh_khi_chua_chi_gi():
    from app.tools import de_xuat_dieu_chinh
    ket_qua = de_xuat_dieu_chinh()
    assert "chưa hũ nào cần điều chỉnh" in ket_qua["de_xuat"][0]


def test_de_xuat_dieu_chinh_khi_co_hu_vuot():
    from app.tools import de_xuat_dieu_chinh, ghi_chi_tieu
    ghi_chi_tieu("huong_thu", 1_500_000)  # vuot han muc 1tr
    ket_qua = de_xuat_dieu_chinh()
    assert any("Hưởng Thụ" in d for d in ket_qua["de_xuat"])


def test_de_xuat_dieu_chinh_goi_y_xu_huong_khi_lech_nhieu():
    from app.tools import de_xuat_dieu_chinh
    from app import storage
    from app.storage import db, ba_thang_lien_truoc
    from app.jars import thang_hien_tai

    # hu "huong_thu" cau hinh 10% (han muc 1tr) nhung 3 thang lien truoc chi
    # chi that 100k/thang (1% thu nhap) -> lech 9 diem % -> phai co goi y.
    for thang_truoc in ba_thang_lien_truoc(thang_hien_tai()):
        id_khoan = storage.ghi_chi_tieu("huong_thu", 100_000)
        with db() as conn:
            conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?",
                         (f"{thang_truoc}-05T12:00:00", thang_truoc, id_khoan))

    ket_qua = de_xuat_dieu_chinh()
    assert any("Hưởng Thụ" in d and "3 tháng" in d for d in ket_qua["de_xuat"])


def test_de_xuat_dieu_chinh_khong_goi_y_xu_huong_khi_khong_du_du_lieu():
    from app.tools import de_xuat_dieu_chinh
    ket_qua = de_xuat_dieu_chinh()
    assert ket_qua["de_xuat"] == [
        "Chi tiêu tháng này đang trong tầm kiểm soát, chưa hũ nào cần điều chỉnh."
    ]


def test_de_xuat_dieu_chinh_khong_goi_y_xu_huong_khi_lech_duoi_5_diem():
    from app.tools import de_xuat_dieu_chinh
    from app import storage
    from app.storage import db, ba_thang_lien_truoc
    from app.jars import thang_hien_tai

    # hu "huong_thu" cau hinh 10% (han muc 1tr) nhung 3 thang lien truoc chi
    # chi that 700k/thang (7% thu nhap) -> lech 3 diem % -> khong du 5 diem,
    # khong phai co goi y.
    for thang_truoc in ba_thang_lien_truoc(thang_hien_tai()):
        id_khoan = storage.ghi_chi_tieu("huong_thu", 700_000)
        with db() as conn:
            conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?",
                         (f"{thang_truoc}-05T12:00:00", thang_truoc, id_khoan))

    ket_qua = de_xuat_dieu_chinh()
    # Khong co "3 thang" trong suggestions -> chi co default message
    assert not any("3 tháng" in d for d in ket_qua["de_xuat"])


def test_ghi_chi_tieu_han_muc_cong_thu_nhap_them():
    from app.tools import ghi_chi_tieu, ghi_thu_nhap_them
    ghi_thu_nhap_them("thuong", 2_000_000)  # thu nhap hieu qua: 10tr + 2tr = 12tr
    ket_qua = ghi_chi_tieu("thiet_yeu", 100_000)
    assert ket_qua["han_muc_thang"] == 6_000_000  # 50% cua 12tr


def test_xem_ngan_sach_thu_nhap_cong_thu_nhap_them():
    from app.tools import ghi_thu_nhap_them, xem_ngan_sach
    ghi_thu_nhap_them("thuong", 2_000_000)
    ket_qua = xem_ngan_sach()
    assert ket_qua["thu_nhap_thuc_linh"] == 12_000_000
    hu_thiet_yeu = next(h for h in ket_qua["hu"] if h["ma"] == "thiet_yeu")
    assert hu_thiet_yeu["han_muc_thang"] == 6_000_000


def test_ghi_chi_tieu_va_xem_ngan_sach_han_muc_nhat_quan_sau_thu_nhap_them():
    """Ràng buộc quan trọng: ghi_chi_tieu và xem_ngan_sach phải trả CÙNG 1
    han_muc cho cùng 1 hũ ngay sau khi ghi thu nhập phát sinh."""
    from app.tools import ghi_chi_tieu, ghi_thu_nhap_them, xem_ngan_sach
    ghi_thu_nhap_them("thuong", 2_000_000)
    han_muc_tu_ghi_chi_tieu = ghi_chi_tieu("thiet_yeu", 100_000)["han_muc_thang"]
    han_muc_tu_xem_ngan_sach = next(
        h for h in xem_ngan_sach()["hu"] if h["ma"] == "thiet_yeu"
    )["han_muc_thang"]
    assert han_muc_tu_ghi_chi_tieu == han_muc_tu_xem_ngan_sach


def test_ghi_thu_nhap_them_so_tien_am_bi_tu_choi():
    from app.tools import ghi_thu_nhap_them
    ket_qua = ghi_thu_nhap_them("thuong", -1000)
    assert "loi" in ket_qua


def test_ghi_thu_nhap_them_so_tien_qua_lon_bi_tu_choi():
    from app.tools import ghi_thu_nhap_them
    ket_qua = ghi_thu_nhap_them("thuong", 10**13)
    assert "loi" in ket_qua


def test_ghi_thu_nhap_them_tra_ve_han_muc_moi_du_cac_hu():
    from app.tools import ghi_thu_nhap_them
    ket_qua = ghi_thu_nhap_them("thuong", 2_000_000)
    assert ket_qua["da_ghi"] is True
    assert ket_qua["thu_nhap_hieu_qua_thang"] == 12_000_000
    ma_cac_hu = {h["ma"] for h in ket_qua["han_muc_moi"]}
    assert ma_cac_hu == {"thiet_yeu", "huong_thu"}
    hu_thiet_yeu = next(h for h in ket_qua["han_muc_moi"] if h["ma"] == "thiet_yeu")
    assert hu_thiet_yeu["han_muc_thang"] == 6_000_000


def test_xem_ngan_sach_thu_nhap_co_dinh_khong_doi_khi_co_thu_nhap_them():
    from app.tools import ghi_thu_nhap_them, xem_ngan_sach
    ghi_thu_nhap_them("thuong", 2_000_000)
    ket_qua = xem_ngan_sach()
    assert ket_qua["thu_nhap_co_dinh"] == 10_000_000
    assert ket_qua["thu_nhap_thuc_linh"] == 12_000_000


def test_de_xuat_dieu_chinh_xu_huong_khong_bi_thu_nhap_them_lam_lech():
    """Ràng buộc quan trọng: xu hướng 3 tháng phải so với lương CỐ ĐỊNH, không
    phải thu nhập hiệu quả — nếu không, 1 khoản thưởng tháng này sẽ làm lệch
    gợi ý dựa trên lịch sử 3 tháng trước (thời điểm chưa có khoản thưởng đó)."""
    from app.tools import de_xuat_dieu_chinh, ghi_thu_nhap_them
    from app import storage
    from app.storage import db, ba_thang_lien_truoc
    from app.jars import thang_hien_tai

    # 3 thang truoc chi dung 50% luong CO DINH (5tr/10tr) cho thiet_yeu, khop
    # dung cau hinh 50% -> khong co gi de goi y ve xu huong.
    for thang_truoc in ba_thang_lien_truoc(thang_hien_tai()):
        id_khoan = storage.ghi_chi_tieu("thiet_yeu", 5_000_000)
        with db() as conn:
            conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?",
                         (f"{thang_truoc}-05T12:00:00", thang_truoc, id_khoan))

    # Ghi 1 khoan thu nhap phat sinh lon THANG NAY -> khong duoc lam lech
    # goi y xu huong dua tren lich su 3 thang TRUOC (thoi diem chua co khoan
    # thuong nay).
    ghi_thu_nhap_them("thuong", 10_000_000)

    ket_qua = de_xuat_dieu_chinh()
    assert not any("3 tháng" in d for d in ket_qua["de_xuat"])


def test_ghi_tam_ung_cong_ty_thanh_cong():
    from app.tools import ghi_tam_ung_cong_ty
    ket_qua = ghi_tam_ung_cong_ty(5_000_000, "di cong tac")
    assert ket_qua["da_ghi"] is True
    assert ket_qua["so_du_hien_tai"] == 5_000_000


def test_ghi_tam_ung_cong_ty_so_tien_am_bi_tu_choi():
    from app.tools import ghi_tam_ung_cong_ty
    ket_qua = ghi_tam_ung_cong_ty(-1000, "sai")
    assert "loi" in ket_qua


def test_ghi_tam_ung_cong_ty_so_tien_qua_lon_bi_tu_choi():
    from app.tools import ghi_tam_ung_cong_ty
    ket_qua = ghi_tam_ung_cong_ty(10**13, "qua lon")
    assert "loi" in ket_qua


def test_ghi_tam_ung_cong_ty_mo_ta_rong_bi_tu_choi():
    from app.tools import ghi_tam_ung_cong_ty
    ket_qua = ghi_tam_ung_cong_ty(1_000_000, "   ")
    assert "loi" in ket_qua


def test_ghi_tam_ung_cong_ty_mo_ta_qua_dai_bi_tu_choi():
    from app.tools import ghi_tam_ung_cong_ty
    ket_qua = ghi_tam_ung_cong_ty(1_000_000, "a" * 501)
    assert "loi" in ket_qua


def test_ghi_chi_cong_ty_thanh_cong_va_giam_so_du():
    from app.tools import ghi_tam_ung_cong_ty, ghi_chi_cong_ty
    ghi_tam_ung_cong_ty(5_000_000, "di cong tac")
    ket_qua = ghi_chi_cong_ty(300_000, "taxi")
    assert ket_qua["da_ghi"] is True
    assert ket_qua["so_du_hien_tai"] == 4_700_000


def test_ghi_chi_cong_ty_mo_ta_rong_bi_tu_choi():
    from app.tools import ghi_chi_cong_ty
    ket_qua = ghi_chi_cong_ty(100_000, "")
    assert "loi" in ket_qua


def test_ghi_chi_cong_ty_mo_ta_qua_dai_bi_tu_choi():
    from app.tools import ghi_chi_cong_ty
    ket_qua = ghi_chi_cong_ty(100_000, "a" * 501)
    assert "loi" in ket_qua


def test_ghi_chi_cong_ty_vuot_tam_ung_van_duoc_ghi_so_du_am():
    from app.tools import ghi_tam_ung_cong_ty, ghi_chi_cong_ty
    ghi_tam_ung_cong_ty(1_000_000, "ung it")
    ket_qua = ghi_chi_cong_ty(1_500_000, "chi nhieu hon")
    assert ket_qua["da_ghi"] is True
    assert ket_qua["so_du_hien_tai"] == -500_000


def test_xem_so_du_cong_ty_khi_chua_co_giao_dich():
    from app.tools import xem_so_du_cong_ty
    ket_qua = xem_so_du_cong_ty()
    assert ket_qua["so_du"] == 0
    assert ket_qua["so_luong_giao_dich"] == 0
    assert "Chưa có" in ket_qua["dien_giai"]


def test_xem_so_du_cong_ty_khi_dang_giu_tien():
    from app.tools import ghi_tam_ung_cong_ty, xem_so_du_cong_ty
    ghi_tam_ung_cong_ty(5_000_000, "di cong tac")
    ket_qua = xem_so_du_cong_ty()
    assert ket_qua["so_du"] == 5_000_000
    assert "đang giữ" in ket_qua["dien_giai"].lower()


def test_xem_so_du_cong_ty_khi_cong_ty_no_lai():
    from app.tools import ghi_tam_ung_cong_ty, ghi_chi_cong_ty, xem_so_du_cong_ty
    ghi_tam_ung_cong_ty(1_000_000, "ung it")
    ghi_chi_cong_ty(1_500_000, "chi nhieu hon")
    ket_qua = xem_so_du_cong_ty()
    assert ket_qua["so_du"] == -500_000
    assert "nợ lại" in ket_qua["dien_giai"]


def test_giai_chi_cong_ty_khong_co_giao_dich_tra_loi():
    from app.tools import giai_chi_cong_ty
    ket_qua = giai_chi_cong_ty()
    assert "loi" in ket_qua


def test_giai_chi_cong_ty_thanh_cong():
    from app.tools import ghi_tam_ung_cong_ty, ghi_chi_cong_ty, giai_chi_cong_ty
    ghi_tam_ung_cong_ty(5_000_000, "di cong tac")
    ghi_chi_cong_ty(300_000, "taxi")
    ket_qua = giai_chi_cong_ty()
    assert ket_qua["da_giai_chi"] is True
    assert ket_qua["tong_tam_ung"] == 5_000_000
    assert ket_qua["tong_chi"] == 300_000
    assert ket_qua["so_du"] == 4_700_000
    assert "id" in ket_qua
    assert "/ui/tam-ung/" in ket_qua["duong_dan_pdf"]
    assert ket_qua["duong_dan_pdf"].endswith("/pdf")


def test_giai_chi_cong_ty_khoa_giao_dich_cu_mo_ky_moi():
    from app.tools import ghi_tam_ung_cong_ty, giai_chi_cong_ty, xem_so_du_cong_ty
    from app import storage
    ghi_tam_ung_cong_ty(5_000_000, "dot 1")
    giai_chi_cong_ty()
    ket_qua = xem_so_du_cong_ty()
    assert ket_qua["so_du"] == 0
    assert ket_qua["so_luong_giao_dich"] == 0
    assert storage.danh_sach_lan_giai_chi()[0]["tong_tam_ung"] == 5_000_000


def test_giai_chi_cong_ty_pdf_that_bai_khong_lam_mat_ket_qua_giai_chi(monkeypatch):
    """I1: neu sinh PDF that bai (vd het dung luong dia), giai_chi_cong_ty()
    van phai tra ve ket qua binh thuong -- ky da bi khoa durably trong DB
    truoc do (storage.giai_chi() da commit), khong the de loi PDF lam
    exception bay len nguoi goi (se thanh 500 o tang HTTP)."""
    from app import tools
    from app.tools import ghi_tam_ung_cong_ty, ghi_chi_cong_ty, giai_chi_cong_ty

    ghi_tam_ung_cong_ty(5_000_000, "di cong tac")
    ghi_chi_cong_ty(300_000, "taxi")

    def _loi(*a, **kw):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(tools.pdf_cong_ty, "tao_pdf_giai_chi", _loi)

    ket_qua = giai_chi_cong_ty()
    assert ket_qua["da_giai_chi"] is True
    assert ket_qua["so_du"] == 4_700_000
    assert "duong_dan_pdf" in ket_qua


def test_xem_ngan_sach_ap_dung_chi_phi_dac_biet():
    """fixture _db_tam (đầu file) chỉ cấu hình thiet_yeu/huong_thu -- KHÔNG
    có du_phong -- nên 100k tràn thẳng sang huong_thu (han mức gốc 10% của
    10tr = 1tr)."""
    from app.tools import xem_ngan_sach
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi", 100_000)
    ket_qua = xem_ngan_sach()
    hu_huong_thu = next(h for h in ket_qua["hu"] if h["ma"] == "huong_thu")
    assert hu_huong_thu["han_muc_thang"] == 900_000
    assert ket_qua["tong_chi_phi_dac_biet_thang_nay"] == 100_000
    assert ket_qua["canh_bao_chi_phi_dac_biet"] is None


def test_xem_ngan_sach_canh_bao_khi_vuot_ca_2_hu():
    """Không có du_phong trong fixture: 5tr vượt xa hạn mức gốc của
    huong_thu (1tr) -> huong_thu về 0, phần thiếu 4tr TỰ BÙ tiếp từ thiet_yeu
    theo THU_TU_BU (spec 2026-09-23-tu-bu-hu-am-design.md, quyết định 3 --
    trước đây chỉ cảnh báo "chưa có chỗ bù")."""
    from app.tools import xem_ngan_sach
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    ghi_chi_phi_dac_biet(thang_hien_tai(), "vien phi lon", 5_000_000)
    ket_qua = xem_ngan_sach()
    hu_huong_thu = next(h for h in ket_qua["hu"] if h["ma"] == "huong_thu")
    hu_thiet_yeu = next(h for h in ket_qua["hu"] if h["ma"] == "thiet_yeu")
    assert hu_huong_thu["han_muc_thang"] == 0
    assert hu_thiet_yeu["han_muc_thang"] == 1_000_000  # 5tr - 4tr bù phần thiếu
    assert hu_thiet_yeu["da_nhuong"] == 4_000_000
    assert ket_qua["canh_bao_chi_phi_dac_biet"] is not None
    assert "4,000,000" in ket_qua["canh_bao_chi_phi_dac_biet"]
    assert "đã tự bù" in ket_qua["canh_bao_chi_phi_dac_biet"]
    assert "chưa có chỗ bù" not in ket_qua["canh_bao_chi_phi_dac_biet"]
    assert ket_qua["tong_con_lai"] == 1_000_000


def test_ghi_chi_tieu_va_xem_ngan_sach_han_muc_nhat_quan_sau_chi_phi_dac_biet():
    """Ràng buộc quan trọng nhất task này: ghi_chi_tieu và xem_ngan_sach phải
    trả CÙNG 1 han_muc cho cùng 1 hũ ngay sau khi có khai báo chi phí đặc
    biệt -- đúng lớp lỗi Critical Tính năng B."""
    from app.tools import ghi_chi_tieu, xem_ngan_sach
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi", 300_000)
    han_muc_tu_ghi_chi_tieu = ghi_chi_tieu("huong_thu", 50_000)["han_muc_thang"]
    han_muc_tu_xem_ngan_sach = next(
        h for h in xem_ngan_sach()["hu"] if h["ma"] == "huong_thu"
    )["han_muc_thang"]
    assert han_muc_tu_ghi_chi_tieu == han_muc_tu_xem_ngan_sach == 700_000


def test_ghi_thu_nhap_them_han_muc_moi_phan_anh_chi_phi_dac_biet():
    from app.tools import ghi_thu_nhap_them
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi", 300_000)
    ket_qua = ghi_thu_nhap_them("thuong", 1)  # 1 VNĐ, không đổi han mức gốc đáng kể
    hu_huong_thu = next(h for h in ket_qua["han_muc_moi"] if h["ma"] == "huong_thu")
    assert hu_huong_thu["han_muc_thang"] == 700_000


def test_xem_ngan_sach_da_chi_khong_doi_boi_chi_phi_dac_biet():
    """da_chi TỪNG HŨ chỉ gồm khoản ghi_chi_tieu -- chi phí đặc biệt trừ vào
    ngân sách tháng qua hạn mức (co hẹp DP/HT), không cộng vào da_chi hũ nào
    (khai báo = đã chi ở mức TỔNG ngân sách, xem I1 23/09/2026)."""
    from app.tools import ghi_chi_tieu, xem_ngan_sach
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    ghi_chi_tieu("huong_thu", 200_000)
    ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi", 300_000)
    hu_huong_thu = next(h for h in xem_ngan_sach()["hu"] if h["ma"] == "huong_thu")
    assert hu_huong_thu["da_chi"] == 200_000  # khong bi cong them 300k


def test_khai_bao_chi_phi_dac_biet_thanh_cong():
    """fixture _db_tam (đầu file này) chỉ cấu hình 2 hũ thiet_yeu/huong_thu --
    KHÔNG có du_phong. han_muc_theo_ma.get("du_phong", 0) trong
    khai_bao_chi_phi_dac_biet() do đó trả về mặc định 0 (key không tồn tại
    trong dict, không phải "đã trừ về 0"). huong_thu (han mức gốc 10% của
    10tr = 1tr) hấp thụ toàn bộ 300k vì du_phong không tồn tại để trừ trước."""
    from app.tools import khai_bao_chi_phi_dac_biet
    ket_qua = khai_bao_chi_phi_dac_biet("hoc phi", 300_000)
    assert ket_qua["da_ghi"] is True
    assert ket_qua["mo_ta"] == "hoc phi"
    assert ket_qua["so_tien_vua_ghi"] == 300_000
    assert ket_qua["han_muc_du_phong_moi"] == 0
    assert ket_qua["han_muc_huong_thu_moi"] == 700_000
    assert ket_qua["canh_bao"] is None


def test_khai_bao_chi_phi_dac_biet_tra_ve_tong_con_lai_va_canh_bao_tong():
    """F6 (side note của I1, độc lập với ngữ nghĩa I1): phản hồi
    khai_bao_chi_phi_dac_biet phải có tong_con_lai/canh_bao_tong -- trước
    fix, một khai báo đẩy tổng xuống âm bị im lặng cho tới vòng cảnh báo
    chủ động kế tiếp."""
    from app.tools import khai_bao_chi_phi_dac_biet, xem_ngan_sach
    ket_qua = khai_bao_chi_phi_dac_biet("hoc phi", 300_000)
    assert "tong_con_lai" in ket_qua
    assert "canh_bao_tong" in ket_qua
    assert ket_qua["tong_con_lai"] == xem_ngan_sach()["tong_con_lai"]


def test_khai_bao_chi_phi_dac_biet_so_tien_am_bi_tu_choi():
    from app.tools import khai_bao_chi_phi_dac_biet
    ket_qua = khai_bao_chi_phi_dac_biet("hoc phi", -1000)
    assert "loi" in ket_qua


def test_khai_bao_chi_phi_dac_biet_so_tien_qua_lon_bi_tu_choi():
    from app.tools import khai_bao_chi_phi_dac_biet
    ket_qua = khai_bao_chi_phi_dac_biet("hoc phi", 10**13)
    assert "loi" in ket_qua


def test_khai_bao_chi_phi_dac_biet_mo_ta_rong_bi_tu_choi():
    from app.tools import khai_bao_chi_phi_dac_biet
    ket_qua = khai_bao_chi_phi_dac_biet("   ", 300_000)
    assert "loi" in ket_qua


def test_khai_bao_chi_phi_dac_biet_khong_dung_toi_jars_config_json():
    """Bất biến cách ly quan trọng nhất -- lặp lại ở tầng tools.py (không chỉ
    tầng jars.py Task 1 đã test) vì đây là đường Zalo bot thực sự gọi.
    Dùng thẳng jars_config.json thật do fixture _db_tam thiết lập (không
    tạo file giả riêng) -- khai_bao_chi_phi_dac_biet() có gọi xem_ngan_sach()
    nên NÓ CÓ ĐỌC config thật (hợp lệ, cần thiết để lấy %), điều cần xác
    nhận là nó không GHI đè lên file này."""
    import app.jars as jars
    from app.tools import khai_bao_chi_phi_dac_biet
    noi_dung_truoc = jars.JARS_CONFIG_PATH.read_bytes()

    khai_bao_chi_phi_dac_biet("hoc phi", 300_000)

    assert jars.JARS_CONFIG_PATH.read_bytes() == noi_dung_truoc


def test_ghi_chi_tieu_han_muc_0_voi_chi_tieu_bao_cao_vuot_100_phan_tram():
    """I1 review Tính năng D: han_muc == 0 (do bị điều chỉnh về 0 bởi khai
    báo chi phí đặc biệt) KHÔNG được đọc như "0% đã dùng" (fallback cũ dành
    cho hũ chưa cấu hình % -- ý nghĩa khác) -- nếu đã có chi tiêu thật, phải
    báo vượt (>=100%), không phải 0%."""
    from app.tools import ghi_chi_tieu
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi lon", 1_000_000)  # huong_thu han_muc_goc 1tr -> ve 0
    ket_qua = ghi_chi_tieu("huong_thu", 500_000)
    assert ket_qua["han_muc_truoc_bu"] == 0
    assert ket_qua["duoc_bu"] == 500_000  # tự bù từ thiet_yeu (spec 2026-09-23)
    assert ket_qua["han_muc_thang"] == 500_000
    assert ket_qua["ty_le_da_dung_phan_tram"] == 100.0
    assert ket_qua["trang_thai"] == "vuot_han_muc"


def test_xem_ngan_sach_han_muc_0_voi_da_chi_bao_cao_vuot_100_phan_tram():
    from app.tools import xem_ngan_sach, ghi_chi_tieu
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi lon", 1_000_000)
    ghi_chi_tieu("huong_thu", 500_000)
    hu_huong_thu = next(h for h in xem_ngan_sach()["hu"] if h["ma"] == "huong_thu")
    assert hu_huong_thu["han_muc_truoc_bu"] == 0
    assert hu_huong_thu["duoc_bu"] == 500_000
    assert hu_huong_thu["han_muc_thang"] == 500_000
    assert hu_huong_thu["ty_le_da_dung_phan_tram"] == 100.0


def test_xem_ngan_sach_han_muc_0_khong_co_chi_tieu_bao_cao_0_phan_tram():
    """Trường hợp nguyên gốc vẫn phải đúng: han_muc = 0 MÀ chưa chi gì thì
    vẫn là 0% (không crash chia cho 0, không báo vượt sai)."""
    from app.tools import xem_ngan_sach
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi lon", 1_000_000)
    hu_huong_thu = next(h for h in xem_ngan_sach()["hu"] if h["ma"] == "huong_thu")
    assert hu_huong_thu["han_muc_thang"] == 0
    assert hu_huong_thu["ty_le_da_dung_phan_tram"] == 0.0


def test_xem_ngan_sach_tra_ve_ngay_bat_dau_chu_ky_mac_dinh():
    from app.tools import xem_ngan_sach
    assert xem_ngan_sach()["ngay_bat_dau_chu_ky"] == 1


def test_xem_ngan_sach_tra_ve_ngay_bat_dau_chu_ky_da_cau_hinh():
    from app.tools import xem_ngan_sach
    from app.jars import doc_cau_hinh, ghi_cau_hinh
    cfg = doc_cau_hinh()
    cfg["ngay_bat_dau_chu_ky"] = 20
    ghi_cau_hinh(cfg)
    assert xem_ngan_sach()["ngay_bat_dau_chu_ky"] == 20


def test_thong_tin_ky_dung_dong_ho_gia_va_ngay_chu_ky_da_cau_hinh(monkeypatch):
    """F4/M4 (mutation test): _thong_tin_ky (qua xem_ngan_sach) phải dùng
    ĐÚNG ngay_bat_dau_chu_ky đã cấu hình (5), không hard-code ngày 1 -- đột
    biến M1 của reviewer ("ngay_bd = 1" trong app/tools.py, bỏ qua
    ngay_bat_dau_chu_ky()) khiến 328 test cũ vẫn pass hết; chỉ test dùng
    đồng hồ giả + chu kỳ khác 1 này bắt được. Đồng hồ giả phải patch CẢ
    app.tools.datetime LẪN app.jars.datetime (thang_hien_tai() dùng
    datetime.now() ở jars.py)."""
    from datetime import datetime
    import app.tools as tools_mod
    import app.jars as jars_mod
    from app.jars import doc_cau_hinh, ghi_cau_hinh
    from app.tools import xem_ngan_sach

    cfg = doc_cau_hinh()
    cfg["ngay_bat_dau_chu_ky"] = 5
    ghi_cau_hinh(cfg)

    class _DatetimeGiaLap(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 23, 10, 0)

    monkeypatch.setattr(tools_mod, "datetime", _DatetimeGiaLap)
    monkeypatch.setattr(jars_mod, "datetime", _DatetimeGiaLap)

    ns = xem_ngan_sach()
    assert ns["so_ngay_con_lai"] == 12
    assert ns["ngay_bat_dau_ky_sau"] == "2026-10-05"
    assert ns["trung_binh_moi_ngay_con_lai"] == ns["tong_con_lai"] // 12


def test_giao_dich_cong_ty_khong_lot_vao_tong_ca_nhan():
    """F4/M4 (mutation test): tiền công ty (tạm ứng/chi công ty) không được
    cộng vào tong_da_chi/tong_con_lai cá nhân -- bảng riêng
    (cong_ty_giao_dich), không đi qua chi_tieu/tinh_ngan_sach_thang."""
    from app.tools import ghi_tam_ung_cong_ty, ghi_chi_cong_ty, xem_ngan_sach

    truoc = xem_ngan_sach()
    ghi_tam_ung_cong_ty(2_000_000, "cong tac Da Nang")
    ghi_chi_cong_ty(480_000, "taxi san bay cong tac")
    sau = xem_ngan_sach()

    assert sau["tong_da_chi"] == truoc["tong_da_chi"]
    assert sau["tong_con_lai"] == truoc["tong_con_lai"]


def test_xem_ngan_sach_khong_sap_khi_ngay_chu_ky_ngoai_khoang_da_sua_tay():
    """F2/M2: jars_config.json sửa tay có ngay_bat_dau_chu_ky=31 từng làm
    xem_ngan_sach() raise ValueError ("day is out of range for month") ở
    ngay_bat_dau_ky_sau() -- ngay_bat_dau_chu_ky() giờ kẹp về 28 nên không
    sập nữa. /api/cau-hinh đã tự chặn 1-28 khi lưu qua /ui; giá trị ngoài
    khoảng chỉ phát sinh khi sửa tay file (CLAUDE.md cho phép)."""
    from app.jars import doc_cau_hinh, ghi_cau_hinh
    from app.tools import xem_ngan_sach
    cfg = doc_cau_hinh()
    cfg["ngay_bat_dau_chu_ky"] = 31
    ghi_cau_hinh(cfg)
    ns = xem_ngan_sach()  # không raise
    assert ns["ngay_bat_dau_chu_ky"] == 28


def test_de_xuat_dieu_chinh_khong_de_xuat_bu_vao_hu_da_ve_0_va_da_vuot():
    """I1 review: trước fix, de_xuat_dieu_chinh() gợi ý bù ngân sách VÀO
    chính hũ đã bị điều chỉnh về 0 và đã vượt chi -- lỗi nghiêm trọng vì đây
    là lời khuyên thực sự gửi qua Zalo cho người dùng."""
    from app.tools import de_xuat_dieu_chinh, ghi_chi_tieu
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    ghi_chi_phi_dac_biet(thang_hien_tai(), "hoc phi lon", 1_000_000)
    ghi_chi_tieu("huong_thu", 500_000)
    ket_qua = de_xuat_dieu_chinh()
    thong_bao_du_nhieu = [d for d in ket_qua["de_xuat"] if "còn dư nhiều" in d]
    assert not thong_bao_du_nhieu or "Hưởng Thụ" not in thong_bao_du_nhieu[0]
    thong_bao_vuot = [d for d in ket_qua["de_xuat"] if "sát/vượt hạn mức" in d]
    assert thong_bao_vuot and "Hưởng Thụ" in thong_bao_vuot[0]


def test_de_xuat_dieu_chinh_co_phan_bo_de_xuat_va_tach_luong():
    from app.tools import de_xuat_dieu_chinh, ghi_chi_tieu
    ghi_chi_tieu("thiet_yeu", 200_000)
    ket_qua = de_xuat_dieu_chinh()
    assert ket_qua["luong_co_dinh"] == 10_000_000
    assert ket_qua["thu_nhap_ngoai_luong_thang_nay"] == 0
    assert ket_qua["phan_bo_de_xuat"]["du_lieu_du"] is False
    ma_cac_hu = {d["ma"] for d in ket_qua["phan_bo_de_xuat"]["de_xuat"]}
    assert ma_cac_hu == {"thiet_yeu", "huong_thu"}


def test_de_xuat_dieu_chinh_thu_nhap_ngoai_luong_duoc_tach_rieng():
    from app.tools import de_xuat_dieu_chinh, ghi_thu_nhap_them
    ghi_thu_nhap_them("thuong", 2_000_000)
    ket_qua = de_xuat_dieu_chinh()
    assert ket_qua["luong_co_dinh"] == 10_000_000
    assert ket_qua["thu_nhap_ngoai_luong_thang_nay"] == 2_000_000


def test_tach_giao_dich_id_khong_ton_tai():
    from app.tools import tach_giao_dich
    ket_qua = tach_giao_dich(999999, [
        {"hu_ma": "thiet_yeu", "so_tien": 50_000, "ghi_chu": ""},
        {"hu_ma": "huong_thu", "so_tien": 50_000, "ghi_chu": ""},
    ])
    assert "loi" in ket_qua


def test_tach_giao_dich_thanh_cong_2_hu():
    from app import storage
    from app.tools import tach_giao_dich
    id_goc = storage.ghi_chi_tieu("thiet_yeu", 100_000, "sinh hoat")
    ket_qua = tach_giao_dich(id_goc, [
        {"hu_ma": "thiet_yeu", "so_tien": 60_000, "ghi_chu": "an uong"},
        {"hu_ma": "huong_thu", "so_tien": 40_000, "ghi_chu": "giai tri"},
    ])
    assert ket_qua["da_tach"] is True
    assert ket_qua["id_goc"] == id_goc
    assert len(ket_qua["id_moi"]) == 2
    assert ket_qua["so_luong_muc"] == 2
    ma_list = [c["ma"] for c in ket_qua["chi_tiet_hu_lien_quan"]]
    assert ma_list == ["thiet_yeu", "huong_thu"]
    thiet_yeu = next(c for c in ket_qua["chi_tiet_hu_lien_quan"] if c["ma"] == "thiet_yeu")
    assert thiet_yeu["da_chi_thang_nay"] == 60_000
    assert thiet_yeu["han_muc_thang"] == 5_000_000  # 50% cua 10tr (fixture)
    huong_thu = next(c for c in ket_qua["chi_tiet_hu_lien_quan"] if c["ma"] == "huong_thu")
    assert huong_thu["da_chi_thang_nay"] == 40_000
    assert huong_thu["han_muc_thang"] == 1_000_000  # 10% cua 10tr (fixture)


def test_tach_giao_dich_tong_khong_khop_bi_tu_choi():
    from app import storage
    from app.tools import tach_giao_dich
    id_goc = storage.ghi_chi_tieu("thiet_yeu", 100_000)
    ket_qua = tach_giao_dich(id_goc, [
        {"hu_ma": "thiet_yeu", "so_tien": 60_000, "ghi_chu": ""},
        {"hu_ma": "huong_thu", "so_tien": 30_000, "ghi_chu": ""},
    ])
    assert "loi" in ket_qua
    assert storage.chi_tieu_theo_id(id_goc) is not None  # KHONG bi xoa khi validate fail


def test_tach_giao_dich_it_hon_2_muc_bi_tu_choi():
    from app import storage
    from app.tools import tach_giao_dich
    id_goc = storage.ghi_chi_tieu("thiet_yeu", 100_000)
    ket_qua = tach_giao_dich(id_goc, [
        {"hu_ma": "thiet_yeu", "so_tien": 100_000, "ghi_chu": ""},
    ])
    assert "loi" in ket_qua
    assert storage.chi_tieu_theo_id(id_goc) is not None


def test_tach_giao_dich_hu_ma_khong_ton_tai_bi_tu_choi():
    from app import storage
    from app.tools import tach_giao_dich
    id_goc = storage.ghi_chi_tieu("thiet_yeu", 100_000)
    ket_qua = tach_giao_dich(id_goc, [
        {"hu_ma": "khong_ton_tai", "so_tien": 60_000, "ghi_chu": ""},
        {"hu_ma": "huong_thu", "so_tien": 40_000, "ghi_chu": ""},
    ])
    assert "loi" in ket_qua
    assert storage.chi_tieu_theo_id(id_goc) is not None


def test_tach_giao_dich_so_tien_am_bi_tu_choi():
    from app import storage
    from app.tools import tach_giao_dich
    id_goc = storage.ghi_chi_tieu("thiet_yeu", 100_000)
    ket_qua = tach_giao_dich(id_goc, [
        {"hu_ma": "thiet_yeu", "so_tien": -60_000, "ghi_chu": ""},
        {"hu_ma": "huong_thu", "so_tien": 160_000, "ghi_chu": ""},
    ])
    assert "loi" in ket_qua
    assert storage.chi_tieu_theo_id(id_goc) is not None


def test_tach_giao_dich_so_tien_chuoi_bi_tu_choi_khong_crash():
    from app import storage
    from app.tools import tach_giao_dich
    id_goc = storage.ghi_chi_tieu("thiet_yeu", 100_000)
    ket_qua = tach_giao_dich(id_goc, [
        {"hu_ma": "thiet_yeu", "so_tien": "60000", "ghi_chu": ""},
        {"hu_ma": "huong_thu", "so_tien": 40_000, "ghi_chu": ""},
    ])
    assert "loi" in ket_qua
    assert storage.chi_tieu_theo_id(id_goc) is not None


def test_tach_giao_dich_so_tien_float_le_bi_tu_choi():
    from app import storage
    from app.tools import tach_giao_dich
    id_goc = storage.ghi_chi_tieu("thiet_yeu", 100_000)
    ket_qua = tach_giao_dich(id_goc, [
        {"hu_ma": "thiet_yeu", "so_tien": 60_000.5, "ghi_chu": ""},
        {"hu_ma": "huong_thu", "so_tien": 39_999.5, "ghi_chu": ""},
    ])
    assert "loi" in ket_qua
    assert storage.chi_tieu_theo_id(id_goc) is not None


def test_tach_giao_dich_so_tien_bool_bi_tu_choi():
    from app import storage
    from app.tools import tach_giao_dich
    id_goc = storage.ghi_chi_tieu("thiet_yeu", 100_000)
    ket_qua = tach_giao_dich(id_goc, [
        {"hu_ma": "thiet_yeu", "so_tien": True, "ghi_chu": ""},
        {"hu_ma": "huong_thu", "so_tien": 99_999, "ghi_chu": ""},
    ])
    assert "loi" in ket_qua
    assert storage.chi_tieu_theo_id(id_goc) is not None


def test_xem_lich_su_mac_dinh_thang_hien_tai():
    from app import storage
    from app.jars import thang_hien_tai
    from app.tools import xem_lich_su
    id_khoan = storage.ghi_chi_tieu("thiet_yeu", 75_000, "an sang")
    ket_qua = xem_lich_su()
    assert ket_qua["thang"] == thang_hien_tai()
    assert ket_qua["so_luong"] == 1
    gd = ket_qua["giao_dich"][0]
    assert gd["id"] == id_khoan
    assert gd["hu_ma"] == "thiet_yeu"
    assert gd["hu_ten"] == "Thiết Yếu"
    assert gd["so_tien"] == 75_000
    assert gd["ghi_chu"] == "an sang"


def test_xem_lich_su_loc_dung_thang_duoc_truyen():
    from app import storage
    from app.tools import xem_lich_su
    id_thang_1 = storage.ghi_chi_tieu("thiet_yeu", 100_000, "thang 1", thang="2025-01")
    id_thang_2 = storage.ghi_chi_tieu("thiet_yeu", 200_000, "thang 2", thang="2025-02")
    ket_qua = xem_lich_su("2025-01")
    assert ket_qua["thang"] == "2025-01"
    assert ket_qua["so_luong"] == 1
    ids = [gd["id"] for gd in ket_qua["giao_dich"]]
    assert id_thang_1 in ids
    assert id_thang_2 not in ids


def test_xem_lich_su_thang_sai_dinh_dang_bi_tu_choi():
    from app.tools import xem_lich_su
    assert "loi" in xem_lich_su("2026")
    assert "loi" in xem_lich_su("not-a-month")


def test_xem_lich_su_thang_khong_co_giao_dich_tra_ve_rong():
    from app.tools import xem_lich_su
    ket_qua = xem_lich_su("2020-01")
    assert ket_qua == {"thang": "2020-01", "giao_dich": [], "so_luong": 0}


# ---------------------------------------------------------------------------
# Hũ âm tự bù + chặn chi vượt tổng (spec 2026-09-23-tu-bu-hu-am-design.md)
# ---------------------------------------------------------------------------


def test_xem_ngan_sach_hu_am_duoc_tu_bu_tu_hu_khac():
    from app.tools import ghi_chi_tieu, xem_ngan_sach
    ghi_chi_tieu("huong_thu", 1_300_000)  # hạn mức riêng 1tr -> âm 300k, bù từ thiet_yeu
    ket_qua = xem_ngan_sach()
    huong_thu = next(h for h in ket_qua["hu"] if h["ma"] == "huong_thu")
    thiet_yeu = next(h for h in ket_qua["hu"] if h["ma"] == "thiet_yeu")
    assert huong_thu["han_muc_truoc_bu"] == 1_000_000
    assert huong_thu["duoc_bu"] == 300_000
    assert huong_thu["bu_tu"] == [{"ma": "thiet_yeu", "ten": "Thiết Yếu", "so_tien": 300_000}]
    assert huong_thu["han_muc_thang"] == 1_300_000
    assert huong_thu["con_lai"] == 0
    assert huong_thu["ty_le_da_dung_phan_tram"] == 100.0
    assert thiet_yeu["da_nhuong"] == 300_000
    assert thiet_yeu["han_muc_thang"] == 4_700_000
    assert thiet_yeu["con_lai"] == 4_700_000


def test_xem_ngan_sach_hu_nhuong_het_bao_100_phan_tram():
    """Hũ đã nhường hết phần còn lại cho hũ khác: không còn đồng nào để chi
    ở hũ này -> 100% dù chưa chi gì."""
    from app.tools import ghi_chi_tieu, xem_ngan_sach
    ghi_chi_tieu("thiet_yeu", 6_000_000)  # âm 1tr -> rút hết 1tr của huong_thu
    huong_thu = next(h for h in xem_ngan_sach()["hu"] if h["ma"] == "huong_thu")
    assert huong_thu["han_muc_thang"] == 0
    assert huong_thu["da_nhuong"] == 1_000_000
    assert huong_thu["ty_le_da_dung_phan_tram"] == 100.0


def test_xem_ngan_sach_tra_ve_tong_con_chi_duoc_va_so_ngay():
    from app.tools import ghi_chi_tieu, xem_ngan_sach
    ghi_chi_tieu("thiet_yeu", 1_000_000)
    ket_qua = xem_ngan_sach()
    assert ket_qua["tong_ngan_sach"] == 6_000_000
    assert ket_qua["tong_da_chi"] == 1_000_000
    assert ket_qua["tong_con_lai"] == 5_000_000
    assert ket_qua["ty_le_tong_da_dung_phan_tram"] == 16.7
    assert ket_qua["so_ngay_con_lai"] >= 1
    assert ket_qua["trung_binh_moi_ngay_con_lai"] == 5_000_000 // ket_qua["so_ngay_con_lai"]
    assert len(ket_qua["ngay_bat_dau_ky_sau"]) == 10  # YYYY-MM-DD
    assert ket_qua["canh_bao_tong"] is None


def test_xem_ngan_sach_canh_bao_tong_khi_dung_tu_80_phan_tram():
    from app.tools import ghi_chi_tieu, xem_ngan_sach
    ghi_chi_tieu("thiet_yeu", 4_900_000)  # 4.9tr / 6tr = 81.7%
    ket_qua = xem_ngan_sach()
    assert ket_qua["canh_bao_tong"] is not None
    assert "⚠️" in ket_qua["canh_bao_tong"]
    assert "Chỉ còn 1,100,000 VNĐ" in ket_qua["canh_bao_tong"]


def test_xem_ngan_sach_chi_phi_dac_biet_khong_du_bu_het():
    from app.tools import xem_ngan_sach
    from app.storage import ghi_chi_phi_dac_biet
    from app.jars import thang_hien_tai
    ghi_chi_phi_dac_biet(thang_hien_tai(), "vien phi rat lon", 7_000_000)
    ket_qua = xem_ngan_sach()
    # huong_thu 1tr về 0, thiếu 6tr: thiet_yeu bù 5tr, còn 1tr không có chỗ bù
    assert "không đủ" in ket_qua["canh_bao_chi_phi_dac_biet"]
    assert "còn 1,000,000 VNĐ chưa có chỗ bù" in ket_qua["canh_bao_chi_phi_dac_biet"]
    assert ket_qua["tong_con_lai"] == -1_000_000
    assert "🚨" in ket_qua["canh_bao_tong"]


def test_ghi_chi_tieu_vuot_tong_khong_xac_nhan_thi_khong_ghi():
    from app.tools import ghi_chi_tieu
    from app import storage
    from app.jars import thang_hien_tai
    ghi_chi_tieu("thiet_yeu", 5_500_000)  # tổng ngân sách 6tr -> còn 500k
    ket_qua = ghi_chi_tieu("huong_thu", 700_000)
    assert ket_qua["da_ghi"] is False
    assert ket_qua["can_xac_nhan"] is True
    assert ket_qua["tong_con_lai"] == 500_000
    assert ket_qua["vuot_tong_neu_ghi"] == 200_000
    assert "200,000" in ket_qua["canh_bao"]
    assert "xac_nhan_vuot_tong=True" in ket_qua["huong_dan"]
    assert storage.tong_chi_trong_thang("huong_thu", thang_hien_tai()) == 0  # KHÔNG ghi


def test_ghi_chi_tieu_can_xac_nhan_co_du_3_khoa_thong_tin_ky():
    """F3/M3: nhánh can_xac_nhan phải có so_ngay_con_lai/ngay_bat_dau_ky_sau/
    trung_binh_moi_ngay_con_lai như docstring app/main.py hứa ("Kết quả
    luôn có... LUÔN nêu 3 số này") -- trước fix nhánh này chỉ có
    tong_con_lai, ép model nêu 2 số không tồn tại trong kết quả."""
    from app.tools import ghi_chi_tieu
    ghi_chi_tieu("thiet_yeu", 5_500_000)  # tổng ngân sách 6tr -> còn 500k
    ket_qua = ghi_chi_tieu("huong_thu", 700_000)
    assert ket_qua["can_xac_nhan"] is True
    assert "so_ngay_con_lai" in ket_qua
    assert "ngay_bat_dau_ky_sau" in ket_qua
    assert "trung_binh_moi_ngay_con_lai" in ket_qua


def test_ghi_chi_tieu_vuot_tong_co_xac_nhan_thi_ghi_va_canh_bao_do():
    from app.tools import ghi_chi_tieu
    from app import storage
    from app.jars import thang_hien_tai
    ghi_chi_tieu("thiet_yeu", 5_500_000)
    ket_qua = ghi_chi_tieu("huong_thu", 700_000, "", xac_nhan_vuot_tong=True)
    assert ket_qua["da_ghi"] is True
    assert ket_qua["tong_con_lai"] == -200_000
    assert "🚨" in ket_qua["canh_bao"]
    assert "200,000" in ket_qua["canh_bao"]
    assert storage.tong_chi_trong_thang("huong_thu", thang_hien_tai()) == 700_000


def test_ghi_chi_tieu_khi_tong_da_am_moi_khoan_deu_can_xac_nhan():
    from app.tools import ghi_chi_tieu
    ghi_chi_tieu("thiet_yeu", 6_100_000, "", xac_nhan_vuot_tong=True)  # tổng 6tr -> âm 100k
    ket_qua = ghi_chi_tieu("thiet_yeu", 10_000)
    assert ket_qua["da_ghi"] is False
    assert ket_qua["can_xac_nhan"] is True
    assert ket_qua["vuot_tong_neu_ghi"] == 110_000


def test_ghi_chi_tieu_tieu_vua_het_tong_khong_can_xac_nhan():
    from app.tools import ghi_chi_tieu
    ghi_chi_tieu("thiet_yeu", 5_000_000)
    ket_qua = ghi_chi_tieu("huong_thu", 1_000_000)  # còn đúng 1tr -> về 0, không vượt
    assert ket_qua["da_ghi"] is True
    assert ket_qua["tong_con_lai"] == 0


def test_ghi_chi_tieu_hu_am_trong_tong_bao_da_bu_tu_hu_nao():
    from app.tools import ghi_chi_tieu
    ket_qua = ghi_chi_tieu("huong_thu", 1_300_000)
    assert ket_qua["da_ghi"] is True
    assert ket_qua["trang_thai"] == "vuot_han_muc"
    assert ket_qua["han_muc_truoc_bu"] == 1_000_000
    assert ket_qua["duoc_bu"] == 300_000
    assert ket_qua["han_muc_thang"] == 1_300_000
    assert ket_qua["con_lai"] == 0
    assert "Thiết Yếu 300,000" in ket_qua["canh_bao"]
    assert ket_qua["tong_con_lai"] == 4_700_000


def test_ghi_chi_tieu_hu_chi_bi_rut_bu_khong_bi_bao_vuot():
    """Hũ nhường hết phần còn lại cho hũ khác rồi chi trong hạn mức RIÊNG của
    nó: ty_le hiệu lực 100% nhưng trang_thai phải là binh_thuong."""
    from app.tools import ghi_chi_tieu
    ghi_chi_tieu("thiet_yeu", 5_900_000)  # âm 900k -> rút 900k từ huong_thu
    ket_qua = ghi_chi_tieu("huong_thu", 100_000)  # 10% hạn mức riêng 1tr
    assert ket_qua["da_ghi"] is True
    assert ket_qua["ty_le_da_dung_phan_tram"] == 100.0
    assert ket_qua["trang_thai"] == "binh_thuong"


def test_ghi_chi_tieu_luon_tra_tong_con_lai_va_so_ngay():
    from app.tools import ghi_chi_tieu
    ket_qua = ghi_chi_tieu("thiet_yeu", 100_000)
    assert ket_qua["tong_con_lai"] == 5_900_000
    assert ket_qua["so_ngay_con_lai"] >= 1
    assert ket_qua["trung_binh_moi_ngay_con_lai"] == 5_900_000 // ket_qua["so_ngay_con_lai"]
    assert ket_qua["canh_bao"] is None


def test_de_xuat_dieu_chinh_bao_da_tu_bu_va_khong_goi_y_tam_bu_nua():
    from app.tools import de_xuat_dieu_chinh, ghi_chi_tieu
    ghi_chi_tieu("huong_thu", 1_500_000)
    ket_qua = de_xuat_dieu_chinh()
    assert any("Đã tự động bù" in d and "Hưởng Thụ" in d for d in ket_qua["de_xuat"])
    assert not any("còn dư nhiều" in d for d in ket_qua["de_xuat"])


def test_de_xuat_dieu_chinh_hu_chi_bi_rut_khong_bi_goi_la_vuot():
    from app.tools import de_xuat_dieu_chinh, ghi_chi_tieu
    ghi_chi_tieu("thiet_yeu", 6_000_000)  # âm 1tr -> rút hết 1tr của huong_thu
    ket_qua = de_xuat_dieu_chinh()
    dong_vuot = [d for d in ket_qua["de_xuat"] if "sát/vượt hạn mức" in d]
    assert dong_vuot
    assert "Thiết Yếu" in dong_vuot[0]
    assert "Hưởng Thụ" not in dong_vuot[0]


def test_tach_giao_dich_tra_han_muc_hieu_luc_sau_tu_bu():
    from app import storage
    from app.tools import tach_giao_dich
    id_goc = storage.ghi_chi_tieu("thiet_yeu", 1_300_000, "gop")
    ket_qua = tach_giao_dich(id_goc, [
        {"hu_ma": "thiet_yeu", "so_tien": 100_000, "ghi_chu": "an"},
        {"hu_ma": "huong_thu", "so_tien": 1_200_000, "ghi_chu": "choi"},
    ])
    huong_thu = next(c for c in ket_qua["chi_tiet_hu_lien_quan"] if c["ma"] == "huong_thu")
    assert huong_thu["han_muc_thang"] == 1_200_000  # riêng 1tr + được bù 200k
    assert huong_thu["con_lai"] == 0


def test_ghi_thu_nhap_them_tra_han_muc_hieu_luc_sau_tu_bu():
    from app.tools import ghi_chi_tieu, ghi_thu_nhap_them
    ghi_chi_tieu("huong_thu", 1_500_000)
    ket_qua = ghi_thu_nhap_them("thuong", 2_000_000)  # huong_thu riêng 1.2tr -> âm 300k
    huong_thu = next(h for h in ket_qua["han_muc_moi"] if h["ma"] == "huong_thu")
    assert huong_thu["han_muc_thang"] == 1_500_000


def test_xem_so_du_cong_ty_liet_ke_tung_giao_dich():
    from app.tools import ghi_tam_ung_cong_ty, ghi_chi_cong_ty, xem_so_du_cong_ty
    ghi_tam_ung_cong_ty(2_000_000, "Tạm ứng công ty")
    ghi_chi_cong_ty(480_000, "vé xe đi công tác")
    ket_qua = xem_so_du_cong_ty()
    assert ket_qua["so_du"] == 1_520_000
    assert len(ket_qua["giao_dich"]) == 2
    theo_mo_ta = {g["mo_ta"]: (g["loai"], g["so_tien"]) for g in ket_qua["giao_dich"]}
    assert theo_mo_ta["Tạm ứng công ty"] == ("tam_ung", 2_000_000)
    assert theo_mo_ta["vé xe đi công tác"] == ("chi", 480_000)
    assert all({"id", "thoi_gian", "loai", "so_tien", "mo_ta"} <= set(g) for g in ket_qua["giao_dich"])


def _cau_hinh_6_hu_10tr():
    """Cấu hình đúng kịch bản tái hiện I1 của reviewer: thu nhập 10tr, 6 hũ
    50/10/10/10/10/10."""
    from app.jars import doc_cau_hinh, ghi_cau_hinh
    cfg = doc_cau_hinh()
    cfg["thu_nhap_thuc_linh_thang"] = 10_000_000
    cfg["hu"] = [
        {"ma": ma, "ten": ma, "ty_le_phan_tram": pt}
        for ma, pt in (("thiet_yeu", 50), ("gia_dinh", 10), ("hoc_tap", 10),
                       ("du_phong", 10), ("huong_thu", 10), ("tu_do_tai_chinh", 10))
    ]
    ghi_cau_hinh(cfg)


def test_chi_phi_dac_biet_khai_bao_la_da_chi_khong_ghi_lai_khoan_that():
    """I1 (review Hũ âm tự bù 23/09/2026), người dùng chọn A: khai báo chi phí
    đặc biệt = ĐÃ CHI, trừ thẳng vào ngân sách tháng; khi trả tiền thật KHÔNG
    ghi_chi_tieu lại. Kịch bản reviewer: sau khai báo 3tr còn 7tr, chi thật
    5tr cho thiết yếu thì còn 2tr -- không bị hỏi xác nhận vượt tổng."""
    from app.tools import ghi_chi_tieu, khai_bao_chi_phi_dac_biet
    _cau_hinh_6_hu_10tr()
    assert khai_bao_chi_phi_dac_biet("hoc phi ky 1", 3_000_000)["tong_con_lai"] == 7_000_000
    ket_qua = ghi_chi_tieu("thiet_yeu", 5_000_000, "chi sinh hoat")
    assert ket_qua["da_ghi"] is True
    assert not ket_qua.get("can_xac_nhan")
    assert ket_qua["tong_con_lai"] == 2_000_000


def test_xem_ngan_sach_liet_ke_chi_phi_dac_biet_thang_nay():
    """Để bot tra được khoản đã khai báo trước khi ghi khoản trả thật (docstring
    ghi_chi_tieu dặn không ghi lại) -- chỉ có tổng thì không biết khoản nào."""
    from app.tools import khai_bao_chi_phi_dac_biet, xem_ngan_sach
    khai_bao_chi_phi_dac_biet("hoc phi ky 1", 300_000)
    khai_bao_chi_phi_dac_biet("vien phi", 200_000)
    danh_sach = xem_ngan_sach()["chi_phi_dac_biet_thang_nay"]
    assert sorted((k["mo_ta"], k["so_tien"]) for k in danh_sach) == [("hoc phi ky 1", 300_000), ("vien phi", 200_000)]
    assert all(isinstance(k["id"], int) for k in danh_sach)
