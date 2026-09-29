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
        for m in (v if isinstance(v, (list, dict)) and not k.endswith("_mot_trong") else []):
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
    assert de_luyen.cham({**bai, "roi_khi_o_duoi": 3}, {"roi_khi_o_duoi": 3}) == []
    assert de_luyen.cham({**bai, "roi_khi_o_duoi": None}, {"roi_khi_o_duoi": 3}) == [
        "roi_khi_o_duoi phải là 3, bài viết None"]
    assert de_luyen.cham({**bai, "roi_khi_o_duoi": 1}, {"roi_khi_o_duoi_mot_trong": [1, 3]}) == []
    assert de_luyen.cham({**bai, "roi_khi_o_duoi": 10}, {"roi_khi_o_duoi_mot_trong": [1, 3]}) != []


@pytest.mark.parametrize("d", __import__("services.de_luyen.sinh_kich_ban", fromlist=["DE"]).DE,
                         ids=lambda d: d["ten"])
def test_de_tinh_huong_dung_khuon(d):
    """Bộ đề dựng tình huống (mọi kiểu nơi chốn): đề đúng khuôn tầng kịch bản, thiết bị trong đáp án có trong đề,
    và bộ chấm nhận một bài làm đúng."""
    from services import kich_ban_nha
    from services.de_luyen import sinh_kich_ban as sk
    de = sk.de_cho(d)
    assert "C. THIẾT BỊ" in de and "B2. AI Ở NHÀ" in de
    for y in d["dap_an"].get("phai_co") or []:
        assert y["thiet_bi"] in de
    bai = {"kich_ban": [{"thiet_bi": y["thiet_bi"], "tinh_huong": y["tu"][0], "cam_bien_thay": "",
                         "nen": y.get("nen", "bat"), "hien_tai": y.get("hien_tai", "sai"), "vi_sao": "", "hoi": None}
                        for y in d["dap_an"].get("phai_co") or []]
           + [{"thiet_bi": next(iter(d["uv"]["thiet_bi"])), "tinh_huong": "hỏi", "cam_bien_thay": "", "nen": "hoi",
               "hien_tai": "khong_ro", "vi_sao": "", "hoi": nhom[0]} for nhom in d["dap_an"].get("phai_hoi_ve") or []]}
    k = kich_ban_nha.kiem(bai, d["uv"])
    assert isinstance(k, dict) and sk.cham_cho(k, d["dap_an"]) == []
    assert sk.cham_cho({"kich_ban": []}, d["dap_an"]) != []
