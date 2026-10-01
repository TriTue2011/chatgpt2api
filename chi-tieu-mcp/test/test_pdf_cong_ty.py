"""Test app/pdf_cong_ty.py -- sinh file PDF thật ra tmp_path, không đụng
data/tam_ung_pdf/ thật. Không cần DB (module này chỉ nhận dữ liệu đã tính
sẵn, không tự query)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_duong_dan_pdf_dung_dinh_dang():
    from app.pdf_cong_ty import duong_dan_pdf
    assert duong_dan_pdf(42).name == "giai-chi-42.pdf"


def test_tao_pdf_giai_chi_sinh_file_dung_duong_dan(tmp_path, monkeypatch):
    from app import pdf_cong_ty
    monkeypatch.setattr(pdf_cong_ty, "THU_MUC_PDF", tmp_path)
    giao_dich = [
        {"thoi_gian": "2026-09-01T10:00:00", "loai": "tam_ung", "so_tien": 5_000_000, "mo_ta": "di cong tac"},
        {"thoi_gian": "2026-09-02T08:30:00", "loai": "chi", "so_tien": 300_000, "mo_ta": "taxi san bay"},
    ]
    duong_dan = pdf_cong_ty.tao_pdf_giai_chi(1, giao_dich, 5_000_000, 300_000, 4_700_000)
    assert duong_dan == tmp_path / "giai-chi-1.pdf"
    assert duong_dan.exists()
    assert duong_dan.stat().st_size > 0
    with open(duong_dan, "rb") as f:
        assert f.read(4) == b"%PDF"  # magic bytes, xac nhan la file PDF that


def test_tao_pdf_giai_chi_danh_sach_rong_van_sinh_duoc_file(tmp_path, monkeypatch):
    """so_du am (cong ty no lai) van phai sinh PDF binh thuong, khong crash."""
    from app import pdf_cong_ty
    monkeypatch.setattr(pdf_cong_ty, "THU_MUC_PDF", tmp_path)
    duong_dan = pdf_cong_ty.tao_pdf_giai_chi(2, [], 0, 500_000, -500_000)
    assert duong_dan.exists()


def test_tao_pdf_giai_chi_mo_ta_dai_khong_loi_van_sinh_pdf_hop_le(tmp_path, monkeypatch):
    """I2: mo_ta dai (vd ~300 ky tu) truoc day tran ra ngoai cot co dinh do
    pdf.cell() khong tu xuong dong -- gio dung pdf.table() tu wrap, phai
    sinh PDF hop le khong loi voi mo_ta rat dai."""
    from app import pdf_cong_ty
    monkeypatch.setattr(pdf_cong_ty, "THU_MUC_PDF", tmp_path)
    mo_ta_dai = "Ăn trưa với đối tác ở Đà Nẵng, " * 10
    giao_dich = [
        {"thoi_gian": "2026-09-01T10:00:00", "loai": "chi", "so_tien": 300_000, "mo_ta": mo_ta_dai},
    ]
    duong_dan = pdf_cong_ty.tao_pdf_giai_chi(3, giao_dich, 0, 300_000, -300_000)
    assert duong_dan.exists()
    with open(duong_dan, "rb") as f:
        assert f.read(4) == b"%PDF"


def test_tao_pdf_giai_chi_mo_ta_tai_gioi_han_500_ky_tu_khong_loi(tmp_path, monkeypatch):
    """Sau khi them gioi han 500 ky tu cho mo_ta (app/tools.py, app/web.py),
    pin lai: noi dung dai dung bang gioi han nay van phai sinh PDF hop le,
    khong crash ValueError cua pdf.table() (xay ra thuc nghiem tu ~1750 ky
    tu cho 1 giao dich -- 500 con nhieu du du an toan)."""
    from app import pdf_cong_ty
    monkeypatch.setattr(pdf_cong_ty, "THU_MUC_PDF", tmp_path)
    mo_ta_500 = ("Ăn trưa với đối tác ở Đà Nẵng, " * 20)[:500]
    giao_dich = [
        {"thoi_gian": "2026-09-01T10:00:00", "loai": "chi", "so_tien": 300_000, "mo_ta": mo_ta_500},
    ]
    duong_dan = pdf_cong_ty.tao_pdf_giai_chi(4, giao_dich, 0, 300_000, -300_000)
    assert duong_dan.exists()
    with open(duong_dan, "rb") as f:
        assert f.read(4) == b"%PDF"
