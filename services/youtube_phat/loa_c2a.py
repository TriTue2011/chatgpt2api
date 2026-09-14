"""Loa Cast trong Sổ loa c2a — điều khiển THẲNG, không qua Home Assistant.

Chủ máy 14/09/2026 (ảnh tab YouTube "Không đọc được Home Assistant", không còn loa
nào): "ha lỗi, không thấy loa, nên ưu tiên loa trên dự án". Loa Cast chủ máy đã
thêm vào Sổ loa (`services/voice/speakers.py`) được giữ kết nối riêng bằng
pychromecast, nên HA khởi động lại hay mất kết nối thì tab vẫn phát được.

Để phần còn lại của trình phát không phải biết loa đi đường nào, mỗi loa trong sổ
mang mã dạng media_player (`media_player.c2a_<id>`), báo trạng thái cùng hình dạng
state của HA, và nhận lệnh cùng dạng `call_service(domain, service, data)`.

Đo trên máy thật 14/09/2026: nối loa 172.16.10.249 mất 0,17 s; loa đã rút điện
(172.16.10.242) thì chờ hết 6 s mới báo hỏng — nên nối lại chạy nền, đọc trạng
thái không bao giờ phải chờ.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from utils.log import logger

TIEN_TO = "media_player.c2a_"
KIEU_HO_TRO = {"cast"}
NOI_LAI_SAU_GIAY = 30.0
CHO_NOI_KHI_RA_LENH = 6.0

# Bit supported_features như media_player của HA (khớp hằng số trong phat_ha).
PAUSE, SEEK, VOLUME_SET, PLAY_MEDIA, STOP, PLAY = 1, 2, 4, 512, 4096, 16384
TINH_NANG_CAST = PAUSE | SEEK | VOLUME_SET | PLAY_MEDIA | STOP | PLAY
TRANG_THAI_CAST = {"PLAYING": "playing", "PAUSED": "paused", "BUFFERING": "buffering"}


def ma_loa(loa: dict[str, Any]) -> str:
    return TIEN_TO + re.sub(r"[^a-z0-9_]", "_", str(loa.get("id") or "").lower())


def la_loa_c2a(entity_id: Any) -> bool:
    return str(entity_id or "").startswith(TIEN_TO)


def cac_loa() -> list[dict[str, Any]]:
    """Loa trong Sổ loa mà c2a tự phát được luồng nhạc (hiện: Cast)."""
    from services.voice import speakers as vspk

    return [loa for loa in vspk.list_speakers()
            if loa.get("kind") in KIEU_HO_TRO and str(loa.get("host") or "").strip() and loa.get("id")]


def _tao_cast(loa: dict[str, Any]):
    import pychromecast

    cast = pychromecast.get_chromecast_from_host(
        (str(loa["host"]).strip(), int(loa.get("port") or 8009), None, None, str(loa.get("name") or "loa")),
        tries=1, retry_wait=5, timeout=4)
    cast.wait(timeout=5)
    return cast


class _KetNoi:
    """Một kết nối Cast sống lâu cho một loa; nối lại chạy nền, tối đa 30 s một lần."""

    def __init__(self, loa: dict[str, Any], tao: Callable[[dict[str, Any]], Any]):
        self.loa = loa
        self._tao = tao
        self._cast = None
        self._khoa = threading.Lock()
        self._dang_noi = False
        self._lan_thu = 0.0

    def cast(self):
        cast = self._cast
        if cast is not None and getattr(getattr(cast, "socket_client", None), "is_connected", False):
            return cast
        return None

    def noi_nen(self) -> None:
        with self._khoa:
            if self._dang_noi or self.cast() is not None or time.monotonic() - self._lan_thu < NOI_LAI_SAU_GIAY:
                return
            self._dang_noi = True
            self._lan_thu = time.monotonic()
        threading.Thread(target=self._noi, name=f"loa-c2a-{self.loa.get('id')}", daemon=True).start()

    def cho_noi(self, giay: float) -> Any:
        """Ra lệnh mà chưa nối: thử nối ngay (người vừa bấm), chờ tối đa `giay`."""
        if self.cast() is None:
            with self._khoa:
                self._lan_thu = 0.0
            self.noi_nen()
            het = time.monotonic() + giay
            while self.cast() is None and self._dang_noi and time.monotonic() < het:
                time.sleep(0.1)
        return self.cast()

    def _noi(self) -> None:
        cu = self._cast
        try:
            if cu is not None:
                try:
                    cu.disconnect(timeout=1)
                except Exception:  # kết nối cũ hỏng sẵn thì bỏ
                    pass
            self._cast = self._tao(self.loa)
        except Exception as error:  # pychromecast ném nhiều loại cho một lần không tới được
            self._cast = None
            logger.info({"event": "loa_c2a_khong_noi_duoc", "loa": self.loa.get("id"), "loi": str(error)[:120]})
        finally:
            with self._khoa:
                self._dang_noi = False


_khoa = threading.Lock()
_ket_noi: dict[str, _KetNoi] = {}
_tao_mac_dinh: Callable[[dict[str, Any]], Any] = _tao_cast


def _ket_noi_cua(loa: dict[str, Any]) -> _KetNoi:
    ma = ma_loa(loa)
    with _khoa:
        k = _ket_noi.get(ma)
        dia_chi = (str(loa.get("host") or "").strip(), int(loa.get("port") or 8009))
        if k is None or (str(k.loa.get("host") or "").strip(), int(k.loa.get("port") or 8009)) != dia_chi:
            k = _KetNoi(loa, lambda rec: _tao_mac_dinh(rec))
            _ket_noi[ma] = k
        k.loa = loa
        return k


def _moc(gio: Any) -> str | None:
    if not isinstance(gio, datetime):
        return None
    return (gio if gio.tzinfo else gio.replace(tzinfo=timezone.utc)).isoformat()


def trang_thai_tat_ca() -> list[dict[str, Any]]:
    """State kiểu HA cho mọi loa Cast trong sổ; loa chưa nối được là `unavailable`."""
    ket_qua = []
    for loa in cac_loa():
        k = _ket_noi_cua(loa)
        k.noi_nen()
        cast = k.cast()
        thuoc_tinh: dict[str, Any] = {"friendly_name": str(loa.get("name") or loa["id"]), "device_class": "speaker",
                                      "supported_features": TINH_NANG_CAST}
        if cast is None:
            ket_qua.append({"entity_id": ma_loa(loa), "state": "unavailable", "attributes": thuoc_tinh})
            continue
        st = cast.status
        mc = cast.media_controller.status
        if st is not None and isinstance(getattr(st, "volume_level", None), (int, float)):
            thuoc_tinh["volume_level"] = float(st.volume_level)
        if getattr(mc, "content_id", None):
            thuoc_tinh["media_content_id"] = str(mc.content_id)
            if isinstance(mc.duration, (int, float)):
                thuoc_tinh["media_duration"] = float(mc.duration)
            if isinstance(mc.current_time, (int, float)) and _moc(getattr(mc, "last_updated", None)):
                thuoc_tinh["media_position"] = float(mc.current_time)
                thuoc_tinh["media_position_updated_at"] = _moc(mc.last_updated)
            if getattr(mc, "title", None):
                thuoc_tinh["media_title"] = str(mc.title)
        ket_qua.append({"entity_id": ma_loa(loa), "state": TRANG_THAI_CAST.get(str(getattr(mc, "player_state", "")), "idle"),
                        "attributes": thuoc_tinh})
    return ket_qua


def goi(domain: str, service: str, data: dict[str, Any]) -> bool:
    """Như `ha_client.call_service` cho loa trong sổ; True = loa đã nhận lệnh."""
    ma = str((data or {}).get("entity_id") or "")
    loa = next((l for l in cac_loa() if ma_loa(l) == ma), None)
    if domain != "media_player" or loa is None:
        return False
    cast = _ket_noi_cua(loa).cho_noi(CHO_NOI_KHI_RA_LENH)
    if cast is None:
        return False
    mc = cast.media_controller
    try:
        if service == "play_media":
            mc.play_media(str(data["media_content_id"]), str(data.get("media_content_type") or "audio/mpeg"),
                          stream_type="BUFFERED")
        elif service == "media_play":
            mc.play()
        elif service == "media_pause":
            mc.pause()
        elif service == "media_play_pause":
            if str(getattr(mc.status, "player_state", "")) == "PLAYING":
                mc.pause()
            else:
                mc.play()
        elif service == "media_stop":
            mc.stop()
        elif service == "volume_set":
            cast.set_volume(float(data["volume_level"]))
        elif service == "media_seek":
            mc.seek(float(data["seek_position"]))
        else:
            return False
    except Exception as error:  # mất kết nối giữa chừng, loa từ chối lệnh
        logger.warning({"event": "loa_c2a_lenh_loi", "loa": loa.get("id"), "lenh": service, "loi": str(error)[:160]})
        return False
    return True


def _reset_for_tests(tao: Callable[[dict[str, Any]], Any] | None = None) -> None:
    global _tao_mac_dinh
    with _khoa:
        _ket_noi.clear()
    _tao_mac_dinh = tao or _tao_cast
