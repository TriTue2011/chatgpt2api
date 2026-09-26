"""Sổ cách đọc (26/09/2026): chủ máy dạy "TBBH đọc là trung tâm bảo hành" — mọi giọng theo."""
from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from services.voice import cach_doc  # noqa: E402


@pytest.fixture(autouse=True)
def so_rieng(tmp_path, monkeypatch):
    """Mỗi test một sổ trống trong thư mục tạm — không đụng DATA_DIR thật."""
    monkeypatch.setattr(cach_doc, "_PATH", tmp_path / "cach_doc.json")
    monkeypatch.setattr(cach_doc, "_data", {})
    monkeypatch.setattr(cach_doc, "_loaded", False)
    monkeypatch.setattr(cach_doc, "_mau", None)
    xoa_dem = []
    from services.voice import tts_cache
    monkeypatch.setattr(tts_cache, "clear", lambda: xoa_dem.append(1) or (0, 0))
    yield xoa_dem


def test_cau_chu_may_bao_loi(so_rieng):
    cach_doc.day("TV", "ti vi")
    cach_doc.day("LG", "eo gi")
    cach_doc.day("TBBH", "trung tâm bảo hành")
    cach_doc.day("smart", "xờ mát")
    assert cach_doc.ap("smart TV LG được bảo hành ở TBBH") == \
        "xờ mát ti vi eo gi được bảo hành ở trung tâm bảo hành"
    assert so_rieng, "sổ đổi thì phải bỏ audio đã đệm (câu cũ đọc theo cách cũ)"


def test_ranh_gioi_chu_va_kieu_hoa():
    cach_doc.day("TV", "ti vi")
    cach_doc.day("smart", "xờ mát")
    assert cach_doc.ap("Kênh TVB và smartphone") == "Kênh TVB và smartphone"
    assert cach_doc.ap("Smart home, SMART TV") == "xờ mát home, xờ mát ti vi"   # chữ thường: mọi kiểu hoa
    assert cach_doc.ap("xem tv") == "xem tv"                                     # chữ HOA: đúng hoa


@pytest.mark.parametrize("chu, doc", [("", "x"), ("TV", ""), ("x" * 41, "y"), ("...", "chấm"),
                                      ("LG", "LG điện tử")])
def test_tu_choi_chu_hoac_cach_doc_sai(chu, doc):
    with pytest.raises(ValueError):
        cach_doc.day(chu, doc)


def test_luu_ra_tep_va_doc_lai(monkeypatch):
    cach_doc.day("TBBH", "trung tâm bảo hành")
    monkeypatch.setattr(cach_doc, "_data", {})
    monkeypatch.setattr(cach_doc, "_loaded", False)
    monkeypatch.setattr(cach_doc, "_mau", None)
    assert cach_doc.ap("ở TBBH") == "ở trung tâm bảo hành"
    assert cach_doc.xoa("TBBH") and not cach_doc.xoa("TBBH")
    assert cach_doc.ap("ở TBBH") == "ở TBBH" and cach_doc.danh_sach() == []


def test_doc_cong_thuc_ap_so_truoc_tien():
    from services.voice import engines
    cach_doc.day("TV", "ti vi")
    assert "ti vi" in engines._doc_cong_thuc("Mua TV mới", "nghi:ban-mai")
    assert engines._doc_cong_thuc("Mua TV mới", "kokoro:af") == "Mua TV mới"   # giọng tiếng Anh: không đụng


def test_cong_cu_bot_chi_chu_may(monkeypatch):
    from services import voice as _voice
    from services.agent import capabilities as cap
    monkeypatch.setattr(_voice, "tts_ready", lambda: False)
    ra = cap._h_day_cach_doc({"chu": "TBBH", "doc": "trung tâm bảo hành"}, {"is_admin": False})
    assert "chủ máy" in ra["text"] and cach_doc.danh_sach() == []
    ra = cap._h_day_cach_doc({"chu": "TBBH", "doc": "trung tâm bảo hành"}, {"is_admin": True})
    assert "Đã ghi" in ra["text"] and cach_doc.ap("TBBH") == "trung tâm bảo hành"
    assert "TBBH → trung tâm bảo hành" in cap._h_day_cach_doc({"hanh_dong": "xem"}, {"is_admin": True})["text"]
    assert "Đã bỏ" in cap._h_day_cach_doc({"hanh_dong": "xoa", "chu": "TBBH"}, {"is_admin": True})["text"]
    assert cap.group_of("day_cach_doc") == "memory"
