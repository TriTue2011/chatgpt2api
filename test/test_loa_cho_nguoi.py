"""Thông báo loa: nhà vắng thì GIỮ, có người mới phát (chủ máy 03/10/2026). Không gọi mạng / loa thật.

Đo 14 ngày tới 03/10 (7h–22h): `nha_co_nguoi` báo vắng chỉ chiều ngày thường ~13–16h.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.voice import announce as ann  # noqa: E402

LOA = {"id": "loa1", "name": "Loa phòng khách"}


@pytest.fixture
def nha(tmp_path, monkeypatch):
    monkeypatch.setattr(ann, "_duong_cho", lambda: tmp_path / "cho.json")
    monkeypatch.setattr(ann, "_resolve_one", lambda q: LOA)
    phat: list[str] = []
    from services import voice
    monkeypatch.setattr(voice, "play_text_on", lambda text, rec, v="", files_out=None: phat.append(text) or "u")
    monkeypatch.setattr(ann, "_tra_am_luong_sau_khi_phat", lambda *a, **k: None)
    co = {"nguoi": False}
    monkeypatch.setattr(ann, "co_nguoi_nghe", lambda luc=None: co["nguoi"])
    return phat, co


def test_nha_vang_thi_giu_khong_phat(nha):
    phat, _ = nha
    job = ann.schedule("loa1", "Bố về muộn, hai mẹ con ăn cơm trước", delay_seconds=0)
    assert job["status"] == "cho_nguoi" and phat == []
    assert [x["text"] for x in ann.dang_cho()] == ["Bố về muộn, hai mẹ con ăn cơm trước"]


def test_co_nguoi_ve_thi_phat_tin_cho_mot_lan(nha):
    phat, co = nha
    ann.schedule("loa1", "tin 1", delay_seconds=0)
    assert ann.phat_cho() == 0, "vẫn vắng thì vẫn giữ"
    co["nguoi"] = True
    assert ann.phat_cho() == 1 and phat == ["tin 1"]
    assert ann.dang_cho() == [] and ann.phat_cho() == 0, "đã phát thì không phát lại"


def test_co_nguoi_thi_phat_ngay(nha):
    phat, co = nha
    co["nguoi"] = True
    assert ann.schedule("loa1", "phát luôn", delay_seconds=0)["status"] == "done" and phat == ["phát luôn"]


def test_tin_cho_qua_24_gio_thi_bo(nha):
    phat, co = nha
    ann.schedule("loa1", "tin cũ", delay_seconds=0)
    co["nguoi"] = True
    import time
    assert ann.phat_cho(now=time.time() + ann.GIU_TOI_DA + 60) == 0 and phat == [] and ann.dang_cho() == []


def test_khong_xet_duoc_thi_phat_luon(monkeypatch):
    """Không đọc được bằng chứng có người: thà phát thừa còn hơn nuốt tin."""
    from services import kich_hoat_nha
    monkeypatch.setattr(kich_hoat_nha, "nha_co_nguoi", lambda *a, **k: (_ for _ in ()).throw(OSError("db")))
    assert ann.co_nguoi_nghe() is True


def test_nhac_viec_ra_loa_luc_vang_cung_giu(nha, monkeypatch):
    phat, _ = nha
    from services.agent import reminders
    from services.voice import speakers as vspk
    monkeypatch.setattr(vspk, "get", lambda sid: LOA)
    ok, ten = reminders._phat_ra_loa({"speaker_id": "loa1", "voice": "v"}, "Uống thuốc")
    assert ok and "nhà đang vắng" in ten and phat == []
    assert ann.dang_cho()[-1]["text"] == "Uống thuốc"
