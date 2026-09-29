"""Loa camera Dahua/Imou qua cổng 37777 (24/09/2026) và cổng 8086 (28/09/2026).

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
def test_doi_am_thanh_ve_pcm_mono():
    import io
    import wave
    b = io.BytesIO()
    w = wave.open(b, "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
    w.writeframes(b"\x00\x00" * 2 * 48000)                  # 1 giây stereo 48 kHz
    w.close()
    assert len(lc.pcm_mono(b.getvalue(), 8000)) == 16000      # 1 giây mono 8 kHz
    assert len(lc.pcm_mono(b.getvalue(), 16000)) == 32000     # 1 giây mono 16 kHz


def test_noi_cau_rong_bao_loi():
    with pytest.raises(lc.LoiLoa, match="Chưa có câu"):
        lc.noi("Cam cửa", "   ")


def test_phat_luong_camera_rot_mang_bao_loi_loa() -> None:
    """Người gọi (vệ tinh, bộ đàm) chỉ bắt LoiLoa: lỗi mạng phải đổi thành LoiLoa."""
    with mock.patch.object(lc, "_lay_cho_phat", lambda ten: (ten, {})), \
            mock.patch.object(lc, "dia_chi", lambda cam: ("127.0.0.1", "u", "p")), \
            mock.patch.object(lc.KenhNoi8086, "_mo", side_effect=ConnectionRefusedError("từ chối")), \
            mock.patch.object(lc.KenhNoi, "_mo", side_effect=ConnectionRefusedError("từ chối")):
        with pytest.raises(lc.LoiLoa, match="không nói được"):
            lc.PhatLuong("cửa", 8000)
    # Khoá camera được nhả: lần sau không kẹt.
    assert not lc._khoa["127.0.0.1"].locked()


# ── Cổng 8086 (AAC 16 kHz) ──────────────────────────────────────────────────

class Camera8086Gia:
    """Máy chủ 8086 giả: trả 200 cho các PLAY (hay 401 kèm realm lần đầu), gom khung tiếng."""

    def __init__(self, doi_realm: bool = False, ma: int = 200) -> None:
        self.doi_realm, self.ma = doi_realm, ma
        self.ln = socket.create_server(("127.0.0.1", 0))
        self.cong = self.ln.getsockname()[1]
        self.yeu_cau: list[str] = []
        self.khung: list[bytes] = []
        threading.Thread(target=self._nghe, daemon=True).start()

    def _nghe(self):
        c, _ = self.ln.accept()
        du = b""
        try:
            while True:
                b = c.recv(65536)
                if not b:
                    return
                du += b
                while True:
                    if du.startswith(b"$") and len(du) >= 6:
                        dai = 6 + struct.unpack_from(">I", du, 2)[0]
                        if len(du) < dai:
                            break
                        self.khung.append(du[:dai])
                        du = du[dai:]
                    elif b"\r\n\r\n" in du:
                        dau, _, du = du.partition(b"\r\n\r\n")
                        chu = dau.decode()
                        m = [x for x in chu.split("\r\n") if x.startswith("Private-Length: ")]
                        du = du[int(m[0].split(": ")[1]):] if m else du
                        self.yeu_cau.append(chu)
                        if self.doi_realm and len(self.yeu_cau) == 1:
                            c.sendall(b'HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Digest realm="Login to X", '
                                      b'nonce="1"\r\nContent-Length: 0\r\n\r\n')
                        else:
                            c.sendall(f"HTTP/1.1 {self.ma} OK\r\nContent-Length: 0\r\n\r\n".encode())
                    else:
                        break
        except OSError:
            pass


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="cần ffmpeg")
def test_kenh_8086_bat_tay_va_gui_aac_16k_dung_nhip():
    import time
    cam = Camera8086Gia()
    t0 = time.monotonic()
    with lc.KenhNoi8086("127.0.0.1", "admin", "mk", cong=cam.cong) as k:
        assert k.tan_so == 16000
        k.phat_pcm(b"\x10\x00" * 16000)                      # 1 giây
    mat = time.monotonic() - t0
    assert [y.split(" ")[1].split("trackID=")[1].split("&")[0] for y in cam.yeu_cau] == ["31", "6", "64"]
    assert "talktype=talk" in cam.yeu_cau[2] and 'Username="admin"' in cam.yeu_cau[0]
    assert "Private-Type: application/sdp" in cam.yeu_cau[0]
    assert 14 <= len(cam.khung) <= 20                          # ~1 giây / 64 ms mỗi khung
    k0 = cam.khung[0]
    assert k0[:2] == b"$\x0a" and k0[6:10] == b"DHAV" and k0[0x1E:0x22] == b"\x83\x01\x1a\x04"
    assert k0[6 + 0x17] == sum(k0[6:6 + 0x17]) & 0xFF        # tổng kiểm đầu DHAV
    assert k0[6 + 28] == 0xFF and k0[-8:-4] == b"dhav"         # thân là khung ADTS
    assert mat >= 0.9                                          # gửi đúng nhịp, không dồn


def test_kenh_8086_doi_realm_thi_bam_lai_mot_lan():
    cam = Camera8086Gia(doi_realm=True)
    with mock.patch.object(lc.subprocess, "Popen"), mock.patch.object(lc.threading, "Thread"):
        k = lc.KenhNoi8086("127.0.0.1", "admin", "mk", cong=cam.cong)
        k._mo()
    assert len(cam.yeu_cau) == 4                                # 31 (401) → 31 → 6 → 64
    so = [x.split('PasswordDigest="')[1].split('"')[0] for x in cam.yeu_cau[:2]]
    assert so[0] != so[1]


def test_camera_tu_choi_8086_thi_lui_37777_va_nho():
    lc._lui_37777.clear()
    goi = []

    class K37777:
        tan_so = 8000

        def __init__(self, *a, **k):
            goi.append("37777")

        def __enter__(self):
            return self

    with mock.patch.object(lc.KenhNoi8086, "_mo", side_effect=ConnectionRefusedError("đóng")) as mo, \
            mock.patch.object(lc, "KenhNoi", K37777):
        assert lc.mo_kenh("10.0.0.9", "u", "p").tan_so == 8000
        assert lc.mo_kenh("10.0.0.9", "u", "p").tan_so == 8000
    assert mo.call_count == 1 and goi == ["37777", "37777"]    # lần hai khỏi thử lại 8086
    lc._lui_37777.clear()


def test_cat_adts_giu_phan_do():
    k = bytes([0xFF, 0xF1, 0x50, 0x80, 0x01, 0x5F, 0xFC]) + b"x" * 3   # khung dài 10
    ra, con = lc.cat_adts(k + k + k[:4])
    assert ra == [k, k] and con == k[:4]


# ── EZVIZ / Hikvision qua HCNetSDK (29/09/2026) ──────────────────────────────
#
# Đo thật trên H6C: đăng nhập 0,6–1,3 s, mở kênh 0,02–0,27 s; vừa đóng kênh thì ~1,24 s sau mới
# mở lại được, sớm hơn camera báo "(mã 29)". Tiến trình con giả dưới đây nói đúng giao thức của
# ``services/hik_noi.py``; ffmpeg giả nhả một khung ADTS cho mỗi 2048 byte PCM.

_ADTS = bytes([0xFF, 0xF1, 0x60, 0x40, 0x01, 0x5F, 0xFC]) + b"a" * 3      # một khung dài 10


@pytest.fixture
def hik_gia(tmp_path, monkeypatch):
    import sys as _sys

    nhat_ky = tmp_path / "nhat_ky.txt"
    tro_giup = tmp_path / "hik_noi_gia.py"
    tro_giup.write_text(f"""
import os, struct, sys
bao = os.fdopen(os.dup(1), "w", buffering=1)
if os.environ.get("HIK_MK") == "sai":
    bao.write("LOI đăng nhập cổng 8000 không được (mã 1)\\n"); sys.exit(3)
nk = open({str(nhat_ky)!r}, "a", buffering=1)
nk.write("dang_nhap\\n")
bao.write("SAN AAC 16000\\n")
ban = int(os.environ.get("HIK_BAN", "0"))
mo, n = False, 0
while len(d := sys.stdin.buffer.read(4)) == 4:
    k = struct.unpack(">I", d)[0]
    if k == 0xFFFFFFFF:
        if ban:
            ban -= 1; bao.write("LOI camera không mở kênh đàm thoại (mã 29)\\n"); continue
        mo, n = True, 0; bao.write("OK\\n")
    elif k == 0:
        if mo: nk.write(f"luot {{n}}\\n")
        mo = False; bao.write("DONG\\n")
    else:
        sys.stdin.buffer.read(k); n += 1
nk.write("dang_xuat\\n")
""")
    ffmpeg = tmp_path / "bin" / "ffmpeg"
    ffmpeg.parent.mkdir()
    ffmpeg.write_text(f"#!{_sys.executable}\nimport sys\n"
                      f"while d := sys.stdin.buffer.read(2048):\n"
                      f"    sys.stdout.buffer.write({_ADTS!r}); sys.stdout.buffer.flush()\n")
    ffmpeg.chmod(0o755)
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "libhcnetsdk.so").write_bytes(b"")
    monkeypatch.setenv("PATH", f"{ffmpeg.parent}:{os.environ['PATH']}")
    monkeypatch.setattr(lc, "_HIK_NOI", tro_giup)
    monkeypatch.setattr(lc, "thu_muc_hik", lambda: lib)
    lc._hik.clear()
    yield lambda: nhat_ky.read_text().split("\n")[:-1] if nhat_ky.exists() else []
    for tg in list(lc._hik.values()):
        tg.close()
    lc._hik.clear()


def _luot(ip="10.0.0.9", mk="MA"):
    k = lc.mo_kenh(ip, "admin", mk, "hik")
    assert k.tan_so == 16000
    k.phat_pcm(b"\x00\x01" * 2048)           # 4096 byte → 2 khung
    k.dong()


def test_hik_giu_dang_nhap_giua_cac_luot(hik_gia):
    for _ in range(3):
        _luot()
    lc._hik.pop("10.0.0.9").close()
    assert hik_gia() == ["dang_nhap", "luot 2", "luot 2", "luot 2", "dang_xuat"]


def test_hik_camera_chua_nha_kenh_thi_cho_roi_mo_lai(hik_gia, monkeypatch):
    monkeypatch.setenv("HIK_BAN", "2")
    _luot()
    assert hik_gia() == ["dang_nhap", "luot 2"]


def test_hik_tien_trinh_chet_thi_dang_nhap_lai(hik_gia):
    _luot()
    lc._hik["10.0.0.9"].p.kill()
    lc._hik["10.0.0.9"].p.wait()
    _luot()
    assert hik_gia() == ["dang_nhap", "luot 2", "dang_nhap", "luot 2"]


def test_hik_sai_mat_khau_bao_ro(hik_gia):
    with pytest.raises(lc.LoiLoa, match="mã 1"):
        lc.mo_kenh("10.0.0.9", "admin", "sai", "hik")


def test_hik_chua_co_sdk_bao_cach_cai(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "thu_muc_hik", lambda: tmp_path)
    lc._hik.clear()
    with pytest.raises(lc.LoiLoa, match="Device Network SDK"):
        lc.mo_kenh("10.0.0.9", "admin", "MA", "hik")


def test_kieu_loa_mac_dinh_la_imou():
    assert lc.kieu_loa({}) == "" and lc.kieu_loa({"loa_kieu": "hik"}) == "hik"
    assert lc.kieu_loa({"loa_kieu": "la"}) == ""
