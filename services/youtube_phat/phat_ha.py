"""Phát YouTube / Zing / HTTP ra loa và tivi của Home Assistant — cho tab YouTube.

Chủ máy 14/09/2026: "Xây dựng 1 tab youtube riêng hiển thị token và có chức năng
như card nhưng thiết kế lại đẹp hơn".

Chuyển từ tích hợp HA của repo TriTue2011/youtube (`playback.py`, `actions.py`,
bản 0.8.5): cùng bảng khả năng theo nền tảng; tivi Cast, Android TV, LG webOS mở
ứng dụng YouTube gốc (có hình), loa còn lại nhận luồng âm thanh `/yt/api/stream`
như Zing. Khác thẻ: chạy trong c2a, gọi HA qua `ha_client.call_service`.

Danh sách thiết bị đọc THÔ (`ha_client.doc_media_player_tho`), không qua sổ
«Bỏ khỏi c2a» — sổ đó để bot và tầng học không thấy thiết bị, còn 9/10 loa của
nhà nằm trong đó. Tab có sổ ẩn riêng (`thiet_bi_an.json`) để bớt thiết bị không
dùng và khôi phục khi cần.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from services import ha_client

from . import dich_vu

MEDIA_PLAYER = re.compile(r"^media_player\.[a-z0-9_]+$")
TOI_DA_THIET_BI = 16

# Bit `supported_features` của media_player trong HA.
PAUSE, SEEK, VOLUME_SET, PLAY_MEDIA, STOP, PLAY = 1, 2, 4, 512, 4096, 16384

# Media player ảo của chính tích hợp TriTue — không phải loa thật.
NEN_TANG_AO = {"tritue_youtube_player"}

YOUTUBE_GOC = {"google_cast_video", "android_tv", "lg_webos"}
WEBOS_YOUTUBE = "youtube.leanback.v4"
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
AUDIO_THEO_DUOI = {
    ".aac": "audio/aac", ".flac": "audio/flac", ".m3u8": "application/vnd.apple.mpegurl",
    ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/ogg",
    ".wav": "audio/wav",
}
AUDIO_CHO_PHEP = {*AUDIO_THEO_DUOI.values(), "application/x-mpegurl"}

# "dung" dừng cả phiên (xoá bài đang phát); "dung_rieng" chỉ tắt một loa vừa bỏ
# chọn, các loa khác phát tiếp.
LENH = {"phat_tam_dung": "media_play_pause", "dung": "media_stop", "dung_rieng": "media_stop",
        "am_luong": "volume_set", "tua": "media_seek"}

_BO_DEM_GIAY = 3.0
_bo_dem: tuple[float, list[dict[str, Any]]] = (0.0, [])
_khoa = threading.Lock()


def kha_nang(nen_tang: str | None, device_class: str | None, features: int | None) -> dict[str, Any]:
    """Nguồn nào gửi được tới một media_player — `build_target_capabilities` của repo."""
    nen_tang = str(nen_tang or "").lower()
    device_class = str(device_class or "").lower()
    phat_duoc = features is None or bool(int(features) & PLAY_MEDIA)
    if nen_tang == "cast":
        transport = {"speaker": "google_cast_audio", "tv": "google_cast_video"}.get(
            device_class, "google_cast_unknown")
    elif nen_tang in {"androidtv", "androidtv_remote"}:
        transport = "android_tv"
    elif nen_tang == "webostv":
        transport = "lg_webos"
    elif nen_tang == "dlna_dmr":
        transport = "dlna"
    elif phat_duoc:
        transport = "generic_audio"
    else:
        transport = "unsupported"
    return {
        "transport": transport,
        "phat_duoc": phat_duoc,
        "youtube": "goc" if transport in YOUTUBE_GOC else "am_thanh",
    }


def lenh_mo_youtube(item: dict[str, Any], nen_tang: str | None,
                    device_class: str | None) -> tuple[str, str, dict[str, Any]]:
    """(domain, service, data) mở ứng dụng YouTube gốc — `build_target_call` của repo."""
    video_id = str(item.get("id") or "")
    la_video = item.get("kind") == "video" and video_id
    if nen_tang == "webostv":
        if not la_video:
            raise ValueError("webos_playlist_requires_video")
        return "webostv", "command", {
            "command": "system.launcher/launch",
            "payload": {"id": WEBOS_YOUTUBE, "contentId": video_id},
        }
    if nen_tang == "cast" and device_class != "speaker":
        if not la_video:
            raise ValueError("cast_playlist_requires_video")
        payload = {"app_name": "youtube", "media_id": video_id}
        if playlist_id := str(item.get("playlist_id") or ""):
            payload["playlist_id"] = playlist_id
        return "media_player", "play_media", {
            "media_content_type": "cast",
            "media_content_id": json.dumps(payload, separators=(",", ":")),
        }
    if nen_tang in {"androidtv", "androidtv_remote"}:
        if item.get("kind") == "video":
            url = f"https://www.youtube.com/watch?v={video_id}"
            if playlist_id := str(item.get("playlist_id") or ""):
                url = f"{url}&list={playlist_id}"
        else:
            url = f"https://www.youtube.com/playlist?list={video_id}"
        return "media_player", "play_media", {"media_content_type": "url", "media_content_id": url}
    raise ValueError("youtube_transport_unsupported")


def yeu_cau_http(url: str, loai: str | None = None) -> dict[str, str]:
    """Dữ liệu `play_media` cho URL âm thanh trực tiếp — `build_direct_audio_request`."""
    url = str(url or "")
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (len(url) > 2048 or parsed.scheme not in {"http", "https"} or not host
            or parsed.username is not None or parsed.password is not None
            or host in YOUTUBE_HOSTS or host.endswith(".youtube.com")):
        raise ValueError("invalid_http_audio_target")
    duoi = next((t for d, t in AUDIO_THEO_DUOI.items() if parsed.path.lower().endswith(d)), "audio/mpeg")
    loai = str(loai or duoi)
    if loai not in AUDIO_CHO_PHEP:
        raise ValueError("invalid_http_audio_target")
    return {"media_content_id": url, "media_content_type": loai}


# ── Sổ ẩn thiết bị ───────────────────────────────────────────────────────────

def _duong_so_an() -> Path:
    return dich_vu.core().data_dir / "thiet_bi_an.json"


def doc_an() -> list[str]:
    try:
        value = json.loads(_duong_so_an().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [str(x) for x in value if MEDIA_PLAYER.fullmatch(str(x))] if isinstance(value, list) else []


def dat_an(entity_ids: Any, an: bool) -> list[str]:
    """Ẩn (an=True) hoặc khôi phục các thiết bị; trả sổ ẩn mới."""
    if not isinstance(entity_ids, list) or not entity_ids or not all(
            MEDIA_PLAYER.fullmatch(str(x)) for x in entity_ids):
        raise ValueError("invalid_target_entity")
    with _khoa:
        so = doc_an()
        if an:
            so += [str(x) for x in entity_ids if str(x) not in so]
        else:
            bo = {str(x) for x in entity_ids}
            so = [x for x in so if x not in bo]
        path = _duong_so_an()
        path.parent.mkdir(parents=True, exist_ok=True)
        tam = path.with_suffix(".json.tmp")
        tam.write_text(json.dumps(so, ensure_ascii=False, indent=2), encoding="utf-8")
        tam.replace(path)
    return so


# ── Danh sách thiết bị ───────────────────────────────────────────────────────

def _trang_thai_tho(dung_bo_dem: bool = True) -> list[dict[str, Any]]:
    """`/api/states` nặng ~580 KB; trang hỏi lại vài giây một lần nên đệm ngắn."""
    global _bo_dem
    now = time.monotonic()
    if dung_bo_dem and _bo_dem[0] and now - _bo_dem[0] < _BO_DEM_GIAY:
        return _bo_dem[1]
    data = ha_client.doc_media_player_tho()
    _bo_dem = (now, data)
    return data


def _xoa_bo_dem() -> None:
    global _bo_dem
    _bo_dem = (0.0, [])


def vi_tri_phat(trang_thai: str, a: dict[str, Any], bay_gio: datetime | None = None) -> float | None:
    """Giây đang phát của loa, tính tới lúc trả lời: HA chỉ cập nhật
    `media_position` khi loa báo, kèm mốc `media_position_updated_at`. Tab dùng
    để cho video trên trang chạy theo loa."""
    vi_tri = a.get("media_position")
    if isinstance(vi_tri, bool) or not isinstance(vi_tri, (int, float)):
        return None
    if trang_thai != "playing":
        return float(vi_tri)
    try:
        moc = datetime.fromisoformat(str(a.get("media_position_updated_at")))
    except ValueError:
        return float(vi_tri)
    if moc.tzinfo is None:
        moc = moc.replace(tzinfo=timezone.utc)
    troi = ((bay_gio or datetime.now(timezone.utc)) - moc).total_seconds()
    return float(vi_tri) + max(0.0, troi)


def danh_sach(dung_bo_dem: bool = True) -> list[dict[str, Any]]:
    nen_tang = ha_client.get_ha_area_index().get("entity_platform") or {}
    an = set(doc_an())
    ket_qua = []
    for s in _trang_thai_tho(dung_bo_dem):
        eid = str(s.get("entity_id") or "")
        if not MEDIA_PLAYER.fullmatch(eid) or nen_tang.get(eid) in NEN_TANG_AO:
            continue
        a = s.get("attributes") or {}
        try:
            features = int(a.get("supported_features") or 0)
        except (TypeError, ValueError):
            features = 0
        am_luong = a.get("volume_level")
        ket_qua.append({
            "entity_id": eid,
            "ten": str(a.get("friendly_name") or eid),
            "trang_thai": str(s.get("state") or "unknown"),
            "loai": "tivi" if a.get("device_class") == "tv" else "loa",
            "device_class": str(a.get("device_class") or ""),
            "nen_tang": nen_tang.get(eid) or "",
            "am_luong": float(am_luong) if isinstance(am_luong, (int, float)) else None,
            "chinh_am_luong": bool(features & VOLUME_SET),
            "tam_dung": bool(features & (PAUSE | PLAY)),
            "dung": bool(features & STOP),
            "tua": bool(features & SEEK),
            "vi_tri": vi_tri_phat(str(s.get("state") or ""), a),
            "tieu_de": str(a.get("media_title") or ""),
            "nghe_si": str(a.get("media_artist") or a.get("media_channel") or ""),
            "an": eid in an,
            **kha_nang(nen_tang.get(eid), a.get("device_class"), features),
        })
    ket_qua.sort(key=lambda d: (d["an"], d["ten"].lower()))
    return ket_qua


# ── Phát và điều khiển ───────────────────────────────────────────────────────

def _chon(entity_ids: Any) -> list[str]:
    if not isinstance(entity_ids, list):
        raise ValueError("invalid_target_entities")
    chon: list[str] = []
    for x in entity_ids:
        if not MEDIA_PLAYER.fullmatch(str(x)):
            raise ValueError("invalid_target_entity")
        if str(x) not in chon:
            chon.append(str(x))
    if not 1 <= len(chon) <= TOI_DA_THIET_BI:
        raise ValueError("invalid_target_entities")
    return chon


def phat(source: str, target: str, entity_ids: Any, base_url: str, *,
         media_content_type: str | None = None,
         goi: Callable[[str, str, dict], bool] | None = None) -> dict[str, Any]:
    """Gửi một bài tới các loa/tivi đã chọn. Trả {da_gui, bo_qua, phien}.

    Thiết bị không phát được hoặc HA từ chối thì vào `bo_qua` kèm lý do, không
    làm hỏng cả lượt; không gửi được tới thiết bị nào thì ném ValueError."""
    goi = goi or ha_client.call_service
    if source not in {"youtube", "zing", "http"}:
        raise ValueError("unsupported_source")
    chon = _chon(entity_ids)
    theo_ma = {d["entity_id"]: d for d in danh_sach(dung_bo_dem=False)}
    bo_qua: list[dict[str, str]] = []
    thiet_bi = []
    for eid in chon:
        d = theo_ma.get(eid)
        if d is None:
            bo_qua.append({"entity_id": eid, "ly_do": "khong_con_trong_ha"})
        elif d["trang_thai"] == "unavailable":
            bo_qua.append({"entity_id": eid, "ly_do": "khong_truc_tuyen"})
        elif not d["phat_duoc"]:
            bo_qua.append({"entity_id": eid, "ly_do": "khong_nhan_play_media"})
        else:
            thiet_bi.append(d)
    if not thiet_bi:
        raise ValueError("khong_co_thiet_bi_phat_duoc")

    core = dich_vu.core()
    da_gui: list[str] = []
    loi_dau: str | None = None

    def gui(d: dict[str, Any], domain: str, service: str, data: dict[str, Any]) -> None:
        if goi(domain, service, {**data, "entity_id": d["entity_id"]}):
            da_gui.append(d["entity_id"])
        else:
            bo_qua.append({"entity_id": d["entity_id"], "ly_do": "ha_tu_choi"})

    def luong(nguon: str, ma: str) -> dict[str, str]:
        ma_da_kiem, giai = core.prepare_stream(nguon, ma)
        return {"media_content_id": core.create_stream_url(nguon, ma_da_kiem, base_url),
                "media_content_type": str(giai.get("content_type") or "audio/mpeg")}

    if source == "http":
        yc = yeu_cau_http(target, media_content_type)
        loai = yc["media_content_type"]
        for d in thiet_bi:
            gui(d, "media_player", "play_media", yc)
    elif source == "zing":
        yc = luong("zing", target)
        loai = yc["media_content_type"]
        for d in thiet_bi:
            gui(d, "media_player", "play_media", yc)
    else:
        item = dich_vu.normalize_target(target)
        loai = "video"
        am_thanh = []
        for d in thiet_bi:
            if d["youtube"] != "goc":
                am_thanh.append(d)
                continue
            try:
                domain, service, data = lenh_mo_youtube(item, d["nen_tang"], d["device_class"])
            except ValueError as error:
                loi_dau = loi_dau or str(error)
                bo_qua.append({"entity_id": d["entity_id"], "ly_do": str(error)})
                continue
            gui(d, domain, service, data)
        if am_thanh:
            if item.get("kind") != "video":
                for d in am_thanh:
                    bo_qua.append({"entity_id": d["entity_id"], "ly_do": "youtube_audio_requires_video"})
                loi_dau = loi_dau or "youtube_audio_requires_video"
            else:
                yc = luong("youtube", item["id"])
                loai = yc["media_content_type"]
                for d in am_thanh:
                    gui(d, "media_player", "play_media", yc)

    if not da_gui:
        raise ValueError(loi_dau or "ha_tu_choi")
    _xoa_bo_dem()
    phien = core.record_session(source, target, output_entity_ids=da_gui, media_content_type=loai)
    return {"da_gui": da_gui, "bo_qua": bo_qua, "phien": phien}


def dieu_khien(lenh: str, entity_ids: Any, am_luong: Any = None, *, vi_tri: Any = None,
               goi: Callable[[str, str, dict], bool] | None = None) -> list[str]:
    """Phát/tạm dừng, dừng, đặt âm lượng, tua; trả các thiết bị HA đã nhận lệnh."""
    goi = goi or ha_client.call_service
    service = LENH.get(lenh)
    if service is None:
        raise ValueError("lenh_khong_ho_tro")
    chon = _chon(entity_ids)
    data: dict[str, Any] = {}
    if lenh == "am_luong":
        if isinstance(am_luong, bool) or not isinstance(am_luong, (int, float)) or not 0 <= am_luong <= 1:
            raise ValueError("invalid_volume_level")
        data["volume_level"] = float(am_luong)
    if lenh == "tua":
        if isinstance(vi_tri, bool) or not isinstance(vi_tri, (int, float)) or not 0 <= vi_tri <= 86400:
            raise ValueError("invalid_seek_position")
        data["seek_position"] = float(vi_tri)
    da_gui = [eid for eid in chon if goi("media_player", service, {**data, "entity_id": eid})]
    if lenh == "dung":
        dich_vu.core().stop()
    _xoa_bo_dem()
    return da_gui
