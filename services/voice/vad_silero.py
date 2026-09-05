"""Dò giọng nói bằng Silero VAD — mạng nơ-ron thay cho ngưỡng năng lượng.

**Vì sao cần.** Chỗ cắt "đoạn có tiếng" của dự án đang đo NĂNG LƯỢNG (RMS 100 ms,
xem :func:`services.video_asr._khung_co_tieng`). Cách đó hỏng ở hai đầu: tiếng ồn
đều và to (quạt, xe, điều hoà) vượt ngưỡng nên bị nhận là tiếng nói, còn giọng nói
nhỏ trong bản thu ồn thì nằm dưới ngưỡng nên bị cắt mất. Silero phân biệt bằng
hình dạng phổ chứ không bằng độ to, nên không dính cả hai.

**Vì sao không thêm thư viện mới.** ``sherpa-onnx`` (dự án đã dùng cho STT) có sẵn
Silero VAD, nên chỉ cần thêm MỘT file model 629 KB trên volume. Giữ đúng nguyên
tắc đóng gói của phần giọng nói: CODE trong image, MODEL ngoài volume — tải bằng
``scripts/download_silero_vad.py``.

**Hợp đồng.** Mọi hàm ở đây KHÔNG BAO GIỜ ném lỗi ra ngoài và trả ``None`` (hoặc
dữ liệu vào nguyên vẹn) khi không chạy được — thiếu model, thiếu sherpa-onnx, hay
VAD không thấy tiếng nào. Người gọi lùi về đường cũ, nên bật/tắt model không đổi
hành vi của phần còn lại.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

#: Ngưỡng xác suất và các mốc thời gian — giữ mặc định của Silero, chỉ nới
#: `min_silence_duration` lên 0,35 s vì tiếng Việt có nhiều khoảng ngắt trong
#: câu; để 0,1 s như mặc định thì một câu bị băm thành nhiều mẩu rời.
NGUONG = 0.5
LANG_TOI_THIEU = 0.35
TIENG_TOI_THIEU = 0.15

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def _sherpa():
    import sherpa_onnx
    return sherpa_onnx


def duong_model():
    """Đường dẫn file model, hoặc None nếu chưa tải về volume."""
    try:
        from services.voice import config as vcfg
        return vcfg.vad_model_path()
    except Exception:
        return None


def co_san() -> bool:
    """Có đủ model và thư viện để chạy VAD không."""
    if duong_model() is None:
        return False
    try:
        _sherpa()
    except Exception:
        return False
    return True


def _bo_dd(rate: int):
    """Bộ dò dùng lại theo tần số lấy mẫu. None nếu không dựng được.

    Dựng lại bộ dò cho mỗi tệp là nạp lại model mỗi lần — nhớ theo `rate` vì
    `window_size` của Silero phụ thuộc tần số (512 mẫu ở 16 kHz, 256 ở 8 kHz).
    """
    khoa = f"cfg:{rate}"
    with _lock:
        if khoa in _cache:
            return _cache[khoa]
        cfg = None
        try:
            p = duong_model()
            if p is not None:
                so = _sherpa()
                cfg = so.VadModelConfig()
                cfg.silero_vad.model = str(p)
                cfg.silero_vad.threshold = NGUONG
                cfg.silero_vad.min_silence_duration = LANG_TOI_THIEU
                cfg.silero_vad.min_speech_duration = TIENG_TOI_THIEU
                cfg.sample_rate = int(rate)
        except Exception as exc:
            logger.warning("vad_silero: dựng cấu hình lỗi: %s", str(exc)[:150])
            cfg = None
        _cache[khoa] = cfg
        return cfg


def doan_co_tieng(mau, rate: int) -> list[tuple[float, float]] | None:
    """[(bắt đầu, kết thúc)] giây của các đoạn CÓ TIẾNG, hoặc None.

    ``mau`` là mảng numpy float32 mono trong [-1, 1]. Trả None nghĩa là "không
    dùng được VAD này" — người gọi phải lùi về cách cũ, KHÁC hẳn với danh sách
    rỗng nghĩa là "đã nghe và trong tệp không có tiếng nói nào".
    """
    cfg = _bo_dd(rate)
    if cfg is None:
        return None
    try:
        import numpy as np

        so = _sherpa()
        cua = int(cfg.silero_vad.window_size)
        if cua <= 0 or len(mau) < cua:
            return None
        # Bộ dò giữ trạng thái nội bộ nên PHẢI dựng mới mỗi tệp; chỉ `cfg`
        # (đường dẫn model) mới đáng nhớ lại.
        vad = so.VoiceActivityDetector(cfg, buffer_size_in_seconds=30)
        x = np.asarray(mau, dtype=np.float32).reshape(-1)
        ra: list[tuple[float, float]] = []

        def _gom() -> None:
            while not vad.empty():
                doan = vad.front
                bat = float(doan.start) / rate
                ra.append((bat, bat + len(doan.samples) / rate))
                vad.pop()

        for i in range(0, len(x) - cua + 1, cua):
            vad.accept_waveform(x[i:i + cua])
            # Gom liên tục: đệm chỉ giữ 30 giây, tệp dài hơn mà không lấy ra
            # thì những đoạn đầu bị đẩy đi mất.
            _gom()
        try:
            vad.flush()      # lấy nốt đoạn đang dở ở cuối tệp
        except Exception:
            pass
        _gom()
        return sorted(ra)
    except Exception as exc:
        logger.warning("vad_silero: dò tiếng lỗi: %s", str(exc)[:150])
        return None


def mat_na_khung(mau, rate: int, khung_giay: float = 0.1):
    """Mặt nạ boolean theo khung ``khung_giay`` giây, hoặc None.

    Cùng hình dạng với mặt nạ năng lượng của :mod:`services.video_asr` để cắm
    thẳng vào chỗ cũ mà không phải viết lại phần ghép đoạn.
    """
    doan = doan_co_tieng(mau, rate)
    if doan is None:
        return None
    try:
        import numpy as np

        khung = max(1, int(rate * khung_giay))
        n = len(mau) // khung
        if n <= 0:
            return None
        noi = np.zeros(n, dtype=bool)
        for bat, ket in doan:
            i = max(0, int(bat / khung_giay))
            j = min(n, int(ket / khung_giay) + 1)
            if j > i:
                noi[i:j] = True
        return noi if bool(noi.any()) else None
    except Exception as exc:
        logger.warning("vad_silero: dựng mặt nạ lỗi: %s", str(exc)[:150])
        return None


def cat_im_lang_wav(wav16: bytes, *, dem: float = 0.15) -> bytes:
    """WAV 16 kHz mono s16 → WAV cùng định dạng, bỏ các quãng không có tiếng.

    Trả NGUYÊN BẢN khi không chạy được VAD, khi tệp không có quãng lặng đáng
    kể, hoặc khi VAD không thấy tiếng nào — thà nghe cả tệp còn hơn nghe nhầm
    một tệp đã bị cắt trắng.

    ``dem`` là phần đệm hai đầu mỗi đoạn: cắt sát quá thì mất phụ âm đầu và âm
    cuối, đúng chỗ bộ nghe hay nuốt chữ.
    """
    if not wav16:
        return wav16
    try:
        import io
        import wave

        import numpy as np

        with wave.open(io.BytesIO(wav16), "rb") as w:
            rate, kenh, rong = w.getframerate(), w.getnchannels(), w.getsampwidth()
            pcm = w.readframes(w.getnframes())
        if kenh != 1 or rong != 2 or not pcm:
            return wav16
        mau = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        doan = doan_co_tieng(mau, rate)
        if not doan:
            return wav16

        giu = np.zeros(len(mau), dtype=bool)
        for bat, ket in doan:
            i = max(0, int((bat - dem) * rate))
            j = min(len(mau), int((ket + dem) * rate))
            if j > i:
                giu[i:j] = True
        so_giu = int(giu.sum())
        # Cắt dưới 15% thì không bõ: mọi lần cắt đều có rủi ro mất âm ở mép,
        # mà lợi ích (bớt thời gian nghe) thì không đáng kể.
        if so_giu <= 0 or so_giu > len(mau) * 0.85:
            return wav16

        ra = io.BytesIO()
        with wave.open(ra, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(np.frombuffer(pcm, dtype=np.int16)[giu].tobytes())
        return ra.getvalue()
    except Exception as exc:
        logger.warning("vad_silero: cắt im lặng lỗi: %s", str(exc)[:150])
        return wav16
