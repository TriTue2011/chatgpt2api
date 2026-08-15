"""Bản chờ chọn cho việc dịch — menu và giải số.

Chủ máy chốt 14/08: bot KHÔNG được tự đoán. Phụ đề phải cho chọn ngôn ngữ đích
và kiểu kết quả (.srt hay bản chữ); `/dich` không nêu đích cũng phải hỏi.
"""
from __future__ import annotations

import pytest

from services import dich_cho as dc


@pytest.fixture(autouse=True)
def _sach():
    dc._pending.clear()
    yield
    dc._pending.clear()


# ── Sổ chờ ──────────────────────────────────────────────────────────────────


def test_so_cho_theo_khoa(tmp_path):
    tep = tmp_path / "phim.mp4"
    tep.write_bytes(b"x")
    dc.set_pending("k1", path=str(tep), ten="phim.mp4", so_byte=1)
    assert dc.has_pending("k1") and not dc.has_pending("k2")
    assert (dc.get_pending("k1") or {})["ten"] == "phim.mp4"
    assert (dc.pop_pending("k1") or {})["path"] == str(tep)
    assert not dc.has_pending("k1")


def test_set_pending_moi_xoa_tep_cu(tmp_path):
    cu = tmp_path / "cu.mp4"
    cu.write_bytes(b"x")
    dc.set_pending("k", path=str(cu), ten="cu.mp4")
    dc.set_pending("k", url="https://youtu.be/abc", ten="link")
    assert not cu.exists()          # tệp cũ bị dọn, không rác lại đĩa


def test_het_han_thi_don(tmp_path, monkeypatch):
    tep = tmp_path / "a.mp4"
    tep.write_bytes(b"x")
    dc.set_pending("k", path=str(tep))
    dc._pending["k"]["ts"] -= dc._TTL + 1
    assert dc.has_pending("k") is False
    assert not tep.exists()


# ── Menu ────────────────────────────────────────────────────────────────────


def test_menu_video_co_du_5_lua_chon():
    m = dc.menu({"ten": "phim.mp4", "path": "/tmp/x", "so_byte": 133 * 1024 * 1024})
    assert "133 MB" in m
    for so in ("1.", "2.", "3.", "4.", "5."):
        assert so in m
    assert ".srt" in m and "Bản chữ" in m and "GIỮ nguyên" in m


def test_menu_phu_de_va_link_noi_dung_khac_nhau():
    assert "Tệp phụ đề" in dc.menu({"ten": "phim.srt", "path": "/tmp/x"})
    assert "Link video" in dc.menu({"ten": "youtu.be/x", "url": "https://youtu.be/x"})


def test_menu_chu_chi_hoi_tieng_dich():
    m = dc.menu({"chu": "xin chào cả nhà", "ten": "đoạn chữ"})
    assert "xin chào cả nhà" in m
    assert "Tiếng Việt" in m and "Tiếng Hàn" in m
    assert ".srt" not in m            # chữ thì không có chuyện phụ đề


def test_menu_chu_cat_doan_xem_truoc():
    m = dc.menu({"chu": "x" * 200})
    assert "…" in m and len(m) < 500


# ── Giải số ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text, kieu, target", [
    ("1", "phu-de", "vi"),
    ("2", "chu", "vi"),
    ("3", "phu-de", "giu-goc"),
    ("4 anh", "phu-de", "en"),
    ("4 nhật", "phu-de", "ja"),
    ("5 trung", "chu", "zh"),
    ("5 hàn", "chu", "ko"),
    ("4 japanese", "phu-de", "ja"),
])
def test_giai_chon_video(text, kieu, target):
    assert dc.giai_chon(text) == {"kieu": kieu, "target": target}


def test_giai_chon_4_thieu_tieng_thi_bao():
    ra = dc.giai_chon("4")
    assert ra and ra.get("thieu_tieng") is True


@pytest.mark.parametrize("text, ma", [
    ("1", "vi"), ("2", "en"), ("3", "ja"), ("4", "zh"), ("5", "ko"),
])
def test_giai_chon_chu(text, ma):
    assert dc.giai_chon(text, cho_chu=True) == {"kieu": "chu", "target": ma}


@pytest.mark.parametrize("text", ["thôi", "bỏ", "huỷ", "cancel"])
def test_xin_bo(text):
    assert dc.giai_chon(text) == {"bo": True}


@pytest.mark.parametrize("text", [
    "", "gửi file cho nhóm A", "6", "0", "mai là thứ mấy",
    "dịch giúp em sang tiếng nhật",     # không bắt đầu bằng số → không phải menu
])
def test_khong_phai_tra_loi_menu(text):
    assert dc.giai_chon(text) is None


# ── target cho máy dịch ─────────────────────────────────────────────────────


def test_target_cho_may():
    # Dạng CẶP cũ (tab Dịch bản cũ còn gửi): để máy tự chọn chiều.
    assert dc.target_cho_may({"target": "cap:vi"}) == ""
    # Mã TRƠ: đúng tiếng đó, không suy diễn gì thêm — đây là dạng menu ba bước
    # dùng, vì nó đã hỏi rõ cả nguồn lẫn đích.
    assert dc.target_cho_may({"target": "vi"}) == "vi"
    assert dc.target_cho_may({"target": "ja"}) == "ja"
    # giữ nguyên tiếng gốc: biết nguồn thì dịch-sang-chính-nó = chép lời
    assert dc.target_cho_may({"target": "giu-goc"}, "en") == "en"
    assert dc.target_cho_may({"target": "giu-goc"}) == "giu-goc"
