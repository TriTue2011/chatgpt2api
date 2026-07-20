"""ha_helper — tools chuyên cho Home Assistant voice assistant.

Bổ sung cho HA conversation agent: giờ hoàng đạo, gợi ý format câu lệnh,
tips tránh từ khoá nhập nhằng giữa device names và verbs.

Tools:
- get_hoang_dao_today(): giờ hoàng đạo hôm nay (cho automation kiểu cúng/khai trương)
- check_command_format(text): kiểm tra câu lệnh HA voice có rõ ràng không
- list_command_patterns(): list mẫu câu HA voice tốt
"""

from __future__ import annotations

import os
import threading
import httpx
from datetime import date
import difflib

from fastmcp import FastMCP

mcp = FastMCP("ha_helper")

# 12 giờ hoàng đạo theo can chi truyền thống VN.
HOANG_DAO_BY_DAY_CHI = {
    "Tý": ["Tý", "Sửu", "Mão", "Ngọ", "Thân", "Dậu"],
    "Sửu": ["Dần", "Mão", "Tỵ", "Thân", "Tuất", "Hợi"],
    "Dần": ["Tý", "Sửu", "Thìn", "Tỵ", "Mùi", "Tuất"],
    "Mão": ["Tý", "Dần", "Mão", "Ngọ", "Mùi", "Dậu"],
    "Thìn": ["Dần", "Thìn", "Tỵ", "Thân", "Dậu", "Hợi"],
    "Tỵ": ["Sửu", "Thìn", "Ngọ", "Mùi", "Tuất", "Hợi"],
    "Ngọ": ["Tý", "Sửu", "Mão", "Ngọ", "Thân", "Dậu"],
    "Mùi": ["Dần", "Mão", "Tỵ", "Thân", "Tuất", "Hợi"],
    "Thân": ["Tý", "Sửu", "Thìn", "Tỵ", "Mùi", "Tuất"],
    "Dậu": ["Tý", "Dần", "Mão", "Ngọ", "Mùi", "Dậu"],
    "Tuất": ["Dần", "Thìn", "Tỵ", "Thân", "Dậu", "Hợi"],
    "Hợi": ["Sửu", "Thìn", "Ngọ", "Mùi", "Tuất", "Hợi"],
}

CHI_HOURS = {
    "Tý": "23:00-01:00", "Sửu": "01:00-03:00", "Dần": "03:00-05:00",
    "Mão": "05:00-07:00", "Thìn": "07:00-09:00", "Tỵ": "09:00-11:00",
    "Ngọ": "11:00-13:00", "Mùi": "13:00-15:00", "Thân": "15:00-17:00",
    "Dậu": "17:00-19:00", "Tuất": "19:00-21:00", "Hợi": "21:00-23:00",
}

CHI_LIST = ["Tý", "Sửu", "Dần", "Mão", "Thìn", "Tỵ", "Ngọ", "Mùi", "Thân", "Dậu", "Tuất", "Hợi"]


def _day_chi(d: date) -> str:
    """Tính chi của ngày dương lịch (theo công thức truyền thống)."""
    # Chi của ngày 1/1/2000 là "Quý Mùi" → chi = Mùi (index 7)
    # Chu kỳ chi: ngày sau cộng 1, mod 12.
    delta = (d - date(2000, 1, 1)).days
    return CHI_LIST[(7 + delta) % 12]


@mcp.tool()
def get_hoang_dao_today() -> str:
    """Tính giờ hoàng đạo hôm nay (theo lịch can chi truyền thống VN).

    Returns:
        Danh sách 6 giờ hoàng đạo trong ngày kèm khung giờ dương.
    """
    today = date.today()
    chi = _day_chi(today)
    hoang_dao_chi = HOANG_DAO_BY_DAY_CHI.get(chi, [])
    if not hoang_dao_chi:
        return f"Không tính được giờ hoàng đạo cho ngày {today.isoformat()}."
    lines = [
        f"**Giờ hoàng đạo {today.isoformat()} (ngày {chi}):**",
        "",
    ]
    for c in hoang_dao_chi:
        lines.append(f"- Giờ {c}: {CHI_HOURS[c]}")
    return "\n".join(lines)


@mcp.tool()
def check_command_format(text: str) -> str:
    """Kiểm tra câu lệnh HA voice có dễ hiểu cho intent recognition không.

    Args:
        text: Câu lệnh người dùng (vd: "bật đèn phòng khách").

    Returns:
        Đánh giá + gợi ý cải thiện nếu câu lệnh nhập nhằng.
    """
    t = text.strip().lower()
    issues: list[str] = []
    if len(t) < 5:
        issues.append("Câu quá ngắn — HA có thể không xác định được intent.")
    if len(t) > 100:
        issues.append("Câu quá dài — nên tách thành 2 lệnh ngắn.")
    verbs = ["bật", "tắt", "mở", "đóng", "khoá", "tăng", "giảm", "đặt"]
    if not any(v in t for v in verbs):
        issues.append("Thiếu động từ rõ ràng (bật/tắt/mở/đóng/khoá...).")
    if " và " in t or " thì " in t:
        issues.append("Câu có nhiều mệnh đề — nên tách lệnh.")

    if not issues:
        return f"✅ Câu lệnh '{text}' rõ ràng, HA voice nên hiểu được."
    return f"⚠️ Câu lệnh '{text}' có vấn đề:\n" + "\n".join(f"- {i}" for i in issues)


@mcp.tool()
def list_command_patterns() -> str:
    """Liệt kê các mẫu câu HA voice thường được nhận diện tốt.

    Returns:
        Danh sách mẫu câu kèm ví dụ.
    """
    patterns = [
        ("Bật/tắt thiết bị", "bật đèn phòng khách", "tắt quạt phòng ngủ"),
        ("Đặt giá trị", "đặt nhiệt độ điều hòa 25 độ", "đặt độ sáng đèn 50%"),
        ("Trạng thái", "trạng thái cửa chính", "kiểm tra camera sân"),
        ("Câu hỏi cảm biến", "nhiệt độ phòng khách bao nhiêu", "độ ẩm trong nhà"),
        ("Quy tắc thời gian", "đặt báo thức 6 giờ sáng", "tắt đèn sau 30 phút"),
    ]
    lines = ["**Mẫu câu HA voice tốt:**", ""]
    for name, ex1, ex2 in patterns:
        lines.append(f"- **{name}**:")
        lines.append(f"  - Ví dụ: \"{ex1}\"")
        lines.append(f"  - Ví dụ: \"{ex2}\"")
    return "\n".join(lines)


# --- Home Assistant API Integration ---

# Client DÙNG CHUNG: tiến trình MCP hub sống nhiều ngày, tạo httpx.Client mới
# mỗi lần gọi tool sẽ rò connection pool + socket cho tới khi cạn file
# descriptor. httpx.Client an toàn đa luồng nên tái dùng được; chỉ dựng lại khi
# HASS_URL/HASS_TOKEN đổi.
_ha_client: httpx.Client | None = None
_ha_client_key: tuple[str, str] = ("", "")
_ha_client_lock = threading.Lock()


def _get_ha_client() -> httpx.Client | None:
    global _ha_client, _ha_client_key
    url = os.environ.get("HASS_URL", "").rstrip("/")
    token = os.environ.get("HASS_TOKEN", "")
    if not url or not token:
        return None
    with _ha_client_lock:
        if _ha_client is not None and _ha_client_key == (url, token):
            return _ha_client
        if _ha_client is not None:
            try:
                _ha_client.close()
            except Exception:
                pass
        _ha_client = httpx.Client(
            base_url=url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=10.0,
        )
        _ha_client_key = (url, token)
        return _ha_client


def _ha_states(client: httpx.Client) -> list[dict]:
    """GET /api/states -> list. Raise khi HA trả lỗi (401/500) hoặc body lạ —
    caller bắt Exception rồi báo người dùng, thay vì để dict lỗi lọt xuống
    _fuzzy_match_entity gây TypeError khó hiểu."""
    resp = client.get("/api/states")
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"HA trả dữ liệu không phải danh sách entity: {str(data)[:160]}")
    return data


@mcp.tool()
def ha_list_devices(domain: str = "") -> str:
    """Lấy danh sách các thiết bị/entity trong Home Assistant kèm theo tên (friendly_name) và trạng thái hiện tại.
    Rất hữu ích để tìm tên thiết bị trước khi gọi lệnh điều khiển.
    
    Args:
        domain: (Tuỳ chọn) Lọc theo loại thiết bị (vd: light, switch, climate, fan, cover). Nếu để trống sẽ lấy tất cả.
    """
    client = _get_ha_client()
    if not client:
        return "Lỗi: Chưa cấu hình HASS_URL và HASS_TOKEN trong biến môi trường."
    
    try:
        states = _ha_states(client)
    except Exception as e:
        return f"Lỗi khi kết nối HA: {e}"
    
    lines = []
    for s in states:
        entity_id = s.get("entity_id", "")
        if domain and not entity_id.startswith(f"{domain}."):
            continue
        # Bỏ qua các domain hệ thống không cần thiết
        if not domain and entity_id.split(".")[0] in ("sensor", "binary_sensor", "sun", "zone", "person", "device_tracker", "update", "weather"):
            continue
            
        name = s.get("attributes", {}).get("friendly_name", entity_id)
        state = s.get("state", "unknown")
        lines.append(f"- Tên: '{name}' | Entity: {entity_id} | Trạng thái: {state}")
        
    if not lines:
        return f"Không tìm thấy thiết bị nào{' thuộc domain ' + domain if domain else ''}."
    
    return "Danh sách thiết bị:\n" + "\n".join(lines)


def _fuzzy_match_entity(target_name: str, states: list[dict]) -> str | None:
    """Tìm entity_id dựa trên tên (friendly_name) hoặc entity_id bằng fuzzy matching."""
    target = target_name.lower().strip()
    
    # 1. Exact match entity_id
    for s in states:
        if s["entity_id"].lower() == target:
            return s["entity_id"]
            
    # 2. Exact match friendly_name
    for s in states:
        name = s.get("attributes", {}).get("friendly_name", "").lower()
        if name == target:
            return s["entity_id"]
            
    # 3. Fuzzy match friendly_name
    names = {s.get("attributes", {}).get("friendly_name", ""): s["entity_id"] for s in states if s.get("attributes", {}).get("friendly_name")}
    matches = difflib.get_close_matches(target_name, names.keys(), n=1, cutoff=0.6)
    if matches:
        return names[matches[0]]
        
    return None


def _normalize_control_service(domain: str, action: str, has_light_opts: bool) -> str:
    """Map friendly action → HA service name for domain."""
    try:
        # Prefer shared helper when running inside monorepo gateway context
        from services.ha_client import normalize_control_service
        return normalize_control_service(domain, action, has_light_opts=has_light_opts)
    except Exception:
        pass
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


@mcp.tool()
def ha_control_device(
    name: str,
    action: str,
    temperature: float | None = None,
    brightness: int | None = None,
    brightness_pct: int | None = None,
    brightness_step_pct: int | None = None,
    color_name: str | None = None,
    color_temp_kelvin: int | None = None,
    rgb_color: str | None = None,
    transition: float | None = None,
    effect: str | None = None,
    position: int | None = None,
    fan_mode: str | None = None,
    hvac_mode: str | None = None,
    humidity: int | None = None,
    preset_mode: str | None = None,
    percentage: int | None = None,
) -> str:
    """Điều khiển thiết bị Home Assistant BẰNG TÊN (hoặc entity_id).

    Tham số tường minh (FastMCP không hỗ trợ **kwargs). Chỉ điền field cần dùng.
    Xem ha_describe_actions(name) để biết thiết bị hỗ trợ gì.

    Args:
        name: Tên thiết bị (vd "Đèn phòng khách") hoặc entity_id.
        action: turn_on | turn_off | toggle | set_temperature | set_hvac_mode |
            set_fan_mode | set_humidity | set_preset_mode | open_cover | close_cover |
            set_cover_position | set_percentage | ...
        temperature: Nhiệt độ đích (climate).
        brightness: Độ sáng 0-255 (light).
        brightness_pct: Độ sáng % 0-100 (light).
        brightness_step_pct: Tăng/giảm % (light), vd 10 hoặc -10.
        color_name: Tên màu (light), vd "red", "warmwhite".
        color_temp_kelvin: Nhiệt độ màu kelvin (light), vd 2700–6500.
        rgb_color: Màu RGB dạng "255,100,50" hoặc "[255,100,50]".
        transition: Số giây chuyển mượt (light).
        effect: Hiệu ứng đèn (nếu hỗ trợ).
        position: Vị trí rèm 0-100 (cover).
        fan_mode: Chế độ quạt climate, vd "auto".
        hvac_mode: heat | cool | heat_cool | auto | off | dry | fan_only.
        humidity: Độ ẩm đích % (climate).
        preset_mode: Preset climate/fan, vd "away", "sleep".
        percentage: Tốc độ quạt % 0-100 (fan).
    """
    # FastMCP: mọi tham số phải khai báo tường minh — gom non-None thành payload.
    raw_opts = {
        "temperature": temperature,
        "brightness": brightness,
        "brightness_pct": brightness_pct,
        "brightness_step_pct": brightness_step_pct,
        "color_name": color_name,
        "color_temp_kelvin": color_temp_kelvin,
        "rgb_color": rgb_color,
        "transition": transition,
        "effect": effect,
        "position": position,
        "fan_mode": fan_mode,
        "hvac_mode": hvac_mode,
        "humidity": humidity,
        "preset_mode": preset_mode,
        "percentage": percentage,
    }
    opts = {k: v for k, v in raw_opts.items() if v is not None}

    client = _get_ha_client()
    if not client:
        return "Lỗi: Chưa cấu hình HASS_URL và HASS_TOKEN trong biến môi trường."

    try:
        states = _ha_states(client)
    except Exception as e:
        return f"Lỗi lấy trạng thái HA: {e}"

    entity_id = _fuzzy_match_entity(name, states)
    if not entity_id:
        return (
            f"Không tìm thấy thiết bị nào giống với tên '{name}'. "
            f"Hãy dùng ha_list_devices để xem danh sách tên chính xác."
        )

    domain = entity_id.split(".")[0]
    light_opts = any(
        k in opts for k in (
            "brightness", "brightness_pct", "brightness_step_pct",
            "color_name", "color_temp_kelvin", "rgb_color", "transition", "effect",
        )
    )
    service = _normalize_control_service(domain, action, light_opts)

    # Domain-specific service fixes
    if domain == "cover" and "position" in opts and service in (
        "turn_on", "set_position", "position",
    ):
        service = "set_cover_position"
    if domain == "climate":
        if "hvac_mode" in opts and service in ("turn_on", "set_mode"):
            service = "set_hvac_mode" if "temperature" not in opts else service
        if "humidity" in opts and service == "turn_on":
            service = "set_humidity"
        if "preset_mode" in opts and service == "turn_on":
            service = "set_preset_mode"
        if "fan_mode" in opts and service == "turn_on" and "temperature" not in opts:
            service = "set_fan_mode"
        if "temperature" in opts and service in ("turn_on", "set_temp"):
            service = "set_temperature"
    if domain == "fan" and "percentage" in opts and service in ("turn_on", "set_speed"):
        service = "set_percentage"
    if domain == "fan" and "preset_mode" in opts and service == "turn_on":
        service = "set_preset_mode"

    payload: dict = {"entity_id": entity_id}

    def _put_num(key: str, cast=float):
        if key in opts:
            try:
                payload[key] = cast(opts[key])
            except (TypeError, ValueError):
                pass

    _put_num("temperature", float)
    _put_num("brightness", int)
    _put_num("brightness_pct", int)
    _put_num("brightness_step_pct", int)
    _put_num("color_temp_kelvin", int)
    _put_num("transition", float)
    _put_num("position", int)
    _put_num("humidity", int)
    _put_num("percentage", int)
    if "color_name" in opts:
        payload["color_name"] = str(opts["color_name"]).strip()
    if "effect" in opts:
        payload["effect"] = str(opts["effect"]).strip()
    if "fan_mode" in opts:
        payload["fan_mode"] = str(opts["fan_mode"]).strip()
    if "hvac_mode" in opts:
        payload["hvac_mode"] = str(opts["hvac_mode"]).strip()
    if "preset_mode" in opts:
        payload["preset_mode"] = str(opts["preset_mode"]).strip()
    if "rgb_color" in opts:
        raw = str(opts["rgb_color"]).strip().strip("[]()")
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        try:
            if len(parts) >= 3:
                payload["rgb_color"] = [int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))]
        except (TypeError, ValueError):
            return f"❌ rgb_color không hợp lệ: {opts['rgb_color']} (cần dạng 255,100,50)"

    # cover uses position in set_cover_position
    if service == "set_cover_position" and "position" in payload:
        pass  # already set
    elif service == "set_percentage" and "percentage" not in payload and "brightness_pct" in payload:
        payload["percentage"] = payload.pop("brightness_pct")

    service_url = f"/api/services/{domain}/{service}"
    try:
        resp = client.post(service_url, json=payload)
        resp.raise_for_status()
        return (
            f"✅ Đã thực hiện `{service}` trên **{name}** "
            f"(Entity: `{entity_id}`).\nPayload: `{payload}`"
        )
    except Exception as e:
        hint = ""
        if domain in ("light", "climate", "fan", "cover"):
            hint = f"\nGợi ý: gọi ha_describe_actions(name=\"{name}\") để xem field/service hỗ trợ."
        return f"❌ Lỗi khi gửi lệnh đến HA: {e}\nURL: {service_url}\nPayload: {payload}{hint}"


@mcp.tool()
def ha_describe_actions(name: str) -> str:
    """Mô tả thiết bị hỗ trợ service/tham số nào (schema live từ HA + state).

    Dùng TRƯỚC khi chỉnh màu/nhiệt độ nếu không chắc param.
    Args:
        name: Tên thân thiện hoặc entity_id.
    """
    client = _get_ha_client()
    if not client:
        return "Lỗi: Chưa cấu hình HASS_URL và HASS_TOKEN."
    try:
        states = _ha_states(client)
    except Exception as e:
        return f"Lỗi lấy states: {e}"
    entity_id = _fuzzy_match_entity(name, states)
    if not entity_id:
        return f"Không tìm thấy thiết bị '{name}'. Dùng ha_list_devices."
    st = next((s for s in states if s.get("entity_id") == entity_id), None)
    domain = entity_id.split(".", 1)[0]
    attrs = (st or {}).get("attributes") or {}
    fname = attrs.get("friendly_name") or entity_id
    lines = [
        f"**{fname}** (`{entity_id}`)",
        f"- Trạng thái: `{(st or {}).get('state', '?')}`",
    ]
    # Capability from attributes
    bits = []
    if attrs.get("supported_color_modes"):
        bits.append(f"color_modes={attrs['supported_color_modes']}")
    if attrs.get("min_color_temp_kelvin") or attrs.get("max_color_temp_kelvin"):
        bits.append(
            f"kelvin {attrs.get('min_color_temp_kelvin', '?')}–"
            f"{attrs.get('max_color_temp_kelvin', '?')}"
        )
    if attrs.get("min_temp") is not None:
        bits.append(f"temp {attrs.get('min_temp')}–{attrs.get('max_temp')}")
    for key in ("hvac_modes", "fan_modes", "preset_modes", "effect_list"):
        if attrs.get(key):
            bits.append(f"{key}={attrs.get(key)}")
    if bits:
        lines.append("- Từ state: " + "; ".join(str(b) for b in bits))

    # Live service schema
    try:
        svc_resp = client.get("/api/services")
        svc_resp.raise_for_status()
        catalog = svc_resp.json()
    except Exception as e:
        lines.append(f"- Không lấy được /api/services: {e}")
        return "\n".join(lines)

    domain_block = next((d for d in catalog if d.get("domain") == domain), None)
    services = (domain_block or {}).get("services") or {}
    prefer = [
        "turn_on", "turn_off", "toggle", "set_temperature", "set_hvac_mode",
        "set_fan_mode", "set_humidity", "set_preset_mode", "set_percentage",
        "set_cover_position", "open_cover", "close_cover",
    ]
    lines.append("- Service schema (HA live):")
    shown = 0
    for svc in prefer:
        if svc not in services:
            continue
        meta = services[svc] if isinstance(services[svc], dict) else {}
        fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
        field_names = []
        for fk, fv in list(fields.items())[:16]:
            if isinstance(fv, dict) and isinstance(fv.get("fields"), dict) and "selector" not in fv:
                field_names.extend(list(fv["fields"].keys())[:8])
            else:
                field_names.append(str(fk))
        desc = str(meta.get("description") or meta.get("name") or "")[:80]
        lines.append(
            f"  • `{domain}.{svc}`"
            + (f" — {desc}" if desc else "")
            + (f"\n    fields: {', '.join(field_names)}" if field_names else "")
        )
        shown += 1
        if shown >= 8:
            break
    other = [s for s in sorted(services.keys()) if s not in prefer]
    if other:
        lines.append(f"- Service khác: {', '.join(other[:25])}")
    lines.append(
        "Gợi ý ha_control_device: light→brightness_pct/color_temp_kelvin/rgb_color; "
        "climate→temperature+hvac_mode; cover→position; fan→percentage."
    )
    return "\n".join(lines)


@mcp.tool()
def ha_get_entity_state(entity_id: str) -> str:
    """Lấy thông tin trạng thái và thuộc tính (attributes) chi tiết của một entity_id cụ thể.
    
    Args:
        entity_id: Mã entity_id cần tra cứu (ví dụ: "light.phong_khach").
    """
    client = _get_ha_client()
    if not client:
        return "Lỗi: Chưa cấu hình HASS_URL và HASS_TOKEN."
    try:
        resp = client.get(f"/api/states/{entity_id}")
        if resp.status_code == 404:
            return f"Không tìm thấy entity_id: {entity_id}"
        resp.raise_for_status()
        import json
        return json.dumps(resp.json(), ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Lỗi: {e}"


@mcp.tool()
def ha_get_services(domain: str = "", with_fields: bool = False) -> str:
    """Lấy domain/services HA hỗ trợ (schema live từ /api/services).

    Args:
        domain: Lọc 1 domain (vd light, climate). Trống = tóm tắt mọi domain.
        with_fields: True = in thêm tên field của mỗi service (dài hơn).
    """
    client = _get_ha_client()
    if not client:
        return "Lỗi: Chưa cấu hình HASS_URL và HASS_TOKEN."
    try:
        resp = client.get("/api/services")
        resp.raise_for_status()
        data = resp.json()
        want = (domain or "").strip().lower()
        lines = []
        for d in data:
            dom = d.get("domain") or ""
            if want and dom != want:
                continue
            services = d.get("services") or {}
            if not with_fields:
                lines.append(f"- {dom}: {', '.join(services.keys())}")
                continue
            lines.append(f"### {dom}")
            for svc, meta in list(services.items())[:40]:
                meta = meta if isinstance(meta, dict) else {}
                fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
                fnames = list(fields.keys())[:20]
                lines.append(
                    f"- `{dom}.{svc}`"
                    + (f" fields=[{', '.join(fnames)}]" if fnames else "")
                )
        if not lines:
            return f"Không thấy domain `{domain}`." if want else "Catalog rỗng."
        return "Domain / services (live HA):\n" + "\n".join(lines)
    except Exception as e:
        return f"Lỗi: {e}"


@mcp.tool()
def ha_call_service_advanced(domain: str, service: str, payload: dict) -> str:
    """Gọi một Service bất kỳ trong Home Assistant với payload tùy chỉnh.
    Dùng công cụ này để thực hiện những hành động phức tạp hơn (vd: gọi script, kích hoạt automation, gửi thông báo).
    
    Args:
        domain: Domain của service (vd: "light", "script", "automation", "notify").
        service: Tên service (vd: "turn_on", "trigger", "notify").
        payload: Dữ liệu JSON gửi kèm (vd: {"entity_id": "light.phong_khach", "brightness": 255} hoặc {"message": "Hello"}).
    """
    client = _get_ha_client()
    if not client:
        return "Lỗi: Chưa cấu hình HASS_URL và HASS_TOKEN."
    try:
        resp = client.post(f"/api/services/{domain}/{service}", json=payload)
        resp.raise_for_status()
        return f"✅ Gọi service {domain}.{service} thành công. Phản hồi:\n" + str(resp.json())
    except Exception as e:
        return f"❌ Lỗi: {e}"


@mcp.tool()
def ha_render_template(template: str) -> str:
    """Render một đoạn mã Jinja2 Template trong Home Assistant.
    Công cụ mạnh mẽ để truy vấn nhiều trạng thái, tính toán, hoặc trích xuất dữ liệu tùy biến từ HA.
    
    Args:
        template: Mã Jinja2 (vd: "{{ states('sensor.nhiet_do') }}" hoặc "{% for state in states.light %}...").
    """
    client = _get_ha_client()
    if not client:
        return "Lỗi: Chưa cấu hình HASS_URL và HASS_TOKEN."
    try:
        resp = client.post("/api/template", json={"template": template})
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        return f"Lỗi: {e}"


@mcp.tool()
def ha_call_api(method: str, endpoint: str, json_body: dict | None = None) -> str:
    """Gọi trực tiếp REST API của Home Assistant (GET/POST/PUT/DELETE).
    Cho phép AI quản lý toàn diện Home Assistant (thêm/sửa/xoá automation, đọc log, thay đổi cấu hình, v.v.).
    Tham khảo API: https://developers.home-assistant.io/docs/api/rest/
    
    Args:
        method: HTTP Method ("GET", "POST", "PUT", "DELETE").
        endpoint: Đường dẫn API bắt đầu bằng /api/ (vd: "/api/config/automation/config", "/api/error_log").
        json_body: Dữ liệu JSON gửi kèm (nếu là POST/PUT).
    """
    client = _get_ha_client()
    if not client:
        return "Lỗi: Chưa cấu hình HASS_URL và HASS_TOKEN."
    try:
        req_method = method.upper()
        if req_method == "GET":
            resp = client.get(endpoint)
        elif req_method == "POST":
            resp = client.post(endpoint, json=json_body or {})
        elif req_method == "PUT":
            resp = client.put(endpoint, json=json_body or {})
        elif req_method == "DELETE":
            resp = client.delete(endpoint)
        else:
            return "Method không hợp lệ."
            
        resp.raise_for_status()
        if "application/json" in resp.headers.get("Content-Type", ""):
            import json
            return json.dumps(resp.json(), ensure_ascii=False, indent=2)
        return resp.text
    except Exception as e:
        return f"Lỗi API: {e}"
