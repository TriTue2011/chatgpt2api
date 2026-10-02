"""Sự cố thiết bị bot tự điều khiển — báo kèm NGUYÊN NHÂN (chủ máy 02/10/2026).

Ca thật cùng ngày: 09:56 quạt phòng khách tạo lại dưới mã mới, mã cũ thành thực thể bỏ lại (restored, unavailable);
16:17 người về, luật định bật quạt mà chỉ ghi nhật ký. Không gọi HA thật."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import ha_client, su_co_thiet_bi as sc  # noqa: E402

_TZ = timezone(timedelta(hours=7))


def _luc(h: int, m: int) -> str:
    return datetime(2026, 10, 2, h, m, tzinfo=_TZ).isoformat()


def _nen(n=40):
    """Thực thể bình thường, mốc đổi rải rác (nhà thật: ngoài lúc HA khởi động lại không phút nào quá 9%)."""
    return [_s(f"sensor.nen_{i}", "1", datetime(2026, 10, 1, i % 24, i % 60, tzinfo=_TZ).isoformat()) for i in range(n)]


def _s(ma, tt, doi, ten="", **a):
    return {"entity_id": ma, "state": tt, "last_changed": doi, "last_updated": doi,
            "attributes": {"friendly_name": ten or ma, **a}}


@pytest.fixture
def ha(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "_FILE", tmp_path / "su_co.json")
    nha: dict = {"states": [], "idx": {"entity_platform": {}, "entity_device_ids": {}, "entity_mirror": {}}}
    monkeypatch.setattr(ha_client, "get_states", lambda use_cache=True: list(nha["states"]))
    monkeypatch.setattr(ha_client, "get_state",
                        lambda ma: next((x for x in nha["states"] if x["entity_id"] == ma), None))
    monkeypatch.setattr(ha_client, "get_ha_area_index", lambda use_cache=True: nha["idx"])
    monkeypatch.setattr(sc, "_gia_tri_cuoi", lambda ma: nha.get("cuoi", {}))
    return nha


def test_thuc_the_bo_lai_chi_ra_thuc_the_moi(ha):
    ha["idx"]["area_names"] = {"phong khach": "Phòng khách", "phong ngu": "Phòng ngủ"}
    ha["states"] = [_s("fan.phong_khach", "unavailable", _luc(9, 56), "Quạt phòng khách", restored=True),
                    _s("fan.ir_quat_phong_khach", "off", _luc(9, 56), "ir quat Phòng khách"),
                    _s("fan.phong_ngu", "off", _luc(9, 56), "Quạt phòng ngủ"),
                    _s("light.bep", "on", _luc(7, 0))]
    cd = sc.chan_doan("fan.phong_khach")
    assert cd["nguyen_nhan"] == "thực thể bị bỏ lại"
    assert "fan.ir_quat_phong_khach" in cd["chi_tiet"] and "09:56" in cd["chi_tiet"]


def test_khong_con_trong_ha_va_ha_khong_tra_loi(ha):
    ha["states"] = [_s("light.bep", "on", _luc(7, 0))]
    assert sc.chan_doan("fan.phong_khach")["nguyen_nhan"] == "thực thể không còn"
    ha["states"] = []
    assert sc.chan_doan("fan.phong_khach")["nguyen_nhan"] == "mất kết nối tới Home Assistant"


def test_nhieu_tich_hop_cung_mat_la_mang_hoac_ha_khoi_dong_lai(ha):
    ha["states"] = [_s(f"sensor.x{i}", "unavailable", _luc(9, 0)) for i in range(25)] + _nen(200)
    ha["idx"]["entity_platform"] = {f"sensor.x{i}": ["mqtt", "esphome", "tuya"][i % 3] for i in range(25)}
    ha["states"].append(_s("light.bep", "unavailable", _luc(9, 1)))
    assert sc.chan_doan("light.bep")["nguyen_nhan"] == "mất mạng / HA khởi động lại"


def test_ca_tich_hop_mat_la_hub(ha):
    ha["states"] = [_s("switch.a", "unavailable", _luc(9, 0)), _s("switch.b", "unavailable", _luc(9, 2)),
                    _s("switch.c", "unavailable", _luc(9, 1)), _s("light.dien_thoai", "unavailable", _luc(3, 0))
                    ] + _nen()
    ha["idx"]["entity_platform"] = {"switch.a": "mqtt", "switch.b": "mqtt", "switch.c": "mqtt",
                                    "light.dien_thoai": "mobile_app"}
    ha["idx"]["entity_device_ids"] = {"switch.a": ["z:1"], "switch.b": ["z:2"], "switch.c": ["z:3"]}
    cd = sc.chan_doan("switch.a")
    assert cd["nguyen_nhan"] == "cả tích hợp mqtt mất kết nối" and "3 thiết bị" in cd["chi_tiet"]


def test_rieng_thiet_bi_qua_cap_guong_kem_song_yeu(ha):
    """Đèn bọc công tắc Zigbee: tích hợp và cảm biến sóng nằm ở công tắc gốc."""
    ha["states"] = [_s("light.phong_khach_l4", "unavailable", _luc(9, 0)),
                    _s("switch.phong_khach_l4", "unavailable", _luc(9, 0)),
                    _s("sensor.0xa4_linkquality", "unavailable", _luc(9, 0)),
                    _s("switch.khac", "on", _luc(8, 0))] + _nen()
    ha["idx"] = {"entity_platform": {"light.phong_khach_l4": "switch_as_x", "switch.phong_khach_l4": "mqtt",
                                     "sensor.0xa4_linkquality": "mqtt", "switch.khac": "mqtt"},
                 "entity_mirror": {"light.phong_khach_l4": "switch.phong_khach_l4"},
                 "entity_device_ids": {"switch.phong_khach_l4": ["z:a4"], "sensor.0xa4_linkquality": ["z:a4"],
                                       "switch.khac": ["z:b"]}}
    ha["cuoi"] = {"sensor.0xa4_linkquality": "18"}
    cd = sc.chan_doan("light.phong_khach_l4")
    assert cd["nguyen_nhan"] == "thiết bị mất kết nối"
    assert "18/255" in cd["chi_tiet"] and "2 thực thể" in cd["chi_tiet"]


def test_ha_khoi_dong_lai_ma_thiet_bi_chua_ve(ha):
    """Đo 02/10/2026: 66% thực thể cùng mốc 09:56 sau khi HA khởi động lại."""
    ha["states"] = [_s(f"sensor.k{i}", "1", _luc(9, 56)) for i in range(30)] + _nen(10) + [
        _s("switch.ariston_power", "unavailable", _luc(9, 56))]
    ha["idx"]["entity_platform"] = {"switch.ariston_power": "ariston"}
    cd = sc.chan_doan("switch.ariston_power")
    assert cd["nguyen_nhan"] == "chưa kết nối lại sau khi HA khởi động lại" and "ariston" in cd["chi_tiet"]


def test_bo_lai_khong_goi_y_nham_khi_ten_khac(ha):
    """Sau khởi động lại mọi thực thể «sinh cùng lúc» — đo 02/10/2026 từng gợi ý nhầm «Aptomat tổng Dòng»."""
    ha["idx"]["area_names"] = {"phong khach": "Phòng khách", "bep": "Bếp"}
    ha["states"] = [_s("sensor.tv_phong_khach_kc", "unavailable", _luc(9, 56), "TV phòng khách 2F34", restored=True),
                    _s("sensor.aptomat_tong_leakage_current", "0", _luc(9, 56), "Aptomat tổng Dòng"),
                    _s("sensor.cam_phong_khach", "0", _luc(9, 56), "Cam phong khach")]
    cd = sc.chan_doan("sensor.tv_phong_khach_kc")
    assert cd["nguyen_nhan"] == "thực thể bị bỏ lại" and "thay thế" not in cd["chi_tiet"]


def test_con_ket_noi_ma_khong_theo_lenh_la_do(ha):
    import time
    cu = datetime.fromtimestamp(time.time() - 10 * 3600, _TZ).isoformat()
    ha["states"] = [_s("fan.phong_khach", "off", cu)]
    assert sc.chan_doan("fan.phong_khach", sau_lenh="on")["nguyen_nhan"] == "thiết bị đơ"
    ha["states"] = [_s("fan.phong_khach", "off", datetime.now(_TZ).isoformat())]
    assert sc.chan_doan("fan.phong_khach", sau_lenh="on")["nguyen_nhan"] == "thiết bị không theo lệnh"


def test_bao_kem_nguyen_nhan_va_khong_bao_trung(ha, monkeypatch):
    from services import thong_bao
    da: list[str] = []
    monkeypatch.setattr(thong_bao, "gui", lambda khoa, tin, anh_url="": da.append(f"{khoa}|{tin}") or 1)
    ha["states"] = [_s("fan.phong_khach", "unavailable", _luc(9, 56), "Quạt phòng khách", restored=True),
                    _s("fan.ir_quat_phong_khach", "off", _luc(9, 56), "ir quat Phòng khách")]
    assert sc.bao("fan.phong_khach", "den_luc", hd="on", vi="16:17 Cảm biến cửa chính có người vào")
    assert not sc.bao("fan.phong_khach", "den_luc", hd="on", vi="16:18 khác"), "cùng lần mất kết nối — một tin"
    assert len(da) == 1 and da[0].startswith("nha.canh_bao|⏰ 16:17")
    assert "đáng lẽ em bật Quạt phòng khách" in da[0] and "Nguyên nhân: thực thể bị bỏ lại" in da[0]
