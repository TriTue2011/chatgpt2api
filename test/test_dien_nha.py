"""Mất điện qua NUT (chủ máy 05/10/2026) — đọc upsd, báo mất điện / có điện / pin yếu, giữ tin khi chưa gửi được.

Chuỗi trạng thái lấy từ lần mất điện THẬT 05/10/2026 (lịch sử cảm biến HA): 14:28:15 chuyển OB ở 69%, 14:47:15
«OB LB» ở 8%, máy chủ sập, khởi động lại thì OL 100%. Không gọi NUT thật."""
from __future__ import annotations

import os
import socket
import threading

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import dien_nha as dn  # noqa: E402

T0 = 1_791_185_295.0   # 14:28:15 05/10/2026 giờ VN


def _ups(st, pin="69", tai="28"):
    return {"ups.status": st, "battery.charge": pin, "battery.charge.low": "15", "ups.load": tai}


@pytest.fixture
def nha(tmp_path, monkeypatch):
    dn._reset_for_tests(tmp_path / "dien.json")
    monkeypatch.setitem(dn.config.data, "dien_nha", {"nut": "prolink@127.0.0.1:1"})
    st = {"doc": _ups("OL", "100"), "gui": [], "kenh_song": True}

    def doc(dc):
        if st["doc"] is None:
            raise OSError("Connection refused")
        return st["doc"]
    monkeypatch.setattr(dn, "doc", doc)
    from services import thong_bao

    def gui(khoa, tin, anh_url=""):
        if not st["kenh_song"]:
            return 0
        st["gui"].append((khoa, tin))
        return 1
    monkeypatch.setattr(thong_bao, "gui", gui)
    return st


def test_lan_mat_dien_that_05_10(nha):
    assert dn.chay_mot_lan(T0 - 60) == []
    nha["doc"] = _ups("OB", "69")
    assert dn.chay_mot_lan(T0) == [], "mới chạy pin, chưa đủ 10 s thì chưa báo"
    tin = dn.chay_mot_lan(T0 + 10)
    assert len(tin) == 1 and "Mất điện từ 14:28" in tin[0] and "còn 69%" in tin[0] and "dưới 15%" in tin[0]
    assert dn.chay_mot_lan(T0 + 300) == [], "đã báo thì không báo lại mỗi nhịp"

    nha["doc"] = _ups("OB LB", "8")
    tin = dn.chay_mot_lan(T0 + 19 * 60)
    assert len(tin) == 1 and "Pin UPS còn 8%" in tin[0] and "đang tắt" in tin[0]
    assert dn.chay_mot_lan(T0 + 19 * 60 + 5) == []

    # máy chủ sập; 4 giờ sau có điện, c2a khởi động lại và đọc được OL
    nha["doc"] = _ups("OL", "100")
    tin = dn.chay_mot_lan(T0 + 4 * 3600)
    assert len(tin) == 1 and "Có điện lại" in tin[0] and "từ 14:28" in tin[0] and "~240 phút" in tin[0]
    assert "đã tự khởi động lại" in tin[0]
    assert [k for k, _ in nha["gui"]] == ["nha.mat_dien"] * 3


def test_chop_dien_vai_giay_thi_im(nha):
    nha["doc"] = _ups("OB")
    dn.chay_mot_lan(T0)
    nha["doc"] = _ups("OL")
    assert dn.chay_mot_lan(T0 + 5) == []
    nha["doc"] = _ups("OB")
    assert dn.chay_mot_lan(T0 + 60) == [], "lần chạy pin mới đếm lại từ đầu"
    assert nha["gui"] == []


def test_pin_yeu_ngay_thi_bao_ca_hai_khong_cho_xac_nhan(nha):
    nha["doc"] = _ups("OB LB", "12")
    tin = dn.chay_mot_lan(T0)
    assert len(tin) == 2 and "Mất điện" in tin[0] and "Pin UPS còn 12%" in tin[1]


def test_khong_doc_duoc_ups_bao_loi_he_thong(nha):
    nha["doc"] = None
    assert dn.chay_mot_lan(T0) == []
    assert dn.chay_mot_lan(T0 + 179) == []
    tin = dn.chay_mot_lan(T0 + 180)
    assert len(tin) == 1 and "Không đọc được UPS" in tin[0] and "prolink@127.0.0.1:1" in tin[0]
    assert dn.chay_mot_lan(T0 + 600) == []
    nha["doc"] = _ups("OL", "100")
    tin = dn.chay_mot_lan(T0 + 605)
    assert len(tin) == 1 and "Đọc lại được UPS" in tin[0]
    assert [k for k, _ in nha["gui"]] == ["he_thong.loi", "he_thong.loi"]


def test_tin_chua_gui_duoc_thi_giu_va_gui_lai_dung_thu_tu(nha):
    nha["kenh_song"] = False                      # mất điện → modem tắt, chưa có mạng
    nha["doc"] = _ups("OB", "69")
    dn.chay_mot_lan(T0)
    dn.chay_mot_lan(T0 + 10)
    nha["doc"] = _ups("OL", "60")
    dn.chay_mot_lan(T0 + 900)
    assert nha["gui"] == [] and len(dn.trang_thai()["hang_doi"]) == 2

    nha["kenh_song"] = True
    dn.chay_mot_lan(T0 + 905)
    assert nha["gui"] == [], "vừa thử lúc T0+900, chờ đủ nhịp gửi lại"
    dn.chay_mot_lan(T0 + 900 + dn.GUI_LAI_GIAY)
    assert ["Mất điện" in nha["gui"][0][1], "Có điện lại" in nha["gui"][1][1]] == [True, True]
    assert dn.trang_thai()["hang_doi"] == []


def test_tin_qua_han_giu_thi_bo(nha):
    nha["kenh_song"] = False
    nha["doc"] = _ups("OB LB", "10")
    dn.chay_mot_lan(T0)
    nha["kenh_song"] = True
    nha["doc"] = _ups("OL", "100")
    dn.chay_mot_lan(T0 + dn.GIU_TIN_GIAY + 1)
    assert len(nha["gui"]) == 1 and "Có điện lại" in nha["gui"][0][1]


def test_chua_khai_dia_chi_thi_nam_im(nha, monkeypatch):
    monkeypatch.setitem(dn.config.data, "dien_nha", {})
    nha["doc"] = _ups("OB LB", "5")
    assert dn.chay_mot_lan(T0) == [] and nha["gui"] == []


# ── doc(): giao thức NUT với một upsd giả ──────────────────────────────────
def _upsd_gia(tra_loi: bytes):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def chay():
        c, _ = srv.accept()
        c.recv(100)
        for i in range(0, len(tra_loi), 50):        # chia nhỏ: doc() phải gom đủ tới dòng END
            c.sendall(tra_loi[i:i + 50])
        c.close()
        srv.close()
    threading.Thread(target=chay, daemon=True).start()
    return srv.getsockname()[1]


def test_doc_dung_dinh_dang_upsd_that():
    cong = _upsd_gia(b'BEGIN LIST VAR prolink\nVAR prolink battery.charge "100"\nVAR prolink battery.charge.low "15"\n'
                     b'VAR prolink device.model "PRO1201SFC"\nVAR prolink ups.status "OB LB"\nEND LIST VAR prolink\n')
    d = dn.doc(f"prolink@127.0.0.1:{cong}")
    assert d == {"battery.charge": "100", "battery.charge.low": "15", "device.model": "PRO1201SFC",
                 "ups.status": "OB LB"}


def test_doc_ups_sai_ten_thi_loi():
    cong = _upsd_gia(b"ERR UNKNOWN-UPS\n")
    with pytest.raises(ValueError, match="UNKNOWN-UPS"):
        dn.doc(f"khongco@127.0.0.1:{cong}")


def test_dia_chi_sai_dang():
    with pytest.raises(ValueError):
        dn.doc("172.16.10.100")


def test_tom_tat_cho_nut_kiem_tra():
    d = {"device.mfr": "Prolink", "device.model": "PRO1201SFC", "ups.status": "OB LB", "battery.charge": "12",
         "battery.charge.low": "15", "ups.load": "28", "input.voltage": "0.0"}
    assert dn.tom_tat(d) == ("Prolink PRO1201SFC — ĐANG CHẠY PIN, PIN YẾU, pin 12% (máy chủ tắt khi dưới 15%), "
                             "tải 28%, điện vào 0.0 V")


def _goi_endpoint(monkeypatch, body):
    from unittest import mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import mqtt
    app = FastAPI()
    with mock.patch("api.mqtt.require_admin", lambda *a, **k: None):
        app.include_router(mqtt.create_router())
        return TestClient(app).post("/api/dien-nha/thu", json=body).json()


def test_endpoint_thu_dia_chi_vua_nhap(monkeypatch):
    monkeypatch.setitem(dn.config.data, "dien_nha", {"nut": "cu@127.0.0.1:1"})
    cong = _upsd_gia(b'BEGIN LIST VAR prolink\nVAR prolink ups.status "OL"\nVAR prolink battery.charge "100"\n'
                     b'END LIST VAR prolink\n')
    d = _goi_endpoint(monkeypatch, {"nut": f"prolink@127.0.0.1:{cong}"})
    assert d == {"ok": True, "tom_tat": "UPS — đang dùng điện lưới, pin 100%"}


def test_endpoint_o_trong_dung_dia_chi_da_luu_va_noi_ly_do(monkeypatch):
    monkeypatch.setitem(dn.config.data, "dien_nha", {"nut": "prolink@127.0.0.1:1"})
    d = _goi_endpoint(monkeypatch, {"nut": ""})
    assert d["ok"] is False and "prolink@127.0.0.1:1" in d["error"] and "3493" in d["error"]
    monkeypatch.setitem(dn.config.data, "dien_nha", {})
    assert "chưa có địa chỉ NUT" in _goi_endpoint(monkeypatch, {})["error"]
