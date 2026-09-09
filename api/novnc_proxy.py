"""noVNC same-origin proxy — mở màn hình trình duyệt qua CÙNG cổng với web UI.

VÌ SAO CẦN. noVNC chạy trong chính container này ở cổng 6080, và cổng đó được
publish ra LAN nên vào bằng IP thì mở thẳng `http://<ip>:6080/vnc.html` là xong.
Nhưng khi vào bằng TÊN MIỀN qua Cloudflare Tunnel thì không: tunnel chỉ trỏ MỘT
dịch vụ (cổng 3030 của web UI), không có đường nào tới 6080. Bấm "Mở noVNC" ở
`https://gpt.vhtatn.io.vn/settings/` ra `https://gpt.vhtatn.io.vn:6080/…` —
cổng đó không tồn tại qua tunnel nên trình duyệt treo rồi báo lỗi (đo 09/09).

Ghi cứng địa chỉ nội bộ vào cấu hình cũng không xong: người dùng vào bằng cả IP
lẫn tên miền, đặt một cái là hỏng cái kia.

Proxy này đưa noVNC về cùng gốc với web UI (`/novnc/…`) nên chạy được với MỌI
đường vào — IP, tên miền, hay qua tunnel — mà không phải thêm route Cloudflare.

Gồm hai phần, thiếu một là màn hình đen:
  · HTTP  `/novnc/{path}`   → tệp tĩnh của noVNC (vnc.html, JS, CSS, ảnh)
  · WS    `/novnc/websockify` → kênh RFB thật; noVNC nói WebSocket nhị phân với
    websockify, nên phải chuyển tiếp hai chiều theo byte, không đụng nội dung.

BẢO MẬT: cùng cổng nghĩa là cùng ai vào được web UI thì vào được đây. Đường HTTP
đòi khoá quản trị như các proxy khác. Đường WS thì KHÔNG kiểm được bằng header
(trình duyệt không cho đặt header khi mở WebSocket) — nó dựa vào chính lớp bảo
vệ của noVNC/x11vnc, đúng như khi vào thẳng cổng 6080 từ LAN.
"""

from __future__ import annotations

import asyncio
import os

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from api.support import require_admin
from services.ingress_guard import BodyTooLarge, read_body_limited, read_upstream_limited

NOVNC_URL = os.getenv("NOVNC_URL_INTERNAL", "http://127.0.0.1:6080").rstrip("/")
_NOVNC_WS = NOVNC_URL.replace("http://", "ws://").replace("https://", "wss://")

# Tệp tĩnh của noVNC nhỏ (JS/CSS/ảnh); 16MB là rộng tay.
_MAX_BODY = 16 * 1024 * 1024
_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=5.0)
_DROP_REQ = {"host", "content-length", "connection", "accept-encoding",
             "authorization", "cookie", "x-csrf-token"}
_DROP_RESP = {"content-encoding", "transfer-encoding", "content-length", "connection"}


def create_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/novnc/websockify")
    async def novnc_ws(ws: WebSocket):
        """Kênh RFB: nối trình duyệt ⟷ websockify, chuyển byte thô hai chiều.

        `subprotocols=["binary"]` là bắt buộc — noVNC đề nghị đúng giao thức con
        đó, không đáp lại thì nó đóng kết nối ngay và người dùng thấy màn hình
        đen không rõ lý do.
        """
        try:
            import websockets
        except ImportError:
            await ws.close(code=1011)
            return
        await ws.accept(subprotocol="binary")
        try:
            async with websockets.connect(
                f"{_NOVNC_WS}/websockify",
                subprotocols=["binary"],
                max_size=None,          # khung ảnh có thể rất lớn
                ping_interval=None,     # để noVNC tự lo nhịp giữ kết nối
            ) as up:
                async def _len():
                    """Trình duyệt → websockify."""
                    try:
                        while True:
                            await up.send(await ws.receive_bytes())
                    except (WebSocketDisconnect, RuntimeError):
                        pass

                async def _xuong():
                    """websockify → trình duyệt."""
                    try:
                        async for goi in up:
                            if isinstance(goi, bytes):
                                await ws.send_bytes(goi)
                            else:
                                await ws.send_text(goi)
                    except Exception:
                        pass

                # Một chiều đứt là coi như xong; huỷ chiều kia để không treo.
                _xong, con_lai = await asyncio.wait(
                    {asyncio.create_task(_len()), asyncio.create_task(_xuong())},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in con_lai:
                    t.cancel()
        except Exception:
            # Không nối được tới websockify (noVNC chưa chạy) → đóng lịch sự.
            pass
        finally:
            try:
                await ws.close()
            except Exception:
                pass

    @router.api_route("/novnc/{path:path}", methods=["GET", "POST", "HEAD"])
    async def novnc_http(path: str, request: Request,
                         authorization: str | None = Header(default=None)):
        """Tệp tĩnh của noVNC. Đòi khoá quản trị như các proxy nội bộ khác."""
        require_admin(authorization)
        url = f"{NOVNC_URL}/{path}"
        try:
            body = await read_body_limited(request, _MAX_BODY)
        except BodyTooLarge:
            raise HTTPException(status_code=413, detail={"error": "payload too large"})
        fwd = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQ}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                async with client.stream(
                    request.method, url, params=request.query_params,
                    content=body, headers=fwd,
                ) as upstream:
                    try:
                        payload = await read_upstream_limited(upstream, _MAX_BODY)
                    except BodyTooLarge:
                        raise HTTPException(status_code=502,
                                            detail={"error": "upstream response too large"})
                    status = upstream.status_code
                    headers = {k: v for k, v in upstream.headers.items()
                               if k.lower() not in _DROP_RESP}
                    ctype = upstream.headers.get("content-type")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502,
                                detail={"error": f"noVNC không phản hồi: {str(exc)[:120]}"})
        return Response(content=payload, status_code=status,
                        headers=headers, media_type=ctype)

    return router
