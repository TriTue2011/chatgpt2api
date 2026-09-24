"""Vệ tinh camera cho Home Assistant (24/09/2026).

Đóng vai HA đúng như ``homeassistant/components/wyoming/assist_satellite.py``
(HA 2026.9.3): describe → info có ``satellite``; run-satellite → vệ tinh xin
pipeline bắt từ gọi và đẩy tiếng mic; ping → pong; tiếng TTS/announce → phát
ra loa rồi báo played.
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import loa_camera  # noqa: E402
from services import ve_tinh_camera as vt  # noqa: E402


class LoaGia:
    ds: list["LoaGia"] = []

    def __init__(self, ten, rate, width, channels):
        self.ten, self.rate, self.nhan, self.da_xong = ten, rate, b"", False
        LoaGia.ds.append(self)

    def them(self, pcm):
        self.nhan += pcm

    def xong(self, cho=0):
        self.da_xong = True
        return 1.0


async def _gui(w, loai, data=None, payload=b""):
    d = json.dumps(data or {}).encode()
    h = {"type": loai, "data_length": len(d)}
    if payload:
        h["payload_length"] = len(payload)
    w.write(json.dumps(h).encode() + b"\n" + d + payload)
    await w.drain()


async def _doc(r):
    h = json.loads(await r.readline())
    data = json.loads(await r.readexactly(h["data_length"])) if h.get("data_length") else {}
    p = await r.readexactly(h["payload_length"]) if h.get("payload_length") else b""
    return h["type"], data, p


async def _kich_ban():
    async def nghe_gia(self):
        for i in range(2):
            await self.ghi("audio-chunk", {"rate": 16000, "width": 2, "channels": 1,
                                           "timestamp": i * 64}, b"\x01\x00" * 1024)
        await asyncio.sleep(3600)

    async def ket_noi(r, w):
        await vt._VeTinh("Cam cửa", r, w).chay()

    LoaGia.ds.clear()
    with mock.patch.object(vt._VeTinh, "_nghe", nghe_gia), \
            mock.patch.object(loa_camera, "PhatLuong", LoaGia):
        server = await asyncio.start_server(ket_noi, "127.0.0.1", 0)
        cong = server.sockets[0].getsockname()[1]
        r, w = await asyncio.open_connection("127.0.0.1", cong)
        ra = []
        await _gui(w, "describe")
        ra.append(await _doc(r))
        await _gui(w, "run-satellite")
        for _ in range(3):
            ra.append(await _doc(r))
        await _gui(w, "ping", {"text": "x"})
        ra.append(await _doc(r))
        await _gui(w, "audio-start", {"rate": 22050, "width": 2, "channels": 1})
        await _gui(w, "audio-chunk", {"rate": 22050, "width": 2, "channels": 1}, b"\x02\x00" * 100)
        await _gui(w, "audio-stop")
        ra.append(await _doc(r))
        w.close()
        server.close()
        return ra


def test_vai_ha_tu_dau_den_cuoi():
    ra = asyncio.run(_kich_ban())
    loai = [x[0] for x in ra]
    assert loai == ["info", "run-pipeline", "audio-chunk", "audio-chunk", "pong", "played"]
    assert ra[0][1]["satellite"]["name"] == "Camera Cam cửa"
    assert ra[1][1] == {"start_stage": "wake", "end_stage": "tts", "restart_on_end": True}
    assert ra[2][1]["rate"] == 16000 and len(ra[2][2]) == 2048
    assert ra[4][1] == {"text": "x"}
    loa = LoaGia.ds[0]
    assert (loa.ten, loa.rate, loa.nhan, loa.da_xong) == ("Cam cửa", 22050, b"\x02\x00" * 100, True)


def test_lenh_mic_ma_hoa_mat_khau_trong_url():
    lenh = vt._lenh_mic({"base": "http://172.16.10.200:1984/", "src": "cua", "src_ai": "cua-sub",
                         "username": "u", "password": "m@t:1"})
    url = lenh[lenh.index("-i") + 1]
    assert url == "http://u:m%40t%3A1@172.16.10.200:1984/api/stream.mp4?src=cua-sub&video=none&audio=all"
    assert lenh[-8:] == ["-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"]


def test_chua_bat_thi_khong_mo_cong():
    with mock.patch.object(vt, "cau_hinh", return_value={"cong": {"Cam cửa": 10801}}):
        assert vt.start() == []
