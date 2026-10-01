"""Test app/jars.py — đọc/ghi cấu hình 6 Hũ qua tmp_path, không đụng
data/jars_config.json thật (theo đúng pattern các file test khác)."""
import os
import sys
from pathlib import Path
from datetime import datetime

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _jars_config_tam(tmp_path, monkeypatch):
    import app.jars as jars
    monkeypatch.setattr(jars, "JARS_CONFIG_PATH", tmp_path / "jars_config.json")
    import app.storage as storage
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "chi_tieu_test.db")
    storage.khoi_tao_db()
    yield


def test_ghi_cau_hinh_roundtrip_qua_doc_cau_hinh():
    from app.jars import ghi_cau_hinh, doc_cau_hinh
    cfg = {
        "thu_nhap_thuc_linh_thang": 15_000_000,
        "hu": [{"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 55.0}],
        "nguong_canh_bao": [0.65, 0.8, 1.0],
    }
    ghi_cau_hinh(cfg)
    assert doc_cau_hinh() == cfg


def test_ghi_cau_hinh_ghi_atomic_khong_de_lai_file_tmp():
    """M2: ghi_cau_hinh phải ghi qua file .tmp rồi os.replace() — sau khi ghi
    xong, file thật phải tồn tại và không còn file .tmp rơi rớt lại."""
    import app.jars as jars
    jars.ghi_cau_hinh({"thu_nhap_thuc_linh_thang": 1, "hu": [], "nguong_canh_bao": []})
    assert jars.JARS_CONFIG_PATH.exists()
    assert not Path(f"{jars.JARS_CONFIG_PATH}.tmp").exists()


def test_ghi_cau_hinh_flush_va_fsync_truoc_khi_replace(monkeypatch):
    """M2 round 2: os.replace() atomic chỉ bảo vệ nếu process crash giữa
    chừng -- không bảo vệ nếu kernel/mất điện trước khi data thực sự xuống
    đĩa. Phải flush() + os.fsync() trước os.replace(). Spy lên os.fsync (vẫn
    gọi hàm thật) để xác nhận nó thực sự được gọi, đúng 1 lần, trước khi ghi
    xong."""
    import app.jars as jars
    fsync_that = os.fsync
    cac_lan_goi = []

    def fsync_gia(fd):
        cac_lan_goi.append(fd)
        return fsync_that(fd)

    monkeypatch.setattr(jars.os, "fsync", fsync_gia)
    jars.ghi_cau_hinh({"thu_nhap_thuc_linh_thang": 1, "hu": [], "nguong_canh_bao": []})
    assert len(cac_lan_goi) == 1


def test_ghi_cau_hinh_don_file_tmp_neu_that_bai_giua_chung():
    """Nếu json.dump() tự nó raise (vd cfg chứa object không serialize được),
    trước đây file .tmp sẽ rơi rớt lại vĩnh viễn. Phải dọn nó đi VÀ vẫn
    raise lại lỗi gốc (không nuốt lỗi)."""
    import app.jars as jars

    class KhongTheSerialize:
        pass

    with pytest.raises(TypeError):
        jars.ghi_cau_hinh({"xau": KhongTheSerialize()})
    assert not Path(f"{jars.JARS_CONFIG_PATH}.tmp").exists()
    assert not jars.JARS_CONFIG_PATH.exists()


def test_thu_nhap_hieu_qua_cong_thu_nhap_them():
    from app.jars import ghi_cau_hinh, thu_nhap_hieu_qua
    from app.storage import ghi_thu_nhap_them
    ghi_cau_hinh({"thu_nhap_thuc_linh_thang": 10_000_000, "hu": [], "nguong_canh_bao": []})
    ghi_thu_nhap_them("thuong", 1_000_000)
    thang = datetime.now().strftime("%Y-%m")
    assert thu_nhap_hieu_qua(thang) == 11_000_000


def test_thu_nhap_hieu_qua_khong_co_thu_them():
    from app.jars import ghi_cau_hinh, thu_nhap_hieu_qua
    ghi_cau_hinh({"thu_nhap_thuc_linh_thang": 10_000_000, "hu": [], "nguong_canh_bao": []})
    thang = datetime.now().strftime("%Y-%m")
    assert thu_nhap_hieu_qua(thang) == 10_000_000


def test_tinh_han_muc_da_dieu_chinh_khong_co_khai_bao_thi_giu_nguyen():
    from app.jars import tinh_han_muc_da_dieu_chinh
    han_muc_goc = {"du_phong": 1_000_000, "huong_thu": 1_000_000, "thiet_yeu": 5_000_000}
    ket_qua = tinh_han_muc_da_dieu_chinh("2026-09", han_muc_goc)
    assert ket_qua["han_muc"] == han_muc_goc
    assert ket_qua["tong_chi_phi_dac_biet"] == 0
    assert ket_qua["con_thieu"] == 0


def test_tinh_han_muc_da_dieu_chinh_tru_du_phong_truoc():
    from app.jars import tinh_han_muc_da_dieu_chinh
    from app.storage import ghi_chi_phi_dac_biet
    ghi_chi_phi_dac_biet("2026-09", "sua xe", 600_000)
    han_muc_goc = {"du_phong": 1_000_000, "huong_thu": 1_000_000}
    ket_qua = tinh_han_muc_da_dieu_chinh("2026-09", han_muc_goc)
    assert ket_qua["han_muc"]["du_phong"] == 400_000
    assert ket_qua["han_muc"]["huong_thu"] == 1_000_000  # chua dung toi
    assert ket_qua["con_thieu"] == 0


def test_tinh_han_muc_da_dieu_chinh_tran_sang_huong_thu():
    from app.jars import tinh_han_muc_da_dieu_chinh
    from app.storage import ghi_chi_phi_dac_biet
    ghi_chi_phi_dac_biet("2026-09", "hoc phi", 1_500_000)
    han_muc_goc = {"du_phong": 1_000_000, "huong_thu": 1_000_000}
    ket_qua = tinh_han_muc_da_dieu_chinh("2026-09", han_muc_goc)
    assert ket_qua["han_muc"]["du_phong"] == 0
    assert ket_qua["han_muc"]["huong_thu"] == 500_000
    assert ket_qua["con_thieu"] == 0


def test_tinh_han_muc_da_dieu_chinh_vuot_ca_2_hu_tra_con_thieu():
    from app.jars import tinh_han_muc_da_dieu_chinh
    from app.storage import ghi_chi_phi_dac_biet
    ghi_chi_phi_dac_biet("2026-09", "vien phi lon", 3_000_000)
    han_muc_goc = {"du_phong": 1_000_000, "huong_thu": 1_000_000, "thiet_yeu": 5_000_000}
    ket_qua = tinh_han_muc_da_dieu_chinh("2026-09", han_muc_goc)
    assert ket_qua["han_muc"]["du_phong"] == 0
    assert ket_qua["han_muc"]["huong_thu"] == 0
    assert ket_qua["han_muc"]["thiet_yeu"] == 5_000_000  # KHONG cascade sang hu khac
    assert ket_qua["con_thieu"] == 1_000_000


def test_tinh_han_muc_da_dieu_chinh_nhieu_khai_bao_cong_don():
    from app.jars import tinh_han_muc_da_dieu_chinh
    from app.storage import ghi_chi_phi_dac_biet
    ghi_chi_phi_dac_biet("2026-09", "hoc phi", 4_000_000)
    ghi_chi_phi_dac_biet("2026-09", "vien phi", 1_000_000)
    han_muc_goc = {"du_phong": 1_000_000, "huong_thu": 1_000_000}
    ket_qua = tinh_han_muc_da_dieu_chinh("2026-09", han_muc_goc)
    assert ket_qua["tong_chi_phi_dac_biet"] == 5_000_000
    assert ket_qua["han_muc"]["du_phong"] == 0
    assert ket_qua["han_muc"]["huong_thu"] == 0
    assert ket_qua["con_thieu"] == 3_000_000


def test_tinh_han_muc_da_dieu_chinh_khong_dung_toi_thang_khac():
    """Bất biến cách ly theo tháng — khai báo tháng 9 KHÔNG được ảnh hưởng
    han_muc tính cho tháng 8."""
    from app.jars import tinh_han_muc_da_dieu_chinh
    from app.storage import ghi_chi_phi_dac_biet
    ghi_chi_phi_dac_biet("2026-09", "hoc phi", 4_000_000)
    han_muc_goc = {"du_phong": 1_000_000, "huong_thu": 1_000_000}
    ket_qua = tinh_han_muc_da_dieu_chinh("2026-08", han_muc_goc)
    assert ket_qua["han_muc"] == han_muc_goc
    assert ket_qua["con_thieu"] == 0


def test_tinh_han_muc_da_dieu_chinh_khong_dung_toi_jars_config_json(tmp_path, monkeypatch):
    """Bất biến cách ly quan trọng nhất (bài học I3 Tính năng C): hàm này
    KHÔNG được đọc/ghi jars_config.json dưới bất kỳ hình thức nào — chỉ
    tính toán thuần trên dict truyền vào + dữ liệu DB."""
    import app.jars as jars
    duong_dan_gia = tmp_path / "jars_config_khong_duoc_dung.json"
    duong_dan_gia.write_text('{"day la du lieu goc, khong duoc doc/ghi": true}', encoding="utf-8")
    monkeypatch.setattr(jars, "JARS_CONFIG_PATH", duong_dan_gia)
    noi_dung_truoc = duong_dan_gia.read_bytes()

    from app.storage import ghi_chi_phi_dac_biet
    ghi_chi_phi_dac_biet("2026-09", "hoc phi", 4_000_000)
    jars.tinh_han_muc_da_dieu_chinh("2026-09", {"du_phong": 1_000_000, "huong_thu": 1_000_000})

    assert duong_dan_gia.read_bytes() == noi_dung_truoc


def test_nhan_dang_chu_ky_ngay_bat_dau_1_giong_lich_duong():
    from app.jars import nhan_dang_chu_ky
    from datetime import datetime
    assert nhan_dang_chu_ky(datetime(2026, 9, 1), 1) == "2026-09"
    assert nhan_dang_chu_ky(datetime(2026, 9, 30), 1) == "2026-09"


def test_nhan_dang_chu_ky_truoc_ngay_bat_dau_lui_1_thang():
    from app.jars import nhan_dang_chu_ky
    from datetime import datetime
    assert nhan_dang_chu_ky(datetime(2026, 9, 4), 5) == "2026-08"
    assert nhan_dang_chu_ky(datetime(2026, 9, 5), 5) == "2026-09"
    assert nhan_dang_chu_ky(datetime(2026, 9, 6), 5) == "2026-09"


def test_nhan_dang_chu_ky_bac_qua_ranh_gioi_nam():
    from app.jars import nhan_dang_chu_ky
    from datetime import datetime
    assert nhan_dang_chu_ky(datetime(2026, 1, 4), 5) == "2025-12"
    assert nhan_dang_chu_ky(datetime(2026, 1, 5), 5) == "2026-01"


def test_ngay_bat_dau_chu_ky_mac_dinh_1_khi_chua_cau_hinh():
    from app.jars import ghi_cau_hinh, ngay_bat_dau_chu_ky
    ghi_cau_hinh({"thu_nhap_thuc_linh_thang": 10_000_000, "hu": [], "nguong_canh_bao": []})
    assert ngay_bat_dau_chu_ky() == 1


def test_ngay_bat_dau_chu_ky_doc_dung_gia_tri_da_cau_hinh():
    from app.jars import ghi_cau_hinh, ngay_bat_dau_chu_ky
    ghi_cau_hinh({"thu_nhap_thuc_linh_thang": 10_000_000, "hu": [], "nguong_canh_bao": [],
                  "ngay_bat_dau_chu_ky": 15})
    assert ngay_bat_dau_chu_ky() == 15


def test_ngay_bat_dau_chu_ky_kep_gia_tri_qua_lon_ve_28():
    """F2/M2: jars_config.json sửa tay có thể có ngay_bat_dau_chu_ky ngoài
    1-28 (vd 31) -- trước fix, giá trị này lọt thẳng xuống
    ngay_bat_dau_ky_sau() và làm date(năm, tháng, 31) raise ValueError vào
    những tháng không có ngày 31. Kẹp về 28."""
    from app.jars import ghi_cau_hinh, ngay_bat_dau_chu_ky
    ghi_cau_hinh({"thu_nhap_thuc_linh_thang": 10_000_000, "hu": [], "nguong_canh_bao": [],
                  "ngay_bat_dau_chu_ky": 31})
    assert ngay_bat_dau_chu_ky() == 28


def test_ngay_bat_dau_chu_ky_kep_gia_tri_qua_nho_ve_1():
    from app.jars import ghi_cau_hinh, ngay_bat_dau_chu_ky
    ghi_cau_hinh({"thu_nhap_thuc_linh_thang": 10_000_000, "hu": [], "nguong_canh_bao": [],
                  "ngay_bat_dau_chu_ky": 0})
    assert ngay_bat_dau_chu_ky() == 1


def test_thang_hien_tai_dung_ngay_bat_dau_chu_ky_da_cau_hinh(monkeypatch):
    """thang_hien_tai() phai cycle-aware -- gia lap "hom nay" la ngay truoc
    ngay_bat_dau_chu_ky da cau hinh, xac nhan tra ve thang TRUOC."""
    from app.jars import ghi_cau_hinh
    import app.jars as jars
    from datetime import datetime

    ghi_cau_hinh({"thu_nhap_thuc_linh_thang": 10_000_000, "hu": [], "nguong_canh_bao": [],
                  "ngay_bat_dau_chu_ky": 20})

    class _DatetimeGiaLap(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 10)  # truoc ngay 20 -> thuoc chu ky thang 8

    monkeypatch.setattr(jars, "datetime", _DatetimeGiaLap)
    assert jars.thang_hien_tai() == "2026-08"


def test_tinh_de_xuat_phan_bo_khong_du_lieu_tra_ve_cau_hinh_hien_tai():
    from app.jars import ghi_cau_hinh, tinh_de_xuat_phan_bo
    ghi_cau_hinh({
        "thu_nhap_thuc_linh_thang": 10_000_000,
        "hu": [
            {"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 50.0},
            {"ma": "huong_thu", "ten": "Hưởng Thụ", "ty_le_phan_tram": 10.0},
        ],
        "nguong_canh_bao": [0.65, 0.8, 1.0],
    })
    ket_qua = tinh_de_xuat_phan_bo("2026-09")
    assert ket_qua["du_lieu_du"] is False
    assert ket_qua["de_xuat"] == [
        {"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 50.0},
        {"ma": "huong_thu", "ten": "Hưởng Thụ", "ty_le_phan_tram": 10.0},
    ]


def test_tinh_de_xuat_phan_bo_co_du_lieu_chuan_hoa_dung_100():
    from app.jars import ghi_cau_hinh, tinh_de_xuat_phan_bo, thang_hien_tai
    from app import storage
    from app.storage import db, ba_thang_lien_truoc
    ghi_cau_hinh({
        "thu_nhap_thuc_linh_thang": 10_000_000,
        "hu": [
            {"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 50.0},
            {"ma": "huong_thu", "ten": "Hưởng Thụ", "ty_le_phan_tram": 10.0},
        ],
        "nguong_canh_bao": [0.65, 0.8, 1.0],
    })
    thang = thang_hien_tai()
    for thang_truoc in ba_thang_lien_truoc(thang):
        id1 = storage.ghi_chi_tieu("thiet_yeu", 3_000_000)
        id2 = storage.ghi_chi_tieu("huong_thu", 1_000_000)
        with db() as conn:
            conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?",
                         (f"{thang_truoc}-05T12:00:00", thang_truoc, id1))
            conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?",
                         (f"{thang_truoc}-05T12:00:00", thang_truoc, id2))
    ket_qua = tinh_de_xuat_phan_bo(thang)
    assert ket_qua["du_lieu_du"] is True
    tong = sum(d["ty_le_phan_tram"] for d in ket_qua["de_xuat"])
    assert tong == pytest.approx(100.0)
    de_xuat_thiet_yeu = next(d["ty_le_phan_tram"] for d in ket_qua["de_xuat"] if d["ma"] == "thiet_yeu")
    de_xuat_huong_thu = next(d["ty_le_phan_tram"] for d in ket_qua["de_xuat"] if d["ma"] == "huong_thu")
    # thiet_yeu chi gap 3 lan huong_thu (3tr vs 1tr) -> ty le de xuat cung ~gap 3 lan
    assert de_xuat_thiet_yeu == pytest.approx(75.0, abs=0.1)
    assert de_xuat_huong_thu == pytest.approx(25.0, abs=0.1)


def test_tinh_de_xuat_phan_bo_hu_khong_co_chi_duoc_tinh_0():
    from app.jars import ghi_cau_hinh, tinh_de_xuat_phan_bo, thang_hien_tai
    from app import storage
    from app.storage import db, ba_thang_lien_truoc
    ghi_cau_hinh({
        "thu_nhap_thuc_linh_thang": 10_000_000,
        "hu": [
            {"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 50.0},
            {"ma": "huong_thu", "ten": "Hưởng Thụ", "ty_le_phan_tram": 10.0},
        ],
        "nguong_canh_bao": [0.65, 0.8, 1.0],
    })
    thang = thang_hien_tai()
    # Chi that chi o "huong_thu" (hu thu 2, khong phai hu cuoi de tranh vo tinh
    # nhan phan du lam tron) -- "thiet_yeu" (hu dau) khong co dong chi nao.
    for thang_truoc in ba_thang_lien_truoc(thang):
        id1 = storage.ghi_chi_tieu("huong_thu", 500_000)
        with db() as conn:
            conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?",
                         (f"{thang_truoc}-05T12:00:00", thang_truoc, id1))
    ket_qua = tinh_de_xuat_phan_bo(thang)
    assert ket_qua["du_lieu_du"] is True
    de_xuat_thiet_yeu = next(d["ty_le_phan_tram"] for d in ket_qua["de_xuat"] if d["ma"] == "thiet_yeu")
    de_xuat_huong_thu = next(d["ty_le_phan_tram"] for d in ket_qua["de_xuat"] if d["ma"] == "huong_thu")
    assert de_xuat_thiet_yeu == 0.0
    assert de_xuat_huong_thu == pytest.approx(100.0)


def test_tinh_de_xuat_phan_bo_hu_cuoi_khong_chi_khong_bao_gio_am():
    """Critical (review nhánh Đề xuất phân bổ hũ thông minh): hũ CUỐI theo thứ
    tự danh_sach_hu() -- trong cấu hình thật của dự án là tu_do_tai_chinh, hũ
    CHỈ ĐỂ TIẾT KIỆM nên bình thường không hề có dòng chi tiêu nào -- KHÔNG
    còn được phép nhận "phần dư làm tròn" theo vị trí list nữa. Trước fix,
    nếu 5 hũ trước đó làm tròn LÊN cộng dồn vượt 100.0 (kịch bản tái tạo
    đúng ở đây), hũ cuối bị ép nhận phần dư ÂM -- vô nghĩa và bị
    /api/cau-hinh từ chối 400 sau khi UI đã hiện tổng hợp lệ 100% màu xanh.
    Đây là bản đối xứng của test_..._hu_khong_co_chi_duoc_tinh_0 ở trên (test
    đó cố tình đặt hũ chi=0 ở vị trí ĐẦU để né đúng bug này; test này đặt hũ
    chi=0 ở đúng vị trí CUỐI để xác nhận bug đã được vá)."""
    from app.jars import ghi_cau_hinh, tinh_de_xuat_phan_bo, thang_hien_tai
    from app import storage
    from app.storage import db, ba_thang_lien_truoc
    ghi_cau_hinh({
        "thu_nhap_thuc_linh_thang": 10_000_000,
        "hu": [
            {"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 50.0},
            {"ma": "gia_dinh", "ten": "Gia Đình", "ty_le_phan_tram": 12.6},
            {"ma": "hoc_tap", "ten": "Học Tập & Nâng Cao", "ty_le_phan_tram": 10.0},
            {"ma": "du_phong", "ten": "Dự Phòng Khẩn Cấp", "ty_le_phan_tram": 10.0},
            {"ma": "huong_thu", "ten": "Hưởng Thụ & Giải Trí", "ty_le_phan_tram": 7.9},
            {"ma": "tu_do_tai_chinh", "ten": "Tự Do Tài Chính & Đầu Tư", "ty_le_phan_tram": 9.5},
        ],
        "nguong_canh_bao": [0.65, 0.8, 1.0],
    })
    thang = thang_hien_tai()
    # Chi thật ở 5 hũ đầu, đều đặt giá trị làm cho tỷ lệ thô sau chuẩn hoá +
    # làm tròn LÊN (kịch bản tái tạo đúng bug: tổng 5 hũ làm tròn cộng dồn
    # 100.1, hũ cuối -- tu_do_tai_chinh -- trước fix sẽ phải nhận 100.0 -
    # 100.1 = -0.1). "tu_do_tai_chinh" KHÔNG được ghi bất kỳ dòng chi nào
    # trong cả 3 tháng -- đúng thực tế: đây là hũ chỉ để tiết kiệm.
    chi_moi_thang = {
        "thiet_yeu": 5_100_000,
        "gia_dinh": 1_250_000,
        "hoc_tap": 830_000,
        "du_phong": 510_000,
        "huong_thu": 710_000,
    }
    for thang_truoc in ba_thang_lien_truoc(thang):
        for ma, so_tien in chi_moi_thang.items():
            id_khoan = storage.ghi_chi_tieu(ma, so_tien)
            with db() as conn:
                conn.execute("UPDATE chi_tieu SET thoi_gian = ?, thang = ? WHERE id = ?",
                             (f"{thang_truoc}-05T12:00:00", thang_truoc, id_khoan))

    ket_qua = tinh_de_xuat_phan_bo(thang)
    assert ket_qua["du_lieu_du"] is True
    for d in ket_qua["de_xuat"]:
        assert d["ty_le_phan_tram"] >= 0.0, f"hu {d['ma']} bi am: {d['ty_le_phan_tram']}"
    tong = sum(d["ty_le_phan_tram"] for d in ket_qua["de_xuat"])
    assert tong == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Tự bù hũ âm (spec docs/superpowers/specs/2026-09-23-tu-bu-hu-am-design.md)
# ---------------------------------------------------------------------------


def test_tinh_tu_bu_khong_hu_nao_am_giu_nguyen():
    from app.jars import tinh_tu_bu
    han_muc = {"thiet_yeu": 5_000_000, "huong_thu": 1_000_000}
    kq = tinh_tu_bu(han_muc, {"thiet_yeu": 1_000_000})
    assert kq["han_muc_hieu_luc"] == han_muc
    assert kq["duoc_bu"] == {"thiet_yeu": 0, "huong_thu": 0}
    assert kq["da_nhuong"] == {"thiet_yeu": 0, "huong_thu": 0}
    assert kq["bu_tu"] == {"thiet_yeu": [], "huong_thu": []}
    assert kq["thieu_dac_biet_chua_bu"] == 0
    assert kq["tong_ngan_sach"] == 6_000_000
    assert kq["tong_da_chi"] == 1_000_000
    assert kq["tong_con_lai"] == 5_000_000


def test_tinh_tu_bu_tai_hien_dung_so_that_23_09():
    """Bảng số thật lúc chốt thiết kế -- phải khớp từng đồng."""
    from app.jars import tinh_tu_bu
    han_muc = {"thiet_yeu": 6_359_000, "gia_dinh": 1_602_468, "hoc_tap": 1_271_800,
               "du_phong": 1_271_800, "huong_thu": 1_004_722, "tu_do_tai_chinh": 1_208_210}
    kq = tinh_tu_bu(han_muc, {"thiet_yeu": 11_343_000})
    assert kq["duoc_bu"]["thiet_yeu"] == 4_984_000
    assert kq["bu_tu"]["thiet_yeu"] == [("huong_thu", 1_004_722), ("du_phong", 1_271_800),
                                        ("hoc_tap", 1_271_800), ("gia_dinh", 1_435_678)]
    hl = kq["han_muc_hieu_luc"]
    assert hl["thiet_yeu"] == 11_343_000
    assert hl["huong_thu"] == 0
    assert hl["du_phong"] == 0
    assert hl["hoc_tap"] == 0
    assert hl["gia_dinh"] == 166_790
    assert hl["tu_do_tai_chinh"] == 1_208_210
    assert kq["tong_con_lai"] == 1_375_000


def test_tinh_tu_bu_rut_can_hu_truoc_moi_toi_hu_sau():
    from app.jars import tinh_tu_bu
    han_muc = {"thiet_yeu": 1_000_000, "huong_thu": 300_000, "du_phong": 500_000}
    kq = tinh_tu_bu(han_muc, {"thiet_yeu": 1_400_000})
    # thiếu 400k: huong_thu (đứng đầu THU_TU_BU) cạn 300k trước, rồi du_phong 100k
    assert kq["bu_tu"]["thiet_yeu"] == [("huong_thu", 300_000), ("du_phong", 100_000)]
    assert kq["da_nhuong"] == {"thiet_yeu": 0, "huong_thu": 300_000, "du_phong": 100_000}
    assert kq["han_muc_hieu_luc"] == {"thiet_yeu": 1_400_000, "huong_thu": 0, "du_phong": 400_000}


def test_tinh_tu_bu_chi_nhuong_phan_con_du():
    from app.jars import tinh_tu_bu
    han_muc = {"thiet_yeu": 1_000_000, "huong_thu": 300_000, "du_phong": 500_000}
    kq = tinh_tu_bu(han_muc, {"thiet_yeu": 1_200_000, "huong_thu": 250_000})
    # huong_thu chỉ còn dư 50k -> nhường 50k, 150k còn lại lấy từ du_phong
    assert kq["bu_tu"]["thiet_yeu"] == [("huong_thu", 50_000), ("du_phong", 150_000)]
    assert kq["han_muc_hieu_luc"]["huong_thu"] == 250_000  # = đã chi, còn 0
    assert kq["han_muc_hieu_luc"]["du_phong"] == 350_000


def test_tinh_tu_bu_tu_do_tai_chinh_bi_dung_cuoi_cung():
    from app.jars import tinh_tu_bu
    han_muc = {"tu_do_tai_chinh": 1_000_000, "thiet_yeu": 1_000_000,
               "gia_dinh": 1_000_000, "huong_thu": 100_000}
    kq = tinh_tu_bu(han_muc, {"huong_thu": 1_600_000})
    # thiếu 1.5tr: gia_dinh 1tr -> thiet_yeu 500k, chưa tới tu_do_tai_chinh
    assert kq["bu_tu"]["huong_thu"] == [("gia_dinh", 1_000_000), ("thiet_yeu", 500_000)]
    assert kq["da_nhuong"]["tu_do_tai_chinh"] == 0


def test_tinh_tu_bu_nhieu_hu_am_bu_theo_thu_tu_cau_hinh():
    from app.jars import tinh_tu_bu
    han_muc = {"thiet_yeu": 1_000_000, "hoc_tap": 200_000, "huong_thu": 500_000}
    kq = tinh_tu_bu(han_muc, {"thiet_yeu": 1_300_000, "hoc_tap": 400_000})
    # thiet_yeu đứng trước trong cấu hình -> được bù trước (300k), hoc_tap sau (200k)
    assert kq["bu_tu"]["thiet_yeu"] == [("huong_thu", 300_000)]
    assert kq["bu_tu"]["hoc_tap"] == [("huong_thu", 200_000)]
    assert kq["han_muc_hieu_luc"] == {"thiet_yeu": 1_300_000, "hoc_tap": 400_000, "huong_thu": 0}
    assert kq["tong_con_lai"] == 0


def test_tinh_tu_bu_khong_du_bu_hu_am_con_am_dung_phan_thieu():
    from app.jars import tinh_tu_bu
    kq = tinh_tu_bu({"thiet_yeu": 1_000_000, "huong_thu": 200_000}, {"thiet_yeu": 1_500_000})
    assert kq["duoc_bu"]["thiet_yeu"] == 200_000
    assert kq["han_muc_hieu_luc"]["thiet_yeu"] == 1_200_000  # còn âm 300k
    assert kq["tong_con_lai"] == -300_000


def test_tinh_tu_bu_thieu_dac_biet_duoc_bu_truoc():
    from app.jars import tinh_tu_bu
    han_muc = {"thiet_yeu": 1_000_000, "hoc_tap": 300_000, "huong_thu": 0}
    kq = tinh_tu_bu(han_muc, {"huong_thu": 200_000}, thieu_dac_biet=250_000)
    # 250k thiếu của chi phí đặc biệt rút TRƯỚC: hoc_tap 250k. Rồi huong_thu âm
    # 200k: hoc_tap còn 50k + thiet_yeu 150k.
    assert kq["bu_tu"]["huong_thu"] == [("hoc_tap", 50_000), ("thiet_yeu", 150_000)]
    assert kq["da_nhuong"] == {"thiet_yeu": 150_000, "hoc_tap": 300_000, "huong_thu": 0}
    assert kq["thieu_dac_biet_chua_bu"] == 0
    assert kq["tong_ngan_sach"] == 1_050_000  # 1.3tr - 250k
    assert kq["tong_con_lai"] == 850_000


def test_tinh_tu_bu_thieu_dac_biet_khong_du_bu():
    from app.jars import tinh_tu_bu
    kq = tinh_tu_bu({"thiet_yeu": 100_000}, {}, thieu_dac_biet=300_000)
    assert kq["thieu_dac_biet_chua_bu"] == 200_000
    assert kq["tong_con_lai"] == -200_000


def test_tinh_tu_bu_ma_ngoai_thu_tu_xep_cuoi():
    from app.jars import tinh_tu_bu
    han_muc = {"hu_moi": 1_000_000, "tu_do_tai_chinh": 1_000_000, "thiet_yeu": 100_000}
    kq = tinh_tu_bu(han_muc, {"thiet_yeu": 1_600_000})
    # thiếu 1.5tr: tu_do_tai_chinh (cuối THU_TU_BU) 1tr trước, rồi mới tới hu_moi 500k
    assert kq["bu_tu"]["thiet_yeu"] == [("tu_do_tai_chinh", 1_000_000), ("hu_moi", 500_000)]


def test_tinh_tu_bu_bat_bien_tong():
    """Chưa vượt tổng: không hũ nào còn âm, tổng phần còn lại các hũ =
    tong_con_lai, tổng nhường = tổng được bù + phần thiếu đặc biệt đã bù."""
    from app.jars import tinh_tu_bu
    han_muc = {"thiet_yeu": 3_000_000, "gia_dinh": 800_000, "hoc_tap": 600_000,
               "du_phong": 600_000, "huong_thu": 500_000, "tu_do_tai_chinh": 500_000}
    da_chi = {"thiet_yeu": 3_900_000, "gia_dinh": 850_000, "huong_thu": 100_000}
    kq = tinh_tu_bu(han_muc, da_chi, thieu_dac_biet=100_000)
    con_lai = {ma: kq["han_muc_hieu_luc"][ma] - da_chi.get(ma, 0) for ma in han_muc}
    assert all(v >= 0 for v in con_lai.values())
    assert sum(con_lai.values()) == kq["tong_con_lai"] == 1_050_000
    assert sum(kq["da_nhuong"].values()) == sum(kq["duoc_bu"].values()) + 100_000


def test_ngay_bat_dau_ky_sau_va_so_ngay_con_lai():
    from datetime import date
    from app.jars import ngay_bat_dau_ky_sau, so_ngay_con_lai_trong_ky
    assert ngay_bat_dau_ky_sau(date(2026, 9, 23), 5) == date(2026, 10, 5)
    assert ngay_bat_dau_ky_sau(date(2026, 9, 3), 5) == date(2026, 9, 5)
    assert so_ngay_con_lai_trong_ky(date(2026, 9, 23), 5) == 12
    assert so_ngay_con_lai_trong_ky(date(2026, 10, 4), 5) == 1
    assert so_ngay_con_lai_trong_ky(date(2026, 10, 5), 5) == 31


def test_ngay_bat_dau_ky_sau_qua_nam():
    from datetime import date
    from app.jars import ngay_bat_dau_ky_sau, so_ngay_con_lai_trong_ky
    assert ngay_bat_dau_ky_sau(date(2026, 12, 31), 1) == date(2027, 1, 1)
    assert so_ngay_con_lai_trong_ky(date(2026, 12, 31), 1) == 1
    assert ngay_bat_dau_ky_sau(date(2026, 12, 20), 5) == date(2027, 1, 5)


def test_tinh_ngan_sach_thang_gop_du_lieu_that_va_tu_bu():
    from app.jars import ghi_cau_hinh, tinh_ngan_sach_thang, thang_hien_tai
    from app import storage
    ghi_cau_hinh({
        "thu_nhap_thuc_linh_thang": 10_000_000,
        "hu": [
            {"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 50.0},
            {"ma": "huong_thu", "ten": "Hưởng Thụ", "ty_le_phan_tram": 10.0},
        ],
        "nguong_canh_bao": [0.65, 0.8, 1.0],
    })
    thang = thang_hien_tai()
    storage.ghi_chi_tieu("huong_thu", 1_300_000, thang=thang)
    kq = tinh_ngan_sach_thang(thang)
    assert [h["ma"] for h in kq["hu"]] == ["thiet_yeu", "huong_thu"]
    thiet_yeu, huong_thu = kq["hu"]
    assert huong_thu["han_muc_truoc_bu"] == 1_000_000
    assert huong_thu["duoc_bu"] == 300_000
    assert huong_thu["bu_tu"] == [{"ma": "thiet_yeu", "ten": "Thiết Yếu", "so_tien": 300_000}]
    assert huong_thu["han_muc_hieu_luc"] == 1_300_000
    assert huong_thu["con_lai"] == 0
    assert thiet_yeu["da_nhuong"] == 300_000
    assert thiet_yeu["con_lai"] == 4_700_000
    assert kq["thu_nhap_hieu_qua"] == 10_000_000
    assert kq["tong_ngan_sach"] == 6_000_000
    assert kq["tong_da_chi"] == 1_300_000
    assert kq["tong_con_lai"] == 4_700_000
    assert kq["ty_le_tong_da_dung"] == pytest.approx(1_300_000 / 6_000_000)


def test_tinh_ngan_sach_thang_ty_le_tong_khi_ngan_sach_bang_0():
    from app.jars import ghi_cau_hinh, tinh_ngan_sach_thang, thang_hien_tai
    ghi_cau_hinh({"thu_nhap_thuc_linh_thang": 0,
                  "hu": [{"ma": "thiet_yeu", "ten": "Thiết Yếu", "ty_le_phan_tram": 100.0}],
                  "nguong_canh_bao": [0.65, 0.8, 1.0]})
    kq = tinh_ngan_sach_thang(thang_hien_tai())
    assert kq["tong_ngan_sach"] == 0
    assert kq["ty_le_tong_da_dung"] == 0.0


def test_doc_cau_hinh_tu_tao_tu_mau_khi_chua_co_file(tmp_path, monkeypatch):
    """Máy cài mới (thư mục data/ còn trống): đọc cấu hình lần đầu phải tự
    chép mẫu 6 hũ sang, không văng FileNotFoundError."""
    import json
    import app.jars as jars
    dich = tmp_path / "data_moi" / "jars_config.json"
    monkeypatch.setattr(jars, "JARS_CONFIG_PATH", dich)
    mau = json.loads(jars.JARS_CONFIG_MAU_PATH.read_text(encoding="utf-8"))

    assert jars.doc_cau_hinh() == mau
    assert json.loads(dich.read_text(encoding="utf-8")) == mau


def test_doc_cau_hinh_khong_ghi_de_file_da_co(tmp_path, monkeypatch):
    import app.jars as jars
    dich = tmp_path / "jars_config.json"
    noi_dung = '{"thu_nhap_thuc_linh_thang": 1, "hu": []}'
    dich.write_text(noi_dung, encoding="utf-8")
    monkeypatch.setattr(jars, "JARS_CONFIG_PATH", dich)

    assert jars.doc_cau_hinh() == {"thu_nhap_thuc_linh_thang": 1, "hu": []}
    assert dich.read_text(encoding="utf-8") == noi_dung


def test_file_mau_la_6_hu_chuan_khop_ma_hu_trong_code():
    """Mẫu dùng đúng 6 mã hũ mà code phụ thuộc (THU_TU_BU, màu /ui, docstring
    tool), tổng tỷ lệ 100%, số liệu chung chung -- không phải của ai."""
    import json
    import app.jars as jars
    mau = json.loads(jars.JARS_CONFIG_MAU_PATH.read_text(encoding="utf-8"))
    assert [h["ma"] for h in mau["hu"]] == [
        "thiet_yeu", "gia_dinh", "hoc_tap", "du_phong", "huong_thu", "tu_do_tai_chinh"]
    assert set(jars.THU_TU_BU) == {h["ma"] for h in mau["hu"]}
    assert sum(h["ty_le_phan_tram"] for h in mau["hu"]) == 100
    assert mau["thu_nhap_thuc_linh_thang"] == 10_000_000
    assert mau["nguong_canh_bao"] == [0.65, 0.8, 1.0]
    assert mau["ngay_bat_dau_chu_ky"] == 1


def test_tao_tu_mau_song_song_chi_ghi_mot_lan(tmp_path, monkeypatch):
    """/ui mở lần đầu gọi nhiều API song song: các luồng cùng thấy "chưa có
    file" -- chỉ được tạo 1 lần, không luồng nào lỗi hay đọc phải file dở."""
    import threading
    import time
    import app.jars as jars
    dich = tmp_path / "jars_config.json"
    monkeypatch.setattr(jars, "JARS_CONFIG_PATH", dich)
    so_lan_ghi = []
    ghi_that = jars.ghi_cau_hinh

    def _ghi_cham(cfg):
        so_lan_ghi.append(1)
        time.sleep(0.05)  # nới cửa sổ tranh chấp để lỗi (nếu có) lộ ra chắc chắn
        ghi_that(cfg)

    monkeypatch.setattr(jars, "ghi_cau_hinh", _ghi_cham)
    rao = threading.Barrier(8)
    ket_qua, loi = [], []

    def _doc():
        rao.wait()
        try:
            ket_qua.append(jars.doc_cau_hinh())
        except Exception as exc:  # noqa: BLE001
            loi.append(exc)

    luong = [threading.Thread(target=_doc) for _ in range(8)]
    for t in luong:
        t.start()
    for t in luong:
        t.join()

    assert loi == []
    assert len(so_lan_ghi) == 1
    assert len(ket_qua) == 8 and all(k == ket_qua[0] for k in ket_qua)


def test_dam_bao_co_cau_hinh_khong_doc_file_da_co(tmp_path, monkeypatch):
    """Lúc khởi động (app/main.py) chỉ cần BẢO ĐẢM có file, không parse: file
    sửa tay hỏng cú pháp JSON không được làm container chết ngay lúc lên và
    restart lặp -- lỗi để lộ ở request cần cấu hình, như trước khi có mẫu."""
    import app.jars as jars
    dich = tmp_path / "jars_config.json"
    dich.write_text("{khong phai json", encoding="utf-8")
    monkeypatch.setattr(jars, "JARS_CONFIG_PATH", dich)

    jars.dam_bao_co_cau_hinh()

    assert dich.read_text(encoding="utf-8") == "{khong phai json"


def test_dam_bao_co_cau_hinh_tao_tu_mau_khi_chua_co(tmp_path, monkeypatch):
    import json
    import app.jars as jars
    dich = tmp_path / "moi" / "jars_config.json"
    monkeypatch.setattr(jars, "JARS_CONFIG_PATH", dich)

    jars.dam_bao_co_cau_hinh()

    assert json.loads(dich.read_text(encoding="utf-8")) == \
        json.loads(jars.JARS_CONFIG_MAU_PATH.read_text(encoding="utf-8"))
