"""API cho Camera nhà — tab Cài đặt → Home Assistant.

Sổ camera nằm trong ``config`` (khoá ``cameras``), nên web lưu nó qua đúng đường
lưu cấu hình chung như mọi card khác — ở đây KHÔNG có endpoint CRUD nào cho nó.
Ai được xem camera thì hỏi bộ lọc chức năng của từng kênh (ô tích «📷 Camera
nhà»), không phải một danh sách riêng của camera.

Hai việc web không tự làm được:

``POST /api/camera/test``        chụp thử một camera, trả ảnh xem trước
``POST /api/camera/noi``         đọc một câu ra loa camera (Dahua/Imou, cổng 37777)

Bộ đàm (mic điện thoại qua thẻ WebRTC Camera của HA → loa camera):

``GET  /api/camera/bo_dam/{ten}/go2rtc``  dòng ``exec:`` để dán vào go2rtc.yaml
``POST /api/camera/bo_dam/{ten}``         go2rtc đẩy luồng A-law 8 kHz tới đây

go2rtc không gửi được header ``Authorization`` từ một lệnh ``exec``, nên đường
POST dùng chữ ký HMAC (``services/signed_url``) gắn với đúng camera và đúng
phương thức — chữ ký rò ra chỉ phát được ra loa của camera ấy, không làm gì khác.
"""

from __future__ import annotations

import asyncio
import base64
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from api.support import require_admin

logger = logging.getLogger(__name__)


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
        nguon = ("exec:ffmpeg -hide_banner -loglevel error -f alaw -ar 8000 -ac 1 -i - "
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
            logger.info({"event": "bo_dam_dong", "camera": ten, "giay": round(phien.giay, 1)})
        return {"ok": True, "giay": round(phien.giay, 1)}

    return router


_PHAM_VI_BO_DAM = "bo_dam"
#: Dòng dán vào go2rtc.yaml phải sống lâu; thu hồi bằng cách đổi khoá gốc.
_BO_DAM_SONG_GIAY = 10 * 365 * 86400


def _duong_bo_dam(ten: str) -> str:
    return f"/api/camera/bo_dam/{ten}"
