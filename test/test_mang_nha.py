"""Mạng nhà qua MikroTik (chủ máy 02/10/2026) — đọc qua HA, máy lạ vào mạng, internet rớt / có lại, công tắc VPN.
Không gọi HA thật."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import ha_client, mang_nha as mn  # noqa: E402

P = "mikrotik_extended"


def _s(ma, gt, **a):
    return {"entity_id": ma, "state": gt, "attributes": a}


@pytest.fixture
def nha(tmp_path, monkeypatch):
    mn._reset_for_tests(tmp_path / "mang.json")
    st = {"leases": [{"mac": "aa:aa", "address": "172.16.10.5", "host_name": "may-a"}], "wan": "on"}

    def states(use_cache=True):
        return [
            _s("sensor.r_ppp_pppoe_out1_ip_address", "1.52.237.136", interface="pppoe-out1"),
            _s("sensor.r_ppp_pppoe_out1_rx_total", "24.1"),
            _s("binary_sensor.r_ppp_pppoe_out1_connection", st["wan"]),
            # dải 192.16.0.0/24 là IP CÔNG CỘNG (đo nhà chủ máy: wg-home) — không được nhận nhầm là WAN
            _s("sensor.r_port_wg_home_ip_address", "192.16.0.1", interface="wg-home"),
            _s("sensor.r_port_wg_home_rx_total", "0.0"),
            _s("sensor.r_port_ether4_ip_address", "100.100.100.1", interface="WAN-ETHER1"),   # CGNAT
            _s("sensor.r_core_dhcp_leases", str(len(st["leases"])), leases=st["leases"]),
            _s("sensor.r_core_wired_clients", "1", wired_clients_list=[{"mac": "aa:aa", "address": "172.16.10.5",
                                                                         "host_name": "May A"}]),
            _s("switch.r_wireguard_surfshark_hk", "on", friendly_name="WireGuard surfshark HK"),
            _s("switch.r_wireguard_surfshark_sing", "off", friendly_name="WireGuard surfshark SING"),
            _s("binary_sensor.r_wireguard_surfshark_hk_connected", "on"),
        ]
    monkeypatch.setattr(ha_client, "get_states", states)
    monkeypatch.setattr(ha_client, "get_ha_area_index",
                        lambda use_cache=True: {"entity_platform": {x["entity_id"]: P for x in states()}})
    from services import thong_bao
    gui: list[str] = []
    monkeypatch.setattr(thong_bao, "gui", lambda khoa, tin, anh_url="": gui.append(tin) or 1)
    st["gui"] = gui
    return st


def test_wan_la_giao_dien_ip_cong_cong_nhan_nhieu_nhat(nha):
    d = mn.doc()
    assert d["wan"]["giao_dien"] == "pppoe-out1" and d["wan"]["ket_noi"] == "on"
    t = mn.tom_tat(d)
    assert "May A (172.16.10.5)" in t and "surfshark HK bật (đang nối)" in t


def test_may_la_chi_bao_sau_lan_quet_dau(nha):
    assert mn.quet(1000.0) == [], "lần đầu ghi nhớ máy đang có, không báo"
    nha["leases"].append({"mac": "bb:bb", "address": "172.16.10.9", "host_name": "la"})
    tin = mn.quet(2000.0)
    assert len(tin) == 1 and "Máy LẠ" in tin[0] and "BB:BB" in tin[0] and nha["gui"] == tin
    assert mn.quet(3000.0) == [], "đã biết thì thôi"


def test_internet_rot_bao_khi_co_lai_bo_qua_chop(nha):
    mn.quet(1000.0)
    nha["wan"] = "off"
    assert mn.quet(2000.0) == []
    nha["wan"] = "on"
    tin = mn.quet(2600.0)
    assert len(tin) == 1 and "đã có lại" in tin[0] and "~10 phút" in tin[0]
    nha["wan"] = "off"
    mn.quet(3000.0)
    nha["wan"] = "on"
    assert mn.quet(3030.0) == [], "rớt 30 giây — chớp, không báo"


def test_cong_tac_vpn_theo_ten_va_chi_admin(nha, monkeypatch):
    goi: list = []
    monkeypatch.setattr(ha_client, "call_service", lambda mien, dv, data: goi.append((mien, dv, data)) or True)
    assert "đã tắt" in mn.dat_cong_tac("vpn", "hk", False)
    assert goi == [("switch", "turn_off", {"entity_id": "switch.r_wireguard_surfshark_hk"})]
    assert "không chắc" in mn.dat_cong_tac("vpn", "surfshark", True), "hai VPN cùng khớp — hỏi lại"
    assert "chỉ chủ máy" in mn.xu_ly({"viec": "xem"}, {"is_admin": False})["text"]
