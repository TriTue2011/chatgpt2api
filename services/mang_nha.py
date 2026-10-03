"""MẠNG NHÀ qua router MikroTik — theo dõi, báo và điều khiển (chủ máy 02/10/2026: "tìm mikrotik để tích hợp kiểm
soát mạng"; chọn cả bốn: theo dõi & báo, bật/tắt VPN và Kid Control, chặn/mở mạng từng máy, băng thông từng máy).

Giai đoạn A (file này, chỉ đọc + công tắc sẵn có): đọc qua tích hợp HA «MikroTik Extended» — không cần tài khoản
riêng, không ghi gì vào router ngoài các công tắc HA đã cho phép. Chặn/mở từng máy và giới hạn băng thông cần gọi
REST API của RouterOS bằng một tài khoản riêng (giai đoạn B).

Nhận thực thể theo DẤU HIỆU, không theo tên nhà này: tích hợp `mikrotik_extended`; cổng WAN là giao diện có IP
CÔNG CỘNG (không thuộc dải riêng / CGNAT), kèm cảm biến «… connection» cùng tên giao diện; danh sách DHCP là cảm biến có
thuộc tính ``leases``; máy đang dùng mạng là ``wired_clients_list`` / ``wireless_clients_list``.
"""

from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.config import DATA_DIR
from utils.log import logger

_PATH = Path(DATA_DIR) / "agent" / "mang_nha.json"
_TZ = timezone(timedelta(hours=7))
_khoa = threading.Lock()
TICH_HOP = "mikrotik_extended"
#: Mạng rớt ngắn hơn ngần này không báo (PPPoE nhà mạng hay chớp lại vài giây).
ROT_TOI_THIEU = 60


def _nap() -> dict[str, Any]:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _luu(d: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_PATH)


def _gio(ts: float) -> str:
    return datetime.fromtimestamp(ts, _TZ).strftime("%H:%M %d/%m")


# ── Đọc từ HA ───────────────────────────────────────────────────────────────
def doc() -> dict[str, Any]:
    """Ảnh chụp mạng: {"co": bool, "wan": {...}|None, "leases": [...], "dang_dung": [...], "cong_tac": [...], "cpu", "ram"}."""
    from services import ha_client

    st = ha_client.get_states() or []
    pf = (ha_client.get_ha_area_index() or {}).get("entity_platform") or {}
    mk = [s for s in st if pf.get(str(s["entity_id"])) == TICH_HOP]
    if not mk:
        return {"co": False}
    ra: dict[str, Any] = {"co": True, "wan": None, "leases": [], "dang_dung": [], "cong_tac": []}
    theo_ma = {str(s["entity_id"]): s for s in mk}
    ung: list[tuple[float, dict[str, Any]]] = []
    for s in mk:
        ma, a = str(s["entity_id"]), s.get("attributes") or {}
        if "leases" in a:
            ra["leases"] = [x for x in a["leases"] if isinstance(x, dict) and x.get("mac")]
        for k in ("wired_clients_list", "wireless_clients_list"):
            ra["dang_dung"] += [x for x in a.get(k) or [] if isinstance(x, dict) and x.get("mac")]
        if ma.endswith("_cpu_load"):
            ra["cpu"] = s.get("state")
        elif ma.endswith("_memory_usage"):
            ra["ram"] = s.get("state")
        elif ma.startswith("switch.") and ("_wireguard_" in ma or "_kidcontrol_" in ma):
            ra["cong_tac"].append({"ma": ma, "ten": str(a.get("friendly_name") or ma), "bat": s.get("state") == "on",
                                   "loai": "vpn" if "_wireguard_" in ma else "kid"})
        elif ma.endswith("_ip_address") and a.get("interface"):
            try:
                ip = ipaddress.ip_address(str(s.get("state")))
            except ValueError:
                continue
            if ip.is_global:                    # IP công cộng → ứng viên WAN
                goc = ma[: -len("_ip_address")]
                ket = goc.replace("sensor.", "binary_sensor.", 1) + "_connection"
                try:
                    nhan = float((theo_ma.get(goc + "_rx_total") or {}).get("state"))
                except (TypeError, ValueError):
                    nhan = 0.0
                ung.append((nhan, {"giao_dien": str(a.get("interface")), "ip": str(ip), "ma_ket_noi": ket,
                                   "ket_noi": (theo_ma.get(ket) or {}).get("state")}))
    if ung:
        # Nhiều giao diện mang IP công cộng (đo nhà này: wg-home đặt dải 192.16.0.0/24 — dải CÔNG CỘNG, không phải
        # 192.168) → WAN là cái NHẬN nhiều dữ liệu nhất: mọi lượt tải từ internet đi qua nó.
        ra["wan"] = max(ung, key=lambda x: x[0])[1]
    for x in ra["cong_tac"]:
        x["noi"] = (theo_ma.get(x["ma"].replace("switch.", "binary_sensor.", 1) + "_connected") or {}).get("state") == "on"
    return ra


def tom_tat(d: dict[str, Any] | None = None) -> str:
    """Câu trả lời «mạng nhà sao rồi / ai đang dùng mạng»."""
    d = d or doc()
    if not d.get("co"):
        return "Em chưa thấy router MikroTik nào trong Home Assistant (cần tích hợp MikroTik Extended)."
    w = d.get("wan") or {}
    dong = [f"🌐 Internet ({w.get('giao_dien', '?')}): {'đang có' if w.get('ket_noi') == 'on' else 'MẤT'}"
            + (f", IP {w['ip']}" if w.get("ip") else "") + f" · router CPU {d.get('cpu', '?')}% RAM {d.get('ram', '?')}%"]
    ds = sorted({x["mac"]: x for x in d["dang_dung"]}.values(), key=lambda x: str(x.get("host_name") or ""))
    dong.append(f"📶 {len(ds)} máy đang dùng mạng: "
                + ", ".join(f"{x.get('host_name') or x['mac']} ({x.get('address', '?')})" for x in ds[:40]))
    vpn = [x for x in d["cong_tac"] if x["loai"] == "vpn"]
    if vpn:
        dong.append("🔒 VPN: " + ", ".join(f"{x['ten']} {'bật' if x['bat'] else 'tắt'}"
                                          + (" (đang nối)" if x["noi"] else "") for x in vpn))
    kid = [x for x in d["cong_tac"] if x["loai"] == "kid"]
    if kid:
        dong.append("🧒 Kid Control: " + ", ".join(f"{x['ten']} {'bật' if x['bat'] else 'tắt'}" for x in kid))
    return "\n".join(dong)


# ── Theo dõi & báo (heartbeat 5 phút) ──────────────────────────────────────
def quet(now: float | None = None) -> list[str]:
    """Máy LẠ vào mạng (MAC chưa từng thấy trong DHCP), Internet rớt / có lại. Trả các tin đã gửi.

    Lần quét đầu chỉ ghi nhớ các máy đang có (không báo cả nhà là «lạ»). Internet rớt thì không gửi được tin ra
    ngoài — báo khi có lại: rớt từ lúc nào tới lúc nào."""
    from services import thong_bao

    now = now or time.time()
    d = doc()
    if not d.get("co"):
        return []
    tin: list[str] = []
    with _khoa:
        so = _nap()
        biet = so.setdefault("mac_biet", {})
        lan_dau = not biet
        for x in d["leases"]:
            mac = str(x["mac"]).upper()
            if mac in biet:
                continue
            biet[mac] = {"ten": str(x.get("host_name") or ""), "ip": str(x.get("address") or ""), "luc": now}
            if not lan_dau:
                tin.append(f"📶 Máy LẠ vào mạng nhà: {x.get('host_name') or 'không tên'} — IP {x.get('address', '?')}, "
                           f"MAC {mac}, lúc {_gio(now)}. Người nhà thì bỏ qua; không biết là ai thì nhắn em «chặn "
                           f"mạng máy {mac}».")
        tin += _quet_router(so, now)
        w = d.get("wan") or {}
        if w.get("ket_noi") == "off":
            so.setdefault("rot_tu", now)
        elif w.get("ket_noi") == "on" and so.get("rot_tu"):
            tu = float(so.pop("rot_tu"))
            if now - tu >= ROT_TOI_THIEU:
                tin.append(f"🌐 Internet ({w.get('giao_dien')}) đã có lại — rớt từ khoảng {_gio(tu)} tới {_gio(now)} "
                           f"(~{(now - tu) / 60:.0f} phút).")
        _luu(so)
    tin += het_han(now)
    for t in tin:
        thong_bao.gui("nha.canh_bao", t)
    if tin:
        logger.info({"event": "mang_nha_bao", "so_tin": len(tin)})
    return tin


# ── Điều khiển qua công tắc HA sẵn có ──────────────────────────────────────
def _tim_cong_tac(loai: str, ten: str) -> dict[str, Any] | None:
    from services.ha_client import _fold_diacritics
    ds = [x for x in doc().get("cong_tac") or [] if x["loai"] == loai]
    q = _fold_diacritics(str(ten or "")).lower().split()
    if not q:
        return ds[0] if len(ds) == 1 else None
    khop = [x for x in ds if all(t in _fold_diacritics(x["ten"] + " " + x["ma"]).lower() for t in q)]
    return khop[0] if len(khop) == 1 else None


def dat_vpn(ten: str, bat: bool) -> str:
    """Bật/tắt một đường VPN WireGuard ra ngoài ĐỦ BỘ trên router: giao diện + luật đánh dấu tuyến (mangle) + NAT của nó.

    Vì sao không dùng công tắc HA: đo 03/10/2026, công tắc «WireGuard surfshark HK» của MikroTik Extended bật/tắt
    PEER, trong khi thứ đang tắt là GIAO DIỆN `mik-hk` — công tắc báo «on» mà VPN không chạy, bot bảo «đã bật» là sai.
    Chỉ đụng luật có dấu của chính giao diện đó: mangle `new-routing-mark` = tên giao diện, NAT `out-interface` = tên
    giao diện, luật MSS có chú thích bắt đầu bằng tên giao diện."""
    from services.ha_client import _fold_diacritics

    def _lam(r: Any) -> str:
        peers = r.goi("/interface/wireguard/peers/print", **{".proplist": "interface,comment,name,endpoint-address"})
        ra = {p["interface"]: p for p in peers if p.get("endpoint-address")}      # chỉ đường RA ngoài (có endpoint)
        q = _fold_diacritics(str(ten or "")).lower().split()
        khop = [i for i, p in ra.items()
                if q and all(t in _fold_diacritics(f"{i} {p.get('comment', '')} {p.get('name', '')}").lower() for t in q)]
        if len(khop) != 1:
            ds = ", ".join(f"{p.get('comment') or i} ({i})" for i, p in ra.items())
            return f"Em không chắc «{ten}» là đường VPN nào — đang có: {ds or 'không có'}. Anh nói rõ giúp em."
        gd = khop[0]

        def _dat(g: str, b: bool) -> int:
            for x in r.goi("/interface/wireguard/print", **{".proplist": ".id,name"}):
                if x.get("name") == g:
                    r.goi("/interface/wireguard/set", id=x[".id"], disabled="no" if b else "yes")
            n = 0
            for duong, khoa in (("/ip/firewall/mangle", "new-routing-mark"), ("/ip/firewall/nat", "out-interface")):
                for x in r.goi(f"{duong}/print", **{".proplist": f".id,comment,{khoa}"}):
                    if x.get(khoa) == g or (duong.endswith("mangle") and str(x.get("comment") or "").startswith(f"{g} ")):
                        r.goi(f"{duong}/set", id=x[".id"], disabled="no" if b else "yes")
                        n += 1
            return n
        # Một đường ra một lúc: đo 03/10/2026 mik-hk và mik-sg cùng mang 10.14.0.2/16 — bật cả hai là hai tuyến nối
        # thẳng trùng nhau, gói đi đường nào tuỳ router.
        tat_kia = [g for g in ra if g != gd and bat]
        for g in tat_kia:
            _dat(g, False)
        doi = _dat(gd, bat)
        ten_vpn = ra[gd].get("comment") or gd
        if not bat:
            return f"Đã tắt VPN {ten_vpn}: giao diện {gd} và {doi} luật đi kèm."
        time.sleep(6)                    # chờ bắt tay; WireGuard chỉ báo nối sau gói đầu tiên
        hs = next((p.get("last-handshake") for p in r.goi("/interface/wireguard/peers/print",
                                                          **{".proplist": "interface,last-handshake"})
                   if p.get("interface") == gd), None)
        return (f"Đã bật VPN {ten_vpn}: giao diện {gd} và {doi} luật đi kèm"
                + (f" (tắt {', '.join(ra[g].get('comment') or g for g in tat_kia)} — một đường ra một lúc)" if tat_kia else "")
                + " — "
                + (f"đã bắt tay với máy chủ ({hs} trước)." if hs else
                   "CHƯA bắt tay được với máy chủ sau 6 giây (kiểm khoá/tài khoản Surfshark)."))
    return _ket(_lam)


def dat_cong_tac(loai: str, ten: str, bat: bool) -> str:
    from services import ha_client, routeros
    if loai == "vpn" and routeros.cau_hinh().get("password"):
        return dat_vpn(ten, bat)
    x = _tim_cong_tac(loai, ten)
    if x is None:
        ds = ", ".join(c["ten"] for c in doc().get("cong_tac") or [] if c["loai"] == loai)
        return f"Em không chắc «{ten}» là cái nào — đang có: {ds or 'không có'}. Anh nói rõ tên giúp em."
    if not ha_client.call_service("switch", "turn_on" if bat else "turn_off", {"entity_id": x["ma"]}):
        return f"Router không nhận lệnh {'bật' if bat else 'tắt'} {x['ten']}."
    return f"Dạ, em đã {'bật' if bat else 'tắt'} {x['ten']}."


# ── Giai đoạn B: điều khiển thẳng router qua API (services/routeros.py) ─────
# Chủ máy 03/10/2026: duyệt máy trước khi cho mạng (kể cả hàng xóm biết mật khẩu wifi), khách hạn chế, IoT trần băng
# thông trừ camera, cho dùng vài hôm rồi đá ra. Đo router nhà này cùng ngày: 39/44 lease đã tĩnh kèm tên, BridgeLAN
# `arp=reply-only` + DHCP `add-arp=yes` (máy tự đặt IP tay không nói chuyện được với router), DNS DHCP = AdGuard,
# router không có wifi — hai AP cắm ether2/ether3 làm cầu, nên MAC từng máy hiện trong bảng host của bridge.
#
# Dấu của c2a trên router: danh sách địa chỉ ``c2a_chan`` + một luật forward drop; hàng đợi tên «c2a: …»; luật ép DNS
# chú thích «c2a: ép DNS». Không sửa chú thích lease chủ máy đã đặt; nhóm và hạn của máy nằm ở sổ ``may`` của file này.

DS_CHAN = "c2a_chan"
LUAT_CHAN = "c2a: chặn máy"
LUAT_DNS = "c2a: ép DNS"
TIEN_TO_HANG = "c2a: "
NHOM = {"chu": "Chủ nhà", "nha": "Người nhà", "khach": "Khách", "iot": "IoT", "camera": "Camera"}
#: Trần mặc định theo nhóm, dạng RouterOS «tải lên/tải xuống» của máy. Đổi ở ``mang_nha.bang_thong``. Nhóm không có
#: ở đây là KHÔNG giới hạn (chủ, người nhà, camera — chủ máy dặn camera không hạn chế).
BANG_THONG = {"khach": "5M/20M", "iot": "1M/2M"}
_TOC_DO = re.compile(r"^\d+(?:\.\d+)?[kKMG]?(?:/\d+(?:\.\d+)?[kKMG]?)?$")


def _mac(s: str) -> str:
    h = re.sub(r"[^0-9a-fA-F]", "", str(s or ""))
    return ":".join(h[i:i + 2] for i in range(0, 12, 2)).upper() if len(h) == 12 else ""


def _bang_thong() -> dict[str, str]:
    from services.config import config
    raw = (config.data.get("mang_nha") or {}).get("bang_thong")
    gop = {**BANG_THONG, **(raw if isinstance(raw, dict) else {})}
    return {k: v for k, v in gop.items() if v}


def _ten_lease(x: dict[str, Any]) -> str:
    return str(x.get("comment") or x.get("host-name") or x.get("mac-address") or x.get("address") or "?")


def _leases(r: Any) -> list[dict[str, str]]:
    return r.goi("/ip/dhcp-server/lease/print", **{".proplist": ".id,address,mac-address,host-name,comment,dynamic,"
                                                                 "status,server,last-seen,block-access"})


def tim_may(r: Any, may: str) -> dict[str, str]:
    """IP hoặc MAC thì khớp đúng; còn lại là tên — mọi chữ (bỏ dấu) phải có trong chú thích / host-name. Không thấy
    hoặc nhiều máy cùng khớp → ``routeros.Loi`` kèm danh sách để bot hỏi lại, không đoán."""
    from services.ha_client import _fold_diacritics
    from services.routeros import Loi

    ds = _leases(r)
    q = str(may or "").strip()
    mac = _mac(q)
    if mac:
        khop = [x for x in ds if _mac(x.get("mac-address", "")) == mac]
    elif re.fullmatch(r"\d+\.\d+\.\d+\.\d+", q):
        khop = [x for x in ds if x.get("address") == q]
    else:
        tu = _fold_diacritics(q).lower().split()
        khop = [x for x in ds if tu and all(
            t in _fold_diacritics(f"{x.get('comment', '')} {x.get('host-name', '')}").lower() for t in tu)]
    if len(khop) == 1:
        return khop[0]
    if not khop:
        raise Loi(f"không thấy máy «{q}» trong danh sách DHCP của router")
    raise Loi(f"«{q}» khớp {len(khop)} máy: " + ", ".join(f"{_ten_lease(x)} ({x.get('address')})" for x in khop[:8])
              + " — anh nói rõ IP hoặc MAC giúp em")


def _dam_bao_luat_chan(r: Any) -> None:
    """Luật drop cho ``c2a_chan`` đứng ĐẦU chuỗi forward — trước cả «Established», để chặn là cắt luôn kết nối đang
    mở (đang xem video thì đứt ngay, không đợi mở kết nối mới)."""
    fw = r.goi("/ip/firewall/filter/print", **{".proplist": ".id,chain,comment"})
    if any(x.get("comment") == LUAT_CHAN for x in fw):
        return
    dau = next((x[".id"] for x in fw if x.get("chain") == "forward"), None)
    r.goi("/ip/firewall/filter/add", chain="forward", src_address_list=DS_CHAN, action="drop", comment=LUAT_CHAN,
          **({"place-before": dau} if dau else {}))


def _ket(fn: Any) -> str:
    """Chạy một việc trên router; lỗi trả NGUYÊN lý do (chủ máy: bị từ chối phải nói vì sao)."""
    from services import routeros
    try:
        with routeros.ket_noi() as r:
            return fn(r)
    except routeros.Loi as exc:
        logger.warning({"event": "mang_nha_router_loi", "error": str(exc)[:200]})
        return f"Em chưa làm được: {exc}."
    except OSError as exc:
        return f"Em chưa làm được: mất kết nối với router ({exc})."


def chan(may: str, phut: int | None = None) -> str:
    def _lam(r: Any) -> str:
        x = tim_may(r, may)
        ip, ten = x["address"], _ten_lease(x)
        _dam_bao_luat_chan(r)
        for c in r.goi("/ip/firewall/address-list/print", truy_van=[f"?list={DS_CHAN}", f"?address={ip}"]):
            r.goi("/ip/firewall/address-list/remove", id=c[".id"])
        r.goi("/ip/firewall/address-list/add", list=DS_CHAN, address=ip, comment=ten,
              **({"timeout": f"{int(phut)}m"} if phut else {}))
        han = f" trong {_thoi_luong(int(phut) * 60)} (router tự mở lại)" if phut else ""
        return f"⛔ Đã chặn internet máy {ten} ({ip}){han}."
    return _ket(_lam)


def mo(may: str) -> str:
    def _lam(r: Any) -> str:
        x = tim_may(r, may)
        ip, ten = x["address"], _ten_lease(x)
        co = r.goi("/ip/firewall/address-list/print", truy_van=[f"?list={DS_CHAN}", f"?address={ip}"])
        for c in co:
            r.goi("/ip/firewall/address-list/remove", id=c[".id"])
        return f"✅ Đã mở internet cho {ten} ({ip})." if co else f"Máy {ten} ({ip}) đang không bị em chặn."
    return _ket(_lam)


def _dat_hang(r: Any, ip: str, ten: str, toc_do: str) -> None:
    """Hàng đợi riêng «c2a: tên» cho một IP; ``toc_do`` rỗng = gỡ. Đặt TRƯỚC hàng đợi tĩnh đầu tiên: hàng đợi đơn khớp
    theo thứ tự, mà nhà này có «Global-QoS» đích cả BridgeLAN — đứng sau nó là không bao giờ tới lượt."""
    for c in r.goi("/queue/simple/print", **{".proplist": ".id,name,target"}):
        if c.get("name", "").startswith(TIEN_TO_HANG) and c.get("target", "").split("/")[0] == ip:
            r.goi("/queue/simple/remove", id=c[".id"])
    if not toc_do:
        return
    dau = next((c[".id"] for c in r.goi("/queue/simple/print", **{".proplist": ".id,dynamic"})
                if c.get("dynamic") != "true"), None)
    r.goi("/queue/simple/add", name=f"{TIEN_TO_HANG}{ten}"[:60], target=f"{ip}/32",
          max_limit=toc_do if "/" in toc_do else f"{toc_do}/{toc_do}", **({"place-before": dau} if dau else {}))


def gioi_han(may: str, toc_do: str) -> str:
    t = str(toc_do or "").strip().replace(" ", "")
    bo = t.lower() in ("", "0", "bo", "khong", "none")
    if not bo and not _TOC_DO.match(t):
        return f"Tốc độ «{toc_do}» em không hiểu — viết kiểu «2M» (cả hai chiều) hoặc «1M/5M» (tải lên/tải xuống)."

    def _lam(r: Any) -> str:
        x = tim_may(r, may)
        _dat_hang(r, x["address"], _ten_lease(x), "" if bo else t)
        return (f"Đã bỏ giới hạn tốc độ cho {_ten_lease(x)}." if bo
                else f"🐢 Đã giới hạn {_ten_lease(x)} ({x['address']}) ở {t} (tải lên/tải xuống).")
    return _ket(_lam)


def _thoi_luong(giay: int) -> str:
    for ten, s in (("tuần", 604800), ("ngày", 86400), ("giờ", 3600), ("phút", 60)):
        if giay >= s and giay % s == 0:
            return f"{giay // s} {ten}"
    return f"{round(giay / 3600, 1)} giờ"


def _may_dang_doi(r: Any, ds: list[dict[str, str]]) -> list[dict[str, str]]:
    """Máy chưa duyệt: lease ĐỘNG (khi DHCP còn phát tự do) + MAC trong bảng host của bridge mà không có lease nào
    (khi DHCP đã khoá «static-only», máy lạ không nhận được IP nên chỉ còn dấu ở đây — AP nhà này làm cầu)."""
    co = {_mac(x.get("mac-address", "")) for x in ds}
    ra = [x for x in ds if x.get("dynamic") == "true"]
    for h in r.goi("/interface/bridge/host/print", **{".proplist": "mac-address,on-interface,local"}):
        m = _mac(h.get("mac-address", ""))
        if m and h.get("local") != "true" and m not in co:
            co.add(m)
            ra.append({"mac-address": m, "on-interface": h.get("on-interface", "")})
    return ra


def cho_duyet() -> str:
    def _lam(r: Any) -> str:
        ds = _may_dang_doi(r, _leases(r))
        if not ds:
            return "Không có máy nào đang chờ duyệt — mọi máy trong mạng đều đã có địa chỉ cố định."
        dong = [f"• {x.get('host-name') or 'không tên'} — MAC {_mac(x['mac-address'])}"
                + (f", IP {x['address']}" if x.get("address") else ", chưa có IP") for x in ds]
        return (f"📋 {len(ds)} máy chưa duyệt:\n" + "\n".join(dong)
                + "\nDuyệt: «duyệt máy <MAC> tên …, nhóm khách/iot/nhà/chủ/camera, 3 ngày» (bỏ hạn = mãi).")
    return _ket(_lam)


def _ip_trong(r: Any, ds: list[dict[str, str]]) -> str:
    """IP trống đầu tiên trong pool DHCP của mạng LAN — pool máy chủ DHCP đang dùng, hoặc pool cũ đã cất khi khoá
    «static-only». Không trùng lease nào và không trùng bảng ARP (máy đặt IP tay)."""
    from services.routeros import Loi

    with _khoa:
        cu = _nap().get("pool_cu") or {}
    ten_pool = {s.get("address-pool") if s.get("address-pool") != "static-only" else cu.get(s.get("name"))
                for s in r.goi("/ip/dhcp-server/print", **{".proplist": "name,address-pool"})} - {None}
    dung = {x.get("address") for x in ds} | {a.get("address") for a in r.goi("/ip/arp/print",
                                                                         **{".proplist": "address"})}
    for p in r.goi("/ip/pool/print"):
        if p.get("name") not in ten_pool:
            continue
        for khoang in str(p.get("ranges", "")).split(","):
            a, _, b = khoang.partition("-")
            try:
                tu, den = ipaddress.ip_address(a.strip()), ipaddress.ip_address((b or a).strip())
            except ValueError:
                continue
            for n in range(int(tu), int(den) + 1):
                ip = str(ipaddress.ip_address(n))
                if ip not in dung:
                    return ip
    raise Loi("hết IP trống trong pool DHCP (hoặc không biết pool nào của mạng nhà)")


def duyet(may: str, ten: str = "", nhom: str = "nha", giay: int | None = None, *, nguoi_duyet: str = "",
          now: float | None = None) -> str:
    """Cho một máy vào mạng: lease thành TĨNH (khoá DHCP rồi máy chưa có lease thì tạo lease tĩnh mới), đặt chú thích
    là tên nếu anh đặt, giới hạn theo nhóm, ghi hạn vào sổ để `het_han` đá ra."""
    nhom = nhom if nhom in NHOM else "nha"
    now = float(now or time.time())

    def _lam(r: Any) -> str:
        ds = _leases(r)
        m = _mac(may)
        x = next((l for l in ds if m and _mac(l.get("mac-address", "")) == m), None) if m else tim_may(r, may)
        if x is None:
            if not m:
                from services.routeros import Loi
                raise Loi(f"«{may}» không phải MAC")
            srv = next((l.get("server") for l in ds if l.get("server")), None)
            ip = _ip_trong(r, ds)
            r.goi("/ip/dhcp-server/lease/add", mac_address=m, address=ip,
                  comment=ten or m, **({"server": srv} if srv else {}))
            x = {"address": ip, "mac-address": m, "comment": ten or m}
        else:
            if x.get("dynamic") == "true":
                r.goi("/ip/dhcp-server/lease/make-static", numbers=x[".id"])
            if ten:
                # make-static giữ nguyên .id; chú thích CHỈ đặt khi anh đặt tên — tên chủ máy gõ sẵn trên router giữ nguyên.
                r.goi("/ip/dhcp-server/lease/set", id=x[".id"], comment=ten)
                x["comment"] = ten
        ip, mac, goi = x["address"], _mac(x["mac-address"]), _ten_lease(x)
        toc = _bang_thong().get(nhom, "")
        _dat_hang(r, ip, goi, toc)
        with _khoa:
            so = _nap()
            so.setdefault("may", {})[mac] = {"ten": goi, "ip": ip, "nhom": nhom, "luc": now,
                                            "het_han": now + giay if giay else None, "nguoi_duyet": nguoi_duyet}
            so.setdefault("mac_biet", {}).setdefault(mac, {"ten": goi, "ip": ip, "luc": now})
            _luu(so)
        logger.info({"event": "mang_nha_duyet", "mac": mac, "nhom": nhom, "giay": giay})
        return (f"✅ Đã cho {goi} ({ip}) vào mạng — nhóm {NHOM[nhom]}"
                + (f", tốc độ tối đa {toc}" if toc else ", không giới hạn tốc độ")
                + (f", trong {_thoi_luong(int(giay))} rồi em tự đá ra." if giay else ", không thời hạn."))
    return _ket(_lam)


def het_han(now: float | None = None) -> list[str]:
    """Máy hết hạn: xoá lease tĩnh (không còn được phát IP), chặn IP đang giữ thêm 1 ngày — đúng lease-time, máy còn
    nhớ IP cũ tới lúc xin lại — và gỡ hàng đợi. Trả câu báo."""
    from services import routeros

    now = float(now or time.time())
    with _khoa:
        qua = {m: v for m, v in (_nap().get("may") or {}).items() if v.get("het_han") and v["het_han"] <= now}
    if not qua:
        return []
    bao: list[str] = []
    try:
        with routeros.ket_noi() as r:
            ds = _leases(r)
            _dam_bao_luat_chan(r)
            for mac, v in qua.items():
                for x in ds:
                    if _mac(x.get("mac-address", "")) == mac and x.get("dynamic") != "true":
                        r.goi("/ip/dhcp-server/lease/remove", id=x[".id"])
                r.goi("/ip/firewall/address-list/add", list=DS_CHAN, address=v["ip"], timeout="1d",
                      comment=f"hết hạn: {v['ten']}")
                _dat_hang(r, v["ip"], v["ten"], "")
                bao.append(f"⌛ Hết hạn dùng mạng của {v['ten']} ({v['ip']}, nhóm {NHOM.get(v['nhom'], v['nhom'])}) — "
                           "em đã gỡ khỏi danh sách và cắt mạng.")
    except routeros.Loi as exc:
        logger.warning({"event": "mang_nha_het_han_loi", "error": str(exc)[:200]})
        return []
    with _khoa:
        so = _nap()
        for mac in qua:
            (so.get("may") or {}).pop(mac, None)
        _luu(so)
    return bao


def khoa_dhcp(bat: bool, xac_nhan: bool = False) -> str:
    """Bật: DHCP chỉ phát IP cho lease tĩnh («static-only») — máy lạ biết mật khẩu wifi cũng không có mạng. Lần gọi đầu
    chỉ báo những máy SẼ MẤT mạng (lease động), phải gọi lại với ``xac_nhan`` mới làm. Tắt: trả pool cũ."""
    def _lam(r: Any) -> str:
        sv = [s for s in r.goi("/ip/dhcp-server/print", **{".proplist": ".id,name,address-pool,interface"})]
        if not sv:
            return "Router không có máy chủ DHCP nào."
        with _khoa:
            so = _nap()
        if bat:
            doi = [x for x in _leases(r) if x.get("dynamic") == "true"]
            if doi and not xac_nhan:
                return ("⚠️ Khoá DHCP thì những máy này mất mạng khi hết hạn lease (tối đa 1 ngày) vì chưa được duyệt:\n"
                        + "\n".join(f"• {_ten_lease(x)} — {x.get('address')} / {_mac(x.get('mac-address', ''))}"
                                    for x in doi)
                        + "\nĐiện thoại bật «địa chỉ MAC ngẫu nhiên» sẽ hiện như máy lạ — tắt nó cho wifi nhà, hoặc "
                          "duyệt MAC mới. Anh duyệt các máy trên trước, hoặc bảo em «khoá DHCP, chắc chắn».")
            cu = dict(so.get("pool_cu") or {})
            for s in sv:
                if s.get("address-pool") != "static-only":
                    cu[s["name"]] = s.get("address-pool")
                    r.goi("/ip/dhcp-server/set", id=s[".id"], address_pool="static-only")
            with _khoa:
                so = _nap()
                so["pool_cu"] = cu
                _luu(so)
            return "🔒 Đã khoá DHCP: chỉ máy đã duyệt mới nhận IP. Máy mới vào em sẽ báo để anh duyệt."
        cu = so.get("pool_cu") or {}
        mo_ = []
        for s in sv:
            if s.get("address-pool") == "static-only" and cu.get(s["name"]):
                r.goi("/ip/dhcp-server/set", id=s[".id"], address_pool=cu[s["name"]])
                mo_.append(s["name"])
        return ("🔓 Đã mở DHCP — máy nào vào cũng nhận IP như trước." if mo_
                else "DHCP đang không khoá (hoặc em không biết pool cũ) — em để nguyên.")
    return _ket(_lam)


def ep_dns(bat: bool, xac_nhan: bool = False) -> str:
    """Mọi truy vấn DNS (53 udp/tcp, DoT 853) từ LAN đi nơi khác ngoài AdGuard thì bị từ chối — máy tự đặt DNS 8.8.8.8
    để lách AdGuard (đo 90 ngày: không một truy vấn Roblox nào tới AdGuard) phải quay về AdGuard. Từ chối thay vì
    drop: máy thấy lỗi ngay và chuyển DNS dự phòng, không treo chờ."""
    from services.config import config
    from urllib.parse import urlparse

    ag = urlparse(str((config.data.get("adguard") or {}).get("url") or "")).hostname or ""
    if bat and not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ag):
        return "Em chưa biết IP của AdGuard (Cài đặt › Home Assistant › Mạng nhà) nên chưa ép DNS được."
    if bat and not xac_nhan:
        return (f"⚠️ Ép DNS: máy nào tự đặt DNS khác {ag} sẽ không phân giải được tên miền cho tới khi dùng AdGuard "
                "(thiết bị cài cứng 8.8.8.8 có thể mất mạng). DoH (DNS qua HTTPS) chưa chặn được bằng cách này. "
                "Anh bảo em «ép DNS, chắc chắn» để làm.")

    def _lam(r: Any) -> str:
        fw = r.goi("/ip/firewall/filter/print", **{".proplist": ".id,chain,comment"})
        cu = [x for x in fw if x.get("comment") == LUAT_DNS]
        if not bat:
            for x in cu:
                r.goi("/ip/firewall/filter/remove", id=x[".id"])
            return "Đã bỏ ép DNS." if cu else "DNS đang không bị ép."
        if cu:
            return "DNS đã được ép qua AdGuard từ trước."
        dau = next((x[".id"] for x in fw if x.get("chain") == "forward"), None)
        for proto, cong, kieu in (("udp", "53", "icmp-port-unreachable"), ("tcp", "53", "tcp-reset"),
                                  ("tcp", "853", "tcp-reset")):
            r.goi("/ip/firewall/filter/add", chain="forward", in_interface_list="LAN", protocol=proto, dst_port=cong,
                  src_address=f"!{ag}", dst_address=f"!{ag}", action="reject", reject_with=kieu, comment=LUAT_DNS,
                  **({"place-before": dau} if dau else {}))
        return f"🛡️ Đã ép DNS: mọi máy trong nhà chỉ hỏi tên miền qua AdGuard ({ag})."
    return _ket(_lam)


def dat_bang_thong(nhom: str, toc_do: str) -> str:
    """Trần tốc độ mặc định của một nhóm (``mang_nha.bang_thong``) — áp cho máy duyệt SAU này; máy đã duyệt giữ
    hàng đợi cũ tới khi đổi nhóm / đặt lại."""
    from services.config import config
    if nhom not in NHOM:
        return f"Nhóm «{nhom}» không có."
    t = str(toc_do or "").strip().replace(" ", "")
    bo = t.lower() in ("", "0", "bo", "khong")
    if not bo and not _TOC_DO.match(t):
        return f"Tốc độ «{toc_do}» em không hiểu — viết kiểu «2M» hoặc «1M/5M» (tải lên/tải xuống)."

    def _ghi(data: dict) -> None:
        bt = dict((data.setdefault("mang_nha", {})).get("bang_thong") or {})
        bt[nhom] = "" if bo else t
        data["mang_nha"]["bang_thong"] = bt
    config.mutate(_ghi)
    return f"Nhóm {NHOM[nhom]}: " + ("không giới hạn." if bo else f"tối đa {t} (tải lên/tải xuống).")


def danh_sach() -> dict[str, Any]:
    """Một lần đọc cho trang Mạng nhà: máy (lease) kèm trạng thái chặn / tốc độ / nhóm / hạn, máy chờ duyệt, DHCP
    khoá chưa, DNS ép chưa, VPN ra ngoài. Lỗi router → {"ok": False, "loi": lý do}."""
    from services import routeros

    try:
        with routeros.ket_noi() as r:
            ds = _leases(r)
            cho = _may_dang_doi(r, ds)
            chan = {x.get("address"): x.get("timeout") or "" for x in r.goi(
                "/ip/firewall/address-list/print", truy_van=[f"?list={DS_CHAN}"], **{".proplist": "address,timeout"})}
            hang = {c.get("target", "").split("/")[0]: c.get("max-limit", "") for c in r.goi(
                "/queue/simple/print", **{".proplist": "name,target,max-limit"})
                if c.get("name", "").startswith(TIEN_TO_HANG)}
            sv = r.goi("/ip/dhcp-server/print", **{".proplist": "name,address-pool"})
            fw = r.goi("/ip/firewall/filter/print", **{".proplist": "comment"})
            peers = r.goi("/interface/wireguard/peers/print",
                          **{".proplist": "interface,comment,endpoint-address,last-handshake"})
            tat = {x.get("name") for x in r.goi("/interface/wireguard/print", truy_van=["?disabled=true"],
                                                 **{".proplist": "name"})}
            ban = r.goi("/system/resource/print", **{".proplist": "version,uptime,cpu-load"})[0]
    except (routeros.Loi, OSError) as exc:
        return {"ok": False, "loi": str(exc)}
    with _khoa:
        so = _nap().get("may") or {}
    may = []
    for x in ds:
        mac = _mac(x.get("mac-address", ""))
        ip = x.get("address", "")
        v = so.get(mac) or {}
        may.append({"id": x.get(".id"), "ip": ip, "mac": mac, "host": x.get("host-name", ""),
                    "ten": x.get("comment", ""), "duyet": x.get("dynamic") != "true",
                    "khoa": x.get("block-access") == "true", "trang_thai": x.get("status", ""),
                    "thay": x.get("last-seen", ""), "chan": ip in chan, "chan_con": chan.get(ip, ""),
                    "toc_do": hang.get(ip, ""), "nhom": v.get("nhom", ""), "het_han": v.get("het_han")})
    return {"ok": True, "router": f"RouterOS {ban.get('version', '?')} · chạy {ban.get('uptime', '?')} · CPU "
                                  f"{ban.get('cpu-load', '?')}%",
            "may": sorted(may, key=lambda m: (m["duyet"], tuple(int(p) for p in m["ip"].split(".")) if m["ip"] else ())),
            "cho": [{"mac": _mac(x["mac-address"]), "ip": x.get("address", ""), "host": x.get("host-name", ""),
                     "cong": x.get("on-interface", "")} for x in cho],
            "dhcp_khoa": bool(sv) and all(s.get("address-pool") == "static-only" for s in sv),
            "ep_dns": any(x.get("comment") == LUAT_DNS for x in fw),
            "vpn": [{"gd": p["interface"], "ten": p.get("comment") or p["interface"], "bat": p["interface"] not in tat,
                     "bat_tay": p.get("last-handshake", "")} for p in peers if p.get("endpoint-address")],
            "nhom": NHOM, "bang_thong": _bang_thong()}


def dat_ten(may: str, ten: str) -> str:
    ten = " ".join(str(ten or "").split())[:60]
    if not ten:
        return "Tên trống — em không đổi."

    def _lam(r: Any) -> str:
        x = tim_may(r, may)
        r.goi("/ip/dhcp-server/lease/set", id=x[".id"], comment=ten)
        return f"Đã đặt tên {x.get('address')} là «{ten}»."
    return _ket(_lam)


def kick(may: str) -> str:
    """Đá một máy ra và không cho vào lại: lease TĨNH + ``block-access=yes`` (DHCP không cấp IP, bridge
    `arp=reply-only` nên máy tự đặt IP tay cũng không nói chuyện được với router) + cắt kết nối đang mở bằng
    ``c2a_chan`` 1 ngày. Máy chỉ có MAC (chưa có IP) thì tạo lease khoá với một IP trống của pool."""
    def _lam(r: Any) -> str:
        ds = _leases(r)
        m = _mac(may)
        x = next((l for l in ds if m and _mac(l.get("mac-address", "")) == m), None) if m else tim_may(r, may)
        if x is None:
            ip = _ip_trong(r, ds)
            srv = next((l.get("server") for l in ds if l.get("server")), None)
            r.goi("/ip/dhcp-server/lease/add", mac_address=m, address=ip, block_access=True,
                  comment=f"c2a: đã kick {m}", **({"server": srv} if srv else {}))
            return f"🚫 Đã chặn MAC {m}: router sẽ không cấp IP cho máy này."
        if x.get("dynamic") == "true":
            r.goi("/ip/dhcp-server/lease/make-static", numbers=x[".id"])
        r.goi("/ip/dhcp-server/lease/set", id=x[".id"], block_access=True)
        _dam_bao_luat_chan(r)
        for c in r.goi("/ip/firewall/address-list/print", truy_van=[f"?list={DS_CHAN}", f"?address={x['address']}"]):
            r.goi("/ip/firewall/address-list/remove", id=c[".id"])
        r.goi("/ip/firewall/address-list/add", list=DS_CHAN, address=x["address"], timeout="1d",
              comment=f"kick: {_ten_lease(x)}")
        return f"🚫 Đã kick {_ten_lease(x)} ({x['address']}): cắt mạng ngay, không cấp IP lại."
    return _ket(_lam)


def bo_kick(may: str) -> str:
    def _lam(r: Any) -> str:
        x = tim_may(r, may)
        r.goi("/ip/dhcp-server/lease/set", id=x[".id"], block_access=False)
        for c in r.goi("/ip/firewall/address-list/print", truy_van=[f"?list={DS_CHAN}", f"?address={x['address']}"]):
            r.goi("/ip/firewall/address-list/remove", id=c[".id"])
        return f"✅ Đã cho {_ten_lease(x)} ({x['address']}) vào mạng lại."
    return _ket(_lam)


def _quet_router(so: dict[str, Any], now: float) -> list[str]:
    """Máy chờ duyệt từ router — bắt được cả máy KHÔNG có lease (sau khi khoá DHCP). Mỗi MAC báo một lần, chung sổ
    ``mac_biet`` với đường đọc qua HA để không báo hai lần."""
    from services import routeros
    if not routeros.cau_hinh().get("password"):
        return []
    try:
        with routeros.ket_noi() as r:
            doi = _may_dang_doi(r, _leases(r))
    except (routeros.Loi, OSError) as exc:
        logger.warning({"event": "mang_nha_router_loi", "error": str(exc)[:200]})
        return []
    biet = so.setdefault("mac_biet", {})
    tin = []
    for x in doi:
        m = _mac(x["mac-address"])
        if m in biet:
            continue
        biet[m] = {"ten": x.get("host-name", ""), "ip": x.get("address", ""), "luc": now}
        tin.append(f"📶 Máy LẠ xin vào mạng nhà: {x.get('host-name') or 'không tên'} — MAC {m}"
                   + (f", IP {x['address']}" if x.get("address") else ", chưa được cấp IP")
                   + f", lúc {_gio(now)}.\nDuyệt: nhắn em «duyệt máy {m} tên …, khách 3 ngày» · "
                     f"chặn: «chặn mạng máy {m}» · bỏ qua nếu là người nhà đổi MAC.")
    return tin


# ── Tool cho bot ────────────────────────────────────────────────────────────
MO_TA = ("Mạng NHÀ qua router MikroTik (chỉ admin): xem internet, máy nào đang dùng mạng, VPN, Kid Control → "
         "viec='xem'; bật/tắt VPN WireGuard → viec='vpn' (ten, bat); hồ sơ Kid Control → viec='kid' (ten, bat); chặn / "
         "mở internet một máy → viec='chan' (may, phut nếu có thời hạn) | 'mo' (may); giới hạn tốc độ → viec='gioi_han' "
         "(may, toc_do vd «2M» hoặc «1M/5M», «bo» để gỡ); máy chờ duyệt → viec='cho'; cho máy vào mạng → viec='duyet' "
         "(may = MAC/IP/tên, ten_moi, nhom chu|nha|khach|iot|camera, phut = thời hạn, bỏ trống = mãi); chỉ cấp IP cho máy "
         "đã duyệt → viec='khoa_dhcp' (bat; xac_nhan=true CHỈ khi anh đã nói «chắc chắn»); buộc DNS qua AdGuard → "
         "viec='ep_dns' (bat, xac_nhan như trên). KHÔNG dùng cho mạng ngoài nhà.")
THAM_SO = {"type": "object", "properties": {
    "viec": {"type": "string", "enum": ["xem", "vpn", "kid", "chan", "mo", "gioi_han", "cho", "duyet", "khoa_dhcp",
                                        "ep_dns"]},
    "ten": {"type": "string", "description": "Tên VPN / hồ sơ Kid Control (vd «surfshark hk»)."},
    "bat": {"type": "boolean"},
    "may": {"type": "string", "description": "Máy: tên (theo ghi chú trên router), IP hoặc MAC."},
    "toc_do": {"type": "string", "description": "viec='gioi_han': «2M», «1M/5M» (tải lên/tải xuống) hoặc «bo»."},
    "phut": {"type": "integer", "description": "Thời hạn tính bằng phút (chặn 2 tiếng = 120; khách 3 ngày = 4320)."},
    "ten_moi": {"type": "string", "description": "viec='duyet': tên đặt cho máy."},
    "nhom": {"type": "string", "enum": list(NHOM)},
    "xac_nhan": {"type": "boolean", "description": "Chỉ true khi chủ máy đã xác nhận rõ ràng."}},
    "required": ["viec"]}


def xu_ly(args: dict, ctx: dict) -> dict:
    if not bool((ctx or {}).get("is_admin")):
        return {"deliver_now": True, "text": "Điều khiển mạng nhà chỉ chủ máy dùng được ạ."}
    viec = str(args.get("viec") or "xem")
    may = str(args.get("may") or "").strip()
    phut = int(args["phut"]) if str(args.get("phut") or "").strip().isdigit() and int(args["phut"]) > 0 else None
    if viec == "xem":
        return {"text": tom_tat()}
    if viec in ("vpn", "kid", "khoa_dhcp", "ep_dns") and args.get("bat") is None:
        return {"text": "Anh muốn bật hay tắt ạ?"}
    if viec in ("vpn", "kid"):
        return {"text": dat_cong_tac(viec, str(args.get("ten") or ""), bool(args["bat"]))}
    if viec in ("chan", "mo", "gioi_han", "duyet") and not may:
        return {"text": "Anh cho em biết máy nào (tên, IP hoặc MAC) ạ."}
    if viec == "chan":
        return {"text": chan(may, phut)}
    if viec == "mo":
        return {"text": mo(may)}
    if viec == "gioi_han":
        return {"text": gioi_han(may, str(args.get("toc_do") or ""))}
    if viec == "cho":
        return {"text": cho_duyet()}
    if viec == "duyet":
        return {"text": duyet(may, str(args.get("ten_moi") or ""), str(args.get("nhom") or "nha"),
                              phut * 60 if phut else None, nguoi_duyet=str((ctx or {}).get("user_id") or ""))}
    if viec == "khoa_dhcp":
        return {"text": khoa_dhcp(bool(args["bat"]), bool(args.get("xac_nhan")))}
    if viec == "ep_dns":
        return {"text": ep_dns(bool(args["bat"]), bool(args.get("xac_nhan")))}
    return {"text": f"Việc «{viec}» em chưa biết làm với mạng nhà."}


def _reset_for_tests(duong: Path) -> None:
    global _PATH
    _PATH = duong
