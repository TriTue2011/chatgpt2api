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
    # Một tình huống hỏng thì bỏ riêng nó; mã bị hụt («vao») đi lượt bổ sung mã bỏ sót.
    assert len(de) == 2 and "EM ĐÃ BỎ SÓT các mã: vao" in de[1]
    assert isinstance(k, dict) and k["thieu"] == []
    # CẢ BÀI sai khuôn: hỏi lại MỘT lần kèm lỗi; vẫn sai thì trả lỗi, không hỏi lần ba.
    de.clear()
    toan_hong = _bai([None, None])
    for x in toan_hong["kich_ban"]:
        x["loai"] = None
    tra = [toan_hong, _bai([None, None])]
    k = kb.giai_mot(kb.do(), DEN, "- `vao` — x\n- `o_lai` — y", "m", [])
    assert len(de) == 2 and "BÀI BỊ LOẠI VÌ SAI KHUÔN" in de[1] and "«loai»" in de[1] and k["thieu"] == []
    de.clear()
    tra = [toan_hong, toan_hong, toan_hong]
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


def test_de_bay_khoang_cach_do_sang_dem_nguoi_loa_theo_dau_hieu_HA(kb, monkeypatch):
    """Chủ máy 30/09/2026: tình huống cần khoảng cách radar, đếm người camera, loa / loa camera — nhận ra theo dấu
    hiệu tích hợp khai (device_class, đơn vị, cờ tính năng, sổ thiết bị), không theo tên, để nhà nào cũng dùng được."""
    from services import boi_canh_nha, ha_client
    them = [
        {"entity_id": "binary_sensor.radar_pk", "state": "on", "attributes": {"device_class": "occupancy", "friendly_name": "Radar PK"}},
        {"entity_id": "sensor.radar_pk_kc", "state": "2.1", "attributes": {"device_class": "distance", "unit_of_measurement": "m", "friendly_name": "Radar PK khoảng cách"}},
        {"entity_id": "sensor.radar_pn_target_distance", "state": "376", "attributes": {"unit_of_measurement": "cm", "friendly_name": "Radar PN Target distance"}},
        {"entity_id": "sensor.dien_thoai_kc", "state": "5", "attributes": {"device_class": "distance", "unit_of_measurement": "km", "friendly_name": "Điện thoại cách nhà"}},
        {"entity_id": "sensor.lux_pk", "state": "30", "attributes": {"device_class": "illuminance", "friendly_name": "Độ sáng PK"}},
        {"entity_id": "sensor.cam_pk_person_count", "state": "2", "attributes": {"unit_of_measurement": "objects", "friendly_name": "Cam PK đếm người"}},
        {"entity_id": "media_player.loa_cam", "state": "idle", "attributes": {"supported_features": 1048576 | 512, "friendly_name": "Loa cam cửa"}},
        {"entity_id": "media_player.tivi", "state": "off", "attributes": {"supported_features": 512, "friendly_name": "Tivi"}},
    ]
    monkeypatch.setattr(ha_client, "get_states", lambda: TT + them)
    monkeypatch.setattr(ha_client, "get_ha_area_index", lambda: {"entity_platform": {}, "entity_device_ids": {
        "binary_sensor.radar_pk": ["z:1"], "sensor.radar_pk_kc": ["z:1"], "sensor.radar_pn_target_distance": ["z:1"], "sensor.dien_thoai_kc": ["app:2"],
        "media_player.loa_cam": ["cam:9"], "camera.cam_cua": ["cam:9"]}})
    monkeypatch.setattr(boi_canh_nha, "phong_cua", lambda ma: "Phòng ngủ" if ma in (DEN, NGU) else "Phòng khách")
    uv = kb.do()
    pk = " | ".join(uv["phong"]["Phòng khách"])
    assert "Radar PK khoảng cách (KHOẢNG CÁCH người tới radar, m)" in pk
    assert "Radar PN Target distance (KHOẢNG CÁCH người tới radar, cm)" in pk, "radar Zigbee chỉ khai đơn vị, không device_class"
    assert "Điện thoại cách nhà" not in pk, "khoảng cách không cùng thiết bị radar thì không phải radar"
    assert "Độ sáng PK (độ sáng)" in pk and "Cam PK đếm người (ĐẾM số vật thể camera thấy)" in pk
    assert uv["loa"] == ["Loa cam cửa (ở Phòng khách — loa TRÊN CAMERA)"], "tivi không có cờ thông báo thì không là loa"
    de = kb.de(uv, [], DEN, ["vao"])
    assert "B4. LOA đọc được thông báo:\n- Loa cam cửa" in de and "B5. BOT NHÌN ĐƯỢC GÌ:" in de
    assert "noi" in kb.NEN


def test_tinh_huong_sai_khuon_bo_rieng_no_khong_loai_ca_bai(kb):
    """Đo 30/09/2026: 5/41 bài bị loại cả bài chỉ vì MỘT tình huống thiếu `loai` — nay bỏ riêng tình huống đó."""
    ma = ["vao", "o_lai"]
    tot = _bai([None])["kich_ban"][0]
    k = kb.kiem({"kich_ban": [tot, {**tot, "loai": None}, {**tot, "loai": "o_lai", "nen": "bat_nhe"}]}, DEN, ma)
    assert isinstance(k, dict) and [x["loai"] for x in k["kich_ban"]] == ["vao"] and k["sai_khuon"] == 2
    assert kb.thieu(k, ma) == ["o_lai"], "mã bị hụt do bỏ tình huống sai khuôn → lượt bổ sung sẽ hỏi lại"


def test_danh_muc_dai_chia_nhieu_luot_moi_luot_it_ma(kb, monkeypatch):
    """Đo 30/09/2026: 22 mã một lượt tụt 27/34 → 19/34 — chia danh mục, mỗi lượt ≤ MA_MOI_LUOT mã, gộp lại."""
    from services import thoi_quen_nha
    ma = [f"ma_{chr(97 + i)}" for i in range(25)]
    huong = "\n".join(f"- `{m}` — x" for m in ma)
    de: list[str] = []

    def tra(ht, m, h, d):
        de.append(d)
        dong = next(x for x in d.splitlines() if x.startswith("DANH MỤC"))
        cua = dong.rsplit("): ", 1)[1].split(", ")
        return {"kich_ban": [{"loai": c, "tinh_huong": "t", "nen": "giu", "hien_tai": "dung"} for c in cua],
                "tom_tat": f"phần {len(de)}"}
    monkeypatch.setattr(thoi_quen_nha, "_hoi_bot", tra)
    k = kb.giai_mot(kb.do(), DEN, huong, "m", [])
    assert len(de) == 3 and all(len(x.splitlines()[1].rsplit("): ", 1)[1].split(", ")) <= kb.MA_MOI_LUOT for x in de)
    assert sorted(x["loai"] for x in k["kich_ban"]) == sorted(ma) and k["thieu"] == []
    assert "phần 1" in k["tom_tat"] and "phần 3" in k["tom_tat"]


def test_de_bay_bai_tu_xac_minh_dang_ap(kb, tmp_path, monkeypatch):
    """01/10/2026: đề thiếu bài xác minh nên bot kết luận đèn trần "cần xử lý cảm biến nhiễu bằng camera" — việc
    bot đã làm (kiểm lại bằng camera mỗi 2 phút)."""
    from services import camera_nha, xac_minh_nha as xm
    xm._reset_for_tests(tmp_path / "xm.json")
    monkeypatch.setattr(camera_nha, "danh_sach", lambda **k: [{"name": "Cam phòng ngủ"}])
    with xm._khoa:
        xm._nap()["bai"][DEN] = [{"id": 1, "luc": 0, "ket_qua": "dung", "gia_tri": {
            "bat": {"xac_minh": ["Cam phòng ngủ"], "kiem_lai": ["Cam phòng ngủ"], "lech_lich": [], "hoi": "khong"},
            "tat": {"xac_minh": ["Cam phòng ngủ", NGU], "nha_vang": [], "lech_lich": [], "hoi": "khong"}}}]
    de = kb.de(kb.do(), [], DEN, ["vao", "o_lai"])
    assert "TỰ XÁC MINH trước khi bật (lúc luật định hỏi anh): nhìn Cam phòng ngủ — thấy người thì tự bật, " \
           "không thấy ai thì không bật, không hỏi" in de
    assert "KIỂM LẠI sau khi bật: mỗi 2 phút nhìn Cam phòng ngủ" in de
    assert "TỰ XÁC MINH trước khi tắt khi vắng: Cam phòng ngủ, Hiện diện phòng ngủ còn thấy người" in de
    xm._reset_for_tests(tmp_path / "xm2.json")
