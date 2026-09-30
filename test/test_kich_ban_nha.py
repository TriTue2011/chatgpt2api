"""Kịch bản nhà (30/09/2026): code bày sơ đồ + cảm biến + việc đang cài, bot dựng tình huống và xét
đúng/sai, chỗ chưa chắc hỏi chủ nhà TỪNG câu; câu trả lời vào sổ mô tả của sơ đồ nhà."""
from __future__ import annotations

import json

import pytest

from test.test_kich_hoat_nha import DEN, NGU, TT, kh  # noqa: F401 — fixture dùng chung


@pytest.fixture
def kb(kh, tmp_path, monkeypatch):  # noqa: F811
    from services import (boi_canh_nha, cam_bien_ghep, ha_client, hieu_thiet_bi_nha as ht, kich_ban_nha,
                          so_do_nha)
    kich_ban_nha._reset_for_tests(tmp_path / "kb.json")
    monkeypatch.setattr(so_do_nha, "_PATH", tmp_path / "sd.json")
    cam_bien_ghep._reset_for_tests(tmp_path / "cbg.json")
    monkeypatch.setattr(ha_client, "get_states", lambda: TT)
    monkeypatch.setattr(ha_client, "get_ha_area_index", lambda: {"entity_platform": {}})
    monkeypatch.setattr(boi_canh_nha, "phong_cua", lambda ma: "Phòng ngủ" if ma in (DEN, NGU) else "")
    monkeypatch.setattr(ht, "huong_dan", lambda ten: ("- `vao` — vào khu\n- `o_lai` — ở lại", "v1"))
    monkeypatch.setattr(ht, "_model", lambda: "m")
    tin: list[str] = []
    monkeypatch.setattr(ht, "bao_nhom", lambda t: tin.append(t) or 1)
    kich_ban_nha.tin = tin
    kh.dat_thiet_bi(DEN, bat=True, tat_khi_vang={"bat": True, "cam_bien": [NGU], "phut": 3})
    yield kich_ban_nha
    cam_bien_ghep._reset_for_tests(tmp_path / "cbg.json")


def _bai(hoi: list[str | None], loai: tuple[str, ...] = ("vao", "o_lai")) -> dict:
    return {"kich_ban": [{"loai": loai[i % len(loai)], "tinh_huong": f"tình huống {i}", "cam_bien_thay": "radar",
                          "nen": "tat", "hien_tai": "sai" if i == 0 else "khong_ro", "vi_sao": "", "hoi": h}
                         for i, h in enumerate(hoi)], "tom_tat": "đèn phòng ngủ thiếu"}


def test_de_bay_viec_dang_cai_va_kiem_bai(kb):
    uv = kb.do()
    ma = ["vao", "o_lai"]
    de = kb.de(uv, [], DEN, ma)
    assert de.startswith(f"THIẾT BỊ ĐANG XÉT: {DEN} | Đèn phòng ngủ | ở Phòng ngủ")
    assert "DANH MỤC phải đi qua (mỗi mã: tình huống hoặc khong_ap_dung): vao, o_lai" in de
    assert "Hiện diện phòng ngủ (sóng/chuyển động)" in de
    assert f"► {DEN} | Đèn phòng ngủ | ở Phòng ngủ" in de and "TẮT KHI VẮNG: Hiện diện phòng ngủ báo vắng liền 3–3 phút" in de
    assert "BẬT: chưa tự bật" in de
    k = kb.kiem(_bai([None]), DEN, ma)
    assert isinstance(k, dict) and k["kich_ban"][0]["thiet_bi"] == DEN and kb.thieu(k, ma) == ["o_lai"]
    assert "«loai»" in kb.kiem({"kich_ban": [{**_bai([None])["kich_ban"][0], "loai": "la"}]}, DEN, ma)
    assert "«nen»" in kb.kiem({"kich_ban": [{**_bai([None])["kich_ban"][0], "nen": "bat_nhe"}]}, DEN, ma)
    k = kb.kiem({**_bai([None]), "khong_ap_dung": [{"loai": "o_lai", "vi_sao": "không ai ngồi đây"}]}, DEN, ma)
    assert kb.thieu(k, ma) == []


def test_bo_sot_danh_muc_thi_hoi_lai_dung_ma_thieu(kb, monkeypatch):
    """Chủ máy 30/09/2026: "tránh bỏ sót … thiếu tình huống với chỉ 1 thiết bị" — thiếu mã nào hỏi lại mã đó."""
    from services import thoi_quen_nha
    de: list[str] = []
    tra = [_bai([None], loai=("vao",)), _bai([None, None])]
    monkeypatch.setattr(thoi_quen_nha, "_hoi_bot", lambda ht, m, h, d: de.append(d) or tra[len(de) - 1])
    k = kb.giai_mot(kb.do(), DEN, "- `vao` — x\n- `o_lai` — y", "m", [])
    assert len(de) == 2 and "EM ĐÃ BỎ SÓT các mã: o_lai" in de[1] and k["thieu"] == []
    assert kb.noi_cua("chung_cu") == "chung_cu" and kb.noi_cua("nha_dat") == "nha_pho" and kb.noi_cua("khong_ro") == ""


def test_sai_khuon_thi_hoi_lai_mot_lan_kem_loi(kb, monkeypatch):
    """Đo 30/09/2026 (Codex hết lượt, combo rơi về ChatGPT miễn phí): một tình huống thiếu `loai` là cả bài bị loại."""
    from services import thoi_quen_nha
    de: list[str] = []
    hong = _bai([None, None])
    hong["kich_ban"][0]["loai"] = None
    tra = [hong, _bai([None, None])]
    monkeypatch.setattr(thoi_quen_nha, "_hoi_bot", lambda ht, m, h, d: de.append(d) or tra[len(de) - 1])
    k = kb.giai_mot(kb.do(), DEN, "- `vao` — x\n- `o_lai` — y", "m", [])
    assert len(de) == 2 and "BÀI BỊ LOẠI VÌ SAI KHUÔN" in de[1] and "«loai»" in de[1]
    assert isinstance(k, dict) and k["thieu"] == []
    # Hỏi lại vẫn sai: trả lỗi như cũ, không hỏi lần ba.
    de.clear()
    tra = [hong, hong, hong]
    assert isinstance(kb.giai_mot(kb.do(), DEN, "- `vao` — x\n- `o_lai` — y", "m", []), str) and len(de) == 2


def test_khong_ap_dung_dat_nham_vao_tinh_huong_thi_chuyen_cho(kb):
    """Đo 30/09/2026: model ghi `hien_tai: "khong_ap_dung"` ngay trong kich_ban — ý đúng, sai chỗ."""
    bai = _bai([None, None])
    bai["kich_ban"][1].update(hien_tai="khong_ap_dung", vi_sao="phòng không có thú cưng")
    k = kb.kiem(bai, DEN, ["vao", "o_lai"])
    assert [x["loai"] for x in k["kich_ban"]] == ["vao"]
    assert k["khong_ap_dung"] == [{"thiet_bi": DEN, "loai": "o_lai", "vi_sao": "phòng không có thú cưng"}]
    assert kb.thieu(k, ["vao", "o_lai"]) == []


def test_hoi_tung_cau_tra_loi_vao_so_do_roi_hoi_cau_ke(kb, monkeypatch):
    from services import so_do_nha, thoi_quen_nha
    monkeypatch.setattr(thoi_quen_nha, "_hoi_bot", lambda ht, m, h, de: _bai(["Ngủ yên radar có giữ không?",
                                                                              "Có bật khi đi vệ sinh đêm?", None]))
    kq = kb.giai_va_bao()
    assert kq["ok"] and len(kb.tin) == 2
    assert "✗1" in kb.tin[0] and "✗ [1] tình huống 0 → nên tắt" in kb.tin[0]
    assert kb.tin[1].startswith("❓ KB1 (Đèn phòng ngủ — tình huống 0)") and "còn 1 câu" in kb.tin[1]
    assert kb.tra_loi("Có, radar giữ được") == "Dạ, em ghi KB1."
    assert kb.tin[-1].startswith("❓ KB2")
    assert any("chủ nhà: Có, radar giữ được" in x["noi_dung"] for x in so_do_nha.so()["mo_ta"])
    # Lần dựng sau: câu đã hỏi không hỏi lại, và đề có câu trả lời.
    de: list[str] = []
    monkeypatch.setattr(thoi_quen_nha, "_hoi_bot", lambda ht, m, h, d: de.append(d) or _bai(["Ngủ yên radar có giữ không?"]))
    kb.giai()
    assert "Ngủ yên radar có giữ không? → Có, radar giữ được" in de[0]
    assert [x["so"] for x in kb.so()["hoi"]] == [1, 2]
    monkeypatch.setattr(kb.threading, "Thread", lambda **k: type("T", (), {"start": lambda s: None})())
    assert "Hết câu hỏi" in kb.tra_loi("Không bật")
    assert kb.tra_loi("gì đó") == "Em không có câu hỏi tình huống nào đang chờ ạ."
    json.dumps(kb.so())


def test_cham_tinh_huong_vao_de_lan_sau(kb, monkeypatch):
    from services import thoi_quen_nha
    monkeypatch.setattr(thoi_quen_nha, "_hoi_bot", lambda ht, m, h, de: _bai([None, None]))
    kq = kb.giai()
    assert kb.cham(kq["id"], 1, False, cham_boi="claude", ghi_chu="số đo bác bỏ: 13% < 20%")
    assert not kb.cham(kq["id"], 9, False, cham_boi="claude", ghi_chu="x")
    with pytest.raises(ValueError):
        kb.cham(kq["id"], 1, True, cham_boi="ai_do", ghi_chu="")
    de: list[str] = []
    monkeypatch.setattr(thoi_quen_nha, "_hoi_bot", lambda ht, m, h, d: de.append(d) or _bai([None]))
    kb.giai()
    assert "F. LỜI CHẤM" in de[0] and "(giáo viên chấm SAI)" in de[0] and "13% < 20%" in de[0]
