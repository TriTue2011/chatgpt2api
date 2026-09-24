"""Loa camera Dahua/Imou qua cổng 37777 (24/09/2026).

Camera giả nói đúng trình tự khung byte của giao thức: thách đăng nhập, đăng
nhập, AddObject, kênh phụ, bật/tắt nói. Phần băm mật khẩu thì đo trên máy thật:
cả bốn camera Imou nhà chủ nhận đăng nhập, Cam cửa phát được tiếng bíp.
"""
from __future__ import annotations

import os
import shutil
import socket
import struct
import threading
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import loa_camera as lc  # noqa: E402


class CameraGia:
    """Máy chủ 37777 giả: ghi lại mọi khung nhận được."""

    def __init__(self, phien: int = 1002, ly_do: int = 0) -> None:
        self.phien, self.ly_do = phien, ly_do
        self.ln = socket.create_server(("127.0.0.1", 0))
        self.cong = self.ln.getsockname()[1]
        self.chu: list[str] = []          # thân các khung F4, theo thứ tự nhận
        self.tieng: list[bytes] = []      # các khung âm thanh 0x1D (cả đầu)
        self.so_ket_noi = 0
        self.dang_nhap = 0
        threading.Thread(target=self._nghe, daemon=True).start()

    def _gui(self, c, cmd, than=b"", phien=0, ly_do=0):
        h = bytearray(32)
        h[0] = cmd
        h[4:8] = struct.pack("<I", len(than))
        h[8] = ly_do
        h[16:20] = struct.pack("<I", phien)
        c.sendall(bytes(h) + than)

    def _nghe(self):
        while True:
            try:
                c, _ = self.ln.accept()
            except OSError:
                return
            self.so_ket_noi += 1
            threading.Thread(target=self._phuc_vu, args=(c,), daemon=True).start()

    def _phuc_vu(self, c):
        try:
            while True:
                h, b = lc._doc_khung(c)
                if h[0] == lc._A0 and not b:
                    self._gui(c, lc._B0, b"Realm:Login to GIA\r\nRandom:12345\r\n")
                elif h[0] == lc._A0:
                    self.dang_nhap += 1
                    self._gui(c, lc._B0, phien=self.phien, ly_do=self.ly_do)
                elif h[0] == lc._F4:
                    s = b.decode()
                    self.chu.append(s)
                    if "AddObject" in s and "DeleteObject" not in s:
                        self._gui(c, lc._F4, b"AddObjectResponse\r\nFaultCode:OK\r\nConnectionID:77\r\n")
                    elif "AckSubChannel" in s:
                        self._gui(c, lc._F4, b"AckSubChannel\r\nFaultCode:OK\r\n")
                elif h[0] == lc._TALK:
                    self.tieng.append(h + b)
        except (OSError, ConnectionError):
            pass


def test_phien_noi_dung_trinh_tu_va_khung_tieng():
    cam = CameraGia()
    pcm = b"\x10\x00" * 1000                                  # 2000 byte = 125 ms
    with mock.patch.object(lc.time, "sleep"):
        with lc.KenhNoi("127.0.0.1", "admin", "mk", cong=cam.cong) as k:
            k.phat_pcm(pcm)
    # Camera giả đọc hai kết nối trên hai luồng: chờ cả hai đọc xong mới kiểm.
    import time
    for _ in range(250):
        if any("DeleteObject" in s for s in cam.chu) and \
                sum(len(t) - 40 for t in cam.tieng) == len(pcm):
            break
        time.sleep(0.02)
    thu_tu = [next(m for m in ("AddObject", "AckSubChannel", "State:1", "State:0", "DeleteObject")
                   if m in s) for s in cam.chu]
    assert thu_tu == ["AddObject", "AckSubChannel", "State:1", "State:0", "DeleteObject"]
    assert "SessionID:1002" in cam.chu[1] and "ConnectionID:77" in cam.chu[1]
    assert "Channel:0" in cam.chu[2] and "Frequency:8000" in cam.chu[2]
    assert [len(t) - 40 for t in cam.tieng] == [640, 640, 640, 80]   # khối 40 ms
    dau = cam.tieng[0]
    assert dau[8] == 2 and struct.unpack("<III", dau[9:21]) == (16, 1, 8000)
    assert dau[32:38] == b"\x00\x00\x01\xF0\x0C\x02"                  # PCM16, 8 kHz
    assert b"".join(t[40:] for t in cam.tieng) == pcm


def test_sai_mat_khau_bao_ro_va_khong_thu_lai():
    """Camera khoá phiên sau vài lần sai — thử lại chỉ gia hạn khoá."""
    cam = CameraGia(phien=0, ly_do=1)
    with pytest.raises(lc.LoiLoa, match="sai mật khẩu"):
        with lc.KenhNoi("127.0.0.1", "admin", "sai", cong=cam.cong):
            pass
    assert cam.dang_nhap == 1


def test_dia_chi_lay_tu_luong_go2rtc_khong_giu_mat_khau_rieng():
    tra = mock.Mock(status_code=200)
    tra.json.return_value = {"producers": [
        {"url": "ffmpeg:cua#audio=opus"},
        {"url": "rtsp://admin:m%40t@172.16.10.250/cam/realmonitor?channel=1&subtype=0"}]}
    with mock.patch("httpx.get", return_value=tra) as goi:
        ip = lc.dia_chi({"kind": "go2rtc", "base": "http://ha:1984/", "src": "cua"})
    assert ip == ("172.16.10.250", "admin", "m@t")
    assert goi.call_args.kwargs["params"] == {"src": "cua"}
    assert lc.dia_chi({"kind": "rtsp", "url": "rtsp://u:p@10.0.0.9:554/x"}) == ("10.0.0.9", "u", "p")


def test_luong_go2rtc_khong_tro_vao_camera_thi_bao_ro():
    tra = mock.Mock(status_code=200)
    tra.json.return_value = {"producers": [{"url": "ffmpeg:cua#audio=opus"}]}
    with mock.patch("httpx.get", return_value=tra):
        with pytest.raises(lc.LoiLoa, match="không trỏ thẳng"):
            lc.dia_chi({"kind": "go2rtc", "base": "http://ha:1984", "src": "cua"})


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="cần ffmpeg")
def test_doi_am_thanh_ve_pcm_8k():
    import io
    import wave
    b = io.BytesIO()
    w = wave.open(b, "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
    w.writeframes(b"\x00\x00" * 2 * 48000)                  # 1 giây stereo 48 kHz
    w.close()
    assert len(lc.pcm_8k(b.getvalue())) == 16000             # 1 giây mono 8 kHz


def test_noi_cau_rong_bao_loi():
    with pytest.raises(lc.LoiLoa, match="Chưa có câu"):
        lc.noi("Cam cửa", "   ")
