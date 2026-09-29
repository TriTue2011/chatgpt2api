"""API cho Camera nhà — tab Cài đặt → Home Assistant.

Sổ camera nằm trong ``config`` (khoá ``cameras``), nên web lưu nó qua đúng đường
lưu cấu hình chung như mọi card khác — ở đây KHÔNG có endpoint CRUD nào cho nó.
Ai được xem camera thì hỏi bộ lọc chức năng của từng kênh (ô tích «📷 Camera
nhà»), không phải một danh sách riêng của camera.

Hai việc web không tự làm được:

``POST /api/camera/test``        chụp thử một camera, trả ảnh xem trước
``POST /api/camera/noi``         đọc một câu ra loa camera (Dahua/Imou, cổng 37777)
``GET  /api/camera/tro_ly``      trợ lý giọng nói qua camera: từ gọi, trợ lý khác trong HA

Bộ đàm (mic điện thoại qua thẻ WebRTC Camera của HA → loa camera):

``GET  /api/camera/bo_dam/{ten}/go2rtc``  dòng ``exec:`` để dán vào go2rtc.yaml
``POST /api/camera/bo_dam/{ten}``         go2rtc đẩy luồng A-law 8 kHz tới đây

Xem trực tiếp trong web c2a (khung bộ đàm):

``POST /api/camera/xem/{ten}/ve``         vé dùng một lần cho thẻ ``<img>`` (không gửi được header)
``GET  /api/camera/xem/{ten}?ve=``        MJPEG ~8 khung/giây, rộng 640 — luồng phụ nếu có khai

Bộ đàm ngay trong web c2a (không cần HA):

``POST /api/camera/bo_dam/{ten}/ve``      vé dùng một lần, sống 60 giây
``WS   /api/camera/bo_dam/{ten}/ws?ve=``  hai chiều: máy chủ gửi tiếng mic camera
                                          (PCM16 mono 16 kHz, nhị phân); trình
                                          duyệt gửi tiếng mic PCM16 16 kHz lúc giữ
                                          nút, và chữ ``het`` khi thả nút

go2rtc không gửi được header ``Authorization`` từ một lệnh ``exec``, nên đường
POST dùng chữ ký HMAC (``services/signed_url``) gắn với đúng camera và đúng
phương thức — chữ ký rò ra chỉ phát được ra loa của camera ấy, không làm gì khác.
"""

from __future__ import annotations

import asyncio
import base64

from fastapi import APIRouter, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from api.support import require_admin
# Logger của dự án: ``logging.getLogger(__name__)`` không có handler, mọi dòng bị nuốt.
from utils.log import logger


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/camera/test")
    async def test(body: dict, authorization: str | None = Header(default=None)):
        """Chụp thử một camera đã lưu và trả về ảnh xem trước.

        Bấm Lưu xong mới test được: hàm chụp đọc sổ trong config, không nhận
        tham số rời. Nói rõ trong UI để người dùng không tưởng nút hỏng.
        """
        require_admin(authorization)

        from services import camera_nha

        ten = str(body.get("ten") or "").strip()
        if not ten:
            return {"ok": False, "error": "Chưa chọn camera nào để thử."}
        try:
            ten_that, jpeg = await asyncio.to_thread(camera_nha.chup, ten)
        except camera_nha.LoiCamera as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("test camera '%s' lỗi: %s", ten, exc)
            return {"ok": False, "error": str(exc)[:200]}
        return {
            "ok": True,
            "ten": ten_that,
            "bytes": len(jpeg),
            "anh": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii"),
        }

    @router.get("/api/camera/tro_ly")
    async def tro_ly(authorization: str | None = Header(default=None)):
        """Trợ lý giọng nói qua camera: từ gọi chọn được, trợ lý khác trong HA, tai đang chạy."""
        require_admin(authorization)
        from services import ve_tinh_camera

        return await asyncio.to_thread(ve_tinh_camera.trang_thai)

    @router.post("/api/camera/noi")
    async def noi(body: dict, authorization: str | None = Header(default=None)):
        """Đọc ``cau`` ra loa camera ``ten`` bằng giọng ``giong`` (rỗng = mặc định)."""
        require_admin(authorization)

        from services import loa_camera

        try:
            kq = await asyncio.to_thread(loa_camera.noi, str(body.get("ten") or ""),
                                         str(body.get("cau") or ""), str(body.get("giong") or ""))
        except loa_camera.LoiLoa as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **kq}

    @router.get("/api/camera/bo_dam/{ten}/go2rtc")
    async def bo_dam_go2rtc(ten: str, request: Request, goc: str = "",
                            authorization: str | None = Header(default=None)):
        """Dòng nguồn go2rtc cho bộ đàm camera ``ten``.

        ``goc`` là địa chỉ c2a mà MÁY CHẠY go2rtc gọi tới được (vd
        ``http://172.16.10.38:3030``); bỏ trống thì lấy địa chỉ của chính request.
        """
        require_admin(authorization)

        from urllib.parse import quote

        from services import camera_nha
        from services.signed_url import ky_duong_dan

        try:
            ten_that, _cam = await asyncio.to_thread(camera_nha._lay, ten)
        except camera_nha.LoiCamera as exc:
            return {"ok": False, "error": str(exc)}
        goc = (goc.strip() or str(request.base_url)).rstrip("/")
        ky = ky_duong_dan(_duong_bo_dam(ten_that), pham_vi=_PHAM_VI_BO_DAM,
                          song_giay=_BO_DAM_SONG_GIAY, phuong_thuc="POST")
        url = f"{goc}/api/camera/bo_dam/{quote(ten_that, safe='')}?{ky}"
        # go2rtc tách lệnh exec theo dấu cách và tham số theo dấu #: URL đã mã
        # hoá nên không chứa cả hai.
        from services.loa_camera import FFMPEG_TRUC_TIEP

        nguon = ("exec:ffmpeg -hide_banner -loglevel error "
                 f"{' '.join(FFMPEG_TRUC_TIEP)} -f alaw -ar 8000 -ac 1 -i - "
                 "-c:a copy -f alaw -flush_packets 1 -method POST "
                 f"{url}#backchannel=1#audio=alaw/8000")
        return {"ok": True, "ten": ten_that, "nguon": nguon}

    @router.post("/api/camera/bo_dam/{ten}")
    async def bo_dam(ten: str, request: Request, exp: str = "", sig: str = ""):
        from services import loa_camera
        from services.signed_url import kiem_chu_ky

        if not kiem_chu_ky(_duong_bo_dam(ten), exp, sig, pham_vi=_PHAM_VI_BO_DAM,
                           phuong_thuc="POST"):
            raise HTTPException(403, "chữ ký không hợp lệ hoặc đã hết hạn")
        phien = loa_camera.BoDam(ten)
        logger.info({"event": "bo_dam_mo", "camera": ten})
        try:
            async for khuc in request.stream():
                await asyncio.to_thread(phien.them, khuc)
        finally:
            await asyncio.to_thread(phien.dong)
            logger.info({"event": "bo_dam_dong", "camera": ten, "giay": round(phien.giay, 1),
                         "nhan_giay": round(phien.nhan_giay, 1),
                         "muc_max_db": round(phien.muc_max_db, 1), "loi": phien.loi[:120]})
        return {"ok": True, "giay": round(phien.giay, 1)}

    @router.post("/api/camera/xem/{ten}/ve")
    async def xem_ve(ten: str, request: Request, authorization: str | None = Header(default=None)):
        """Vé xem trực tiếp một camera — thẻ ``<img>`` không gửi được header."""
        identity = require_admin(authorization)
        from services.sse_ticket import kho_ve

        ve, ttl = kho_ve.cap({**identity, "xem": ten}, _phien_bam(request))
        return {"ok": True, "ticket": ve, "expires_in": ttl}

    @router.get("/api/camera/xem/{ten}")
    async def xem(ten: str, request: Request, ve: str = ""):
        """MJPEG trực tiếp của camera ``ten`` (``multipart/x-mixed-replace``).

        Trình duyệt mở c2a bằng https không gọi thẳng được go2rtc (http, mạng LAN), nên c2a
        đọc luồng (qua go2rtc hoặc RTSP thẳng) và chuyển thành ảnh JPEG liên tục — thẻ
        ``<img>`` nào cũng xem được. ffmpeg dừng ngay khi trình duyệt đóng.
        """
        from services import camera_nha
        from services.sse_ticket import kho_ve

        danh_tinh = kho_ve.dung(ve, _phien_bam(request))
        if not danh_tinh or danh_tinh.get("xem") != ten:
            raise HTTPException(401, "vé xem không hợp lệ hoặc đã dùng")
        try:
            _ten_that, cam = await asyncio.to_thread(camera_nha._lay, ten)
            url = await asyncio.to_thread(camera_nha.url_luong, ten,
                                          "phu" if camera_nha.co_luong_phu(cam) else "chinh")
        except camera_nha.LoiCamera as exc:
            raise HTTPException(404, str(exc)) from exc
        proc = await asyncio.create_subprocess_exec(
            *lenh_mjpeg(url), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL)

        async def phat():
            du = b""
            try:
                while b := await proc.stdout.read(65536):
                    anh, du = cat_jpeg(du + b)
                    for a in anh:
                        yield (b"--khung\r\nContent-Type: image/jpeg\r\nContent-Length: "
                               + str(len(a)).encode() + b"\r\n\r\n" + a + b"\r\n")
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

        return StreamingResponse(phat(), media_type="multipart/x-mixed-replace; boundary=khung",
                                 headers={"Cache-Control": "no-store"})

    @router.post("/api/camera/bo_dam/{ten}/ve")
    async def bo_dam_ve(ten: str, request: Request,
                        authorization: str | None = Header(default=None)):
        """Xin vé mở bộ đàm web. WebSocket của trình duyệt không gửi được header."""
        identity = require_admin(authorization)
        from services.sse_ticket import kho_ve

        ve, ttl = kho_ve.cap({**identity, "bo_dam": ten}, _phien_bam(request))
        return {"ok": True, "ticket": ve, "expires_in": ttl}

    @router.websocket("/api/camera/bo_dam/{ten}/ws")
    async def bo_dam_ws(ws: WebSocket, ten: str, ve: str = ""):
        from services import camera_nha, loa_camera, ve_tinh_camera
        from services.sse_ticket import kho_ve

        danh_tinh = kho_ve.dung(ve, _phien_bam(ws))
        # Vé cấp cho camera này mới mở được camera này.
        if not danh_tinh or danh_tinh.get("bo_dam") != ten:
            await ws.close(code=4401)
            return
        try:
            ten_that, cam = await asyncio.to_thread(camera_nha._lay, ten)
        except camera_nha.LoiCamera as exc:
            await ws.accept()
            await ws.send_json({"loi": str(exc)})
            await ws.close()
            return
        await ws.accept()
        phien = loa_camera.BoDam(ten_that, _TAN_SO_WEB)
        logger.info({"event": "bo_dam_web_mo", "camera": ten_that})

        async def nghe() -> None:
            """Tiếng mic camera → trình duyệt; ffmpeg chết (camera rớt mạng) thì mở lại."""
            while True:
                proc = await asyncio.create_subprocess_exec(
                    *ve_tinh_camera._lenh_mic(cam), stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL)
                try:
                    while True:
                        await ws.send_bytes(await proc.stdout.readexactly(_KHUC_NGHE))
                except asyncio.IncompleteReadError:
                    pass
                finally:
                    if proc.returncode is None:
                        proc.kill()
                        await proc.wait()
                await asyncio.sleep(2)

        tai = asyncio.create_task(nghe())
        da_bao = ""
        try:
            while True:
                tin = await ws.receive()
                if tin["type"] == "websocket.disconnect":
                    break
                if tin.get("bytes"):
                    await asyncio.to_thread(phien.them_pcm, tin["bytes"])
                    if phien.loi != da_bao:
                        da_bao = phien.loi
                        await ws.send_json({"loi": da_bao})
                elif tin.get("text") == "het":
                    await asyncio.to_thread(phien.dong)
        except WebSocketDisconnect:
            pass
        finally:
            tai.cancel()
            await asyncio.gather(tai, return_exceptions=True)
            await asyncio.to_thread(phien.dong)
            logger.info({"event": "bo_dam_web_dong", "camera": ten_that,
                         "giay": round(phien.giay, 1), "nhan_giay": round(phien.nhan_giay, 1),
                         "muc_max_db": round(phien.muc_max_db, 1), "loi": phien.loi[:120]})

    return router


#: Xem trực tiếp: khung/giây và bề ngang ảnh — đủ nhìn người đứng trước camera, nhẹ máy chủ.
_XEM_KHUNG_GIAY = 8
_XEM_RONG = 640


def lenh_mjpeg(url: str) -> list[str]:
    """ffmpeg đọc luồng RTSP → chuỗi JPEG liền nhau (mỗi khung một ảnh trọn)."""
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-rtsp_transport", "tcp", "-fflags", "nobuffer", "-flags", "low_delay", "-i", url,
            "-an", "-vf", f"fps={_XEM_KHUNG_GIAY},scale={_XEM_RONG}:-2", "-q:v", "7",
            "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1"]


def cat_jpeg(du: bytes) -> tuple[list[bytes], bytes]:
    """Tách các ảnh JPEG trọn (FFD8…FFD9) khỏi dòng byte; phần dở trả lại. Trong dữ liệu ảnh
    byte FF luôn được chèn 00 phía sau, nên FFD9 chỉ xuất hiện ở cuối ảnh."""
    anh = []
    while True:
        a = du.find(b"\xff\xd8")
        if a < 0:
            return anh, b""
        b = du.find(b"\xff\xd9", a + 2)
        if b < 0:
            return anh, du[a:]
        anh.append(du[a:b + 2])
        du = du[b + 2:]


def _phien_bam(conn) -> str:
    """Hash session-id trong cookie ("" nếu đi bằng Bearer) — khuôn ``api/register``.

    Vé RÀNG vào phiên đã xin nó: đọc được vé trong 60 giây cũng không mở được
    bộ đàm từ máy khác.
    """
    try:
        from services.browser_session import COOKIE_NAME, _bam
        sid = conn.cookies.get(COOKIE_NAME, "")
        return _bam(sid) if sid else ""
    except Exception:
        return ""


#: Trình duyệt thu và phát ở 16 kHz — đủ cho tiếng nói, nhẹ đường truyền.
_TAN_SO_WEB = 16000
#: 64 ms mỗi khúc gửi trình duyệt.
_KHUC_NGHE = 2048


_PHAM_VI_BO_DAM = "bo_dam"
#: Dòng dán vào go2rtc.yaml phải sống lâu; thu hồi bằng cách đổi khoá gốc.
_BO_DAM_SONG_GIAY = 10 * 365 * 86400


def _duong_bo_dam(ten: str) -> str:
    return f"/api/camera/bo_dam/{ten}"
