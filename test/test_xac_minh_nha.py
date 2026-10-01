"""Bot tự xác minh trước khi bật/tắt và tự chấm sau khi làm (chủ máy 01/10/2026): đề bày đủ nguồn,
kiểm biên chỉ nhận mã có trong đề, bộ đề luyện đúng khuôn."""
from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from services import xac_minh_nha as xm  # noqa: E402
from services.de_luyen import chon_xac_minh as bo  # noqa: E402

BAI = {"bat": {"xac_minh": [bo.CAM_PK], "kiem_lai": [], "lech_lich": [], "hoi": "khong"},
       "tat": {"xac_minh": [bo.CAM_PK, bo.KPK], "nha_vang": [], "lech_lich": [bo.CAM_B], "hoi": "khong"},
       "tu_cham": {"bat": [bo.RPK], "tat": [bo.CAM_PK]}, "chac": 0.8, "vi_sao": "x"}


@pytest.mark.parametrize("d", bo.DE, ids=[d["ten"] for d in bo.DE])
def test_de_luyen_dung_khuon(d):
    de = xm.de(d["uv"], d["ten_tb"], d["dan"])
    assert "A. THIẾT BỊ" in de and "B. NGUỒN" in de and "C. CAMERA" in de and "D. LỊCH" in de
    for k, v in d["dap_an"].items():
        for m in v if isinstance(v, list) and not k.endswith("_mot_trong") else []:
            assert m in de, f"đáp án nhắc {m} mà đề không có"


def test_kiem_nhan_ma_trong_de_va_loai_ma_la():
    uv = bo.DE[0]["uv"]
    k = xm.kiem(BAI, uv)
    assert isinstance(k, dict) and k["tat"]["xac_minh"] == [bo.CAM_PK, bo.KPK] and k["tat"]["nha_vang"] == []
    assert bo.cham_cho(k, bo.DE[0]["dap_an"]) == []
    assert "không có trong đề" in xm.kiem({**BAI, "tat": {**BAI["tat"], "xac_minh": ["Cam lạ"]}}, uv)
    assert "hoi phải là" in xm.kiem({**BAI, "bat": {**BAI["bat"], "hoi": "co"}}, uv)
    assert "tu_cham" in xm.kiem({k2: v for k2, v in BAI.items() if k2 != "tu_cham"}, uv)


def test_cham_bat_loi_dung_cho():
    uv = bo.DE[0]["uv"]
    k = xm.kiem({**BAI, "tat": {**BAI["tat"], "xac_minh": [bo.RB], "hoi": "khi_khong_ro",
                                "nha_vang": [bo.DTA]}}, uv)
    loi = bo.cham_cho(k, bo.DE[0]["dap_an"])
    assert f"tat.xac_minh thiếu {bo.CAM_PK}" in loi and f"tat.xac_minh không được có {bo.RB}" in loi
    assert any("tat.hoi phải là" in x for x in loi) and any("tat.nha_vang phải rỗng" in x for x in loi)


# ── B3: chạy thật ───────────────────────────────────────────────────────────
from test.test_kich_hoat_nha import DEN, NGU, TT, kh  # noqa: E402,F401

BAI_TAT = {"bat": {"xac_minh": ["Cam phòng ngủ"], "kiem_lai": ["Cam phòng ngủ"], "lech_lich": [], "hoi": "khong"},
           "tat": {"xac_minh": ["Cam phòng ngủ"], "nha_vang": [], "lech_lich": [], "hoi": "khong"},
           "tu_cham": {"bat": [], "tat": []}, "chac": 0.9, "vi_sao": ""}


@pytest.fixture
def xmn(tmp_path, monkeypatch):
    from services import camera_nha
    xm._reset_for_tests(tmp_path / "xm.json")
    monkeypatch.setattr(camera_nha, "danh_sach", lambda **k: [{"name": "Cam phòng ngủ"}])
    yield xm
    xm._reset_for_tests(tmp_path / "xm.json")


def _ap(xm_, tb=DEN, gia_tri=BAI_TAT):
    with xm_._khoa:
        xm_._nap()["bai"][tb] = [{"id": 1, "luc": 0, "gia_tri": gia_tri, "ket_qua": "cho"}]
    assert xm_.ap(tb) is None, "chưa chấm thì chưa áp"
    assert xm_.cham(tb, 1, True, cham_boi="claude")
    assert xm_.ap(tb) == gia_tri


def test_xac_minh_ba_trang_thai(kh, xmn, monkeypatch):
    tt = {x["entity_id"]: dict(x) for x in TT}
    monkeypatch.setattr(kh, "_trang_thai_ha", lambda: list(tt.values()))
    thay = {"kq": ""}
    monkeypatch.setattr(kh, "_nhin_lai", lambda cams, khu="": thay["kq"])
    assert xmn.xac_minh(["Cam phòng ngủ", NGU], "Phòng ngủ")[0] is False
    tt[NGU]["state"] = "on"
    assert xmn.xac_minh(["Cam phòng ngủ", NGU], "Phòng ngủ")[0] is True
    thay["kq"] = None
    assert xmn.xac_minh(["Cam phòng ngủ"], "Phòng ngủ")[0] is None, "camera không nhìn được = không biết"


def test_lech_lich_them_nguon(xmn, monkeypatch):
    from services import lich_sinh_hoat
    h = {"xac_minh": ["a"], "lech_lich": ["Cam phòng ngủ"]}
    monkeypatch.setattr(lich_sinh_hoat, "ca_nha", lambda loai, luc: False)
    assert xmn.nguon_luc(h, 0) == ["a"]
    monkeypatch.setattr(lich_sinh_hoat, "ca_nha", lambda loai, luc: loai == "vang")
    assert xmn.nguon_luc(h, 0) == ["a", "Cam phòng ngủ"]


def _hen_gia(kh, monkeypatch) -> list:
    hen: list = []

    class HenGia:
        def __init__(self, giay, ham, args=()):
            self.giay, self.ham, self.args = giay, ham, args
            hen.append(self)

        def start(self):
            pass

        def cancel(self):
            pass
    monkeypatch.setattr(kh.threading, "Timer", HenGia)
    return hen


def test_tat_khi_vang_hoan_khi_tu_xac_minh_thay_nguoi(kh, xmn, monkeypatch):
    tt = {x["entity_id"]: dict(x) for x in TT}
    tt[DEN]["state"] = "on"
    monkeypatch.setattr(kh, "_trang_thai_ha", lambda: list(tt.values()))
    from services import ha_client
    monkeypatch.setattr(ha_client, "get_state", lambda e: tt.get(e))
    hen = _hen_gia(kh, monkeypatch)
    thay = {"kq": "Cam phòng ngủ: 1 người"}
    monkeypatch.setattr(kh, "_nhin_lai", lambda cams, khu="": thay["kq"])
    kh.dat_thiet_bi(DEN, bat=True, tat_khi_vang={"bat": True, "cam_bien": [NGU], "phut": 3})
    _ap(xmn)
    kh._tat_vi_vang(DEN)
    assert kh.goi == [] and hen[-1].giay == kh.HEN_LAI, "camera còn thấy người: hoãn"
    thay["kq"] = ""
    kh._tat_vi_vang(DEN)
    assert kh.goi == [("switch", "turn_off", {"entity_id": DEN})], "không ai: tắt"


def test_kiem_lai_sau_khi_bat(kh, xmn, monkeypatch):
    tt = {x["entity_id"]: dict(x) for x in TT}
    tt[DEN]["state"] = "on"
    monkeypatch.setattr(kh, "_trang_thai_ha", lambda: list(tt.values()))
    from services import ha_client, thong_bao
    monkeypatch.setattr(ha_client, "get_state", lambda e: tt.get(e))
    canh_bao: list = []
    monkeypatch.setattr(thong_bao, "gui", lambda khoa, nd, *a, **k: canh_bao.append((khoa, nd)) or True)
    hen = _hen_gia(kh, monkeypatch)
    _ap(xmn)
    thay = {"kq": None}
    monkeypatch.setattr(kh, "_nhin_lai", lambda cams, khu="": thay["kq"])
    kh._kiem_lai(DEN, 0)
    assert kh.goi == [] and hen and hen[-1].args == (DEN, 1), "không nhìn được: hẹn kiểm lại"
    thay["kq"] = "Cam phòng ngủ: 1 người"
    kh._kiem_lai(DEN, 1)
    assert kh.goi == [] and len(hen) == 1, "thấy người thật: thôi kiểm"
    thay["kq"] = ""
    kh._kiem_lai(DEN, 2)
    assert kh.goi == [("switch", "turn_off", {"entity_id": DEN})]
    assert canh_bao and canh_bao[0][0] == "nha.canh_bao" and "báo ảo" in canh_bao[0][1]


def test_thiet_bi_nguy_hiem_khong_tu_xac_minh_de_tu_lam(kh, xmn):
    _ap(xmn, gia_tri={**BAI_TAT, "bat": {**BAI_TAT["bat"], "hoi": "luon"}})
    assert kh._xac_minh_truoc_hoi(DEN, "on", f"{NGU} có người vào", 0.0) is None
    assert kh._xac_minh_truoc_hoi(DEN, "off", f"{NGU} vắng", 0.0) is None


def test_radar_ghep_voi_khoang_cach_cua_chinh_no(kh, xmn, monkeypatch, tmp_path):
    """Radar phòng khách báo vì người đứng bếp (khoảng cách ngoài vùng) thì không tính là có người."""
    from services import ha_client, vung_khoang_cach as vk
    vk._reset_for_tests(tmp_path / "vk.json")
    vk._nap()["sensor.kc"] = {"radar": NGU, "dat": True, "huong": "duoi", "nguong": 3.66}
    tt = {x["entity_id"]: dict(x) for x in TT}
    tt[NGU]["state"] = "on"
    tt["sensor.kc"] = {"entity_id": "sensor.kc", "state": "4.5"}
    monkeypatch.setattr(kh, "_trang_thai_ha", lambda: list(tt.values()))
    monkeypatch.setattr(ha_client, "get_state", lambda e: tt.get(e))
    assert xmn.xac_minh([NGU], "Phòng ngủ")[0] is False
    tt["sensor.kc"]["state"] = "2.5"
    assert xmn.xac_minh([NGU], "Phòng ngủ")[0] is True
    tt["sensor.kc"]["state"] = "0"
    assert xmn.xac_minh([NGU], "Phòng ngủ")[0] is True, "không đo được khoảng cách: tin radar"
    vk._reset_for_tests(tmp_path / "vk.json")


def test_nguy_hiem_dung_dau_vao_cua_chot_luc_chay():
    """«Đèn CỬA sổ» không phải khoá cửa: đề phải nhận thiết bị nguy hiểm bằng ĐÚNG đầu vào chốt lúc chạy dùng."""
    from services import du_doan_nha as dd, kich_hoat_nha as kh_
    assert not dd._cam_tu_lam(kh_._ten_tt("light.phong_khach_l1", "on"))
    assert dd._cam_tu_lam(kh_._ten_tt("switch.binh_nong_lanh", "on"))


def test_xac_minh_bat_nhin_lai_mot_nhip_truoc_khi_ket_luan_vang(kh, xmn, monkeypatch):
    """17:33 01/10/2026: mở cửa, Cam PK chưa thấy người vừa bước vào → chặn «không bật, không hỏi»; 2 giây sau Frigate
    thấy người, người tự bật. Một lần nhìn không thấy lúc người VỪA vào chưa phải vắng."""
    monkeypatch.setattr(kh, "xet", lambda *a, **k: {"lam": "hoi"})
    monkeypatch.setattr(kh.time, "sleep", lambda s: None)
    _ap(xmn)
    lan = iter(["", "Cam phòng ngủ: 1 người"])
    monkeypatch.setattr(kh, "_nhin_lai", lambda cams, khu="": next(lan))
    assert kh._xac_minh_truoc_hoi(DEN, "on", f"{NGU} có người vào", 0.0)[1] is True
    monkeypatch.setattr(kh, "_nhin_lai", lambda cams, khu="": "")
    assert kh._xac_minh_truoc_hoi(DEN, "on", f"{NGU} có người vào", 0.0)[1] is False, "nhìn lại vẫn trống: vắng"


def test_chu_may_sua_bai_tren_web_ap_ngay(kh, xmn, monkeypatch):
    """01/10/2026: chủ máy chỉnh bài xác minh trên web — kiểm như bài bot (mã phải có trong đề), áp ngay."""
    monkeypatch.setattr(xmn, "do", lambda tb: {"nguon": [{"ma": NGU, "loai": "hien_dien", "ghi_chu": "Radar"}],
                                               "camera": [{"ten": "Cam phòng ngủ", "thay": ["Phòng ngủ"]}],
                                               "nguy_hiem": False})
    bai = {**BAI_TAT, "tat": {**BAI_TAT["tat"], "xac_minh": ["Cam phòng ngủ", NGU]}}
    kq = xmn.sua(DEN, bai)
    assert xmn.ap(DEN)["tat"]["xac_minh"] == ["Cam phòng ngủ", NGU] and kq["id"] >= 1
    assert xmn.so()["bai"][DEN][-1]["cham_boi"] == "chu_may"
    with pytest.raises(ValueError):
        xmn.sua(DEN, {**bai, "bat": {**bai["bat"], "xac_minh": ["Cam bếp"]}})
    lc = xmn.lua_chon(DEN)
    assert {x["ma"] for x in lc["nguon"]} == {NGU, "Cam phòng ngủ"} and lc["ap"] == xmn.ap(DEN)
