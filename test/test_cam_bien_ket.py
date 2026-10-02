"""Cảm biến kẹt theo ngày — tầng học coi ngày kẹt là «không biết» (chủ máy 02/10/2026).

Ca thật: radar phòng học báo «có người» 99–100% mỗi ngày 22–29/09, khoảng cách đứng im 126 cm; từ 01/10 về 14–18%."""
from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import thoi_quen_nha as tq  # noqa: E402
from services.cam_bien_ket import bo_ket, ngay_ket  # noqa: E402


def _t(ngay: int, gio: int, phut: int = 0) -> float:
    return datetime(2026, 9, ngay, gio, phut).timestamp()


def _chuoi_ket():
    """Bình thường 21/09, KẸT on 22 + 23/09 (chớp tắt 10 phút — vẫn ≥ 98%), bình thường lại từ 24/09."""
    ev = [(_t(21, 8), "on"), (_t(21, 12), "off"), (_t(21, 23, 50), "on"),
          (_t(22, 9), "off"), (_t(22, 9, 10), "on"),
          (_t(24, 7), "off"), (_t(24, 19), "on"), (_t(24, 21), "off")]
    return [t for t, _ in ev], [g for _, g in ev]


def test_ngay_on_tren_98_phan_tram_la_ket():
    ts, gt = _chuoi_ket()
    q = ngay_ket(ts, gt, _t(21, 0), _t(26, 0))
    assert [datetime.fromtimestamp(a).day for a, _ in q] == [22, 23]


def test_cam_bien_binh_thuong_va_so_do_khong_bi_dung():
    ts, gt = [_t(21, 8), _t(21, 20)], ["on", "off"]
    assert ngay_ket(ts, gt, _t(21, 0), _t(24, 0)) == []
    so = [_t(21, h) for h in range(24)]
    assert bo_ket(so, ["126"] * 24, _t(21, 0), _t(23, 0)) == (so, ["126"] * 24)


def test_ngay_ket_thanh_khong_biet_roi_tro_lai_gia_tri_that():
    ts, gt = _chuoi_ket()
    t2, g2 = bo_ket(ts, gt, _t(21, 0), _t(26, 0))
    assert tq._truoc(t2, g2, _t(21, 10)) == "on", "trước ngày kẹt giữ nguyên"
    assert tq._truoc(t2, g2, _t(22, 15)) is None, "trong ngày kẹt là không biết"
    assert tq._truoc(t2, g2, _t(23, 15)) is None, "hai ngày kẹt liền nhau đều không biết"
    assert tq._truoc(t2, g2, _t(24, 3)) == "on", "hết kẹt: trả giá trị thật lúc ấy"
    assert tq._truoc(t2, g2, _t(24, 8)) == "off"


def test_kich_hoat_khong_sinh_moc_co_nguoi_vao_trong_ngay_ket(tmp_path, monkeypatch):
    import sqlite3
    from services import kich_hoat_nha as kh
    db = tmp_path / "ls.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE su_kien (ts REAL, thiet_bi TEXT, truong TEXT, gia_tri TEXT)")
    ma = "binary_sensor.hien_dien_phong_hoc_occupancy"
    ev = [(_t(21, 8), "on"), (_t(21, 12), "off"), (_t(21, 23, 50), "on"),
          (_t(22, 9), "off"), (_t(22, 9, 10), "on"),          # chớp trong ngày kẹt
          (_t(24, 7), "off"), (_t(24, 19), "on"), (_t(24, 21), "off")]
    c.executemany("INSERT INTO su_kien VALUES (?,?,?,?)", [(t, ma, "state", g) for t, g in ev])
    c.commit()
    monkeypatch.setattr(kh._cbg, "ds", lambda: {})
    sk = kh._su_kien_nguon(c, _t(21, 0), _t(26, 0), set())
    moc = [datetime.fromtimestamp(t).strftime("%d %H:%M") for t, n in sk if n.endswith("có người vào")]
    assert "22 09:10" not in moc, "chớp trong ngày kẹt không phải người vào"
    assert "24 19:00" in moc and "21 23:50" in moc
