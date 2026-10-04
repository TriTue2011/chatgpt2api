"""Độ tin cảm biến (04/10/2026) — đo flap/dwell/kẹt trên lịch sử giả, dán nhãn lành/nhiễu/kẹt. Không gọi HA."""
from __future__ import annotations

import os
import sqlite3
import time

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import do_tin_cam_bien as dt  # noqa: E402


@pytest.fixture
def ro(tmp_path, monkeypatch):
    db = tmp_path / "ls.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE su_kien (ts REAL, thiet_bi TEXT, truong TEXT, gia_tri TEXT)")
    conn.execute("CREATE TABLE so_do (o_5p INT, thiet_bi TEXT, nho REAL, lon REAL, tb REAL, n INT)")
    from services import lich_su_nha
    monkeypatch.setattr(lich_su_nha, "_DB_PATH", db)
    return conn


def _nhip(conn, ma, now, so_ngay, chu_ky_giay):
    """Đổi on/off đều mỗi chu_ky_giay suốt so_ngay."""
    t = now - so_ngay * 86400
    k = 0
    while t < now:
        conn.execute("INSERT INTO su_kien VALUES (?,?,?,?)", (t, ma, "state", "on" if k % 2 else "off"))
        t += chu_ky_giay
        k += 1
    conn.commit()


def test_nhieu_vs_lanh(ro):
    now = time.time()
    _nhip(ro, "binary_sensor.nhieu", now, 3, 8)        # đổi ~mỗi 8 giây → nhiễu
    _nhip(ro, "binary_sensor.lanh", now, 3, 2000)      # đổi ~mỗi 33 phút → lành
    assert dt.do("binary_sensor.nhieu", 3, now, ro)["nhan"] == "nhieu"
    assert dt.do("binary_sensor.lanh", 3, now, ro)["nhan"] == "lanh"


def test_ket_khi_7ngay_doi_nhung_24h_im(ro):
    now = time.time()
    # 7 ngày trước tới 2 ngày trước: đổi nhiều; 2 ngày gần đây: im
    t = now - 7 * 86400
    k = 0
    while t < now - 2 * 86400:
        ro.execute("INSERT INTO su_kien VALUES (?,?,?,?)", (t, "binary_sensor.ket", "state", "on" if k % 2 else "off"))
        t += 1800
        k += 1
    ro.commit()
    r = dt.do("binary_sensor.ket", 3, now, ro)
    assert r["nhan"] == "ket" and r["im_gio"] >= 24


def test_it_du_lieu(ro):
    now = time.time()
    ro.execute("INSERT INTO su_kien VALUES (?,?,?,?)", (now - 100, "binary_sensor.moi", "state", "on"))
    ro.commit()
    assert dt.do("binary_sensor.moi", 3, now, ro)["nhan"] == "it_du_lieu"


def test_khoang_cach_cham_0_nhieu_la_nhieu(ro):
    now = time.time(); o = int(now // 300)
    for i in range(60):
        nho = 0.0 if i % 10 < 8 else 2.0            # 80% ô chạm 0
        ro.execute("INSERT INTO so_do VALUES (?,?,?,?,?,?)", (o - 60 + i, "sensor.kc", nho, 5.0, 3.0, 5))
    ro.commit()
    assert dt.do_so("sensor.kc", 2, now, ro)["nhan"] == "nhieu"
    for i in range(60):
        ro.execute("INSERT INTO so_do VALUES (?,?,?,?,?,?)", (o - 60 + i, "sensor.kc2", 2.0, 2.6, 2.3, 5))
    ro.commit()
    assert dt.do_so("sensor.kc2", 2, now, ro)["nhan"] == "lanh"


def test_nguong_giu_nhieu_co_so_lanh_None(ro):
    now = time.time()
    _nhip(ro, "binary_sensor.nhieu", now, 3, 8)
    _nhip(ro, "binary_sensor.lanh", now, 3, 2000)
    assert dt.nguong_giu("binary_sensor.nhieu", 3, now) is not None
    assert dt.nguong_giu("binary_sensor.lanh", 3, now) is None
