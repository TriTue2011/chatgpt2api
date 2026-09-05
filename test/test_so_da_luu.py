"""Sổ MỤC LỤC đã lưu: ghi + tìm theo mô tả, riêng theo người, khử trùng ref."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


def _patch_dir(tmp_path, monkeypatch):
    import services.config as cfg
    monkeypatch.setattr(cfg, "DATA_DIR", str(tmp_path), raising=False)


def test_ghi_va_tim_theo_mo_ta(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import so_da_luu as s
    assert s.ghi("u1", ref="http://x/anh1.png", kind=s.KIND_ANH,
                 mo_ta="hộp thuốc Concor 5mg", ten="Concor-5mg-10.jpg")
    assert s.ghi("u1", ref="http://x/anh2.png", kind=s.KIND_ANH,
                 mo_ta="ảnh con trai chơi bóng", ten="son.jpg")
    assert s.ghi("u2", ref="http://x/other.png", kind=s.KIND_ANH,
                 mo_ta="hộp thuốc của người khác")

    kq = s.tim("u1", "gửi ảnh thuốc")
    assert kq and kq[0]["ref"] == "http://x/anh1.png"
    kq2 = s.tim("u1", "ảnh con trai")
    assert kq2 and kq2[0]["ref"] == "http://x/anh2.png"
    # Không rò rỉ sang người khác.
    assert all(m["ref"] != "http://x/other.png" for m in s.tim("u1", "thuốc"))
    # Không khớp → rỗng, không bịa.
    assert s.tim("u1", "xe máy giao hàng") == []


def test_loc_theo_kind(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import so_da_luu as s
    s.ghi("u3", ref="http://x/hd.pdf", kind=s.KIND_TAILIEU, mo_ta="hợp đồng thuê nhà")
    s.ghi("u3", ref="http://x/anh.png", kind=s.KIND_ANH, mo_ta="ảnh hợp đồng chụp")
    chi_anh = s.tim("u3", "hợp đồng", kind=s.KIND_ANH)
    assert chi_anh and all(m["kind"] == s.KIND_ANH for m in chi_anh)
    chi_tl = s.tim("u3", "hợp đồng", kind=s.KIND_TAILIEU)
    assert chi_tl and all(m["kind"] == s.KIND_TAILIEU for m in chi_tl)


def test_bo_trung_ref_cap_nhat_mo_ta(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import so_da_luu as s
    s.ghi("u4", ref="http://x/a.png", kind=s.KIND_ANH, mo_ta="cũ")
    s.ghi("u4", ref="http://x/a.png", kind=s.KIND_ANH, mo_ta="mới")
    ds = s.liet_ke("u4")
    assert len([m for m in ds if m["ref"] == "http://x/a.png"]) == 1
    assert ds[0]["mo_ta"] == "mới"


def test_handler_gui_lai_anh(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import capabilities as caps
    from services.agent import so_da_luu as s
    s.ghi("uX", ref="http://x/thuoc.png", kind=s.KIND_ANH, mo_ta="hộp thuốc Concor")
    out = caps._h_tim_da_luu({"mo_ta": "ảnh thuốc"}, {"user_id": "uX"})
    assert out.get("image_url") == "http://x/thuoc.png"
    out2 = caps._h_tim_da_luu({"mo_ta": "phi thuyền vũ trụ"}, {"user_id": "uX"})
    assert "chưa" in out2["text"].lower()
    out3 = caps._h_tim_da_luu({"mo_ta": ""}, {"user_id": "uX"})
    assert "mô tả" in out3["text"].lower()
