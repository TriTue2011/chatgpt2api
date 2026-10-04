"""Bộ chấm của đề luyện `chuyen_truong_hop` (nhà giả) — offline: bài mẫu đúng qua, bài mắc đúng các lỗi thật thì bị
bắt. Không gọi model."""
from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.de_luyen import chuyen_truong_hop as bo  # noqa: E402


def _d(ten):
    return next(x for x in bo.DE if x["ten"] == ten)


def _l(so, nen, khi, neu=None, xm=False):
    return {"so": so, "nen": nen, "khi": khi, "neu": neu or [], "xac_minh": xm}


def _cham(ten, luat):
    d = _d(ten)
    k = bo.kiem({"luat": luat, "khong_chuyen_duoc": []}, d["uv"])
    return bo.cham_cho(k, d["dap_an"])


def test_de_dung_khuon_nha_that_va_du_muc():
    d = _d("nhieu_va_trung")
    de = bo.de_cho(d)
    assert "A. TRƯỜNG HỢP" in de and "B3." in de and "B4." in de and "B2." in de and "C. LỊCH" in de


def test_quat_bat_luc_mo_cua_bi_bat_loi():
    sai = _cham("quat_o_lai", [_l(1, "bat", [f"{bo.CUA} có người vào"]), _l(2, "khong_lam", [f"{bo.CUA} có người vào"]),
                               _l(3, "tat", [f"{bo.RK} vắng"])])
    assert any("ở lại" in e for e in sai)
    dung = _cham("quat_o_lai", [_l(1, "bat", [f"{bo.RK} ở lại 180 giây"]), _l(2, "khong_lam", [f"{bo.CUA} có người vào"]),
                                _l(3, "tat", [f"{bo.RK} vắng"])])
    assert dung == []


def test_binh_nong_lanh_khong_duoc_tu_bat():
    assert any("nguy hiểm" in e for e in _cham("binh_nong_lanh", [_l(1, "bat", [f"{bo.CUA} có người vào"]),
                                                                    _l(2, "hoi", [f"{bo.RK} vắng"])]))
    assert _cham("binh_nong_lanh", [_l(1, "hoi", [f"{bo.CUA} có người vào"]), _l(2, "hoi", [f"{bo.RK} vắng"])]) == []


def test_den_tran_chi_nghe_cua_bi_bat_loi():
    sai = _cham("den_tran_moi_duong_vao", [_l(1, "bat", [f"{bo.CUA} có người vào"]),
                                           _l(2, "bat", [f"{bo.CUA} có người vào"]), _l(3, "tat", [f"{bo.RK} vắng"])])
    assert any("không luật BẬT nào nghe" in e for e in sai)


def test_radar_tren_bi_bat_loi_va_nguoc_cap_trung_bi_bat():
    assert any("radar 0" in e for e in _cham("radar_khong", [_l(1, "tat", [f"{bo.RK} vắng"], [{"ma": bo.KK, "tren": 3.5}])]))
    sai = _cham("nhieu_va_trung", [_l(1, "bat", [f"{bo.RK} ở lại 180 giây"],
                                      [{"ma": bo.CK, "la": "on"}, {"ma": bo.CK2, "la": "on", "phu_dinh": True}]),
                                   _l(2, "tat", [f"{bo.RK} vắng"])])
    assert any("cùng tín hiệu" in e for e in sai) or any("mâu thuẫn" in e for e in sai)


def test_dua_vao_cam_bien_nhieu_khong_kem_gi_bi_bat():
    sai = _cham("nhieu_va_trung", [_l(1, "bat", [f"{bo.RK} ở lại 180 giây"]), _l(2, "tat", [f"{bo.RK} vắng"])])
    assert any("NHIỄU" in e for e in sai)
    dung = _cham("nhieu_va_trung", [_l(1, "bat", [f"{bo.RK} ở lại 180 giây"], xm=True), _l(2, "tat", [f"{bo.RK} vắng"], xm=True)])
    assert dung == []
