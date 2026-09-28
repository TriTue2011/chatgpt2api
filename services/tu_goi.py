"""Nghe TỪ GỌI ngay trong c2a (openWakeWord) — camera tự thức như loa R1, không cần HA.

Chủ máy 28/09/2026: "làm c2a code mới nhất. Có thể wakeup như HA khi không kết nối với HA".
Dùng ĐÚNG thư viện wyoming-openwakeword 2.x dùng (`pyopen-wakeword`: đặc trưng + mô hình
.tflite theo luồng, mỗi khúc 80 ms), nên điểm ở đây khớp điểm của container openWakeWord.

Từ gọi: năm mô hình có sẵn của thư viện (okay_nabu, hey_jarvis…) và «Trợ lý» tự huấn luyện
(`voices/wakeword/tro_ly.tflite` — bản 2, 28/09/2026). Độ nhạy là ngưỡng điểm, đo trên giọng
chưa học theo luồng:

    ngưỡng  gọi đúng (giọng máy / người thật)   câu nói thường thức nhầm
    0,5     171/171 · 4/4                        5/114
    0,7     170/171 · 4/4                        1/114
    0,9     155/171 · 3/4                        0/114

Mic THẬT 4 camera, 20 phút mỗi cái (28/09/2026) — số lần thức khi không ai gọi:

    ngưỡng  ban công  cửa  bếp  phòng khách
    0,5     18        12   1    0
    0,7     8         6    1    0
    0,9     0         0    0    0

12/21 lần là tiếng ồn (Silero VAD không thấy tiếng nói) — ``ve_tinh_camera`` bỏ các lần đó; mẫu
gọi thật vẫn thức đủ 4/4 ở mức vừa. Hai camera ngoài trời (gió, xe) nên để mức thấp.

Thư viện nạp MUỘN: CI chỉ cài theo uv.lock (không có gói này), còn ảnh Docker cài qua
``deploy/extra-requirements.txt``.

Chi phí đo trên máy chủ (Xeon E5-2630L v4 1,8 GHz, 28/09/2026): gần hết nằm ở hai mô hình đặc
trưng (mel + embedding). Để TFLite tự chọn số luồng thì 30 giây tiếng tốn 6,3 giây CPU (21%
một nhân mỗi camera) — mô hình quá nhỏ, chia luồng chỉ thêm tiền chờ; ép 1 luồng còn 3,9 giây
(13%), vẫn nhanh gấp 7 lần thời gian thật.
"""
from __future__ import annotations

import ctypes
import threading
import time
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
THU_MUC_RIENG = GOC / "voices" / "wakeword"
CO_SAN = ("okay_nabu", "hey_jarvis", "hey_mycroft", "alexa", "hey_rhasspy")
TEN_HIEN = {"tro_ly": "Trợ lý", "okay_nabu": "Okay Nabu", "hey_jarvis": "Hey Jarvis",
            "hey_mycroft": "Hey Mycroft", "alexa": "Alexa", "hey_rhasspy": "Hey Rhasspy"}
MUC_DO = {"thap": 0.9, "vua": 0.7, "cao": 0.5}
#: Bắt được một lần thì nghỉ ngần này giây (một câu gọi kéo dài vài khúc trên ngưỡng).
NGHI_GIAY = 2.0

_khoa_mot_luong = threading.Lock()


def _mot_luong() -> None:
    """Mọi bộ thông dịch TFLite của thư viện chạy 1 luồng. Thư viện gọi
    ``TfLiteInterpreterCreate(model, None)`` (không cho truyền tuỳ chọn) nên chen vào ngay sau
    lúc nó nạp thư viện C — làm một lần cho cả tiến trình."""
    from pyopen_wakeword import wakeword

    with _khoa_mot_luong:
        goc = wakeword.TfLiteWakeWord.__init__
        if getattr(goc, "_c2a_mot_luong", False):
            return

        def __init__(self, duong):
            goc(self, duong)
            lib = self.lib
            lib.TfLiteInterpreterOptionsCreate.restype = ctypes.c_void_p
            lib.TfLiteInterpreterOptionsSetNumThreads.argtypes = [ctypes.c_void_p, ctypes.c_int32]
            tao = lib.TfLiteInterpreterCreate

            def tao_mot_luong(model, _tuy_chon):
                o = lib.TfLiteInterpreterOptionsCreate()
                lib.TfLiteInterpreterOptionsSetNumThreads(o, 1)
                return tao(model, o)

            lib.TfLiteInterpreterCreate = tao_mot_luong

        __init__._c2a_mot_luong = True
        wakeword.TfLiteWakeWord.__init__ = __init__


def co_thu_vien() -> bool:
    try:
        import pyopen_wakeword  # noqa: F401
        return True
    except ImportError:
        return False


def cac_tu_goi() -> list[str]:
    """Từ gọi c2a nghe được: «Trợ lý» (và mọi .tflite riêng) trước, rồi các mô hình có sẵn."""
    rieng = sorted(p.stem for p in THU_MUC_RIENG.glob("*.tflite"))
    return rieng + [x for x in CO_SAN if x not in rieng]


def nguong(muc: str) -> float:
    return MUC_DO.get(str(muc or "vua"), MUC_DO["vua"])


class BoNghe:
    """Một luồng tiếng (một camera). ``them(pcm16 mono 16 kHz)`` → True khi vừa bắt được từ gọi."""

    def __init__(self, tu_goi: str, muc: str = "vua") -> None:
        from pyopen_wakeword import Model, OpenWakeWord, OpenWakeWordFeatures

        _mot_luong()
        tep = THU_MUC_RIENG / f"{tu_goi}.tflite"
        if tep.is_file():
            self._ww = OpenWakeWord.from_model(tep)
        elif tu_goi in CO_SAN:
            self._ww = OpenWakeWord.from_builtin(Model(tu_goi))
        else:
            raise ValueError(f"không có từ gọi «{tu_goi}»")
        self._dt = OpenWakeWordFeatures.from_builtin()
        self.tu_goi, self.nguong = tu_goi, nguong(muc)
        self.diem_cao = 0.0
        self._nghi_toi = 0.0

    def them(self, pcm: bytes) -> bool:
        bat = False
        for emb in self._dt.process_streaming(pcm):
            for p in self._ww.process_streaming(emb):
                p = float(p)
                self.diem_cao = max(self.diem_cao, p)
                if p >= self.nguong and time.monotonic() >= self._nghi_toi:
                    bat = True
        if bat:
            self._nghi_toi = time.monotonic() + NGHI_GIAY
            self.dat_lai()
        return bat

    def dat_lai(self) -> None:
        """Quên tiếng cũ — sau khi bắt được, hoặc sau lúc loa camera vừa nói (tiếng chính nó)."""
        self._ww.reset()
        self._dt.reset()
