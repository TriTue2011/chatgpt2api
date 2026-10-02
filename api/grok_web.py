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
from typing import Any, Callable, Iterator, TypeVar

T = TypeVar("T")

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


def chuoi_che_do(model: str) -> list[str]:
    """Các mode thử LẦN LƯỢT. «auto» phía c2a: fast trước; mọi tài khoản hết lượt fast thì hạ sang mode «auto» của
    chính Grok — chủ máy 02/10/2026: "hết fast hạ xuống 4". Đo cùng ngày trên tài khoản miễn phí: fast còn 0/30 lượt
    mà mode auto vẫn trả lời và không trừ hạn mức grok-3 lẫn grok-4; mode expert / grok-4 thì bị «model_unavailable»."""
    ten = str(model or "").strip().lower()
    return ["fast", "auto"] if ten in ("", "auto") else [che_do(ten)]


def _het_luot(exc: Exception) -> bool:
    return "usage_limit" in str(exc)


def stream_theo_chuoi(prompt: str, modes: list[str]) -> Iterator[str]:
    """`stream_chat` theo từng mode; mode trước hết lượt ở MỌI tài khoản (chưa gửi chữ nào) thì sang mode sau."""
    for i, mode in enumerate(modes):
        da_gui = False
        try:
            for manh in stream_chat(prompt, mode):
                da_gui = True
                yield manh
            return
        except Exception as exc:
            if da_gui or i == len(modes) - 1 or not _het_luot(exc):
                raise
            _logger().warning({"event": "grok_web_ha_che_do", "tu": mode, "sang": modes[i + 1]})


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


def stream_chat(prompt: str, mode: str, cookies: dict[str, str] | None = None) -> Iterator[str]:
    """Sinh từng mảnh chữ. Xoay tài khoản theo thứ tự ưu tiên (như Flow): tài khoản hết phiên thì mở lại hồ sơ
    Firefox của nó MỘT lần, vẫn hỏng thì sang tài khoản kế. Chỉ đổi khi CHƯA gửi chữ nào — thử lại sau khi đã gửi
    nửa câu thì người gọi nhận câu trả lời lặp đầu."""
    if cookies is not None:
        yield from _stream_chat(prompt, mode, cookies)
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
                    for manh in _stream_chat(prompt, mode, tai_cookie(p)):
                        da_gui = True
                        yield manh
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


def _mo_ws(cookies: dict[str, str], duong: str):
    """Mở websocket ``wss://grok.com<duong>`` bằng cookie; trả (tls, phần dữ liệu đọc thừa sau bắt tay)."""
    jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
    key = base64.b64encode(os.urandom(16)).decode()
    raw = socket.create_connection(("grok.com", 443), timeout=20)
    tls = ssl.create_default_context().wrap_socket(raw, server_hostname="grok.com")
    try:
        tls.settimeout(_IM_TOI_DA)
        tls.sendall((
            f"GET {duong} HTTP/1.1\r\n"
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
        return tls, rest
    except BaseException:
        tls.close()
        raise


def _stream_chat(prompt: str, mode: str, cookies: dict[str, str]) -> Iterator[str]:
    """Một lượt gửi. Phiên tạm, không ghi vào lịch sử grok.com."""
    cookies = dict(cookies)
    if not cookies.get("sso"):
        raise RuntimeError("Cookie Grok web thiếu sso")
    uid = _user_id(cookies)
    if not uid:
        raise RuntimeError("Không lấy được user id của phiên Grok web")
    if "x-userid" not in cookies:
        cookies["x-userid"] = uid
    tls, rest = _mo_ws(cookies, f"/ws/mgw/?uid={uid}")
    try:
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
            if kind == "response.grok.output":
                # Đo 02/10/2026: hết lượt thì Grok gửi `output.stream_error` (usage_limit_reached …) rồi kết thúc lượt
                # «incomplete» — bỏ qua thì người dùng nhận nửa câu như đã xong («3+4» → «5», «12 nhân 3» → «12»).
                out = ev.get("output") if isinstance(ev.get("output"), dict) else {}
                loi_luong = out.get("stream_error") if isinstance(out.get("stream_error"), dict) else None
                if loi_luong:
                    raise RuntimeError(f"Grok web: {loi_luong.get('kind') or 'stream_error'}: "
                                       f"{str(loi_luong.get('message') or '')[:160]}")
            if kind == "response.done":
                resp = ev.get("response") if isinstance(ev.get("response"), dict) else {}
                trang_thai = str(resp.get("status") or "completed")
                if trang_thai != "completed":
                    ly_do = (resp.get("status_details") or {}).get("reason") if isinstance(
                        resp.get("status_details"), dict) else ""
                    raise RuntimeError(f"Grok web dừng giữa câu trả lời: {trang_thai} ({ly_do or 'không rõ'})")
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
    modes = chuoi_che_do(model)
    shown = "grok/auto" if len(modes) > 1 else f"grok/{modes[0]}"
    _logger().info({"event": "grok_web_request", "model": shown, "chars": len(prompt)})
    if stream:
        from services.protocol.openai_v1_chat_complete import completion_chunk
        cid = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())

        def _gen() -> Iterator[dict[str, Any]]:
            started = False
            for piece in stream_theo_chuoi(prompt, modes):
                delta: dict[str, Any] = {"content": piece}
                if not started:
                    delta = {"role": "assistant", "content": piece}
                    started = True
                yield completion_chunk(shown, delta, None, cid, created)
            yield completion_chunk(shown, {}, "stop", cid, created)

        return _gen()
    text = "".join(stream_theo_chuoi(prompt, modes))
    from services.protocol.openai_v1_chat_complete import completion_response
    return completion_response(shown, text, messages=messages)


class GrokTuChoi(RuntimeError):
    """Grok từ chối nội dung (kiểm duyệt) — tài khoản khác cũng sẽ từ chối, đừng xoay tài khoản tốn lượt."""


def theo_tai_khoan(lam: Callable[[str, dict[str, str]], T], viec: str) -> tuple[T, str]:
    """``lam(profile, cookies)`` lần lượt trên các tài khoản đang bật (thứ tự ưu tiên, như `stream_chat`): hết phiên
    thì mở lại hồ sơ Firefox MỘT lần, vẫn hỏng hoặc hết lượt thì sang tài khoản kế. Trả (kết quả, profile đã dùng)."""
    from api.grok_firefox import dang_bat, lam_moi
    ds = dang_bat()
    if not ds:
        raise RuntimeError("Chưa có tài khoản Grok nào đang bật — thêm và đăng nhập ở Cài đặt › Grok.")
    loi: list[str] = []
    for acc in ds:
        p = acc["profile"]
        _ghi_tai_khoan(acc, viec)
        for lan in range(2):
            try:
                return lam(p, tai_cookie(p)), p
            except GrokTuChoi:
                raise
            except Exception as exc:
                if not lan and _la_loi_phien(exc):
                    lam_moi(p)
                    continue
                loi.append(f"{acc.get('label') or p}: {str(exc)[:120]}")
                _logger().warning({"event": "grok_web_tai_khoan_hong", "profile": p, "viec": viec,
                                   "error": str(exc)[:160]})
                break
    raise RuntimeError("Grok web: mọi tài khoản đều hỏng — " + "; ".join(loi))


#: Tỉ lệ khung Grok Imagine nhận (grok2api `resolveImageAspectRatio`).
_TI_LE = (("1:1", 1.0), ("16:9", 16 / 9), ("9:16", 9 / 16), ("4:3", 4 / 3), ("3:4", 3 / 4), ("3:2", 3 / 2),
          ("2:3", 2 / 3))


def ti_le(size: str | None) -> str:
    """``size`` kiểu OpenAI ("1792x1024") hay tỉ lệ sẵn ("16:9") → tỉ lệ Grok gần nhất; không rõ thì "auto"."""
    chu = str(size or "").strip().lower()
    if any(chu == t for t, _ in _TI_LE):
        return chu
    try:
        w, h = (int(x) for x in chu.split("x"))
        return min(_TI_LE, key=lambda m: abs(m[1] - w / h))[0]
    except (ValueError, ZeroDivisionError):
        return "auto"


def _byte_anh(o: dict[str, Any], cookies: dict[str, str]) -> bytes:
    if o["blob"]:
        return base64.b64decode(o["blob"].split(",")[-1])
    import urllib.request
    url = o["url"] if o["url"].startswith("http") else f"https://assets.grok.com/{o['url'].lstrip('/')}"
    hd = {"Referer": "https://grok.com/",
          "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0"}
    if "assets.grok.com" in url:     # ảnh riêng của tài khoản: không cookie thì 403
        hd["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    with urllib.request.urlopen(urllib.request.Request(url, headers=hd), timeout=60) as resp:
        return resp.read()


def _imagine(prompt: str, n: int, ratio: str, cookies: dict[str, str], *, pro: bool = False) -> list[bytes]:
    """Vẽ bằng websocket của trang Imagine (``/ws/imagine/listen``), như grok2api `generateWSImageAttempt`.

    Đo 02/10/2026: nhờ khung chat (``/ws/mgw/``) vẽ thì Grok nhận ĐÚNG prompt mà trả ảnh phong cảnh có sẵn không liên
    quan — «voi xanh trong tuyết» ra rừng thu, «xe đạp xanh» ra hồ núi, cùng một tấm rừng thu ở hai tài khoản. Đường
    Imagine vẽ đúng trong ~5 giây. Máy chủ gửi ``image`` (``percentage_complete`` < 100 là ảnh nháp) rồi ``json``
    ``current_status=completed`` (có thể kèm ``moderated``) cho từng ảnh."""
    tls, buf = _mo_ws(cookies, "/ws/imagine/listen")
    anh: dict[str, dict[str, Any]] = {}
    try:
        def gui(noi_dung: dict[str, Any]) -> None:
            _ws_send(tls, {"type": "conversation.item.create", "timestamp": int(time.time() * 1000),
                           "item": {"type": "message", "content": [noi_dung]}})
        gui({"type": "reset"})
        gui({"requestId": uuid.uuid4().hex, "text": prompt, "type": "input_text", "properties": {
            "section_count": 0, "is_kids_mode": False, "enable_nsfw": False, "skip_upsampler": False,
            "enable_side_by_side": True, "is_initial": False, "aspect_ratio": ratio, "enable_pro": pro,
            "num_generations": n}})
        while True:
            frame, buf = _ws_recv(tls, buf)
            if not frame or frame[0] == 8:
                break
            if frame[0] != 1:
                continue
            try:
                m = json.loads(frame[1])
            except ValueError:
                continue
            kind = m.get("type")
            if kind == "error":
                # đo 02/10/2026: hết lượt vẽ → {"type": "error", "err_code": "rate_limit_exceeded", "err_msg": …}
                raise RuntimeError(f"Grok Imagine: {m.get('err_code') or 'error'}: {str(m.get('err_msg') or '')[:160]}")
            id_ = str(m.get("image_id") or m.get("job_id") or m.get("id") or "")
            if kind not in ("image", "json") or not id_:
                continue
            o = anh.setdefault(id_, {"xong": False, "kiem_duyet": False, "blob": "", "url": ""})
            pct = m.get("percentage_complete")
            if kind == "image" and (pct is None or float(pct) >= 100):
                o["blob"], o["url"] = str(m.get("blob") or ""), str(m.get("url") or "")
            elif kind == "json" and m.get("current_status") == "completed":
                o["xong"], o["kiem_duyet"] = True, bool(m.get("moderated"))
                o["url"] = o["url"] or str(m.get("url") or "")
            xong = [o for o in anh.values() if o["xong"]]
            if len(xong) >= n and all(o["kiem_duyet"] or o["blob"] or o["url"] for o in xong):
                break
    finally:
        tls.close()
    dung = [o for o in anh.values() if o["xong"] and not o["kiem_duyet"] and (o["blob"] or o["url"])]
    if not dung:
        if any(o["kiem_duyet"] for o in anh.values()):
            raise GrokTuChoi("Grok từ chối vẽ nội dung này (kiểm duyệt)")
        raise RuntimeError("Grok Imagine kết thúc mà không trả ảnh nào")
    return [_byte_anh(o, cookies) for o in dung[:n]]


def _ve_net_nhat(prompt: str, n: int, ratio: str, cookies: dict[str, str]) -> list[bytes]:
    """Ưu tiên Imagine PRO; tài khoản không còn đủ lượt cho Pro thì vẽ thường NGAY trên tài khoản đó.

    Chủ máy 02/10/2026: "tạo ảnh grok bị mờ, tăng độ phân giải cao nhất". Đo cùng ngày, cùng prompt, khung 16:9:
    thường và Pro đều 1280×720 (kênh Imagine không cho chọn cỡ lớn hơn) nhưng Pro nét gần gấp đôi (độ lệch biên
    43,3 so với 23,8; 398 so với 250 KB), 18 giây so với 7 giây; Pro tốn 3 lượt, thường 1 lượt (lượt «Ảnh Pro»
    là hạn mức vẽ chung, tài khoản miễn phí 8 lượt/ngày)."""
    try:
        return _imagine(prompt, n, ratio, cookies, pro=True)
    except RuntimeError as exc:
        if "rate_limit" not in str(exc):
            raise
        return _imagine(prompt, n, ratio, cookies)


def luu_media(byte: bytes, base_url: str, response_format: str = "url") -> dict[str, str]:
    """Lưu vào thư mục ảnh (``/images/grok/...``) như Gemini Web API; trả mục ``data`` kiểu OpenAI."""
    from services.config import config
    duoi = "png" if byte[:4] == b"\x89PNG" else "mp4" if byte[4:8] == b"ftyp" else "jpg"
    thu_muc = config.images_dir / "grok"
    thu_muc.mkdir(parents=True, exist_ok=True)
    ten = f"{uuid.uuid4().hex}.{duoi}"
    (thu_muc / ten).write_bytes(byte)
    if response_format == "b64_json":
        return {"b64_json": base64.b64encode(byte).decode("ascii")}
    return {"url": f"{base_url.rstrip('/')}/images/grok/{ten}" if base_url else f"/images/grok/{ten}"}


def handle_grok_web_image_gen(prompt: str, n: int = 1, response_format: str = "url",
                              base_url: str = "", size: str | None = None) -> dict[str, Any]:
    """/v1/images/generations cho ``grok/imagine`` — model vẽ của trang Imagine (xem `_imagine`)."""
    n = max(1, min(int(n or 1), 4))
    ds, p = theo_tai_khoan(lambda _p, ck: _ve_net_nhat(prompt, n, ti_le(size), ck), "imagine")
    data = [luu_media(b, base_url, response_format) for b in ds]
    _logger().info({"event": "grok_web_image", "so_anh": len(data), "profile": p})
    return {"created": int(time.time()), "data": data}
