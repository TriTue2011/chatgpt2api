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
        # macOS có socket buffer nhỏ hơn payload 70 KB bên dưới. Gửi đồng bộ ở
        # đây sẽ chặn trước khi `recv_text()` có cơ hội đọc; mô phỏng đúng server
        # thật bằng một luồng gửi song song.
        sender = threading.Thread(target=b.sendall, args=(server_bytes,), daemon=True)
        sender.start()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        self.addCleanup(sender.join, 1.0)
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


class LocGhiLichSuTests(unittest.TestCase):
    """Chọn lọc thứ ghi vào lịch sử — chỉ giữ tín hiệu NÓI LÊN CÓ NGƯỜI."""

    def test_thiet_bi_dong_ngat_thi_GHI(self) -> None:
        for e in ("light.bep", "switch.o_cam", "lock.cua_chinh",
                  "climate.dieu_hoa", "media_player.tivi"):
            self.assertTrue(ha_live._dang_ghi(e), e)

    def test_cam_bien_HIEN_DIEN_thi_GHI(self) -> None:
        for e in ("binary_sensor.phong_khach_presence",
                  "sensor.hien_dien_bep_motion_state",
                  "sensor.bep_occupancy", "sensor.ban_cong_person_count"):
            self.assertTrue(ha_live._dang_ghi(e), e)

    def test_NHIET_DO_DO_AM_PHAI_GHI(self) -> None:
        """Sơ đồ chủ máy 10/09/2026: quạt và bình nóng lạnh học theo NHIỆT ĐỘ.

        Hôm 09/09 tôi chặn nhiệt độ vì thấy nó chiếm 46% bản ghi — lo nhầm
        bảng: số đo vào `so_do` đã gộp 5 phút nên tối đa 288 dòng/ngày/trường.
        Chặn ở đây là mất luôn điều kiện cần để học.
        """
        for e in ("sensor.nhiet_am_ban_cong_temperature",
                  "sensor.nhiet_am_ban_cong_humidity",
                  "sensor.aptomat_tong_power"):
            self.assertTrue(ha_live._dang_ghi(e), e)

    def test_LUX_GHI_CA_NGOAI_TROI(self) -> None:
        """Sơ đồ "Đèn, rèm" cần LUX, và lux ngoài trời cho biết trời tối chưa.

        Đo thật: tra ngược 400 lần bật đèn bếp xem lúc đó bao nhiêu lux →
        0/400 lần tra được, vì bộ lọc cũ chặn.
        """
        for e in ("sensor.hien_dien_bep_illuminance",
                  "sensor.hien_dien_ban_cong_illuminance",
                  "sensor.san_thuong_illuminance"):
            self.assertTrue(ha_live._dang_ghi(e), e)

    def test_VI_TRI_NGUOI_PHAI_GHI(self) -> None:
        """Sơ đồ "Thời gian về nhà" cần biết người đang ở đâu."""
        for e in ("device_tracker.dien_thoai", "person.chu_nha"):
            self.assertTrue(ha_live._dang_ghi(e), e)

    def test_ha_thong_khong_ghi(self) -> None:
        """Chỉ còn chặn thứ do CHÍNH HỆ THỐNG sinh ra.

        `automation.`/`script.`/`scene.` là việc bot và HA tự chạy — học từ
        chúng là học từ chính mình.
        """
        for e in ("update.ha_core", "automation.den_bep", "sun.sun",
                  "number.do_sang", "script.di_ngu", "scene.buoi_toi"):
            self.assertFalse(ha_live._dang_ghi(e), e)


if __name__ == "__main__":
    unittest.main()
