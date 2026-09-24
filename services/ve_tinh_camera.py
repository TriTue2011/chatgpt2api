"""Vệ tinh camera — mỗi camera thành một "vệ tinh Assist" Wyoming cho Home Assistant.

Chủ máy 24/09/2026: "tích hợp thẳng vào HA để lấy của HA luôn", đánh thức bằng
"ok nabu" hoặc từ gọi riêng, tới đàm thoại hai chiều với nhà.

HA nối vào cổng của từng camera (tích hợp Wyoming → thêm ``máy_c2a:cổng``) và
coi nó như một thiết bị Assist: HA lo bắt từ gọi (openWakeWord), nhận giọng, hiểu
lệnh, đọc trả lời — đúng pipeline chọn trong trang thiết bị. Ở đây chỉ hai việc:

* **Tai**: tiếng mic camera lấy qua go2rtc (AAC 16 kHz → PCM16 mono 16 kHz bằng
  ffmpeg), đẩy liên tục thành ``audio-chunk`` sau một ``run-pipeline`` bắt đầu
  từ bước bắt từ gọi, ``restart_on_end`` để nghe lại ngay khi xong một lượt.
* **Miệng**: tiếng HA gửi về (trả lời pipeline, hay ``assist_satellite.announce``
  — thông báo/cảnh báo ra loa) phát qua ``loa_camera.PhatLuong`` rồi báo
  ``played``.

Giao thức bám đúng ``homeassistant/components/wyoming/assist_satellite.py``
(HA 2026.9.3): HA gửi ``describe`` → ta trả ``info`` có khoá ``satellite``; HA
gửi ``run-satellite`` → ta bắt đầu; ``ping`` phải trả ``pong`` trong 5 giây, không
thì HA coi như mất kết nối.

Cấu hình (``config`` khoá ``ve_tinh_camera``)::

    {"bat": true, "cong": {"Cam cửa": 10801, "Cam phòng khách": 10802}}

Cổng phải được mở ra ngoài container (stack Portainer) thì HA mới nối tới được.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

#: Tiếng mic gửi HA: PCM16 mono 16 kHz — đúng định dạng pipeline HA đòi.
_TAN_SO = 16000
#: 64 ms mỗi khúc, cỡ các vệ tinh khác gửi.
_KHUC = 2048

_luong: dict[int, threading.Thread] = {}
_khoa = threading.Lock()


def cau_hinh() -> dict[str, Any]:
    from services.config import config

    c = config.data.get("ve_tinh_camera")
    return c if isinstance(c, dict) else {}


def _info(ten: str) -> dict[str, Any]:
    return {"satellite": {
        "name": f"Camera {ten}",
        "description": f"Mic và loa của camera {ten} (c2a)",
        "attribution": {"name": "chatgpt2api", "url": "https://github.com/TriTue2011/chatgpt2api"},
        "installed": True,
        "version": "1",
    }}


def _lenh_mic(cam: dict[str, Any]) -> list[str]:
    """Lệnh ffmpeg đọc tiếng mic camera qua go2rtc, ra PCM16 mono 16 kHz."""
    base = str(cam.get("base") or "").rstrip("/")
    if cam.get("username"):
        # Mật khẩu có ký tự như "@" phải mã hoá mới nằm được trong URL.
        dau, _, sau = base.partition("://")
        base = f"{dau}://{quote(str(cam['username']), safe='')}:" \
               f"{quote(str(cam.get('password') or ''), safe='')}@{sau}"
    src = str(cam.get("src_ai") or cam.get("src") or "")
    url = f"{base}/api/stream.mp4?src={quote(src, safe='')}&video=none&audio=all"
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", url,
            "-vn", "-ac", "1", "-ar", str(_TAN_SO), "-f", "s16le", "pipe:1"]


class _VeTinh:
    """Một kết nối HA ↔ một camera."""

    def __init__(self, ten: str, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter) -> None:
        self.ten, self.reader, self.writer = ten, reader, writer
        self._ghi_khoa = asyncio.Lock()
        self._mic: asyncio.Task | None = None
        self._phat = None

    async def ghi(self, loai: str, data: dict | None = None, payload: bytes = b"") -> None:
        from services.voice.wyoming_server import _write_event

        async with self._ghi_khoa:
            await _write_event(self.writer, loai, data, payload)

    async def chay(self) -> None:
        from services.voice.wyoming_server import _read_event

        try:
            while True:
                ev = await _read_event(self.reader)
                if ev is None:
                    return
                await self._xu_ly(ev)
        finally:
            await self._tat_mic()
            if self._phat is not None:
                await asyncio.to_thread(self._phat.xong, 5.0)
                self._phat = None

    async def _xu_ly(self, ev: dict[str, Any]) -> None:
        loai, data = ev["type"], ev["data"]
        if loai == "describe":
            await self.ghi("info", _info(self.ten))
        elif loai == "ping":
            await self.ghi("pong", {"text": data.get("text")})
        elif loai == "run-satellite":
            await self._bat_mic()
        elif loai == "pause-satellite":
            await self._tat_mic()
        elif loai == "audio-start":
            await self._bat_dau_phat(data)
        elif loai == "audio-chunk":
            if self._phat is not None and ev["payload"]:
                await asyncio.to_thread(self._phat.them, ev["payload"])
        elif loai == "audio-stop":
            await self._het_phat()
        elif loai in ("detection", "transcript", "error"):
            logger.info({"event": "ve_tinh_camera", "camera": self.ten, "loai": loai,
                         "noi_dung": str(data.get("name") or data.get("text") or "")[:120]})
            if loai == "error" and self._mic is not None and not self._mic.done():
                # Pipeline lỗi thì HA thôi tự chạy lại, chờ vệ tinh xin lượt mới
                # (chống vòng lặp lỗi dồn dập) — xin lại sau một nhịp nghỉ.
                asyncio.create_task(self._xin_lai(2.0))

    # ── Miệng ────────────────────────────────────────────────────────────────

    async def _bat_dau_phat(self, data: dict[str, Any]) -> None:
        from services import loa_camera

        if self._phat is not None:
            await asyncio.to_thread(self._phat.xong, 5.0)
        try:
            self._phat = await asyncio.to_thread(
                loa_camera.PhatLuong, self.ten, int(data.get("rate") or 22050),
                int(data.get("width") or 2), int(data.get("channels") or 1))
        except loa_camera.LoiLoa as exc:
            self._phat = None
            logger.warning({"event": "ve_tinh_camera_loa_hong", "camera": self.ten,
                            "loi": str(exc)[:160]})

    async def _het_phat(self) -> None:
        phat, self._phat = self._phat, None
        if phat is not None:
            await asyncio.to_thread(phat.xong)
        # Báo xong kể cả khi loa hỏng: HA chờ "played" mới quay về nghe.
        await self.ghi("played")

    # ── Tai ─────────────────────────────────────────────────────────────────

    async def _bat_mic(self) -> None:
        if self._mic is not None and not self._mic.done():
            return
        await self.ghi("run-pipeline", {"start_stage": "wake", "end_stage": "tts",
                                        "restart_on_end": True})
        self._mic = asyncio.create_task(self._nghe())

    async def _xin_lai(self, cho: float) -> None:
        await asyncio.sleep(cho)
        if self._mic is not None and not self._mic.done():
            await self.ghi("run-pipeline", {"start_stage": "wake", "end_stage": "tts",
                                            "restart_on_end": True})

    async def _tat_mic(self) -> None:
        if self._mic is not None:
            self._mic.cancel()
            try:
                await self._mic
            except (asyncio.CancelledError, Exception):
                pass
            self._mic = None

    async def _nghe(self) -> None:
        """Đẩy tiếng mic liên tục; ffmpeg chết (camera rớt mạng…) thì mở lại."""
        from services import camera_nha

        while True:
            try:
                _ten, cam = camera_nha._lay(self.ten)
            except camera_nha.LoiCamera as exc:
                logger.warning({"event": "ve_tinh_camera_mic_hong", "camera": self.ten,
                                "loi": str(exc)[:160]})
                await asyncio.sleep(30)
                continue
            proc = await asyncio.create_subprocess_exec(
                *_lenh_mic(cam), stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL)
            ms = 0
            try:
                while True:
                    khuc = await proc.stdout.readexactly(_KHUC)
                    await self.ghi("audio-chunk", {"rate": _TAN_SO, "width": 2, "channels": 1,
                                                   "timestamp": ms}, khuc)
                    ms += _KHUC * 1000 // (2 * _TAN_SO)
            except asyncio.IncompleteReadError:
                logger.warning({"event": "ve_tinh_camera_mic_dut", "camera": self.ten})
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            await asyncio.sleep(2)


# ── Máy chủ ─────────────────────────────────────────────────────────────────

async def _phuc_vu(ten: str, cong: int) -> None:
    async def _ket_noi(reader, writer):
        from services.voice.wyoming_server import _bat_keepalive

        _bat_keepalive(writer.get_extra_info("socket"))
        logger.info({"event": "ve_tinh_camera_noi", "camera": ten,
                     "tu": str(writer.get_extra_info("peername"))})
        try:
            await _VeTinh(ten, reader, writer).chay()
        finally:
            writer.close()

    server = await asyncio.start_server(_ket_noi, "0.0.0.0", cong)
    logger.info({"event": "ve_tinh_camera_nghe", "camera": ten, "cong": cong})
    async with server:
        await server.serve_forever()


def _chay(ten: str, cong: int) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_phuc_vu(ten, cong))
    except Exception as exc:
        logger.warning({"event": "ve_tinh_camera_dung", "camera": ten, "cong": cong,
                        "loi": str(exc)[:160]})
    finally:
        loop.close()


def start() -> list[int]:
    """Mở cổng cho từng camera đã khai trong ``ve_tinh_camera.cong``. Trả các cổng đã mở."""
    c = cau_hinh()
    if not c.get("bat"):
        return []
    mo = []
    for ten, cong in (c.get("cong") or {}).items():
        try:
            cong = int(cong)
        except (TypeError, ValueError):
            continue
        with _khoa:
            if cong in _luong and _luong[cong].is_alive():
                continue
            th = threading.Thread(target=_chay, args=(str(ten), cong),
                                  name=f"ve-tinh-{cong}", daemon=True)
            _luong[cong] = th
        th.start()
        mo.append(cong)
    return mo
