"""Định tuyến theo cặp ngôn ngữ: en↔vi đi EnViT5, còn lại đi NLLB.

Không nạp model thật: thay hai backend bằng hàm giả rồi kiểm ĐƯỜNG ĐI. Cái
đáng hỏng ở đây là chọn nhầm máy dịch và bỏ quên lớp mổ dòng, cả hai đều kiểm
được mà không cần 900 MB model.
"""
from __future__ import annotations

import pytest

from app.engine import Engine, KhongCoNgonNgu


@pytest.fixture()
def may(monkeypatch):
    e = Engine()
    e.nhan_ky: list[tuple[str, list[str]]] = []

    def envit5(manh, nguon, dich):
        e.nhan_ky.append(("envit5", list(manh)))
        return [f"E<{m}>" for m in manh]

    def nllb(manh, nguon, dich):
        e.nhan_ky.append(("nllb", list(manh)))
        return [f"N<{m}>" for m in manh]

    monkeypatch.setattr(e, "_co_envit5", lambda: True)
    monkeypatch.setattr(e, "_dich_envit5", envit5)
    monkeypatch.setattr(e, "_dich_nllb", nllb)
    monkeypatch.setattr(e, "_nap", lambda: None)
    e._tr = object()          # coi như NLLB đã nạp
    return e


def _may_nao(e):
    return [x[0] for x in e.nhan_ky]


@pytest.mark.parametrize("nguon, dich", [("vi", "en"), ("en", "vi")])
def test_en_vi_di_envit5(may, nguon, dich):
    assert may.dich(["hello"], nguon, dich) == ["E<hello>"]
    assert _may_nao(may) == ["envit5"]


@pytest.mark.parametrize("nguon, dich", [
    ("vi", "ja"), ("ja", "vi"), ("ko", "vi"), ("vi", "zh-Hans"), ("en", "ja"),
])
def test_cap_khac_di_nllb(may, nguon, dich):
    assert may.dich(["hello"], nguon, dich) == ["N<hello>"]
    assert _may_nao(may) == ["nllb"]


def test_envit5_hong_thi_roi_xuong_nllb(may, monkeypatch):
    def no(manh, nguon, dich):
        raise RuntimeError("model hỏng")

    monkeypatch.setattr(may, "_dich_envit5", no)
    assert may.dich(["hello"], "vi", "en") == ["N<hello>"]
    assert _may_nao(may) == ["nllb"]


def test_khong_co_envit5_thi_dung_nllb(may, monkeypatch):
    monkeypatch.setattr(may, "_co_envit5", lambda: False)
    assert may.dich(["hello"], "vi", "en") == ["N<hello>"]
    assert _may_nao(may) == ["nllb"]


def test_envit5_cung_di_qua_lop_mo_dong(may):
    """Dòng trống + tên riêng KHÔNG được gửi cho EnViT5, y như với NLLB."""
    ra = may.dich(["Vu Minh Tuan\n\nxin chào\n10:51"], "vi", "en")
    assert may.nhan_ky == [("envit5", ["xin chào"])]
    assert ra == ["Vu Minh Tuan\n\nE<xin chào>\n10:51"]


def test_ngon_ngu_la_van_bao_loi(may):
    with pytest.raises(KhongCoNgonNgu):
        may.dich(["x"], "xx", "vi")


def test_khong_co_gi_de_dich_thi_khong_goi_may_nao(may):
    assert may.dich(["", "  ", "---"], "vi", "en") == ["", "  ", "---"]
    assert may.nhan_ky == []
