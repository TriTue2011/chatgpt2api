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
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse

from api.support import require_admin, resolve_image_base_url
from services.ingress_guard import BodyTooLarge, read_json_limited
from services.youtube_phat import dich_vu, phat_ha
from services.youtube_phat.thong_bao import THONG_BAO as _THONG_BAO
from services.youtube_phat.search import SearchUnavailableError
from services.youtube_phat.streaming import (
    InvalidStreamTokenError,
    StreamUnavailableError,
    danh_sach_hls,
    doc_muc_luc_mp4,
    verify_stream_token,
)
from utils.log import logger

TIEN_TO = "/yt"

_KHA_NANG = ["history", "play", "search", "session", "sessions", "status", "stop",
             "youtube_stream", "zing_stream"]

#: Cỡ mỗi khúc proxy xin của Google. Đo 21/09/2026 trên một bài 82 MB: xin không
#: giới hạn được 0,033 MB/giây, xin từng khúc 4 MB được 15 MB/giây — nhanh hơn
#: khoảng 450 lần. Khúc quá nhỏ thì tốn nhiều lượt mở kết nối, 4 MB là chỗ đã đo
#: thấy đầy tốc ngay từ khúc đầu (0,09 giây) mà vẫn vào tiếng sớm.
KHUC_LUONG = 4 * 1024 * 1024
#: Đủ cho mục lục sidx của một bài rất dài (mỗi khúc ~12 byte). Bài 3 giờ đo
#: 22/09/2026 chỉ chiếm khoảng 14 KB.
_DAU_MUC_LUC = 256 * 1024
_IOS = re.compile(r"iPhone|iPad|iPod")


def _la_ios(request: Request) -> bool:
    return _IOS.search(request.headers.get("user-agent") or "") is not None


def _ios_can_danh_sach(token: str, request: Request) -> bool:
    """iPhone nhận danh sách khúc, trừ khi đang xin đúng một khoảng byte của khúc.

    Loa và Android không đi đây: chúng phát tốt tệp liền. Zing/Facebook cũng không
    — chỉ tiếng YouTube mới là MP4 cắt mảnh làm iPhone chờ theo độ dài cả bài.
    """
    if request.query_params.get("khoi") == "1" or not _la_ios(request):
        return False
    try:
        source, _target = verify_stream_token(token, dich_vu.core().integration_token)
    except InvalidStreamTokenError:
        return False
    return source == "youtube"


def _tong_co_tep(up) -> int:
    """Cỡ THẬT của cả tệp, đọc từ «Content-Range: bytes a-b/TỔNG» của khúc đầu.

    Không dùng «Content-Length» được: với một khúc thì nó là cỡ của khúc ấy thôi.
    """
    tong = str(up.headers.get("Content-Range") or "").rsplit("/", 1)[-1].strip()
    if tong.isdigit():
        return int(tong)
    con = str(up.headers.get("Content-Length") or "").strip()
    return int(con) if con.isdigit() else 0


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
            "sources": ["youtube", "zing", "facebook"], "playback_sources": ["youtube", "zing", "facebook", "http"],
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
                auto_advance=payload.get("auto_advance") is not False,
                playlist_id=payload.get("playlist_id") or None)
        except ValueError as error:
            ma = str(error)
            if ma == "playlist_not_found":
                return _json(404, {"error": ma})
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

    async def _playlist(payload: dict) -> tuple[int, dict]:
        try:
            ket_qua = await asyncio.to_thread(dich_vu.core().playlist_action, payload)
        except (SearchUnavailableError, StreamUnavailableError):
            # Đọc playlist từ YouTube/Zing hỏng: link sai, playlist riêng tư hoặc nguồn lỗi.
            return 502, {"error": "playlist_unavailable"}
        except ValueError as error:
            return 400, {"error": str(error)}
        return 200, ket_qua

    # Playlist chung cả nhà: tích hợp HA (token) và tab YouTube (quản trị) cùng một kho.
    @router.get(f"{I}/playlists")
    async def playlists_integration(authorization: str | None = Header(default=None)):
        if (loi := _xac_thuc(authorization)) is not None:
            return loi
        ma, body = await _playlist({"action": "list"})
        return _json(ma, {"success": ma == 200, **body})

    @router.post(f"{I}/playlists")
    async def playlist_integration(request: Request, authorization: str | None = Header(default=None)):
        if (loi := _xac_thuc(authorization)) is not None:
            return loi
        try:
            payload = await _doc_json(request, 400_000)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return _json(400, {"error": "invalid_request"})
        ma, body = await _playlist(payload)
        return _json(ma, {"success": ma == 200, **body})

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
            # Cửa chặn RIÊNG của tầng API, độc lập với STREAM_SOURCES bên streaming và
            # với các nhánh trong dich_vu. Thiếu nguồn ở đây thì hai hàm giải luồng
            # chạy tốt bên dưới không bao giờ được gọi tới — đo 19/09/2026: gọi thẳng
            # resolve_facebook_audio/video trong container đều OK, mà thẻ vẫn báo
            # "không lấy được tiếng/hình".
            if source not in {"zing", "youtube", "youtube_video", "facebook", "facebook_video"}:
                raise ValueError("unsupported_stream_source")
            # youtube_video: chỉ hình, cho thẻ HA khi YouTube không cho nhúng.
            chieu_cao = [payload.get("max_height") or 720] if source in {"youtube_video", "facebook_video"} else []
            target, resolved = await asyncio.to_thread(c.prepare_stream, source, payload.get("target"), *chieu_cao)
            stream_url = c.create_stream_url(source, target, url_goc(request))
        except StreamUnavailableError:
            return _json(502, {"error": "stream_unavailable"})
        except ValueError as error:
            ma = str(error)
            if ma == "public_base_url_required":
                return _json(409, {"error": ma})
            if ma == "unverified_zing_target":
                return _json(403, {"error": ma})
            # «invalid_facebook_target» PHẢI có trong danh sách giữ nguyên: thiếu nó thì
            # mã lỗi bị nghiền thành «invalid_request» và người dùng lại mất nguyên nhân.
            if ma not in {"invalid_request", "invalid_youtube_target", "invalid_zing_target",
                          "invalid_facebook_target",
                          "unsupported_stream_source", "youtube_audio_requires_video"}:
                ma = "invalid_request"
            return _json(400, {"error": ma})
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _json(400, {"error": "invalid_request"})
        return _json(200, {"success": True, "source": source, "stream_url": stream_url,
                           "media_content_type": resolved.get("content_type", "audio/mpeg"),
                           "expires_in": 3600,
                           **(_luong_hinh(resolved) if source in {"youtube_video", "facebook_video"} else {})})

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

    def _luong_hinh(giai: dict) -> dict:
        """Thông tin luồng hình cho trình duyệt. `direct_url` là link googlevideo gắn IP
        mạng nhà: máy trong nhà (cùng IP ra Internet) tải thẳng, không qua c2a; tải thẳng
        hỏng nghĩa là đang ở ngoài nhà — khi đó hình phải đi qua link đã ký (tốn băng
        thông tải lên của nhà), trang hỏi người xem trước."""
        return {"height": giai.get("height"), "bitrate_kbps": giai.get("bitrate_kbps"), "direct_url": giai.get("url")}

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

    def _url_khuc(request: Request) -> str:
        """Địa chỉ trả một khoảng byte. Bỏ «.m3u8» nếu đang đứng ở danh sách."""
        goc = str(request.url).split("?", 1)[0]
        if goc.endswith(".m3u8"):
            goc = goc[: -len(".m3u8")]
        return goc + "?khoi=1"

    async def _danh_sach_khuc(token: str, request: Request):
        """Danh sách HLS của một bài YouTube. Hỏng mục lục thì 502, không trả
        tệp liền — trả tệp liền là đúng cái cách iPhone đang chờ lâu."""
        resolved, loi = await _mo_luong(token, request)
        if loi is not None:
            return loi

        def _doc_dau():
            headers = {**resolved["headers"], "Accept-Encoding": "identity",
                       "Range": f"bytes=0-{_DAU_MUC_LUC - 1}"}
            up = urlopen(UrlRequest(resolved["url"], headers=headers), timeout=20)
            try:
                return up.read(_DAU_MUC_LUC)
            finally:
                dong = getattr(up, "close", None)
                if dong:
                    dong()

        try:
            buf = await asyncio.to_thread(_doc_dau)
        except (OSError, HTTPError) as exc:
            logger.warning({"event": "youtube_phat_muc_luc_loi", "loi": str(exc)[:160]})
            return _json(502, {"error": "stream_unavailable"})
        muc = doc_muc_luc_mp4(buf)
        if muc is None:
            logger.warning({"event": "youtube_phat_muc_luc_loi", "loi": "khong_co_sidx"})
            return _json(502, {"error": "stream_unavailable"})
        khoi, khuc = muc
        try:
            body = danh_sach_hls(khoi, khuc, _url_khuc(request))
        except ValueError:
            return _json(502, {"error": "stream_unavailable"})
        return Response(body, media_type="application/vnd.apple.mpegurl", headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        })

    @router.get(f"{TIEN_TO}/api/stream/{{token}}")
    async def proxy_stream(token: str, request: Request):
        """Tiếp sóng luồng âm thanh cho loa — loa không gọi thẳng googlevideo.com
        (URL gắn IP máy giải, loa tải là 403).

        LẤY THEO TỪNG KHÚC CÓ GIỚI HẠN, đừng mở một cú không giới hạn. Đo trên máy
        chủ 21/09/2026, cùng một bài 82 MB, cùng lúc:

            không Range, hoặc «bytes=0-»   →  0,033 MB/giây
            từng khúc «bytes=a-b» 4 MB      →  15 MB/giây

        Nhanh hơn khoảng 450 lần. Google bóp mọi yêu cầu KHÔNG GIỚI HẠN xuống cỡ tốc
        độ nghe, và chỉ trả hết tốc khi được hỏi một khúc có đầu có cuối. Bài ngắn
        không lộ ra (cả tệp còn nhỏ hơn một khúc), nên hôm 21/09 tôi đo bằng một bài
        3,45 MB và tưởng chỉ cần thêm «Range» là xong — bài dài thì vẫn nhỏ giọt.

        Hậu quả đã thấy: loa Google Cast báo "Failed to cast media … Reachable from
        the cast device" (log HA 17:05:28) vì nó tải nhỏ giọt rồi bỏ cuộc, còn điện
        thoại thì nằm ở "đang tải mà không có dữ liệu".

        iPhone thì còn một lớp nữa. Hộp đen 22/09/2026: fetch lấy 2 byte trong khoảng
        0,1 giây mà phần tử âm thanh đứng «nap=0» tới 12 giây, bài càng dài càng lâu.
        Tệp là MP4 cắt mảnh, iPhone chờ theo độ dài cả tệp. Máy đó được chuyển sang
        danh sách khúc khoảng 10 giây để vào tiếng sau khúc đầu rồi tải tiếp. Loa
        và Android giữ đường tệp liền.
        """
        if token.endswith(".m3u8"):
            return await _danh_sach_khuc(token[: -len(".m3u8")], request)
        if _ios_can_danh_sach(token, request):
            return RedirectResponse(str(request.url).split("?", 1)[0] + ".m3u8", status_code=302)
        range_header = request.headers.get("range")
        if range_header and not re.fullmatch(r"bytes=\d*-\d*", range_header):
            return _json(400, {"error": "invalid_range"})
        # «bytes=-500» (xin 500 byte CUỐI) không tính được đầu khúc nếu chưa biết cỡ
        # tệp, mà máy nghe gần như không dùng. Giữ nguyên đường cũ cho nó.
        xin = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header or "bytes=0-")
        dau = int(xin.group(1)) if xin else 0
        cuoi_xin = int(xin.group(2)) if xin and xin.group(2) else None

        def _mo_khuc(resolved, tu, den):
            headers = {**resolved["headers"], "Accept-Encoding": "identity",
                       "Range": f"bytes={tu}-{den}" if den is not None else f"bytes={tu}-"}
            return urlopen(UrlRequest(resolved["url"], headers=headers), timeout=30)

        het_khuc_dau = None if not xin else dau + KHUC_LUONG - 1
        if cuoi_xin is not None:
            het_khuc_dau = min(het_khuc_dau, cuoi_xin) if het_khuc_dau is not None else cuoi_xin
        for lan in (1, 2):
            resolved, loi = await _mo_luong(token, request)
            if loi is not None:
                return loi
            try:
                up = await asyncio.to_thread(_mo_khuc, resolved, dau, het_khuc_dau)
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

        tong = _tong_co_tep(up)
        cuoi = cuoi_xin if cuoi_xin is not None else (tong - 1 if tong else None)
        out = {"Content-Type": up.headers.get("Content-Type", resolved.get("content_type", "audio/mpeg")),
               "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
               "Accept-Ranges": "bytes"}
        if cuoi is not None:
            out["Content-Length"] = str(cuoi - dau + 1)
        if range_header and tong:
            # Máy nghe hỏi theo khúc thì trả đúng khúc NÓ hỏi — không phải khúc proxy
            # này đang lấy của Google.
            ma = 206
            out["Content-Range"] = f"bytes {dau}-{cuoi}/{tong}"
        else:
            ma = 200

        def _noi_cac_khuc():
            """Đọc hết khúc đang mở rồi tự mở khúc kế — máy nghe thấy một luồng liền."""
            mo = up
            vi_tri = dau
            try:
                while True:
                    try:
                        while mieng := mo.read(64 * 1024):
                            vi_tri += len(mieng)
                            yield mieng
                    finally:
                        mo.close()
                    if cuoi is None or vi_tri > cuoi:
                        return
                    ke = min(vi_tri + KHUC_LUONG - 1, cuoi)
                    mo = _mo_khuc(resolved, vi_tri, ke)
            except (OSError, HTTPError):
                # Máy nghe bỏ đi (tua, đổi bài) hoặc link hết hạn giữa chừng.
                return

        return StreamingResponse(_noi_cac_khuc(), status_code=ma, headers=out)

    @router.head(f"{TIEN_TO}/api/stream/{{token}}")
    async def head_stream(token: str, request: Request):
        """Loa DLNA hỏi HEAD trước khi GET — trả kiểu, cỡ, ranges, không tải audio."""
        if not token.endswith(".m3u8") and _ios_can_danh_sach(token, request):
            return RedirectResponse(str(request.url).split("?", 1)[0] + ".m3u8", status_code=302)
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
                "cac_phien": phat_ha.cac_phien(),
                "canh_bao": "Không đọc được Home Assistant — đang dùng loa trong Sổ loa c2a." if phat_ha.loi_ha else ""}

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
            ma = str(error)
            # Facebook không có tìm theo chữ. Mã chung «invalid_search_query» dành cho
            # YouTube; trang này cần một câu nói đúng việc người dùng vừa làm.
            if source == "facebook" and ma == "invalid_search_query":
                ma = "invalid_facebook_query"
            return _loi(ma)
        except SearchUnavailableError as error:
            ma = str(error)
            if ma not in _THONG_BAO:
                ma = "search_unavailable"
            return _loi(ma)
        return {"ok": True, "items": items}

    @router.get("/api/youtube-phat/playlist")
    async def playlist_tab(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        ma, body = await _playlist({"action": "list"})
        return {"ok": True, **body} if ma == 200 else _loi(body["error"])

    @router.post("/api/youtube-phat/playlist")
    async def playlist_lenh_tab(request: Request, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            payload = await _doc_json(request, 400_000)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return _loi("invalid_request")
        ma, body = await _playlist(payload)
        return {"ok": True, **body} if ma == 200 else _loi(body["error"])

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
                join_ids=payload.get("join_ids") if isinstance(payload.get("join_ids"), list) else None,
                playlist_id=payload.get("playlist_id") or None)
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
            if source not in {"youtube", "zing", "youtube_video", "facebook", "facebook_video"}:
                raise ValueError("unsupported_source")
            c = dich_vu.core()
            # youtube_video: chỉ hình, khi YouTube không cho nhúng video trên trang.
            chieu_cao = [payload.get("max_height") or 720] if source in {"youtube_video", "facebook_video"} else []
            ma, giai = await asyncio.to_thread(c.prepare_stream, source, str(payload.get("target") or ""), *chieu_cao)
            url = c.create_stream_url(source, ma, f"{resolve_image_base_url(request)}{TIEN_TO}")
        except StreamUnavailableError:
            return _loi("stream_unavailable")
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            return _loi(str(error))
        c.prefetch(payload.get("ke"))
        return {"ok": True, "url": urlsplit(url).path, "content_type": giai.get("content_type") or "audio/mpeg",
                **(_luong_hinh(giai) if source in {"youtube_video", "facebook_video"} else {})}

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
