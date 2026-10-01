"""Grok web miễn phí. Chat bằng cookie, Firefox chỉ mở lúc lấy cookie.

Tài khoản theo thứ tự trong ``providers.grok_web.accounts`` (Cài đặt › Grok), mỗi tài khoản
một hồ sơ Firefox riêng — xem ``api/grok_firefox.py``. Hết phiên thì mở lại đúng hồ sơ đó (còn
đăng nhập, không gõ mật khẩu), vẫn hỏng thì sang tài khoản kế. Không đi Chrome của captcha-solver:
máy này bị Cloudflare chặn Chrome.

Chat là websocket ``wss://grok.com/ws/mgw/``. Không hâm nóng sẵn client
như Gemini.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
import time
import urllib.error
import uuid
from typing import Any, Iterator

#: Giây im lặng tối đa giữa hai thông điệp của máy chủ trước khi coi phiên là treo.
_IM_TOI_DA = 45

_MODES = {
    "fast": "fast",
    "grok-chat-fast": "fast",
    "auto": "auto",
    "grok-chat-auto": "auto",
    "expert": "expert",
    "grok-chat-expert": "expert",
    "heavy": "heavy",
    "grok-chat-heavy": "heavy",
}


def _logger():
    from utils.log import logger
    return logger


def che_do(model: str) -> str:
    """Tên model phía người gọi → mode grok.com. Tài khoản miễn phí dùng fast."""
    ten = str(model or "").strip().lower()
    if ten in ("", "auto"):
        return "fast"
    return _MODES.get(ten, "fast")


def hop_van_ban(messages: list[dict[str, Any]] | None) -> str:
    """Ghép transcript thành một prompt, cùng ý với Gemini flatten."""
    parts: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").strip().lower() or "user"
        content = msg.get("content")
        if isinstance(content, list):
            lines = []
            for part in content:
                if isinstance(part, str):
                    lines.append(part)
                elif isinstance(part, dict) and part.get("type") in (None, "text"):
                    lines.append(str(part.get("text") or ""))
            content = "\n".join(x for x in lines if x)
        text = str(content or "").strip()
        if text:
            parts.append(f"[{role}]\n{text}")
    return "\n\n".join(parts).strip()


def tai_cookie(profile: str) -> dict[str, str]:
    """Cookie Firefox riêng của tài khoản đã thu (`api/grok_firefox`). Không hỏi Chrome của solver."""
    from api.grok_firefox import doc_cookie_file
    cookies = doc_cookie_file(profile)
    if cookies.get("sso"):
        return cookies
    raise RuntimeError(f"Chưa có phiên Grok cho {profile} — bấm «Đăng nhập» ở Cài đặt › Grok.")


def _ws_send(tls, obj: dict) -> None:
    _ws_frame(tls, 0x1, json.dumps(obj, separators=(",", ":")).encode())


def _ws_frame(tls, opcode: int, data: bytes) -> None:
    """Một khung client → server (RFC 6455: client PHẢI che mặt nạ)."""
    mask = os.urandom(4)
    header = bytearray([0x80 | opcode])
    n = len(data)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack("!H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", n)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    tls.sendall(bytes(header) + mask + masked)


def _doc_du(tls, buf: bytes, n: int) -> bytes | None:
    """Đọc tới khi ``buf`` đủ ``n`` byte. Máy chủ đóng kết nối giữa chừng thì None — `recv` trả b"" mãi mãi,
    vòng `while len(buf) < n: buf += recv()` cũ quay vô hạn."""
    while len(buf) < n:
        chunk = tls.recv(8192)
        if not chunk:
            return None
        buf += chunk
    return buf


def _ws_recv_khung(tls, buf: bytes) -> tuple[tuple[bool, int, bytes] | None, bytes]:
    """Một khung: (FIN, opcode, payload)."""
    b = _doc_du(tls, buf, 2)
    if b is None:
        return None, buf
    buf = b
    fin, opcode, ln, i = bool(buf[0] & 0x80), buf[0] & 0x0F, buf[1] & 0x7F, 2
    if ln in (126, 127):
        i = 4 if ln == 126 else 10
        b = _doc_du(tls, buf, i)
        if b is None:
            return None, buf
        buf = b
        ln = struct.unpack("!H", buf[2:4])[0] if i == 4 else struct.unpack("!Q", buf[2:10])[0]
    b = _doc_du(tls, buf, i + ln)
    if b is None:
        return None, buf
    buf = b
    return (fin, opcode, buf[i:i + ln]), buf[i + ln:]


def _ws_recv(tls, buf: bytes) -> tuple[tuple[int, bytes] | None, bytes]:
    """Một THÔNG ĐIỆP trọn vẹn: ghép khung phân mảnh (opcode 0 nối tiếp tới FIN), trả lời ping bằng pong. Trước
    đây khung nối tiếp bị bỏ nên một sự kiện JSON dài bị cắt đôi rồi rơi im lặng ở `json.loads`, còn ping không ai
    đáp thì máy chủ đóng kết nối giữa câu trả lời dài."""
    tin: tuple[int, bytearray] | None = None
    while True:
        khung, buf = _ws_recv_khung(tls, buf)
        if khung is None:
            return None, buf
        fin, opcode, payload = khung
        if opcode == 0x9:
            _ws_frame(tls, 0xA, payload)
            continue
        if opcode == 0xA:
            continue
        if opcode == 0x8:
            return (opcode, payload), buf
        if opcode == 0x0:
            if tin is None:
                continue                # nối tiếp mà không có khung đầu — bỏ
            tin[1].extend(payload)
        else:
            tin = (opcode, bytearray(payload))
        if fin:
            return (tin[0], bytes(tin[1])), buf


def _user_id(cookies: dict[str, str]) -> str:
    uid = str(cookies.get("x-userid") or "").strip()
    if uid:
        return uid
    import urllib.request
    jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request("https://grok.com/api/auth/session", headers={
        "Cookie": jar,
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        sess = json.loads(resp.read().decode())
    return str(((sess.get("session") or {}).get("userId")) or "")


def _delta_tu_event(ev: dict) -> str:
    kind = str(ev.get("type") or "")
    if kind == "response.chunk":
        chunk = ev.get("chunk") if isinstance(ev.get("chunk"), dict) else {}
        text = chunk.get("text") if isinstance(chunk.get("text"), dict) else {}
        delta = text.get("text") if isinstance(text.get("text"), str) else ""
        channel = str(text.get("channel") or "").upper()
        if delta and "ANALYSIS" not in channel and "REASONING" not in channel:
            return delta
    if kind == "response.output_text.delta" and isinstance(ev.get("delta"), str):
        return ev["delta"]
    if kind == "response.output_text.done" and isinstance(ev.get("text"), str):
        return ""
    return ""


def _loi_event(ev: dict) -> str:
    err = ev.get("error") if isinstance(ev.get("error"), dict) else {}
    code = str(err.get("code") or err.get("type") or "error")
    msg = err.get("message")
    if isinstance(msg, str) and msg and len(msg) < 160:
        return f"{code}: {msg}"
    return code


def _la_loi_phien(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403):
        return True
    chu = str(exc)
    return any(mau in chu for mau in (
        "từ chối websocket", "user id", "thiếu sso", "Chưa có phiên", "403",
    ))


def stream_chat(prompt: str, mode: str, cookies: dict[str, str] | None = None,
                anh: list[str] | None = None, da_dung: list[str] | None = None) -> Iterator[str]:
    """Sinh từng mảnh chữ. Xoay tài khoản theo thứ tự ưu tiên (như Flow): tài khoản hết phiên thì mở lại hồ sơ
    Firefox của nó MỘT lần, vẫn hỏng thì sang tài khoản kế. Chỉ đổi khi CHƯA gửi chữ nào — thử lại sau khi đã gửi
    nửa câu thì người gọi nhận câu trả lời lặp đầu."""
    if cookies is not None:
        yield from _stream_chat(prompt, mode, cookies, anh)
        return
    from api.grok_firefox import dang_bat, lam_moi
    ds = dang_bat()
    if not ds:
        raise RuntimeError("Chưa có tài khoản Grok nào đang bật — thêm và đăng nhập ở Cài đặt › Grok.")
    loi: list[str] = []
    for acc in ds:
        p = acc["profile"]
        da_gui = False
        try:
            _ghi_tai_khoan(acc, mode)
            for lan in range(2):
                try:
                    for manh in _stream_chat(prompt, mode, tai_cookie(p), anh):
                        da_gui = True
                        yield manh
                    if da_dung is not None:
                        da_dung.append(p)
                    return
                except Exception as exc:
                    if da_gui or lan or not _la_loi_phien(exc):
                        raise
                    lam_moi(p)
        except Exception as exc:
            if da_gui:
                raise
            loi.append(f"{acc.get('label') or p}: {str(exc)[:120]}")
            _logger().warning({"event": "grok_web_tai_khoan_hong", "profile": p, "error": str(exc)[:160]})
    raise RuntimeError("Grok web: mọi tài khoản đều hỏng — " + "; ".join(loi))


def _ghi_tai_khoan(acc: dict[str, Any], mode: str) -> None:
    """Báo request_context để Agent runs hiện đúng tài khoản Grok đã dùng (như Flow)."""
    try:
        from services.request_context import note_provider_account
        note_provider_account("grok_web", str(acc.get("email") or acc.get("label") or acc["profile"]),
                              model=f"grok/{mode}", account_id=str(acc["profile"]))
    except Exception:
        pass


def _anh_xong(ev: dict) -> str:
    """Đường ảnh đã vẽ XONG trong một mảnh (đo 01/10/2026: `chunk.render_generated_image.image_chunk` có
    `imageUrl` = "users/<id>/generated/<uuid>/image.jpg", `progress` tới 100; tải ở assets.grok.com kèm cookie).
    Vẽ hỏng thì mảnh mang `systemErrCode` thay cho `imageUrl` — báo lỗi ra, đừng nói chung chung «không có ảnh»."""
    chunk = ev.get("chunk") if isinstance(ev.get("chunk"), dict) else {}
    ve = chunk.get("render_generated_image") if isinstance(chunk.get("render_generated_image"), dict) else {}
    ic = ve.get("image_chunk") if isinstance(ve.get("image_chunk"), dict) else {}
    if ic.get("systemErrCode"):
        raise RuntimeError(f"Grok vẽ ảnh lỗi: systemErrCode={ic.get('systemErrCode')}")
    url = str(ic.get("imageUrl") or "")
    return url if url and int(ic.get("progress") or 0) >= 100 else ""


def _stream_chat(prompt: str, mode: str, cookies: dict[str, str], anh: list[str] | None = None) -> Iterator[str]:
    """Một lượt gửi. Phiên tạm, không ghi vào lịch sử grok.com. ``anh``: nhận đường các ảnh Grok vẽ xong."""
    cookies = dict(cookies)
    if not cookies.get("sso"):
        raise RuntimeError("Cookie Grok web thiếu sso")
    uid = _user_id(cookies)
    if not uid:
        raise RuntimeError("Không lấy được user id của phiên Grok web")
    if "x-userid" not in cookies:
        cookies["x-userid"] = uid
    jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
    key = base64.b64encode(os.urandom(16)).decode()
    raw = socket.create_connection(("grok.com", 443), timeout=20)
    tls = ssl.create_default_context().wrap_socket(raw, server_hostname="grok.com")
    try:
        tls.settimeout(_IM_TOI_DA)
        tls.sendall((
            f"GET /ws/mgw/?uid={uid} HTTP/1.1\r\n"
            "Host: grok.com\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            "Origin: https://grok.com\r\n"
            "User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0\r\n"
            "Accept-Language: vi-VN,vi;q=0.9,en;q=0.8\r\n"
            f"Cookie: {jar}\r\n\r\n"
        ).encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = tls.recv(8192)
            if not chunk:
                raise RuntimeError("Grok web đóng kết nối trước khi bắt tay websocket xong")
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise RuntimeError(f"Grok web từ chối websocket: {status.decode('latin1', 'replace')[:80]}")
        init_id = "evt_init_" + uuid.uuid4().hex
        _ws_send(tls, {"event": {
            "type": "session.create",
            "event_id": init_id,
            "session": {
                "model": mode,
                "x_grok": {
                    "protocol_capabilities": ["conversation_attached", "custom_methods_v1"],
                    "use_chunk": True,
                    "enable_side_by_side": True,
                    "force_side_by_side": False,
                    "enable_image_generation": True,
                    "image_generation_count": 2,
                    "disable_text_follow_ups": False,
                    "disable_artifact": True,
                    "force_concise": False,
                    "keep_context": False,
                    "is_temporary": True,
                    "disable_memory": True,
                },
            },
        }})
        buf = rest
        created = False
        attached = False
        sent = False
        session_id = ""
        # Hạn tính từ lần CUỐI có dữ liệu, không phải từ lúc mở: hạn cứng 45 giây cũ cắt câu trả lời dài (expert,
        # heavy) rồi trả phần dở như đã xong.
        deadline = time.time() + _IM_TOI_DA
        while time.time() < deadline:
            frame, buf = _ws_recv(tls, buf)
            if not frame:
                break
            deadline = time.time() + _IM_TOI_DA
            opcode, payload = frame
            if opcode == 8:
                break
            if opcode != 1:
                continue
            try:
                obj = json.loads(payload.decode())
            except Exception:
                continue
            ev = obj.get("event") if isinstance(obj, dict) else None
            if not isinstance(ev, dict):
                continue
            kind = str(ev.get("type") or "")
            if kind == "error":
                raise RuntimeError(f"Grok web: {_loi_event(ev)}")
            if kind == "session.created" and ev.get("client_event_id") in ("", init_id):
                created = True
                session_id = session_id or str(obj.get("session_id") or "")
            if kind == "conversation.attached":
                attached = True
                conv = ev.get("conversation") if isinstance(ev.get("conversation"), dict) else {}
                session_id = session_id or str(conv.get("id") or "")
            delta = _delta_tu_event(ev)
            if delta:
                yield delta
            if anh is not None and kind == "response.chunk":
                url = _anh_xong(ev)
                if url and url not in anh:
                    anh.append(url)
            if kind == "response.done":
                return
            if created and attached and not sent and session_id:
                sent = True
                now = int(time.time() * 1000)
                _ws_send(tls, {
                    "session_id": session_id,
                    "event": {
                        "type": "conversation.item.create",
                        "event_id": f"evt_msg_{now}",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "x_grok": {
                                "client_message_id": uuid.uuid4().hex,
                                "input_chunks": [{"text": {"text": prompt}}],
                            },
                        },
                    },
                })
                _ws_send(tls, {
                    "session_id": session_id,
                    "event": {"type": "response.create", "event_id": f"evt_resp_{now}"},
                })
        if not sent:
            raise RuntimeError("Grok web không mở được phiên chat")
        raise RuntimeError("Grok web ngắt giữa câu trả lời (không có response.done)")
    finally:
        try:
            tls.close()
        except Exception:
            pass


def handle_grok_web_chat(
    model: str,
    messages: list[dict[str, Any]],
    stream: Any,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Cửa cho router chính. ``grok/fast`` và ``gw/fast``."""
    del body
    prompt = hop_van_ban(messages)
    if not prompt:
        raise RuntimeError("Tin nhắn trống")
    mode = che_do(model)
    shown = f"grok/{mode}"
    _logger().info({"event": "grok_web_request", "model": shown, "chars": len(prompt)})
    if stream:
        from services.protocol.openai_v1_chat_complete import completion_chunk
        cid = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())

        def _gen() -> Iterator[dict[str, Any]]:
            started = False
            for piece in stream_chat(prompt, mode):
                delta: dict[str, Any] = {"content": piece}
                if not started:
                    delta = {"role": "assistant", "content": piece}
                    started = True
                yield completion_chunk(shown, delta, None, cid, created)
            yield completion_chunk(shown, {}, "stop", cid, created)

        return _gen()
    text = "".join(stream_chat(prompt, mode))
    from services.protocol.openai_v1_chat_complete import completion_response
    return completion_response(shown, text, messages=messages)


def handle_grok_web_image_gen(prompt: str, n: int = 1, response_format: str = "url",
                              base_url: str = "") -> dict[str, Any]:
    """/v1/images/generations cho ``grok/imagine`` — cùng websocket chat, Grok tự vẽ (model imagine). Ảnh tải bằng
    cookie của CHÍNH tài khoản vừa vẽ (assets.grok.com trả 403 khi không có), lưu vào thư mục ảnh như Gemini Web API."""
    import base64
    import urllib.request
    from services.config import config

    anh: list[str] = []
    da_dung: list[str] = []
    loi = "".join(stream_chat(f"Vẽ ảnh: {prompt}" if "vẽ" not in prompt.lower() else prompt, "fast",
                              anh=anh, da_dung=da_dung))
    if not anh:
        raise RuntimeError(f"Grok không vẽ ảnh nào. Trả lời: {loi[:200]}")
    cookies = tai_cookie(da_dung[-1])
    jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
    thu_muc = config.images_dir / "grok"
    thu_muc.mkdir(parents=True, exist_ok=True)
    data: list[dict[str, Any]] = []
    for duong in anh[:max(1, int(n or 1))]:
        req = urllib.request.Request(f"https://assets.grok.com/{duong.lstrip('/')}", headers={
            "Cookie": jar, "Referer": "https://grok.com/",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            byte = resp.read()
        if not byte:
            continue
        ten = f"{uuid.uuid4().hex}.jpg"
        (thu_muc / ten).write_bytes(byte)
        if response_format == "b64_json":
            data.append({"b64_json": base64.b64encode(byte).decode("ascii")})
        else:
            data.append({"url": f"{base_url.rstrip('/')}/images/grok/{ten}" if base_url else f"/images/grok/{ten}"})
    if not data:
        raise RuntimeError("Tải ảnh Grok vẽ không được")
    _logger().info({"event": "grok_web_image", "so_anh": len(data), "profile": da_dung[-1]})
    return {"created": int(time.time()), "data": data}
