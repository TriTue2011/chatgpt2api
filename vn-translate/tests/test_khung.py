"""Mổ văn bản thành mảnh trước khi vào model, và ghép lại sau khi dịch.

Không cần model: `_khung`/`_ghep` là ghép chữ thuần tuý. Hai thứ hỏng ở đây
đều đã xảy ra thật, nên test đứng riêng để chúng không quay lại:

- Dòng trống lọt vào NLLB → model BỊA ra câu ("Tương tự:" mọc đầy bản dịch
  khối YAML, đo thật 13/08).
- Thụt lề bị tokenizer nuốt → YAML/mã dịch xong sai cấu trúc.
"""
from __future__ import annotations

import pytest

from app.engine import _ghep, _khung, co_chu


def _dich_gia(can: list[str]) -> list[str]:
    """Model giả: thêm tiền tố, và BỎ khoảng trắng biên đúng như NLLB thật."""
    return [f"vi:{m}".strip() for m in can]


def _di_het(texts: list[str]) -> list[str]:
    khung, can = _khung(texts)
    return _ghep(khung, _dich_gia(can))


@pytest.mark.parametrize("s, cho_doi", [
    ("", False), ("   ", False), ("\t", False), ("---", False), ("  - ", False),
    ("{{ x }}", True), ("abc", True), ("Xin chào", True), ("日本語", True),
])
def test_co_chu(s, cho_doi):
    assert co_chu(s) is cho_doi


def test_dong_trong_khong_bao_gio_vao_model():
    _, can = _khung(["Alpha\n\n\nBeta\n   \nGamma"])
    assert can == ["Alpha", "Beta", "Gamma"]
    assert all(x.strip() for x in can)


def test_ghep_giu_nguyen_so_dong_va_dong_trong():
    goc = "Alpha\n\n\nBeta\n   \nGamma"
    ra = _di_het([goc])[0]
    assert ra.split("\n") == ["vi:Alpha", "", "", "vi:Beta", "   ", "vi:Gamma"]


def test_thut_le_yaml_duoc_giu():
    goc = "data:\n  task_name: Generate content\n    - Tone: spooky"
    ra = _di_het([goc])[0]
    assert ra == "vi:data:\n  vi:task_name: Generate content\n    vi:- Tone: spooky"


def test_dong_chi_co_dau_di_thang_qua():
    goc = "Alpha\n---\n...\nBeta"
    khung, can = _khung([goc])
    assert can == ["Alpha", "Beta"]
    assert _ghep(khung, _dich_gia(can))[0] == "vi:Alpha\n---\n...\nvi:Beta"


def test_lo_nhieu_van_ban_giu_dung_vi_tri():
    ra = _di_het(["Alpha", "", "  ", "Beta\n\nGamma"])
    assert ra == ["vi:Alpha", "", "  ", "vi:Beta\n\nvi:Gamma"]


def test_cau_dai_cat_nhieu_manh_ghep_lai_mot_dong():
    """Dòng >400 ký tự bị cắt theo câu — ghép lại phải vẫn là MỘT dòng."""
    goc = " ".join(f"Sentence number {i} is here." for i in range(40))
    khung, can = _khung([goc])
    assert len(can) > 1
    ra = _ghep(khung, _dich_gia(can))[0]
    assert "\n" not in ra
    assert ra.startswith("vi:Sentence number 0")


def test_khong_co_gi_de_dich_thi_can_rong():
    khung, can = _khung(["", "\n\n", "   ", "---"])
    assert can == []
    assert _ghep(khung, []) == ["", "\n\n", "   ", "---"]
