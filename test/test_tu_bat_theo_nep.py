"""Tự bật theo nếp (05/10/2026) — học giờ & thời lượng từ lần NGƯỜI bật, chốt an toàn. Lịch sử giả, không gọi HA."""
from __future__ import annotations

import os
import sqlite3
import time
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import tu_bat_theo_nep as tb  # noqa: E402

BNL = "switch.binh_nong_lanh"
NHIET = "sensor.nhiet_ngoai"
LECH = 7 * 3600


def _luc(ngay_truoc: int, gio: int, phut: int, now: float) -> float:
    """Mốc giờ địa phương (+7) của ``ngay_truoc`` ngày trước."""
    dau_hom_nay = ((now + LECH) // 86400) * 86400 - LECH
    return dau_hom_nay - ngay_truoc * 86400 + gio * 3600 + phut * 60


@pytest.fixture
def nha(tmp_path, monkeypatch):
    tb._reset_for_tests(tmp_path / "tb.json")
    db = tmp_path / "ls.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE su_kien (ts REAL, thiet_bi TEXT, truong TEXT, gia_tri TEXT, do_ai INT)")
    conn.execute("CREATE TABLE so_do (o_5p INT, thiet_bi TEXT, nho REAL, lon REAL, tb REAL, n INT)")
    from services import lich_su_nha
    monkeypatch.setattr(lich_su_nha, "_DB_PATH", db)
    return conn


def _bat(conn, t: float, phut: float, do_ai: int = 0) -> None:
    conn.execute("INSERT INTO su_kien VALUES (?,?,?,?,?)", (t, BNL, "state", "on", do_ai))
    conn.execute("INSERT INTO su_kien VALUES (?,?,?,?,?)", (t + phut * 60, BNL, "state", "off", do_ai))
    conn.commit()


def test_hoc_gio_va_thoi_luong_tu_nguoi_bat(nha):
    now = _luc(0, 4, 30, time.time())
    for d in range(1, 15):
        _bat(nha, _luc(d, 17, (d % 3) * 5, now), 18 + d % 4)
    n = tb.nep(BNL, now)
    assert n["du"] and n["gio"] == "17:05" and 18 <= n["phut_bat"] <= 22


def test_khong_hoc_tu_lan_bot_bat(nha):
    now = _luc(0, 4, 30, time.time())
    for d in range(1, 15):
        _bat(nha, _luc(d, 6, 0, now), 20, do_ai=1)       # bot bật 6:00 — không phải nếp người
    n = tb.nep(BNL, now)
    assert not n["du"], "chỉ học lần NGƯỜI bật — bot tự bật không thành nếp"


def test_it_ngay_hoac_thua_thi_chua_du(nha):
    now = _luc(0, 4, 30, time.time())
    for d in (1, 9, 18, 30, 45, 58):
        _bat(nha, _luc(d, 17, 0, now), 20)
    assert not tb.nep(BNL, now)["du"]


def test_chia_thoi_luong_theo_troi_nong_mat(nha):
    now = _luc(0, 16, 0, time.time())
    for d in range(1, 13):
        mat = d % 2 == 0
        t = _luc(d, 17, 0, now)
        _bat(nha, t, 28 if mat else 15)
        nha.execute("INSERT INTO so_do VALUES (?,?,?,?,?,?)", (int(t // 300), NHIET, 0, 0, 22.0 if mat else 34.0, 1))
    nha.execute("INSERT INTO so_do VALUES (?,?,?,?,?,?)", (int(now // 300), NHIET, 0, 0, 23.0, 1))
    nha.commit()
    n = tb.nep(BNL, now, NHIET)
    assert n["phut_bat"] == 28 and "mát" in n["chia"]


@pytest.fixture
def chay(nha, monkeypatch):
    from services import du_doan_nha as dd, ha_client, kich_hoat_nha as kh, thong_bao
    now = _luc(0, 17, 3, time.time())
    for d in range(1, 15):
        _bat(nha, _luc(d, 17, 0, now), 20)
    st = {"tt": "off", "lam": [], "tin": [], "co_nguoi": True}
    monkeypatch.setattr(ha_client, "get_state", lambda m: {"state": st["tt"]})
    monkeypatch.setattr(kh, "_lam", lambda t, hd, tu_lam: st["lam"].append(hd) or st.update(tt=hd) or True)
    monkeypatch.setattr(kh, "_nk", lambda *a, **k: None)
    monkeypatch.setattr(kh, "_ten_tb", lambda t: "Bình nóng lạnh")
    monkeypatch.setattr(kh, "nha_co_nguoi", lambda tru, luc, t=None: st["co_nguoi"])
    monkeypatch.setattr(dd, "ghi_nhan", lambda *a, **k: 5)
    monkeypatch.setattr(thong_bao, "gui", lambda k, t, *a, **kw: st["tin"].append(t) or 1)
    monkeypatch.setattr(tb, "_hen_tat", lambda t, giay: None)
    st["now"] = now
    return st


def test_chua_bat_che_do_thi_khong_lam(chay):
    assert tb.xet(BNL, chay["now"]) == "chưa bật chế độ" and chay["lam"] == []


def test_toi_gio_bat_roi_het_thoi_luong_tu_tat(chay):
    tb.dat(BNL, True)
    assert tb.xet(BNL, chay["now"]).startswith("đã bật") and chay["lam"] == ["on"]
    assert "#5" in chay["tin"][-1] and "Đúng hay sai" in chay["tin"][-1]
    assert tb.xet(BNL, chay["now"] + 300) == "hôm nay đã xử lý", "không bật đúp"
    assert tb.xet(BNL, chay["now"] + 3600) == "tới giờ tắt" and chay["lam"] == ["on", "off"]


def test_nha_vang_khong_bat(chay):
    tb.dat(BNL, True)
    chay["co_nguoi"] = False
    assert tb.xet(BNL, chay["now"]) == "nhà vắng" and chay["lam"] == []


def test_nguoi_da_bat_hom_nay_thi_thoi(chay, nha):
    tb.dat(BNL, True)
    _bat(nha, chay["now"] - 3 * 3600, 20)        # sáng nay người đã bật
    assert tb.xet(BNL, chay["now"]) == "người đã bật hôm nay" and chay["lam"] == []


def test_ngoai_khung_gio_khong_bat(chay):
    tb.dat(BNL, True)
    assert tb.xet(BNL, chay["now"] - 2 * 3600).startswith("chưa tới giờ") and chay["lam"] == []


def test_nguoi_tat_truoc_thi_bot_khong_tat_nua(chay):
    tb.dat(BNL, True)
    tb.xet(BNL, chay["now"])
    chay["tt"] = "off"                            # người đã tắt sớm
    tb.xet(BNL, chay["now"] + 3600)
    assert chay["lam"] == ["on"], "đã tắt rồi thì không gửi lệnh tắt"
