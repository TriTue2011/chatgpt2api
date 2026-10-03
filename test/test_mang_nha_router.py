"""Mạng nhà giai đoạn B — điều khiển thẳng router MikroTik qua API (chủ máy 03/10/2026). Router GIẢ trong bộ nhớ,
dựng theo số đo router thật cùng ngày: lease tĩnh kèm tên, «Global-QoS» đích cả LAN, luật forward «Established»."""
from __future__ import annotations

import itertools
import os
import socket
import threading

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import mang_nha as mn, routeros  # noqa: E402


class _Router:
    def __init__(self):
        self.so = itertools.count(100)
        self.bang: dict[str, list[dict]] = {
            "/ip/dhcp-server/lease": [
                {".id": "*1", "address": "172.16.10.21", "mac-address": "AA:00:00:00:00:21", "host-name": "V40-ThinQ",
                 "comment": "My phone LG", "dynamic": "false", "server": "dhcp_lan"},
                {".id": "*2", "address": "172.16.10.31", "mac-address": "AA:00:00:00:00:31", "host-name": "",
                 "dynamic": "true", "server": "dhcp_lan"},
                {".id": "*3", "address": "172.16.10.201", "mac-address": "AA:00:00:00:02:01", "host-name": "LGwebOSTV",
                 "comment": "Tivi LG", "dynamic": "false", "server": "dhcp_lan"},
            ],
            "/interface/bridge/host": [{"mac-address": "AA:00:00:00:00:21", "on-interface": "ether2"},
                                       {"mac-address": "BB:00:00:00:00:99", "on-interface": "ether3"},
                                       {"mac-address": "CC:00:00:00:00:01", "on-interface": "BridgeLAN", "local": "true"}],
            "/ip/arp": [{"address": "172.16.10.10"}],
            "/ip/pool": [{"name": "dhcp_pool", "ranges": "172.16.10.10-172.16.10.254"},
                         {"name": "dhcp_pool1", "ranges": "192.168.10.2-192.168.10.254"}],
            "/ip/dhcp-server": [{".id": "*1", "name": "dhcp_lan", "address-pool": "dhcp_pool", "interface": "BridgeLAN"}],
            "/ip/firewall/filter": [{".id": "*C", "chain": "forward", "comment": "FORWARD: Established"},
                                    {".id": "*A", "chain": "input", "comment": "INPUT: DROP ALL OTHER"}],
            "/ip/firewall/address-list": [],
            "/queue/simple": [{".id": "*Q", "name": "Global-QoS", "target": "BridgeLAN", "dynamic": "false"}],
            "/interface/wireguard": [{".id": "*W1", "name": "mik-hk", "disabled": "true"},
                                     {".id": "*W3", "name": "mik-sg", "disabled": "false"},
                                     {".id": "*W2", "name": "wg-home", "disabled": "false"}],
            "/interface/wireguard/peers": [
                {"interface": "mik-hk", "comment": "surfshark HK", "endpoint-address": "hk.example"},
                {"interface": "mik-sg", "comment": "surfshark SING", "endpoint-address": "sg.example"},
                {"interface": "wg-home", "comment": "Phone", "endpoint-address": ""}],
            "/ip/firewall/mangle": [{".id": "*M1", "new-routing-mark": "mik-hk", "comment": "mik-hk"},
                                    {".id": "*M2", "comment": "mik-hk mss"},
                                    {".id": "*M3", "comment": "MANGLE: MSS for PPPoE"}],
            "/ip/firewall/nat": [{".id": "*N1", "out-interface": "mik-hk"}, {".id": "*N2", "out-interface-list": "WAN"}],
            "/system/resource": [{"version": "7.20.5 (stable)", "uptime": "1d", "cpu-load": "3"}],
        }
        self.lenh: list[tuple] = []

    def goi(self, lenh, truy_van=None, **tt):
        self.lenh.append((lenh, tt))
        duong, _, viec = lenh.rpartition("/")
        tt = {("id" if k == "id" else k.replace("_", "-")): v for k, v in tt.items()}
        b = self.bang.setdefault(duong, [])
        if viec == "print":
            loc = dict(q[1:].split("=", 1) for q in (truy_van or []))
            return [dict(x) for x in b if all(x.get(k) == v for k, v in loc.items())]
        if viec == "add":
            truoc = tt.pop("place-before", None)
            x = {".id": f"*{next(self.so)}", **tt}
            i = next((n for n, y in enumerate(b) if y[".id"] == truoc), len(b))
            b.insert(i, x)
            return [{"ret": x[".id"]}]
        ma = tt.pop("id", None) or tt.pop("numbers", None)
        x = next(y for y in b if y[".id"] == ma)
        if viec == "remove":
            b.remove(x)
        elif viec == "set":
            x.update(tt)
        elif viec == "make-static":
            x["dynamic"] = "false"
        return []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def r(tmp_path, monkeypatch):
    mn._reset_for_tests(tmp_path / "mang.json")
    rt = _Router()
    monkeypatch.setattr(routeros, "ket_noi", lambda cfg=None: rt)
    monkeypatch.setattr(routeros, "cau_hinh", lambda: {"host": "r", "username": "c2a", "password": "x"})
    monkeypatch.setattr(mn.time, "sleep", lambda s: None)
    from services.config import config
    monkeypatch.setitem(config.data, "adguard", {"url": "http://172.16.10.10:3000"})
    return rt


def test_chan_dat_luat_dau_chuoi_forward_va_co_han(r):
    t = mn.chan("tivi", 120)
    assert "Tivi LG" in t and "2 giờ" in t
    fw = r.bang["/ip/firewall/filter"]
    assert fw[0]["comment"] == mn.LUAT_CHAN, "drop đứng TRƯỚC «Established» để cắt luôn kết nối đang mở"
    assert r.bang["/ip/firewall/address-list"] == [
        {".id": r.bang["/ip/firewall/address-list"][0][".id"], "list": "c2a_chan", "address": "172.16.10.201",
         "comment": "Tivi LG", "timeout": "120m"}]
    mn.chan("172.16.10.201")
    assert len(r.bang["/ip/firewall/address-list"]) == 1 and sum(x["comment"] == mn.LUAT_CHAN for x in fw) == 1
    assert "Đã mở" in mn.mo("tivi lg") and r.bang["/ip/firewall/address-list"] == []


def test_khong_doan_khi_ten_mo_ho_hay_khong_co(r):
    assert "khớp 2 máy" in mn.chan("lg")
    assert "không thấy máy «tủ lạnh»" in mn.chan("tủ lạnh")
    assert r.bang["/ip/firewall/address-list"] == []


def test_gioi_han_dat_hang_doi_truoc_global_qos(r):
    assert "1M/5M" in mn.gioi_han("tivi", "1M/5M")
    q = r.bang["/queue/simple"]
    assert q[0]["name"] == "c2a: Tivi LG" and q[0]["target"] == "172.16.10.201/32" and q[0]["max-limit"] == "1M/5M"
    assert q[1]["name"] == "Global-QoS", "đứng sau hàng đợi đích cả LAN là không bao giờ tới lượt"
    mn.gioi_han("tivi", "2M")
    assert [x["max-limit"] for x in q if x["name"].startswith("c2a")] == ["2M/2M"]
    mn.gioi_han("tivi", "bo")
    assert [x["name"] for x in q] == ["Global-QoS"]
    assert "không hiểu" in mn.gioi_han("tivi", "nhanh lắm")


def test_cho_duyet_gom_lease_dong_va_mac_chi_co_tren_bridge(r):
    t = mn.cho_duyet()
    assert "AA:00:00:00:00:31" in t and "BB:00:00:00:00:99" in t and "chưa có IP" in t
    assert "AA:00:00:00:00:21" not in t and "CC:00:00:00:00:01" not in t, "đã tĩnh / MAC của chính router thì thôi"


def test_duyet_khach_co_han_roi_het_han_thi_da_ra(r):
    t = mn.duyet("AA:00:00:00:00:31", "Điện thoại khách", "khach", 3 * 86400, now=1000.0)
    assert "nhóm Khách" in t and "3 ngày" in t
    le = next(x for x in r.bang["/ip/dhcp-server/lease"] if x[".id"] == "*2")
    assert le["dynamic"] == "false" and le["comment"] == "Điện thoại khách"
    assert any(x["target"] == "172.16.10.31/32" and x["max-limit"] == mn.BANG_THONG["khach"]
               for x in r.bang["/queue/simple"])
    assert mn.het_han(1000.0 + 86400) == []
    bao = mn.het_han(1000.0 + 3 * 86400 + 1)
    assert len(bao) == 1 and "Điện thoại khách" in bao[0]
    assert all(x[".id"] != "*2" for x in r.bang["/ip/dhcp-server/lease"]), "xoá lease tĩnh → không được phát IP nữa"
    assert any(x["address"] == "172.16.10.31" and x["timeout"] == "1d" for x in r.bang["/ip/firewall/address-list"])
    assert [x["name"] for x in r.bang["/queue/simple"]] == ["Global-QoS"]
    assert mn.het_han(1000.0 + 9 * 86400) == [], "đã đá rồi thì thôi"


def test_duyet_may_chua_co_lease_cap_ip_trong_cua_pool_nha(r):
    r.bang["/ip/dhcp-server"][0]["address-pool"] = "static-only"
    mn._luu({"pool_cu": {"dhcp_lan": "dhcp_pool"}})
    t = mn.duyet("bb-00-00-00-00-99", "Loa mới", "iot")
    le = r.bang["/ip/dhcp-server/lease"][-1]
    assert le["mac-address"] == "BB:00:00:00:00:99" and le["address"] == "172.16.10.11", "bỏ .10 đã có trong ARP"
    assert le["server"] == "dhcp_lan" and "nhóm IoT" in t and "không thời hạn" in t


def test_camera_va_chu_khong_gioi_han(r):
    assert "không giới hạn tốc độ" in mn.duyet("172.16.10.31", nhom="camera")
    assert [x["name"] for x in r.bang["/queue/simple"]] == ["Global-QoS"]


def test_khoa_dhcp_hoi_truoc_roi_moi_khoa_va_tra_lai_pool(r):
    t = mn.khoa_dhcp(True)
    assert "172.16.10.31" in t and "MAC ngẫu nhiên" in t
    assert r.bang["/ip/dhcp-server"][0]["address-pool"] == "dhcp_pool", "chưa xác nhận thì chưa đụng"
    assert "Đã khoá" in mn.khoa_dhcp(True, xac_nhan=True)
    assert r.bang["/ip/dhcp-server"][0]["address-pool"] == "static-only"
    assert "Đã mở" in mn.khoa_dhcp(False)
    assert r.bang["/ip/dhcp-server"][0]["address-pool"] == "dhcp_pool"


def test_ep_dns_tru_adguard_va_go_duoc(r):
    assert "chắc chắn" in mn.ep_dns(True)
    assert not any(x.get("comment") == mn.LUAT_DNS for x in r.bang["/ip/firewall/filter"])
    mn.ep_dns(True, xac_nhan=True)
    dns = [x for x in r.bang["/ip/firewall/filter"] if x.get("comment") == mn.LUAT_DNS]
    assert {(x["protocol"], x["dst-port"]) for x in dns} == {("udp", "53"), ("tcp", "53"), ("tcp", "853")}
    assert all(x["src-address"] == x["dst-address"] == "!172.16.10.10" for x in dns)
    assert "Đã bỏ" in mn.ep_dns(False) and not any(x.get("comment") == mn.LUAT_DNS
                                                    for x in r.bang["/ip/firewall/filter"])


def test_vpn_bat_ca_giao_dien_va_luat_cua_no_khong_dung_luat_khac(r):
    t = mn.dat_cong_tac("vpn", "surfshark hk", True)
    assert "Đã bật VPN surfshark HK" in t and "CHƯA bắt tay" in t and "tắt surfshark SING" in t
    assert [x["disabled"] for x in r.bang["/interface/wireguard"]] == ["no", "yes", "false"], "HK bật, SG tắt, wg-home để nguyên"
    assert {x[".id"]: x.get("disabled") for x in r.bang["/ip/firewall/mangle"]} == {"*M1": "no", "*M2": "no",
                                                                                     "*M3": None}
    assert {x[".id"]: x.get("disabled") for x in r.bang["/ip/firewall/nat"]} == {"*N1": "no", "*N2": None}
    assert "không chắc" in mn.dat_cong_tac("vpn", "phone", True), "wg-home là đường VÀO nhà, không phải VPN ra"


def test_router_tu_choi_thi_noi_ly_do(r, monkeypatch):
    def _hong(cfg=None):
        raise routeros.Loi("đăng nhập router bằng «c2a» không được: invalid user name or password (6)")
    monkeypatch.setattr(routeros, "ket_noi", _hong)
    assert "invalid user name or password" in mn.chan("tivi")


def test_tool_chi_admin_va_doi_phut(r):
    assert "chỉ chủ máy" in mn.xu_ly({"viec": "chan", "may": "tivi"}, {"is_admin": False})["text"]
    assert "2 giờ" in mn.xu_ly({"viec": "chan", "may": "tivi", "phut": 120}, {"is_admin": True})["text"]


# ── Giao thức API thật: một máy chủ giả nói đúng khung từ của RouterOS ─────
def _tu(s: str) -> bytes:
    b = s.encode()
    return routeros._ma_do_dai(len(b)) + b


def test_giao_thuc_dang_nhap_va_tra_loi():
    """Máy chủ giả nói đúng khung từ của RouterOS (từ dài >127 byte dùng mã độ dài 2 byte)."""
    sv = socket.socket()
    sv.bind(("127.0.0.1", 0))
    sv.listen(1)
    nhan: list[list[str]] = []

    def _chay_gon():
        c, _ = sv.accept()
        p = routeros.Phien(c)
        nhan.append(p._cau())
        c.sendall(_tu("!done") + b"\x00")
        nhan.append(p._cau())
        c.sendall(_tu("!re") + _tu("=name=c2a") + _tu("=address=" + "x" * 200) + b"\x00" + _tu("!done") + b"\x00")
        nhan.append(p._cau())
        c.sendall(_tu("!trap") + _tu("=message=no such item") + b"\x00" + _tu("!done") + b"\x00")
        c.close()
    th = threading.Thread(target=_chay_gon, daemon=True)
    th.start()
    s = socket.create_connection(sv.getsockname())
    p = routeros.Phien(s)
    assert p.goi("/login", name="c2a", password="mk") == []
    assert p.goi("/user/print", truy_van=["?name=c2a"]) == [{"name": "c2a", "address": "x" * 200}]
    with pytest.raises(routeros.Loi, match="no such item"):
        p.goi("/ip/firewall/filter/remove", id="*99")
    th.join(2)
    assert nhan == [["/login", "=name=c2a", "=password=mk"], ["/user/print", "?name=c2a"],
                    ["/ip/firewall/filter/remove", "=.id=*99"]]


def test_thieu_cau_hinh_noi_ro_thieu_gi():
    with pytest.raises(routeros.Loi, match="thiếu password"):
        routeros.ket_noi({"host": "r", "username": "c2a"})


def test_endpoint_thu_dung_o_vua_nhap_va_bao_ly_do(monkeypatch):
    from unittest import mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import mqtt
    from services.config import config
    monkeypatch.setitem(config.data, "mang_nha", {"router": {"host": "r", "username": "homeassistant",
                                                             "password": "cu"}})
    monkeypatch.setitem(config.data, "adguard", {})
    thay: list[dict] = []

    def _kn(cfg=None):
        thay.append(dict(cfg))
        raise routeros.Loi("đăng nhập router bằng «c2a» không được: invalid user name or password (6)")
    monkeypatch.setattr(routeros, "ket_noi", _kn)
    app = FastAPI()
    with mock.patch("api.mqtt.require_admin", lambda *a, **k: None):
        app.include_router(mqtt.create_router())
        d = TestClient(app).post("/api/mang-nha/thu", json={"router": {"username": "c2a", "password": ""},
                                                             "adguard": {}}).json()
    assert thay == [{"host": "r", "username": "c2a", "password": "cu"}], "ô trống giữ mật khẩu đã lưu"
    assert d["router"] == {"ok": False, "error": "đăng nhập router bằng «c2a» không được: invalid user name or "
                                                  "password (6)"}
    assert d["adguard"] == {"ok": False, "error": "chưa có URL AdGuard"}


def test_danh_sach_cho_trang_mang_nha(r):
    mn.chan("tivi", 60)
    mn.gioi_han("tivi", "1M/5M")
    mn.duyet("AA:00:00:00:00:31", "Khách", "khach", 86400, now=1000.0)
    d = mn.danh_sach()
    assert d["ok"] and "RouterOS 7.20.5" in d["router"] and d["dhcp_khoa"] is False and d["ep_dns"] is False
    tv = next(m for m in d["may"] if m["ip"] == "172.16.10.201")
    assert tv["chan"] and tv["chan_con"] == "60m" and tv["toc_do"] == "1M/5M" and tv["duyet"] and tv["ten"] == "Tivi LG"
    k = next(m for m in d["may"] if m["ip"] == "172.16.10.31")
    assert k["nhom"] == "khach" and k["het_han"] == 1000.0 + 86400
    assert [c["mac"] for c in d["cho"]] == ["BB:00:00:00:00:99"]
    assert d["vpn"] == [{"gd": "mik-hk", "ten": "surfshark HK", "bat": False, "bat_tay": ""},
                        {"gd": "mik-sg", "ten": "surfshark SING", "bat": True, "bat_tay": ""}]


def test_dat_ten_kick_va_bo_kick(r):
    assert "«Đèn bàn»" in mn.dat_ten("172.16.10.31", "Đèn bàn")
    assert r.bang["/ip/dhcp-server/lease"][1]["comment"] == "Đèn bàn"
    t = mn.kick("172.16.10.31")
    le = r.bang["/ip/dhcp-server/lease"][1]
    assert "Đã kick" in t and le["dynamic"] == "false" and le["block-access"] is True
    assert any(x["address"] == "172.16.10.31" and x["timeout"] == "1d" for x in r.bang["/ip/firewall/address-list"])
    assert "vào mạng lại" in mn.bo_kick("172.16.10.31")
    assert le["block-access"] is False and r.bang["/ip/firewall/address-list"] == []
    assert "Đã chặn MAC BB:00:00:00:00:99" in mn.kick("BB:00:00:00:00:99")
    moi = r.bang["/ip/dhcp-server/lease"][-1]
    assert moi["mac-address"] == "BB:00:00:00:00:99" and moi["block-access"] is True


def test_bang_thong_theo_nhom(r, monkeypatch):
    from services.config import config
    monkeypatch.setitem(config.data, "mang_nha", {})
    monkeypatch.setattr(config, "_save", lambda: None)
    assert "tối đa 3M" in mn.dat_bang_thong("iot", "3M")
    assert mn._bang_thong()["iot"] == "3M"
    assert "không giới hạn" in mn.dat_bang_thong("khach", "")
    assert "khach" not in mn._bang_thong(), "bỏ trần mặc định của khách"
    assert "không hiểu" in mn.dat_bang_thong("iot", "nhanh")
    assert "không có" in mn.dat_bang_thong("may_bay", "1M")


def test_endpoint_viec_goi_dung_ham_va_bao_ly_do(r, monkeypatch):
    from unittest import mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import mqtt
    app = FastAPI()
    with mock.patch("api.mqtt.require_admin", lambda *a, **k: None):
        app.include_router(mqtt.create_router())
        c = TestClient(app)
        assert "2 giờ" in c.post("/api/mang-nha/viec", json={"viec": "chan", "may": "tivi", "phut": 120}).json()["text"]
        assert "Thiếu máy" in c.post("/api/mang-nha/viec", json={"viec": "kick"}).json()["text"]
        assert "không có" in c.post("/api/mang-nha/viec", json={"viec": "xoa_router"}).json()["text"]
        t = c.post("/api/mang-nha/viec", json={"viec": "khoa_dhcp", "bat": True}).json()["text"]
        assert t.startswith("⚠️") and r.bang["/ip/dhcp-server"][0]["address-pool"] == "dhcp_pool", "hỏi trước"
        d = c.get("/api/mang-nha/may").json()
    assert d["ok"] and any(m["chan"] for m in d["may"])
