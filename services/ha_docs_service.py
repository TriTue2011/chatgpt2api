"""HA Docs — tài liệu hóa Home Assistant thành Markdown cho Knowledge Base.

Lấy cảm hứng từ HADocs (github.com/SirBlondieDK/HADocs): quét toàn bộ khu vực,
thiết bị, automation, script, scene... qua HA REST API rồi sinh một tài liệu
Markdown có cấu trúc. Tài liệu được nạp vào KB `ha_docs` (Chroma, qua
/api/mcp/ha-docs/refresh) để AI Agent trả lời được các câu hỏi về CẤU TRÚC nhà
(nhà có gì, ở đâu, automation nào đang chạy) — bổ sung cho GetLiveContext vốn
chỉ trả trạng thái realtime.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections import defaultdict
from typing import Any

from services.ha_client import (
    _get_ha_config,
    get_ha_area_index,
    get_service_catalog,
    get_states,
)
from utils.log import logger

KB_NAME = "ha_docs"
KB_LABEL = "Tài liệu nhà (HA)"

# Domain vật lý hiển thị trong mục "thiết bị theo khu vực"
_DEVICE_DOMAINS = (
    "light", "switch", "climate", "fan", "cover", "lock", "media_player",
    "camera", "vacuum", "humidifier", "water_heater", "valve", "siren",
    "remote", "input_boolean",
)

_DOMAIN_LABELS = {
    "light": "Đèn", "switch": "Công tắc / Ổ cắm", "climate": "Điều hòa",
    "fan": "Quạt", "cover": "Rèm / Cửa cuốn", "lock": "Khóa",
    "media_player": "Loa / TV", "camera": "Camera", "vacuum": "Robot hút bụi",
    "humidifier": "Máy tạo ẩm", "water_heater": "Bình nóng lạnh",
    "valve": "Van", "siren": "Còi báo", "remote": "Remote",
    "input_boolean": "Công tắc ảo",
}

# Cảm biến đáng đưa vào tài liệu (bỏ battery/diagnostic cho gọn)
_SENSOR_CLASSES = {
    "temperature", "humidity", "power", "energy", "illuminance",
    "co2", "pm25", "pm10", "voltage", "current",
}


def _ha_get(path: str, timeout: int = 15) -> Any:
    cfg = _get_ha_config()
    if not cfg:
        raise RuntimeError("Chưa cấu hình Home Assistant (URL/token) trong Settings")
    req = urllib.request.Request(
        f"{cfg['url']}{path}",
        headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _friendly(state: dict[str, Any]) -> str:
    attrs = state.get("attributes") or {}
    return str(attrs.get("friendly_name") or state.get("entity_id", ""))


def _area_map_via_template() -> dict[str, str]:
    """Fallback lấy mapping entity→khu vực qua REST /api/template.

    get_ha_area_index() dùng WebSocket — có thể timeout tùy mạng/reverse proxy.
    Template API chạy trên cùng kênh REST với /api/states nên ổn định hơn.
    """
    template = (
        "{% set ns = namespace(items=[]) %}"
        "{% for s in states %}"
        "{% set a = area_name(s.entity_id) %}"
        "{% if a %}{% set ns.items = ns.items + [[s.entity_id, a]] %}{% endif %}"
        "{% endfor %}"
        "{{ ns.items | tojson }}"
    )
    cfg = _get_ha_config()
    if not cfg:
        return {}
    try:
        req = urllib.request.Request(
            f"{cfg['url']}/api/template",
            data=json.dumps({"template": template}).encode(),
            headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"},
        )
        raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="ignore")
        pairs = json.loads(raw)
        return {str(eid): str(area) for eid, area in pairs if eid and area}
    except Exception as exc:
        logger.warning({"event": "ha_docs_template_area_failed", "error": str(exc)[:120]})
        return {}


def build_ha_docs_markdown() -> str:
    """Sinh tài liệu Markdown mô tả toàn bộ cấu trúc nhà từ HA API.

    Raises RuntimeError khi HA chưa cấu hình hoặc không truy cập được.
    """
    states = get_states(use_cache=False)
    if not states:
        raise RuntimeError("Không lấy được danh sách entity từ Home Assistant")

    idx = get_ha_area_index(use_cache=False)
    entity_area: dict[str, str] = idx.get("entity_area") or {}
    if not entity_area:
        entity_area = _area_map_via_template()

    try:
        ha_cfg = _ha_get("/api/config")
    except Exception:
        ha_cfg = {}

    lines: list[str] = []
    home_name = str(ha_cfg.get("location_name") or "Nhà")
    lines.append(f"# Tài liệu Home Assistant — {home_name}")
    lines.append("")
    lines.append(f"- Phiên bản HA: {ha_cfg.get('version', 'không rõ')}")
    lines.append(f"- Tổng số entity: {len(states)}")
    lines.append(f"- Múi giờ: {ha_cfg.get('time_zone', 'không rõ')}")
    lines.append(f"- Tài liệu tạo lúc: {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(
        "Tài liệu này mô tả cấu trúc nhà: khu vực, thiết bị, automation, script,"
        " scene và các cảm biến chính. Trạng thái bật/tắt realtime tra bằng"
        " GetLiveContext hoặc ha_get_state, KHÔNG dùng tài liệu này."
    )

    # ── Thiết bị theo khu vực ────────────────────────────────────────────
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in states:
        domain = str(s.get("entity_id", "")).split(".", 1)[0]
        by_domain[domain].append(s)

    area_devices: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    unassigned: dict[str, list[str]] = defaultdict(list)
    for domain in _DEVICE_DOMAINS:
        for s in by_domain.get(domain, []):
            eid = s.get("entity_id", "")
            entry = f"{_friendly(s)} (`{eid}`)"
            area = entity_area.get(eid)
            if area:
                area_devices[area][domain].append(entry)
            else:
                unassigned[domain].append(entry)

    lines.append("")
    lines.append("## Khu vực và thiết bị")
    if not area_devices:
        lines.append("")
        lines.append("(Chưa gán thiết bị vào khu vực nào trong HA)")
    for area in sorted(area_devices):
        lines.append("")
        lines.append(f"### Khu vực: {area}")
        for domain in _DEVICE_DOMAINS:
            entries = area_devices[area].get(domain)
            if not entries:
                continue
            label = _DOMAIN_LABELS.get(domain, domain)
            lines.append(f"- {label}: " + "; ".join(sorted(entries)))
    if unassigned:
        lines.append("")
        lines.append("### Thiết bị chưa gán khu vực")
        for domain in _DEVICE_DOMAINS:
            entries = unassigned.get(domain)
            if not entries:
                continue
            label = _DOMAIN_LABELS.get(domain, domain)
            lines.append(f"- {label}: " + "; ".join(sorted(entries)))

    # ── Service catalog (tham số điều khiển — live từ /api/services) ─────
    try:
        catalog = get_service_catalog(use_cache=False)
    except Exception:
        catalog = {}
    if catalog:
        lines.append("")
        lines.append("## Service & tham số (schema live HA)")
        lines.append("")
        lines.append(
            "Danh sách rút gọn domain hay dùng. Field chi tiết thay đổi theo "
            "version HA — agent nên ưu tiên ha_describe_actions / ha_get_services."
        )
        for dom in (
            "light", "switch", "climate", "fan", "cover", "lock",
            "media_player", "scene", "script", "automation",
        ):
            svcs = catalog.get(dom) or {}
            if not svcs:
                continue
            lines.append("")
            lines.append(f"### Domain `{dom}`")
            for svc_name in sorted(svcs.keys())[:12]:
                meta = svcs[svc_name] or {}
                fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
                # flatten nested field groups
                fnames: list[str] = []
                for fk, fv in list(fields.items())[:16]:
                    if (
                        isinstance(fv, dict)
                        and isinstance(fv.get("fields"), dict)
                        and "selector" not in fv
                    ):
                        fnames.extend(list(fv["fields"].keys())[:8])
                    else:
                        fnames.append(str(fk))
                if fnames:
                    lines.append(f"- `{dom}.{svc_name}`: {', '.join(fnames[:18])}")
                else:
                    lines.append(f"- `{dom}.{svc_name}`")

    # ── Automation ───────────────────────────────────────────────────────
    automations = by_domain.get("automation", [])
    lines.append("")
    lines.append(f"## Automation ({len(automations)})")
    for s in sorted(automations, key=_friendly):
        attrs = s.get("attributes") or {}
        status = "đang bật" if s.get("state") == "on" else "đang tắt"
        last = str(attrs.get("last_triggered") or "")[:16].replace("T", " ")
        last_txt = f", chạy lần cuối {last}" if last else ""
        lines.append(f"- {_friendly(s)} (`{s.get('entity_id')}`) — {status}{last_txt}")

    # ── Script & Scene ───────────────────────────────────────────────────
    scripts = by_domain.get("script", [])
    scenes = by_domain.get("scene", [])
    if scripts:
        lines.append("")
        lines.append(f"## Script ({len(scripts)})")
        for s in sorted(scripts, key=_friendly):
            lines.append(f"- {_friendly(s)} (`{s.get('entity_id')}`)")
    if scenes:
        lines.append("")
        lines.append(f"## Scene ({len(scenes)})")
        for s in sorted(scenes, key=_friendly):
            lines.append(f"- {_friendly(s)} (`{s.get('entity_id')}`)")

    # ── Cảm biến chính ───────────────────────────────────────────────────
    sensors = [
        s for s in by_domain.get("sensor", [])
        if (s.get("attributes") or {}).get("device_class") in _SENSOR_CLASSES
    ]
    if sensors:
        lines.append("")
        lines.append(f"## Cảm biến chính ({len(sensors)})")
        by_class: dict[str, list[str]] = defaultdict(list)
        for s in sensors:
            attrs = s.get("attributes") or {}
            unit = str(attrs.get("unit_of_measurement") or "")
            area = entity_area.get(s.get("entity_id", ""), "")
            loc = f" [{area}]" if area else ""
            by_class[str(attrs.get("device_class"))].append(
                f"{_friendly(s)}{loc} (`{s.get('entity_id')}`, đơn vị {unit or 'không rõ'})"
            )
        for cls in sorted(by_class):
            lines.append("")
            lines.append(f"### {cls}")
            for entry in sorted(by_class[cls])[:80]:
                lines.append(f"- {entry}")

    # ── Người / presence ─────────────────────────────────────────────────
    persons = by_domain.get("person", [])
    if persons:
        lines.append("")
        lines.append(f"## Thành viên ({len(persons)})")
        for s in sorted(persons, key=_friendly):
            lines.append(f"- {_friendly(s)} (`{s.get('entity_id')}`)")

    doc = "\n".join(lines)
    logger.info({
        "event": "ha_docs_built",
        "chars": len(doc),
        "areas": len(area_devices),
        "automations": len(automations),
    })
    return doc
