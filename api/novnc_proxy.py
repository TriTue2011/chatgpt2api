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

XÁC THỰC — vì sao phải dùng vé chứ không phải header. Web UI gắn khoá admin vào
header `Authorization` bằng JavaScript, nhưng noVNC mở bằng `window.open` sang
TAB MỚI: tab đó là điều hướng thường của trình duyệt, không có JavaScript nào
gắn header vào được. Bản đầu đòi `require_admin(authorization)` nên tab mới
luôn 401 (chủ máy dán ảnh 09/09) — đúng cái lỗi mà `services/sse_ticket.py` đã
gặp và giải cho SSE.

Bám theo đúng khuôn mẫu đó, thêm một bước vì noVNC khác SSE: SSE mở MỘT kết nối
nên vé dùng-một-lần là đủ, còn noVNC tải hàng chục tệp (vnc.html, rồi core/*.js,
app/*.js…) nên vé sẽ cháy ngay ở tệp đầu. Vé vì thế đổi lấy một COOKIE ngắn hạn
giới hạn trong đường `/novnc` — mọi tệp con và kênh WebSocket dùng chung cookie
đó, và nó không mở được bất kỳ endpoint nào khác.

Nhờ vậy kênh WebSocket cũng được bảo vệ: trình duyệt tự gửi cookie khi mở
WebSocket cùng gốc, thứ mà header không làm được.
"""

from __future__ import annotations

import asyncio
import os

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, WebSocket
from fastapi.responses import Response

from api.support import require_admin
from services.novnc_ve import kho_ve_novnc
from services.ingress_guard import BodyTooLarge, read_body_limited, read_upstream_limited

NOVNC_URL = os.getenv("NOVNC_URL_INTERNAL", "http://127.0.0.1:6080").rstrip("/")
_NOVNC_WS = NOVNC_URL.replace("http://", "ws://").replace("https://", "wss://")

# Tệp tĩnh của noVNC nhỏ (JS/CSS/ảnh); 16MB là rộng tay.
_MAX_BODY = 16 * 1024 * 1024
_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=5.0)
_DROP_REQ = {"host", "content-length", "connection", "accept-encoding",
             "authorization", "cookie", "x-csrf-token"}
_DROP_RESP = {"content-encoding", "transfer-encoding", "content-length", "connection"}

# Cookie phiên noVNC. Đặt path=/novnc nên không lẫn với cookie phiên chính.
TEN_COOKIE = "c2a_novnc"


async def _chuyen_tiep(path: str, request: Request) -> Response:
    """Lấy một tệp của noVNC từ cổng 6080 nội bộ và trả nguyên về cho trình duyệt."""
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


def create_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/novnc/websockify")
    async def novnc_ws(ws: WebSocket):
        """Kênh RFB: nối trình duyệt ⟷ websockify, chuyển byte thô hai chiều.

        `subprotocols=["binary"]` là bắt buộc — noVNC đề nghị đúng giao thức con
        đó, không đáp lại thì nó đóng kết nối ngay và người dùng thấy màn hình
        đen không rõ lý do.
        """
        # Trình duyệt TỰ gửi cookie khi mở WebSocket cùng gốc — nên kênh này
        # kiểm được danh tính, thứ mà header không làm được. Từ chối trước khi
        # accept để kẻ không có phiên không chạm tới VNC server.
        if not kho_ve_novnc.phien_con_han(ws.cookies.get(TEN_COOKIE, "")):
            await ws.close(code=1008)   # 1008 = vi phạm chính sách
            return
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
                    """Trình duyệt → websockify.

                    Dùng `receive()` thô chứ KHÔNG `receive_bytes()`: RFB là
                    giao thức SERVER NÓI TRƯỚC, nên ngay sau bắt tay trình
                    duyệt chưa gửi byte nào, còn Starlette vẫn có thể giao
                    khung `text` hoặc sự kiện `websocket.disconnect`.
                    `receive_bytes()` gặp hai thứ đó thì ném `KeyError` —
                    KHÔNG nằm trong `(WebSocketDisconnect, RuntimeError)` mà
                    bản cũ bắt, nên ngoại lệ thoát ra, `asyncio.wait` thấy
                    FIRST_COMPLETED và đóng cả phiên.

                    Đo thật 10/09/2026: log đi đúng thứ tự `connection open →
                    connection closed` RỒI websockify mới ghi nhận kết nối —
                    tức proxy đã đóng phía trình duyệt trước khi kịp bơm
                    `RFB 003.008` xuống. Người dùng thấy "Connecting..." rồi
                    noVNC thử lại mãi (17 lần trong 20 phút).
                    """
                    try:
                        while True:
                            tin = await ws.receive()
                            if tin.get("type") == "websocket.disconnect":
                                return
                            goi = tin.get("bytes")
                            if goi is None:
                                chu = tin.get("text")
                                if chu is None:
                                    continue
                                goi = chu.encode()
                            await up.send(goi)
                    except Exception:
                        # Bắt RỘNG có chủ đích: chiều này đứt kiểu gì cũng chỉ
                        # có một cách xử lý — kết thúc để chiều kia được dọn.
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

    @router.post("/api/novnc/ve")
    async def novnc_cap_ve(authorization: str | None = Header(default=None)):
        """Xin vé mở noVNC. Xác thực bằng header như mọi endpoint khác.

        Web UI gọi cái này TRƯỚC khi `window.open`, rồi nhét vé vào URL. Vé
        sống 60 giây và dùng một lần nên lộ qua log hay lịch sử trình duyệt
        cũng gần như vô hại — khác hẳn việc nhét thẳng khoá admin vào URL.
        """
        require_admin(authorization)
        ve, ttl = kho_ve_novnc.cap()
        return {"ok": True, "ticket": ve, "expires_in": ttl}

    @router.api_route("/novnc/{path:path}", methods=["GET", "POST", "HEAD"])
    async def novnc_http(path: str, request: Request,
                         authorization: str | None = Header(default=None)):
        """Tệp tĩnh của noVNC.

        Nhận xác thực theo ba đường, theo thứ tự thực tế hay gặp:
          1. cookie phiên noVNC — các tệp con sau khi đã vào bằng vé;
          2. `?ve=` — lần mở đầu tiên từ tab mới, đổi luôn lấy cookie;
          3. header — script hoặc client tự gọi.
        """
        phien = request.cookies.get(TEN_COOKIE, "")
        if kho_ve_novnc.phien_con_han(phien):
            return await _chuyen_tiep(path, request)

        ve = request.query_params.get("ve", "")
        if ve and kho_ve_novnc.dung(ve):
            # Vé hợp lệ → cấp cookie cho các tệp con, rồi phục vụ luôn tệp này.
            phien_moi = kho_ve_novnc.mo_phien()
            resp = await _chuyen_tiep(path, request)
            resp.set_cookie(
                TEN_COOKIE, phien_moi,
                max_age=int(kho_ve_novnc.PHIEN_TTL),
                # Chỉ gửi kèm cho chính đường /novnc — cookie này không mở
                # được bất kỳ endpoint nào khác của hệ thống.
                path="/novnc",
                httponly=True,
                samesite="lax",
                # Qua tunnel là HTTPS, mở bằng IP LAN là HTTP. Đặt cứng
                # secure=True là cookie không bao giờ tới khi vào bằng IP.
                secure=request.url.scheme == "https",
            )
            return resp

        require_admin(authorization)
        return await _chuyen_tiep(path, request)

    return router
