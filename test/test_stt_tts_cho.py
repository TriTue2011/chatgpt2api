"""Hai lệnh /stt và /tts đi CHUNG sổ chờ với /dich.

Vì sao dùng chung: một khoá phiên chỉ được có một menu đang mở. Hai sổ chờ
riêng thì người dùng nhắn "2" mà cả hai bên cùng nhận là hỏng, và bên nào thắng
phụ thuộc thứ tự if trong bot — thứ không ai đọc ra được từ giao diện.
"""

from __future__ import annotations

import pytest

from services import dich_cho as dc


@pytest.fixture(autouse=True)
def _so_sach():
    dc._pending.clear()
    yield
    dc._pending.clear()


def test_stt_la_loi_tat_vao_o_chep_loi_chu_khong_phai_luong_rieng():
    """/stt không hỏi lại "làm gì" — tên lệnh đã nói rồi. Nó nhảy thẳng tới câu
    hỏi tiếng, và việc đã chốt sẵn là chép lời ra bản chữ."""
    loi = dc.mo_stt("k")
    assert "tệp âm thanh" in loi
    assert dc.dang_cho_tep("k")

    m = dc.nap_tep("k", "/tmp/a.mp3", "ghi-am.mp3", 1 << 20)
    assert "nói tiếng gì" in m
    ra = dc.tra_loi_buoc("k", "1")          # tệp nói tiếng Việt
    assert ra == {"kieu": "chu", "target": "giu-goc", "nguon": "vi"}


def test_tts_co_san_chu_thi_hoi_tieng_luon():
    m = dc.mo_tts("k", "xin chào các bạn")
    assert "Đọc bằng tiếng nào" in m
    ra = dc.tra_loi_buoc("k", "3")          # đọc bằng tiếng Nhật
    assert ra == {"tts_tieng": "ja", "chu": "xin chào các bạn"}


def test_tts_khong_co_chu_thi_xin_noi_dung_truoc():
    loi = dc.mo_tts("k")
    assert "đoạn chữ" in loi
    assert dc.dang_cho_chu("k")
    m = dc.nap_chu("k", "hôm nay trời đẹp")
    assert "Đọc bằng tiếng nào" in m


def test_dich_xong_phai_hoi_truoc_khi_doc():
    """Đọc xong mới thấy dịch sai là mất trắng cả lượt tổng hợp giọng, nên bản
    dịch phải được người dùng duyệt trước."""
    dc.mo_tts("k", "hôm nay trời đẹp")
    dc.tra_loi_buoc("k", "2")               # đọc bằng tiếng Anh
    m = dc.dat_ban_dich("k", "the weather is nice today", "en")
    assert "đọc bản nào" in m.lower()

    ra = dc.tra_loi_buoc("k", "1")          # đọc bản dịch
    assert ra == {"tts_doc": "the weather is nice today", "tieng": "en"}


def test_chon_doc_ban_goc_thi_giu_nguyen_tieng():
    dc.mo_tts("k", "hôm nay trời đẹp")
    dc.tra_loi_buoc("k", "2")
    dc.dat_ban_dich("k", "the weather is nice today", "en")
    ra = dc.tra_loi_buoc("k", "2")          # đọc bản gốc
    assert ra == {"tts_doc": "hôm nay trời đẹp", "tieng": ""}


def test_so_ngoai_menu_o_buoc_duyet():
    dc.mo_tts("k", "abc")
    dc.tra_loi_buoc("k", "2")
    dc.dat_ban_dich("k", "abc dịch", "en")
    assert dc.tra_loi_buoc("k", "4") is None
    assert dc.tra_loi_buoc("k", "thôi") == {"bo": True}


def test_hai_lenh_khong_dam_nhau_tren_cung_khoa():
    """Mở /tts khi đang chờ /stt thì bản chờ cũ bị thay hẳn, không còn hai menu
    cùng sống trên một khoá."""
    dc.mo_stt("k")
    dc.mo_tts("k", "abc")
    p = dc.get_pending("k") or {}
    assert p.get("viec_chinh") == "tts" and not p.get("path")
