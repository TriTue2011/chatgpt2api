"""Nút «Tải xuống» (28/09/2026): chạy script tải ở nền, đọc tiến độ, trùng thì dùng lại, giới hạn."""
from __future__ import annotations

import os
import sys
import time
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import danh_muc_model, tai_model  # noqa: E402


@pytest.fixture(autouse=True)
def _sach():
    tai_model._reset_for_tests()
    yield
    tai_model._reset_for_tests()


def _cho(id_, han=10.0):
    het = time.time() + han
    while time.time() < het:
        v = next(x for x in tai_model.ds() if x["id"] == id_)
        if v["trang_thai"] != "dang_chay":
            return v
        time.sleep(0.05)
    raise AssertionError("việc tải không xong")


def _gia(ma: str):
    return lambda lenh: [sys.executable, "-c", ma]


def test_xong_doc_duoc_tien_do_ghi_de_bang_cr():
    ma = "import sys; sys.stdout.write('1.0/2.0 MB\\r2.0/2.0 MB\\n[ok] x.onnx\\n')"
    with mock.patch.object(danh_muc_model, "argv_cua", _gia(ma)):
        v = _cho(tai_model.bat_dau("lenh-a")["id"])
    assert v["trang_thai"] == "xong" and v["ma_thoat"] == 0
    assert v["dong"] == ["1.0/2.0 MB", "2.0/2.0 MB", "[ok] x.onnx"]


def test_script_loi_thi_bao_loi():
    with mock.patch.object(danh_muc_model, "argv_cua", _gia("import sys; print('[HONG] sha'); sys.exit(1)")):
        v = _cho(tai_model.bat_dau("lenh-b")["id"])
    assert (v["trang_thai"], v["ma_thoat"], v["dong"][-1]) == ("loi", 1, "[HONG] sha")


def test_bam_trung_dung_lai_va_toi_da_hai_viec():
    with mock.patch.object(danh_muc_model, "argv_cua", _gia("import time; time.sleep(1)")):
        a = tai_model.bat_dau("lenh-1")
        assert tai_model.bat_dau("lenh-1")["id"] == a["id"]
        tai_model.bat_dau("lenh-2")
        with pytest.raises(ValueError):
            tai_model.bat_dau("lenh-3")


def test_lenh_ngoai_danh_muc_bi_tu_choi():
    with mock.patch.object(danh_muc_model, "argv_cua", side_effect=ValueError("không thuộc")):
        with pytest.raises(ValueError):
            tai_model.bat_dau("rm -r /")
    assert tai_model.ds() == []
