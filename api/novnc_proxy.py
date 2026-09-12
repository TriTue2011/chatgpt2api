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
from starlette.websockets import WebSocketState

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

# DÙNG logger CỦA DỰ ÁN, không phải `logging.getLogger(__name__)`.
#
# App này không gọi `basicConfig`/`dictConfig` ở đâu cả: root logger không có
# handler và mức hiệu lực là WARNING. Nên mọi `logger.info(...)` qua
# `getLogger(__name__)` đều bị nuốt sạch — đo 11/09/2026 trong container:
#
#   api.novnc_proxy level hiệu lực: WARNING · root handlers: []
#   số dòng novnc_bat_tay trong toàn bộ log: 0
#
# Tức lần trước tôi thêm log để hết mù, rồi chính cái log ấy cũng vô hình, và
# tôi lại mất một lượt nữa mới nhận ra. `utils.log.logger` tự gắn
# StreamHandler ở mức DEBUG và `propagate=False`, đúng thứ các module khác
# (api/app.py, api/accounts.py) đang dùng để log hiện được ra `docker logs`.
from utils.log import logger


def _la_https(request: Request) -> bool:
    """Trình duyệt có đang dùng HTTPS không — tính cả khi đứng sau tunnel.

    Cloudflare Tunnel cắt TLS ở biên rồi gọi vào bằng HTTP, nên
    `request.url.scheme` là `http` trong khi người dùng đang ở `https://`.
    Chỉ nhìn scheme thì cookie qua domain mất cờ Secure (đo 11/09/2026:
    `set-cookie: …; Path=/novnc; SameSite=lax`, không có Secure).

    Cùng cách đọc với `resolve_image_base_url` trong api/support.py.
    """
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if proto:
        return proto == "https"
    return request.url.scheme == "https"


def _ghi_dut(cho: str, exc: BaseException) -> None:
    """Ghi lý do một chiều của kênh RFB đứt.

    Kênh đứt là chuyện BÌNH THƯỜNG (người dùng đóng tab), nên để mức INFO chứ
    không phải ERROR — nhưng tuyệt đối không được im. Trước đây mọi nhánh hỏng
    đều `pass` trắng, và khi phiên chết ngay sau khi mở thì không còn gì để
    lần: log chỉ có `connection open` rồi `connection closed`.
    """
    logger.info({
        "event": "novnc_kenh_dut",
        "cho": cho,
        "loai": type(exc).__name__,
        "chi_tiet": str(exc)[:200],
    })


# Ô nhập của noVNC (vnc.html) — lấy nguyên văn từ gói Debian `novnc` 1.6.0,
# đã đối chiếu từng byte bằng `cat -A` nên khớp đúng cả khoảng trắng đầu dòng.
_O_MAT_KHAU = b'<input id="noVNC_password_input" type="password">'
_O_MAT_KHAU_MOI = b'<input id="noVNC_password_input" type="password" autocomplete="new-password">'
_O_TEN = b'<input id="noVNC_username_input">'
_O_TEN_MOI = b'<input id="noVNC_username_input" autocomplete="off">'


def _chan_trinh_duyet_nho_mat_khau(html: bytes) -> bytes:
    """Thêm `autocomplete` vào ô nhập của noVNC để trình duyệt thôi ghi nhớ.

    VÌ SAO. `vnc.html` đặt ô mật khẩu trong một `<form>` có nút submit và
    KHÔNG khai `autocomplete`. Đó đúng hình dạng mà Chrome nhận ra là "form
    đăng nhập": nó hỏi lưu, rồi lần sau tự điền theo tên miền. Chủ máy không
    muốn mật khẩu VNC nằm trong kho mật khẩu trình duyệt (11/09/2026).

    Sửa ở proxy chứ không vá tệp trong ảnh: `vnc.html` thuộc gói Debian
    `novnc`, vá trong Dockerfile là sửa tệp của gói và sẽ mất khi gói nâng cấp.
    `_chuyen_tiep` vốn đã đọc trọn thân phản hồi vào bộ nhớ, và `_DROP_RESP` đã
    bỏ `content-length`, nên đổi độ dài ở đây là an toàn.

    Dùng `new-password` cho ô mật khẩu: Chrome tôn trọng giá trị này chắc tay
    hơn `off` khi quyết định KHÔNG tự điền. Ô tên đi kèm cũng phải khai `off`,
    vì Chrome ghép cặp tên+mật khẩu mới coi là form đăng nhập.

    Không khớp thì trả nguyên xi — noVNC đổi markup thì mất tác dụng chứ không
    làm hỏng trang.
    """
    if _O_MAT_KHAU in html:
        html = html.replace(_O_MAT_KHAU, _O_MAT_KHAU_MOI)
    if _O_TEN in html:
        html = html.replace(_O_TEN, _O_TEN_MOI)
    return html


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
    if ctype and "text/html" in ctype.lower():
        payload = _chan_trinh_duyet_nho_mat_khau(payload)
    # CẤM CACHE cả nhánh /novnc — đây là đường CÓ XÁC THỰC.
    #
    # Máy chủ tệp tĩnh phía dưới (websockify --web) không gửi `Cache-Control`
    # nào, nên Cloudflare áp mặc định của nó. Đo 12/09/2026 qua tên miền:
    # `cache-control: max-age=14400`, `cf-cache-status: HIT`, `age: 132` — và
    # lấy được `/novnc/app/ui.js` trả 200 KHÔNG cần cookie, trong khi cùng
    # đường đó qua IP (đi thẳng vào ứng dụng) trả 401. Tức bản cache ở biên
    # phục vụ tệp cho người chưa đăng nhập, vượt qua đúng lớp kiểm mà
    # `novnc_http` dựng lên.
    #
    # Cũng là bảo hiểm cho `vnc.html`: phản hồi của nó MANG Set-Cookie phiên,
    # cache một phản hồi như vậy là phát cùng một cookie cho nhiều người.
    headers["cache-control"] = "no-store"
    return Response(content=payload, status_code=status,
                    headers=headers, media_type=ctype)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/novnc/websockify")
    async def novnc_ws(ws: WebSocket):
        """Kênh RFB: nối trình duyệt ⟷ websockify, chuyển byte thô hai chiều.

        CHỈ ĐÁP LẠI giao thức con mà khách ĐÃ ĐỀ NGHỊ. RFC 6455 cấm máy chủ
        trả một subprotocol khách không xin, và Chrome thi hành nghiêm: nó
        đóng kết nối NGAY, sạch sẽ, không báo lỗi gì.

        Bản cũ `accept(subprotocol="binary")` vô điều kiện. Chú thích cũ bảo
        "noVNC đề nghị binary" — ĐÚNG với noVNC đời cũ, SAI với bản 1.6.0 đang
        đóng trong ảnh này: `core/rfb.js:559` truyền `this._wsProtocols` và cả
        tệp không còn chuỗi "binary" nào.

        Đo 11/09/2026, cùng một proxy, ba kiểu khách:

          khách KHÔNG đề nghị  → máy chủ trả ['binary']   ← VI PHẠM
          khách đề nghị binary → máy chủ trả ['binary']
          khách đề nghị chat   → máy chủ trả ['binary']   ← VI PHẠM

        Nên trình duyệt thật chết sau 29ms: `connection open` → tự ngắt →
        `_len()` thoát ÊM vì gặp `websocket.disconnect`, KHÔNG ngoại lệ nào
        được ném, `novnc_kenh_dut` đếm 0. Còn socket thô của tôi thì sống 8
        giây, vì nó không thi hành luật này.
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
        # CHỈ đáp lại thứ khách đã đề nghị. Khách không xin gì thì trả None —
        # `accept(subprotocol=None)` không phát header Sec-WebSocket-Protocol,
        # đúng luật và Chrome không đóng nữa.
        de_nghi = list(ws.scope.get("subprotocols") or [])
        chon = "binary" if "binary" in de_nghi else None
        logger.info({
            "event": "novnc_bat_tay",
            "khach_de_nghi": de_nghi,
            "may_chu_tra": chon,
        })
        await ws.accept(subprotocol=chon)
        try:
            async with websockets.connect(
                f"{_NOVNC_WS}/websockify",
                # Giữ ĐÚNG thứ đã thoả thuận với trình duyệt. Ép "binary" khi
                # phía dưới không dùng nó là tự tạo lệch giữa hai đầu ống.
                subprotocols=[chon] if chon else None,
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
                    except Exception as exc:
                        # Bắt RỘNG có chủ đích: chiều này đứt kiểu gì cũng chỉ
                        # có một cách xử lý — kết thúc để chiều kia được dọn.
                        # NHƯNG PHẢI GHI LẠI. Bản cũ `pass` trắng: phiên chết
                        # sau 150ms mà log không còn một dấu vết nào, nên không
                        # cách nào biết vì sao (đo 11/09/2026, chủ máy mở qua
                        # domain: `connection open` → 0,15s → `connection
                        # closed`, không kèm gì cả).
                        _ghi_dut("len", exc)

                async def _xuong():
                    """websockify → trình duyệt."""
                    try:
                        async for goi in up:
                            if isinstance(goi, bytes):
                                await ws.send_bytes(goi)
                            else:
                                await ws.send_text(goi)
                    except Exception as exc:
                        _ghi_dut("xuong", exc)

                # Một chiều đứt là coi như xong; huỷ chiều kia để không treo.
                t_len = asyncio.create_task(_len(), name="len")
                t_xuong = asyncio.create_task(_xuong(), name="xuong")
                _xong, con_lai = await asyncio.wait(
                    {t_len, t_xuong}, return_when=asyncio.FIRST_COMPLETED,
                )
                # GHI CẢ LỐI THOÁT ÊM. Lần trước tôi chỉ gắn log vào các nhánh
                # NGOẠI LỆ, nên khi trình duyệt tự ngắt (thoát bình thường,
                # không ném gì) thì log vẫn trắng — `novnc_kenh_dut` đếm 0 và
                # tôi mất thêm một lượt đoán mò. Bên nào về trước cũng là dữ
                # kiện: "len" về trước = trình duyệt ngắt, "xuong" về trước =
                # websockify ngắt.
                logger.info({
                    "event": "novnc_kenh_ket_thuc",
                    "ben_ve_truoc": ", ".join(sorted(t.get_name() for t in _xong)),
                })
                for t in con_lai:
                    t.cancel()
        except Exception as exc:
            # Không nối được tới websockify (noVNC chưa chạy) → đóng lịch sự,
            # nhưng NÓI RA. Đây là chỗ nuốt mất lỗi `websockets.connect` —
            # thiếu gói, sai subprotocol, websockify từ chối… đều rơi vào đây
            # và trước nay biến mất không dấu vết.
            _ghi_dut("noi_upstream", exc)
        finally:
            # CHỈ đóng khi kết nối còn sống. Kênh đứt bình thường là người dùng
            # tắt tab: trình duyệt ngắt, `_len` nhận `websocket.disconnect` rồi
            # thoát — lúc này gửi `websocket.close` xuống một kết nối đã mất thì
            # uvicorn ném RuntimeError "Unexpected ASGI message
            # 'websocket.close', after sending 'websocket.close' or response
            # already completed", và nó được ghi thành `novnc_kenh_dut
            # cho=dong` — một dòng lỗi GIẢ, lại còn CHE MẤT lý do đứt thật vì
            # đó là dòng cuối cùng của phiên.
            #
            # Đo 12/09/2026 trên log các lượt thật của chủ máy (17:33–17:38):
            # mọi phiên đều kết thúc bằng đúng dòng RuntimeError ấy, nên nhìn
            # log không biết được kênh đứt vì đâu.
            #
            # PHẢI nhìn `client_state`, KHÔNG phải `application_state` — bản
            # trước chỉ chặn bằng `application_state` và ĐÃ ĐO LÀ KHÔNG ĂN:
            # lên ảnh rồi thử lại, vẫn đúng 1 dòng lỗi giả. Đọc
            # starlette/websockets.py mới rõ hai trạng thái đổi ở hai lúc khác
            # nhau: `client_state` → DISCONNECTED khi NHẬN `websocket.disconnect`
            # (dòng 54, đúng thứ vòng `_len` gặp rồi thoát), còn
            # `application_state` chỉ đổi khi ỨNG DỤNG gửi đi cái gì đó (dòng
            # 63–95) nên chưa gửi close thì vẫn CONNECTED. Client đã đi mà
            # application vẫn CONNECTED → điều kiện cũ luôn đúng → vẫn gọi
            # close → uvicorn ném "Unexpected ASGI message 'websocket.close'".
            #
            # Kiểm bằng uvicorn THẬT (TestClient không tái hiện được, lớp vận
            # chuyển trong bộ nhớ của nó dễ tính hơn): điều kiện cũ ghi
            # `['dong']`, điều kiện này ghi `[]`.
            if (ws.client_state is not WebSocketState.DISCONNECTED
                    and ws.application_state is not WebSocketState.DISCONNECTED):
                try:
                    await ws.close()
                except Exception as exc:
                    _ghi_dut("dong", exc)

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
                #
                # Đứng SAU Cloudflare Tunnel thì `request.url.scheme` là `http`
                # (tunnel đã cắt TLS ở biên) trong khi trình duyệt đang dùng
                # HTTPS — nên chỉ nhìn scheme là cookie qua domain mất cờ
                # Secure. Đo 11/09/2026: `set-cookie: …; Path=/novnc;
                # SameSite=lax`, không có Secure. Lấy thêm `x-forwarded-proto`
                # như resolve_image_base_url đã làm.
                secure=_la_https(request),
            )
            return resp

        require_admin(authorization)
        return await _chuyen_tiep(path, request)

    return router
