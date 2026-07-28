"""Gương trạng thái Home Assistant THỜI GIAN THỰC qua WebSocket.

Vấn đề nó giải: cache states của ha_client sống theo ``refresh_interval``
(đang cấu hình 3600s) — bot từng trả lời "Nhà: 0, không có ai" bằng số cũ
cả tiếng trong khi cảm biến đang báo 1 người (đo 2026-07-28). Poll nhanh hơn
thì tốn; đằng nào HA cũng CÓ kênh đẩy: WebSocket ``subscribe_events``.

Cách chạy: một luồng nền duy nhất giữ kết nối ws://<ha>/api/websocket,
subscribe ``state_changed``; mỗi event vá THẲNG vào ``ha_client._state_cache``
(cùng lock) và bơm ``_state_cache_ts``. Nhờ đó MỌI đường đọc sẵn có —
fast-path, home_status, persona context, MCP ha_helper — thấy dữ liệu của
đúng khoảnh khắc hỏi mà không đổi một dòng code nào ở phía đọc.

An toàn khi hỏng: gương chết ⇒ ts không được bơm nữa ⇒ get_states() tự rơi
về REST như trước. Tệ nhất bằng hiện trạng, không bao giờ tệ hơn.

Không dependency mới — raw WebSocket bằng stdlib, cùng kiểu
``_ws_fetch_exposed`` đã chạy ổn; khác ở chỗ kết nối SỐNG DÀI nên có thêm
ping/pong, close frame, ghép mảnh, và nối lại có backoff.

Tắt/bật: ``home_assistant.live_mirror`` (mặc định BẬT khi có url+token).
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
import time
from typing import Any, Optional

from utils.log import logger

_thread: Optional[threading.Thread] = None
_started_lock = threading.Lock()
_stop = threading.Event()

# Số liệu cho /health + debug.
_stats = {
    "connected": False,
    "events": 0,
    "last_event_ts": 0.0,
    "reconnects": 0,
    "last_error": "",
}

_BACKOFF_START = 5.0
_BACKOFF_CAP = 120.0
# Không nhận được gì (kể cả pong) quá chừng này → coi là kết nối chết.
_IDLE_TIMEOUT = 70.0
_PING_EVERY = 25.0


def stats() -> dict[str, Any]:
    return dict(_stats)


def _enabled() -> bool:
    try:
        from services.config import config
        ha = config.data.get("home_assistant") or {}
        if not (str(ha.get("url") or "").strip() and str(ha.get("token") or "").strip()):
            return False
        return bool(ha.get("live_mirror", True))
    except Exception:
        return False


class _WS:
    """Khung WebSocket tối thiểu cho kết nối SỐNG DÀI (RFC6455, client side).

    _ws_fetch_exposed chỉ cần 4 frame rồi đóng nên bỏ qua control frame được;
    ở đây HA sẽ ping định kỳ và một frame JSON to có thể bị chẻ nhỏ — thiếu
    ping/pong + ghép mảnh là kết nối chết âm thầm sau vài phút.
    """

    def __init__(self, host: str, port: int, path: str = "/api/websocket",
                 timeout: float = 10.0) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(_IDLE_TIMEOUT)
        self.buf = bytearray()
        self.sock.sendall((
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("ws handshake closed")
            resp += chunk
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            raise RuntimeError("ws handshake refused: %r" % resp[:80])

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def _need(self, n: int) -> None:
        while len(self.buf) < n:
            c = self.sock.recv(16384)
            if not c:
                raise RuntimeError("ws closed")
            self.buf.extend(c)

    def _send_raw(self, opcode: int, payload: bytes) -> None:
        m = os.urandom(4)
        h = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            h.append(0x80 | n)
        elif n < 65536:
            h.append(0x80 | 126); h += struct.pack(">H", n)
        else:
            h.append(0x80 | 127); h += struct.pack(">Q", n)
        h += m
        self.sock.sendall(bytes(h) + bytes(b ^ m[i % 4] for i, b in enumerate(payload)))

    def send_json(self, obj: dict) -> None:
        self._send_raw(0x1, json.dumps(obj).encode())

    def ping(self) -> None:
        self._send_raw(0x9, b"ka")

    def recv_text(self) -> str:
        """Một MESSAGE text hoàn chỉnh — tự ghép mảnh, tự trả lời ping."""
        parts: list[bytes] = []
        while True:
            self._need(2)
            b0, b1 = self.buf[0], self.buf[1]
            fin, opcode = b0 & 0x80, b0 & 0x0F
            ln = b1 & 0x7F
            idx = 2
            if ln == 126:
                self._need(4); ln = struct.unpack(">H", bytes(self.buf[2:4]))[0]; idx = 4
            elif ln == 127:
                self._need(10); ln = struct.unpack(">Q", bytes(self.buf[2:10]))[0]; idx = 10
            self._need(idx + ln)
            payload = bytes(self.buf[idx:idx + ln])
            del self.buf[:idx + ln]

            if opcode == 0x9:            # ping → pong, đợi frame kế
                self._send_raw(0xA, payload)
                continue
            if opcode == 0xA:            # pong (trả lời ping của ta) → bỏ qua
                continue
            if opcode == 0x8:            # close
                raise RuntimeError("ws close frame")
            if opcode in (0x1, 0x0):     # text / continuation
                parts.append(payload)
                if fin:
                    return b"".join(parts).decode("utf-8", "replace")
                continue
            # binary hoặc opcode lạ — HA không dùng, bỏ qua cho an toàn
            continue


def _patch_state(new_state: dict[str, Any] | None, entity_id: str,
                 index: dict[str, int]) -> None:
    """Vá MỘT entity vào ha_client._state_cache dưới lock của chính nó."""
    from services import ha_client as hc
    with hc._state_cache_lock:
        cache = hc._state_cache
        pos = index.get(entity_id, -1)
        if new_state is None:
            # Entity bị xoá khỏi HA → gỡ khỏi gương, dựng lại index phía sau.
            if 0 <= pos < len(cache) and cache[pos].get("entity_id") == entity_id:
                del cache[pos]
                for k, v in list(index.items()):
                    if v > pos:
                        index[k] = v - 1
                index.pop(entity_id, None)
        elif 0 <= pos < len(cache) and cache[pos].get("entity_id") == entity_id:
            cache[pos] = new_state
        else:
            index[entity_id] = len(cache)
            cache.append(new_state)
        hc._state_cache_ts = time.time()


def _resync(index: dict[str, int]) -> None:
    """Nạp lại TOÀN BỘ states qua REST (nguồn sự thật khi vừa (re)connect)."""
    from services import ha_client as hc
    data = hc.get_states(use_cache=False)
    index.clear()
    with hc._state_cache_lock:
        for i, st in enumerate(hc._state_cache):
            eid = str(st.get("entity_id") or "")
            if eid:
                index[eid] = i
    logger.info({"event": "ha_live_resync", "entities": len(data)})


def _run_once(index: dict[str, int]) -> None:
    """Một phiên kết nối: auth → subscribe → đọc event tới khi đứt."""
    from services.config import config
    ha = config.data.get("home_assistant") or {}
    url = str(ha.get("url") or "").rstrip("/")
    token = str(ha.get("token") or "")
    netloc = url.split("//", 1)[-1].split("/")[0]
    host = netloc.split(":")[0]
    port = int(netloc.rsplit(":", 1)[1]) if ":" in netloc else 8123

    ws = _WS(host, port)
    try:
        first = json.loads(ws.recv_text())
        if first.get("type") != "auth_required":
            raise RuntimeError("unexpected first frame: %s" % first.get("type"))
        ws.send_json({"type": "auth", "access_token": token})
        auth = json.loads(ws.recv_text())
        if auth.get("type") != "auth_ok":
            raise RuntimeError("auth failed: %s" % auth.get("type"))

        ws.send_json({"id": 1, "type": "subscribe_events",
                      "event_type": "state_changed"})
        sub = json.loads(ws.recv_text())
        if not (sub.get("id") == 1 and sub.get("success")):
            raise RuntimeError("subscribe failed: %r" % str(sub)[:120])

        # Kết nối chuẩn rồi mới resync — lấp mọi thay đổi lọt khe lúc đứt.
        _resync(index)
        _stats["connected"] = True
        logger.info({"event": "ha_live_connected", "host": host})

        last_ping = time.time()
        while not _stop.is_set():
            if time.time() - last_ping > _PING_EVERY:
                ws.ping()
                last_ping = time.time()
            try:
                raw = ws.recv_text()
            except socket.timeout:
                raise RuntimeError("ws idle timeout")
            msg = json.loads(raw)
            if msg.get("type") != "event":
                continue
            data = (msg.get("event") or {}).get("data") or {}
            eid = str(data.get("entity_id") or "")
            if not eid:
                continue
            _patch_state(data.get("new_state"), eid, index)
            _stats["events"] += 1
            _stats["last_event_ts"] = time.time()
    finally:
        _stats["connected"] = False
        ws.close()


def _run_forever() -> None:
    index: dict[str, int] = {}
    backoff = _BACKOFF_START
    while not _stop.is_set():
        try:
            _run_once(index)
            backoff = _BACKOFF_START  # phiên sống tử tế rồi mới đứt → reset
        except Exception as exc:
            _stats["last_error"] = str(exc)[:160]
            logger.warning({"event": "ha_live_disconnected",
                            "error": str(exc)[:160], "retry_in_s": round(backoff)})
        if _stop.is_set():
            return
        _stats["reconnects"] += 1
        _stop.wait(backoff)
        backoff = min(backoff * 2, _BACKOFF_CAP)


def start() -> bool:
    """Khởi động gương (idempotent). Trả True nếu đang/đã chạy."""
    global _thread
    if not _enabled():
        return False
    with _started_lock:
        if _thread is not None and _thread.is_alive():
            return True
        _stop.clear()
        _thread = threading.Thread(target=_run_forever, daemon=True,
                                   name="ha-live-mirror")
        _thread.start()
        logger.info({"event": "ha_live_started"})
        return True


def stop() -> None:
    _stop.set()
