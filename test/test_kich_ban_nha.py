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
    monkeypatch.setattr(ht, "huong_dan", lambda ten: ("HƯỚNG DẪN", "v1"))
    monkeypatch.setattr(ht, "_model", lambda: "m")
    tin: list[str] = []
    monkeypatch.setattr(ht, "bao_nhom", lambda t: tin.append(t) or 1)
    kich_ban_nha.tin = tin
    kh.dat_thiet_bi(DEN, bat=True, tat_khi_vang={"bat": True, "cam_bien": [NGU], "phut": 3})
    yield kich_ban_nha
    cam_bien_ghep._reset_for_tests(tmp_path / "cbg.json")


def _bai(hoi: list[str | None]) -> dict:
    return {"kich_ban": [{"thiet_bi": DEN, "tinh_huong": f"tình huống {i}", "cam_bien_thay": "radar",
                          "nen": "tat", "hien_tai": "sai" if i == 0 else "khong_ro", "vi_sao": "", "hoi": h}
                         for i, h in enumerate(hoi)], "tom_tat": "đèn phòng ngủ thiếu"}


def test_de_bay_viec_dang_cai_va_kiem_bai(kb):
    uv = kb.do()
    de = kb.de(uv, [])
    assert "Hiện diện phòng ngủ (sóng/chuyển động)" in de
    assert f"- {DEN} | Đèn phòng ngủ | ở Phòng ngủ" in de and "TẮT KHI VẮNG: Hiện diện phòng ngủ báo vắng liền 3–3 phút" in de
    assert "BẬT: chưa tự bật" in de
    assert isinstance(kb.kiem(_bai([None]), uv), dict)
    assert "không có trong đề" in kb.kiem({"kich_ban": [{**_bai([None])["kich_ban"][0], "thiet_bi": "light.la"}]}, uv)
    assert "«nen»" in kb.kiem({"kich_ban": [{**_bai([None])["kich_ban"][0], "nen": "bat_nhe"}]}, uv)


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
