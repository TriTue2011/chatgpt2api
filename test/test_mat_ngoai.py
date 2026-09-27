"""Thiết bị nhận mặt ngoài (Hanet, Double Take, HA…) qua MQTT / HTTP — `services.mat_ngoai`.

Chủ máy 27/09/2026: "nếu tôi có hannet hoặc bất kỳ thiết bị nào nhận diện được khuôn mặt thì
tôi nối qua mqtt hoặc ha vào như nào … lấy được ảnh khuôn mặt … gắn vào c2a để gửi cùng".
"""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from services import mat_ngoai, so_mat_nha, thong_bao  # noqa: E402
from services.config import config  # noqa: E402

pytestmark = pytest.mark.pure

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 50


@pytest.fixture
def mn(monkeypatch):
    tmp = tempfile.TemporaryDirectory()
    monkeypatch.setattr(type(config), "images_dir", mock.PropertyMock(return_value=Path(tmp.name)))
    monkeypatch.setattr("services.local_gateway.gateway_base_url", lambda: "http://cong:5000")
    monkeypatch.setattr(so_mat_nha, "tim_nguoi",
                        lambda ten: {"id": "p1", "ten": "Con trai Trí Anh"} if ten == "Con trai Trí Anh" else None)
    ghi: list = []
    monkeypatch.setattr(so_mat_nha, "ghi_su_kien", lambda *a, **k: ghi.append((a, k)) or {})
    gui: list = []
    monkeypatch.setattr(thong_bao, "gui", lambda khoa, tin, anh="": gui.append((khoa, tin, anh)) or 1)
    mat_ngoai._da_bao.clear()
    mn_ = mat_ngoai
    mn_.ghi, mn_.gui_ = ghi, gui
    yield mn_
    tmp.cleanup()


def test_ten_trung_nguoi_da_day_thi_ghi_luot_gap_va_bao_kem_anh(mn):
    kq = mn.nhan({"ten": "Con trai Trí Anh", "vi_tri": "Cổng", "do_tin": 0.93,
                  "anh": base64.b64encode(JPEG).decode()}, nguon="hanet")
    assert kq["ok"] and kq["nguoi_id"] == "p1" and kq["anh"].startswith("http://cong:5000/images/")
    (cam, nguon, loai), k = mn.ghi[0]
    assert (cam, nguon, loai) == ("Cổng", "ngoai:hanet", "quen") and k["do_giong"] == 93
    khoa, tin, anh = mn.gui_[0]
    assert khoa == "camera.nguoi_quen" and "Con trai Trí Anh — Cổng" in tin and anh == kq["anh"]


def test_nhan_ten_truong_cua_thiet_bi_va_ten_la_van_bao(mn):
    """Tên trường kiểu Hanet (personName/deviceName) nhận thẳng; tên chưa dạy thì không ghi
    thành người nhà nhưng vẫn báo, kèm lời nhắc đặt cùng tên."""
    kq = mn.nhan({"personName": "Bà ngoại", "deviceName": "Cửa chính"}, nguon="hanet")
    assert kq["ok"] and kq["nguoi_id"] is None and mn.ghi == []
    assert "chưa có trong sổ mặt" in mn.gui_[0][1] and "Cửa chính" in mn.gui_[0][1]


def test_gop_tin_trong_cung_cua_so(mn):
    for _ in range(3):
        mn.nhan({"ten": "Con trai Trí Anh", "vi_tri": "Cổng"})
    assert len(mn.gui_) == 1 and len(mn.ghi) == 3, "ghi đủ lượt, báo một lần"


def test_thieu_ten_va_anh_hong(mn):
    assert not mn.nhan({"vi_tri": "Cổng"})["ok"]
    assert mn.nhan({"ten": "Con trai Trí Anh", "anh": "khong-phai-base64!!"})["anh"] == ""
    assert mn._tai_anh("http://192.168.1.5/x.jpg") == b"", "địa chỉ nội bộ lạ bị net_guard chặn"


def test_mqtt_chu_de_mang_ten_thiet_bi(mn):
    mn.tu_mqtt("c2a/khuon_mat/hanet", '{"ten": "Con trai Trí Anh", "vi_tri": "Cổng"}'.encode())
    assert mn.ghi[0][0][1] == "ngoai:hanet"
    mn.tu_mqtt("c2a/khuon_mat", b"khong phai json")          # không raise
