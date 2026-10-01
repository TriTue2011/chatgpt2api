"""Vùng khoảng cách bot tự học (chủ máy 01/10/2026: "tắt thì cũng dựa vào khoảng cách"). Đo thật 10 ngày:
người ở phòng khách radar đo giữa 2,57 m; người ở bếp radar phòng khách báo lây giữa 4,44 m."""
from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from test.test_cam_bien_ghep import BEP, CAM, PK, _ro, _sk, cb  # noqa: E402,F401

KC = "sensor.hien_dien_phong_khach_distance"


@pytest.fixture
def vk(tmp_path):
    from services import vung_khoang_cach
    vung_khoang_cach._reset_for_tests(tmp_path / "vk.json")
    yield vung_khoang_cach
    vung_khoang_cach._reset_for_tests(tmp_path / "vk.json")


def _hoc_xong(vk, nguong=3.66, dat=True):
    vk._nap()[KC] = {"khu": "Phòng khách", "radar": PK, "huong": "duoi", "nguong": nguong, "dung": 0.89,
                     "dat": dat, "n_trong": 3000, "n_ngoai": 1400}


def test_nguong_can_bang_khong_de_nhan_dong_lan():
    from services import vung_khoang_cach as vk
    trong = [2.3, 2.5, 2.6, 2.9] * 50 + [4.0] * 5          # nhãn đông, vài số lẫn
    ngoai = [4.2, 4.5, 5.0] * 10
    t = vk.nguong(trong, ngoai)
    assert t["huong"] == "duoi" and 2.9 < t["nguong"] <= 4.2 and t["dung"] > 0.9
    assert vk.nguong([], ngoai) == {"dung": 0.0}


def test_gan_nhan_theo_camera_va_radar_khu_ben_canh():
    from services import vung_khoang_cach as vk
    radar = [(0.0, "on")]
    cam = [(0.0, "off"), (10.0, "on"), (20.0, "off")]
    bep = [(0.0, "off"), (30.0, "on")]
    kc = [(5.0, "2.5"), (12.0, "2.6"), (15.0, "0"), (25.0, "3.0"), (35.0, "4.4"), (36.0, "abc")]
    trong, ngoai = vk.gan_nhan(kc, radar, [cam], [bep])
    assert trong == [2.6] and ngoai == [4.4]   # 5 s: chưa ai báo; 15 s: số 0; 25 s: không camera không bếp


def test_trong_vung_khong_bao_gio_noi_trong_vi_thieu_hieu_biet(vk):
    assert vk.trong_vung(KC, "4.5")                    # chưa học
    _hoc_xong(vk, dat=False)
    assert vk.trong_vung(KC, "4.5")                    # học chưa đạt
    _hoc_xong(vk)
    assert vk.trong_vung(KC, "2.6") and not vk.trong_vung(KC, "4.5")
    assert vk.trong_vung(KC, "0") and vk.trong_vung(KC, "unknown") and vk.trong_vung(KC, None)


def test_nut_khoang_cach_trong_cam_bien_ghep(cb, vk):
    bt = {"hoac": [{"ma": CAM}, {"va": [{"ma": PK}, {"khoang_cach": KC}]}]}
    cb.dat("binary_sensor.c2a_pk_kc", "Phòng khách theo khoảng cách", bt)
    assert cb.thanh_phan(bt) == {CAM, PK, KC}
    _hoc_xong(vk)
    t = lambda pk, kc, cam="off": cb.tinh(bt, {PK: pk, KC: kc, CAM: cam})  # noqa: E731
    assert t("on", "2.6") and not t("on", "4.5") and t("on", "4.5", "on") and t("on", "0")
    for sai in ({"khoang_cach": "binary_sensor.x"}, {"khoang_cach": KC, "la": ["on"]}):
        with pytest.raises(ValueError):
            cb.dat("binary_sensor.c2a_sai", "x", sai)


def test_dung_lai_lich_su_bo_qua_so_khoang_cach_cu(cb, vk):
    """Kho còn sót bản ghi sự kiện khoảng cách cũ (trước khi gộp 5 phút): đọc nó là cả lịch sử mang một số
    cũ nằm ngoài vùng → cảm biến ghép thành «vắng» suốt 30 ngày."""
    _hoc_xong(vk)
    bt = {"va": [{"ma": PK}, {"khoang_cach": KC}]}
    cb.dat("binary_sensor.c2a_pk_kc2", "x", bt)
    _sk(KC, "4.9", 50.0)
    _sk(PK, "on", 100.0)
    _sk(PK, "off", 900.0)
    with _ro() as ro:
        assert cb.chuoi(ro, "binary_sensor.c2a_pk_kc2", 500.0, 1000.0) == [(500.0, "on"), (900.0, "off")]


def test_de_va_kiem_co_nguoi_nhan_khoang_cach():
    from services import co_nguoi_nha
    from services.de_luyen import chon_co_nguoi as bo
    d = next(x for x in bo.DE if x["ten"] == "khoang_cach_thay_loai_lay_bep_mo")
    de = co_nguoi_nha.de(d["uv"], d["ten_tb"], d["dan"])
    assert "G. KHOẢNG CÁCH" in de and f"{bo.KPK} | {bo.RPK} | dưới 3.66 m | 89%" in de
    bai = {"co_nguoi": {"hoac": [{"ma": bo.CPK}, {"va": [{"ma": bo.RPK}, {"khoang_cach": bo.KPK}]}]},
           "giu": None, "nhin": None, "roi_di": None, "chac": 0.8, "vi_sao": "x"}
    k = co_nguoi_nha.kiem(bai, d["uv"])
    from services import de_luyen
    assert isinstance(k, dict) and de_luyen.cham(k, d["dap_an"]) == []
    sai = {**bai, "co_nguoi": {"va": [{"ma": bo.RPK}, {"khoang_cach": "sensor.la"}]}}
    assert "không có trong đề" in co_nguoi_nha.kiem(sai, d["uv"])


def test_ti_le_bat_de_bo_cam_bien_ket():
    from services import vung_khoang_cach as vk
    assert vk.ti_le_bat([(0.0, "on")], 100.0, 200.0) == 1.0
    assert vk.ti_le_bat([(50.0, "off"), (150.0, "on"), (175.0, "off")], 100.0, 200.0) == 0.25
    assert vk.ti_le_bat([], 0.0, 10.0) == 0.0


def test_chi_khu_hay_bao_lay_moi_la_khu_ben_canh():
    from services import vung_khoang_cach as vk
    radar = [(0.0, "on")]
    cam = [(0.0, "off"), (100.0, "on")]                  # 0–99 s camera không thấy ai, 100–199 s thấy người
    bep = [(0.0, "on"), (100.0, "off")]                  # bếp có người đúng lúc camera phòng khách không thấy
    ngu = [(0.0, "off"), (85.0, "on"), (100.0, "off")]   # phòng ngủ có người 1/10 số lần
    ket = [(0.0, "on")]                                  # radar kẹt: báo bất kể camera thấy hay không
    kc = [(float(t), "4.4") for t in range(0, 200, 10)]
    assert vk.nguon_lay(kc, radar, [cam], {"bep": bep, "ngu": ngu, "ket": ket}) == ["bep"]
