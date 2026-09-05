"""Theo dõi chủ đề: thêm/liệt kê/xoá, khử trùng không dấu, riêng theo người."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


def _patch_dir(tmp_path, monkeypatch):
    import services.config as cfg
    monkeypatch.setattr(cfg, "DATA_DIR", str(tmp_path), raising=False)


def test_them_liet_ke_gan_nhat(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import tracked_topic as tt
    assert tt.them("u1", "vụ cháy Hải Dương")
    assert tt.them("u1", "giá vàng")
    ds = tt.liet_ke("u1")
    assert [m["chu_de"] for m in ds] == ["giá vàng", "vụ cháy Hải Dương"]
    assert tt.gan_nhat("u1") == "giá vàng"


def test_khu_trung_khong_dau_va_nang_len_dau(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import tracked_topic as tt
    tt.them("u2", "vụ cháy Hải Dương")
    tt.them("u2", "giá vàng")
    tt.them("u2", "Vụ CHÁY Hải Dương")     # trùng (không dấu) → nâng lên đầu
    ds = tt.liet_ke("u2")
    assert len(ds) == 2
    assert ds[0]["chu_de"] == "Vụ CHÁY Hải Dương"


def test_xoa_va_rieng_theo_nguoi(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import tracked_topic as tt
    tt.them("uA", "bão số 3")
    tt.them("uB", "chứng khoán")
    assert tt.xoa("uA", "bão") is True
    assert tt.liet_ke("uA") == []
    assert tt.xoa("uA", "không tồn tại") is False
    assert [m["chu_de"] for m in tt.liet_ke("uB")] == ["chứng khoán"]


def test_handler_add_list_remove(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import capabilities as caps
    ctx = {"user_id": "uH"}
    out = caps._h_theo_doi_chu_de({"op": "add", "chu_de": "vụ cháy Hải Dương"}, ctx)
    assert "cháy Hải Dương" in out["text"]
    out2 = caps._h_theo_doi_chu_de({"op": "list"}, ctx)
    assert "cháy Hải Dương" in out2["text"]
    out3 = caps._h_theo_doi_chu_de({"op": "remove", "chu_de": "cháy"}, ctx)
    assert "bỏ theo dõi" in out3["text"].lower()
    out4 = caps._h_theo_doi_chu_de({"op": "list"}, ctx)
    assert "chưa theo dõi" in out4["text"].lower()
