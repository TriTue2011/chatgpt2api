"""Home Assistant REST API client via Long-Lived Access Token.

Fetches entity states and calls services so the LLM can see and control
the smart home directly, without needing the HA voice pipeline.
"""

from __future__ import annotations

import json, logging
from typing import Any
import urllib.request

from services.config import config
from utils.log import logger


def _get_ha_config() -> dict[str, str] | None:
    ha = config.data.get("home_assistant") or {}
    url = str(ha.get("url") or "").strip().rstrip("/")
    token = str(ha.get("token") or "").strip()
    if not url or not token:
        return None
    return {"url": url, "token": token}


def get_states() -> list[dict[str, Any]]:
    """Fetch all entity states from HA. Returns empty list if not configured."""
    cfg = _get_ha_config()
    if not cfg:
        return []
    try:
        req = urllib.request.Request(
            f"{cfg['url']}/api/states",
            headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"},
        )
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as exc:
        logger.warning({"event": "ha_states_failed", "error": str(exc)})
        return []


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
    """Call an HA service (e.g., light.turn_on)."""
    cfg = _get_ha_config()
    if not cfg:
        return False
    try:
        body = json.dumps({"entity_id": data.get("entity_id", "")}) if data else "{}"
        req = urllib.request.Request(
            f"{cfg['url']}/api/services/{domain}/{service}",
            data=body.encode(),
            headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as exc:
        logger.warning({"event": "ha_service_failed", "domain": domain, "service": service, "error": str(exc)})
        return False


def format_states_context() -> str:
    """Format HA entity states as LLM context string."""
    states = get_states()
    if not states:
        return ""
    lines = ["## Smart Home State"]
    for s in states[:100]:  # limit to 100 most relevant
        eid = s.get("entity_id", "")
        state = s.get("state", "")
        attrs = s.get("attributes", {})
        friendly = attrs.get("friendly_name", "")
        unit = attrs.get("unit_of_measurement", "")
        label = f"{friendly} ({eid})" if friendly else eid
        line = f"- {label}: {state}"
        if unit:
            line += f" {unit}"
        lines.append(line)
    return "\n".join(lines)


def inject_ha_context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inject HA state context as a system message before the last user message."""
    ctx = format_states_context()
    if not ctx:
        return messages

    result = list(messages)
    # Insert before the last user message
    insert_pos = len(result)
    for i in range(len(result) - 1, -1, -1):
        if result[i].get("role") == "user":
            insert_pos = i
            break
    result.insert(insert_pos, {"role": "system", "content": ctx})
    logger.info({"event": "ha_context_injected", "states_len": len(ctx)})
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
                "name": "ha_get_state",
                "description": "Lấy trạng thái 1 thiết bị Home Assistant theo entity_id.",
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
                "name": "ha_call_service",
                "description": "Gọi Home Assistant service để điều khiển thiết bị (bật/tắt đèn, khóa cửa, v.v.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "Domain: light, switch, lock, climate, cover..."},
                        "service": {"type": "string", "description": "Service: turn_on, turn_off, toggle, lock, unlock..."},
                        "entity_id": {"type": "string", "description": "Entity ID đầy đủ (vd: light.ban_cong)"},
                    },
                    "required": ["domain", "service", "entity_id"],
                },
            },
        },
    ]


def execute_ha_tool(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Execute an HA tool and return result text."""
    if tool_name == "ha_get_state":
        eid = arguments.get("entity_id", "")
        state = get_state(eid)
        if state is None:
            return f"Không tìm thấy thiết bị '{eid}'"
        return json.dumps(state, ensure_ascii=False, indent=2)
    elif tool_name == "ha_call_service":
        domain = arguments.get("domain", "")
        service = arguments.get("service", "")
        entity_id = arguments.get("entity_id", "")
        ok = call_service(domain, service, {"entity_id": entity_id})
        return f"Đã gọi {domain}.{service} cho {entity_id}" if ok else f"Lỗi gọi {domain}.{service}"
    return None
