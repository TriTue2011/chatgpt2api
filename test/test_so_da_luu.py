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


def test_hoi_mo_ta_luu_theo_mo_ta_nguoi_dung(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import so_da_luu as s
    s.dat_cho_mo_ta("uM", ref="http://x/a.png", ten="anh_1.jpg")
    out = s.xu_ly_tra_loi("uM", "hộp thuốc Concor")
    assert out and "mục lục" in out["text"].lower()
    assert s.tim("uM", "thuốc")[0]["ref"] == "http://x/a.png"


def test_hoi_mo_ta_bo_qua_van_luu_theo_ten(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import so_da_luu as s
    s.dat_cho_mo_ta("uN", ref="http://x/b.png", ten="hoadon.jpg")
    out = s.xu_ly_tra_loi("uN", "thôi")
    assert out and "lưu rồi" in out["text"].lower()
    assert s.tim("uN", "hoadon")[0]["ref"] == "http://x/b.png"


def test_hoi_mo_ta_khong_pending_tra_none(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import so_da_luu as s
    assert s.xu_ly_tra_loi("uZ", "câu bất kỳ") is None


def test_chon_so_sau_khi_tim_nhieu(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import so_da_luu as s
    items = [{"ref": "http://x/1.png", "mo_ta": "thuốc A", "kind": s.KIND_ANH},
             {"ref": "http://x/2.png", "mo_ta": "thuốc B", "kind": s.KIND_ANH}]
    s.dat_cho_chon("uP", items)
    out = s.xu_ly_tra_loi("uP", "2")
    assert out and out.get("image_url") == "http://x/2.png"


def test_handler_nhieu_ket_qua_ra_danh_sach_chon(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import capabilities as caps
    from services.agent import so_da_luu as s
    s.ghi("uQ", ref="http://x/t1.png", kind=s.KIND_ANH, mo_ta="thuốc Concor")
    s.ghi("uQ", ref="http://x/t2.png", kind=s.KIND_ANH, mo_ta="thuốc Panadol")
    out = caps._h_tim_da_luu({"mo_ta": "thuốc"}, {"user_id": "uQ"})
    assert "image_url" not in out            # KHÔNG gửi ngay
    assert "số" in out["text"].lower()       # mời chọn số
    r = s.xu_ly_tra_loi("uQ", "1")
    assert r and r.get("image_url") in ("http://x/t1.png", "http://x/t2.png")
