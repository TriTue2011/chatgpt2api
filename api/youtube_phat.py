"""Integration API v1 của TriTue YouTube Player — c2a đóng vai add-on.

Chủ máy 14/09/2026: "đang phụ thuộc addon, tích hợp trực tiếp trên dự án, và
ha có thể kết nối đến, có thể ra lệnh trên ha mở nhạc ở thiết bị trên ha".

Tích hợp HA của repo (custom_components/tritue_youtube_player) gọi
`{URL gốc}{/api/integration/...}` kèm `Authorization: Bearer <token>`; loa tải
`{URL gốc}/api/stream/<token ký>`. Nên ở đây trả ĐÚNG hợp đồng đó (đường dẫn,
JSON, mã lỗi) dưới tiền tố `/yt`, chuyển từ `youtube_player/app/server.py`
(add-on 0.6.2). Trong HA chỉ cần đổi URL tích hợp sang `http://<c2a>:3030/yt`.

Không có trang web player (chủ máy chọn chỉ phát ra loa/tivi). `/api/integration/
play` vẫn giữ: tích hợp HA gọi nó để lấy metadata và mở phiên trước khi phát.

Xác thực: token Integration API riêng (`DATA_DIR/youtube_phat/integration_token`),
KHÔNG dùng khoá quản trị c2a — lộ token này chỉ lộ quyền phát nhạc. Luồng cho
loa không cần Bearer, chỉ nhận token ký HMAC hạn 1 giờ, như add-on.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import re
from urllib.error import HTTPError
from urllib.request import Request as UrlRequest
from urllib.parse import urlsplit
from urllib.request import urlopen

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from api.support import require_admin, resolve_image_base_url
from services.ingress_guard import BodyTooLarge, read_json_limited
from services.youtube_phat import dich_vu, phat_ha
from services.youtube_phat.thong_bao import THONG_BAO as _THONG_BAO
from services.youtube_phat.search import SearchUnavailableError
from services.youtube_phat.streaming import (
    InvalidStreamTokenError,
    StreamUnavailableError,
    verify_stream_token,
)
from utils.log import logger

TIEN_TO = "/yt"

_KHA_NANG = ["history", "play", "search", "session", "sessions", "status", "stop",
             "youtube_stream", "zing_stream"]


def _json(status: int, payload: dict) -> JSONResponse:
    return JSONResponse(payload, status_code=status,
                        headers={"Cache-Control": "no-store"})


def _xac_thuc(authorization: str | None) -> JSONResponse | None:
    token = dich_vu.core().integration_token
    if not hmac.compare_digest(str(authorization or ""), f"Bearer {token}"):
        return _json(401, {"error": "invalid_auth"})
    return None


async def _doc_json(request: Request, toi_da: int) -> dict:
    try:
        payload = await read_json_limited(request, toi_da)
    except BodyTooLarge as error:
        raise ValueError("invalid_request") from error
    # Add-on từ chối body rỗng bằng `invalid_request`; `read_json_limited` trả {}.
    if not isinstance(payload, dict) or not payload:
        raise ValueError("invalid_request")
    return payload


def url_goc(request: Request) -> str:
    """URL gốc loa dùng để tải luồng: cấu hình nếu có, không thì theo chính
    địa chỉ HA đã gọi tới (HA gọi bằng IP LAN nên loa cũng tới được)."""
    return dich_vu.public_base_url_cau_hinh() or (
        f"{request.url.scheme}://{request.headers.get('host') or request.url.netloc}{TIEN_TO}")


def create_router() -> APIRouter:
    router = APIRouter()
    I = f"{TIEN_TO}/api/integration"

    @router.get(f"{I}/health")
    async def health(authorization: str | None = Header(default=None)):
        if (loi := _xac_thuc(authorization)) is not None:
            return loi
        return _json(200, {
            "success": True, "status": "ok", "api_version": dich_vu.API_VERSION,
            "app_version": dich_vu.APP_VERSION, "capabilities": _KHA_NANG,
            "sources": ["youtube", "zing"], "playback_sources": ["youtube", "zing", "http"],
        })

    @router.get(f"{I}/search")
    async def search(request: Request, authorization: str | None = Header(default=None)):
        if (loi := _xac_thuc(authorization)) is not None:
            return loi
        query = str(request.query_params.get("q", "")).strip()
        source = str(request.query_params.get("source", "youtube")).strip().lower()
        try:
            limit = int(request.query_params.get("limit", "20"))
            # Độ dài chính xác do search.py kiểm (chữ 120 ký tự, link YouTube 2048).
            if not 1 <= len(query) <= 2048 or not 1 <= limit <= 30:
                raise ValueError
            items = await asyncio.to_thread(dich_vu.core().search, source, query, limit)
        except ValueError as error:
            ma = "invalid_search_source" if str(error) == "invalid_search_source" else "invalid_search_query"
            return _json(400, {"error": ma})
        except SearchUnavailableError:
            return _json(502, {"error": "search_unavailable"})
        return _json(200, {"success": True, "source": source, "items": items, "total": len(items)})

    @router.get(f"{I}/status")
    async def status(authorization: str | None = Header(default=None)):
        if (loi := _xac_thuc(authorization)) is not None:
            return loi
        c = dich_vu.core()
        session, sessions = c.get_sessions()
        return _json(200, {
            "success": True, "api_version": dich_vu.API_VERSION, "app_version": dich_vu.APP_VERSION,
            "state": session["state"], "item": session["item"], "session": session,
            "sessions": sessions, "history_count": len(c.load_history()),
        })

    @router.get(f"{I}/history")
    async def history(authorization: str | None = Header(default=None)):
        if (loi := _xac_thuc(authorization)) is not None:
            return loi
        items = dich_vu.core().load_history()
        return _json(200, {"success": True, "items": items, "total": len(items)})

    @router.post(f"{I}/stop")
    async def stop(request: Request, authorization: str | None = Header(default=None)):
        if (loi := _xac_thuc(authorization)) is not None:
            return loi
        try:
            expected_revision = None
            session_id = None
            if int(request.headers.get("content-length") or "0"):
                payload = await _doc_json(request, 256)
                expected_revision = payload.get("expected_revision")
                session_id = payload.get("session_id") or None
                if expected_revision is not None and (
                        isinstance(expected_revision, bool) or not isinstance(expected_revision, int)
                        or expected_revision < 0):
                    raise ValueError("invalid_session_revision")
                if expected_revision is None and session_id is None:
                    raise ValueError("invalid_session_revision")
            result = dich_vu.core().stop(expected_revision, session_id)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return _json(400, {"error": "invalid_session_revision"})
        session = result["session"]
        return _json(200, {"success": True, "stopped": result["stopped"],
                           "state": session["state"], "session": session})

    @router.post(f"{I}/session")
    async def session(request: Request, authorization: str | None = Header(default=None)):
        if (loi := _xac_thuc(authorization)) is not None:
            return loi
        try:
            payload = await _doc_json(request, 8192)
            source = str(payload.get("source") or "").lower()
            ket_qua = await asyncio.to_thread(
                dich_vu.core().record_session, source, payload.get("target"),
                output_entity_ids=payload.get("output_entity_ids"),
                media_content_type=payload.get("media_content_type") or "",
                volume_level=payload.get("volume_level"),
                session_id=payload.get("session_id") or None,
                controller=payload.get("controller") or "",
                auto_advance=payload.get("auto_advance") is not False)
        except ValueError as error:
            ma = str(error)
            if ma == "unverified_zing_target":
                return _json(403, {"error": ma})
            if ma not in {"invalid_http_audio_target", "invalid_output_entity_ids", "invalid_session_id",
                          "invalid_volume_level", "invalid_youtube_target",
                          "unsupported_session_source"}:
                ma = "invalid_request"
            return _json(400, {"error": ma})
        except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
            return _json(400, {"error": "invalid_request"})
        return _json(200, {"success": True, "session": ket_qua})

    @router.post(f"{I}/session/outputs")
    async def session_outputs(request: Request, authorization: str | None = Header(default=None)):
        if (loi := _xac_thuc(authorization)) is not None:
            return loi
        try:
            payload = await _doc_json(request, 4096)
            ket_qua = dich_vu.core().set_session_outputs(payload.get("session_id"), payload.get("output_entity_ids"))
        except ValueError as error:
            ma = str(error) if str(error) in {"invalid_session_id", "invalid_output_entity_ids"} else "invalid_request"
            return _json(400, {"error": ma})
        return _json(200, {"success": True, **ket_qua})

    @router.post(f"{I}/stream")
    async def stream(request: Request, authorization: str | None = Header(default=None)):
        if (loi := _xac_thuc(authorization)) is not None:
            return loi
        c = dich_vu.core()
        try:
            payload = await _doc_json(request, 4096)
            source = payload.get("source")
            if source not in {"zing", "youtube"}:
                raise ValueError("unsupported_stream_source")
            target, resolved = await asyncio.to_thread(c.prepare_stream, source, payload.get("target"))
            stream_url = c.create_stream_url(source, target, url_goc(request))
        except StreamUnavailableError:
            return _json(502, {"error": "stream_unavailable"})
        except ValueError as error:
            ma = str(error)
            if ma == "public_base_url_required":
                return _json(409, {"error": ma})
            if ma == "unverified_zing_target":
                return _json(403, {"error": ma})
            if ma not in {"invalid_request", "invalid_youtube_target", "invalid_zing_target",
                          "unsupported_stream_source", "youtube_audio_requires_video"}:
                ma = "invalid_request"
            return _json(400, {"error": ma})
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _json(400, {"error": "invalid_request"})
        return _json(200, {"success": True, "source": source, "stream_url": stream_url,
                           "media_content_type": resolved.get("content_type", "audio/mpeg"),
                           "expires_in": 3600})

    @router.post(f"{I}/play")
    async def play(request: Request, authorization: str | None = Header(default=None)):
        if (loi := _xac_thuc(authorization)) is not None:
            return loi
        try:
            payload = await _doc_json(request, 4096)
            raw_target = payload.get("target")
            target = dich_vu.normalize_target(raw_target)
        except ValueError as error:
            ma = str(error)
            return _json(400, {"error": ma if ma in {"invalid_request", "invalid_youtube_target"}
                               else "invalid_request"})
        except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
            return _json(400, {"error": "invalid_request"})
        ket_qua = await asyncio.to_thread(dich_vu.core().play, target, raw_target=raw_target)
        return _json(200, {"success": True, "item": ket_qua["item"],
                           "session_revision": ket_qua["revision"]})

    async def _mo_luong(token: str, request: Request):
        """(nguồn đã giải, phản hồi thượng nguồn) hoặc JSONResponse lỗi."""
        if not token or len(token) > 4096:
            return None, _json(403, {"error": "invalid_stream_token"})
        c = dich_vu.core()
        try:
            source, target = verify_stream_token(token, c.integration_token)
            resolved = await asyncio.to_thread(c.resolve_stream, source, target)
        except InvalidStreamTokenError:
            return None, _json(403, {"error": "invalid_stream_token"})
        except (StreamUnavailableError, ValueError, OSError):
            return None, _json(502, {"error": "stream_unavailable"})
        return resolved, None

    @router.get(f"{TIEN_TO}/api/stream/{{token}}")
    async def proxy_stream(token: str, request: Request):
        """Tiếp sóng luồng âm thanh cho loa — loa không gọi thẳng googlevideo.com
        (URL gắn IP máy giải, loa tải là 403)."""
        range_header = request.headers.get("range")
        if range_header and not re.fullmatch(r"bytes=\d*-\d*", range_header):
            return _json(400, {"error": "invalid_range"})
        for lan in (1, 2):
            resolved, loi = await _mo_luong(token, request)
            if loi is not None:
                return loi
            headers = {**resolved["headers"], "Accept-Encoding": "identity"}
            if range_header:
                headers["Range"] = range_header
            try:
                up = await asyncio.to_thread(urlopen, UrlRequest(resolved["url"], headers=headers), timeout=30)
                break
            except HTTPError as exc:
                # Link được dùng lại hàng giờ (stream_cache_seconds): YouTube từ chối
                # link cũ thì bỏ bản đệm, giải lại đúng một lần.
                if lan == 1 and exc.code in {403, 404, 410}:
                    source, target = verify_stream_token(token, dich_vu.core().integration_token)
                    dich_vu.core().forget_stream(source, target)
                    continue
                logger.warning({"event": "youtube_phat_luong_loi", "loi": str(exc)[:160]})
                return _json(502, {"error": "stream_unavailable"})
            except OSError as exc:
                logger.warning({"event": "youtube_phat_luong_loi", "loi": str(exc)[:160]})
                return _json(502, {"error": "stream_unavailable"})
        out = {"Content-Type": up.headers.get("Content-Type", resolved.get("content_type", "audio/mpeg")),
               "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
        for ten in ("Content-Length", "Content-Range", "Accept-Ranges"):
            if gia_tri := up.headers.get(ten):
                out[ten] = gia_tri

        def _khuc():
            try:
                while khuc := up.read(64 * 1024):
                    yield khuc
            except OSError:
                return
            finally:
                up.close()

        return StreamingResponse(_khuc(), status_code=up.getcode() or 200, headers=out)

    @router.head(f"{TIEN_TO}/api/stream/{{token}}")
    async def head_stream(token: str, request: Request):
        """Loa DLNA hỏi HEAD trước khi GET — trả kiểu, cỡ, ranges, không tải audio."""
        resolved, loi = await _mo_luong(token, request)
        if loi is not None:
            return Response(status_code=loi.status_code, headers={"Content-Length": "0"})
        content_type = resolved.get("content_type", "audio/mpeg")
        total = None

        def _do() -> tuple[str, int | None]:
            ct, tong = content_type, None
            try:
                h = {**resolved["headers"], "Accept-Encoding": "identity", "Range": "bytes=0-0"}
                with urlopen(UrlRequest(resolved["url"], headers=h), timeout=15) as up:
                    ct = up.headers.get("Content-Type", ct)
                    cr = up.headers.get("Content-Range", "")
                    if "/" in cr and cr.rsplit("/", 1)[-1].strip().isdigit():
                        tong = int(cr.rsplit("/", 1)[-1].strip())
            except (OSError, ValueError):
                pass
            return ct, tong

        content_type, total = await asyncio.to_thread(_do)
        out = {"Content-Type": content_type, "Accept-Ranges": "bytes",
               "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
               "Content-Length": str(total) if total is not None else "0"}
        return Response(status_code=200, headers=out)

    # ── Tab YouTube của web c2a (phiên quản trị, không dùng token tích hợp) ──

    def _ket_noi(request: Request) -> dict:
        return {"ok": True, "url": url_web(request), "token": dich_vu.core().integration_token,
                "url_lan": dich_vu.doc_url_lan()}

    @router.get("/api/youtube-phat/ket-noi")
    async def ket_noi(request: Request, authorization: str | None = Header(default=None)):
        """URL và token để dán vào tích hợp TriTue YouTube Player của HA."""
        require_admin(authorization)
        return _ket_noi(request)

    @router.post("/api/youtube-phat/ket-noi")
    async def luu_ket_noi(request: Request, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            payload = await read_json_limited(request, 1024)
            dich_vu.luu_url_lan(payload.get("url_lan") if isinstance(payload, dict) else None)
        except (ValueError, BodyTooLarge):
            return _loi("url_lan_khong_hop_le")
        return _ket_noi(request)

    @router.get("/api/youtube-phat/thiet-bi")
    async def thiet_bi(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            items = await asyncio.to_thread(phat_ha.danh_sach)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning({"event": "youtube_phat_thiet_bi_loi", "loi": str(exc)[:160]})
            return _loi("ha_khong_doc_duoc")
        return {"ok": True, "items": items, "phien": dich_vu.core().get_session(),
                "cac_phien": phat_ha.cac_phien()}

    @router.post("/api/youtube-phat/an")
    async def an_thiet_bi(request: Request, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            payload = await _doc_json(request, 4096)
            so = phat_ha.dat_an(payload.get("entity_ids"), bool(payload.get("an")))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return _loi("invalid_target_entity")
        return {"ok": True, "an": so}

    @router.get("/api/youtube-phat/tim")
    async def tim(request: Request, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        source = str(request.query_params.get("source", "youtube")).strip().lower()
        query = str(request.query_params.get("q", "")).strip()
        try:
            items = await asyncio.to_thread(dich_vu.core().search, source, query, 20)
        except ValueError as error:
            return _loi(str(error))
        except SearchUnavailableError:
            return _loi("search_unavailable")
        return {"ok": True, "items": items}

    @router.post("/api/youtube-phat/phat")
    async def phat(request: Request, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            payload = await _doc_json(request, 8192)
            ket_qua = await asyncio.to_thread(
                phat_ha.phat, str(payload.get("source") or "").lower(), str(payload.get("target") or ""),
                payload.get("entity_ids"), url_web(request),
                media_content_type=payload.get("media_content_type") or None,
                session_id=payload.get("session_id") or None,
                join_ids=payload.get("join_ids") if isinstance(payload.get("join_ids"), list) else None)
        except StreamUnavailableError:
            return _loi("stream_unavailable")
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            return _loi(str(error))
        except (OSError, RuntimeError) as exc:
            logger.warning({"event": "youtube_phat_phat_loi", "loi": str(exc)[:160]})
            return _loi("ha_khong_doc_duoc")
        return {"ok": True, **ket_qua}

    @router.post("/api/youtube-phat/nghe")
    async def nghe(request: Request, authorization: str | None = Header(default=None)):
        """Chế độ Chỉ nghe: phát bằng thẻ <audio> ngay trên trình duyệt đang mở.

        Trả đường luồng CÙNG NGUỒN với trang (CSP media-src 'self'), đã ký như
        luồng cho loa. Trình duyệt điện thoại giữ tiếng <audio> khi tắt màn hình,
        khung video YouTube thì không. `ke` = bài kế trong hàng đợi trên trang,
        được giải sẵn để bấm bài kế không phải chờ."""
        require_admin(authorization)
        try:
            payload = await _doc_json(request, 8192)
            source = str(payload.get("source") or "").lower()
            if source not in {"youtube", "zing"}:
                raise ValueError("unsupported_source")
            c = dich_vu.core()
            ma, giai = await asyncio.to_thread(c.prepare_stream, source, str(payload.get("target") or ""))
            url = c.create_stream_url(source, ma, f"{resolve_image_base_url(request)}{TIEN_TO}")
        except StreamUnavailableError:
            return _loi("stream_unavailable")
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            return _loi(str(error))
        c.prefetch(payload.get("ke"))
        return {"ok": True, "url": urlsplit(url).path, "content_type": giai.get("content_type") or "audio/mpeg"}

    async def _phien_lenh(request: Request, lam) -> dict:
        try:
            payload = await _doc_json(request, 4096)
            ket_qua = await asyncio.to_thread(lam, payload)
        except StreamUnavailableError:
            return _loi("stream_unavailable")
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            return _loi(str(error))
        except (OSError, RuntimeError) as exc:
            logger.warning({"event": "youtube_phat_phien_loi", "loi": str(exc)[:160]})
            return _loi("ha_khong_doc_duoc")
        return {"ok": True, "ket_qua": ket_qua, "cac_phien": phat_ha.cac_phien()}

    @router.post("/api/youtube-phat/chuyen-bai")
    async def chuyen_bai(request: Request, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        base = url_web(request)
        return await _phien_lenh(request, lambda p: phat_ha.chuyen_bai(p.get("session_id"), p.get("buoc"), base))

    @router.post("/api/youtube-phat/dung-phien")
    async def dung_phien(request: Request, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await _phien_lenh(request, lambda p: phat_ha.dung_phien(p.get("session_id")))

    @router.post("/api/youtube-phat/bo-loa")
    async def bo_loa(request: Request, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return await _phien_lenh(request, lambda p: phat_ha.bo_loa(p.get("entity_ids")))

    @router.post("/api/youtube-phat/dieu-khien")
    async def dieu_khien(request: Request, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            payload = await _doc_json(request, 4096)
            da_gui = await asyncio.to_thread(
                phat_ha.dieu_khien, str(payload.get("lenh") or ""), payload.get("entity_ids"),
                payload.get("am_luong"), vi_tri=payload.get("vi_tri"))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            return _loi(str(error))
        if not da_gui:
            return _loi("ha_tu_choi")
        return {"ok": True, "da_gui": da_gui}

    return router




def _loi(ma: str) -> dict:
    return {"ok": False, "ma": ma, "error": _THONG_BAO.get(ma, _THONG_BAO["invalid_request"])}


def url_web(request: Request) -> str:
    """URL gốc của tab: dán vào tích hợp HA, và loa dùng để tải luồng khi phát từ
    tab. Địa chỉ LAN đã đặt thắng; không thì theo địa chỉ trình duyệt đang mở
    (qua tunnel là tên miền — vẫn tới được, nhưng nên đặt địa chỉ LAN)."""
    return dich_vu.public_base_url_cau_hinh() or f"{resolve_image_base_url(request)}{TIEN_TO}"
