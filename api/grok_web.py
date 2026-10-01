"""Grok web miễn phí — cùng kiểu gemini_web_api, không mở trình duyệt mỗi lần chat.

Gemini (`api/gemini_web.py`) lấy cookie từ hồ sơ đã đăng nhập (captcha-solver)
hoặc từ cookie dán trong cấu hình, rồi thư viện Python tự gọi. Đường này làm
đúng việc đó cho grok.com:

  1. Cookie từ ``GET /v1/grok-web/{profile}/session`` của hồ sơ đã onboard.
  2. Không có hồ sơ thì đọc ``data/grok_web_cookies.json`` (đường lùi, như
     ``psid`` của Gemini).
  3. Gửi chat bằng websocket ``wss://grok.com/ws/mgw/``, trình tự
     ``session.create`` → ``conversation.item.create`` → ``response.create``.
     Đo 01/10/2026 trên chính container này: một tin tạm "ping" nhận "pong".

Không khởi chạy Firefox hay Chrome trong lúc chat. Phiên phải đã được tạo
trước (onboard, hoặc file cookie).

Ba điểm chốt 01/10/2026, khác Gemini Web API:

* Web UI không có thẻ thêm tài khoản Grok. Gemini thêm hồ sơ ở Cài đặt
  (thẻ Gemini Web API) và vòng xoay trên trang Tài khoản. Onboard Chrome
  của grok.com trên máy này bị Cloudflare chặn, nên không dùng thẻ đó.
  Phiên đang chạy là một file ``data/grok_web_cookies.json``, ghi từ
  Firefox đã đăng nhập trên chính máy này.
* Hết hạn không tự lấy lại. Gemini gọi ``relogin-via-google``.
  ``cf_clearance`` của grok.com không đúc lại bằng solver.
* Không hâm nóng. Mỗi tin mở websocket mới. Gemini giữ ``GeminiClient``
  ấm trong ``services/web_prewarmer.py``.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
import time
import uuid
from typing import Any, Iterator

import requests

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


def _config():
    from services.config import config
    return config


def _logger():
    from utils.log import logger
    return logger


def _cfg() -> dict[str, Any]:
    return (_config().data.get("providers") or {}).get("grok_web") or {}


def _cookie_file():
    from services.config import DATA_DIR
    return DATA_DIR / "grok_web_cookies.json"


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


def _solver_cfg() -> dict[str, str]:
    providers = _config().data.get("providers") or {}
    for name in ("grok_web", "gemini_web_api", "gemini_web", "flow"):
        c = providers.get(name) or {}
        raw = str(c.get("captcha_solver_url") or "").strip()
        if raw:
            from services.captcha import captcha_base
            return {"url": captcha_base(raw), "api_key": str(c.get("captcha_solver_api_key") or "")}
    return {"url": "", "api_key": ""}


def _profiles() -> list[str]:
    cfg = _cfg()
    found: list[str] = []
    for entry in (cfg.get("accounts") or []):
        if isinstance(entry, dict):
            p = str(entry.get("profile") or "").strip()
            if p and p not in found:
                found.append(p)
    profs = cfg.get("profiles")
    if isinstance(profs, list):
        for p in profs:
            p = str(p).strip()
            if p and p not in found:
                found.append(p)
    try:
        from services.account_service import account_group, account_service
        for acc in account_service.list_accounts():
            if not isinstance(acc, dict) or account_group(acc) != "grok_web":
                continue
            p = str(acc.get("profile") or acc.get("email") or acc.get("name") or "").strip()
            if p and p not in found:
                found.append(p)
    except Exception:
        pass
    return [p for p in found if not p.endswith("-default") and not p.endswith("_default")]


def _fetch_solver(profile: str) -> dict[str, str]:
    sc = _solver_cfg()
    if not sc["url"] or not profile:
        return {}
    headers = {"Authorization": f"Bearer {sc['api_key']}"} if sc["api_key"] else {}
    try:
        r = requests.get(
            f"{sc['url']}/v1/grok-web/{profile}/session",
            headers=headers,
            timeout=20,
        )
        try:
            if r.status_code != 200:
                _logger().info({
                    "event": "grok_web_cookie_bo",
                    "profile": profile,
                    "status": r.status_code,
                })
                return {}
            cookies = (r.json() or {}).get("cookies") or {}
            if cookies.get("sso"):
                return {str(k): str(v) for k, v in cookies.items() if v}
        finally:
            r.close()
    except Exception as exc:
        _logger().info({"event": "grok_web_cookie_loi", "profile": profile, "error": str(exc)[:120]})
    return {}


def _file_cookies() -> dict[str, str]:
    path = _cookie_file()
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v}


def tai_cookie() -> dict[str, str]:
    """Hồ sơ solver trước, file cookie sau. Cần có ``sso``."""
    for profile in _profiles():
        cookies = _fetch_solver(profile)
        if cookies.get("sso"):
            return cookies
    cookies = _file_cookies()
    if cookies.get("sso"):
        return cookies
    raise RuntimeError(
        "Chưa có phiên Grok web. Onboard một hồ sơ grok_web, hoặc đặt cookie "
        "vào data/grok_web_cookies.json")


def _ws_send(tls, obj: dict) -> None:
    data = json.dumps(obj, separators=(",", ":")).encode()
    mask = os.urandom(4)
    header = bytearray([0x81])
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


def _ws_recv(tls, buf: bytes) -> tuple[tuple[int, bytes] | None, bytes]:
    while len(buf) < 2:
        chunk = tls.recv(8192)
        if not chunk:
            return None, buf
        buf += chunk
    opcode = buf[0] & 0x0F
    ln = buf[1] & 0x7F
    i = 2
    if ln == 126:
        while len(buf) < 4:
            buf += tls.recv(8192)
        ln = struct.unpack("!H", buf[2:4])[0]
        i = 4
    elif ln == 127:
        while len(buf) < 10:
            buf += tls.recv(8192)
        ln = struct.unpack("!Q", buf[2:10])[0]
        i = 10
    while len(buf) < i + ln:
        chunk = tls.recv(8192)
        if not chunk:
            break
        buf += chunk
    return (opcode, buf[i:i + ln]), buf[i + ln:]


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


def stream_chat(prompt: str, mode: str, cookies: dict[str, str] | None = None) -> Iterator[str]:
    """Sinh từng mảnh chữ. Phiên tạm, không ghi vào lịch sử grok.com."""
    cookies = dict(cookies or tai_cookie())
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
        tls.settimeout(25)
        tls.sendall((
            f"GET /ws/mgw/?uid={uid} HTTP/1.1\r\n"
            "Host: grok.com\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            "Origin: https://grok.com\r\n"
            "User-Agent: Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0\r\n"
            "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8\r\n"
            f"Cookie: {jar}\r\n\r\n"
        ).encode())
        data = b""
        while b"\r\n\r\n" not in data:
            data += tls.recv(8192)
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
        deadline = time.time() + 45
        while time.time() < deadline:
            frame, buf = _ws_recv(tls, buf)
            if not frame:
                break
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
