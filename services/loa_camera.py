"""Loa camera — phát âm thanh ra loa của camera Dahua/Imou, và EZVIZ/Hikvision (HCNetSDK).

Camera nhà (Imou, lõi Dahua) KHÔNG có kênh ngược RTSP/ONVIF: đo 24/09/2026 trên
cả bốn camera, DESCRIBE kèm ``Require: www.onvif.org/ver20/backchannel`` chỉ trả
luồng ``recvonly``, CGI HTTP không trả lời. Đường còn lại là giao thức nhị phân
NetSDK trên cổng 37777 — đúng đường app Imou dùng để nói. Mô tả khung byte lấy
từ go2rtc PR #2431 (``pkg/dahua/netsdk.go``, chưa gộp vào go2rtc); ở đây viết lại
bằng thư viện chuẩn, chỉ nối tới đúng camera.

Đo trên Cam cửa: mở kênh nói 0,05 giây; mic của chính camera ghi được tiếng bíp
1 kHz (gấp 164 lần nền), và camera tự tắt mic trong lúc phát — không tự nghe lại
tiếng mình.

Địa chỉ và mật khẩu lấy từ luồng go2rtc mà camera ấy đã khai (hoặc URL RTSP):
c2a không giữ thêm một bản mật khẩu nào.

Đường CHÍNH từ 28/09/2026 là cổng 8086 (``KenhNoi8086``): kênh nói HTTP riêng của Imou,
tiếng AAC 16 kHz — chính camera khai định dạng này cho kênh nói (SDP ``trackID=5 sendonly
MPEG4-GENERIC/16000``). Chủ máy nghe so sánh trên Cam phòng khách cùng ngày: "16 rõ hơn 8".
Cổng 37777 chỉ nhận PCM 8 kHz — cắt mất dải trên 4 kHz, đúng dải phụ âm s/x/ch. Camera nào
không mở 8086 (hay từ chối) thì ``mo_kenh`` tự lùi về 37777.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import select
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

# Logger của dự án: ``logging.getLogger(__name__)`` không có handler nào nên mọi
# dòng bị nuốt (đo 24/09/2026: 6 giờ phát loa, 0 dòng log trong docker logs).
from utils.log import logger  # noqa: E402

CONG_NOI = 37777
#: Kênh nói. Camera một mắt chỉ có kênh 0 — PR #2431 ghi số kênh ngoài dải làm
#: một số đời firmware khởi động lại liên tục, nên không mở cho cấu hình.
KENH = 0
HET_GIO = 5.0
#: Tối đa ngần này giây một lần phát — chặn tin nhắn dài giữ loa cả phút.
TOI_DA_GIAY = 120.0

_HDR = 32
_A0, _B0, _A1, _F4, _TALK = 0xA0, 0xB0, 0xA1, 0xF4, 0x1D
_THACH = bytes([0x05, 0x02, 0x00, 0x01, 0x00, 0x00, 0xA1, 0xAA])
_DANG_NHAP = bytes([0x05, 0x02, 0x00, 0x08, 0x00, 0x00, 0xA1, 0xAA])
_LY_DO = {1: "sai mật khẩu", 2: "không có tài khoản này", 4: "tài khoản đang đăng nhập nơi khác",
          5: "tài khoản bị khoá", 6: "bị chặn vì sai mật khẩu nhiều lần", 7: "camera đang bận",
          8: "camera hết chỗ kết nối", 9: "camera không còn kênh trống"}
#: PCM16 mono 8 kHz, khối 40 ms — đúng định dạng bản Talk mẫu của Dahua.
_TAN_SO = 8000
_KHOI = 640

_khoa: dict[str, threading.Lock] = {}
_khoa_chung = threading.Lock()

#: Cờ bắt buộc cho MỌI ffmpeg đọc tiếng theo luồng từ ống dẫn. Thiếu chúng, ffmpeg
#: gom tiếng để dò định dạng trước khi nhả byte nào — đo 24/09/2026 trong c2a:
#: 20 khúc (2,5 giây) vào mà 0 byte ra; có cờ thì mỗi khúc ra sau ~130 ms. Tức
#: "phát theo luồng" thực chất là thu hết rồi mới phát.
FFMPEG_TRUC_TIEP = ("-probesize", "32", "-analyzeduration", "0", "-fflags", "nobuffer")


class LoiLoa(RuntimeError):
    """Không phát được — thông điệp đã sẵn sàng đọc cho người dùng."""


# ── Khung byte ───────────────────────────────────────────────────────────────

def _khung(cmd: int, than: bytes = b"", duoi: bytes = b"") -> bytes:
    h = bytearray(_HDR)
    h[0] = cmd
    if cmd == _A0:
        h[1:4] = b"\x05\x00\x60"
    h[4:8] = struct.pack("<I", len(than))
    if len(duoi) == 8:
        h[24:32] = duoi
    return bytes(h) + than


def _khung_tieng(pcm: bytes) -> bytes:
    h = bytearray(_HDR)
    h[0] = _TALK
    h[4:8] = struct.pack("<I", 8 + len(pcm))
    h[8] = 0x02                                   # âm thanh
    h[9:21] = struct.pack("<III", 16, 1, _TAN_SO)  # bit, kênh, tần số
    # Đầu phụ DHAV: 0x0C = PCM16, chỉ số tần số 2 = 8 kHz (bản Talk mẫu gửi vậy).
    return bytes(h) + b"\x00\x00\x01\xF0" + bytes([0x0C, 2]) + struct.pack("<H", len(pcm)) + pcm


def _doc_du(s: socket.socket, n: int) -> bytes:
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c:
            raise ConnectionError("camera đóng kết nối")
        b += c
    return b


def _doc_khung(s: socket.socket) -> tuple[bytes, bytes]:
    h = _doc_du(s, _HDR)
    n = struct.unpack("<I", h[4:8])[0]
    if n > 65536:
        raise ConnectionError(f"khung dài bất thường ({n} byte)")
    return h, (_doc_du(s, n) if n else b"")


def _kv(than: bytes) -> dict[str, str]:
    out = {}
    for d in than.decode(errors="replace").rstrip("\x00\r\n").split("\r\n"):
        if ":" in d:
            k, v = d.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _chu(s: socket.socket, dong: list[str]) -> None:
    s.sendall(_khung(_F4, ("\r\n".join(dong) + "\r\n\r\n").encode()))


def _cho_chu(s: socket.socket, muon: str) -> dict[str, str]:
    for _ in range(32):
        h, b = _doc_khung(s)
        if h[0] == _F4 and muon.encode() in b:
            return _kv(b)
    raise ConnectionError(f"camera không trả lời {muon}")


# MD5 là do giao thức Dahua bắt buộc để băm mật khẩu đăng nhập, không phải lựa
# chọn của mình — ``usedforsecurity=False`` ghi rõ điều đó.
def _md5(x: str) -> str:
    return hashlib.md5(x.encode(), usedforsecurity=False).hexdigest().upper()


def _gen1(mk: str) -> str:
    d = hashlib.md5(mk.encode(), usedforsecurity=False).digest()
    ra = ""
    for i in range(8):
        v = (d[i * 2] + d[i * 2 + 1]) % 62
        ra += chr(v + 48 if v < 10 else v + 55 if v < 36 else v + 61)
    return ra


class KenhNoi:
    """Một phiên nói: đăng nhập, mở kênh, phát, đóng. Dùng với ``with``."""

    #: ``phat_pcm`` nhận PCM16 mono ở tần số này.
    tan_so = _TAN_SO

    def __init__(self, ip: str, user: str, mk: str, *, cong: int = CONG_NOI,
                 het_gio: float = HET_GIO) -> None:
        self.ip, self.user, self.mk, self.cong, self.het_gio = ip, user, mk, cong, het_gio
        self.ctrl: socket.socket | None = None
        self.sub: socket.socket | None = None
        self.phien, self.cid = 0, ""
        self._dung = threading.Event()
        self._luong: list[threading.Thread] = []

    def __enter__(self) -> "KenhNoi":
        try:
            self._mo()
        except BaseException:
            self.dong()
            raise
        return self

    def __exit__(self, *_exc) -> None:
        self.dong()

    def _mo(self) -> None:
        self.ctrl = socket.create_connection((self.ip, self.cong), timeout=self.het_gio)
        self.ctrl.sendall(_khung(_A0, duoi=_THACH))
        h, b = _doc_khung(self.ctrl)
        t = _kv(b)
        if h[0] != _B0 or not t.get("Realm") or not t.get("Random"):
            raise LoiLoa("camera không phải loại Dahua/Imou nói được qua cổng 37777")
        g2 = _md5(self.user + ":" + t["Realm"] + ":" + self.mk)
        g2 = _md5(self.user + ":" + t["Random"] + ":" + g2)
        g1 = _md5(self.user + ":" + t["Random"] + ":" + _gen1(self.mk))
        self.ctrl.sendall(_khung(_A0, f"{self.user}&&{g2}{g1}".encode(), _DANG_NHAP))
        h, _b = _doc_khung(self.ctrl)
        self.phien = struct.unpack("<I", h[16:20])[0]
        if not self.phien:
            # KHÔNG thử lại: camera khoá phiên sau vài lần sai, thử nữa là gia hạn khoá.
            raise LoiLoa(f"camera từ chối đăng nhập: {_LY_DO.get(h[8], f'mã {h[8]}')}")
        _chu(self.ctrl, ["TransactionID:6", "Method:AddObject",
                         "ParameterName:Dahua.Device.Network.ControlConnection.Passive",
                         "ConnectProtocol:0"])
        t = _cho_chu(self.ctrl, "AddObjectResponse")
        if t.get("FaultCode") not in ("OK", "", None) or not t.get("ConnectionID"):
            raise LoiLoa(f"camera không mở kết nối nói ({t.get('FaultCode')})")
        self.cid = t["ConnectionID"]
        self.sub = socket.create_connection((self.ip, self.cong), timeout=self.het_gio)
        _chu(self.sub, ["TransactionID:0", "Method:GetParameterNames",
                        "ParameterName:Dahua.Device.Network.ControlConnection.AckSubChannel",
                        f"SessionID:{self.phien}", f"ConnectionID:{self.cid}", "Encrypt:0"])
        if _cho_chu(self.sub, "AckSubChannel").get("FaultCode") != "OK":
            raise LoiLoa("camera không nhận kênh âm thanh phụ")
        self.sub.sendall(_khung(_A1))
        self._trang_thai(True)
        for s in (self.ctrl, self.sub):
            s.settimeout(None)
            self._luong.append(threading.Thread(target=self._xa, args=(s,), name="loa-cam-doc",
                                                daemon=True))
        self._luong.append(threading.Thread(target=self._giu, name="loa-cam-giu", daemon=True))
        for t in self._luong:
            t.start()

    def _trang_thai(self, bat: bool) -> None:
        _chu(self.ctrl, ["TransactionID:" + ("7" if bat else "8"), "Method:GetParameterNames",
                         "ParameterName:Dahua.Device.Network.Talk.General",
                         f"Channel:{KENH}", "EncodeFormat:1",
                         "Depth:" + ("16" if bat else "0"),
                         "Frequency:" + (str(_TAN_SO) if bat else "0"),
                         "State:" + ("1" if bat else "0"), f"ConnectionID:{self.cid}", "TalkMode:0"])

    def _xa(self, s: socket.socket) -> None:
        """Đọc bỏ những gì camera gửi về (trả lời, tiếng mic) cho bộ đệm khỏi đầy."""
        try:
            while not self._dung.is_set():
                _doc_khung(s)
        except (OSError, ConnectionError):
            pass

    def _giu(self) -> None:
        while not self._dung.wait(1.0):
            try:
                self.ctrl.sendall(_khung(_A1))
            except OSError:
                return

    def phat_pcm(self, pcm: bytes) -> None:
        """PCM16 LE mono 8 kHz, gửi từng khối 40 ms đúng nhịp thời gian thực."""
        t0 = time.monotonic()
        for i in range(0, len(pcm), _KHOI):
            self.sub.sendall(_khung_tieng(pcm[i:i + _KHOI]))
            cho = t0 + (i + _KHOI) / (2 * _TAN_SO) - time.monotonic()
            if cho > 0:
                time.sleep(cho)

    def dong(self) -> None:
        self._dung.set()
        try:
            if self.ctrl is not None and self.cid:
                self._trang_thai(False)
                _chu(self.ctrl, ["TransactionID:9", "Method:DeleteObject",
                                 "ParameterName:Dahua.Device.Network.ControlConnection.Passive",
                                 f"ConnectionID:{self.cid}"])
        except OSError:
            pass
        for s in (self.sub, self.ctrl):
            if s is not None:
                # shutdown đánh thức luồng đang chặn ở recv(); chỉ close() thì luồng
                # ấy kẹt tới khi camera tự đóng — mỗi lần phát rò một luồng.
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                s.close()
        self.sub = self.ctrl = None
        for t in self._luong:
            if t is not threading.current_thread():
                t.join(2)


# ── Cổng 8086: kênh nói HTTP riêng của Imou, AAC 16 kHz ──────────────────────
#
# Trình tự byte theo ha-imou-talkback (vnp1978, MIT, 28/09/2026), viết lại ở đây: yêu cầu
# ``PLAY /live/visualtalk.xav…`` kiểu HTTP, xác thực WSSE (UsernameToken), rồi tiếng đi
# trên CHÍNH kết nối ấy dạng xen kẽ ``$<kênh><dài>`` bọc khung DHAV. Đo trên cả bốn camera
# nhà: bắt tay 200 OK trong 0,03 giây (cổng 37777 cần ~1,5 giây mở/đóng mỗi lần phát).

CONG_HTTP = 8086
_TAN_SO_HTTP = 16000
#: Một khung AAC = 1024 mẫu = 64 ms ở 16 kHz.
_KHUNG_AAC_GIAY = 1024 / _TAN_SO_HTTP
#: Camera từ chối 8086 thì ngần này giây sau mới thử lại — khỏi mỗi lần phát lại chờ hỏng.
_LUI_37777_GIAY = 3600.0
#: Sau khung cuối chờ ngần này giây cho camera phát nốt phần đang đệm rồi mới đóng.
_DUOI_GIAY = 0.5
_KENH_NOI_HTTP = 5            # trackID của kênh nói trong SDP camera trả về
_DUONG_HTTP = ("/live/visualtalk.xav?channel=1&subtype=0&encrypt=3&imagesize=18&audioType=1"
               "&trackID={track}&method=0")
_SDP_HTTP = ("v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=Talk\r\nc=IN IP4 0.0.0.0\r\nt=0 0\r\n"
             "m=video 0 RTP/AVP 96\r\na=control:trackID=31\r\n"
             "m=audio 0 RTP/AVP 8 96\r\na=rtpmap:8 PCMA/8000\r\n"
             "a=rtpmap:96 MPEG4-GENERIC/16000/1\r\na=control:trackID=5\r\na=sendrecv\r\n").encode()
_CHU_NONCE = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_lui_37777: dict[str, float] = {}        # ip → lúc được thử lại 8086 (monotonic)


def _wsse(user: str, bi_mat: str, nonce: str, tao: str) -> str:
    # SHA-1 do giao thức camera quy định (WSSE UsernameToken), không phải lựa chọn của ta.
    so = base64.b64encode(hashlib.sha1(f"{nonce}{tao}{bi_mat}".encode(),
                                       usedforsecurity=False).digest()).decode()
    return (f'UsernameToken Username="{user}", PasswordDigest="{so}", '
            f'Nonce="{nonce}", Created="{tao}"')


def khung_dhav(aac: bytes, seq: int, tick_ms: int, giay: int) -> bytes:
    """Một khung AAC → khung DHAV (tiếng, 16 kHz) bọc xen kẽ trên kênh nói."""
    dai = len(aac) + 36
    dau = bytearray(28)
    struct.pack_into("<4sB3xII", dau, 0, b"DHAV", 0xF0, seq & 0xFFFFFFFF, dai)
    struct.pack_into("<IH", dau, 0x10, giay & 0xFFFFFFFF, tick_ms & 0xFFFF)
    dau[0x16] = 0x04
    dau[0x17] = sum(dau[:0x17]) & 0xFF
    dau[0x18:0x1C] = b"\x83\x01\x1a\x04"          # tiếng; mã tần số 4 = 16 kHz
    khung = bytes(dau) + aac + b"dhav" + struct.pack("<I", dai)
    return b"$" + bytes([_KENH_NOI_HTTP * 2]) + struct.pack(">I", len(khung)) + khung


def cat_adts(du: bytes) -> tuple[list[bytes], bytes]:
    """Tách các khung ADTS trọn vẹn khỏi đầu ``du``; trả (khung, phần còn dở)."""
    ra = []
    while len(du) >= 7:
        if du[0] != 0xFF or du[1] & 0xF0 != 0xF0:
            i = du.find(b"\xff", 1)
            du = du[i:] if i > 0 else b""
            continue
        dai = ((du[3] & 0x03) << 11) | (du[4] << 3) | (du[5] >> 5)
        if dai < 7 or len(du) < dai:
            break
        ra.append(du[:dai])
        du = du[dai:]
    return ra, du


class KenhNoi8086:
    """Phiên nói qua cổng 8086 — cùng giao diện với ``KenhNoi`` (``with``, ``tan_so``,
    ``phat_pcm``, ``dong``). ffmpeg mã hoá AAC 16 kHz; một luồng gửi từng khung đúng nhịp."""

    tan_so = _TAN_SO_HTTP

    def __init__(self, ip: str, user: str, mk: str, *, cong: int = CONG_HTTP,
                 het_gio: float = HET_GIO) -> None:
        self.ip, self.user, self.mk, self.cong, self.het_gio = ip, user, mk, cong, het_gio
        self.s: socket.socket | None = None
        self._ff: subprocess.Popen | None = None
        self._cseq = 0
        self._realm = ""
        self._dung = threading.Event()
        self._luong: list[threading.Thread] = []
        self._khoa_gui = threading.Lock()

    def __enter__(self) -> "KenhNoi8086":
        try:
            self._mo()
        except BaseException:
            self.dong(cho=False)
            raise
        return self

    def __exit__(self, *_exc) -> None:
        self.dong()

    # bắt tay -------------------------------------------------------------------
    def _play(self, track: int, *, sdp: bytes = b"", them: str = "") -> int:
        nonce = "".join(_CHU_NONCE[b % len(_CHU_NONCE)] for b in os.urandom(32))
        tao = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        bi_mat = self.mk
        if self._realm:
            # Camera đòi "Digest realm": bí mật là MD5 hoa của user:realm:mật khẩu.
            bi_mat = _md5(f"{self.user}:{self._realm}:{self.mk}").upper()
        dong = [f"PLAY {_DUONG_HTTP.format(track=track)}{them} HTTP/1.1",
                f"Host: {self.ip}:{self.cong}", "Connect-Type: P2P", "Connection: keep-alive",
                f"Cseq: {self._cseq}", "Speed: 1.000000", "User-Agent: Http Stream Client/1.0",
                'Authorization: WSSE profile="UsernameToken"',
                "WSSE: " + _wsse(self.user, bi_mat, nonce, tao)]
        if sdp:
            dong += ["Accpet-Sdp: Private", "Private-Type: application/sdp",
                     f"Private-Length: {len(sdp)}"]
        self._cseq += 1
        self.s.sendall(("\r\n".join(dong) + "\r\n\r\n").encode() + sdp)
        return self._doc_tra_loi()

    def _doc_tra_loi(self) -> int:
        du = b""
        while b"\r\n\r\n" not in du:
            b = self.s.recv(4096)
            if not b:
                raise LoiLoa("camera đóng kết nối cổng 8086 giữa chừng")
            du += b
            while du.startswith(b"$") and len(du) >= 6:      # khung media xen kẽ: bỏ
                dai = 6 + struct.unpack_from(">I", du, 2)[0]
                while len(du) < dai:
                    b = self.s.recv(dai - len(du))
                    if not b:
                        raise LoiLoa("camera đóng kết nối cổng 8086 giữa chừng")
                    du += b
                du = du[dai:]
        dau, _, con = du.partition(b"\r\n\r\n")
        chu = dau.decode("latin1", "replace")
        m = re.match(r"\S+ (\d+)", chu)
        ma = int(m.group(1)) if m else 0
        tt = {k.lower(): v for k, _, v in (x.partition(": ") for x in chu.split("\r\n")[1:])}
        dai = int(tt.get("private-length") or tt.get("content-length") or 0)
        while len(con) < dai:
            b = self.s.recv(dai - len(con))
            if not b:
                break
            con += b
        if ma == 401 and not self._realm:
            m = re.search(r'realm="([^"]+)"', tt.get("www-authenticate", ""), re.IGNORECASE)
            self._realm = m.group(1) if m else ""
        return ma

    def _mo(self) -> None:
        self.s = socket.create_connection((self.ip, self.cong), timeout=self.het_gio)
        ma = self._play(31, sdp=_SDP_HTTP)
        if ma == 401 and self._realm:
            ma = self._play(31, sdp=_SDP_HTTP)             # một lần theo realm — không thử mãi
        for track, them in ((None, ""), (6, ""), (64, "&talktype=talk")):
            if track is not None:
                ma = self._play(track, them=them)
            if ma != 200:
                raise LoiLoa(f"camera từ chối kênh nói cổng 8086 (mã {ma})")
        self._ff = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", *FFMPEG_TRUC_TIEP,
             "-f", "s16le", "-ar", str(_TAN_SO_HTTP), "-ac", "1", "-i", "pipe:0",
             "-c:a", "aac", "-b:a", "48k", "-f", "adts", "-flush_packets", "1", "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.s.settimeout(1.0)
        self._luong = [threading.Thread(target=self._xa, name="loa-cam-8086-doc", daemon=True),
                       threading.Thread(target=self._gui, args=(self._ff,), name="loa-cam-8086-gui",
                                        daemon=True)]
        for t in self._luong:
            t.start()

    # tiếng ---------------------------------------------------------------------
    def _xa(self) -> None:
        """Đọc bỏ tiếng/hình camera gửi về trên cùng kết nối, cho bộ đệm khỏi đầy."""
        while not self._dung.is_set():
            try:
                if not self.s.recv(65536):
                    return
            except TimeoutError:
                continue
            except OSError:
                return

    def _gui(self, ff: subprocess.Popen) -> None:
        # Giữ ``ff`` riêng: ``dong`` gỡ ``self._ff`` ngay khi hết tiếng, luồng này còn gửi nốt.
        du, seq, t0 = b"", 0, None
        tick, giay = int(time.monotonic() * 1000), int(time.time())
        try:
            while True:
                b = ff.stdout.read1(4096)
                if not b:
                    break
                khung, du = cat_adts(du + b)
                for k in khung:
                    if t0 is None:
                        t0 = time.monotonic()
                    cho = t0 + seq * _KHUNG_AAC_GIAY - time.monotonic()
                    if cho > 0:
                        time.sleep(cho)
                    with self._khoa_gui:
                        self.s.sendall(khung_dhav(k, seq, tick + int(seq * 64), giay))
                    seq += 1
        except (OSError, ValueError, AttributeError) as exc:
            logger.warning({"event": "loa_camera_8086_gui_hong", "ip": self.ip,
                            "loi": str(exc)[:120]})

    def phat_pcm(self, pcm: bytes) -> None:
        """PCM16 LE mono 16 kHz. Ghi vào bộ mã hoá; nhịp thời gian thực do luồng gửi giữ
        (ống đầy thì lệnh ghi tự chờ)."""
        try:
            self._ff.stdin.write(pcm)
            self._ff.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise LoiLoa(f"bộ mã hoá tiếng dừng giữa chừng ({str(exc)[:80]})") from exc

    def dong(self, cho: bool = True) -> None:
        """Hết tiếng: chờ gửi nốt các khung (đúng nhịp) rồi đóng kết nối."""
        ff, self._ff = self._ff, None
        if ff is not None:
            try:
                ff.stdin.close()
            except OSError:
                pass
            for t in self._luong:
                if t.name == "loa-cam-8086-gui" and cho:
                    t.join(TOI_DA_GIAY)
            if cho:
                time.sleep(_DUOI_GIAY)
            if ff.poll() is None:
                ff.kill()
            ff.wait()
        self._dung.set()
        if self.s is not None:
            try:
                self.s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.s.close()
            self.s = None
        for t in self._luong:
            if t is not threading.current_thread():
                t.join(2)


# ── EZVIZ / Hikvision: HCNetSDK cổng 8000 ─────────────────────────────────────
#
# EZVIZ H6C nhà (đo 28/09/2026) không có kênh ngược RTSP, không ONVIF, HTTP bị khoá — chỉ
# HCNetSDK qua cổng thiết bị 8000 mở được kênh đàm thoại (AAC 16 kHz). SDK chạy trong tiến trình
# con ``services/hik_noi.py`` (thư viện mã máy của hãng — sập thì c2a không sập theo) và SỐNG
# GIỮA CÁC LƯỢT: đăng nhập 0,6–1,3 s, mở kênh 0,02–0,27 s (đo 29/09/2026). Cùng cách với tích
# hợp dahua_talk của HA (``hik_talk.py``), đã chạy thật trên H6C.

CONG_HIK = 8000
#: Kênh đóng mà ngồi yên ngần này giây thì tiến trình con tự đăng xuất và thoát.
HIK_NGHI_GIAY = 60
#: Còn ngần này giây nữa là nó tự thoát thì thôi dùng lại — khỏi gửi lệnh đúng lúc nó thoát.
_HIK_BIEN_NGHI = 5.0
#: Chờ tiến trình con đăng nhập / mở kênh tối đa ngần này giây.
_HIK_CHO_MO = 15.0
#: Sau khi đóng kênh, H6C cần ~1,24 s mới cho mở lại — mở sớm hơn thì báo "(mã 29)" (thao tác
#: thất bại). Đo 29/09/2026: nói "alo, alo" là câu sau mất hẳn. Chờ nó nhả tối đa ngần này giây.
_HIK_CHO_NHA = 3.0
_HIK_MO_KENH = struct.pack(">I", 0xFFFFFFFF)
#: Chương trình tiến trình con (Python + ctypes).
_HIK_NOI = Path(__file__).with_name("hik_noi.py")
_HIK_DONG_KENH = struct.pack(">I", 0)
KIEU_LOA = ("", "hik")


def thu_muc_hik() -> Path:
    """Thư mục ``lib`` của HCNetSDK người dùng chép vào (không nằm trong ảnh / git)."""
    from services.config import DATA_DIR
    return Path(DATA_DIR) / "hcnetsdk" / "lib"


def kieu_loa(cam: dict[str, Any]) -> str:
    """``"hik"`` = HCNetSDK cổng 8000 (EZVIZ / Hikvision); ``""`` = Imou/Dahua (8086 → 37777)."""
    k = str(cam.get("loa_kieu") or "")
    return k if k in KIEU_LOA else ""


class _TroGiupHik:
    """Một tiến trình ``hik_noi`` đang sống: đã đăng nhập camera, mở / đóng kênh theo lệnh."""

    def __init__(self, ip: str, user: str, mk: str, cong: int = CONG_HIK) -> None:
        lib = thu_muc_hik()
        if not (lib / "libhcnetsdk.so").is_file():
            raise LoiLoa(f"chưa có HCNetSDK — chép thư mục lib của «Device Network SDK (Linux "
                         f"64-bit)» vào {lib}")
        env = {**os.environ, "HIK_LIB": str(lib), "HIK_MK": mk, "HIK_NGHI": str(HIK_NGHI_GIAY),
               "LD_LIBRARY_PATH": f"{lib}:{lib / 'HCNetSDKCom'}"}
        self.p = subprocess.Popen(
            [sys.executable, str(_HIK_NOI), ip, str(cong), user],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        self._du = b""
        self.ranh_tu = time.monotonic()
        dong = self._doc(_HIK_CHO_MO)
        if not dong.startswith("SAN "):
            self.close()
            raise LoiLoa(dong.removeprefix("LOI ") or "HCNetSDK không trả lời")
        _san, self.ma, tan_so = dong.split()[:3]
        self.tan_so = int(tan_so)

    def _doc(self, cho: float) -> str:
        """Một dòng từ kênh báo; hết giờ hoặc tiến trình đã thoát thì trả ""."""
        het = time.monotonic() + cho
        fd = self.p.stdout.fileno()
        while b"\n" not in self._du:
            con = het - time.monotonic()
            if con <= 0 or not select.select([fd], [], [], con)[0]:
                return ""
            b = os.read(fd, 4096)
            if not b:
                return ""
            self._du += b
        dong, self._du = self._du.split(b"\n", 1)
        return dong.decode("utf-8", "replace").strip()

    def gui(self, b: bytes) -> None:
        try:
            self.p.stdin.write(b)
            self.p.stdin.flush()
        except (OSError, ValueError) as exc:
            raise LoiLoa(f"HCNetSDK dừng giữa chừng ({str(exc)[:80]})") from exc

    def dung_lai_duoc(self) -> bool:
        return self.p.poll() is None and time.monotonic() - self.ranh_tu < HIK_NGHI_GIAY - _HIK_BIEN_NGHI

    def mo_kenh(self) -> None:
        het = time.monotonic() + _HIK_CHO_NHA
        while True:
            self.gui(_HIK_MO_KENH)
            dong = self._doc(_HIK_CHO_MO)
            if dong == "OK":
                return
            if not ("(mã 29)" in dong and time.monotonic() < het):
                raise LoiLoa(dong.removeprefix("LOI ") or "HCNetSDK không trả lời")
            time.sleep(0.3)

    def dong_kenh(self, cho: float) -> bool:
        """Báo hết tiếng; nó phát nốt phần đệm rồi đóng kênh. False = không đáp kịp."""
        try:
            self.gui(_HIK_DONG_KENH)
        except LoiLoa:
            return False
        xong = self._doc(cho) == "DONG"
        self.ranh_tu = time.monotonic()
        return xong

    def close(self) -> None:
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(3)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()


_hik: dict[str, _TroGiupHik] = {}             # ip → tiến trình đang giữ đăng nhập


def _tro_giup_hik(ip: str, user: str, mk: str) -> tuple[_TroGiupHik, bool]:
    """Tiến trình đang sống của camera ``ip`` (mới dựng nếu chưa có / sắp tự thoát). Trả
    ``(tiến trình, mới dựng)``. Gọi trong khoá của camera (``_khoa[ip]``)."""
    tg = _hik.get(ip)
    if tg is not None and tg.dung_lai_duoc():
        return tg, False
    if tg is not None:
        _hik.pop(ip, None)
        tg.close()
    tg = _TroGiupHik(ip, user, mk)
    _hik[ip] = tg
    return tg, True


class KenhHik:
    """Một lượt nói qua HCNetSDK — cùng giao diện ``KenhNoi8086`` (``tan_so``, ``phat_pcm``,
    ``dong``). ffmpeg mã hoá theo mã camera đòi; một luồng chuyển khung sang tiến trình con."""

    def __init__(self, ip: str, tg: _TroGiupHik) -> None:
        self.ip, self.tg, self.tan_so = ip, tg, tg.tan_so
        self._t_dau: float | None = None
        self._da_ghi = 0.0
        ra = (["-c:a", "aac", "-b:a", "32k", "-f", "adts"] if tg.ma == "AAC" else
              ["-c:a", "pcm_mulaw" if tg.ma == "G711U" else "pcm_alaw",
               "-f", "mulaw" if tg.ma == "G711U" else "alaw"])
        # ffmpeg khởi động song song lúc camera mở kênh (mã đã biết từ lúc đăng nhập).
        self._ff = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", *FFMPEG_TRUC_TIEP,
             "-f", "s16le", "-ar", str(self.tan_so), "-ac", "1", "-i", "pipe:0",
             *ra, "-flush_packets", "1", "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            tg.mo_kenh()
        except BaseException:
            self._ff.kill()
            self._ff.wait()
            raise
        self._luong = threading.Thread(target=self._chuyen, args=(self._ff,), name="loa-cam-hik",
                                       daemon=True)
        self._luong.start()

    def _chuyen(self, ff: subprocess.Popen) -> None:
        du = b""
        try:
            while b := ff.stdout.read1(4096):
                if self.tg.ma == "AAC":
                    khung, du = cat_adts(du + b)
                else:
                    du += b
                    n = len(du) // 160 * 160
                    khung, du = [du[i:i + 160] for i in range(0, n, 160)], du[n:]
                if khung:
                    self.tg.gui(b"".join(struct.pack(">I", len(k)) + k for k in khung))
        except (OSError, ValueError, LoiLoa) as exc:
            logger.warning({"event": "loa_camera_hik_gui_hong", "ip": self.ip, "loi": str(exc)[:120]})

    def phat_pcm(self, pcm: bytes) -> None:
        if self._t_dau is None:
            self._t_dau = time.monotonic()
        try:
            self._ff.stdin.write(pcm)
            self._ff.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise LoiLoa(f"bộ mã hoá tiếng dừng giữa chừng ({str(exc)[:80]})") from exc
        self._da_ghi += len(pcm) / (2 * self.tan_so)

    def dong(self, cho: bool = True) -> None:
        ff, self._ff = self._ff, None
        if ff is None:
            return
        try:
            ff.stdin.close()
        except OSError:
            pass
        self._luong.join(TOI_DA_GIAY if cho else 2)
        if ff.poll() is None:
            ff.kill()
        ff.wait()
        con = (self._t_dau or 0.0) + self._da_ghi - time.monotonic()
        if not self.tg.dong_kenh(max(0.0, con) + 5.0):
            # Không đáp → bỏ tiến trình này, lượt sau đăng nhập lại.
            if _hik.get(self.ip) is self.tg:
                _hik.pop(self.ip, None)
            self.tg.close()


def _mo_hik(ip: str, user: str, mk: str) -> KenhHik:
    tg, moi = _tro_giup_hik(ip, user, mk)
    try:
        return KenhHik(ip, tg)
    except LoiLoa:
        if moi or tg.p.poll() is None:
            raise
    # Tiến trình đang giữ đã chết (camera khởi động lại…) — đăng nhập lại một lần.
    _hik.pop(ip, None)
    tg.close()
    return KenhHik(ip, _tro_giup_hik(ip, user, mk)[0])


def mo_kenh(ip: str, user: str, mk: str, kieu: str = "") -> KenhNoi | KenhNoi8086 | KenhHik:
    """Mở kênh nói. ``kieu="hik"``: HCNetSDK cổng 8000. Còn lại (Imou/Dahua): cổng 8086 (16 kHz)
    trước; camera không có / từ chối thì 37777 (8 kHz) và nhớ ``_LUI_37777_GIAY`` để lần sau khỏi
    chờ hỏng. Người gọi phải ``dong()``."""
    if kieu == "hik":
        return _mo_hik(ip, user, mk)
    if _lui_37777.get(ip, 0.0) <= time.monotonic():
        try:
            return KenhNoi8086(ip, user, mk).__enter__()
        except (LoiLoa, OSError) as exc:
            _lui_37777[ip] = time.monotonic() + _LUI_37777_GIAY
            logger.warning({"event": "loa_camera_lui_37777", "ip": ip, "loi": str(exc)[:160]})
    return KenhNoi(ip, user, mk).__enter__()


# ── Camera trong sổ → địa chỉ nói ─────────────────────────────────────────────

def _tu_url(url: str) -> tuple[str, str, str] | None:
    u = urlsplit(url)
    if u.scheme.lower() != "rtsp" or not u.hostname:
        return None
    return u.hostname, unquote(u.username or ""), unquote(u.password or "")


def dia_chi(cam: dict[str, Any]) -> tuple[str, str, str]:
    """``(ip, tài khoản, mật khẩu)`` của camera, lấy từ chính nguồn đã khai."""
    if cam.get("kind") == "rtsp":
        kq = _tu_url(str(cam.get("url") or ""))
        if kq:
            return kq
        raise LoiLoa("URL RTSP của camera không có địa chỉ.")
    import httpx

    base = str(cam.get("base") or "").rstrip("/")
    auth = (str(cam["username"]), str(cam.get("password") or "")) if cam.get("username") else None
    try:
        r = httpx.get(f"{base}/api/streams", params={"src": str(cam.get("src") or "")},
                      auth=auth, timeout=HET_GIO)
        r.raise_for_status()
        nguon = r.json().get("producers") or []
    except Exception as exc:
        raise LoiLoa(f"không hỏi được go2rtc về camera ({str(exc)[:100]})") from exc
    for p in nguon:
        kq = _tu_url(str((p or {}).get("url") or ""))
        if kq:
            return kq
    raise LoiLoa("luồng go2rtc của camera này không trỏ thẳng vào camera (không có URL RTSP).")


# ── Chuyển âm thanh ──────────────────────────────────────────────────────────

def pcm_mono(am_thanh: bytes, tan_so: int) -> bytes:
    """Âm thanh bất kỳ (WAV, MP3…) → PCM16 mono ``tan_so``, bằng ffmpeg."""
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-ac", "1", "-ar", str(int(tan_so)), "-f", "s16le", "-t", str(TOI_DA_GIAY), "pipe:1"],
            input=am_thanh, capture_output=True, timeout=60)
    except FileNotFoundError as exc:
        raise LoiLoa("máy chủ thiếu ffmpeg nên chưa đổi được âm thanh") from exc
    if p.returncode or not p.stdout:
        loi = (p.stderr or b"").decode("utf-8", "ignore").strip().splitlines()
        raise LoiLoa(f"không đọc được âm thanh ({loi[-1][:120] if loi else 'lỗi không rõ'})")
    return p.stdout


# ── Lối vào ──────────────────────────────────────────────────────────────────

def _lay_cho_phat(ten: str) -> tuple[str, dict[str, Any]]:
    """Tra camera và kiểm công tắc loa (thẻ Camera → «🔊 Loa»). Tắt thì từ chối."""
    from services import camera_nha

    try:
        ten_that, cam = camera_nha._lay(ten)
    except camera_nha.LoiCamera as exc:
        raise LoiLoa(str(exc)) from exc
    if cam.get("cho_loa") is False:
        raise LoiLoa(f"Loa của camera «{ten_that}» đang tắt (Cài đặt → Camera nhà).")
    return ten_that, cam


def phat(ten: str, am_thanh: bytes) -> dict[str, Any]:
    """Phát ``am_thanh`` ra loa camera ``ten``. Trả ``{"ten", "giay"}``.

    Mỗi camera một lúc chỉ một phiên nói: hai tin cùng tới thì đọc lần lượt.
    """
    ten_that, cam = _lay_cho_phat(ten)
    ip, user, mk = dia_chi(cam)
    pcm = pcm_mono(am_thanh, _TAN_SO_HTTP)
    with _khoa_chung:
        khoa = _khoa.setdefault(ip, threading.Lock())
    t0 = time.monotonic()
    with khoa:
        try:
            kenh = mo_kenh(ip, user, mk, kieu_loa(cam))
            try:
                if kenh.tan_so != _TAN_SO_HTTP:
                    pcm = pcm_mono(am_thanh, kenh.tan_so)
                kenh.phat_pcm(pcm)
            finally:
                kenh.dong()
        except LoiLoa:
            raise
        except OSError as exc:
            raise LoiLoa(f"không nói được với camera ({str(exc)[:100]})") from exc
    giay = len(pcm) / (2 * kenh.tan_so)
    logger.info({"event": "loa_camera_phat", "camera": ten_that, "giay": round(giay, 1),
                 "tan_so": kenh.tan_so, "mat": round(time.monotonic() - t0, 1)})
    return {"ten": ten_that, "giay": round(giay, 1)}


def lenh_doi_luong(rate: int, channels: int = 1, ra: int = _TAN_SO) -> list[str]:
    """ffmpeg đổi PCM16 ``rate``/``channels`` → PCM16 mono ``ra`` Hz, nhả ngay từng khúc."""
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", *FFMPEG_TRUC_TIEP,
            "-f", "s16le", "-ar", str(int(rate)), "-ac", str(int(channels)), "-i", "pipe:0",
            "-ac", "1", "-ar", str(int(ra)), "-f", "s16le", "-flush_packets", "1", "pipe:1"]


class PhatLuong:
    """Phát ra loa camera theo luồng: tiếng tới khúc nào phát khúc đó.

    Dùng cho vệ tinh (Home Assistant đẩy tiếng TTS thành từng khúc PCM). ffmpeg
    đổi định dạng nguồn sang PCM16 mono đúng tần số của kênh (16 kHz qua 8086, 8 kHz
    qua 37777) ngay khi nhận; một luồng nền rút ra và gửi camera. Giữ khoá của camera
    suốt phiên như ``phat``.
    """

    def __init__(self, ten: str, rate: int, width: int = 2, channels: int = 1) -> None:
        self.ten, cam = _lay_cho_phat(ten)
        if width != 2:
            raise LoiLoa(f"chưa đọc được âm thanh {width * 8} bit")
        ip, user, mk = dia_chi(cam)
        with _khoa_chung:
            self._khoa = _khoa.setdefault(ip, threading.Lock())
        self._khoa.acquire()
        self._giu_khoa = True
        try:
            try:
                self._kenh = mo_kenh(ip, user, mk, kieu_loa(cam))
            except OSError as exc:
                # Như ``phat``: người gọi (vệ tinh, bộ đàm) chỉ bắt LoiLoa — lỗi mạng
                # lọt ra là đứt luôn kết nối HA / phiên bộ đàm vì camera rớt mạng.
                raise LoiLoa(f"không nói được với camera ({str(exc)[:100]})") from exc
            self._ff = subprocess.Popen(
                lenh_doi_luong(rate, channels, self._kenh.tan_so),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except BaseException:
            self._dong()
            raise
        self.giay = 0.0
        self._luong = threading.Thread(target=self._rut, name="loa-cam-luong", daemon=True)
        self._luong.start()

    def _rut(self) -> None:
        du = b""
        tan_so = self._kenh.tan_so
        khoi = tan_so * 2 * 40 // 1000                 # 40 ms
        try:
            while True:
                b = self._ff.stdout.read(khoi)
                if not b:
                    break
                du += b
                while len(du) >= khoi:
                    self._kenh.phat_pcm(du[:khoi])
                    self.giay += khoi / (2 * tan_so)
                    du = du[khoi:]
            if du:
                self._kenh.phat_pcm(du)
                self.giay += len(du) / (2 * tan_so)
        except (OSError, ValueError, LoiLoa) as exc:
            logger.warning({"event": "loa_camera_luong_hong", "camera": self.ten,
                            "loi": str(exc)[:120]})

    def them(self, pcm: bytes) -> None:
        try:
            self._ff.stdin.write(pcm)
        except (BrokenPipeError, ValueError):
            pass

    def xong(self, cho: float = TOI_DA_GIAY) -> float:
        """Hết tiếng: chờ phát nốt rồi đóng. Trả số giây đã phát."""
        try:
            self._ff.stdin.close()
        except OSError:
            pass
        self._luong.join(cho)
        self._dong()
        logger.info({"event": "loa_camera_phat_luong", "camera": self.ten, "giay": round(self.giay, 1)})
        return self.giay

    def _dong(self) -> None:
        ff = getattr(self, "_ff", None)
        if ff is not None and ff.poll() is None:
            ff.kill()
        kenh = getattr(self, "_kenh", None)
        if kenh is not None:
            kenh.dong()
        if self._giu_khoa:
            self._giu_khoa = False
            self._khoa.release()


def noi(ten: str, cau: str, giong: str = "") -> dict[str, Any]:
    """Đọc ``cau`` bằng giọng TTS của c2a rồi phát ra loa camera ``ten``."""
    from services.voice import engines

    # Giữ xuống dòng: TTS nghỉ theo dòng / khổ và nhận ra thơ để ngắt nhịp (29/09/2026 — trước
    # đây gộp cả bài thơ thành một dòng, chỉ còn ngắt ở dấu chấm).
    dong = [" ".join(d.split()) for d in str(cau or "").splitlines()]
    cau = re.sub(r"\n{3,}", "\n\n", "\n".join(dong)).strip()
    if not cau:
        raise LoiLoa("Chưa có câu nào để đọc.")
    try:
        wav = engines.synthesize(cau, giong)
    except Exception as exc:
        raise LoiLoa(f"không đọc được câu thành tiếng ({str(exc)[:100]})") from exc
    return phat(ten, wav)


# ── Bộ đàm: mic điện thoại (qua go2rtc của HA) → loa camera ──────────────────
#
# Chủ máy 24/09/2026: "dùng mic điện thoại qua HA phát ra loa giữ nguyên gốc, rồi
# nghe được người bên cam nói gì — giống như app Imou". Chiều nghe go2rtc đã có
# (nguồn ``#audio=opus`` cho WebRTC). Chiều nói: thẻ WebRTC Camera gửi mic vào
# go2rtc, go2rtc đẩy tiếng vào stdin một lệnh ``exec:…#backchannel=1`` (có từ
# go2rtc 1.9.10), lệnh ấy POST luồng A-law 8 kHz tới đây.
#
# Kênh nói chỉ mở KHI CÓ TIẾNG NGƯỜI: camera tự tắt mic trong lúc kênh nói mở
# (đo 24/09/2026), mà trình duyệt gửi tiếng liên tục suốt lúc thẻ còn mở mic —
# mở kênh suốt thì không bao giờ nghe được người bên camera trả lời.

#: Mức coi là có tiếng người (dBFS, RMS từng khúc). Mic bị tắt trong trình duyệt
#: gửi số 0 tuyệt đối; phòng yên sau lọc ồn của trình duyệt dưới -55.
BO_DAM_NGUONG_DB = -45.0
#: Im ngần này giây thì đóng kênh để nghe bên kia.
BO_DAM_IM_GIAY = 1.5
#: Giữ ngần này giây tiếng ngay trước lúc có tiếng — khỏi mất âm đầu câu.
BO_DAM_DEM_GIAY = 0.3


def _bang_alaw() -> list[int]:
    """G.711 A-law → PCM16 (đúng ``alaw2linear`` của bản mẫu ITU/Sun)."""
    bang = []
    for a in range(256):
        a ^= 0x55
        t = (a & 0x0F) << 4
        seg = (a & 0x70) >> 4
        t = t + 8 if seg == 0 else (t + 0x108) << (seg - 1)
        bang.append(t if a & 0x80 else -t)
    return bang


_ALAW = _bang_alaw()


def alaw_sang_pcm(b: bytes) -> bytes:
    import array

    return array.array("h", (_ALAW[x] for x in b)).tobytes()


def _muc_db(pcm: bytes) -> float:
    import array
    import math

    a = array.array("h", pcm[: len(pcm) // 2 * 2])
    if not a:
        return -120.0
    tong = sum(x * x for x in a)
    return 10 * math.log10(tong / len(a) / 32768.0 ** 2) if tong else -120.0


class BoDam:
    """Một phiên bộ đàm tới camera ``ten``: nhận tiếng, mở loa khi có người nói.

    ``them`` nhận A-law 8 kHz (go2rtc), ``them_pcm`` nhận PCM16 mono ``tan_so``
    (trình duyệt). Không thread-safe: một luồng gọi ``them*`` rồi ``dong``.
    """

    def __init__(self, ten: str, tan_so: int = _TAN_SO) -> None:
        self.ten, self.tan_so = ten, int(tan_so)
        self.giay = 0.0                   # tổng số giây đã phát ra loa
        self._phat: PhatLuong | None = None
        self._dem = b""                   # tiếng ngay trước lúc có người nói
        self._im = 0.0                    # số giây im liền từ tiếng cuối
        self.loi = ""                    # lỗi lần mở loa gần nhất ("" = ổn); khỏi ghi log dồn
        # Đo để chẩn đoán "bật bộ đàm mà không ra loa": tiếng có tới máy chủ không, to cỡ nào.
        self.nhan_giay = 0.0
        self.muc_max_db = -120.0

    def them(self, alaw: bytes) -> None:
        self.them_pcm(alaw_sang_pcm(alaw))

    def them_pcm(self, pcm: bytes) -> None:
        pcm = pcm[: len(pcm) // 2 * 2]
        if not pcm:
            return
        giay = len(pcm) / (2 * self.tan_so)
        muc = _muc_db(pcm)
        self.nhan_giay += giay
        self.muc_max_db = max(self.muc_max_db, muc)
        co_tieng = muc > BO_DAM_NGUONG_DB
        self._im = 0.0 if co_tieng else self._im + giay
        if self._phat is None:
            if not co_tieng:
                self._dem = (self._dem + pcm)[-int(BO_DAM_DEM_GIAY * self.tan_so) * 2:]
                return
            try:
                self._phat = PhatLuong(self.ten, self.tan_so)
            except LoiLoa as exc:
                if str(exc) != self.loi:
                    self.loi = str(exc)
                    logger.warning({"event": "bo_dam_khong_mo_duoc_loa", "camera": self.ten,
                                    "loi": self.loi[:160]})
                return
            self.loi = ""
            pcm, self._dem = self._dem + pcm, b""
        self._phat.them(pcm)
        if self._im >= BO_DAM_IM_GIAY:
            self.dong()

    def dong(self) -> None:
        """Đóng kênh nói (nếu đang mở) — camera nghe lại được. Nói tiếp thì mở lại."""
        phat, self._phat = self._phat, None
        self._dem, self._im = b"", 0.0
        if phat is not None:
            self.giay += phat.xong()
