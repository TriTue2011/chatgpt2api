"""Xác minh lệnh nhà thông minh: ĐỌC LẠI trạng thái thay vì tin lời pipeline.

**Vì sao cần.** `control_home` gửi câu tự nhiên sang pipeline Home Assistant rồi
lấy nguyên câu trả lời của pipeline làm kết quả. Pipeline nói "đã thực hiện xong"
là bot báo "dạ em bật đèn rồi ạ" — kể cả khi đèn mất kết nối, thiết bị bị loại
khỏi danh sách cho phép, hay pipeline khớp nhầm sang một thực thể khác. Người
dùng chỉ phát hiện khi bước vào phòng thấy tối.

Ý này lấy từ `luuquangvu/assist-canonicalizer` (bước preflight + thử lại có giới
hạn). Phần xếp hạng đa tín hiệu của repo đó dự án đã có ở `ha_intent_rank`.

**Cách làm.** Chụp trạng thái các thực thể ĐIỀU KHIỂN ĐƯỢC trước khi gửi lệnh,
gửi lệnh, rồi đọc lại và so sánh. Thiết bị thật cần thời gian phản hồi (Zigbee
qua vài chặng), nên đọc lại vài lần cách nhau ngắn thay vì kết luận ngay ở lần
đầu — đúng chỗ mà kết luận vội sẽ báo oan là "chưa ăn".

**Hợp đồng.** Không bao giờ ném lỗi. Chưa cấu hình HA, HA lỗi, hay không đọc
được thì trả rỗng và người gọi giữ nguyên hành vi cũ.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

#: Chỉ những domain NGƯỜI DÙNG ra lệnh được. Bỏ `sensor`/`binary_sensor` vì
#: nhiệt độ, độ ẩm, công suất đổi liên tục theo thời gian — đưa vào thì lệnh nào
#: cũng "có thay đổi", và lời xác minh thành vô nghĩa.
DOMAIN_DIEU_KHIEN = frozenset({
    "light", "switch", "fan", "climate", "cover", "lock", "media_player",
    "vacuum", "humidifier", "water_heater", "valve", "siren",
    "input_boolean", "input_number", "input_select", "scene", "script",
    "automation", "button", "select", "number",
})

#: Đọc lại tối đa mấy lần và giãn cách bao lâu. 4 lần × 0,45 giây ≈ 1,8 giây —
#: đủ cho đèn Zigbee báo trạng thái về, mà chưa làm người dùng thấy bot đơ.
SO_LAN_DOC = 4
GIAN_CACH = 0.45


def _trang_thai_hien_tai() -> dict[str, dict[str, Any]]:
    """{entity_id: bản ghi} của các thực thể điều khiển được. Rỗng nếu không đọc được."""
    try:
        from services import ha_client
        # use_cache=False: xác minh mà đọc bộ nhớ đệm thì so chính mình với
        # chính mình, không bao giờ thấy thay đổi.
        ds = ha_client.get_states(use_cache=False) or []
    except Exception as exc:
        logger.debug("ha_xac_minh: đọc trạng thái lỗi: %s", str(exc)[:120])
        return {}
    ra: dict[str, dict[str, Any]] = {}
    for m in ds:
        if not isinstance(m, dict):
            continue
        eid = str(m.get("entity_id") or "")
        if eid.split(".", 1)[0] in DOMAIN_DIEU_KHIEN:
            ra[eid] = m
    return ra


def chup() -> dict[str, str]:
    """Ảnh chụp {entity_id: trạng thái} TRƯỚC khi ra lệnh."""
    return {k: str(v.get("state") or "") for k, v in _trang_thai_hien_tai().items()}


def _ten(m: dict[str, Any], eid: str) -> str:
    thuoc = m.get("attributes") if isinstance(m.get("attributes"), dict) else {}
    return str((thuoc or {}).get("friendly_name") or eid)


def doi_chieu(truoc: dict[str, str], *, cho: bool = True) -> list[dict[str, str]]:
    """So với ảnh chụp trước → danh sách thực thể ĐÃ ĐỔI trạng thái.

    ``cho=False`` thì đọc đúng một lần, không chờ — dùng cho test và cho lúc
    người gọi đã tự chờ xong.
    """
    if not truoc:
        return []
    doi: list[dict[str, str]] = []
    for lan in range(SO_LAN_DOC if cho else 1):
        sau = _trang_thai_hien_tai()
        if not sau:
            return []
        doi = []
        for eid, m in sau.items():
            cu = truoc.get(eid)
            moi = str(m.get("state") or "")
            # Thực thể MỚI xuất hiện (cu is None) không phải "đã đổi": có thể do
            # HA vừa nạp lại một integration, không liên quan tới lệnh vừa gửi.
            if cu is not None and cu != moi:
                doi.append({"entity_id": eid, "ten": _ten(m, eid), "tu": cu, "sang": moi})
        if doi:
            return doi
        if cho and lan < SO_LAN_DOC - 1:
            time.sleep(GIAN_CACH)
    return doi


def mo_ta(doi: list[dict[str, str]]) -> str:
    """Câu thuật lại thay đổi ĐO ĐƯỢC, để model dựa vào đó trả lời cho đúng.

    Trả "" khi không có thay đổi nào — người gọi tự quyết định nói gì, vì
    "không đổi" có thể là lệnh trượt mà cũng có thể là thiết bị vốn đã đúng
    trạng thái người dùng muốn.
    """
    if not doi:
        return ""
    phan = [f"{m['ten']}: {m['tu']} → {m['sang']}" for m in doi[:6]]
    them = f" (và {len(doi) - 6} thiết bị khác)" if len(doi) > 6 else ""
    return "đo lại trạng thái thấy: " + "; ".join(phan) + them
