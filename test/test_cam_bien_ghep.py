"""Cảm biến ghép (29/09/2026): "phòng khách có người thật" = radar phòng khách VÀ (bếp vắng HOẶC
camera phòng khách thấy người).

Đo 30 ngày thật: radar phòng khách báo có người thì 49% thời gian radar bếp cũng báo; trong lúc
trùng, camera phòng khách thấy người 62% thời gian. Người đứng ở bếp làm radar phòng khách báo
lây → phòng khách VẮNG; hai phòng đều có người (camera thấy) → phòng khách CÓ NGƯỜI.
"""
from __future__ import annotations

import os
import sqlite3
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

PK = "binary_sensor.hien_dien_phong_khach_presence"
BEP = "binary_sensor.hien_dien_bep_presence"
CAM = "binary_sensor.phong_khach_person_occupancy"
GHEP = "binary_sensor.c2a_phong_khach_co_nguoi"
BT = {"va": [{"ma": PK}, {"hoac": [{"khong": {"ma": BEP}}, {"ma": CAM}]}]}


@pytest.fixture
def cb(tmp_path, monkeypatch):
    from services import cam_bien_ghep, lich_su_nha as ls

    ls._reset_for_tests()
    monkeypatch.setattr(ls, "_DB_PATH", tmp_path / "ls.sqlite")
    cam_bien_ghep._reset_for_tests(tmp_path / "cbg.json")
    tt = {PK: "off", BEP: "off", CAM: "off"}
    monkeypatch.setattr(cam_bien_ghep, "_tt_ha", lambda: dict(tt))
    ls._db()
    cam_bien_ghep.dat(GHEP, "Phòng khách có người (thật)", BT)
    cam_bien_ghep.tt = tt
    yield cam_bien_ghep
    cam_bien_ghep._reset_for_tests(tmp_path / "cbg.json")
    ls._reset_for_tests()


def _sk(ma: str, gt: str, ts: float) -> None:
    from services import lich_su_nha as ls
    with ls._khoa_db:
        ls._db().execute(
            "INSERT INTO su_kien (ts, nguon, thiet_bi, truong, gia_tri, gia_tri_cu, do_ai, gio, thu)"
            " VALUES (?,?,?,?,?,?,0,0,0)", (ts, "ha", ma, "state", gt, ""))
        ls._db().commit()


def _ro() -> sqlite3.Connection:
    from services import lich_su_nha as ls
    return sqlite3.connect(f"file:{ls._DB_PATH}?mode=ro", uri=True)


def test_bieu_thuc_theo_so_do_that(cb):
    t = lambda pk, bep, cam: cb.tinh(BT, {PK: pk, BEP: bep, CAM: cam})  # noqa: E731
    assert t("on", "off", "off")                   # chỉ phòng khách có người
    assert not t("on", "on", "off")                # người ở bếp, radar phòng khách báo lây
    assert t("on", "on", "on")                     # hai phòng đều có người — camera thấy
    assert not t("off", "off", "on")               # radar phòng khách vắng
    assert not t("unavailable", "off", "off")      # không rõ = không khớp


def test_kiem_dau_vao(cb):
    for ma, bt in (("binary_sensor.pk", BT), (GHEP, {"va": []}), (GHEP, {"ma": GHEP}),
                   (GHEP, {"ma": PK, "la": "on"}), (GHEP, {"moi": 1})):
        with pytest.raises(ValueError):
            cb.dat(ma, "x", bt)
    assert cb.thanh_phan(BT) == {PK, BEP, CAM}


def test_chuoi_dung_lai_tu_lich_su_cam_bien_goc(cb):
    _sk(PK, "on", 100.0)                  # trước cửa sổ: phòng khách có người
    _sk(BEP, "on", 1000.0)                # người sang bếp, radar phòng khách còn báo → vắng
    _sk(CAM, "on", 1500.0)                # camera thấy người ở phòng khách → có người
    _sk(CAM, "off", 1800.0)
    _sk(BEP, "off", 2000.0)               # bếp vắng, radar phòng khách vẫn báo → có người
    _sk(PK, "off", 2600.0)
    with _ro() as ro:
        assert cb.chuoi(ro, GHEP, 500.0, 3000.0) == [
            (500.0, "on"), (1000.0, "off"), (1500.0, "on"), (1800.0, "off"), (2000.0, "on"), (2600.0, "off")]


def test_song_bao_bo_kich_hoat_khi_doi(cb):
    goi = []
    with mock.patch("services.kich_hoat_nha.su_kien", lambda ma, v: goi.append((ma, v))):
        cb.khoi_tao()
        cb.tt[PK] = "on"
        assert cb.khi_doi(PK) == [(GHEP, "on")]
        cb.tt[BEP] = "on"                                   # sang bếp
        assert cb.khi_doi(BEP) == [(GHEP, "off")]
        assert cb.khi_doi(BEP) == []                        # không đổi thì không báo
        assert cb.khi_doi("binary_sensor.khac") == []       # thực thể không liên quan
    assert goi == [(GHEP, "on"), (GHEP, "off")]
    assert cb.hien_tai()[0]["state"] == "off"


def test_bo_kich_hoat_thay_vao_vang_va_quang_vang_cua_cam_bien_ghep(cb):
    from services import kich_hoat_nha as kh

    _sk(PK, "off", 0.0)
    _sk(PK, "on", 1000.0)                 # vào phòng khách (vắng từ 0 ≥ 3 phút)
    _sk(BEP, "on", 2000.0)                # sang bếp → phòng khách vắng
    _sk(BEP, "off", 2300.0)               # 5 phút sau quay lại phòng khách
    with _ro() as ro:
        sk = [n for _t, n in kh._su_kien_nguon(ro, 500.0, 3000.0, set(), chi={GHEP})]
        assert sk == [f"{GHEP} vắng", f"{GHEP} có người vào"]
        # Quãng vắng từ đầu cửa sổ tới lúc vào, rồi quãng người sang bếp 5 phút.
        assert kh._quang_vang(ro, [GHEP], 500.0, 3000.0) == [(500.0, 1000.0), (2000.0, 2300.0)]
