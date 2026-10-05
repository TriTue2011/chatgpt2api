"""Thiết bị tiện nghi (05/10/2026): cổng nhiệt độ cảm nhận học từ lần NGƯỜI bật + mức theo trời ngoài (quy tắc chủ
máy: mát / mưa → mức thấp). Lịch sử giả, không gọi HA."""
from __future__ import annotations

import os
import sqlite3
import time

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

QUAT, T, H, NGOAI = "fan.quat", "sensor.nhiet_khach", "sensor.am_khach", "sensor.nhiet_ban_cong"


@pytest.fixture
def kh(tmp_path, monkeypatch):
    from services import kich_hoat_nha, lich_su_nha as ls
    ls._reset_for_tests()
    db = tmp_path / "ls.sqlite"
    monkeypatch.setattr(ls, "_DB_PATH", db)
    kich_hoat_nha._reset_for_tests(tmp_path / "kh.json")
    kich_hoat_nha._tn_dem.clear()
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE su_kien (ts REAL, thiet_bi TEXT, truong TEXT, gia_tri TEXT, do_ai INT)")
    conn.execute("CREATE TABLE so_do (o_5p INT, thiet_bi TEXT, nho REAL, lon REAL, tb REAL, n INT)")
    now = time.time()
    # 30 lần người bật, trong nhà 32°C ẩm 70% (cảm nhận ~38,8), ngoài trời 28–33°C
    for i in range(30):
        t = now - (i + 1) * 3 * 3600
        conn.execute("INSERT INTO su_kien VALUES (?,?,?,?,?)", (t, QUAT, "state", "on", 0))
        for ma, v in ((T, 32.0), (H, 70.0), (NGOAI, 28.0 + i % 6)):
            conn.execute("INSERT INTO so_do VALUES (?,?,?,?,?,?)", (int(t // 300), ma, v, v, v, 1))
    conn.execute("INSERT INTO su_kien VALUES (?,?,?,?,?)", (now - 3600, QUAT, "state", "on", 1))   # bot bật — bỏ
    conn.commit()
    st = {"tt": {T: "32", H: "70", NGOAI: "31", "weather.nha": "sunny", QUAT: "off"}}

    def _trang():
        ra = [{"entity_id": m, "state": v, "attributes": {}} for m, v in st["tt"].items()]
        for x in ra:
            if x["entity_id"] == QUAT:
                x["attributes"] = {"preset_modes": ["low", "medium", "high"]}
            if x["entity_id"] == "weather.nha":
                x["attributes"] = {"temperature": 30}
        return ra
    monkeypatch.setattr(kich_hoat_nha, "_trang_thai_ha", _trang)
    monkeypatch.setattr(kich_hoat_nha, "_cam_bien_cam_nhan", lambda tb: (T, H))
    kich_hoat_nha._nap()["thiet_bi"][QUAT] = {"bat": True, "nhiet_ngoai": NGOAI}
    kich_hoat_nha._st = st
    return kich_hoat_nha


def test_hoc_nguong_cam_nhan_va_moc_troi_mat_tu_lan_nguoi_bat(kh):
    h = kh._hoc_tien_nghi(QUAT)
    assert h["so_mau"] == 30 and 38 < h["nguong"] < 40 and h["ngoai_p25"] == 29.0


def test_cong_chan_khi_mat_hon_muc_hay_bat(kh):
    assert kh.cong_tien_nghi(QUAT) is None, "đang nóng như lúc anh hay bật → cho bật"
    kh._st["tt"].update({T: "26", H: "60"})
    ly = kh.cong_tien_nghi(QUAT)
    assert ly and "trời mát" in ly
    assert kh.cong_tien_nghi("light.den") is None, "không phải thiết bị tiện nghi thì không xét"


def test_chua_du_mau_thi_khong_chan(kh, tmp_path, monkeypatch):
    from services import lich_su_nha as ls
    db = tmp_path / "trong.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE su_kien (ts REAL, thiet_bi TEXT, truong TEXT, gia_tri TEXT, do_ai INT)")
    c.execute("CREATE TABLE so_do (o_5p INT, thiet_bi TEXT, nho REAL, lon REAL, tb REAL, n INT)")
    c.commit()
    monkeypatch.setattr(ls, "_DB_PATH", db)
    kh._tn_dem.clear()
    kh._st["tt"].update({T: "20", H: "50"})
    assert kh.cong_tien_nghi(QUAT) is None


def test_muc_thap_khi_mua_hoac_ngoai_mat_thang_muc_may_hoc(kh):
    kh._nap()["mo_hinh"][QUAT] = {"muc": {"moc": [[30.0, "high", 5]], "cam_bien": T, "truong": "preset_mode"}}
    kh._st["tt"]["weather.nha"] = "rainy"
    assert kh._chon_muc(QUAT) == ("preset_mode", "low"), "mưa → mức thấp, thắng mức máy học"
    kh._st["tt"]["weather.nha"] = "sunny"
    kh._st["tt"][NGOAI] = "25"
    assert kh._chon_muc(QUAT) == ("preset_mode", "low"), "ngoài trời mát hơn lúc anh hay bật"
    kh._st["tt"][NGOAI] = "32"
    assert kh._chon_muc(QUAT) == ("preset_mode", "high"), "không mát → mức máy học"
