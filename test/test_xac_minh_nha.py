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
