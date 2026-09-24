"""Đọc công thức hoá học cho TTS tiếng Việt (24/09/2026)."""
from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from services.voice import hoa_hoc as h  # noqa: E402


@pytest.mark.parametrize("viet, doc", [
    ("H₂O", "hát hai ô"),
    ("H2SO4", "hát hai ét ô bốn"),
    ("NaCl", "nờ a xê lờ"),
    ("C6H12O6", "xê sáu hát mười hai ô sáu"),
    ("Ca(OH)2", "xê a ô hát hai lần"),
    ("CuSO4.5H2O", "xê u ét ô bốn chấm năm hát hai ô"),
    ("SO4²⁻", "ét ô bốn hai trừ"),
    ("Fe³⁺", "ép e ba cộng"),
    ("Fe3+", "ép e ba cộng"),
    ("PO4^3-", "phê ô bốn ba trừ"),
    ("OH⁻", "ô hát trừ"),
])
def test_cong_thuc(viet, doc):
    assert h.doc(viet) == doc


def test_phuong_trinh_mui_ten_dau_cong_va_he_so():
    assert h.doc("3CO + Fe2O3 → 2Fe + 3CO2") == \
        "ba xê ô cộng ép e hai ô ba tạo thành hai ép e cộng ba xê ô hai"
    assert h.doc("BaCl2 + Na2SO4 → BaSO4↓ + 2NaCl").count("kết tủa") == 1
    assert "thuận nghịch" in h.doc("N2 + 3H2 ⇌ 2NH3")


@pytest.mark.parametrize("cau", [
    "Co giãn tốt.", "CON mèo.", "WHO họp.", "Mg trong máu.", "iPhone 15.",
    "Chương III.", "Covid-19.", "x² + 2x = 0, 10³", "Giá 100$.", "A4, MP3, G7.",
])
def test_khong_dung_chu_khong_phai_cong_thuc(cau):
    assert h.doc(cau) == cau


def test_dau_cau_dinh_cuoi_khong_thuoc_cong_thuc():
    assert h.doc("Axit là H2SO4.") == "Axit là hát hai ét ô bốn."


def test_doc_so():
    assert [h.doc_so(n) for n in (0, 4, 10, 12, 15, 21, 24, 25, 100, 105, 112)] == [
        "không", "bốn", "mười", "mười hai", "mười lăm", "hai mươi mốt", "hai mươi bốn",
        "hai mươi lăm", "một trăm", "một trăm linh năm", "một trăm mười hai"]


def test_engine_doi_chu_sau_khoa_cache_va_bo_qua_kokoro_anh(monkeypatch):
    from services.voice import config as vcfg
    from services.voice import engines, tts_cache

    monkeypatch.setattr(vcfg, "tts_backend", lambda: "local")
    khoa: list[bytes] = []
    monkeypatch.setattr(tts_cache, "get", lambda k: khoa.append(k))
    nhan: list[str] = []

    def nghi(text, voice, chen_nghi=True):
        nhan.append(text)
        yield 22050, b"\x10\x27" * 100

    monkeypatch.setattr(engines, "_nghi_phat", nghi)
    list(engines._stream_tao("Nước là H2O.", "nghi:ban-mai"))
    assert nhan == ["Nước là hát hai ô."]
    assert khoa[0] == tts_cache.key("stream", "Nước là H2O.", "nghi:ban-mai", "")
    assert engines._doc_cong_thuc("H2O", "kokoro:af") == "H2O"


def test_so_mu_dinh_dau_cau_khong_do_loi():
    assert h.doc("ion Fe³⁺, SO4²⁻.") == "ion ép e ba cộng, ét ô bốn hai trừ."
