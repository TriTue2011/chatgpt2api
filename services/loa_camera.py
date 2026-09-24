"""Loa camera — phát âm thanh ra loa của camera Dahua/Imou.

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
"""

from __future__ import annotations

import hashlib
import logging
import socket
import struct
import subprocess
import threading
import time
from typing import Any
from urllib.parse import unquote, urlsplit

logger = logging.getLogger(__name__)

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

    def __init__(self, ip: str, user: str, mk: str, *, cong: int = CONG_NOI,
                 het_gio: float = HET_GIO) -> None:
        self.ip, self.user, self.mk, self.cong, self.het_gio = ip, user, mk, cong, het_gio
        self.ctrl: socket.socket | None = None
        self.sub: socket.socket | None = None
        self.phien, self.cid = 0, ""
        self._dung = threading.Event()

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
            threading.Thread(target=self._xa, args=(s,), name="loa-cam-doc", daemon=True).start()
        threading.Thread(target=self._giu, name="loa-cam-giu", daemon=True).start()

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
                s.close()
        self.sub = self.ctrl = None


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

def pcm_8k(am_thanh: bytes) -> bytes:
    """Âm thanh bất kỳ (WAV, MP3…) → PCM16 mono 8 kHz, bằng ffmpeg."""
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-ac", "1", "-ar", str(_TAN_SO), "-f", "s16le", "-t", str(TOI_DA_GIAY), "pipe:1"],
            input=am_thanh, capture_output=True, timeout=60)
    except FileNotFoundError as exc:
        raise LoiLoa("máy chủ thiếu ffmpeg nên chưa đổi được âm thanh") from exc
    if p.returncode or not p.stdout:
        loi = (p.stderr or b"").decode("utf-8", "ignore").strip().splitlines()
        raise LoiLoa(f"không đọc được âm thanh ({loi[-1][:120] if loi else 'lỗi không rõ'})")
    return p.stdout


# ── Lối vào ──────────────────────────────────────────────────────────────────

def phat(ten: str, am_thanh: bytes) -> dict[str, Any]:
    """Phát ``am_thanh`` ra loa camera ``ten``. Trả ``{"ten", "giay"}``.

    Mỗi camera một lúc chỉ một phiên nói: hai tin cùng tới thì đọc lần lượt.
    """
    from services import camera_nha

    try:
        ten_that, cam = camera_nha._lay(ten)
    except camera_nha.LoiCamera as exc:
        raise LoiLoa(str(exc)) from exc
    ip, user, mk = dia_chi(cam)
    pcm = pcm_8k(am_thanh)
    with _khoa_chung:
        khoa = _khoa.setdefault(ip, threading.Lock())
    t0 = time.monotonic()
    with khoa:
        try:
            with KenhNoi(ip, user, mk) as kenh:
                kenh.phat_pcm(pcm)
        except LoiLoa:
            raise
        except OSError as exc:
            raise LoiLoa(f"không nói được với camera ({str(exc)[:100]})") from exc
    giay = len(pcm) / (2 * _TAN_SO)
    logger.info({"event": "loa_camera_phat", "camera": ten_that, "giay": round(giay, 1),
                 "mat": round(time.monotonic() - t0, 1)})
    return {"ten": ten_that, "giay": round(giay, 1)}


def noi(ten: str, cau: str, giong: str = "") -> dict[str, Any]:
    """Đọc ``cau`` bằng giọng TTS của c2a rồi phát ra loa camera ``ten``."""
    from services.voice import engines

    cau = " ".join(str(cau or "").split())
    if not cau:
        raise LoiLoa("Chưa có câu nào để đọc.")
    try:
        wav = engines.synthesize(cau, giong)
    except Exception as exc:
        raise LoiLoa(f"không đọc được câu thành tiếng ({str(exc)[:100]})") from exc
    return phat(ten, wav)
