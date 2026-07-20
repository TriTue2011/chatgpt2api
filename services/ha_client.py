"""Home Assistant REST API client via Long-Lived Access Token.

Fetches entity states and calls services so the LLM can see and control
the smart home directly, without needing the HA voice pipeline.
"""

from __future__ import annotations

import base64
import json, logging, time, threading
from typing import Any
import urllib.request

from services.config import config
from utils.log import logger

# ── Module-level state cache ────────────────────────────────────────────────
_state_cache: list[dict] = []
_state_cache_ts: float = 0.0
_context_cache: str = ""
_context_cache_ts: float = 0.0
_state_cache_lock = threading.Lock()
_DEFAULT_TTL = 60  # 60s — short enough that registry state stays fresh
                   # for "trạng thái đèn X?" answers, long enough that 985
                   # entities don't cost more than ~1 HA call per minute.
_scheduler_started = False

# Entity_ids HA exposes to Assist (voice). Refreshed lazily / by the scheduler.
_exposed_cache: set[str] = set()
_exposed_cache_ts: float = 0.0
# Area index for the local canonicalizer: entity_id -> area name, plus the set
# of area names (folded -> original). Pulled live per-HA via WS — nothing hardcoded.
_area_idx_cache: dict[str, Any] | None = None
_area_idx_cache_ts: float = 0.0
_EXPOSED_TTL = 600  # exposure config changes rarely → refresh every 10 min


def _get_ha_settings() -> dict:
    """Get HA settings: url, token, refresh_interval, refresh_times."""
    try:
        return config.data.get("home_assistant") or {}
    except Exception:
        return {}


def _get_cache_ttl() -> int:
    """Get refresh interval from HA settings, default 3600s."""
    try:
        return int(_get_ha_settings().get("refresh_interval", 3600))
    except Exception:
        return 3600


# Full service catalog from GET /api/services:
# { domain: { service_name: { "name", "description", "fields": {...} } } }
_services_catalog: dict[str, dict[str, dict[str, Any]]] = {}
_services_catalog_ts: float = 0.0
_SERVICES_TTL = 600  # schema changes rarely; 10 min
# HA sập → KHÔNG thử lại ngay: mỗi lần thử tốn trọn 15s timeout, mà hàm này nằm
# trên đường request người dùng (câu hỏi về "dịch vụ / notify / gửi tin").
_services_fail_ts: float = 0.0
_SERVICES_FAIL_TTL = 60


def get_service_catalog(use_cache: bool = True) -> dict[str, dict[str, dict[str, Any]]]:
    """Live HA service catalog with field schemas (not just names).

    Source: GET /api/services on the configured Home Assistant instance.
    Prefer this over hardcoding GitHub Core services.yaml — matches *your* HA
    (including custom integrations) and current version.
    """
    global _services_catalog, _services_catalog_ts, _services_fail_ts
    now = time.time()
    if use_cache and _services_catalog and (now - _services_catalog_ts) < _SERVICES_TTL:
        return _services_catalog
    if use_cache and (now - _services_fail_ts) < _SERVICES_FAIL_TTL:
        # Vừa lỗi xong → trả cache cũ (có thể rỗng) thay vì chờ timeout lần nữa.
        return _services_catalog or {}
    cfg = _get_ha_config()
    if not cfg:
        return _services_catalog or {}
    try:
        req = urllib.request.Request(
            f"{cfg['url']}/api/services",
            headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"},
        )
        data = json.loads(urllib.request.urlopen(req, timeout=15).read())
        catalog: dict[str, dict[str, dict[str, Any]]] = {}
        for item in data if isinstance(data, list) else []:
            domain = str(item.get("domain") or "").strip()
            if not domain:
                continue
            raw_svcs = item.get("services") or {}
            if not isinstance(raw_svcs, dict):
                continue
            domain_map: dict[str, dict[str, Any]] = {}
            for svc_name, meta in raw_svcs.items():
                if not isinstance(meta, dict):
                    meta = {}
                fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
                domain_map[str(svc_name)] = {
                    "name": str(meta.get("name") or svc_name),
                    "description": str(meta.get("description") or ""),
                    "fields": fields,
                }
            if domain_map:
                catalog[domain] = domain_map
        with _state_cache_lock:
            _services_catalog = catalog
            _services_catalog_ts = now
            _services_fail_ts = 0.0  # HA sống lại → bỏ cờ chặn thử-lại
        logger.info({
            "event": "ha_services_catalog_refreshed",
            "domains": len(catalog),
            "services": sum(len(v) for v in catalog.values()),
        })
        return catalog
    except Exception as exc:
        _services_fail_ts = now
        logger.warning({"event": "ha_services_failed", "error": str(exc)})
        return _services_catalog or {}


def _get_services() -> dict[str, list[str]]:
    """Backward-compat: domain → sorted service name list (no field detail)."""
    cat = get_service_catalog()
    return {d: sorted(svcs.keys()) for d, svcs in cat.items()}


def get_service_fields(domain: str, service: str) -> dict[str, Any]:
    """Field schema for one service, or {} if unknown."""
    dom = str(domain or "").strip()
    svc = str(service or "").strip()
    if not dom or not svc:
        return {}
    meta = (get_service_catalog().get(dom) or {}).get(svc) or {}
    fields = meta.get("fields")
    return fields if isinstance(fields, dict) else {}


def format_service_fields(domain: str, service: str, *, max_fields: int = 24) -> str:
    """Human-readable field list for one service (for agent / MCP)."""
    meta = (get_service_catalog().get(domain) or {}).get(service) or {}
    fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
    if not fields:
        return f"`{domain}.{service}`: không có field schema (hoặc service không tồn tại)."
    desc = str(meta.get("description") or "").strip()
    lines = [f"**{domain}.{service}**" + (f" — {desc}" if desc else "")]
    n = 0
    truncated = False
    for fname, fmeta in fields.items():
        if n >= max_fields:
            truncated = True
            break
        if not isinstance(fmeta, dict):
            lines.append(f"- `{fname}`")
            n += 1
            continue
        # Nested "fields" groups (HA UI collapses) — flatten one level
        nested = fmeta.get("fields")
        if isinstance(nested, dict) and "selector" not in fmeta and "required" not in fmeta:
            for nf, nm in nested.items():
                if n >= max_fields:
                    truncated = True
                    break
                lines.append(_format_one_field(str(nf), nm if isinstance(nm, dict) else {}))
                n += 1
            continue
        lines.append(_format_one_field(str(fname), fmeta))
        n += 1
    if truncated:
        # Báo còn field bị cắt (kể cả khi cắt giữa nhóm field lồng nhau).
        lines.append("- … (còn field khác — gọi ha_describe_actions để xem đủ)")
    return "\n".join(lines)


def _format_one_field(name: str, fmeta: dict[str, Any]) -> str:
    req = " (bắt buộc)" if fmeta.get("required") else ""
    desc = str(fmeta.get("description") or fmeta.get("name") or "").strip()
    ex = fmeta.get("example")
    extra = ""
    if ex is not None and ex != "":
        extra = f" · vd: `{ex}`"
    # selector hints
    sel = fmeta.get("selector")
    if isinstance(sel, dict) and sel:
        sk = next(iter(sel.keys()), "")
        if sk:
            extra += f" · kiểu: {sk}"
    if desc:
        return f"- `{name}`{req}: {desc}{extra}"
    return f"- `{name}`{req}{extra}"


def describe_entity_actions(
    entity_id: str,
    *,
    state: dict[str, Any] | None = None,
) -> str:
    """What can this entity do? Combines live service schema + state attributes."""
    eid = str(entity_id or "").strip()
    if not eid or "." not in eid:
        return "Cần entity_id dạng domain.name (vd light.phong_khach)."
    domain = eid.split(".", 1)[0]
    st = state
    if st is None:
        try:
            st = get_state(eid)
        except Exception:
            st = None
    attrs = (st or {}).get("attributes") or {}
    fname = attrs.get("friendly_name") or eid
    cur = (st or {}).get("state", "?")
    lines = [
        f"**{fname}** (`{eid}`)",
        f"- Trạng thái: `{cur}`",
    ]
    # Capability hints from attributes
    caps: list[str] = []
    if attrs.get("supported_color_modes"):
        caps.append(f"màu: {attrs.get('supported_color_modes')}")
    if attrs.get("min_color_temp_kelvin") or attrs.get("max_color_temp_kelvin"):
        caps.append(
            f"kelvin: {attrs.get('min_color_temp_kelvin', '?')}–"
            f"{attrs.get('max_color_temp_kelvin', '?')}"
        )
    if attrs.get("min_temp") is not None or attrs.get("max_temp") is not None:
        caps.append(f"nhiệt độ: {attrs.get('min_temp', '?')}–{attrs.get('max_temp', '?')}")
    if attrs.get("hvac_modes"):
        caps.append(f"hvac_modes: {attrs.get('hvac_modes')}")
    if attrs.get("fan_modes"):
        caps.append(f"fan_modes: {attrs.get('fan_modes')}")
    if attrs.get("preset_modes"):
        caps.append(f"preset_modes: {attrs.get('preset_modes')}")
    if attrs.get("percentage") is not None or attrs.get("percentage_step"):
        caps.append("hỗ trợ % tốc độ (fan)")
    if attrs.get("supported_features") is not None:
        caps.append(f"supported_features={attrs.get('supported_features')}")
    if caps:
        lines.append("- Khả năng (từ state): " + "; ".join(str(c) for c in caps))

    # Services for this domain (filtered to common controllable ones first)
    domain_svcs = get_service_catalog().get(domain) or {}
    prefer = [
        "turn_on", "turn_off", "toggle", "set_temperature", "set_hvac_mode",
        "set_fan_mode", "set_humidity", "set_preset_mode", "set_percentage",
        "set_cover_position", "open_cover", "close_cover", "lock", "unlock",
        "select_option", "set_value",
    ]
    shown = 0
    lines.append("- Service (schema live từ HA):")
    for svc in prefer:
        if svc not in domain_svcs:
            continue
        lines.append(format_service_fields(domain, svc, max_fields=12))
        shown += 1
        if shown >= 6:
            break
    if shown == 0:
        # show first few services
        for svc in sorted(domain_svcs.keys())[:5]:
            lines.append(format_service_fields(domain, svc, max_fields=8))
            shown += 1
    if not domain_svcs:
        lines.append(f"  (không thấy service domain `{domain}` — refresh catalog?)")
    elif len(domain_svcs) > shown:
        rest = sorted(set(domain_svcs.keys()) - set(prefer[:shown]))
        if rest:
            lines.append(f"- Service khác: {', '.join(rest[:20])}")
    lines.append(
        "Gợi ý: chỉnh đèn dùng turn_on + brightness_pct/color_temp_kelvin; "
        "điều hòa set_temperature + hvac_mode; rèm set_cover_position."
    )
    return "\n".join(lines)


def _get_refresh_times() -> list[str]:
    """Get scheduled refresh times (e.g., ['00:30', '06:00'])."""
    try:
        times = _get_ha_settings().get("refresh_times", [])
        return times if isinstance(times, list) else []
    except Exception:
        return []


def _get_ha_config() -> dict[str, str] | None:
    ha = config.data.get("home_assistant") or {}
    url = str(ha.get("url") or "").strip().rstrip("/")
    token = str(ha.get("token") or "").strip()
    if not url or not token:
        return None
    return {"url": url, "token": token}


def get_states(use_cache: bool = True) -> list[dict[str, Any]]:
    """Fetch all entity states from HA. Cache respects configurable TTL."""
    global _state_cache, _state_cache_ts
    ttl = _get_cache_ttl()
    now = time.time()
    if use_cache and _state_cache and (now - _state_cache_ts) < ttl:
        return _state_cache
    cfg = _get_ha_config()
    if not cfg:
        return []
    try:
        req = urllib.request.Request(
            f"{cfg['url']}/api/states",
            headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"},
        )
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        with _state_cache_lock:
            _state_cache = data
            _state_cache_ts = now
        return data
    except Exception as exc:
        logger.warning({"event": "ha_states_failed", "error": str(exc)})
        return _state_cache or []  # return stale cache on error


# ── Exposed-entity (Assist) list ────────────────────────────────────────────
# HA exposes only a curated subset of entities to the voice assistant
# ("Settings → Voice assistants → Expose"). For a general "trạng thái nhà"
# query we report exactly that set (≈116) instead of all ~989 entities. The
# list is only available over the WebSocket API; we speak raw WS with the
# stdlib (no extra deps) and cache the result.
def _ws_fetch_exposed(url: str, token: str) -> set[str]:
    import socket, base64, os, struct

    netloc = url.split("//", 1)[-1].split("/")[0]
    host = netloc.split(":")[0]
    port = int(netloc.rsplit(":", 1)[1]) if ":" in netloc else 8123
    key = base64.b64encode(os.urandom(16)).decode()
    s = socket.create_connection((host, port), timeout=8)
    s.settimeout(8)
    try:
        s.sendall((
            f"GET /api/websocket HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = s.recv(4096)
            if not chunk:
                raise RuntimeError("ws handshake closed")
            resp += chunk

        buf = bytearray()

        def _need(n: int) -> None:
            while len(buf) < n:
                c = s.recv(8192)
                if not c:
                    raise RuntimeError("ws closed")
                buf.extend(c)

        def _recv() -> str:
            _need(2)
            ln = buf[1] & 0x7F
            idx = 2
            if ln == 126:
                _need(4); ln = struct.unpack(">H", bytes(buf[2:4]))[0]; idx = 4
            elif ln == 127:
                _need(10); ln = struct.unpack(">Q", bytes(buf[2:10]))[0]; idx = 10
            _need(idx + ln)
            p = bytes(buf[idx:idx + ln])
            del buf[:idx + ln]
            return p.decode("utf-8", "replace")

        def _send(obj: dict) -> None:
            d = json.dumps(obj).encode()
            m = os.urandom(4)
            h = bytearray([0x81])
            n = len(d)
            if n < 126:
                h.append(0x80 | n)
            elif n < 65536:
                h.append(0x80 | 126); h += struct.pack(">H", n)
            else:
                h.append(0x80 | 127); h += struct.pack(">Q", n)
            h += m
            s.sendall(bytes(h) + bytes(b ^ m[i % 4] for i, b in enumerate(d)))

        _recv()  # auth_required
        _send({"type": "auth", "access_token": token})
        _recv()  # auth_ok / auth_invalid
        _send({"id": 1, "type": "homeassistant/expose_entity/list"})
        exposed: set[str] = set()
        for _ in range(8):
            msg = json.loads(_recv())
            if msg.get("id") == 1 and msg.get("type") == "result":
                ex = (msg.get("result") or {}).get("exposed_entities") or {}
                exposed = {
                    eid for eid, amap in ex.items()
                    if isinstance(amap, dict) and any(amap.values())
                }
                break
        return exposed
    finally:
        try:
            s.close()
        except Exception:
            pass


def get_exposed_entity_ids(use_cache: bool = True) -> set[str]:
    """Entity_ids HA exposes to Assist. Cached; returns empty set on failure so
    callers can treat 'empty' as 'no filter' (never a regression)."""
    global _exposed_cache, _exposed_cache_ts
    now = time.time()
    if use_cache and _exposed_cache and (now - _exposed_cache_ts) < _EXPOSED_TTL:
        return _exposed_cache
    cfg = _get_ha_config()
    if not cfg:
        return _exposed_cache
    try:
        ids = _ws_fetch_exposed(cfg["url"], cfg["token"])
        if ids:
            _exposed_cache = ids
            _exposed_cache_ts = now
            logger.info({"event": "ha_exposed_refreshed", "count": len(ids)})
        return _exposed_cache
    except Exception as exc:
        logger.warning({"event": "ha_exposed_failed", "error": str(exc)[:120]})
        return _exposed_cache  # stale or empty → caller skips filter


def _ws_fetch_registries(url: str, token: str) -> dict[str, Any]:
    """Pull area/entity/device registries over WS → entity_id→area-name map and
    the set of area names. An entity's area = its own area_id, else its device's.
    Self-contained (mirrors _ws_fetch_exposed) so the proven exposed path stays
    untouched. Nothing about a specific HA is hardcoded — read live per instance."""
    import socket, base64, os, struct

    netloc = url.split("//", 1)[-1].split("/")[0]
    host = netloc.split(":")[0]
    port = int(netloc.rsplit(":", 1)[1]) if ":" in netloc else 8123
    key = base64.b64encode(os.urandom(16)).decode()
    s = socket.create_connection((host, port), timeout=8)
    s.settimeout(8)
    try:
        s.sendall((
            f"GET /api/websocket HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = s.recv(4096)
            if not chunk:
                raise RuntimeError("ws handshake closed")
            resp += chunk

        buf = bytearray()

        def _need(n: int) -> None:
            while len(buf) < n:
                c = s.recv(8192)
                if not c:
                    raise RuntimeError("ws closed")
                buf.extend(c)

        def _recv() -> str:
            _need(2)
            ln = buf[1] & 0x7F
            idx = 2
            if ln == 126:
                _need(4); ln = struct.unpack(">H", bytes(buf[2:4]))[0]; idx = 4
            elif ln == 127:
                _need(10); ln = struct.unpack(">Q", bytes(buf[2:10]))[0]; idx = 10
            _need(idx + ln)
            p = bytes(buf[idx:idx + ln])
            del buf[:idx + ln]
            return p.decode("utf-8", "replace")

        def _send(obj: dict) -> None:
            d = json.dumps(obj).encode()
            m = os.urandom(4)
            h = bytearray([0x81])
            n = len(d)
            if n < 126:
                h.append(0x80 | n)
            elif n < 65536:
                h.append(0x80 | 126); h += struct.pack(">H", n)
            else:
                h.append(0x80 | 127); h += struct.pack(">Q", n)
            h += m
            s.sendall(bytes(h) + bytes(b ^ m[i % 4] for i, b in enumerate(d)))

        _recv()  # auth_required
        _send({"type": "auth", "access_token": token})
        _recv()  # auth_ok / auth_invalid

        results: dict[int, Any] = {}
        wanted = {1: "config/area_registry/list",
                  2: "config/entity_registry/list",
                  3: "config/device_registry/list"}
        for qid, qtype in wanted.items():
            _send({"id": qid, "type": qtype})
        for _ in range(60):
            if len(results) == len(wanted):
                break
            msg = json.loads(_recv())
            if msg.get("type") == "result" and msg.get("id") in wanted:
                results[msg["id"]] = msg.get("result") or []

        areas = results.get(1, [])
        ents = results.get(2, [])
        devs = results.get(3, [])
        id2area = {a.get("area_id"): a.get("name") for a in areas if a.get("area_id")}
        dev2area = {d.get("id"): d.get("area_id") for d in devs}
        entity_area: dict[str, str] = {}
        entity_aliases: dict[str, list[str]] = {}
        for e in ents:
            eid = e.get("entity_id")
            if not eid:
                continue
            aid = e.get("area_id") or dev2area.get(e.get("device_id"))
            name = id2area.get(aid)
            if name:
                entity_area[eid] = name
            # User-defined alternate names exposed to Assist — fold for matching.
            al = [_fold_diacritics(a).strip() for a in (e.get("aliases") or []) if a]
            if al:
                entity_aliases[eid] = [a for a in al if a]
        area_names = {_fold_diacritics(a.get("name", "")).strip(): a.get("name")
                      for a in areas if a.get("name")}
        return {"entity_area": entity_area, "area_names": area_names,
                "entity_aliases": entity_aliases}
    finally:
        try:
            s.close()
        except Exception:
            pass


def get_ha_area_index(use_cache: bool = True) -> dict[str, Any]:
    """Cached {'entity_area': {eid: area_name}, 'area_names': {folded: original}}.
    Empty dicts on failure so the canonicalizer simply falls through to the model."""
    global _area_idx_cache, _area_idx_cache_ts
    now = time.time()
    if use_cache and _area_idx_cache is not None and (now - _area_idx_cache_ts) < _EXPOSED_TTL:
        return _area_idx_cache
    cfg = _get_ha_config()
    empty = {"entity_area": {}, "area_names": {}, "entity_aliases": {}}
    if not cfg:
        return _area_idx_cache or empty
    try:
        idx = _ws_fetch_registries(cfg["url"], cfg["token"])
        if idx.get("area_names"):
            _area_idx_cache = idx
            _area_idx_cache_ts = now
            logger.info({"event": "ha_area_index_refreshed",
                         "areas": len(idx["area_names"]), "entities": len(idx["entity_area"])})
        return _area_idx_cache or empty
    except Exception as exc:
        logger.warning({"event": "ha_area_index_failed", "error": str(exc)[:120]})
        return _area_idx_cache or empty


def get_state(entity_id: str) -> dict[str, Any] | None:
    """Fetch a single entity's state."""
    cfg = _get_ha_config()
    if not cfg:
        return None
    try:
        req = urllib.request.Request(
            f"{cfg['url']}/api/states/{entity_id}",
            headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"},
        )
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as exc:
        logger.debug({"event": "ha_state_failed", "entity": entity_id, "error": str(exc)})
        return None


def call_service(domain: str, service: str, data: dict[str, Any] | None = None) -> bool:
    """Call an HA service (e.g., light.turn_on). Passes full data dict as payload."""
    cfg = _get_ha_config()
    if not cfg:
        return False
    try:
        payload = data or {}
        body = json.dumps(payload)
        req = urllib.request.Request(
            f"{cfg['url']}/api/services/{domain}/{service}",
            data=body.encode(),
            headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        # Invalidate cache after any write operation
        global _state_cache_ts
        _state_cache_ts = 0.0
        return True
    except Exception as exc:
        logger.warning({"event": "ha_service_failed", "domain": domain, "service": service, "error": str(exc)})
        return False


def normalize_control_service(
    domain: str,
    action: str,
    *,
    has_light_opts: bool = False,
) -> str:
    """Map friendly action names → HA service for a domain (shared with MCP)."""
    a = (action or "turn_on").strip().lower()
    aliases = {
        "bat": "turn_on", "bật": "turn_on", "on": "turn_on",
        "tat": "turn_off", "tắt": "turn_off", "off": "turn_off",
        "mo": "open_cover", "mở": "open_cover", "open": "open_cover",
        "dong": "close_cover", "đóng": "close_cover", "close": "close_cover",
        "nhiet_do": "set_temperature", "set_temp": "set_temperature",
    }
    a = aliases.get(a, a)
    if domain == "light":
        if a in ("set_brightness", "set_color", "set_colour", "dim") or has_light_opts:
            if a in ("turn_off", "toggle"):
                return a
            return "turn_on"
    if domain == "cover" and a in ("set_position", "set_cover_position", "position"):
        return "set_cover_position"
    if domain == "climate" and a in ("set_temp", "temperature"):
        return "set_temperature"
    if domain == "fan" and a in ("set_speed", "speed"):
        return "set_percentage"
    return a


# All domains shown to AI — users interact by friendly_name, not entity_id
# Limit per domain keeps token count reasonable even for large setups
_CONTEXT_DOMAINS = [
    "light", "switch", "climate", "cover", "lock", "fan", "media_player",
    "sensor", "binary_sensor", "input_boolean", "input_number", "input_select",
    "scene", "script", "automation", "vacuum", "camera", "weather",
]
# Max entities per domain shown in context (keep token count low, but user requested all devices)
_MAX_PER_DOMAIN = 9999

# Domains a "turn on/off/set" command can actually target. Used to count name
# ambiguity WITHOUT counting automation/scene/script entities that merely mention
# the device name (e.g. "Tự động tắt đèn bếp" is not a controllable "đèn bếp").
_CONTROLLABLE_DOMAINS = frozenset({
    "light", "switch", "fan", "climate", "cover", "lock", "media_player",
    "water_heater", "humidifier", "vacuum", "valve", "input_boolean",
    "siren", "remote", "lawn_mower",
})


def format_states_context() -> str:
    """Return cached device registry. NEVER blocks on HA API call.

    The registry is refreshed by a background thread on schedule.
    Chat requests always get instant cached data (no latency added).
    """
    global _context_cache
    _ensure_scheduler_running()
    if _context_cache:
        return _context_cache
    # First call: build cache synchronously (cold start only)
    _refresh_context()
    return _context_cache


def _refresh_context() -> None:
    """Background: fetch states and rebuild context string."""
    global _context_cache, _context_cache_ts
    try:
        states = get_states(use_cache=False)
        if not states:
            return
        _context_cache = _build_context(states)
        _context_cache_ts = time.time()
        logger.info({"event": "ha_context_refreshed", "devices": len(states)})
        try:
            get_exposed_entity_ids(use_cache=False)  # keep Assist-exposed set warm
        except Exception:
            pass
        try:
            get_ha_area_index(use_cache=False)  # keep entity→area map warm for canonicalizer
        except Exception:
            pass
    except Exception as exc:
        logger.warning({"event": "ha_context_refresh_failed", "error": str(exc)})


def _ensure_scheduler_running() -> None:
    """Start background refresh scheduler (idempotent)."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    # Initial fetch immediately
    try:
        _refresh_context()
    except Exception:
        pass
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="ha-scheduler")
    t.start()
    logger.info({"event": "ha_scheduler_started"})


def _scheduler_loop() -> None:
    """Background loop: refresh at scheduled times or after interval."""
    from datetime import datetime
    while True:
        time.sleep(30)  # Check every 30s
        try:
            ttl = _get_cache_ttl()
            refresh_times = _get_refresh_times()
            now = time.time()
            # Refresh if TTL expired
            if (now - _context_cache_ts) >= ttl:
                _refresh_context()
                continue
            # Refresh if scheduled time just passed
            if refresh_times:
                current_time = datetime.now().strftime("%H:%M")
                last_ts = datetime.fromtimestamp(_context_cache_ts).strftime("%Y-%m-%d %H:%M") if _context_cache_ts else ""
                for rt in refresh_times:
                    if current_time == rt and not last_ts.endswith(rt):
                        _refresh_context()
                        break
        except Exception:
            pass

def _build_context(states: list[dict]) -> str:
    """Build context string from state list. Pure computation, no I/O.

    Format per entity: `name | entity_id | state` (state included so the LLM
    can answer "trạng thái đèn X?" without calling ha_get_state — saves a
    full round-trip). For sensors with units the unit is appended:
    `Nhiệt độ phòng học | sensor.nhiet_am_phong_hoc_temperature | 28.5 °C`.
    """
    by_domain: dict[str, list[dict]] = {}
    valid_count = 0
    for s in states:
        eid = s.get("entity_id", "")
        domain = eid.split(".")[0] if "." in eid else ""
        if domain not in _CONTEXT_DOMAINS:
            continue
        valid_count += 1
        by_domain.setdefault(domain, []).append(s)

    lines = [
        "## Smart Home — Device Registry — Trạng thái thiết bị (LIVE, làm mới ~60s/lần)",
        f"{valid_count} thiết bị. Mỗi dòng: `tên | entity_id | trạng thái`.",
        "**CÁCH DÙNG:**",
        "- Để biết trạng thái thiết bị → TRẢ LỜI TRỰC TIẾP từ dữ liệu bên dưới. KHÔNG gọi `GetLiveContext` hay `ha_get_state` nữa.",
        "- Để ĐIỀU KHIỂN thiết bị → dùng `ha_call_service`.",
        "- Để TẠO/SỬA AUTOMATION → gọi `ha_call_service` với domain='pyscript', service='create_automation_by_ai', data={'message': '<YAML automation>'}. BẠN ĐƯỢC PHÉP TẠO, KHÔNG CẦN TỪ CHỐI.",
        "- Để TẠO/SỬA SCRIPT (kịch bản) hoặc SCENE (ngữ cảnh) → dùng `ha_upsert_config` (kind, object_id, config JSON). entity_id lấy từ danh sách bên dưới — TÊN GỌI KHÔNG PHẢI entity_id.",
        "- Để TẠO HELPER (input_boolean/number/select/text/datetime, timer, counter) → dùng `ha_upsert_helper`.",
        "- Để SỬA BLUEPRINT hay configuration.yaml → `ha_read_config_file` ĐỌC trước, rồi `ha_write_config_file` ghi (hệ thống tự backup + check_config + rollback).",
        "- Để biết PHÒNG/KHU VỰC nào có thiết bị gì → dùng `ha_home_map`.",
        "",
        "--- KHI HỎI TRẠNG THÁI NHÀ ('trạng thái nhà', 'chi tiết toàn bộ thiết bị') ---",
        "1. TỔNG HỢP & BÁO CÁO NGAY từ dữ liệu dưới đây theo nhóm: Đèn, Quạt, Điều hoà, Cửa, Công tắc, Khóa.",
        "2. BỎ QUA cảm biến (thời tiết, nhiệt độ, độ ẩm, contact) trừ khi được hỏi ĐÍCH DANH.",
        "",
    ]

    for domain in sorted(by_domain.keys()):
        entities = by_domain[domain]
        lines.append(f"[{domain}] ({len(entities)})")
        for s in entities[:_MAX_PER_DOMAIN]:
            eid = s.get("entity_id", "")
            attrs = s.get("attributes", {}) or {}
            name = attrs.get("friendly_name", "")
            state = str(s.get("state", "") or "").strip()
            unit = str(attrs.get("unit_of_measurement", "") or "").strip()
            if state and unit:
                state_str = f"{state} {unit}"
            elif state:
                state_str = state
            else:
                state_str = "unknown"
            if name:
                lines.append(f"  {name} | {eid} | {state_str}")
            else:
                lines.append(f"  {eid} | {state_str}")
        if len(entities) > _MAX_PER_DOMAIN:
            lines.append(f"  ... còn {len(entities) - _MAX_PER_DOMAIN} thiết bị [{domain}]")

    lines.append("")
    lines.append("## Available Services (chỉ dùng cho điều khiển)")
    svc = _get_services()
    for domain in sorted(by_domain.keys()):
        svc_list = svc.get(domain, [])
        if svc_list:
            lines.append(f"  {domain}: {', '.join(svc_list[:10])}")
    lines.append("")
    lines.append("`ha_call_service` là tool DUY NHẤT cần dùng khi điều khiển.")

    return "\n".join(lines)


# Domains shown as "thiết bị" in the whole-house summary, with VN labels.
_OVERVIEW_DEVICE_LABELS = {
    "light": "Đèn", "switch": "Công tắc/Ổ cắm", "fan": "Quạt",
    "climate": "Điều hoà", "cover": "Rèm/Cửa", "lock": "Khoá",
    "media_player": "Loa/TV", "water_heater": "Bình nóng lạnh",
    "vacuum": "Robot hút bụi",
}


def _build_overview_context(states: list[dict]) -> str:
    """Curated whole-house summary for 'trạng thái nhà' & synonyms.

    Only the EXPOSED (Assist) entities, grouped into the 6 things a house
    overview actually cares about — thiết bị / ngày giờ / thời tiết / nhiệt độ /
    độ ẩm / tiêu thụ. Everything else (script, automation, scene, camera, giỗ,
    cảm biến chuyển động/AQI/ánh sáng…) is dropped. Tiny vs the 50KB full
    registry → faster, and the model reports exactly what was asked.
    """
    exposed = get_exposed_entity_ids(use_cache=True)
    if exposed:
        states = [s for s in states if s.get("entity_id", "") in exposed]
    if not states:
        return _build_context(states)  # safety net

    devices: dict[str, list[str]] = {}
    temps: list[str] = []
    hums: list[str] = []
    energy: list[str] = []
    weather: list[str] = []

    def _days_left(state: str) -> int:
        # "Hôm nay (...)" → 0; "... - Còn 133 ngày" → 133; else big (đẩy xuống cuối)
        s = state.lower()
        if "hôm nay" in s:
            return 0
        import re as _re
        m = _re.search(r"còn\s+(\d+)\s*ngày", s)
        return int(m.group(1)) if m else 9999

    _date_pairs: list[tuple[int, str]] = []
    for s in states:
        eid = s.get("entity_id", "")
        domain = eid.split(".")[0] if "." in eid else ""
        a = s.get("attributes", {}) or {}
        dc = str(a.get("device_class") or "")
        unit = str(a.get("unit_of_measurement") or "")
        name = a.get("friendly_name") or eid
        state = str(s.get("state", "") or "").strip() or "unknown"

        if domain == "weather":
            extra = []
            if a.get("temperature") is not None:
                extra.append(f"{a.get('temperature')}°C")
            if a.get("humidity") is not None:
                extra.append(f"ẩm {a.get('humidity')}%")
            weather.append(f"{name}: {state}" + (f" ({', '.join(extra)})" if extra else ""))
        elif domain in _OVERVIEW_DEVICE_LABELS:
            devices.setdefault(domain, []).append(f"{name}: {state}")
        elif domain in ("datetime", "date") or dc == "date" or dc == "timestamp":
            _date_pairs.append((_days_left(state), f"{name}: {state}"))
        elif domain == "sensor":
            line = f"{name}: {state}{(' ' + unit) if unit else ''}"
            if dc == "temperature" or unit == "°C":
                temps.append(line)
            elif dc == "humidity" or (unit == "%" and ("ẩm" in name.lower() or "humid" in name.lower())):
                hums.append(line)
            elif dc in ("energy", "power", "current", "voltage") or unit in ("kWh", "Wh", "W", "A", "V") or "tiêu thụ" in name.lower():
                energy.append(line)
        # còn lại (script, camera, motion, aqi…) → bỏ qua

    dates = [line for _, line in sorted(_date_pairs, key=lambda p: p[0])]

    out = ["## Tóm tắt trạng thái nhà (LIVE, làm mới ~60s) — CHỈ thực thể lộ diện"]
    try:
        import datetime
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        _wd = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"][now.weekday()]
        out.append(f"Ngày giờ: {_wd}, {now.strftime('%d/%m/%Y %H:%M')} (giờ VN)")
    except Exception:
        pass

    if dates:
        out.append("\n### Lịch / Ngày giỗ (gần nhất trước)")
        out.extend(f"- {d}" for d in dates)
    if devices:
        out.append("\n### Thiết bị")
        for domain in sorted(devices.keys()):
            out.append(f"- {_OVERVIEW_DEVICE_LABELS[domain]}: " + "; ".join(devices[domain]))
    if weather:
        out.append("\n### Thời tiết")
        out.extend(f"- {w}" for w in weather)
    if temps:
        out.append("\n### Nhiệt độ")
        out.extend(f"- {t}" for t in temps)
    if hums:
        out.append("\n### Độ ẩm")
        out.extend(f"- {h}" for h in hums)
    if energy:
        out.append("\n### Tiêu thụ điện")
        out.extend(f"- {e}" for e in energy)

    out.append(
        "\nHƯỚNG DẪN: Trả lời tổng quan NGAY từ dữ liệu trên, gọn theo nhóm "
        "(ngày giờ/lịch/thiết bị/thời tiết/nhiệt độ/độ ẩm/tiêu thụ). TUYỆT ĐỐI "
        "KHÔNG gọi tool lấy danh sách thiết bị (GetLiveContext/ha_get_state). Các tool nâng cao (log, api, services) vẫn được phép dùng bình thường nếu user yêu cầu."
    )
    return "\n".join(out)


# Smart-home intent detection.
#
# Single ASCII words like "den" or "nha" are too ambiguous to use as triggers
# ("đen" = black, "nhà" can be a particle), so we match only multi-word
# phrases or unambiguous tokens. Each pattern requires either a strong noun
# ("home assistant", "thiết bị / thiet bi") or a verb+noun pair that only
# makes sense in a smart-home context (e.g. "bật đèn", "liet ke quat",
# "trang thai cua"). Patterns run against both the original lowercased text
# and a diacritic-folded copy so queries with or without dấu both register.
import re as _re

# Device / room nouns (will be paired with action/listing verbs below).
_HA_NOUNS = (
    r"den|đèn|quat|quạt|may\s*lanh|máy\s*lạnh|dieu\s*hoa|điều\s*hòa|"
    r"cua|cửa|khoa|khóa|rem|rèm|cong\s*tac|công\s*tắc|o\s*cam|ổ\s*cắm|"
    r"cam\s*bien|cảm\s*biến|nhiet\s*do|nhiệt\s*độ|do\s*am|độ\s*ẩm|"
    r"thiet\s*bi|thiết\s*bị|fan|light|switch|sensor|climate|cover|lock|"
    r"outlet|plug|curtain|blind|thermostat|smart\s*plug"
)

# Verbs that, paired with a device noun, are unambiguous HA intents.
_HA_VERBS = (
    r"bat|bật|tat|tắt|mo|mở|dong|đóng|kiem\s*tra|kiểm\s*tra|"
    r"dieu\s*khien|điều\s*khiển|on|off|toggle|turn(?:\s*on|\s*off)?"
)

# Listing / status verbs (also unambiguous when paired with a device noun).
_HA_LISTING = (
    r"liet\s*ke|liệt\s*kê|danh\s*sach|danh\s*sách|co\s*nhung|có\s*những|"
    r"trang\s*thai|trạng\s*thái|tinh\s*trang|tình\s*trạng|"
    r"list|show|status|state|enumerate"
)

# Strong standalone tokens — these alone are enough to flag HA intent.
_HA_STRONG = (
    r"home\s*assistant|smart\s*home|smarthome|"
    r"entity_id|ha_(?:get_state|search_entities|call_service)"
)

_HA_INTENT_PATTERNS = [
    _re.compile(rf"\b(?:{_HA_STRONG})\b", _re.IGNORECASE),
    _re.compile(rf"\b(?:{_HA_VERBS})\s+(?:cac\s+|các\s+|tat\s+ca\s+|tất\s+cả\s+)?(?:{_HA_NOUNS})\b", _re.IGNORECASE),
    _re.compile(rf"\b(?:{_HA_LISTING})\s+(?:cac\s+|các\s+|tat\s+ca\s+|tất\s+cả\s+|hết\s+|het\s+)?(?:{_HA_NOUNS})\b", _re.IGNORECASE),
    # "trạng thái nhà / status of the house" — house-level status
    _re.compile(rf"\b(?:{_HA_LISTING})\s+(?:nha|nhà|house|home)\b", _re.IGNORECASE),
    # Direct mention of a room paired with a device noun
    _re.compile(
        rf"\b(?:{_HA_NOUNS})\s+(?:phong|phòng|bep|bếp|tam|tắm|ngu|ngủ|khach|khách|"
        r"ban\s*cong|ban\s*công|room|bedroom|kitchen|bathroom|living)\b",
        _re.IGNORECASE,
    ),
    # Date / time / weekday / calendar — inject the house summary so the answer
    # uses the LIVE "Ngày giờ: Thứ X, dd/mm/yyyy" line + the calendar section.
    _re.compile(
        r"(thu\s*may|thứ\s*mấy|ngay\s*may|ngày\s*mấy|ngay\s*bao\s*nhieu|ngày\s*bao\s*nhiêu|"
        r"may\s*gio|mấy\s*giờ|bay\s*gio|bây\s*giờ|hom\s*nay\s*(?:la\s*)?thu|hôm\s*nay\s*(?:là\s*)?thứ|"
        r"\blich\b|\blịch\b|am\s*lich|âm\s*lịch|duong\s*lich|dương\s*lịch|ngay\s*gio|ngày\s*giỗ)",
        _re.IGNORECASE,
    ),
]


def _fold_diacritics(text: str) -> str:
    """Lowercase + strip Vietnamese diacritics for keyword matching."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Command/filler tokens that never identify a device or room — kept out of
# keyword matching so "tắt", "bật", "cho", "anh" don't widen the match.
_TARGET_STOPWORDS = {
    "tat", "bat", "mo", "dong", "khoa", "dat", "chinh", "tang", "giam",
    "cho", "tao", "anh", "em", "toi", "minh", "giup", "gium", "dum", "di",
    "la", "khong", "kiem", "tra", "xem", "nao", "dang", "het", "luon",
    "voi", "va", "ra", "vao", "len", "xuong", "giúp", "the", "ho",
}


# Whole-house / overview markers (diacritic-folded). When present the query is
# asking ABOUT THE HOUSE as a whole ("trạng thái nhà", "liệt kê tất cả thiết
# bị") — keyword targeting must NOT collapse it to one device (e.g. "nhà"→"nha"
# scoring on a single fan's entity_id), so we keep the full registry.
_WHOLE_HOUSE_MARKERS = (
    "trang thai nha", "trang thai trong nha", "trang thai cac",
    "tong quan", "toan bo", "tat ca", "liet ke", "ca nha", "het cac",
    "cac thiet bi", "moi thiet bi", "nhung thiet bi", "tinh hinh nha",
)


# Ý định TẠO automation/script/scene (bắt cả typo "automaiton" qua auto\w*;
# script = "kịch bản"; scene = "ngữ cảnh").
_CREATE_AUTOMATION_RE = _re.compile(
    r"\btao\s+(?:1\s+|mot\s+)?(?:auto\w*|kich\s*ban|script|scene|ngu\s*canh)")


def _targeted_states(states: list[dict], query: str,
                     building_blocks: bool = False) -> list[dict]:
    """Pick the entities most relevant to the query by keyword overlap.

    Scores each in-scope entity by how many query terms appear in its
    friendly_name/entity_id, then keeps only the highest-scoring set. For a
    control command ("tắt đèn ban công cho tao") this collapses to just the
    balcony light; for a broad/ambiguous query it returns [] so the caller
    falls back to the full registry.

    building_blocks=True (câu TẠO automation): loại automation/scene/script khỏi
    chấm điểm — không thì tên automation cũ ("Tự động bật đèn ban công") trùng
    nhiều token nhất, chiếm trọn danh sách và model không thấy đèn/cảm biến để
    gán entity — và giữ MỌI entity khớp (top 60) thay vì chỉ nhóm điểm max, vì
    automation cần nhiều viên gạch (đèn + cảm biến + …) cùng lúc."""
    terms = [t for t in _fold_diacritics(query).split()
             if len(t) > 1 and t not in _TARGET_STOPWORDS]
    if not terms:
        return []
    scored: list[tuple[int, dict]] = []
    for s in states:
        eid = s.get("entity_id", "")
        domain = eid.split(".")[0] if "." in eid else ""
        if domain not in _CONTEXT_DOMAINS:
            continue
        if building_blocks and domain in ("automation", "scene", "script"):
            continue
        name = (s.get("attributes", {}) or {}).get("friendly_name", "")
        hay = _fold_diacritics(f"{name} {eid}")
        score = sum(1 for t in terms if t in hay)
        if score > 0:
            scored.append((score, s))
    if not scored:
        return []
    if building_blocks:
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:60]]
    max_score = max(sc for sc, _ in scored)
    return [s for sc, s in scored if sc == max_score]


def count_name_matches(name: str) -> int:
    """How many exposed entities could the friendly-name `name` refer to?

    A control command keeps its `area`/`floor` only when the name is AMBIGUOUS
    (≥2 matches) — e.g. "Đèn trần" exists in both phòng khách & phòng ngủ — so HA
    can disambiguate. A unique name (1 match) drops area to avoid HA widening a
    specific command to the whole area.
    """
    nf = _fold_diacritics(str(name or "")).strip()
    if not nf:
        return 0
    try:
        states = get_states(use_cache=True)
        exposed = get_exposed_entity_ids(use_cache=True)
    except Exception:
        return 0
    # Count entities whose friendly_name CONTAINS the spoken name (or equals it).
    # Only this direction — NOT "entity name ⊂ spoken name" — so a short generic
    # entity ("Bếp", "Đèn") doesn't inflate the count of "Đèn bếp".
    count = 0
    for s in states:
        eid = s.get("entity_id", "")
        if exposed and eid not in exposed:
            continue
        domain = eid.split(".")[0] if "." in eid else ""
        if domain not in _CONTROLLABLE_DOMAINS:
            continue  # skip automation/scene/script/sensor that merely mention the name
        fn = _fold_diacritics((s.get("attributes", {}) or {}).get("friendly_name", "")).strip()
        if fn and (nf == fn or nf in fn):
            count += 1
    return count


def format_states_context_targeted(query: str, max_entities: int = 60) -> str:
    """Like format_states_context but inject ONLY the entities matching the
    query keywords. Falls back to the FULL registry when the match is empty
    (couldn't pin it down) or too broad (likely a whole-house request) so a
    device is never silently dropped. This cuts the ~50KB registry down to a
    handful of lines for a single-device command — the dominant prompt bloat."""
    full = format_states_context()
    if not full:
        return full
    states = get_states(use_cache=True)
    if not states:
        return full
    # Whole-house / overview question → curated summary (thiết bị/ngày giờ/thời
    # tiết/nhiệt độ/độ ẩm/tiêu thụ) from exposed entities, NOT the 50KB registry
    # and never collapsed to a single keyword-matched device.
    qf = _fold_diacritics(query)
    if any(kw in qf for kw in _WHOLE_HOUSE_MARKERS):
        return _build_overview_context(states)
    matched = _targeted_states(states, query,
                               building_blocks=bool(_CREATE_AUTOMATION_RE.search(qf)))
    if not matched or len(matched) > max_entities:
        return full  # ambiguous / whole-house → keep full registry
    ctx = _build_context(matched)
    return ctx + (
        "\n\n[Đã lọc theo yêu cầu hiện tại. Nếu cần thiết bị/phòng khác, "
        "gọi ha_search_entities hoặc GetLiveContext.]"
    )


def is_ha_query(messages: list[dict[str, Any]]) -> bool:
    """Public wrapper for HA intent detection. Used by handle() to decide
    on the PRISTINE user message before search/other injections so that
    e.g. "mở cửa" appearing inside gold-price search results doesn't get
    misread as a "mở cửa" smart-home command."""
    return _is_ha_query(messages)


def _is_ha_query(messages: list[dict[str, Any]]) -> bool:
    """Heuristic: is the last user message asking about smart home devices?

    Requires an unambiguous phrase (verb+device, listing+device, strong token,
    or device+room) so generic words like "đen" / "den" / "nhà" alone do not
    trigger HA injection. Checks both the lowercased original text and a
    diacritic-folded copy so input with or without dấu both register.
    """
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        raw = str(m.get("content") or "").lower()
        folded = _fold_diacritics(raw)
        for pat in _HA_INTENT_PATTERNS:
            if pat.search(raw) or pat.search(folded):
                return True
        return False
    return False


def inject_ha_context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inject HA entity registry as a system message — only for HA-related queries."""
    if not _is_ha_query(messages):
        return messages

    # Use the last user message to inject only the relevant entities (a single
    # device for a control command), instead of the whole ~50KB registry.
    query = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                query = c
            elif isinstance(c, list):
                query = " ".join(
                    str(p.get("text") or "") for p in c
                    if isinstance(p, dict) and p.get("type") in ("text", "input_text")
                )
            break

    ctx = format_states_context_targeted(query) if query.strip() else format_states_context()
    if not ctx:
        return messages

    # Ý định TẠO automation (bắt cả typo "automaiton" qua \btao ... auto): kèm
    # hướng dẫn pyscript.create_automation_by_ai. Trước đây chỉ đường chatgpt_free
    # có hint này (_prefetch_ha_context_if_needed) nên codex/gemini nhận lệnh
    # "tạo automation tắt đèn lúc 10h30" lại gọi ha_call_service bật/tắt ngay.
    try:
        _fq = _fold_diacritics(query)
        if (_CREATE_AUTOMATION_RE.search(_fq)
                or "clone automation" in _fq
                or ("nhan ban" in _fq and "auto" in _fq)):
            ctx += (
                "\n\n[TẠO AUTOMATION/SCRIPT/SCENE] Người dùng muốn TẠO cấu hình mới — KHÔNG "
                "bật/tắt thiết bị ngay. Chọn đúng đường:\n"
                "• AUTOMATION (có trigger/điều kiện) → gọi `ha_call_service` domain='pyscript', "
                "service='create_automation_by_ai', data={'message': '<YAML automation hoàn "
                "chỉnh, bắt đầu bằng - id: ...>'}. data CHỈ chứa DUY NHẤT khóa 'message', "
                "KHÔNG truyền entity_id ở cấp tool. YAML phải có `id:` (tự sinh) và `alias:`.\n"
                "• SCRIPT (kịch bản chạy tay, chuỗi hành động) hoặc SCENE (ngữ cảnh trạng thái) "
                "→ gọi `ha_upsert_config` (kind='script'|'scene', object_id=slug, config=JSON).\n"
                "QUAN TRỌNG NHẤT: tên user nói ('đèn ban công') chỉ là TÊN GỌI — entity_id thật "
                "phải TRA trong danh sách `tên | entity_id` ở trên, dòng nào có tên khớp thì lấy "
                "CHÍNH XÁC entity_id của dòng đó (entity_id có thể KHÔNG giống tên, vd 'Đèn ban "
                "công' = light.bep_center). TUYỆT ĐỐI KHÔNG tự ghép chữ thành entity_id kiểu "
                "light.ban_cong."
            )
            logger.info({"event": "ha_context_automation_hint"})
    except Exception:
        pass

    result = list(messages)
    insert_pos = len(result)
    for i in range(len(result) - 1, -1, -1):
        if result[i].get("role") == "user":
            insert_pos = i
            break
    result.insert(insert_pos, {"role": "system", "content": ctx})
    logger.info({"event": "ha_context_injected", "chars": len(ctx)})
    return result


def get_ha_tools() -> list[dict[str, Any]]:
    """Return OpenAI-format tools for HA control (get state, call service)."""
    cfg = _get_ha_config()
    if not cfg:
        return []
    return [
        {
            "type": "function",
            "function": {
                "name": "GetLiveContext",
                "description": "Lấy TOÀN BỘ trạng thái hiện tại của tất cả thiết bị trong nhà (đèn, cảm biến, công tắc, khóa...). GỌI ĐẦU TIÊN khi user hỏi 'chi tiết', 'toàn bộ', 'tổng quan', 'trạng thái hiện tại'. Không cần tham số — trả về danh sách đầy đủ tên + entity_id + state + unit.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_get_state",
                "description": "Lấy TRẠNG THÁI HIỆN TẠI của 1 thiết bị (đang bật/tắt, nhiệt độ, độ ẩm...). CHỈ DÙNG khi user hỏi về trạng thái cụ thể (ví dụ: 'đèn bếp đang bật không', 'nhiệt độ phòng ngủ'). KHÔNG dùng cho câu hỏi liệt kê.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string", "description": "Entity ID (vd: light.ban_cong, sensor.nhiet_do)"}
                    },
                    "required": ["entity_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_search_entities",
                "description": "LIỆT KÊ thiết bị theo từ khóa. DÙNG cho câu hỏi 'danh sách', 'có những X nào', 'liệt kê'. Trả về name + entity_id (KHÔNG có trạng thái). Tự động lọc theo domain (đèn → light.*, quạt → fan.*, công tắc → switch.*). Để xem automation/scene của thứ gì, thêm 'tự động hóa' / 'scene' vào query (vd: 'tự động hóa đèn'). KHÔNG cần gọi ha_get_state sau đó nếu user chỉ hỏi danh sách.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Từ khóa tìm kiếm (vd: đèn, quạt, đèn ban công, tự động hóa đèn)"}
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_call_service",
                "description": "Gọi Home Assistant service để ĐIỀU KHIỂN thiết bị (bật/tắt đèn, chỉnh độ sáng, tốc độ/quay quạt, đặt nhiệt độ, khóa cửa). CHỈ DÙNG khi user yêu cầu hành động (ví dụ: 'tắt đèn bếp', 'độ sáng 100%', 'tăng quạt', 'cho quạt quay').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "Domain: light, switch, fan, lock, climate, cover..."},
                        "service": {"type": "string", "description": "Service: turn_on, turn_off, toggle, set_percentage, oscillate, lock, unlock..."},
                        "entity_id": {"type": "string", "description": "Entity ID đầy đủ (vd: light.ban_cong, fan.phong_khach)"},
                        "data": {"type": "object", "description": "Tham số thêm (KHÔNG gồm entity_id). Đèn: brightness_pct (0-100) — vd {\"brightness_pct\":100} cho sáng 100%. Quạt: percentage (0-100) với service turn_on/set_percentage — vd {\"percentage\":100} cho mạnh nhất; oscillating (true/false) với turn_on hoặc service oscillate — vd {\"oscillating\":true} cho quạt quay. Điều hòa: temperature, hvac_mode."},
                    },
                    "required": ["domain", "service", "entity_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_upsert_config",
                "description": ("TẠO hoặc SỬA script/scene trong Home Assistant. DÙNG khi user yêu cầu "
                                "'tạo script/kịch bản' hoặc 'tạo scene/ngữ cảnh'. entity_id PHẢI lấy từ "
                                "danh sách thiết bị trong context (tên gọi ≠ entity_id, KHÔNG tự ghép chữ). "
                                "Script config: {\"alias\":\"Tên\",\"sequence\":[{\"action\":\"light.turn_on\","
                                "\"target\":{\"entity_id\":\"light.x\"}}]}. Scene config: {\"name\":\"Tên\","
                                "\"entities\":{\"light.x\":{\"state\":\"on\",\"brightness\":200}}}. "
                                "Hệ thống tự kiểm duyệt entity + verify sau khi ghi và tự báo kết quả."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["script", "scene"],
                                 "description": "Loại đối tượng: script hoặc scene"},
                        "object_id": {"type": "string",
                                      "description": "Slug định danh (a-z0-9_), vd 'chao_buoi_sang'. Trùng slug cũ = SỬA đè."},
                        "config": {"type": "object",
                                   "description": "Config JSON đầy đủ (script: alias+sequence; scene: name+entities)"},
                    },
                    "required": ["kind", "object_id", "config"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_upsert_helper",
                "description": ("TẠO/SỬA helper trong Home Assistant (input_boolean, input_number, "
                                "input_select, input_text, input_datetime, timer, counter). DÙNG khi user "
                                "cần cờ bật/tắt, biến số, danh sách chọn, hẹn giờ đếm... Config ví dụ "
                                "input_number: {\"name\":\"Nhiệt độ mục tiêu\",\"min\":16,\"max\":30,\"step\":0.5}. "
                                "Hệ thống tự check_config + rollback + verify entity xuất hiện."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "enum": list(_HELPER_DOMAINS),
                                   "description": "Loại helper"},
                        "object_id": {"type": "string", "description": "Slug (a-z0-9_)"},
                        "config": {"type": "object", "description": "Config JSON của helper (name, min/max, options...)"},
                    },
                    "required": ["domain", "object_id", "config"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_read_config_file",
                "description": ("ĐỌC file config HA (whitelist: /config/configuration.yaml, "
                                "/config/blueprints/**, /config/packages/**). LUÔN đọc trước khi sửa file."),
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "Đường dẫn tuyệt đối dưới /config"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_write_config_file",
                "description": ("GHI file config HA (blueprint mới đặt /config/blueprints/automation/ai/<tên>.yaml; "
                                "sửa /config/configuration.yaml phải ĐỌC trước rồi ghi TOÀN BỘ nội dung mới). "
                                "Hệ thống TỰ backup → check_config → lỗi thì tự khôi phục bản cũ (HA không thể chết) "
                                "→ hợp lệ mới reload. reload_service: automation.reload sau blueprint automation; "
                                "để trống nếu không chắc."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Đường dẫn tuyệt đối (whitelist như ha_read_config_file)"},
                        "content": {"type": "string", "description": "TOÀN BỘ nội dung file mới (YAML)"},
                        "reload_service": {"type": "string", "description": "Service reload sau khi ghi, vd 'automation.reload' (tùy chọn)"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_home_map",
                "description": ("BẢN ĐỒ NHÀ: khu vực (area) nào có những entity nào. DÙNG khi cần biết "
                                "thiết bị thuộc phòng nào, hoặc tạo automation/scene theo phòng/khu vực. "
                                "Trả mỗi dòng: 'Tên khu vực | area_id | entity_id...'"),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_pyscript_setup",
                "description": ("Cài/kiểm tra công cụ pyscript trên HA (ai_file_ops, create_automation_by_ai). "
                                "GỌI với consent=true CHỈ KHI người dùng đã ĐỒNG Ý cho cài (vd họ nói 'đồng ý "
                                "cài pyscript'); action='check' để chỉ kiểm tra thiếu gì. KHÔNG tự ý đặt "
                                "consent=true khi user chưa đồng ý."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["check", "install"], "description": "check = kiểm tra; install = cài (cần user đồng ý)"},
                        "consent": {"type": "boolean", "description": "true CHỈ KHI user đã đồng ý cho cài"},
                    },
                    "required": ["action"],
                },
            },
        },
    ]


# ── Tạo automation: bot tự kiểm duyệt lại sau khi tạo, có lỗi thì tự sửa ─────
# create_automation_and_verify() kiểm duyệt 3 tầng: (1) vá nháy thời gian chắc
# chắn bằng regex (_sanitize_automation_yaml, không cần model), (2) reviewer model
# soi TRƯỚC khi ghi, (3) dùng CHÍNH Home Assistant làm trọng tài: ghi → HA reload
# → soi error_log; còn lỗi thì reviewer SỬA theo đúng lỗi HA rồi ghi lại. Reviewer
# GIỮ NGUYÊN `id:` để pyscript thay thế đúng bản cũ (không đẻ bản lỗi thừa) —
# pyscript create_automation_by_ai đã hỗ trợ replace-by-id.


def _extract_alias_id(text: str) -> tuple[str, str]:
    """Lấy (alias, id) đầu tiên từ YAML automation, kể cả khi YAML chưa parse được
    (fallback regex) để còn soi/dọn theo id."""
    try:
        import yaml
        data = yaml.safe_load(text)
        it = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
        if isinstance(it, dict):
            return str(it.get("alias") or ""), str(it.get("id") or "")
    except Exception:
        pass
    a = _re.search(r"(?im)^\s*(?:-\s*)?alias\s*:\s*(.+?)\s*$", text)
    i = _re.search(r"(?im)^\s*(?:-\s*)?id\s*:\s*['\"]?([\w-]+)", text)
    return (a.group(1).strip().strip("'\"") if a else ""), (i.group(1) if i else "")


def _automation_setup_error(alias: str, aid: str = "") -> str | None:
    """Soi error_log HA xem automation vừa nạp (theo alias hoặc id) có lỗi setup."""
    cfg = _get_ha_config()
    if not cfg or not (alias or aid):
        return None
    try:
        req = urllib.request.Request(
            f"{cfg['url']}/api/error_log",
            headers={"Authorization": f"Bearer {cfg['token']}"},
        )
        log = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "replace")
    except Exception:
        return None
    keys = [k for k in (alias, aid) if k]
    for line in reversed(log.splitlines()[-300:]):
        low = line.lower()
        if any(k.lower() in low for k in keys) and any(
                m in low for m in ("failed to setup", "invalid", "error", "not a valid", "got none")):
            return line.split("]", 1)[-1].strip()[:350] or line[:350]
    return None


def _reviewer_model() -> str:
    """Model Kiểm duyệt (agent_branches.code_reviewer). Trống = bỏ bước review."""
    try:
        return str((config.data.get("agent_branches") or {}).get("code_reviewer") or "").strip()
    except Exception:
        return ""


def _review_automation_yaml(yaml_text: str, ha_error: str = "") -> str:
    """Nhờ model Reviewer soi + SỬA YAML automation. Trả YAML đã sửa (hoặc bản
    gốc nếu reviewer trống/lỗi/không parse được). Dùng để kiểm duyệt TRƯỚC khi
    ghi vào HA và để SỬA sau khi HA báo lỗi."""
    model = _reviewer_model()
    if not model:
        return yaml_text
    prompt = (
        "Bạn là REVIEWER cấu hình Home Assistant. Dưới đây là YAML một automation "
        "SẮP được thêm vào automations.yaml. Soi kỹ và SỬA cho ĐÚNG:\n"
        "- Giá trị thời gian PHẢI để trong nháy đơn: at: '22:30:00' (KHÔNG viết 22:30:00 "
        "trần vì YAML hiểu thành số → HA lỗi 'Expected HH:MM ... Got None').\n"
        "- Bắt buộc có: id, alias, trigger (hoặc triggers), action (hoặc actions).\n"
        "- entity_id phải là entity CÓ THẬT, KHÔNG bịa; nếu thông báo lỗi bên dưới "
        "liệt kê 'entity THẬT gần nhất' thì dùng CHÍNH XÁC id đó.\n"
        "- Cú pháp/thụt lề YAML chuẩn HA.\n"
        + (f"\nHA vừa BÁO LỖI khi nạp bản trước:\n{ha_error}\nSỬa ĐÚNG lỗi này, GIỮ NGUYÊN id.\n"
           if ha_error else "")
        + "\nCHỈ TRẢ VỀ YAML hoàn chỉnh đã sửa (giữ nguyên id, alias), KHÔNG giải thích, "
        "KHÔNG bọc ```.\n\n" + yaml_text
    )
    try:
        from services.agent.runtime import call_model, content_of
        resp = call_model(model, [{"role": "user", "content": prompt}],
                          timeout=150, max_tokens=1500, allow_fastpath=False)
        if resp.get("error"):
            logger.warning({"event": "automation_review_call_error", "error": str(resp["error"])[:120]})
            return yaml_text
        txt = str(content_of(resp) or "").strip()
        if txt.startswith("```"):
            txt = _re.sub(r"^```[a-zA-Z]*\n?", "", txt)
            txt = _re.sub(r"\n?```$", "", txt).strip()
        import yaml
        d = yaml.safe_load(txt)
        if txt and (isinstance(d, list) or isinstance(d, dict)):
            logger.info({"event": "automation_reviewed", "changed": txt.strip() != yaml_text.strip()})
            return txt
    except Exception as exc:
        logger.warning({"event": "automation_review_failed", "error": str(exc)[:150]})
    return yaml_text


# Khóa thời gian HA (time trigger `at`, time condition `before`/`after`). Giá trị
# HH:MM(:SS) TRẦN bị YAML đọc thành số hệ 60 (22:30:00 -> 81000) → HA lỗi
# "Expected HH:MM ... Got None". Phải bọc nháy. Entity id (input_datetime.x) hay
# giá trị đã có nháy thì bỏ qua (regex chỉ khớp chuỗi bắt đầu bằng chữ số).
_TIME_KEY_RE = _re.compile(
    r"^(?P<indent>\s*(?:-\s*)?)(?P<key>at|before|after)\s*:\s*(?P<val>\d{1,2}:\d{2}(?::\d{2})?)\s*$")
_TIME_ITEM_RE = _re.compile(r"^(?P<indent>\s*-\s*)(?P<val>\d{1,2}:\d{2}(?::\d{2})?)\s*$")


def _sanitize_automation_yaml(text: str) -> str:
    """Bọc nháy các mốc thời gian HH:MM(:SS) TRẦN trên khóa at/before/after (và
    phần tử list dưới chúng) — chống bẫy YAML hệ 60. Chạy VÔ ĐIỀU KIỆN, không phụ
    thuộc reviewer, nên kể cả khi model kiểm duyệt trống thì lỗi thời gian phổ
    biến nhất vẫn được vá."""
    out = []
    for line in text.splitlines():
        m = _TIME_KEY_RE.match(line)
        if m:
            line = f"{m.group('indent')}{m.group('key')}: '{m.group('val')}'"
        else:
            im = _TIME_ITEM_RE.match(line)
            if im:
                line = f"{im.group('indent')}'{im.group('val')}'"
        out.append(line)
    return "\n".join(out)


# HA KHÔNG báo lỗi khi automation trỏ entity không tồn tại (nạp "thành công"
# nhưng không bao giờ chạy) → phải TỰ soi entity trước khi ghi. Bẫy thật đã gặp:
# model bịa light.ban_cong trong khi đèn ban công thật là light.bep_center.
_ENTITY_ID_RE = _re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")


def _collect_entity_ids(node) -> set[str]:
    """Gom mọi giá trị entity_id trong config automation đã parse."""
    out: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "entity_id":
                if isinstance(v, str):
                    out.add(v)
                elif isinstance(v, list):
                    out.update(x for x in v if isinstance(x, str))
            else:
                out |= _collect_entity_ids(v)
    elif isinstance(node, list):
        for it in node:
            out |= _collect_entity_ids(it)
    return out


def _entity_candidates(missing: str, states: list[dict]) -> list[tuple[str, str]]:
    """Tìm entity THẬT cùng domain khớp mọi token tên (đã bỏ dấu) của id bịa.
    'light.ban_cong' → light.bep_center vì friendly_name 'Đèn ban công'."""
    dom, _, obj = missing.partition(".")
    toks = [t for t in _fold_diacritics(obj.replace("_", " ")).split() if t]
    if not toks:
        return []
    out = []
    for s in states:
        eid = str(s.get("entity_id") or "")
        if not eid.startswith(dom + "."):
            continue
        fname = str((s.get("attributes") or {}).get("friendly_name") or "")
        # _fold_diacritics không đổi đ→d (NFKD không tách được) — tự đổi để token
        # ASCII từ entity id ("den") khớp được tên tiếng Việt ("đèn").
        hay = (_fold_diacritics(fname).replace("đ", "d") + " "
               + eid.replace("_", " ").replace(".", " "))
        if all(t in hay for t in toks):
            out.append((eid, fname))
    return out[:5]


def _missing_entities_problem(text: str) -> tuple[str, str]:
    """Soi entity không tồn tại. Trả (mô tả lỗi hoặc "", YAML đã tự thay entity
    khi chỉ có DUY NHẤT 1 ứng viên khớp — trường hợp mơ hồ để reviewer quyết)."""
    try:
        import yaml
        data = yaml.safe_load(text)
    except Exception as exc:
        return f"YAML không parse được: {str(exc)[:200]}", text
    ids = sorted(i for i in _collect_entity_ids(data) if _ENTITY_ID_RE.match(i))
    if not ids:
        return "", text
    states = get_states()
    if not states:
        return "", text  # HA không trả states — đừng chặn oan
    have = {str(s.get("entity_id") or "") for s in states}
    probs = []
    for miss in ids:
        if miss in have:
            continue
        cands = _entity_candidates(miss, states)
        if len(cands) == 1:
            text = _re.sub(rf"(?<![\w.]){_re.escape(miss)}(?![\w.])", cands[0][0], text)
            logger.info({"event": "automation_entity_swapped", "from": miss, "to": cands[0][0]})
            continue
        hint = ("; entity THẬT gần nhất: "
                + ", ".join(f"{e} ('{n}')" for e, n in cands)) if cands else ""
        probs.append(f"entity '{miss}' KHÔNG tồn tại trong HA{hint}")
    return " | ".join(probs)[:600], text


def _notify_result_tg(text: str) -> None:
    """Báo KẾT QUẢ tạo automation về Telegram admin — cả khi thành công lẫn lỗi,
    vì user hay giao việc xong đi làm việc khác, không ngồi chờ chat. Best-effort,
    không bao giờ chặn/raise luồng chính."""
    try:
        from services.notifier import notify_admin
        notify_admin(text[:3900])
    except Exception:
        pass


def create_automation_and_verify(message: str) -> tuple[str, str]:
    """Tạo automation với vòng KIỂM DUYỆT: vá nháy thời gian (deterministic) +
    reviewer soi TRƯỚC khi ghi → ghi qua pyscript → HA reload → verify error_log
    → còn lỗi thì reviewer SỬA rồi ghi lại (pyscript replace theo id), tối đa 2
    vòng. Kết quả CUỐI (✅/⚠️/❌) luôn được báo về cả chat lẫn Telegram.
    Trả (status, text)."""
    raw = str(message or "").strip()
    if raw.startswith("```"):
        raw = _re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = _re.sub(r"\n?```$", "", raw).strip()
    if not raw:
        return "error", "❌ Không có nội dung YAML automation. Hãy cung cấp YAML hoàn chỉnh."

    # 0) HA phải có pyscript create_automation_by_ai; thiếu → xin phép user (không
    #    tự ý cài). User đồng ý → tool ha_pyscript_setup(consent) sẽ cài.
    from services import ha_pyscript_deps as _deps
    _ready, _msg = _deps.ensure(["create_automation_by_ai"])
    if not _ready:
        return "need_setup", _msg

    # 1) Vá nháy thời gian ngay (chắc chắn, không cần model) rồi kiểm duyệt TRƯỚC
    #    khi add (bắt lỗi cú pháp/thiếu trường/entity sai).
    raw = _sanitize_automation_yaml(raw)
    raw = _sanitize_automation_yaml(_review_automation_yaml(raw))

    problem = ""
    wrote = False
    for attempt in range(3):
        alias, aid = _extract_alias_id(raw)
        # 2) Entity phải TỒN TẠI (HA nạp automation trỏ entity ma mà không kêu
        #    gì → tự soi; id bịa có đúng 1 ứng viên khớp thì thay luôn).
        problem, raw = _missing_entities_problem(raw)
        if not problem:
            if not call_service("pyscript", "create_automation_by_ai", {"message": raw}):
                _txt = "❌ Không gọi được pyscript.create_automation_by_ai để ghi automation."
                _notify_result_tg(f"🏠 Tạo automation '{alias or aid}':\n{_txt}")
                return "error", _txt
            wrote = True
            time.sleep(2.2)
            problem = _automation_setup_error(alias, aid) or ""
            if not problem:
                logger.info({"event": "automation_created_verified", "alias": alias, "id": aid, "attempt": attempt})
                _txt = (f"✅ Đã tạo automation '{alias or aid}', đã qua kiểm duyệt "
                        f"(entity + cấu trúc + HA nạp thành công, không lỗi).")
                _notify_result_tg(f"🏠 {_txt}" + (f"\n(tự sửa {attempt} lần theo lỗi)" if attempt else ""))
                return "ok", _txt
        logger.warning({"event": "automation_setup_failed", "alias": alias, "id": aid,
                        "attempt": attempt, "wrote": wrote, "problem": problem})
        # 3) Còn lỗi → reviewer SỬA theo mô tả lỗi (kèm entity thật gợi ý) rồi
        #    thử lại (giữ id → pyscript replace).
        fixed = _sanitize_automation_yaml(_review_automation_yaml(raw, ha_error=problem))
        if fixed.strip() == raw.strip():
            break  # reviewer trống hoặc không sửa được gì thêm
        raw = fixed

    alias, aid = _extract_alias_id(raw)
    hint = ""
    pl = problem.lower()
    if "hh:mm" in pl or "got none" in pl:
        hint = " (lỗi thời gian — cần at: '22:30:00' trong nháy)"
    if wrote:
        _txt = (f"⚠️ Automation '{alias or aid}' đã ghi nhưng HA vẫn báo lỗi sau khi kiểm "
                f"duyệt/sửa, nên nó đang bị TẮT: {problem}{hint}. Cần xem lại thủ công.")
    else:
        _txt = (f"❌ KHÔNG ghi automation '{alias or aid}' vào HA vì kiểm duyệt phát hiện "
                f"lỗi không tự sửa được: {problem}{hint}.")
    _notify_result_tg(f"🏠 {_txt}")
    return "error", _txt


def _api_request(method: str, path: str, payload: dict | None = None,
                 timeout: int = 15) -> tuple[int, str]:
    """REST call tới HA. Trả (status_code, body); (0, lỗi) khi không nối được."""
    cfg = _get_ha_config()
    if not cfg:
        return 0, "HA chưa cấu hình url/token"
    try:
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        req = urllib.request.Request(
            f"{cfg['url']}{path}", data=data, method=method,
            headers={"Authorization": f"Bearer {cfg['token']}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read().decode("utf-8", "replace")[:500]
        except Exception:
            return exc.code, str(exc)[:300]
    except Exception as exc:
        return 0, str(exc)[:300]


# Script/Scene qua HA config API (tự validate schema + tự reload) — bọc cùng lưới
# an toàn như automation: soi entity trước khi ghi → ghi → đọc lại + soi error_log
# → báo kết quả cả chat lẫn Telegram. Helper (input_*) cần websocket, chưa hỗ trợ.
_UPSERT_KINDS = ("script", "scene")


def upsert_ha_config_and_verify(kind, object_id, payload) -> tuple[str, str]:
    kind = str(kind or "").strip().lower()
    obj = _re.sub(r"[^a-z0-9_]", "_", str(object_id or "").strip().lower()).strip("_")
    if kind not in _UPSERT_KINDS:
        return "error", (f"❌ kind '{kind}' chưa hỗ trợ — hiện chỉ: "
                         f"{', '.join(_UPSERT_KINDS)}. Automation dùng "
                         "pyscript.create_automation_by_ai.")
    if not obj:
        return "error", "❌ Thiếu object_id (slug a-z0-9_, vd 'chao_buoi_sang')."
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return "error", "❌ config phải là JSON object hợp lệ."
    if not isinstance(payload, dict) or not payload:
        return "error", f"❌ config phải là object JSON đầy đủ của {kind}."
    label = str(payload.get("alias") or payload.get("name") or obj)

    # 1) Entity phải TỒN TẠI (JSON là YAML hợp lệ → tái dùng bộ soi của automation;
    #    id bịa có đúng 1 ứng viên khớp tên thì tự thay).
    blob = json.dumps(payload, ensure_ascii=False)
    problem, blob = _missing_entities_problem(blob)
    if problem:
        _txt = f"❌ KHÔNG ghi {kind} '{label}' vào HA: {problem}."
        _notify_result_tg(f"🏠 {_txt}")
        return "error", _txt
    payload = json.loads(blob)

    # 2) Ghi qua config API — HA validate schema ngay tại đây.
    code, body = _api_request("POST", f"/api/config/{kind}/config/{obj}", payload)
    if code != 200:
        _txt = f"❌ HA từ chối {kind} '{label}' (HTTP {code}): {str(body)[:300]}"
        _notify_result_tg(f"🏠 {_txt}")
        return "error", _txt
    time.sleep(1.5)

    # 3) Verify: đọc lại config + soi error_log theo tên/id.
    code2, _ = _api_request("GET", f"/api/config/{kind}/config/{obj}")
    problem2 = _automation_setup_error(label, obj) or ""
    if code2 == 200 and not problem2:
        logger.info({"event": "ha_config_upserted", "kind": kind, "id": obj})
        _txt = (f"✅ Đã lưu {kind} '{label}', đã kiểm duyệt (entity + schema) và "
                f"HA nạp thành công (không lỗi).")
        _notify_result_tg(f"🏠 {_txt}")
        return "ok", _txt
    _txt = (f"⚠️ {kind} '{label}' đã ghi nhưng verify chưa sạch: đọc lại config "
            f"HTTP {code2}; error_log: {problem2 or 'không có'}. Cần xem lại.")
    _notify_result_tg(f"🏠 {_txt}")
    return "error", _txt


# ── Phase 2: ghi file config HA an toàn (blueprint / packages / configuration.yaml)
# Qua pyscript ai_file_ops (backup mỗi lần ghi + whitelist path phía HA). Quy
# trình BẮT BUỘC: ghi → check_config → lỗi thì RESTORE bản cũ + không reload →
# hợp lệ mới reload. Không bao giờ để HA chết vì config hỏng.
_AI_HELPERS_FILE = "/config/packages/ai_helpers.yaml"
_HELPER_DOMAINS = ("input_boolean", "input_number", "input_select", "input_text",
                   "input_datetime", "timer", "counter")


def _pyscript_file_op(op: str, path: str, content: str | None = None) -> dict:
    payload: dict[str, Any] = {"op": op, "path": path}
    if content is not None:
        payload["content_b64"] = base64.b64encode(content.encode("utf-8")).decode()
    code, body = _api_request("POST", "/api/services/pyscript/ai_file_ops?return_response",
                              payload, timeout=25)
    if code != 200:
        return {"ok": False, "error": f"HTTP {code}: {str(body)[:200]} (đã cài pyscript ai_file_ops chưa?)"}
    try:
        d = json.loads(body)
        return (d.get("service_response") or {}) if isinstance(d, dict) else {}
    except Exception:
        return {"ok": False, "error": "response pyscript không parse được"}


def _check_config() -> tuple[bool, str]:
    """POST /api/config/core/check_config — HA tự kiểm tra TOÀN BỘ config."""
    code, body = _api_request("POST", "/api/config/core/check_config", {}, timeout=90)
    if code != 200:
        return False, f"check_config HTTP {code}"
    try:
        d = json.loads(body)
    except Exception:
        return False, "check_config trả response lạ"
    return (d.get("result") == "valid"), str(d.get("errors") or "")[:400]


def write_ha_file_and_verify(path: str, content: str, reload_service: str = "") -> tuple[str, str]:
    """Ghi file config HA với lưới an toàn: backup (pyscript) → check_config →
    lỗi thì tự RESTORE + không reload → OK mới reload. Báo chat + Telegram."""
    from services import ha_pyscript_deps as _deps
    _ready, _msg = _deps.ensure(["ai_file_ops"])
    if not _ready:
        return "need_setup", _msg
    r = _pyscript_file_op("write", str(path or ""), str(content or ""))
    if not r.get("ok"):
        _txt = f"❌ Không ghi được {path}: {r.get('error')}"
        _notify_result_tg(f"🏠 {_txt}")
        return "error", _txt
    ok, errs = _check_config()
    if not ok:
        rest = _pyscript_file_op("restore", str(path))
        _txt = (f"❌ Nội dung mới làm config HA LỖI ({errs or 'không rõ'}) — đã tự "
                f"KHÔI PHỤC bản cũ ({'ok' if rest.get('ok') else 'RESTORE LỖI: ' + str(rest.get('error'))}), "
                "KHÔNG reload.")
        _notify_result_tg(f"🏠 {_txt}")
        return "error", _txt
    if reload_service:
        dom, _, svc = str(reload_service).partition(".")
        call_service(dom, svc or "reload", {})
        time.sleep(1.8)
    logger.info({"event": "ha_file_written", "path": path, "reload": reload_service})
    _txt = (f"✅ Đã ghi {path} ({r.get('bytes')} bytes, backup: "
            f"{r.get('backup') or 'file mới'}), check_config HỢP LỆ"
            + (f", đã reload {reload_service}" if reload_service else "") + ".")
    _notify_result_tg(f"🏠 {_txt}")
    return "ok", _txt


def upsert_helper_and_verify(domain, object_id, config) -> tuple[str, str]:
    """Phase 1b: helper qua package YAML /config/packages/ai_helpers.yaml —
    merge key → ghi an toàn (check_config + rollback) → reload domain → verify
    entity xuất hiện thật trong states."""
    domain = str(domain or "").strip().lower()
    obj = _re.sub(r"[^a-z0-9_]", "_", str(object_id or "").strip().lower()).strip("_")
    if domain not in _HELPER_DOMAINS:
        return "error", f"❌ domain helper '{domain}' không hỗ trợ. Hỗ trợ: {', '.join(_HELPER_DOMAINS)}"
    if not obj:
        return "error", "❌ Thiếu object_id (slug a-z0-9_)."
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            return "error", "❌ config phải là JSON object."
    if not isinstance(config, dict):
        config = {}
    config.setdefault("name", obj.replace("_", " ").title())

    from services import ha_pyscript_deps as _deps
    _ready, _msg = _deps.ensure(["ai_file_ops"])
    if not _ready:
        return "need_setup", _msg

    r = _pyscript_file_op("read", _AI_HELPERS_FILE)
    if not r.get("ok"):
        _txt = f"❌ Không đọc được {_AI_HELPERS_FILE}: {r.get('error')}"
        _notify_result_tg(f"🏠 {_txt}")
        return "error", _txt
    import yaml
    data = {}
    if r.get("exists"):
        try:
            data = yaml.safe_load(base64.b64decode(r.get("content_b64") or "").decode("utf-8")) or {}
        except Exception as exc:
            return "error", f"❌ {_AI_HELPERS_FILE} hiện tại không parse được: {exc}"
    if not isinstance(data, dict):
        data = {}
    data.setdefault(domain, {})[obj] = config
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    status, txt = write_ha_file_and_verify(_AI_HELPERS_FILE, text, reload_service=f"{domain}.reload")
    if status != "ok":
        return status, txt
    time.sleep(1.5)
    if get_state(f"{domain}.{obj}") is None:
        _txt = (f"⚠️ Helper {domain}.{obj} đã ghi + reload nhưng CHƯA thấy entity — "
                "kiểm tra configuration.yaml có 'packages: !include_dir_named packages' chưa.")
        _notify_result_tg(f"🏠 {_txt}")
        return "error", _txt
    _txt = f"✅ Đã tạo helper {domain}.{obj} — entity đã xuất hiện trong HA."
    _notify_result_tg(f"🏠 {_txt}")
    return "ok", _txt


# ── Phase 3: bản đồ nhà (kiểu Knowledge Pack của HADocs) — khu vực nào có
# thiết bị gì, qua /api/template (registry area chỉ lộ qua template/WebSocket).
_HOME_MAP_TEMPLATE = (
    "{% for aid in areas() %}"
    "{% set ents = area_entities(aid) | list %}"
    "{% if ents %}{{ area_name(aid) }} | {{ aid }} | {{ ents | join(', ') }}\n{% endif %}"
    "{% endfor %}"
)
_home_map_cache: tuple[float, str] | None = None


def get_home_map() -> str:
    """'Tên khu vực | area_id | entity...' mỗi dòng, cache 10 phút."""
    global _home_map_cache
    now = time.time()
    if _home_map_cache and now - _home_map_cache[0] < 600:
        return _home_map_cache[1]
    code, body = _api_request("POST", "/api/template", {"template": _HOME_MAP_TEMPLATE}, timeout=20)
    out = body.strip() if code == 200 and body else ""
    if code != 200:
        logger.warning({"event": "home_map_failed", "code": code, "body": str(body)[:150]})
        return ""
    _home_map_cache = (now, out)
    return out


def execute_ha_tool(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Execute an HA tool and return result text."""
    if tool_name == "GetLiveContext":
        return format_states_context()
    elif tool_name == "ha_get_state":
        eid = arguments.get("entity_id", "")
        state = get_state(eid)
        if state is None:
            return f"Không tìm thấy thiết bị '{eid}'"
        return json.dumps(state, ensure_ascii=False, indent=2)
    elif tool_name == "ha_search_entities":
        query = arguments.get("query", "").lower().strip()
        states = get_states()

        # Detect domain intent from query keywords (Vietnamese + English).
        # If user asks "đèn" → only light.*, not switch/automation/scene that also contain "đèn"
        # in friendly_name. To include automations, user must say "tự động hóa đèn" / "automation đèn".
        DOMAIN_KEYWORDS: dict[str, list[str]] = {
            "light": ["đèn", "light"],
            "switch": ["công tắc", "switch", "ổ cắm", "ổ điện"],
            "climate": ["điều hòa", "máy lạnh", "climate", "nhiệt độ", "thermostat"],
            "cover": ["rèm", "mành", "cửa cuốn", "cover"],
            "lock": ["khóa", "lock"],
            "fan": ["quạt", "fan"],
            "media_player": ["loa", "tivi", "tv", "media"],
            "sensor": ["cảm biến", "sensor"],
            "scene": ["scene", "ngữ cảnh"],
            "automation": ["tự động hóa", "automation"],
            "script": ["script", "kịch bản"],
            "vacuum": ["robot hút bụi", "vacuum"],
        }
        # Force-domain takes priority: phrases that mention "đèn" but explicitly ask
        # for automation/scene/script of that thing.
        force_domain: str | None = None
        for kw in DOMAIN_KEYWORDS["automation"]:
            if kw in query:
                force_domain = "automation"
                break
        if force_domain is None:
            for kw in DOMAIN_KEYWORDS["scene"]:
                if kw in query:
                    force_domain = "scene"
                    break
        if force_domain is None:
            for kw in DOMAIN_KEYWORDS["script"]:
                if kw in query:
                    force_domain = "script"
                    break
        # Match primary thing (light/switch/etc) only when no force_domain
        primary_domain: str | None = None
        if force_domain is None:
            for domain, kws in DOMAIN_KEYWORDS.items():
                if domain in ("automation", "scene", "script"):
                    continue
                if any(kw in query for kw in kws):
                    primary_domain = domain
                    break

        target_domain = force_domain or primary_domain

        matches = []
        for s in states:
            eid = s.get("entity_id", "").lower()
            name = s.get("attributes", {}).get("friendly_name", "").lower()
            domain = eid.split(".")[0] if "." in eid else ""
            # If we detected a target domain, hard-filter to that domain only
            if target_domain and domain != target_domain:
                continue
            if query in eid or query in name:
                real_name = s.get("attributes", {}).get("friendly_name", "")
                label = f"{real_name} | {eid}" if real_name else eid
                matches.append(label)
        if not matches:
            scope = f" (domain={target_domain})" if target_domain else ""
            return f"Không tìm thấy thiết bị nào khớp với '{query}'{scope}"
        scope = f" [domain={target_domain}]" if target_domain else ""
        return f"Thiết bị khớp '{query}'{scope} ({len(matches)}):\n" + "\n".join(matches[:30])
    elif tool_name == "ha_call_service":
        domain = arguments.get("domain", "")
        service = arguments.get("service", "")
        entity_id = arguments.get("entity_id", "")
        extra = arguments.get("data") or {}
        if not isinstance(extra, dict):
            extra = {}
        # Tạo automation: ghi xong TỰ KIỂM DUYỆT bằng HA error_log; lỗi thì trả
        # mô tả + hướng dẫn để model tự sửa và gọi lại (giữ id → replace).
        if domain == "pyscript" and service == "create_automation_by_ai":
            _status, _text = create_automation_and_verify(str(extra.get("message") or ""))
            return _text
        # Pass through service params: brightness_pct (đèn 0-100), percentage
        # (quạt 0-100), oscillating (quay quạt), temperature, hvac_mode, color_name…
        payload = {**extra}
        
        # Determine if we should include entity_id.
        # For notify, most services (like mobile_app_xyz) don't accept entity_id.
        # But 'send_message' DOES require it.
        should_include_entity = True
        if domain == "notify" and service != "send_message":
            should_include_entity = False
        # Pyscript service chỉ nhận đúng kwargs nó khai báo (vd create_automation_by_ai
        # chỉ nhận 'message') — chèn entity_id sẽ nổ TypeError phía HA.
        if domain == "pyscript":
            should_include_entity = False

        if should_include_entity and entity_id:
            payload["entity_id"] = entity_id
        
        ok = call_service(domain, service, payload)
        desc = f"{domain}.{service} cho {entity_id}"
        if extra:
            desc += " (" + ", ".join(f"{k}={v}" for k, v in extra.items()) + ")"
        return f"Đã gọi {desc}" if ok else f"Lỗi gọi {domain}.{service}"
    elif tool_name == "ha_upsert_config":
        _status, _text = upsert_ha_config_and_verify(
            arguments.get("kind"), arguments.get("object_id"), arguments.get("config"))
        return _text
    elif tool_name == "ha_upsert_helper":
        _status, _text = upsert_helper_and_verify(
            arguments.get("domain"), arguments.get("object_id"), arguments.get("config"))
        return _text
    elif tool_name == "ha_read_config_file":
        from services import ha_pyscript_deps as _deps
        _ready, _msg = _deps.ensure(["ai_file_ops"])
        if not _ready:
            return _msg
        _r = _pyscript_file_op("read", str(arguments.get("path") or ""))
        if not _r.get("ok"):
            return f"Lỗi đọc file: {_r.get('error')}"
        if not _r.get("exists"):
            return "File chưa tồn tại."
        try:
            return base64.b64decode(_r.get("content_b64") or "").decode("utf-8", "replace")[:30000]
        except Exception as exc:
            return f"Lỗi decode: {exc}"
    elif tool_name == "ha_write_config_file":
        _status, _text = write_ha_file_and_verify(
            str(arguments.get("path") or ""), str(arguments.get("content") or ""),
            str(arguments.get("reload_service") or ""))
        return _text
    elif tool_name == "ha_home_map":
        _m = get_home_map()
        return _m if _m else "Không lấy được bản đồ khu vực (kiểm tra HA /api/template)."
    elif tool_name == "ha_pyscript_setup":
        from services import ha_pyscript_deps as _deps
        if arguments.get("consent") or arguments.get("action") == "install":
            _ok, _msg = _deps.install()
            return _msg
        _miss = _deps.missing(list(_deps.DEPS.keys()))
        if not _miss:
            return "✅ HA đã có đủ công cụ pyscript (ai_file_ops, create_automation_by_ai)."
        return _deps.consent_message(_miss)
    return None

# Start background scheduler on module import
try:
    _ensure_scheduler_running()
except Exception:
    pass
