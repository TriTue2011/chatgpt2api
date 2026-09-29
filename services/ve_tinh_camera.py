"""Trợ lý giọng nói qua camera — mic camera nghe, loa camera trả lời. Mỗi camera MỘT chế độ.

Chủ máy 24/09/2026: "tích hợp thẳng vào HA để lấy của HA luôn"; 28/09/2026: "làm c2a code mới
nhất. Có thể wakeup như HA khi không kết nối với HA. Nếu kết nối qua wyong phải tốt như qua
custom" và "phải có công tắc bật rõ ràng, tránh người không biết chạy cả custom, wyong, c2a".

Công tắc ``tro_ly_che_do`` của từng camera (thẻ Camera nhà) quyết định AI NGHE MIC — đúng
một đường:

* ``tat`` — không ai nghe mic camera này qua c2a (mặc định).
* ``ha``  — mic gửi **Home Assistant** qua vệ tinh Assist Wyoming (HA thêm ``máy_c2a:cổng``).
  Từ gọi do HA bắt (``tu_goi`` rỗng, openWakeWord của HA) hoặc do c2a bắt (``tu_goi`` = tên
  mô hình, như loa R1 — báo ``detection`` rồi xin pipeline từ bước NGHE). HA mất kết nối thì im.
* ``c2a`` — **c2a tự nghe, tự trả lời**, không cần HA: bắt từ gọi → ting → ghi tới khi người
  nói dứt → nhận giọng của c2a → tác tử chung (``orchestrate``, quyền như lệnh giọng nói từ HA)
  → đọc câu trả lời ra loa camera. HA có nối vào cổng cũng không nhận được tiếng mic.

Cổng vệ tinh (``ve_tinh_cong``) mở ở MỌI chế độ — HA vẫn phát thông báo, cảnh báo ra loa camera
qua đó (đo 28/09/2026: HA đang dùng vệ tinh «Camera Cam bếp» trong khi nghe tắt).

Bật chế độ nào ở đây thì TẮT vệ tinh của tích hợp khác (dahua_talk…) cho camera đó trong HA —
hai bên cùng nghe là một câu gọi hai lần trả lời.

Mang từ dahua_talk 0.2.5–0.2.9 (sự cố thật đã đo):
* Tiếng ting khi bắt được từ gọi; mic BỎ tiếng từ lúc bắt được tới khi ting dứt + 0,4 s — không
  thì ting lọt mic thành "tiếng", nhận giọng bịa chữ.
* Mic đứng im 10 giây (ffmpeg treo mà không đóng) thì mở lại — "idle hàng giờ mà không ai biết".
* Phát câu trả lời CÓ HẠN: HA không gửi ``audio-stop`` thì sau hạn vẫn báo ``played`` — không
  kẹt «Đang phản hồi».
* Loa camera đang nói thì mic bỏ tiếng (camera nghe lại chính nó), xong nói thì quên tiếng cũ.

Cấu hình trong bản ghi từng camera: ``tro_ly_che_do``, ``ve_tinh_cong`` (chế độ ``ha``),
``tu_goi``, ``do_nhay`` (thap/vua/cao), ``ting``, ``mic_tang_db``, ``cho_loa``. Bản ghi cũ chưa có
``tro_ly_che_do``: có cổng và ``cho_nghe`` thì coi là ``ha`` (giữ nguyên hành vi đang chạy).
"""

from __future__ import annotations

import asyncio
import collections
import io
import math
import struct
import threading
import time
import wave
from typing import Any
from urllib.parse import quote

# Logger của dự án: ``logging.getLogger(__name__)`` không có handler, mọi dòng bị nuốt.
from utils.log import logger

#: ffmpeg mic chết / đứng thì nghỉ ngần này giây rồi mở lại.
_MO_LAI_GIAY = 2.0
#: Tiếng mic: PCM16 mono 16 kHz — đúng định dạng pipeline HA đòi và openWakeWord đọc.
_TAN_SO = 16000
#: 64 ms mỗi khúc, cỡ các vệ tinh khác gửi.
_KHUC = 2048
#: Cứ ngần này giây xem lại cài đặt (chế độ, cổng, từ gọi…).
_NHIP = 3.0
#: ffmpeg xuất PCM ĐỀU kể cả lúc phòng yên — ngần này giây không có byte nào là luồng đứng.
_MIC_IM_GIAY = 10.0
#: Sau tiếng ting / sau lúc loa camera nói xong, mic còn bỏ tiếng ngần này giây (vang phòng,
#: camera phát trễ). Đo 26/09/2026 trên dahua_talk.
_DEM_SAU_NOI = 0.4
#: Bắt được từ gọi (chế độ ``ha``, c2a bắt) mà HA chưa trả chữ sau ngần này giây thì thôi gửi.
_LUOT_HA_TOI_DA = 15.0
#: Phát câu trả lời của HA: không nhận ``audio-stop`` sau ngần này giây kể từ khúc cuối thì coi
#: như đã phát xong (báo ``played``).
_PHAT_IM_TOI_DA = 20.0
#: Tự trả lời (chế độ ``c2a``): ghi tối đa ngần này giây; chưa ai nói sau ngần này thì bỏ.
_GHI_TOI_DA = 10.0
_CHO_NOI_GIAY = 5.0
#: Người nói dứt: im ngần này giây sau khi đã có tiếng. Xét lại mỗi `_XET_GIAY`.
_IM_LA_XONG = 0.9
_XET_GIAY = 0.3

MODES = ("tat", "ha", "c2a")

_luong: threading.Thread | None = None
_khoa = threading.Lock()
#: Tên camera → tai đang chạy; tên camera → kết nối HA đang đòi nghe (``run-satellite``).
#: Chỉ dùng trong vòng sự kiện của luồng vệ tinh.
_tai: dict[str, _Tai] = {}
_ket_noi: dict[str, _VeTinh] = {}


# ── Cài đặt ────────────────────────────────────────────────────────────────

def che_do(cam: dict[str, Any]) -> str:
    """Chế độ của camera. Bản ghi cũ: có cổng vệ tinh và cho nghe → ``ha``."""
    m = str(cam.get("tro_ly_che_do") or "")
    if m in MODES:
        return m
    return "ha" if cam.get("cho_nghe") is True else "tat"


def _cong(cam: dict[str, Any]) -> int:
    try:
        cong = int(cam.get("ve_tinh_cong") or 0)
    except (TypeError, ValueError):
        return 0
    return cong if 0 < cong < 65536 else 0


def tu_goi(cam: dict[str, Any]) -> str:
    """Từ gọi c2a bắt; rỗng = để HA bắt (chỉ có nghĩa ở chế độ ``ha``). Chế độ ``c2a`` không có
    HA nên luôn phải có từ gọi — mặc định «Trợ lý»."""
    t = str(cam.get("tu_goi") or "")
    if che_do(cam) == "c2a" and not t:
        return "tro_ly"
    return t


def ds_cong() -> dict[int, str]:
    """``{cổng: tên camera}`` các camera đã khai cổng vệ tinh."""
    from services import camera_nha

    ra: dict[int, str] = {}
    for cam in camera_nha.danh_sach(kem_bi_mat=True):
        if cong := _cong(cam):
            ra[cong] = str(cam["name"])
    return ra


def ds_nghe() -> dict[str, dict[str, Any]]:
    """Tên camera → bản ghi, cho các camera c2a phải nghe mic (chế độ ``ha`` hoặc ``c2a``)."""
    from services import camera_nha

    return {str(c["name"]): c for c in camera_nha.danh_sach(kem_bi_mat=True)
            if che_do(c) in ("ha", "c2a")}


def cho_nghe(ten: str) -> bool:
    """Camera có được nghe mic không. Không rõ thì KHÔNG (an toàn trước)."""
    from services import camera_nha

    try:
        _t, cam = camera_nha._lay(ten)
    except camera_nha.LoiCamera:
        return False
    return che_do(cam) != "tat"


def _info(ten: str) -> dict[str, Any]:
    return {"satellite": {
        "name": f"Camera {ten}",
        "description": f"Mic và loa của camera {ten} (c2a)",
        "attribution": {"name": "chatgpt2api", "url": "https://github.com/TriTue2011/chatgpt2api"},
        "installed": True,
        "version": "2",
    }}


def mic_tang_db(cam: dict[str, Any]) -> float:
    try:
        return max(0.0, min(30.0, float(cam.get("mic_tang_db") or 0)))
    except (TypeError, ValueError):
        return 0.0


def _lenh_mic(cam: dict[str, Any]) -> list[str]:
    """Lệnh ffmpeg đọc tiếng mic camera, ra PCM16 mono 16 kHz — qua go2rtc (luồng phụ nếu có
    khai), hoặc thẳng URL RTSP của camera khai kiểu RTSP (luồng phụ ``url_ai`` nếu có)."""
    if cam.get("kind") == "rtsp":
        vao = ["-rtsp_transport", "tcp", "-i", str(cam.get("url_ai") or cam.get("url") or "")]
    else:
        base = str(cam.get("base") or "").rstrip("/")
        if cam.get("username"):
            # Mật khẩu có ký tự như "@" phải mã hoá mới nằm được trong URL.
            dau, _, sau = base.partition("://")
            base = f"{dau}://{quote(str(cam['username']), safe='')}:" \
                   f"{quote(str(cam.get('password') or ''), safe='')}@{sau}"
        src = str(cam.get("src_ai") or cam.get("src") or "")
        vao = ["-i", f"{base}/api/stream.mp4?src={quote(src, safe='')}&video=none&audio=all"]
    # Mic camera lệch một chiều (DC): đo 24/09/2026 phòng khách, DC +0,0038 trong
    # khi tiếng nền thật chỉ -63,6 dBFS — khuếch đại luôn cả DC là mất chỗ cho
    # tiếng. Lọc thông cao 80 Hz bỏ DC (không đụng dải tiếng nói) TRƯỚC khi tăng,
    # rồi chặn đỉnh để nói gần mic không vỡ tiếng.
    loc = "highpass=f=80"
    if (tang := mic_tang_db(cam)) > 0:
        loc += f",volume={tang:g}dB,alimiter=limit=0.9:attack=5:release=50:level=false"
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *vao,
            "-vn", "-af", loc, "-ac", "1", "-ar", str(_TAN_SO), "-f", "s16le", "pipe:1"]


def tieng_ting(tan_so: int = _TAN_SO) -> bytes:
    """WAV hai nốt ngắn đi lên (Đô 6 → Son 6, ~0,3 s) — báo "đã nghe, nói đi". Ngắn có chủ ý:
    camera tự tắt mic lúc loa phát, tiếng báo dài là nuốt đầu câu lệnh (dahua_talk 0.2.5)."""
    ra = bytearray()
    for hz, giay in ((1047.0, 0.12), (1568.0, 0.18)):
        n = int(tan_so * giay)
        mem = int(tan_so * 0.01)                         # 10 ms vào/ra — khỏi tiếng "bụp"
        for i in range(n):
            bao = min(1.0, i / mem, (n - 1 - i) / mem)
            ra += struct.pack("<h", int(0.35 * 32767 * bao * math.sin(2 * math.pi * hz * i / tan_so)))
    return _wav(bytes(ra), tan_so)


def _wav(pcm: bytes, tan_so: int = _TAN_SO) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(tan_so)
        w.writeframes(pcm)
    return buf.getvalue()


def trang_thai_noi(pcm: bytes, nguong_rms: float) -> str:
    """Bản ghi từ sau tiếng ting tới giờ: ``chua`` (chưa ai nói), ``dang`` (đang nói), ``xong``
    (đã nói rồi im `_IM_LA_XONG` giây). Dò bằng Silero VAD (phân biệt tiếng nói bằng phổ — quạt,
    xe to không lừa được); chưa tải model VAD thì lùi về đo độ to từng 100 ms."""
    dai = len(pcm) / (2 * _TAN_SO)
    cuoi: float | None = None
    try:
        import numpy as np

        from services.voice import vad_silero

        doan = vad_silero.doan_co_tieng(
            np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0, _TAN_SO)
    except Exception:  # noqa: BLE001 — VAD hỏng thì lùi về đo độ to
        doan = None
    if doan is not None:
        cuoi = max((b for _a, b in doan), default=None)
    else:
        buoc = _TAN_SO // 10 * 2
        for i in range(0, len(pcm) - buoc + 1, buoc):
            if _rms(pcm[i:i + buoc]) >= nguong_rms:
                cuoi = (i + buoc) / (2 * _TAN_SO)
    if cuoi is None:
        return "chua"
    return "xong" if dai - cuoi >= _IM_LA_XONG else "dang"


def la_tieng_nguoi(pcm: bytes) -> bool:
    """Từ gọi phải là TIẾNG NGƯỜI. Đo 28/09/2026, 20 phút mic thật 4 camera: 21 lần mô hình từ
    gọi vượt 0,5 thì 12 lần Silero VAD không thấy tiếng nói nào (gió, xe, tiếng rít) — nhận giọng
    ra "Xin cảm ơn mọi người", "Chúng tôi" từ tiếng ồn. Chưa có model VAD thì tin mô hình từ gọi."""
    try:
        import numpy as np

        from services.voice import vad_silero

        doan = vad_silero.doan_co_tieng(
            np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0, _TAN_SO)
    except Exception:  # noqa: BLE001 — VAD hỏng thì tin mô hình từ gọi
        return True
    return doan is None or bool(doan)


def _rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if not n:
        return 0.0
    x = struct.unpack(f"<{n}h", pcm[:n * 2])
    return math.sqrt(sum(v * v for v in x) / n)


# ── Tai: mic một camera, dùng chung cho HA và cho tự trả lời ────────────────

class _Tai:
    """Đọc mic camera liên tục; bắt từ gọi (nếu c2a bắt); chuyển tiếng cho HA hoặc cho lượt tự
    trả lời. Chỉ chạy trong vòng sự kiện của luồng vệ tinh."""

    def __init__(self, ten: str) -> None:
        self.ten = ten
        self.cam: dict[str, Any] = {}
        self.ha: _VeTinh | None = None            # kết nối HA đang muốn nghe (chế độ ``ha``)
        self.bo_nghe = None                       # tu_goi.BoNghe khi c2a bắt từ gọi
        self._bo_nghe_cua: tuple[str, str] | None = None
        self._chan_toi = 0.0                      # mic bỏ tiếng tới mốc này (monotonic)
        self._dang_noi = False                    # loa camera đang nói — bỏ tiếng
        self._quen = False                        # bộ nghe phải quên tiếng cũ ở khúc tới
        self._dang_luot = False                   # đang trong một lượt (ghi / chờ HA)
        self._nhan: asyncio.Queue[bytes] | None = None   # người đang nhận tiếng (lượt tự trả lời)
        self._mic: asyncio.Task | None = None
        self._tang_dang_dung: float | None = None
        self.nen_rms: float | None = None         # mức ồn nền — ngưỡng cắt lời khi chưa có VAD
        self.lan_goi = 0.0                        # lúc bắt được từ gọi gần nhất (time.time)
        self.nghe_duoc = ""                       # câu nghe được gần nhất (chế độ c2a)
        self._vua_nghe: collections.deque[bytes] = collections.deque(maxlen=32)   # ~2 giây

    # cài đặt ------------------------------------------------------------------
    def ap(self, cam: dict[str, Any]) -> None:
        """Nhận cài đặt mới; đổi từ gọi / độ nhạy thì dựng lại bộ nghe, đổi tăng mic thì mở lại."""
        self.cam = cam
        tg = tu_goi(cam)
        khoa = (tg, str(cam.get("do_nhay") or "vua"))
        if not tg:
            self.bo_nghe, self._bo_nghe_cua = None, None
        elif khoa != self._bo_nghe_cua:
            try:
                from services import tu_goi as tgm
                self.bo_nghe = tgm.BoNghe(*khoa)
                self._bo_nghe_cua = khoa
            except Exception as exc:  # noqa: BLE001 — thiếu thư viện / mô hình: báo, không đổ
                self.bo_nghe, self._bo_nghe_cua = None, None
                logger.warning({"event": "ve_tinh_camera_tu_goi_hong", "camera": self.ten,
                                "tu_goi": tg, "loi": str(exc)[:160]})
        if self._mic is not None and self._tang_dang_dung is not None \
                and mic_tang_db(cam) != self._tang_dang_dung:
            self._mic.cancel()
            self._mic = None
        if self._mic is None or self._mic.done():
            self._mic = asyncio.create_task(self._doc_mic())

    def dung(self) -> None:
        if self._mic is not None:
            self._mic.cancel()
            self._mic = None

    # chặn mic -----------------------------------------------------------------
    def chan(self, giay: float) -> None:
        self._chan_toi = max(self._chan_toi, time.monotonic() + giay)

    def bat_dau_noi(self) -> None:
        self._dang_noi = True

    def het_noi(self) -> None:
        self._dang_noi = False
        self.chan(_DEM_SAU_NOI)
        # Không gọi dat_lai() ở đây: bộ nghe có thể đang chạy trong luồng khác (to_thread).
        self._quen = True

    # đọc mic ------------------------------------------------------------------
    async def _doc_mic(self) -> None:
        from services import camera_nha

        while True:
            try:
                _ten, cam = camera_nha._lay(self.ten)
            except camera_nha.LoiCamera as exc:
                logger.warning({"event": "ve_tinh_camera_mic_hong", "camera": self.ten,
                                "loi": str(exc)[:160]})
                await asyncio.sleep(30)
                continue
            self._tang_dang_dung = mic_tang_db(cam)
            proc = await asyncio.create_subprocess_exec(
                *_lenh_mic(cam), stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL)
            try:
                while True:
                    try:
                        khuc = await asyncio.wait_for(proc.stdout.readexactly(_KHUC), _MIC_IM_GIAY)
                    except TimeoutError:
                        logger.warning({"event": "ve_tinh_camera_mic_dung", "camera": self.ten,
                                        "giay": _MIC_IM_GIAY})
                        break
                    await self.nhan_khuc(khuc)
            except asyncio.IncompleteReadError:
                logger.warning({"event": "ve_tinh_camera_mic_dut", "camera": self.ten})
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            await asyncio.sleep(_MO_LAI_GIAY)

    async def nhan_khuc(self, khuc: bytes) -> None:
        """Một khúc mic: bỏ nếu đang chặn; chuyển cho người đang nhận; không thì dò từ gọi."""
        if self._dang_noi or time.monotonic() < self._chan_toi:
            return
        if self._nhan is not None:
            self._nhan.put_nowait(khuc)
            return
        ha = self.ha
        if ha is not None and ha.stream_lien_tuc:
            await ha.gui_tieng(khuc)             # HA tự bắt từ gọi: gửi liên tục như cũ
            return
        if not self._dang_luot:
            # Ồn nền: xuống ngay khi yên hơn, lên RẤT chậm — chính câu gọi (to, ~1 giây) không
            # được đẩy nền lên tới mức nuốt luôn câu lệnh ngay sau đó.
            r = _rms(khuc)
            self.nen_rms = r if self.nen_rms is None or r < self.nen_rms \
                else 0.999 * self.nen_rms + 0.001 * r
        if self.bo_nghe is None or self._dang_luot:
            return
        bo, quen, self._quen = self.bo_nghe, self._quen, False
        if quen:
            self._vua_nghe.clear()
        self._vua_nghe.append(khuc)
        if await asyncio.to_thread(_nghe_khuc, bo, khuc, quen):
            if not await asyncio.to_thread(la_tieng_nguoi, b"".join(self._vua_nghe)):
                logger.info({"event": "ve_tinh_camera_tu_goi_bo", "camera": self.ten,
                             "ly_do": "không có tiếng người", "diem": round(bo.diem_cao, 3)})
                bo.diem_cao = 0.0
                return
            logger.info({"event": "ve_tinh_camera_tu_goi", "camera": self.ten,
                         "tu_goi": bo.tu_goi, "diem": round(bo.diem_cao, 3)})
            bo.diem_cao = 0.0
            self.lan_goi = time.time()
            asyncio.create_task(self._bat_duoc())

    # một lượt -----------------------------------------------------------------
    async def _bat_duoc(self) -> None:
        che = che_do(self.cam)
        if self._dang_luot or (che == "ha" and self.ha is None):
            return                                 # chế độ HA mà HA chưa nối: không ting suông
        self._dang_luot = True
        try:
            await self.phat_ting()
            if che == "ha" and self.ha is not None:
                await self.ha.luot_tu_c2a(self)
            elif che == "c2a":
                await self._tu_tra_loi()
        except Exception as exc:  # noqa: BLE001 — một lượt hỏng không được làm điếc camera
            logger.warning({"event": "ve_tinh_camera_luot_hong", "camera": self.ten,
                            "loi": str(exc)[:200]})
        finally:
            self._nhan = None
            self._dang_luot = False

    async def phat_ting(self) -> None:
        """Tiếng báo đã bắt được từ gọi. Mic bỏ tiếng tới khi ting dứt + 0,4 s — không tới lúc
        đóng xong phiên loa (người dùng nghe thấy ting là nói luôn)."""
        if self.cam.get("ting") is False or self.cam.get("cho_loa") is False:
            return
        from services import loa_camera

        self.chan(30)                              # chặn trong lúc phát; mở lại ngay khi xong
        try:
            await asyncio.wait_for(asyncio.to_thread(loa_camera.phat, self.ten, tieng_ting()), 5.0)
        except Exception as exc:  # noqa: BLE001 — không kêu được ting thì vẫn nghe tiếp
            logger.info({"event": "ve_tinh_camera_ting_hong", "camera": self.ten,
                         "loi": str(exc)[:120]})
        finally:
            self._chan_toi = time.monotonic() + _DEM_SAU_NOI

    async def ghi_loi_noi(self) -> bytes:
        """Chế độ ``c2a``: ghi từ sau tiếng ting tới khi người nói dứt. Rỗng = không ai nói."""
        self._nhan = asyncio.Queue()
        pcm = bytearray()
        trang = "chua"
        bat = xet = time.monotonic()
        nguong = max(3 * (self.nen_rms or 0.0), 150.0)
        try:
            while time.monotonic() - bat < _GHI_TOI_DA:
                try:
                    pcm += await asyncio.wait_for(self._nhan.get(), 1.0)
                except TimeoutError:
                    continue
                if time.monotonic() - xet < _XET_GIAY:
                    continue
                xet = time.monotonic()
                trang = await asyncio.to_thread(trang_thai_noi, bytes(pcm), nguong)
                if trang == "xong" or (trang == "chua" and xet - bat >= _CHO_NOI_GIAY):
                    break
        finally:
            self._nhan = None
        return bytes(pcm) if trang != "chua" else b""

    async def _tu_tra_loi(self) -> None:
        """Nghe → hiểu → nói, trọn trong c2a (không cần HA)."""
        pcm = await self.ghi_loi_noi()
        if not pcm:
            return
        from services import voice

        try:
            chu = await asyncio.to_thread(voice.listen, _wav(pcm), "wav",
                                          session_id=f"camera:{self.ten}")
        except Exception as exc:  # noqa: BLE001 — VoiceError khi bản ghi không có chữ nào
            logger.info({"event": "ve_tinh_camera_khong_nghe_ra", "camera": self.ten,
                         "loi": str(exc)[:120]})
            return
        chu = (chu or "").strip()
        self.nghe_duoc = chu[:120]
        logger.info({"event": "ve_tinh_camera_nghe_duoc", "camera": self.ten, "chu": chu[:120]})
        if not chu:
            return
        tra_loi = await asyncio.to_thread(_hoi_tac_tu, self.ten, chu)
        if tra_loi and self.cam.get("cho_loa") is not False:
            from services import loa_camera

            self.bat_dau_noi()
            try:
                await asyncio.to_thread(loa_camera.noi, self.ten, tra_loi)
            finally:
                self.het_noi()


def trang_thai() -> dict[str, Any]:
    """Cho thẻ Camera nhà: từ gọi chọn được, có thư viện chưa, trợ lý KHÁC đang có trong HA (để
    người dùng thấy mà tắt một bên), và tai nào đang chạy."""
    from services import tu_goi as tgm

    ha_khac: list[dict[str, str]] = []
    try:
        from services import ha_client

        nen = ha_client.get_ha_area_index().get("entity_platform") or {}
        # Vệ tinh do c2a cho (Wyoming) không tính — cùng một đường với công tắc ở đây.
        ha_khac = [{"entity_id": e, "tich_hop": nen[e]} for e in sorted(nen)
                   if e.startswith("assist_satellite.") and nen[e] != "wyoming"]
    except Exception as exc:  # noqa: BLE001 — không hỏi được HA thì chỉ thiếu lời nhắc
        logger.info({"event": "ve_tinh_camera_hoi_ha_loi", "loi": str(exc)[:120]})
    tai = {ten: {"che_do": che_do(t.cam), "tu_goi": tu_goi(t.cam),
                 "mic": t._mic is not None and not t._mic.done(), "ha_noi": t.ha is not None,
                 "lan_goi": t.lan_goi or None, "nghe_duoc": t.nghe_duoc}
           for ten, t in list(_tai.items())}
    return {"co_thu_vien": tgm.co_thu_vien(),
            "tu_goi": [{"id": x, "ten": tgm.TEN_HIEN.get(x, x)} for x in tgm.cac_tu_goi()],
            "ha_khac": ha_khac, "tai": tai}


def _nghe_khuc(bo_nghe, khuc: bytes, quen: bool) -> bool:
    if quen:
        bo_nghe.dat_lai()
    return bo_nghe.them(khuc)


def _hoi_tac_tu(ten: str, chu: str) -> str:
    """Câu nói → câu trả lời, qua tác tử chung của c2a với quyền như lệnh giọng nói từ HA
    (``ha_allowed_groups`` — trần do chủ nhà đặt; chưa đặt thì không có trần)."""
    from services.agent.orchestrator import orchestrate
    from services.config import config

    hag = config.get().get("ha_allowed_groups")
    allow = {str(g) for g in hag} if isinstance(hag, list) else None
    out = orchestrate(chu, f"camera:{ten}", allow=allow, ha_fastpath=True)
    return str((out or {}).get("text") or "").strip()


# ── Vệ tinh Wyoming cho HA (chế độ ``ha``) ──────────────────────────────────

class _VeTinh:
    """Một kết nối HA ↔ một camera."""

    def __init__(self, ten: str, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter) -> None:
        self.ten, self.reader, self.writer = ten, reader, writer
        self._ghi_khoa = asyncio.Lock()
        self._phat = None
        self._het_han_phat: asyncio.Task | None = None
        self._ha_muon_nghe = False
        self.stream_lien_tuc = False              # HA tự bắt từ gọi → gửi mic liên tục
        self._luot_xong: asyncio.Event | None = None
        self._ms = 0

    @property
    def tai(self) -> _Tai | None:
        return _tai.get(self.ten)

    async def dat_nghe(self, lien_tuc: bool) -> None:
        """Bắt đầu / đổi cách đưa mic cho HA. ``lien_tuc`` = HA tự bắt từ gọi → xin pipeline từ
        bước từ gọi và gửi mic liên tục; không thì chờ c2a bắt từ gọi rồi mới gửi."""
        cu, self.stream_lien_tuc = self.stream_lien_tuc, lien_tuc
        if lien_tuc and not cu:
            await self.ghi("run-pipeline", {"start_stage": "wake", "end_stage": "tts",
                                            "restart_on_end": True})

    async def ghi(self, loai: str, data: dict | None = None, payload: bytes = b"") -> None:
        from services.voice.wyoming_server import _write_event

        async with self._ghi_khoa:
            await _write_event(self.writer, loai, data, payload)

    async def gui_tieng(self, khuc: bytes) -> None:
        await self.ghi("audio-chunk", {"rate": _TAN_SO, "width": 2, "channels": 1,
                                       "timestamp": self._ms}, khuc)
        self._ms += _KHUC * 1000 // (2 * _TAN_SO)

    async def chay(self) -> None:
        from services.voice.wyoming_server import _read_event

        try:
            while True:
                ev = await _read_event(self.reader)
                if ev is None:
                    return
                await self._xu_ly(ev)
        finally:
            self._thoi_nghe()
            await self._ket_thuc_phat(bao=False)

    def _thoi_nghe(self) -> None:
        if _ket_noi.get(self.ten) is self:
            del _ket_noi[self.ten]
        tai = self.tai
        if tai is not None and tai.ha is self:
            tai.ha = None
        self.stream_lien_tuc = False
        if self._luot_xong is not None:
            self._luot_xong.set()

    async def _xu_ly(self, ev: dict[str, Any]) -> None:
        loai, data = ev["type"], ev["data"]
        if loai == "describe":
            await self.ghi("info", _info(self.ten))
        elif loai == "ping":
            await self.ghi("pong", {"text": data.get("text")})
        elif loai == "run-satellite":
            self._ha_muon_nghe = True
            _ket_noi[self.ten] = self
            await _ghep_ha(self.ten)
        elif loai == "pause-satellite":
            self._ha_muon_nghe = False
            self._thoi_nghe()
        elif loai == "audio-start":
            await self._bat_dau_phat(data)
        elif loai == "audio-chunk":
            if self._phat is not None and ev["payload"]:
                await asyncio.to_thread(self._phat.them, ev["payload"])
                self._hen_het_phat()
        elif loai == "audio-stop":
            await self._ket_thuc_phat()
        elif loai == "detection":
            # HA bắt được từ gọi (chế độ HA bắt) → kêu ting như dahua_talk.
            logger.info({"event": "ve_tinh_camera", "camera": self.ten, "loai": loai,
                         "noi_dung": str(data.get("name") or "")[:60]})
            if self.stream_lien_tuc and (tai := self.tai) is not None:
                asyncio.create_task(tai.phat_ting())
        elif loai in ("transcript", "error"):
            logger.info({"event": "ve_tinh_camera", "camera": self.ten, "loai": loai,
                         "noi_dung": str(data.get("text") or data.get("message") or "")[:120]})
            if self._luot_xong is not None:
                self._luot_xong.set()            # lượt c2a bắt từ gọi: HA đã có chữ — thôi gửi
            if loai == "error" and self.stream_lien_tuc:
                # Pipeline lỗi thì HA thôi tự chạy lại — xin lượt mới sau một nhịp nghỉ.
                asyncio.create_task(self._xin_lai(2.0))

    async def luot_tu_c2a(self, tai: _Tai) -> None:
        """c2a vừa bắt được từ gọi: báo HA như vệ tinh tự bắt (loa R1, wyoming-satellite), rồi
        gửi tiếng mic tới khi HA trả chữ / báo lỗi / quá hạn."""
        if not self._ha_muon_nghe:
            return
        name = tu_goi(tai.cam)
        await self.ghi("detection", {"name": name, "timestamp": self._ms})
        await self.ghi("run-pipeline", {"start_stage": "asr", "end_stage": "tts",
                                        "restart_on_end": False})
        self._luot_xong = asyncio.Event()
        tai._nhan = asyncio.Queue()
        bat = time.monotonic()
        try:
            while not self._luot_xong.is_set() and time.monotonic() - bat < _LUOT_HA_TOI_DA:
                try:
                    khuc = await asyncio.wait_for(tai._nhan.get(), 0.5)
                except TimeoutError:
                    continue
                await self.gui_tieng(khuc)
        finally:
            tai._nhan = None
            self._luot_xong = None
        await self.ghi("audio-stop", {"timestamp": self._ms})

    async def _xin_lai(self, cho: float) -> None:
        await asyncio.sleep(cho)
        if self._ha_muon_nghe and self.stream_lien_tuc:
            await self.ghi("run-pipeline", {"start_stage": "wake", "end_stage": "tts",
                                            "restart_on_end": True})

    # ── Miệng ────────────────────────────────────────────────────────────────

    async def _bat_dau_phat(self, data: dict[str, Any]) -> None:
        from services import loa_camera

        await self._ket_thuc_phat(bao=False)
        if (tai := self.tai) is not None:
            tai.bat_dau_noi()
        try:
            self._phat = await asyncio.to_thread(
                loa_camera.PhatLuong, self.ten, int(data.get("rate") or 22050),
                int(data.get("width") or 2), int(data.get("channels") or 1))
        except loa_camera.LoiLoa as exc:
            self._phat = None
            logger.warning({"event": "ve_tinh_camera_loa_hong", "camera": self.ten,
                            "loi": str(exc)[:160]})
        self._hen_het_phat()

    def _hen_het_phat(self) -> None:
        """Hạn phát: không có khúc / ``audio-stop`` mới sau `_PHAT_IM_TOI_DA` giây thì tự kết
        thúc và báo ``played`` — HA chờ ``played`` mới quay về nghe."""
        if self._het_han_phat is not None:
            self._het_han_phat.cancel()

        async def _cho() -> None:
            await asyncio.sleep(_PHAT_IM_TOI_DA)
            logger.warning({"event": "ve_tinh_camera_phat_qua_han", "camera": self.ten})
            self._het_han_phat = None
            await self._ket_thuc_phat()

        self._het_han_phat = asyncio.create_task(_cho())

    async def _ket_thuc_phat(self, bao: bool = True) -> None:
        if self._het_han_phat is not None and self._het_han_phat is not asyncio.current_task():
            self._het_han_phat.cancel()
        self._het_han_phat = None
        phat, self._phat = self._phat, None
        dang_noi = phat is not None or (self.tai is not None and self.tai._dang_noi)
        try:
            if phat is not None:
                await asyncio.to_thread(phat.xong)
        finally:
            if dang_noi and (tai := self.tai) is not None:
                tai.het_noi()
        if bao:
            # Báo xong kể cả khi loa hỏng: HA chờ "played" mới quay về nghe.
            await self.ghi("played")


# ── Máy chủ ─────────────────────────────────────────────────────────────────

async def _mo_cong(ten: str, cong: int) -> asyncio.AbstractServer:
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
    return server


async def _ghep_ha(ten: str) -> None:
    """Mic của camera tới HA khi và chỉ khi: chế độ ``ha`` VÀ HA đang đòi nghe."""
    tai, vt = _tai.get(ten), _ket_noi.get(ten)
    if tai is not None and vt is not None and che_do(tai.cam) == "ha":
        tai.ha = vt
        await vt.dat_nghe(not tu_goi(tai.cam))
    elif tai is not None and tai.ha is not None:
        tai.ha.stream_lien_tuc = False
        tai.ha = None


async def _dong_bo_tai() -> None:
    """Tai chạy cho đúng các camera phải nghe; cài đặt mới áp ngay mỗi nhịp."""
    muon = await asyncio.to_thread(ds_nghe)
    for ten in [t for t in _tai if t not in muon]:
        tai = _tai.pop(ten)
        tai.dung()
        if tai.ha is not None:
            tai.ha.stream_lien_tuc = False
        logger.info({"event": "ve_tinh_camera_thoi_nghe", "camera": ten})
    for ten, cam in muon.items():
        tai = _tai.get(ten)
        if tai is None:
            tai = _tai[ten] = _Tai(ten)
            logger.info({"event": "ve_tinh_camera_bat_nghe", "camera": ten,
                         "che_do": che_do(cam), "tu_goi": tu_goi(cam) or "HA"})
        tai.ap(cam)
        await _ghep_ha(ten)


async def _quan_ly() -> None:
    """Giữ tai và cổng khớp cài đặt: thêm thì mở, bỏ/đổi thì đóng."""
    dang: dict[int, tuple[str, asyncio.AbstractServer]] = {}
    while True:
        try:
            await _dong_bo_tai()
            muon = await asyncio.to_thread(ds_cong)
        except Exception as exc:  # noqa: BLE001 — đọc sổ hỏng một nhịp thì giữ nguyên
            logger.warning({"event": "ve_tinh_camera_doc_so_loi", "loi": str(exc)[:120]})
            muon = {c: t for c, (t, _s) in dang.items()}
        for cong, (ten, server) in list(dang.items()):
            if muon.get(cong) != ten:
                server.close()
                del dang[cong]
                logger.info({"event": "ve_tinh_camera_dong_cong", "camera": ten, "cong": cong})
        for cong, ten in muon.items():
            if cong not in dang:
                try:
                    dang[cong] = (ten, await _mo_cong(ten, cong))
                except OSError as exc:
                    logger.warning({"event": "ve_tinh_camera_khong_mo_duoc", "camera": ten,
                                    "cong": cong, "loi": str(exc)[:120]})
        await asyncio.sleep(_NHIP)


def _chay() -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_quan_ly())
    except Exception as exc:  # noqa: BLE001 — vòng quản lý chết thì ghi lại, không kéo đổ app
        logger.warning({"event": "ve_tinh_camera_dung", "loi": str(exc)[:160]})
    finally:
        loop.close()


def start() -> None:
    """Chạy vòng quản lý (một luồng nền cho mọi camera)."""
    global _luong
    with _khoa:
        if _luong is not None and _luong.is_alive():
            return
        _luong = threading.Thread(target=_chay, name="ve-tinh-camera", daemon=True)
        _luong.start()
