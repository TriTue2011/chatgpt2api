"""Mổ văn bản thành mảnh trước khi vào model, và ghép lại sau khi dịch.

Không cần model: `_khung`/`_ghep` là ghép chữ thuần tuý. Hai thứ hỏng ở đây
đều đã xảy ra thật, nên test đứng riêng để chúng không quay lại:

- Dòng trống lọt vào NLLB → model BỊA ra câu ("Tương tự:" mọc đầy bản dịch
  khối YAML, đo thật 13/08).
- Thụt lề bị tokenizer nuốt → YAML/mã dịch xong sai cấu trúc.
"""
from __future__ import annotations

import pytest

from app.engine import _ghep, _khung, co_chu, la_ten_rieng


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


def test_nhieu_cau_tach_tung_cau_truoc_khi_vao_model():
    """Model học trên CẶP CÂU — đưa 3 câu một lượt là nó nuốt câu (đo thật
    13/08: câu cuối biến mất). Mỗi câu phải là một mảnh riêng."""
    goc = "Now, I grab my knife. My knife broke today. I know it sounds stupid."
    khung, can = _khung([goc])
    assert can == ["Now, I grab my knife.", "My knife broke today.",
                   "I know it sounds stupid."]
    assert _ghep(khung, _dich_gia(can))[0] == (
        "vi:Now, I grab my knife. vi:My knife broke today. "
        "vi:I know it sounds stupid.")


def test_cau_don_qua_dai_cat_o_dau_phay():
    goc = ("The first clause goes here and keeps going with many words, "
           * 12).strip().rstrip(",") + "."
    _, can = _khung([goc])
    assert len(can) > 1
    assert all(len(m) <= 400 for m in can)
    assert " ".join(can).replace("  ", " ").startswith("The first clause")


def test_cau_dai_cat_nhieu_manh_ghep_lai_mot_dong():
    """Dòng >400 ký tự bị cắt theo câu — ghép lại phải vẫn là MỘT dòng."""
    goc = " ".join(f"Sentence number {i} is here." for i in range(40))
    khung, can = _khung([goc])
    assert len(can) > 1
    ra = _ghep(khung, _dich_gia(can))[0]
    assert "\n" not in ra
    assert ra.startswith("vi:Sentence number 0")


@pytest.mark.parametrize("s", [
    "Vu Minh Tuan", "Nguyễn Huy Văn", "John Smith", "Trần Thị Bích Ngọc",
])
def test_ten_rieng_duoc_nhan_ra(s):
    assert la_ten_rieng(s) is True


@pytest.mark.parametrize("s", [
    "Được",                                     # nhắn một từ — phải dịch
    "Xong học sinh khen AI giảng bài dễ hiểu",  # có từ viết thường
    "không cần đứng lớp nữa",
    "Formatting Constraints (For TTS Safety):",  # có dấu câu → tiêu đề, phải dịch
    "Input data:",
    "Chào Anh Đi Đâu Đấy Hôm Nay",   # viết hoa từng chữ nhưng quá nhiều từ
    "", "   ", "10:51",
])
def test_khong_nham_la_ten_rieng(s):
    assert la_ten_rieng(s) is False


def test_ten_nguoi_trong_anh_chat_khong_vao_model():
    """Ảnh chụp chat: tên người gửi phải ra nguyên văn, KHÔNG bị bịa thành câu."""
    goc = "Vu Minh Tuan\nXong học sinh khen AI giảng bài dễ hiểu\n10:51"
    khung, can = _khung([goc])
    assert can == ["Xong học sinh khen AI giảng bài dễ hiểu"]
    assert _ghep(khung, _dich_gia(can))[0] == (
        "Vu Minh Tuan\nvi:Xong học sinh khen AI giảng bài dễ hiểu\n10:51")


def test_khong_co_gi_de_dich_thi_can_rong():
    khung, can = _khung(["", "\n\n", "   ", "---"])
    assert can == []
    assert _ghep(khung, []) == ["", "\n\n", "   ", "---"]
