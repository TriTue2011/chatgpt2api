"""Loa Phicomm R1 (AI BOX) — điều khiển THẲNG bằng IP, không cần Home Assistant.

R1 khác Cast/DLNA: nó là loa Android chạy firmware AiboxPlus với 2 kênh riêng
(rút gọn từ integration TriTue2011/R1-card):

  • HTTP bridge  cổng 2847  GET /do-cmd?cmd=<shell android>   → chỉnh âm lượng,
    chạy lệnh shell. Đáp {"code":"0","result": "..."}.
  • WebSocket    cổng 8082  {"action": ...}                    → tìm & phát nhạc
    YouTube/Zing. search_songs → search_result{songs:[{video_id,...}]};
    play_song{video_id} phát luôn (bắn-và-quên).

KHÔNG cài thư viện websocket trong image → tự cài client WS tối giản bằng socket
thuần (RFC 6455) để không phải build lại image. Mọi hàm là ĐỒNG BỘ (gọi qua
run_in_threadpool ở tầng API) và có timeout ngắn để không treo request.

Ghi chú thực địa: đường phát nhạc (WS 8082) bám sát giao thức R1-card nhưng CHƯA
kiểm thử trực tiếp trên thiết bị ở môi trường này — hàm trả lỗi rõ ràng nếu R1
không phản hồi, không báo thành công khống.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import struct
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_CTRL_PORT = 8080   # WS native (điều khiển: âm lượng, shell) — đã verify R1 thật
DEFAULT_WS_PORT = 8082     # AiboxPlus WS (nhạc) — đã verify R1 thật


# ── Điều khiển (âm lượng) qua WS native 8080 ─────────────────────────────────
# R1 192.168.1.50 mở 8080 (native) + 8082 (nhạc); cổng bridge /do-cmd 2847 ĐÓNG.
# Vì thế chỉnh âm lượng bằng WS native {"type":"set_vol"} chứ không qua HTTP.


def set_volume(host: str, level: float, *, port: int = DEFAULT_CTRL_PORT,
               max_vol: int = 15, timeout: float = 6.0) -> int:
    """Đặt âm lượng nhạc qua WS native. `level` 0..1 → chỉ số 0..max_vol.

    `level` >1 coi như đã là CHỈ SỐ tuyệt đối (vd "âm lượng 5"). Trả chỉ số."""
    if level > 1:
        idx = int(round(level))
    else:
        idx = int(round(max(0.0, min(1.0, level)) * int(max_vol)))
    idx = max(0, min(int(max_vol), idx))
    _ws_request(host, port, {"type": "set_vol", "vol": idx},
                expect_type=None, timeout=timeout, wait_reply=False)
    # Gia cố như R1-card: send_message(what=4, arg1=5, arg2=idx) để UI R1 đồng bộ.
    try:
        _ws_request(host, port,
                    {"type": "send_message", "what": 4, "arg1": 5, "arg2": idx, "obj": True},
                    expect_type=None, timeout=timeout, wait_reply=False)
    except Exception:
        pass
    return idx


def get_info(host: str, *, port: int = DEFAULT_CTRL_PORT,
             timeout: float = 6.0) -> dict[str, Any]:
    """Đọc trạng thái R1 (vol, state…) qua WS native get_info. `data` lồng JSON."""
    d = _ws_request(host, port, {"type": "get_info"}, expect_type="get_info",
                    timeout=timeout, wait_reply=True)
    data = d.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            data = {}
    return data if isinstance(data, dict) else {}


# ── WebSocket tối giản (RFC 6455, client, chỉ text) ──────────────────────────


def _ws_connect(host: str, port: int, timeout: float) -> socket.socket:
    sock = socket.create_connection((host, int(port)), timeout=timeout)
    sock.settimeout(timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    handshake = (
        f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(handshake.encode())
    # Đọc tới hết header handshake.
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(1024)
        if not chunk:
            raise RuntimeError("R1 đóng kết nối khi bắt tay WS.")
        buf += chunk
        if len(buf) > 8192:
            break
    if b" 101 " not in buf.split(b"\r\n", 1)[0]:
        raise RuntimeError("R1 từ chối nâng cấp WebSocket (không 101).")
    return sock


def _ws_send_text(sock: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    header = bytearray([0x81])  # FIN=1, opcode=text
    mask = os.urandom(4)
    n = len(payload)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", n)
    header += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes(header) + masked)


def _ws_recv_text(sock: socket.socket) -> Optional[str]:
    """Đọc 1 khung. Trả text, hoặc None nếu là close/không phải text."""
    def _read(n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = sock.recv(n - len(out))
            if not chunk:
                raise RuntimeError("R1 đóng WS giữa chừng.")
            out += chunk
        return out

    b0, b1 = _read(2)
    opcode = b0 & 0x0F
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack(">H", _read(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _read(8))[0]
    masked = bool(b1 & 0x80)
    mask = _read(4) if masked else b""
    data = _read(length) if length else b""
    if masked:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    if opcode == 0x8:      # close
        return None
    if opcode in (0x9, 0xA):  # ping/pong → bỏ qua, đọc khung kế
        return _ws_recv_text(sock)
    if opcode not in (0x1, 0x0):
        return ""
    return data.decode("utf-8", "replace")


def _ws_request(host: str, port: int, payload: dict[str, Any], *,
                expect_type: Optional[str], timeout: float,
                wait_reply: bool) -> dict[str, Any]:
    """Mở WS, gửi payload; nếu wait_reply chờ khung có type khớp expect_type."""
    sock = _ws_connect(host, port, timeout)
    try:
        _ws_send_text(sock, json.dumps(payload, ensure_ascii=False))
        if not wait_reply:
            return {"sent": True}
        for _ in range(40):
            text = _ws_recv_text(sock)
            if text is None:
                break
            text = text.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            kind = str(data.get("type") or data.get("action") or "").strip()
            if kind == "connected":
                continue  # khung bắt tay AiboxPlus
            if expect_type is None or kind == expect_type or "songs" in data or "error" in data:
                return data
        return {}
    finally:
        try:
            sock.close()
        except Exception:
            pass


def search_youtube(host: str, query: str, *, ws_port: int = DEFAULT_WS_PORT,
                   timeout: float = 12.0) -> list[dict[str, Any]]:
    """Tìm nhạc YouTube qua AiboxPlus. Trả danh sách bài (mỗi bài có video_id)."""
    data = _ws_request(host, ws_port, {"action": "search_songs", "query": query},
                       expect_type="search_result", timeout=timeout, wait_reply=True)
    songs = data.get("songs")
    return [s for s in songs if isinstance(s, dict)] if isinstance(songs, list) else []


def play_youtube(host: str, video_id: str, *, ws_port: int = DEFAULT_WS_PORT,
                 timeout: float = 8.0) -> None:
    """Phát 1 video YouTube theo id (bắn-và-quên như R1-card)."""
    _ws_request(host, ws_port, {"action": "play_song", "video_id": str(video_id)},
                expect_type=None, timeout=timeout, wait_reply=False)


def play_music(host: str, query: str, *, ws_port: int = DEFAULT_WS_PORT,
               timeout: float = 12.0) -> dict[str, Any]:
    """Tìm rồi phát bài đầu tiên khớp `query`. Trả bài đã chọn.

    Ném RuntimeError nếu không tìm được — KHÔNG báo thành công khống."""
    songs = search_youtube(host, query, ws_port=ws_port, timeout=timeout)
    if not songs:
        raise RuntimeError(f"R1 không tìm thấy bài nào cho '{query}'.")
    top = songs[0]
    vid = str(top.get("video_id") or top.get("id") or "").strip()
    if not vid:
        raise RuntimeError("Kết quả tìm nhạc R1 thiếu video_id.")
    play_youtube(host, vid, ws_port=ws_port, timeout=timeout)
    return top


def media_action(host: str, action: str, *, ws_port: int = DEFAULT_WS_PORT,
                 timeout: float = 6.0) -> None:
    """stop | pause | play | next | previous trên kênh nhạc AiboxPlus."""
    alias = {"resume": "play"}.get(action, action)
    if alias not in ("play", "pause", "stop", "next", "previous"):
        raise RuntimeError(f"Lệnh R1 không hỗ trợ: {action}")
    _ws_request(host, ws_port, {"action": alias}, expect_type=None,
                timeout=timeout, wait_reply=False)


def test_reachable(host: str, *, port: int = DEFAULT_CTRL_PORT,
                   timeout: float = 4.0) -> tuple[bool, str]:
    """Thử chạm cổng điều khiển R1 (TCP)."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, f"Kết nối được R1 {host}:{port}"
    except Exception as exc:
        return False, f"Không chạm tới R1 {host}:{port} ({str(exc)[:80]})"
