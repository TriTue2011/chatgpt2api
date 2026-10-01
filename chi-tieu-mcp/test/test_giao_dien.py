"""Test app/giao_dien.py -- theme sáng/tối cho /ui (spec
2026-09-23-giao-dien-sang-toi-design.md, mục "Token")."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import giao_dien

MA_HU = {"thiet_yeu", "gia_dinh", "hoc_tap", "du_phong", "huong_thu", "tu_do_tai_chinh"}

# Các cặp (chữ, nền) thật sự xuất hiện trên /ui và trang đăng nhập -- WCAG AA
# cho chữ thường cần >= 4.5:1. Cặp chu-nut-tat/vien (nút bị khoá) được WCAG
# miễn nên không nằm ở đây.
CAP_CHU_NEN = [
    ("chu", "nen"), ("chu", "the"), ("chu-phu", "nen"), ("chu-phu", "the"),
    ("nhan", "nen"), ("nhan", "the"), ("chu-tren-nut", "nut"),
    ("nguy", "nen"), ("nguy", "the"), ("tot", "nen"), ("tot", "the"),
    ("canh-bao", "nen"), ("canh-bao", "the"), ("chu-tren-nguy", "nen-nguy"),
    ("chu", "nen-nguy"), ("chu-phu", "nen-nguy"), ("chu", "nen-canh-bao"),
    ("chu-phu", "nen-canh-bao"),
    # /ui mới (spec 2026-09-23-thiet-ke-lai-ui-design.md, mục "Token mới"):
    # chữ trắng trên cả 3 điểm gradient đầu trang (chip đang chọn ở đầu trang
    # = chữ dau-1 trên nền chu-tren-dau, cùng cặp), phân đoạn, toast, nền
    # xanh/cam của tab Công ty, nền tím nhạt của tóm tắt AI + chip nhanh, nút đỏ.
    ("chu-tren-dau", "dau-1"), ("chu-tren-dau", "dau-2"), ("chu-tren-dau", "dau-3"),
    ("chu-chon", "nen-chon"), ("chu-phu", "nen-phan-doan"), ("chu", "nen-phan-doan"),
    ("chu-toast", "nen-toast"), ("tot", "nen-tot"), ("cam", "nen-cam"), ("cam", "the"),
    ("chu", "nen-nhan"), ("nhan", "nen-nhan"), ("chu-tren-nut", "nut-nguy"),
]


def _do_sang(hex_mau: str) -> float:
    r, g, b = (int(hex_mau.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def _kenh(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _kenh(r) + 0.7152 * _kenh(g) + 0.0722 * _kenh(b)


def _tuong_phan(a: str, b: str) -> float:
    sang, toi = sorted((_do_sang(a), _do_sang(b)), reverse=True)
    return (sang + 0.05) / (toi + 0.05)


def test_ham_tuong_phan_dung_chuan_wcag():
    assert _tuong_phan("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert _tuong_phan("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)


def test_hai_che_do_co_cung_bo_khoa():
    assert giao_dien.MAU["sang"].keys() == giao_dien.MAU["toi"].keys()
    assert set(giao_dien.MAU_HU["sang"]) == set(giao_dien.MAU_HU["toi"]) == MA_HU
    assert set(giao_dien.MAU_NEN_HU["sang"]) == set(giao_dien.MAU_NEN_HU["toi"]) == MA_HU
    assert giao_dien.HIEU_UNG["sang"].keys() == giao_dien.HIEU_UNG["toi"].keys()


@pytest.mark.parametrize("che_do", ["sang", "toi"])
@pytest.mark.parametrize("chu,nen", CAP_CHU_NEN)
def test_cap_chu_nen_dat_wcag_4_5(che_do, chu, nen):
    mau = giao_dien.MAU[che_do]
    assert _tuong_phan(mau[chu], mau[nen]) >= 4.5


@pytest.mark.parametrize("che_do", ["sang", "toi"])
def test_mau_hu_dat_3_tren_nen_the(che_do):
    nen_the = giao_dien.MAU[che_do]["the"]
    for ma, mau in giao_dien.MAU_HU[che_do].items():
        assert _tuong_phan(mau, nen_the) >= 3.0, ma


@pytest.mark.parametrize("che_do", ["sang", "toi"])
def test_icon_hu_dat_3_tren_nen_nhat_cua_hu(che_do):
    """Icon hũ (màu hũ) nằm trên nền nhạt riêng của hũ ở danh sách hũ, ô chọn
    hũ, dòng lịch sử -- đồ hoạ nên cần >= 3:1."""
    for ma, mau in giao_dien.MAU_HU[che_do].items():
        assert _tuong_phan(mau, giao_dien.MAU_NEN_HU[che_do][ma]) >= 3.0, ma


def test_mau_do_chi_danh_cho_trang_thai_vuot():
    """Bảng màu hũ theo bản mẫu: không hũ nào dùng tông đỏ của nguy/nut-nguy
    (đỏ = chi vượt), khác bảng cũ (Dự Phòng đỏ)."""
    for che_do in ("sang", "toi"):
        do = {giao_dien.MAU[che_do]["nguy"].upper(), giao_dien.MAU[che_do]["nut-nguy"].upper()}
        assert not do & {m.upper() for m in giao_dien.MAU_HU[che_do].values()}


def _khoi(css: str, mo_dau: str) -> str:
    return css.split(mo_dau, 1)[1].split("}", 1)[0]


def test_css_theme_du_4_khoi_dung_gia_tri():
    css = giao_dien.css_theme()
    khoi_sang = _khoi(css, ":root {\n  color-scheme: light;")
    khoi_toi_he_dieu_hanh = _khoi(css, '@media (prefers-color-scheme: dark) {\n:root:not([data-theme="light"]) {')
    khoi_toi_ep = _khoi(css, ':root[data-theme="dark"] {\n  color-scheme: dark;')
    khoi_rong = _khoi(css, "@media (min-width: 40em) {\n:root {")
    for ten, gia_tri in giao_dien.MAU["sang"].items():
        assert f"--mau-{ten}: {gia_tri};" in khoi_sang
    for ma, gia_tri in giao_dien.MAU_HU["sang"].items():
        assert f"--hu-{ma}: {gia_tri};" in khoi_sang
    for ma, gia_tri in giao_dien.MAU_NEN_HU["sang"].items():
        assert f"--nen-hu-{ma}: {gia_tri};" in khoi_sang
    for ten, gia_tri in giao_dien.HIEU_UNG["sang"].items():
        assert f"--{ten}: {gia_tri};" in khoi_sang
    for ten, gia_tri in giao_dien.CO_CHU["mac_dinh"].items():
        assert f"--co-chu-{ten}: {gia_tri};" in khoi_sang
    assert "color-scheme: dark;" in khoi_toi_he_dieu_hanh
    for khoi in (khoi_toi_he_dieu_hanh, khoi_toi_ep):
        for ten, gia_tri in giao_dien.MAU["toi"].items():
            assert f"--mau-{ten}: {gia_tri};" in khoi
        for ma, gia_tri in giao_dien.MAU_HU["toi"].items():
            assert f"--hu-{ma}: {gia_tri};" in khoi
        for ma, gia_tri in giao_dien.MAU_NEN_HU["toi"].items():
            assert f"--nen-hu-{ma}: {gia_tri};" in khoi
        for ten, gia_tri in giao_dien.HIEU_UNG["toi"].items():
            assert f"--{ten}: {gia_tri};" in khoi
    for ten, gia_tri in giao_dien.CO_CHU["rong"].items():
        assert f"--co-chu-{ten}: {gia_tri};" in khoi_rong


def test_o_nhap_giu_16px_chong_ios_phong_to():
    assert giao_dien.CO_CHU["mac_dinh"]["nhap"] == "16px"
    assert "nhap" not in giao_dien.CO_CHU["rong"]


def test_the_head_script_doc_khoa_luu_dung_truoc_style():
    the_head = giao_dien.THE_HEAD
    assert giao_dien.KHOA_LUU_CHE_DO == "chitieu-che-do-mau"
    assert the_head.startswith("<script>")
    assert f"localStorage.getItem('{giao_dien.KHOA_LUU_CHE_DO}')" in the_head
    assert the_head.index(giao_dien.KHOA_LUU_CHE_DO) < the_head.index("<style>")
    assert "try{" in the_head and "catch(e){}" in the_head
    assert giao_dien.css_theme() in the_head
