"""Bộ đề luyện dựng được đề đúng khuôn, đáp án chỉ nhắc mã có trong đề, và bộ chấm chấm đúng."""
from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from services import co_nguoi_nha, de_luyen  # noqa: E402
from services.de_luyen import chon_co_nguoi as bo  # noqa: E402


@pytest.mark.parametrize("d", bo.DE, ids=[d["ten"] for d in bo.DE])
def test_de_dung_khuon_va_dap_an_co_trong_de(d):
    de = co_nguoi_nha.de(d["uv"], d["ten_tb"], d["dan"])
    assert "A. CẢM BIẾN" in de and "F. RỜI KHU" in de and "E. CAMERA" in de
    for k, v in d["dap_an"].items():
        for m in (v or []):
            assert m in de, f"{d['ten']}: đáp án {k} nhắc {m} không có trong đề"


def test_cham():
    R, B, L = bo.RPK, bo.RB, bo.LAP
    bai = {"co_nguoi": {"hoac": [{"ma": bo.CPK}, {"va": [{"ma": R}, {"khong": {"ma": B}}]}]},
           "giu": {"va": [{"ma": L, "la": ["home"]}]}, "nhin": ["Cam phòng khách"], "roi_di": None}
    assert de_luyen.cham(bai, {"co_nguoi_phai_co": [R], "co_nguoi_phu_dinh": [B], "roi_di": None,
                               "giu_phai_co": {L: ["home"]}, "nhin_phai_co": ["Cam phòng khách"]}) == []
    assert de_luyen.cham(bai, {"giu": None}) == ["giu phải là null"]
    assert de_luyen.cham(bai, {"co_nguoi_phu_dinh_khong": [B]}) == [f"co_nguoi không được loại lây {B}"]
    assert de_luyen.cham(bai, {"giu_phai_co": {L: ["not_home"]}})[0].startswith("giu:")
    assert de_luyen.cham("model lỗi", {}) == ["bài bị loại: model lỗi"]
