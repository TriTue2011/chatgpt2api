"""Tầng CÓ NGƯỜI THẬT (29/09/2026): bot chọn cảm biến "khu có người" cho việc tắt khi vắng và ngoại
vi giữ khỏi tắt nhầm — code đo và bày, bot chọn, chủ máy chấm rồi mới áp.

Dựng lại đúng các hiện tượng đo ở phòng khách: radar bắt lây người ở bếp, camera thấy người ngồi
yên khi radar mất, cảm biến phòng học kẹt "có người" 100% (0 lần đổi/ngày).
"""
from __future__ import annotations

import sqlite3
from unittest import mock

import pytest

from test.test_kich_hoat_nha import _sk, kh  # noqa: F401 — fixture dùng chung

QUAT = "fan.phong_khach"
R = "binary_sensor.hien_dien_phong_khach_presence"
C = "binary_sensor.phong_khach_person_occupancy"
B = "binary_sensor.hien_dien_bep_presence"
H = "binary_sensor.hien_dien_phong_hoc_occupancy"
L = "device_tracker.laptop_vo"
KHU = {R: "Phòng khách", C: "Phòng khách", QUAT: "Phòng khách", B: "Bếp", H: "Phòng học"}
TT = [{"entity_id": QUAT, "state": "on", "attributes": {"friendly_name": "Quạt phòng khách"}},
      {"entity_id": R, "state": "on", "attributes": {"friendly_name": "Radar PK", "device_class": "presence"}},
      {"entity_id": C, "state": "off", "attributes": {"friendly_name": "Camera PK", "device_class": "occupancy"}},
      {"entity_id": B, "state": "off", "attributes": {"friendly_name": "Radar bếp", "device_class": "presence"}},
      {"entity_id": H, "state": "on", "attributes": {"friendly_name": "Radar học", "device_class": "occupancy"}},
      {"entity_id": L, "state": "home", "attributes": {"friendly_name": "Laptop vợ"}}]
T0 = 1_790_000_000.0
DEN = T0 + 20_000


@pytest.fixture
def cn(kh, tmp_path, monkeypatch):  # noqa: F811
    from services import boi_canh_nha, cam_bien_ghep, co_nguoi_nha, ha_client, hieu_thiet_bi_nha as ht

    ht._reset_for_tests()
    monkeypatch.setattr(ht, "_DB_PATH", tmp_path / "ht.sqlite")
    monkeypatch.setattr(ht, "_ten_ha", lambda: {x["entity_id"]: x["attributes"]["friendly_name"] for x in TT})
    cam_bien_ghep._reset_for_tests(tmp_path / "cbg.json")
    monkeypatch.setattr(cam_bien_ghep, "_tt_ha", lambda: {})
    monkeypatch.setattr(co_nguoi_nha, "_PATH", tmp_path / "cn.json")
    monkeypatch.setattr(boi_canh_nha, "phong_cua", lambda ma: KHU.get(ma, ""))
    monkeypatch.setattr(ha_client, "get_states", lambda: TT)
    yield co_nguoi_nha
    cam_bien_ghep._reset_for_tests(tmp_path / "cbg.json")
    ht._reset_for_tests()


def _lich_su() -> None:
    """Quạt bật suốt. Radar PK mất người 100 s ở 1000 (camera cũng không thấy — mất dấu), người
    sang bếp 3000–5000 (đi thật; radar bếp bật từ 2500 nên 2500–3000 radar PK báo lây), camera thấy
    người ngồi yên 8000–9000 lúc radar mất, rồi mất dấu 100 s nữa ở 9000."""
    for ma, gt, t in [(QUAT, "on", T0 - 10), (H, "on", T0 - 99), (H, "on", T0 + 50), (L, "home", T0 - 5000),
                      (R, "on", T0), (C, "on", T0 + 200), (C, "off", T0 + 900),
                      (R, "off", T0 + 1000), (R, "on", T0 + 1100), (C, "on", T0 + 1200),
                      (C, "off", T0 + 2000), (B, "on", T0 + 2500), (R, "off", T0 + 3000),
                      (B, "off", T0 + 5000), (R, "on", T0 + 5000), (R, "off", T0 + 8000),
                      (C, "on", T0 + 8000), (C, "off", T0 + 9000), (R, "on", T0 + 9100),
                      (R, "off", T0 + 10000)]:
        _sk(ma, gt, t)


def _do(cn):
    from services import lich_su_nha as ls
    with sqlite3.connect(f"file:{ls._DB_PATH}?mode=ro", uri=True) as ro:
        return cn.ung_vien(QUAT, ro, T0, DEN, trang_thai=TT, khu_tb="Phòng khách")


def test_do_bay_dung_hien_tuong_that(cn):
    _lich_su()
    uv = _do(cn)
    assert uv["trong"] == [R, C] and uv["ket"] == [H]          # kẹt không chiếm chỗ bảng lây
    assert [(c["r"], c["x"]) for c in uv["cap"]] == [(R, B)]
    assert uv["cap"][0]["xac"] == {C: "0%"}                     # lúc cùng báo camera không thấy ai
    assert (uv["ngan"], uv["dai"]) == (2, 1)
    assert uv["sang_khac"] == [{"x": B, "ngan": "0%", "dai": "100%"}]
    assert uv["hien_dien"][C]["rieng"] == "5%"                  # 1000 s camera thấy mà radar mất
    assert uv["ngoai_vi"][0]["ma"] == L and uv["ngoai_vi"][0]["ngan"] == "home 100%"
    de = cn.de(uv, "Quạt phòng khách", ["(chấm sai) quạt theo cả laptop vợ"])
    assert "GIÁO VIÊN DẶN" in de and "laptop vợ" in de and f"kẹt: {H}" in de


def test_khu_khong_co_cam_bien_thi_khong_hoi(cn):
    _lich_su()
    from services import lich_su_nha as ls
    with sqlite3.connect(f"file:{ls._DB_PATH}?mode=ro", uri=True) as ro:
        assert "không có cảm biến" in cn.ung_vien(QUAT, ro, T0, DEN, trang_thai=TT, khu_tb="Ban công")


def test_kiem_chi_nhan_ma_va_trang_thai_co_trong_de(cn):
    _lich_su()
    uv = {**_do(cn), "camera": ["Cam phòng khách", "Cam bếp"]}
    dung = {"co_nguoi": {"hoac": [{"ma": C}, {"va": [{"ma": R}, {"khong": {"ma": B}}]}]},
            "giu": {"va": [{"ma": L, "la": ["home"]}, {"khong": {"ma": B}}]}, "nhin": ["Cam phòng khách"],
            "chac": 0.8, "vi_sao": "x"}
    assert cn.kiem(dung, uv)["giu"] == dung["giu"] and cn.kiem(dung, uv)["nhin"] == ["Cam phòng khách"]
    assert cn.kiem({**dung, "giu": None, "nhin": None}, uv)["nhin"] is None
    for sai, vi in (({**dung, "co_nguoi": {"ma": "binary_sensor.bia"}}, "không có trong đề"),
                    ({**dung, "co_nguoi": {"ma": L, "la": ["home"]}}, "không dùng được ở đây"),
                    ({**dung, "giu": {"ma": L, "la": ["dang_dung"]}}, "trạng thái"),
                    ({**dung, "co_nguoi": {"ma": B}}, "trong khu"),
                    ({**dung, "co_nguoi": {"va": []}}, "Biểu thức"),
                    ({**dung, "nhin": None}, "NHÌN LẠI"),               # ngoại vi không giữ một mình
                    ({**dung, "nhin": ["Cam ban công"]}, "không có trong đề")):
        assert vi in cn.kiem(sai, uv)


def _ket_luan(cn, **k):
    from services import hieu_thiet_bi_nha as ht
    kl = {"ma_hoc": QUAT, "khu_vuc": "Phòng khách", "co_nguoi": {"hoac": [{"ma": C}, {"ma": R}]},
          "giu": {"va": [{"ma": L, "la": ["home"]}, {"khong": {"ma": B}}]}, "nhin": ["Cam phòng khách"],
          "chac": 0.8, "vi_sao": "", "ten": {R: "Radar PK", C: "Camera PK", L: "Laptop vợ", B: "Radar bếp"}, **k}
    ht.ghi_co_nguoi(1, [kl])
    return next(d for d in ht.dang_hieu_luc() if d["loai_cau_hoi"] == "co_nguoi")


def test_hoi_roi_moi_ap_sai_thi_tra_lai(cn, kh):  # noqa: F811
    from services import cam_bien_ghep, hieu_thiet_bi_nha as ht
    kh.dat_thiet_bi(QUAT, bat=True, tat_khi_vang={"bat": True, "cam_bien": [R], "phut": 3})
    d = _ket_luan(cn)
    assert "Camera PK hoặc Radar PK" in ht._cau_doc(d, {}) and "khi Laptop vợ là home và không Radar bếp thì nhìn lại bằng Cam phòng khách" in ht._cau_doc(d, {})
    assert cn.ap_dung() == []                                   # chưa chấm: chỉ hỏi
    assert kh._nap()["thiet_bi"][QUAT]["tat_khi_vang"]["cam_bien"] == [R]

    ht.sua_cham(d["id"], True, cham_boi="chu_may")
    ht.ap_ket_luan()
    vang, giu = cn.ma_ghep(QUAT, "vang"), cn.ma_ghep(QUAT, "giu")
    # Ngoại vi KHÔNG vào danh sách vắng — nó chỉ khiến bot nhìn lại bằng camera trước khi tắt.
    assert kh._nap()["thiet_bi"][QUAT]["tat_khi_vang"] == {
        "bat": True, "cam_bien": [vang], "phut": 3, "giu": giu, "nhin": ["Cam phòng khách"], "roi": "",
        "roi_phut": None}
    assert cam_bien_ghep.ds()[vang]["bieu_thuc"] == d["gia_tri"]["co_nguoi"]
    assert cn.ap_dung() == []                                   # áp rồi thì thôi

    ht.sua_cham(d["id"], False, cham_boi="chu_may", ghi_chu="đèn này chiếu cả bếp")
    ht.ap_ket_luan()
    assert kh._nap()["thiet_bi"][QUAT]["tat_khi_vang"] == {"bat": True, "cam_bien": [R], "phut": 3,
                                                           "giu": "", "nhin": [], "roi": "", "roi_phut": None}
    assert vang not in cam_bien_ghep.ds() and giu not in cam_bien_ghep.ds()
    assert ht.ghi_chu_cham("co_nguoi", QUAT) == ["(chấm sai) đèn này chiếu cả bếp"]


def test_tu_quyet_khong_de_cai_tay(cn, kh):  # noqa: F811
    from services import cam_bien_ghep, hieu_thiet_bi_nha as ht
    cam_bien_ghep.dat("binary_sensor.c2a_phong_khach_co_nguoi", "PK thật", {"ma": R})
    kh.dat_thiet_bi(QUAT, bat=True, tat_khi_vang={
        "bat": True, "cam_bien": ["binary_sensor.c2a_phong_khach_co_nguoi"], "phut": 3})
    _ket_luan(cn)
    with mock.patch.object(ht, "can_hoi", return_value=False):
        assert cn.ap_dung() == []                               # chủ máy cài tay: không đè
        kh.dat_thiet_bi(QUAT, tat_khi_vang={"bat": True, "cam_bien": [R], "phut": 3})
        assert [x["thiet_bi"] for x in cn.ap_dung()] == [QUAT]  # đủ thang lên cấp: tự áp


def test_giai_lai_khi_chu_nha_vua_cham_sai_khong_giai_lai_cau_lap_lai(cn):
    now = T0
    cu = {"ket_qua": "cho", "nhom": {"giai_luc": now - 3600}}
    assert not cn._can_giai(cu, now) and cn._can_giai(None, now)
    assert cn._can_giai({**cu, "ket_qua": "sai", "cham_boi": "chu_may", "cham_luc": now - 60}, now)
    assert not cn._can_giai({**cu, "ket_qua": "sai", "cham_boi": "lap_lai", "cham_luc": None}, now)
    assert cn._can_giai({**cu, "nhom": {"giai_luc": now - 8 * 86400}}, now)


def test_roi_khu_bay_bang_va_kiem_chi_nhan_cam_bien_khu_khac(cn):
    """Bảng F: ngay sau lúc khu vắng mà radar bếp báo có người (người sang bếp) thì khu này có người
    lại nhanh hay không — so với lúc không khu nào báo. roi_di chỉ nhận cảm biến KHU KHÁC."""
    _lich_su()
    _sk(B, "off", T0 + 2990)
    _sk(B, "on", T0 + 3030)                 # 30 s sau lúc PK vắng (3000), radar bếp thấy người
    uv = _do(cn)
    assert [d["x"] for d in uv["roi"]] == [B] and uv["roi"][0]["n"] == 1
    assert "khung" in uv["roi_nen"] and "nham" in uv["roi_nen"]
    de = cn.de(uv, "Quạt phòng khách", [])
    assert "F. RỜI KHU" in de and "(không cảm biến khu khác nào báo)" in de
    uv = {**uv, "camera": []}
    bai = {"co_nguoi": {"ma": R}, "giu": None, "nhin": None, "roi_di": {"ma": B}, "chac": 0.7, "vi_sao": ""}
    assert cn.kiem(bai, uv)["roi_di"] == {"ma": B}
    assert "KHU KHÁC" in cn.kiem({**bai, "roi_di": {"ma": R}}, uv), "cảm biến trong khu không phải «đã rời»"
    assert "KHU KHÁC" in cn.kiem({**bai, "roi_di": {"ma": H}}, uv), "cảm biến kẹt không dùng"
    # Đi ngang hay ở lại: bot chỉ chọn được đúng các mốc của cột cuối mục F.
    assert cn.kiem({**bai, "roi_khi_o_duoi": 3}, uv)["roi_khi_o_duoi"] == 3
    assert "roi_khi_o_duoi" in cn.kiem({**bai, "roi_khi_o_duoi": 7}, uv)
    assert cn.kiem({**bai, "roi_di": None, "roi_khi_o_duoi": 3}, uv)["roi_khi_o_duoi"] is None


def test_roi_khu_tach_di_ngang_voi_o_lai(cn):
    """Chủ máy 29/09/2026: "đi đến đâu sáng đến đó, nếu lưu trú thì giữ trạng thái". Bảng F tách tắt
    nhầm theo lúc trước người đã ở bao lâu: ghé 30 s rồi sang bếp (đi thật) khác ngồi 40 phút rồi
    radar bếp báo (người khác đi, người này quay lại ngay)."""
    _sk(QUAT, "on", T0 - 10)
    _sk(H, "on", T0 - 99)
    for ma, gt, t in [(R, "on", T0), (R, "off", T0 + 30), (B, "on", T0 + 50), (B, "off", T0 + 400),
                      (R, "on", T0 + 2000), (R, "off", T0 + 4400), (B, "on", T0 + 4420), (B, "off", T0 + 4500),
                      (R, "on", T0 + 4700), (R, "off", T0 + 9000)]:
        _sk(ma, gt, t)
    uv = _do(cn)
    d = next(d for d in uv["roi"] if d["x"] == B)
    assert d["n"] == 2 and d["o"] == "≤1' 0%/1 ≤3' 0%/1 ≤10' 0%/1"
    assert "tắt nhầm theo lúc trước đã ở" in cn.de(uv, "Quạt phòng khách", [])


def test_giao_vien_cham_sai_thi_bot_giai_lai_va_thay_loi_cham(cn, kh):  # noqa: F811
    """29/09/2026: giáo viên chấm #840/#841 sai (thiếu loại lây) mà bot không giải lại, cũng không
    thấy vì sao — nay lời giáo viên vào đề và kích giải lại."""
    import time as _t
    from services import hieu_thiet_bi_nha as ht
    kh.dat_thiet_bi(QUAT, bat=True, tat_khi_vang={"bat": True, "cam_bien": [R], "phut": 3})
    d = _ket_luan(cn)
    assert not cn._can_giai(d, _t.time())
    ht.sua_cham(d["id"], False, cham_boi="claude", ghi_chu="thiếu loại lây radar bếp")
    d = next(x for x in ht.dang_hieu_luc() if x["id"] == d["id"])
    assert cn._can_giai(d, _t.time())
    assert ht.ghi_chu_cham("co_nguoi", QUAT) == ["(giáo viên chấm sai) thiếu loại lây radar bếp"]
