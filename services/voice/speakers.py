"""Sổ loa — đặt TÊN cho loa rồi phát file âm thanh ra loa đó.

Ba kiểu loa, không kiểu nào bắt buộc Home Assistant:
  cast — Google Cast / Nest / Android TV (thư viện pychromecast, nối bằng IP)
  dlna — loa UPnP/DLNA (SOAP thuần, không cần thư viện)
  ha   — nhờ Home Assistant phát (media_player.play_media) cho thiết bị lạ

Loa được đặt tên như đặt tên người/bot ("loa phòng khách") để user ra lệnh tự
nhiên: "phát ra loa phòng khách". Lưu tại DATA_DIR/voice/speakers.json:

    {"<id>": {"id","name","kind","host","port","entity_id","note","added_at"}}

LƯU Ý MẠNG: container chạy trên bridge network nên mDNS/SSDP (tự dò loa)
thường KHÔNG qua được — vì vậy luôn cho phép thêm loa bằng IP thủ công, và
nhập sẵn danh sách từ Home Assistant nếu có.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from services.config import DATA_DIR

logger = logging.getLogger(__name__)

_PATH = Path(DATA_DIR) / "voice" / "speakers.json"
_lock = threading.RLock()
_data: dict[str, dict[str, Any]] = {}
_loaded = False

KINDS = ("cast", "dlna", "ha", "r1")


def _ensure() -> None:
    global _loaded, _data
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        try:
            if _PATH.is_file():
                raw = json.loads(_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    _data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        except Exception:
            _data = {}
        _loaded = True


def _save() -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_PATH)
    except Exception as exc:
        logger.warning("voice.speakers: khong luu duoc: %s", exc)


# ── CRUD ─────────────────────────────────────────────────────────────────────


def list_speakers() -> list[dict[str, Any]]:
    _ensure()
    with _lock:
        rows = [dict(v) for v in _data.values()]
    rows.sort(key=lambda r: str(r.get("name") or "").lower())
    return rows


def get(speaker_id: str) -> Optional[dict[str, Any]]:
    _ensure()
    with _lock:
        rec = _data.get(str(speaker_id or "").strip())
        return dict(rec) if rec else None


def add(name: str, kind: str, *, host: str = "", port: int = 0,
        entity_id: str = "", note: str = "", ws_port: int = 0,
        max_vol: int = 0, control_url: str = "") -> dict[str, Any]:
    """Thêm loa. `host` = IP (cast/dlna/r1), `entity_id` = media_player.* (ha).

    Loa r1 dùng thêm `ws_port` (mặc định 8082 — kênh nhạc AiboxPlus) và `max_vol`
    (thang âm lượng, mặc định 15)."""
    _ensure()
    name = (name or "").strip()
    kind = (kind or "").strip().lower()
    if not name:
        raise ValueError("Loa phải có tên (vd 'loa phòng khách').")
    if kind not in KINDS:
        raise ValueError(f"Kiểu loa phải là một trong {KINDS}.")
    if kind == "ha" and not entity_id.strip():
        raise ValueError("Loa kiểu 'ha' cần entity_id (media_player.xxx).")
    if kind in ("cast", "dlna", "r1") and not host.strip():
        raise ValueError("Loa Cast/DLNA/R1 cần IP hoặc URL.")
    sid = uuid.uuid4().hex[:10]
    default_port = 8009 if kind == "cast" else 8080 if kind == "r1" else 0
    rec = {
        "id": sid,
        "name": name,
        "kind": kind,
        "host": host.strip(),
        "port": int(port or default_port),
        "entity_id": entity_id.strip(),
        "note": note.strip(),
        "added_at": int(time.time()),
    }
    if kind == "r1":
        rec["ws_port"] = int(ws_port or 8082)
        rec["max_vol"] = int(max_vol or 15)
    if kind == "dlna" and control_url.strip():
        rec["control_url"] = control_url.strip()   # từ SSDP → _play_dlna dùng thẳng
    with _lock:
        _data[sid] = rec
        _save()
    return dict(rec)


def update(speaker_id: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
    _ensure()
    sid = str(speaker_id or "").strip()
    with _lock:
        rec = _data.get(sid)
        if not rec:
            return None
        rec = dict(rec)
        for key in ("name", "kind", "host", "entity_id", "note"):
            if key in patch:
                rec[key] = str(patch[key] or "").strip()
        if "port" in patch:
            try:
                rec["port"] = int(patch["port"] or 0)
            except (TypeError, ValueError):
                pass
        if "volume" in patch:
            # Âm lượng mặc định khi phát (0..1); rỗng/None = giữ nguyên loa.
            try:
                v = patch["volume"]
                rec["volume"] = None if v in (None, "") else max(
                    0.0, min(1.0, float(v)))
            except (TypeError, ValueError):
                pass
        _data[sid] = rec
        _save()
        return dict(rec)


def remove(speaker_id: str) -> bool:
    _ensure()
    sid = str(speaker_id or "").strip()
    with _lock:
        if sid in _data:
            del _data[sid]
            _save()
            return True
    return False


def _fold(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", str(text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", t.replace("đ", "d")).strip()


def resolve(query: str) -> list[dict[str, Any]]:
    """Tìm loa theo tên/id/IP (bỏ dấu, khớp một phần). Trả về DANH SÁCH —
    nhiều kết quả nghĩa là yêu cầu chưa rõ, caller phải hỏi lại user."""
    q = _fold(query)
    raw = str(query or "").strip()
    if not q and not raw:
        return []
    rows = list_speakers()
    exact = [r for r in rows if _fold(r.get("name")) == q or r.get("id") == raw]
    if exact:
        return exact
    hits = [r for r in rows
            if q and (q in _fold(r.get("name")) or _fold(r.get("name")) in q)]
    if hits:
        return hits
    return [r for r in rows if raw and raw == str(r.get("host") or "")]


def describe(rec: dict[str, Any]) -> str:
    kind = str(rec.get("kind") or "")
    where = rec.get("entity_id") if kind == "ha" else rec.get("host")
    return f"{rec.get('name')} ({kind} · {where})"


# ── Phát ─────────────────────────────────────────────────────────────────────


def _cast_connect(rec: dict[str, Any], timeout: int = 10):
    """Nối THẲNG tới thiết bị Cast bằng IP:8009 (get_chromecast_from_host) —
    không đi qua lớp discovery/zeroconf vốn thất thường sau bridge network
    (get_listed_chromecasts từng pass lúc 'Kiểm tra' nhưng fail lúc phát).

    Caller PHẢI gọi cast.disconnect() khi xong để không rò thread socket."""
    try:
        import pychromecast
    except Exception as exc:
        raise RuntimeError("Chưa cài pychromecast trong image.") from exc
    host = str(rec.get("host") or "").strip()
    port = int(rec.get("port") or 8009)
    cast = pychromecast.get_chromecast_from_host(
        (host, port, None, None, str(rec.get("name") or "loa")),
        timeout=timeout,
    )
    cast.wait(timeout=timeout)
    return cast


def _play_cast(rec: dict[str, Any], url: str, timeout: int = 30) -> None:
    host = str(rec.get("host") or "").strip()
    port = int(rec.get("port") or 8009)
    try:
        cast = _cast_connect(rec, timeout=min(timeout, 15))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Không kết nối được loa Cast {host}:{port}.") from exc
    try:
        # Âm lượng mặc định của loa (0..1) đặt trước khi phát, nếu khai trong sổ.
        try:
            vol = rec.get("volume")
            if vol is not None and str(vol) != "":
                cast.set_volume(max(0.0, min(1.0, float(vol))))
        except Exception:
            pass
        cast.media_controller.play_media(url, "audio/wav", stream_type="BUFFERED")
        cast.media_controller.block_until_active(timeout=timeout)
    finally:
        try:
            cast.disconnect(timeout=2)
        except Exception:
            pass


# ── Điều khiển Cast (âm lượng / mute / pause / resume / stop / trạng thái) ───
# Bộ lệnh thiết thực của giao thức Google Cast qua pychromecast. Còn sẵn để
# mở rộng sau: seek, queue, launch app (YouTube/receiver riêng) — cùng
# media_controller. Volume DLNA cần parse device-description XML → để sau.


def set_volume(rec: dict[str, Any], level: float) -> float:
    """Đặt âm lượng loa Cast/R1 (0..1). Trả mức đã đặt."""
    kind = str(rec.get("kind") or "")
    if kind == "r1":
        from services.voice import r1 as _r1
        _r1.set_volume(str(rec.get("host") or ""), float(level),
                       port=int(rec.get("port") or 8080),
                       max_vol=int(rec.get("max_vol") or 15))
        return max(0.0, min(1.0, float(level)))
    if kind != "cast":
        raise RuntimeError("Chỉnh âm lượng hiện chỉ hỗ trợ loa Google Cast / R1.")
    level = max(0.0, min(1.0, float(level)))
    cast = _cast_connect(rec)
    try:
        cast.set_volume(level)
    finally:
        try:
            cast.disconnect(timeout=2)
        except Exception:
            pass
    return level


def set_mute(rec: dict[str, Any], muted: bool) -> None:
    if str(rec.get("kind") or "") != "cast":
        raise RuntimeError("Mute chỉ hỗ trợ loa Cast.")
    cast = _cast_connect(rec)
    try:
        cast.set_volume_muted(bool(muted))
    finally:
        try:
            cast.disconnect(timeout=2)
        except Exception:
            pass


def media_control(rec: dict[str, Any], action: str) -> None:
    """pause | resume | stop | on | off trên loa Cast.

    on/off mô phỏng media_player.turn_on/turn_off của Home Assistant:
    on = đánh thức bằng Default Media Receiver (CC1AD845); off = quit_app
    thoát app đang cast (loa về idle — Cast không có lệnh cắt nguồn thật)."""
    kind = str(rec.get("kind") or "")
    if kind == "r1":
        from services.voice import r1 as _r1
        act = {"stop": "stop", "pause": "pause", "resume": "play",
               "on": "play", "off": "stop"}.get(action)
        if not act:
            raise RuntimeError(f"Lệnh không hỗ trợ trên R1: {action}")
        _r1.media_action(str(rec.get("host") or ""), act,
                         ws_port=int(rec.get("ws_port") or 8082))
        return
    if kind != "cast":
        raise RuntimeError("Điều khiển phát chỉ hỗ trợ loa Cast / R1.")
    cast = _cast_connect(rec)
    try:
        mc = cast.media_controller
        if action == "pause":
            mc.pause()
        elif action == "resume":
            mc.play()
        elif action == "stop":
            mc.stop()
        elif action == "on":
            cast.start_app("CC1AD845")   # Default Media Receiver — thức dậy
        elif action == "off":
            cast.quit_app()              # thoát app đang cast → idle
        else:
            raise RuntimeError(f"Lệnh không hỗ trợ: {action}")
    finally:
        try:
            cast.disconnect(timeout=2)
        except Exception:
            pass


def speaker_status(rec: dict[str, Any]) -> dict[str, Any]:
    """Trạng thái loa Cast: âm lượng, mute, đang phát gì."""
    if str(rec.get("kind") or "") != "cast":
        return {"kind": rec.get("kind"), "supported": False}
    cast = _cast_connect(rec)
    try:
        st = cast.status
        mc = cast.media_controller.status
        return {
            "supported": True,
            "volume": round(float(getattr(st, "volume_level", 0) or 0), 2),
            "muted": bool(getattr(st, "volume_muted", False)),
            "app": str(getattr(st, "display_name", "") or ""),
            "player_state": str(getattr(mc, "player_state", "") or ""),
            "title": str(getattr(mc, "title", "") or ""),
        }
    finally:
        try:
            cast.disconnect(timeout=2)
        except Exception:
            pass


_SOAP_SET = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    "<s:Body><u:SetAVTransportURI "
    'xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
    "<InstanceID>0</InstanceID><CurrentURI>{url}</CurrentURI>"
    "<CurrentURIMetaData></CurrentURIMetaData>"
    "</u:SetAVTransportURI></s:Body></s:Envelope>"
)
_SOAP_PLAY = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    "<s:Body><u:Play "
    'xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
    "<InstanceID>0</InstanceID><Speed>1</Speed>"
    "</u:Play></s:Body></s:Envelope>"
)


def _dlna_control_url(rec: dict[str, Any]) -> str:
    """Endpoint AVTransport. `host` có thể là IP, IP:port hoặc URL đầy đủ."""
    explicit = str(rec.get("control_url") or "").strip()
    if explicit:
        return explicit
    h = str(rec.get("host") or "").strip()
    if h.startswith("http"):
        p = urlparse(h)
        if p.path and p.path not in ("/", ""):
            return h
        base = f"{p.scheme}://{p.netloc}"
    else:
        base = f"http://{h}" if ":" in h else f"http://{h}:49152"
    return base.rstrip("/") + "/AVTransport/control"


def _play_dlna(rec: dict[str, Any], url: str, timeout: int = 20) -> None:
    import urllib.request

    ctrl = _dlna_control_url(rec)

    def _soap(body: str, action: str) -> None:
        req = urllib.request.Request(
            ctrl, data=body.encode("utf-8"), method="POST",
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPACTION": f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()

    _soap(_SOAP_SET.format(url=url), "SetAVTransportURI")
    _soap(_SOAP_PLAY, "Play")


def _play_ha(rec: dict[str, Any], url: str, announce: bool = True) -> None:
    """Nhờ HA phát — `announce` chen ngang rồi trả lại nhạc đang nghe."""
    from services.ha_client import call_service

    ok = call_service("media_player", "play_media", {
        "entity_id": rec.get("entity_id"),
        "media_content_id": url,
        "media_content_type": "music",
        "announce": bool(announce),
    })
    if not ok:
        raise RuntimeError(f"HA không phát được ra {rec.get('entity_id')}.")


def play_url(speaker: dict[str, Any], url: str) -> None:
    """Phát URL âm thanh ra một loa. Ném RuntimeError nếu thất bại."""
    kind = str(speaker.get("kind") or "").lower()
    if kind == "cast":
        _play_cast(speaker, url)
    elif kind == "dlna":
        _play_dlna(speaker, url)
    elif kind == "ha":
        _play_ha(speaker, url)
    elif kind == "r1":
        raise RuntimeError(
            "Loa R1 chưa đọc thẳng file TTS — R1 dùng để phát nhạc/điều khiển. "
            "Muốn đọc thông báo bằng giọng, chọn loa Cast/DLNA/HA.")
    else:
        raise RuntimeError(f"Kiểu loa không hỗ trợ: {kind}")


def play_music(speaker: dict[str, Any], query: str) -> dict[str, Any]:
    """Mở nhạc theo yêu cầu (YouTube) — hiện chỉ loa R1. Trả bài đã chọn."""
    if str(speaker.get("kind") or "") != "r1":
        raise RuntimeError("Mở nhạc theo yêu cầu hiện chỉ hỗ trợ loa R1.")
    from services.voice import r1 as _r1
    return _r1.play_music(str(speaker.get("host") or ""), str(query or "").strip(),
                          ws_port=int(speaker.get("ws_port") or 8082))


def test_reachable(speaker: dict[str, Any], timeout: float = 4.0) -> tuple[bool, str]:
    """Thử chạm tới loa (TCP) — dùng cho nút 'Kiểm tra' trên UI."""
    import socket

    kind = str(speaker.get("kind") or "").lower()
    if kind == "ha":
        try:
            from services.ha_client import get_state
            st = get_state(str(speaker.get("entity_id") or ""))
            if not st:
                return False, "HA không có entity này."
            return True, f"HA ok (state={st.get('state')})"
        except Exception as exc:
            return False, str(exc)[:120]
    if kind == "r1":
        from services.voice import r1 as _r1
        return _r1.test_reachable(str(speaker.get("host") or ""),
                                  port=int(speaker.get("port") or 8080))
    host = str(speaker.get("host") or "").strip()
    if host.startswith("http"):
        p = urlparse(host)
        host, port = (p.hostname or ""), int(p.port or 80)
    elif ":" in host:
        host, _, raw_port = host.partition(":")
        port = int(raw_port or 0)
    else:
        port = int(speaker.get("port") or (8009 if kind == "cast" else 49152))
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"Kết nối được {host}:{port}"
    except Exception as exc:
        return False, f"Không chạm tới {host}:{port} ({str(exc)[:80]})"


def _prefix_of(ip: str) -> str:
    """'192.168.1.10' → '192.168.1'. Rỗng nếu không phải IPv4."""
    ip = str(ip or "").strip()
    if ip.startswith("http"):
        ip = urlparse(ip).hostname or ""
    else:
        ip = ip.split(":")[0]
    parts = ip.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return ".".join(parts[:3])
    return ""


def _cast_name(ip: str, timeout: float = 1.2) -> str:
    """Hỏi tên thân thiện của thiết bị Cast qua eureka_info (cổng 8008)."""
    import urllib.request
    try:
        url = f"http://{ip}:8008/setup/eureka_info?params=name"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return str((data or {}).get("name") or "").strip()
    except Exception:
        return ""


def _ssdp_search(st: str, timeout: float = 3.0, mx: int = 2, want: int = 12) -> list[str]:
    """M-SEARCH active SSDP → danh sách URL mô tả (LOCATION). Reply là UNICAST nên
    thường vẫn về được qua NAT bridge (khác NOTIFY multicast bị chặn). Rỗng nếu
    mạng chặn hẳn multicast."""
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
           'MAN: "ssdp:discover"\r\n' f"MX: {mx}\r\nST: {st}\r\n\r\n").encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    except OSError:
        pass
    s.settimeout(timeout)
    locations: set[str] = set()
    try:
        s.sendto(msg, ("239.255.255.250", 1900))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, _ = s.recvfrom(65507)
            except socket.timeout:
                break
            for line in data.decode("utf-8", "replace").split("\r\n")[1:]:
                if line.lower().startswith("location:"):
                    locations.add(line.split(":", 1)[1].strip())
            if len(locations) >= want:
                break
    except OSError:
        pass
    finally:
        s.close()
    return list(locations)


def _parse_dlna_desc(location: str, timeout: float = 3.0) -> Optional[dict[str, Any]]:
    """Lấy tên + control URL AVTransport từ mô tả UPnP của một DLNA renderer."""
    import urllib.request
    import xml.etree.ElementTree as ET
    from urllib.parse import urljoin

    try:
        with urllib.request.urlopen(location, timeout=timeout) as r:
            raw = r.read()
        root = ET.fromstring(raw)
    except Exception:
        return None

    def _local(t: str) -> str:
        return t.split("}", 1)[-1]

    name = base = ctrl = ""
    is_renderer = False
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "friendlyName" and el.text and not name:
            name = el.text.strip()
        elif tag == "URLBase" and el.text and not base:
            base = el.text.strip()
        elif tag == "deviceType" and el.text and "MediaRenderer" in el.text:
            is_renderer = True
    for svc in root.iter():
        if _local(svc.tag) != "service":
            continue
        stype = curl = ""
        for c in svc:
            lt = _local(c.tag)
            if lt == "serviceType":
                stype = c.text or ""
            elif lt == "controlURL":
                curl = c.text or ""
        if "AVTransport" in stype and curl:
            ctrl = urljoin(base or location, curl)
            break
    if not ctrl and not is_renderer:
        return None
    host = urlparse(location).hostname or ""
    return {"host": host, "name": name or f"DLNA {host}", "kind": "dlna",
            "control_url": ctrl, "port": urlparse(location).port or 0}


def discover_lan(subnets: Optional[list[str]] = None,
                 hint_hosts: Optional[list[str]] = None,
                 kind: Optional[str] = None,
                 timeout: float = 0.4, workers: int = 128) -> list[dict[str, Any]]:
    """Dò loa trong LAN theo LOẠI (kind = cast | dlna | r1 | all, mặc định all).

      • cast/r1: quét TCP cổng cố định (Cast 8009, R1 8082). Container bridge vẫn
        nối tới IP LAN được nên quét đơn ra. R1 dò thấy 8082 nhưng control ở 8080.
      • dlna: SSDP M-SEARCH (MediaRenderer) vì cổng UPnP động — trả kèm control_url
        để phát thẳng. Nếu mạng chặn multicast thì rỗng (nhập tay / nhập từ HA).

    subnets/hint_hosts chỉ cần cho quét TCP (cast/r1)."""
    from concurrent.futures import ThreadPoolExecutor

    kind = (kind or "all").strip().lower()
    have_hosts = {str(r.get("host") or "").split(":")[0] for r in list_speakers()}
    hits: list[dict[str, Any]] = []

    # ── DLNA qua SSDP ──
    if kind in ("all", "dlna"):
        seen: set[str] = set()
        for loc in _ssdp_search("urn:schemas-upnp-org:device:MediaRenderer:1"):
            d = _parse_dlna_desc(loc)
            if d and d["host"] and d["host"] not in seen:
                seen.add(d["host"])
                hits.append(d)

    # ── Cast / R1 qua quét TCP cổng cố định ──
    scan_ports = [pk for pk in ((8009, "cast"), (8082, "r1"))
                  if kind in ("all", pk[1])]
    if scan_ports:
        prefixes: set[str] = set()
        for p in (subnets or []):
            pref = _prefix_of(p) or (p if p.count(".") == 2 else "")
            if pref:
                prefixes.add(pref)
        if not prefixes:
            for r in list_speakers():
                pref = _prefix_of(str(r.get("host") or ""))
                if pref:
                    prefixes.add(pref)
            for h in (hint_hosts or []):
                pref = _prefix_of(h)
                if pref:
                    prefixes.add(pref)
        if not prefixes and kind != "all":
            raise RuntimeError(
                "Chưa biết dải mạng để quét. Thêm 1 loa bằng IP trước, hoặc điền "
                "'URL công khai gateway' trong cấu hình để em biết dải LAN.")
        found_hosts = {h["host"] for h in hits}
        targets = [(f"{pref}.{i}", port, k)
                   for pref in sorted(prefixes) for i in range(1, 255)
                   for port, k in scan_ports]

        def _probe(t: tuple[str, int, str]) -> Optional[dict[str, Any]]:
            ip, port, k = t
            try:
                with socket.create_connection((ip, port), timeout=timeout):
                    return {"host": ip, "port": port, "kind": k}
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for res in pool.map(_probe, targets):
                if not res or res["host"] in found_hosts:
                    continue
                found_hosts.add(res["host"])
                if res["kind"] == "cast":
                    res["name"] = _cast_name(res["host"]) or f"Cast {res['host']}"
                else:
                    res["port"] = 8080     # dò thấy 8082 (nhạc) nhưng control là 8080
                    res["name"] = f"R1 {res['host']}"
                hits.append(res)

    for h in hits:
        h["known"] = h["host"] in have_hosts
    return hits


def import_from_ha() -> list[dict[str, Any]]:
    """Nhập media_player từ HA thành loa kiểu 'ha' (bỏ qua cái đã có)."""
    from services.ha_client import get_states

    added: list[dict[str, Any]] = []
    have = {str(r.get("entity_id") or "") for r in list_speakers()}
    for st in (get_states() or []):
        eid = str(st.get("entity_id") or "")
        if not eid.startswith("media_player.") or eid in have:
            continue
        name = str((st.get("attributes") or {}).get("friendly_name") or eid)
        try:
            added.append(add(name, "ha", entity_id=eid, note="nhập từ Home Assistant"))
        except Exception:
            continue
    return added


def _reset_for_tests(path: Path | None = None) -> None:
    global _PATH, _data, _loaded
    with _lock:
        if path is not None:
            _PATH = Path(path)
        _data = {}
        _loaded = False
