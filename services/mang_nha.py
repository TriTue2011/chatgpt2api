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
        w = d.get("wan") or {}
        if w.get("ket_noi") == "off":
            so.setdefault("rot_tu", now)
        elif w.get("ket_noi") == "on" and so.get("rot_tu"):
            tu = float(so.pop("rot_tu"))
            if now - tu >= ROT_TOI_THIEU:
                tin.append(f"🌐 Internet ({w.get('giao_dien')}) đã có lại — rớt từ khoảng {_gio(tu)} tới {_gio(now)} "
                           f"(~{(now - tu) / 60:.0f} phút).")
        _luu(so)
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


def dat_cong_tac(loai: str, ten: str, bat: bool) -> str:
    from services import ha_client
    x = _tim_cong_tac(loai, ten)
    if x is None:
        ds = ", ".join(c["ten"] for c in doc().get("cong_tac") or [] if c["loai"] == loai)
        return f"Em không chắc «{ten}» là cái nào — đang có: {ds or 'không có'}. Anh nói rõ tên giúp em."
    if not ha_client.call_service("switch", "turn_on" if bat else "turn_off", {"entity_id": x["ma"]}):
        return f"Router không nhận lệnh {'bật' if bat else 'tắt'} {x['ten']}."
    return f"Dạ, em đã {'bật' if bat else 'tắt'} {x['ten']}."


# ── Tool cho bot ────────────────────────────────────────────────────────────
MO_TA = ("Mạng NHÀ qua router MikroTik (chỉ admin): xem tình trạng internet, ai/máy nào đang dùng mạng, VPN, Kid "
         "Control → viec='xem'; bật/tắt VPN WireGuard (vd Surfshark HK/SG) → viec='vpn' (ten, bat); bật/tắt hồ sơ "
         "Kid Control → viec='kid' (ten, bat); chặn / mở internet một máy hay giới hạn tốc độ → viec='chan' | 'mo' | "
         "'gioi_han' (may = tên/IP/MAC). KHÔNG dùng cho wifi điện thoại của người dùng hay mạng ngoài nhà.")
THAM_SO = {"type": "object", "properties": {
    "viec": {"type": "string", "enum": ["xem", "vpn", "kid", "chan", "mo", "gioi_han"]},
    "ten": {"type": "string", "description": "Tên VPN / hồ sơ Kid Control (vd «surfshark hk»)."},
    "bat": {"type": "boolean"},
    "may": {"type": "string", "description": "Máy cần chặn/mở/giới hạn: tên máy, IP hoặc MAC."},
    "toc_do": {"type": "string", "description": "viec='gioi_han': tốc độ tối đa, vd «2M»."}},
    "required": ["viec"]}


def xu_ly(args: dict, ctx: dict) -> dict:
    if not bool((ctx or {}).get("is_admin")):
        return {"deliver_now": True, "text": "Điều khiển mạng nhà chỉ chủ máy dùng được ạ."}
    viec = str(args.get("viec") or "xem")
    if viec == "xem":
        return {"text": tom_tat()}
    if viec in ("vpn", "kid"):
        if args.get("bat") is None:
            return {"text": "Anh muốn bật hay tắt ạ?"}
        return {"text": dat_cong_tac(viec, str(args.get("ten") or ""), bool(args["bat"]))}
    return {"text": "Chặn / mở mạng từng máy và giới hạn tốc độ cần một tài khoản API riêng trên router MikroTik — "
                    "em chưa có tài khoản đó nên chưa làm được ạ."}


def _reset_for_tests(duong: Path) -> None:
    global _PATH
    _PATH = duong
