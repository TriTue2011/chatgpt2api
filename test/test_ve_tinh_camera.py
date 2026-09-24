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
            mock.patch.object(vt, "cho_nghe", return_value=True), \
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
    assert lenh[-7:] == ["-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"]


def test_chi_camera_khai_cong_moi_thanh_ve_tinh():
    from services import camera_nha
    with mock.patch.object(camera_nha, "danh_sach", return_value=[
            {"name": "Cam cửa", "ve_tinh_cong": 10801},
            {"name": "Cam bếp", "ve_tinh_cong": "10803"},
            {"name": "Cam sân"}, {"name": "Cam hỏng", "ve_tinh_cong": "abc"}]):
        assert vt.ds_cong() == {10801: "Cam cửa", 10803: "Cam bếp"}


def test_cho_nghe_mac_dinh_tat():
    """Chủ máy 24/09/2026: tránh người ngoài cửa ra lệnh cho nhà — không khai là KHÔNG nghe."""
    from services import camera_nha
    for cam, muon in (({}, False), ({"cho_nghe": False}, False), ({"cho_nghe": "true"}, False),
                      ({"cho_nghe": True}, True)):
        with mock.patch.object(camera_nha, "_lay", return_value=("Cam cửa", cam)):
            assert vt.cho_nghe("Cam cửa") is muon


async def _kich_ban_cong_tac():
    """HA đòi nghe khi công tắc TẮT: không mic; bật lên thì tự nghe."""
    trang_thai = {"nghe": False}

    async def nghe_gia(self):
        await self.ghi("audio-chunk", {"rate": 16000, "width": 2, "channels": 1}, b"\x01\x00")
        await asyncio.sleep(3600)

    async def ket_noi(r, w):
        await vt._VeTinh("Cam cửa", r, w).chay()

    with mock.patch.object(vt._VeTinh, "_nghe", nghe_gia), \
            mock.patch.object(vt, "_NHIP", 0.05), \
            mock.patch.object(vt, "cho_nghe", side_effect=lambda _t: trang_thai["nghe"]):
        server = await asyncio.start_server(ket_noi, "127.0.0.1", 0)
        r, w = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
        await _gui(w, "run-satellite")
        try:
            await asyncio.wait_for(_doc(r), 0.3)
            im_lang = False
        except asyncio.TimeoutError:
            im_lang = True
        trang_thai["nghe"] = True
        sau = [(await asyncio.wait_for(_doc(r), 2))[0] for _ in range(2)]
        w.close()
        server.close()
        return im_lang, sau


def test_cong_tac_nghe_tat_thi_khong_day_mic_bat_len_thi_nghe():
    im_lang, sau = asyncio.run(_kich_ban_cong_tac())
    assert im_lang
    assert sau == ["run-pipeline", "audio-chunk"]


def test_loa_tat_thi_tu_choi_phat():
    from services import camera_nha
    import pytest as _pt
    with mock.patch.object(camera_nha, "_lay", return_value=("Cam cửa", {"cho_loa": False})):
        with _pt.raises(loa_camera.LoiLoa, match="đang tắt"):
            loa_camera.phat("Cam cửa", b"")
        with _pt.raises(loa_camera.LoiLoa, match="đang tắt"):
            loa_camera.PhatLuong("Cam cửa", 22050)


def test_tang_mic_them_bo_loc_va_chan_dinh():
    """Mic camera nhỏ; ô Mic volume của HA 2026.9 không áp vào vệ tinh Wyoming."""
    goc = {"base": "http://h:1984", "src": "cua"}
    lenh = vt._lenh_mic(goc)
    assert lenh[lenh.index("-af") + 1] == "highpass=f=80"          # luôn bỏ DC
    lenh = vt._lenh_mic({**goc, "mic_tang_db": 12})
    assert lenh[lenh.index("-af") + 1].startswith("highpass=f=80,volume=12dB,alimiter=limit=0.9")
    assert vt.mic_tang_db({"mic_tang_db": 99}) == 30.0 and vt.mic_tang_db({"mic_tang_db": "x"}) == 0.0
