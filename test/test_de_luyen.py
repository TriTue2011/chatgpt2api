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


_NOI = ("chung_cu", "nha_pho", "biet_thu", "van_phong", "xuong")
_KB = [(n, d) for n in _NOI for d in __import__(f"services.de_luyen.sinh_kich_ban_{n}", fromlist=["DE"]).DE]


@pytest.fixture
def huong_repo(monkeypatch):
    """Hướng dẫn đọc thẳng bản gốc trong repo (không đụng bản chạy thật trong DATA_DIR)."""
    from pathlib import Path

    from services import hieu_thiet_bi_nha as ht
    goc = Path(__file__).resolve().parents[1] / "services" / "huong_dan_hoc"
    monkeypatch.setattr(ht, "huong_dan", lambda ten="": ((goc / f"{ten}.md").read_text(encoding="utf-8"), ten))


@pytest.mark.parametrize("n,d", _KB, ids=[f"{n}:{d['ten']}" for n, d in _KB])
def test_de_tinh_huong_dung_khuon(n, d, huong_repo):
    """Bộ đề dựng tình huống theo NƠI: đề đúng khuôn (thiết bị đang xét, danh mục chung + riêng của nơi), thiết bị
    trong đáp án có trong đề, bộ chấm nhận một bài làm đúng và bắt bài bỏ sót."""
    from services import kich_ban_nha
    from services.de_luyen import _kich_ban as kb
    assert d["uv"]["noi"] == n
    huong, _ = kich_ban_nha.huong_dan_cho(n)
    ma = kich_ban_nha.danh_muc(huong)
    assert "vao" in ma and "an_ninh" in ma and len(ma) > 13, "danh mục = chung + riêng của nơi"
    de = kb.de_cho(d)
    assert "THIẾT BỊ ĐANG XÉT" in de and "DANH MỤC phải đi qua" in de and "B2. AI Ở NHÀ" in de
    for y in d["dap_an"].get("phai_co") or []:
        assert y["thiet_bi"] in d["uv"]["thiet_bi"]
        for m in ([y["loai"]] if isinstance(y.get("loai"), str) else y.get("loai") or []):
            assert m in ma, f"{d['ten']}: đáp án nhắc mã {m} không có trong danh mục của {n}"

    def mot(v, mac_dinh):
        return (v[0] if isinstance(v, list) else v) if v else mac_dinh
    bai = {"kich_ban": [{"thiet_bi": y["thiet_bi"], "loai": mot(y.get("loai"), "vao"), "tinh_huong": y["tu"][0],
                         "cam_bien_thay": "", "nen": mot(y.get("nen"), "bat"), "hien_tai": mot(y.get("hien_tai"), "sai"),
                         "vi_sao": "", "hoi": None} for y in d["dap_an"].get("phai_co") or []]
           + [{"thiet_bi": next(iter(d["uv"]["thiet_bi"])), "loai": "rieng", "tinh_huong": "hỏi", "cam_bien_thay": "",
               "nen": "hoi", "hien_tai": "khong_ro", "vi_sao": "", "hoi": nhom[0]}
              for nhom in d["dap_an"].get("phai_hoi_ve") or []],
           "khong_ap_dung": [], "thieu": {}}
    assert kb.cham_cho(bai, d["dap_an"]) == []
    assert kb.cham_cho({"kich_ban": [], "khong_ap_dung": [], "thieu": {}}, d["dap_an"]) != []
    if d["dap_an"].get("phu_du"):
        assert kb.cham_cho({**bai, "thieu": {"x": ["vao"]}}, d["dap_an"]) != [], "bỏ sót danh mục là sai"
