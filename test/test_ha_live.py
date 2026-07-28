"""Gương trạng thái HA thời gian thực (services/ha_live.py).

Hai phần dễ vỡ nhất được chốt ở đây:

1. _patch_state — vá thẳng vào ha_client._state_cache: sai index một nhịp là
   từ đó về sau gương ghi đè NHẦM entity, bot trả lời sai còn tệ hơn cache cũ.
2. _WS.recv_text — kết nối sống dài: thiếu pong là HA ngắt sau vài phút,
   thiếu ghép mảnh là frame JSON to vỡ giữa chừng. (_ws_fetch_exposed cũ chỉ
   sống 4 frame nên chưa từng cần hai thứ này.)
"""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import ha_client as hc  # noqa: E402
from services import ha_live  # noqa: E402


def _st(eid: str, state: str) -> dict:
    return {"entity_id": eid, "state": state, "attributes": {}}


class PatchStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._cache, self._ts = hc._state_cache, hc._state_cache_ts
        hc._state_cache = [_st("light.a", "off"), _st("sensor.b", "1"), _st("fan.c", "on")]
        hc._state_cache_ts = 0.0
        self.index = {"light.a": 0, "sensor.b": 1, "fan.c": 2}

    def tearDown(self) -> None:
        hc._state_cache, hc._state_cache_ts = self._cache, self._ts

    def test_update_existing(self) -> None:
        ha_live._patch_state(_st("sensor.b", "5"), "sensor.b", self.index)
        self.assertEqual(hc._state_cache[1]["state"], "5")
        self.assertGreater(hc._state_cache_ts, 0, "ts phải được bơm để cache được coi là tươi")

    def test_add_new_entity(self) -> None:
        ha_live._patch_state(_st("switch.d", "on"), "switch.d", self.index)
        self.assertEqual(len(hc._state_cache), 4)
        self.assertEqual(self.index["switch.d"], 3)
        # entity mới phải đọc lại được qua chính index
        ha_live._patch_state(_st("switch.d", "off"), "switch.d", self.index)
        self.assertEqual(hc._state_cache[3]["state"], "off")
        self.assertEqual(len(hc._state_cache), 4, "update không được nhân bản")

    def test_remove_shifts_index(self) -> None:
        """Xoá entity giữa danh sách: mọi index phía sau phải trượt theo."""
        ha_live._patch_state(None, "sensor.b", self.index)
        self.assertEqual([s["entity_id"] for s in hc._state_cache], ["light.a", "fan.c"])
        self.assertNotIn("sensor.b", self.index)
        self.assertEqual(self.index["fan.c"], 1, "index sau vị trí xoá phải -1")
        # và vá tiếp fan.c phải trúng đúng chỗ mới
        ha_live._patch_state(_st("fan.c", "off"), "fan.c", self.index)
        self.assertEqual(hc._state_cache[1]["state"], "off")

    def test_stale_index_falls_back_to_append_not_corrupt(self) -> None:
        """Index lệch (trỏ vào entity khác) → không được ghi đè nhầm."""
        self.index["sensor.b"] = 0  # cố tình sai: trỏ vào light.a
        ha_live._patch_state(_st("sensor.b", "9"), "sensor.b", self.index)
        self.assertEqual(hc._state_cache[0]["entity_id"], "light.a",
                         "entity khác không được bị ghi đè")
        self.assertEqual(hc._state_cache[-1]["state"], "9")


def _frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    """Frame server→client (KHÔNG mask) như HA gửi."""
    h = bytearray([(0x80 if fin else 0) | opcode])
    n = len(payload)
    if n < 126:
        h.append(n)
    elif n < 65536:
        h.append(126); h += struct.pack(">H", n)
    else:
        h.append(127); h += struct.pack(">Q", n)
    return bytes(h) + payload


class WsFramingTests(unittest.TestCase):
    def _ws_over(self, server_bytes: bytes) -> ha_live._WS:
        """Dựng _WS quanh socketpair, KHÔNG qua handshake HTTP."""
        a, b = socket.socketpair()
        ws = ha_live._WS.__new__(ha_live._WS)   # bỏ __init__ (handshake)
        ws.sock = a
        ws.buf = bytearray()
        b.sendall(server_bytes)
        self._peer = b
        return ws

    def test_reassembles_fragmented_text(self) -> None:
        data = json.dumps({"type": "event", "x": "y" * 200}).encode()
        ws = self._ws_over(
            _frame(0x1, data[:50], fin=False) + _frame(0x0, data[50:], fin=True))
        self.assertEqual(ws.recv_text(), data.decode())

    def test_ping_gets_ponged_and_skipped(self) -> None:
        msg = b'{"type":"pong-test"}'
        ws = self._ws_over(_frame(0x9, b"ka") + _frame(0x1, msg))
        self.assertEqual(ws.recv_text(), msg.decode())
        # server (peer) phải nhận lại một pong frame (opcode 0xA, masked)
        self._peer.settimeout(2)
        reply = self._peer.recv(64)
        self.assertEqual(reply[0] & 0x0F, 0xA, "ping phải được trả lời bằng pong")

    def test_close_frame_raises(self) -> None:
        ws = self._ws_over(_frame(0x8, b""))
        with self.assertRaises(RuntimeError):
            ws.recv_text()

    def test_large_frame_16bit_length(self) -> None:
        data = ("A" * 70000).encode()          # dùng nhánh length 64-bit
        ws = self._ws_over(_frame(0x1, data))
        self.assertEqual(len(ws.recv_text()), 70000)


class LifecycleTests(unittest.TestCase):
    def test_start_respects_disable_flag(self) -> None:
        from unittest import mock
        from services.config import config
        with mock.patch.dict(config.data, {"home_assistant": {
                "url": "http://x:8123", "token": "t", "live_mirror": False}}):
            self.assertFalse(ha_live.start(), "live_mirror=false thì không được chạy")

    def test_start_requires_url_and_token(self) -> None:
        from unittest import mock
        from services.config import config
        with mock.patch.dict(config.data, {"home_assistant": {"url": "", "token": ""}}):
            self.assertFalse(ha_live.start())


if __name__ == "__main__":
    unittest.main()
