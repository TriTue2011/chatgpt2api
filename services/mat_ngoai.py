"""Nhận mặt từ THIẾT BỊ NGOÀI (Hanet, Double Take, CompreFace, image_processing của HA…).

Chủ máy 27/09/2026: "nếu tôi có hannet hoặc bất kỳ thiết bị nào nhận diện được khuôn mặt thì
tôi nối qua mqtt hoặc ha vào như nào. Kể cả ở phần thông báo nhận diện hiện nay, nếu lấy được
ảnh khuôn mặt qua api hoặc kết nối nào đó thì gắn vào c2a như nào để gửi cùng".

MỘT hợp đồng, hai đường vào (xem README «Thiết bị nhận mặt ngoài»):

* MQTT: đăng JSON lên chủ đề ``c2a/khuon_mat`` (hoặc ``c2a/khuon_mat/<tên thiết bị>``) — luồng
  `mqtt_nha` đang nghe sẵn mọi nhánh.
* HTTP: ``POST /api/nhin-nha/mat-ngoai`` kèm khoá admin — cho ``rest_command`` của Home Assistant.

JSON: ``{"ten": "Con trai Trí Anh", "vi_tri": "Cổng", "anh": "<URL | base64>", "do_tin": 0.93}``.
Nhận thêm tên trường thường gặp của thiết bị (``personName``, ``deviceName``/``placeName``,
``detected_image_url``…) để khỏi phải viết lớp chuyển đổi ở giữa — chỉ ở biên hệ thống này.

Tên phải trùng tên người đã dạy mặt trong c2a mới được tính là người nhà (ghi lượt gặp, trông
xe coi là người nhà). Tên lạ vẫn báo tin — kèm lời nhắc đặt cùng tên.
"""
from __future__ import annotations

import base64
import binascii
import time
from typing import Any
from urllib.parse import urlsplit

from utils.log import logger

CHU_DE = "c2a/khuon_mat"
#: Ảnh mặt tải về tối đa ngần này byte.
TOI_DA_BYTE = 5_000_000

_TRUONG_TEN = ("ten", "personName", "person_name", "name", "person")
_TRUONG_VI_TRI = ("vi_tri", "camera", "deviceName", "placeName", "location", "device")
_TRUONG_ANH = ("anh", "anh_url", "image", "image_url", "detected_image_url", "snapshot", "photo")
_TRUONG_TIN = ("do_tin", "confidence", "score", "similarity")

_da_bao: dict[tuple[str, str], float] = {}


def _lay(d: dict[str, Any], truong: tuple[str, ...]) -> Any:
    return next((d[k] for k in truong if d.get(k) not in (None, "")), None)


def _tai_anh(anh: Any) -> bytes:
    """Ảnh từ thiết bị → byte JPEG/PNG. Nhận base64 (có hoặc không ``data:``), URL của chính
    Home Assistant đã khai (tải kèm token — máy chủ tự cấu hình, thường ở mạng trong nhà),
    đường ``/api/...`` của HA, hoặc URL công khai (qua `net_guard.safe_fetch`, chặn địa chỉ nội
    bộ). Không lấy được thì trả b"" — tin vẫn đi, chỉ thiếu ảnh."""
    s = str(anh or "").strip()
    if not s:
        return b""
    try:
        if s.startswith("data:"):
            return base64.b64decode(s.split(",", 1)[1], validate=False)[:TOI_DA_BYTE]
        # Base64 của JPEG luôn mở đầu "/9j/" — đường HA phải nhận theo "/api/", không theo "/".
        if not s.startswith(("http://", "https://", "/api/")):
            return base64.b64decode(s, validate=True)[:TOI_DA_BYTE]
        from services import ha_client
        ha = ha_client._get_ha_config()
        if ha and (s.startswith("/api/") or urlsplit(s).netloc == urlsplit(ha["url"]).netloc):
            import httpx
            url = ha["url"] + s if s.startswith("/api/") else s
            r = httpx.get(url, headers={"Authorization": f"Bearer {ha['token']}"}, timeout=10)
            r.raise_for_status()
            return r.content[:TOI_DA_BYTE]
        if s.startswith("/api/"):
            return b""
        from services import net_guard
        return net_guard.safe_fetch(s, timeout=10, max_bytes=TOI_DA_BYTE)
    except (ValueError, binascii.Error):
        return b""
    except Exception as exc:  # noqa: BLE001 — ảnh hỏng không được làm mất tin báo
        logger.info({"event": "mat_ngoai_anh_loi", "loi": str(exc)[:160]})
        return b""


def _luu_anh(du_lieu: bytes) -> str:
    """Byte ảnh → URL /images/ (cùng thư viện ảnh camera) để kênh chat gửi kèm."""
    if not du_lieu.startswith((b"\xff\xd8", b"\x89PNG")):     # chỉ nhận JPEG / PNG thật
        return ""
    from services.config import config
    from services.local_gateway import gateway_base_url

    duoi = ".png" if du_lieu.startswith(b"\x89PNG") else ".jpg"
    thu_muc = config.images_dir / time.strftime("%Y") / time.strftime("%m") / time.strftime("%d")
    thu_muc.mkdir(parents=True, exist_ok=True)
    tep = f"mat_ngoai_{int(time.time() * 1000)}{duoi}"
    (thu_muc / tep).write_bytes(du_lieu)
    return f"{gateway_base_url()}/images/{time.strftime('%Y/%m/%d')}/{tep}"


def nhan(du_lieu: dict[str, Any], *, nguon: str = "ngoai") -> dict[str, Any]:
    """Một lượt thiết bị ngoài nhận ra mặt. Ghi lượt gặp (nếu tên trùng người đã dạy), báo tin
    «người quen» kèm ảnh (cùng khoá thông báo, cùng cửa sổ gộp ``phien_phut`` với camera).
    Trả ``{"ok", "ten", "nguoi_id", "anh"}`` hoặc ``{"ok": False, "loi"}``."""
    from services import canh_camera_nha, so_mat_nha, thong_bao

    if not isinstance(du_lieu, dict):
        return {"ok": False, "loi": "Cần một đối tượng JSON."}
    ten = " ".join(str(_lay(du_lieu, _TRUONG_TEN) or "").split())
    if not ten:
        return {"ok": False, "loi": "Thiếu tên người (trường «ten»)."}
    vi_tri = " ".join(str(_lay(du_lieu, _TRUONG_VI_TRI) or nguon).split())[:60]
    try:
        tin = float(_lay(du_lieu, _TRUONG_TIN) or 0)
    except (TypeError, ValueError):
        tin = 0.0
    tin = tin * 100 if 0 < tin <= 1 else tin
    ts = time.time()
    anh_url = _luu_anh(_tai_anh(_lay(du_lieu, _TRUONG_ANH)))
    nguoi = so_mat_nha.tim_nguoi(ten)
    if nguoi:
        so_mat_nha.ghi_su_kien(vi_tri, f"ngoai:{nguon}", "quen", nguoi_id=nguoi["id"],
                               do_giong=tin, anh=anh_url, ts=ts)
    logger.info({"event": "mat_ngoai", "nguon": nguon, "vi_tri": vi_tri, "khop": bool(nguoi)})
    c = canh_camera_nha.cfg()
    phien = canh_camera_nha._so(c.get("phien_phut"), 10.0, 0.5, 24 * 60) * 60
    khoa = (vi_tri, ten)
    if ts - _da_bao.get(khoa, 0.0) >= phien:
        _da_bao[khoa] = ts
        thong_bao.gui("camera.nguoi_quen",
                      f"🏠 {nguoi['ten'] if nguoi else ten} — {vi_tri} lúc {time.strftime('%H:%M')} "
                      f"(thiết bị {nguon})."
                      + ("" if nguoi else f"\n(«{ten}» chưa có trong sổ mặt của c2a — đặt cùng tên "
                                          "để trông xe/tìm người coi là người nhà.)"),
                      anh_url)
    return {"ok": True, "ten": nguoi["ten"] if nguoi else ten, "nguoi_id": nguoi["id"] if nguoi else None,
            "anh": anh_url}


def tu_mqtt(chu_de: str, payload: bytes) -> None:
    """Tin trên ``c2a/khuon_mat[/<thiết bị>]``. Không bao giờ raise (đang ở luồng MQTT)."""
    import json

    try:
        du_lieu = json.loads(payload.decode("utf-8", "replace"))
        phan = chu_de.split("/")
        nhan(du_lieu, nguon=phan[2] if len(phan) > 2 and phan[2] else "mqtt")
    except Exception as exc:  # noqa: BLE001
        logger.warning({"event": "mat_ngoai_mqtt_loi", "loi": str(exc)[:160]})
