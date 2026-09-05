"""Xác minh lệnh nhà: đo lại trạng thái thật, không tin lời pipeline.

Không có Home Assistant nào ở đây, nên `ha_client.get_states` được thay bằng một
bản giả trả về đúng những gì từng bài cần.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


def _ent(eid: str, state: str, ten: str = ""):
    return {"entity_id": eid, "state": state,
            "attributes": {"friendly_name": ten or eid}}


def _gia_states(monkeypatch, cac_lan: list[list[dict]]):
    """Mỗi lần gọi get_states trả về khung tiếp theo trong `cac_lan`."""
    from services import ha_client

    con = list(cac_lan)

    def _gia(use_cache: bool = True):
        return con.pop(0) if len(con) > 1 else con[0]

    monkeypatch.setattr(ha_client, "get_states", _gia)


def test_khong_doc_duoc_ha_thi_khong_can_thiep(monkeypatch):
    """Chưa cấu hình HA → rỗng, và người gọi giữ nguyên hành vi cũ."""
    from services import ha_xac_minh as hxm

    _gia_states(monkeypatch, [[]])
    assert hxm.chup() == {}
    assert hxm.doi_chieu({}) == []
    assert hxm.mo_ta([]) == ""


def test_bo_qua_cam_bien_doi_lien_tuc(monkeypatch):
    """Nhiệt độ nhích một độ không được tính là 'lệnh đã ăn'."""
    from services import ha_xac_minh as hxm

    _gia_states(monkeypatch, [[
        _ent("light.phong_khach", "off", "Đèn phòng khách"),
        _ent("sensor.nhiet_do", "27.4", "Nhiệt độ"),
    ]])
    truoc = hxm.chup()
    assert "light.phong_khach" in truoc
    assert "sensor.nhiet_do" not in truoc


def test_thay_doi_that_thi_thuat_lai_dung(monkeypatch):
    from services import ha_xac_minh as hxm

    truoc_ds = [_ent("light.phong_khach", "off", "Đèn phòng khách"),
                _ent("switch.quat", "off", "Quạt")]
    sau_ds = [_ent("light.phong_khach", "on", "Đèn phòng khách"),
              _ent("switch.quat", "off", "Quạt")]
    _gia_states(monkeypatch, [truoc_ds, sau_ds])
    truoc = hxm.chup()
    doi = hxm.doi_chieu(truoc)
    assert len(doi) == 1
    assert doi[0]["entity_id"] == "light.phong_khach"
    assert doi[0]["tu"] == "off" and doi[0]["sang"] == "on"
    assert "Đèn phòng khách: off → on" in hxm.mo_ta(doi)


def test_lenh_khong_an_thi_bao_khong_doi(monkeypatch):
    """Đây là ca quan trọng: pipeline báo xong mà thiết bị không nhúc nhích."""
    from services import ha_xac_minh as hxm

    ds = [_ent("light.phong_khach", "off", "Đèn phòng khách")]
    _gia_states(monkeypatch, [ds])
    monkeypatch.setattr(hxm, "SO_LAN_DOC", 2)
    monkeypatch.setattr(hxm, "GIAN_CACH", 0.0)
    assert hxm.doi_chieu(hxm.chup()) == []


def test_cho_thiet_bi_phan_hoi_cham(monkeypatch):
    """Zigbee báo trạng thái về chậm — đọc lại vài lần chứ đừng kết luận ngay."""
    from services import ha_xac_minh as hxm

    tat = [_ent("light.san", "off", "Đèn sân")]
    bat = [_ent("light.san", "on", "Đèn sân")]
    # chụp → lần đọc 1 vẫn off → lần đọc 2 mới on
    _gia_states(monkeypatch, [tat, tat, bat])
    monkeypatch.setattr(hxm, "GIAN_CACH", 0.0)
    doi = hxm.doi_chieu(hxm.chup())
    assert len(doi) == 1 and doi[0]["sang"] == "on"


def test_thuc_the_moi_khong_tinh_la_da_doi(monkeypatch):
    """HA nạp lại một integration làm xuất hiện thực thể mới — không phải do lệnh."""
    from services import ha_xac_minh as hxm

    truoc_ds = [_ent("light.a", "off", "Đèn A")]
    sau_ds = [_ent("light.a", "off", "Đèn A"), _ent("switch.moi", "on", "Ổ cắm mới")]
    _gia_states(monkeypatch, [truoc_ds, sau_ds])
    monkeypatch.setattr(hxm, "SO_LAN_DOC", 1)
    assert hxm.doi_chieu(hxm.chup()) == []
