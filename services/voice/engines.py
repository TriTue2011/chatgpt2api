"""Engine TTS/STT — chạy THẲNG trong tiến trình này, không cần container phụ.

TTS: binary `piper` (subprocess) đọc file .onnx trên volume → WAV bytes.
STT: `sherpa-onnx` + model Zipformer trên volume → text.
Cả hai có đường lùi `wyoming` (TCP + JSONL thuần, không thư viện) để tái dùng
server Wyoming sẵn có trong nhà.

Giao thức Wyoming: mỗi message là 1 dòng JSON header, theo sau là `data_length`
byte JSON và `payload_length` byte nhị phân.
"""

from __future__ import annotations

import io
import json
import logging
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import wave
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse

from services.voice import config as vcfg
from services.voice import tts_cache

logger = logging.getLogger(__name__)

_stt_lock = threading.Lock()
_recognizers: dict = {}     # lang → (key, sherpa_onnx.OfflineRecognizer)


class VoiceError(RuntimeError):
    """Lỗi tổng hợp/nhận dạng — caller bắt để báo người dùng tử tế."""


# ── Wyoming (dùng chung cho TTS + STT) ───────────────────────────────────────


def _parse_uri(uri: str) -> tuple[str, int]:
    u = uri if "://" in uri else f"tcp://{uri}"
    p = urlparse(u)
    if not p.hostname or not p.port:
        raise VoiceError(f"URL Wyoming không hợp lệ: {uri}")
    return p.hostname, int(p.port)


def _wyoming_send(sock: socket.socket, msg_type: str, data: dict | None = None,
                  payload: bytes = b"") -> None:
    data_bytes = json.dumps(data or {}).encode() if data is not None else b""
    header: dict = {"type": msg_type}
    if data_bytes:
        header["data_length"] = len(data_bytes)
    if payload:
        header["payload_length"] = len(payload)
    sock.sendall(json.dumps(header).encode() + b"\n" + data_bytes + payload)


def _wyoming_tts(text: str, uri: str, timeout: int = 60) -> bytes:
    """Gọi wyoming-piper → WAV bytes."""
    host, port = _parse_uri(uri)
    chunks: list[bytes] = []
    rate, width, channels = 22050, 2, 1
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        _wyoming_send(sock, "synthesize", {"text": text})
        f = sock.makefile("rb")
        while True:
            line = f.readline()
            if not line:
                break
            head = json.loads(line)
            dlen = int(head.get("data_length") or 0)
            plen = int(head.get("payload_length") or 0)
            data = json.loads(f.read(dlen)) if dlen else {}
            payload = f.read(plen) if plen else b""
            kind = head.get("type")
            if kind == "audio-start":
                rate = int(data.get("rate") or rate)
                width = int(data.get("width") or width)
                channels = int(data.get("channels") or channels)
            elif kind == "audio-chunk":
                chunks.append(payload)
            elif kind == "audio-stop":
                break
    if not chunks:
        raise VoiceError("Wyoming TTS không trả về âm thanh.")
    return _pcm_to_wav(b"".join(chunks), rate, width, channels)


def _wyoming_stt(wav_bytes: bytes, uri: str, timeout: int = 120) -> str:
    """Gửi WAV 16kHz mono tới wyoming-stt → text."""
    host, port = _parse_uri(uri)
    rate, width, channels, pcm = _wav_parts(wav_bytes)
    text = ""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        _wyoming_send(sock, "audio-start",
                      {"rate": rate, "width": width, "channels": channels})
        step = 8192
        for i in range(0, len(pcm), step):
            _wyoming_send(sock, "audio-chunk",
                          {"rate": rate, "width": width, "channels": channels},
                          pcm[i:i + step])
        _wyoming_send(sock, "audio-stop", {})
        f = sock.makefile("rb")
        while True:
            line = f.readline()
            if not line:
                break
            head = json.loads(line)
            dlen = int(head.get("data_length") or 0)
            plen = int(head.get("payload_length") or 0)
            data = json.loads(f.read(dlen)) if dlen else {}
            if plen:
                f.read(plen)
            if head.get("type") == "transcript":
                text = str(data.get("text") or "")
                break
    return text.strip()


# ── WAV helper ───────────────────────────────────────────────────────────────


def _pcm_to_wav(pcm: bytes, rate: int, width: int, channels: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _wav_parts(wav_bytes: bytes) -> tuple[int, int, int, bytes]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return (w.getframerate(), w.getsampwidth(), w.getnchannels(),
                w.readframes(w.getnframes()))


def to_wav_16k_mono(audio: bytes, src_hint: str = "") -> bytes:
    """Chuyển audio bất kỳ (ogg/opus của Telegram, m4a của Zalo…) → WAV 16kHz
    mono cho STT. Cần ffmpeg trong image; đã đúng định dạng thì giữ nguyên."""
    try:
        rate, width, channels, _ = _wav_parts(audio)
        if rate == 16000 and channels == 1 and width == 2:
            return audio
    except Exception:
        pass
    suffix = f".{src_hint.lstrip('.')}" if src_hint else ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as src:
        src.write(audio)
        src_path = src.name
    dst_path = src_path + ".wav"
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", src_path, "-ac", "1", "-ar", "16000", "-f", "wav", dst_path],
            capture_output=True, timeout=120,
        )
        if proc.returncode != 0 or not Path(dst_path).is_file():
            raise VoiceError(
                "Không chuyển được định dạng âm thanh"
                + (f": {proc.stderr.decode('utf-8', 'ignore')[:160]}" if proc.stderr else "")
            )
        return Path(dst_path).read_bytes()
    except FileNotFoundError as exc:
        raise VoiceError("Thiếu ffmpeg trong image — không giải mã được voice note.") from exc
    finally:
        for p in (src_path, dst_path):
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass


# ── TTS: VieNeu v3 Turbo (ONNX/CPU, 48 kHz, song ngữ Việt–Anh) ───────────────

# ── Nhả model TTS không dùng ────────────────────────────────────────────────
# Model đã nạp thì nằm lại trong tiến trình tới lần khởi động sau. Đo 23/09/2026:
# uvicorn 5,4 GB, gần hết là vùng nhớ ẩn danh của model; mốc 15/09: nạp VieNeu +
# ZeroTTS làm c2a từ 2,1 lên 4,1 GB. VieNeu không gán cho giọng mặc định, loa hay
# pipeline nào — chỉ ai đọc thử là chiếm ~1,5 GB mãi. Chủ máy chọn 23/09/2026:
# họ model nào 30 phút không dùng thì nhả, TRỪ họ đang được gán (giọng mặc định,
# giọng từng loa) hoặc đã được Assist gọi qua Wyoming — gán thì phải đọc ngay,
# không chờ nạp lại.

_NHA_SAU_GIAY = 30 * 60
_NHA_NHIP_GIAY = 5 * 60
_DUNG_LUC: dict[str, float] = {}
# Nhả họ nhẹ chẳng tiết kiệm được bao nhiêu mà lượt kế phải nạp lại vài giây
# (NghiTTS ~3 s). Chủ máy 24/09/2026: "giữ nghi và kokoro, zero". Không liệt kê
# họ nào nhẹ: lần nhả đầu ĐO RAM thật trả về; dưới ngưỡng thì từ đó giữ luôn.
# Đo trên c2a cùng ngày (MB trả về khi nhả): nghi 80–158, kokorovi 338,
# vieneunano 281, zerotts int8 464 — VieNeu Turbo ~1240 và ZeroTTS fp32 (máy
# khoẻ tự chọn, 867 MB trên đĩa) vượt ngưỡng nên vẫn nhả. Số đo ghi ra đĩa để
# khởi động lại (mỗi lần đổi ảnh) không phải nhả thử lần nữa.
_NHE_MB = 600.0
_RAM_HO: dict[str, float] | None = None       # họ → MB trả về khi nhả (đã đo)
_RAM_TEP = Path(vcfg.DATA_DIR) / "tts_ram_ho.json"
# Giọng đọc gần nhất của từng họ: khởi động lại (đổi ảnh) thì nạp sẵn đúng giọng
# ấy cho họ nhẹ, câu đầu không phải chờ nạp model (xem `nap_giong_da_dung`).
_GIONG_CUOI: dict[str, str] | None = None
_GIONG_TEP = Path(vcfg.DATA_DIR) / "tts_giong_cuoi.json"
_GIU_ASSIST: set[str] = set()
_nha_luong: threading.Thread | None = None


def _dung(ho: str) -> None:
    """Ghi mốc vừa dùng họ model; lần đầu thì dựng luồng dọn."""
    import time as _time

    global _nha_luong
    _DUNG_LUC[ho] = _time.monotonic()
    if _nha_luong is None:
        _nha_luong = threading.Thread(target=_vong_nha, name="tts-nha-model", daemon=True)
        _nha_luong.start()


def giu_cho_assist(voice: str) -> None:
    """Assist (Wyoming) vừa đọc giọng này: giữ họ ấy trong RAM."""
    if voice:
        _GIU_ASSIST.add(_ho_engine(voice))


def _ho_dang_gan() -> set[str]:
    giu = {_ho_engine(vcfg.tts_voice())} | set(_GIU_ASSIST)
    try:
        from services.voice import speakers
        giu |= {_ho_engine(str(sp.get("voice"))) for sp in speakers.list_speakers() if sp.get("voice")}
    except Exception as exc:   # không đọc được sổ loa thì thôi nhả lượt này
        logger.warning("voice: khong doc duoc so loa de giu model: %s", str(exc)[:120])
        return {"vieneu", "vieneunano", "zerotts", "kokorovi", "kokoro", "nghi", "dangu"}
    return giu


def _bo_model(ho: str) -> bool:
    """Bỏ model của một họ. Đang đọc dở (khoá bận) thì để lượt sau."""
    global _vieneu, _vieneu_loaded_precision, _kokoro, _kokoro_vi, _zerotts, _vieneu_nano
    khoa = {"vieneu": _vieneu_lock, "kokoro": _kokoro_lock, "zerotts": _zerotts_lock,
            "vieneunano": _vieneu_nano_lock,
            "kokorovi": _kokoro_vi_lock, "nghi": _nghi_lock, "dangu": _da_ngu_lock}.get(ho)
    if khoa is None or not khoa.acquire(blocking=False):
        return False
    try:
        if ho == "vieneu":
            _vieneu, _vieneu_loaded_precision = None, ""
        elif ho == "kokoro":
            _kokoro = None
        elif ho == "zerotts":
            _zerotts = None
        elif ho == "vieneunano":
            _vieneu_nano = None
        elif ho == "kokorovi":
            _kokoro_vi = None
            _kokoro_vi_vp.clear()
        elif ho == "nghi":
            _nghi.clear()
        elif ho == "dangu":
            _da_ngu.clear()
    finally:
        khoa.release()
    return True


def nha_model_nhan_roi(bay_gio: float | None = None) -> list[str]:
    """Nhả họ model quá `_NHA_SAU_GIAY` không dùng và không được gán."""
    import gc
    import time as _time

    bay_gio = _time.monotonic() if bay_gio is None else bay_gio
    giu = _ho_dang_gan()
    ram = _ram_ho()
    da_nha = []
    for ho, luc in list(_DUNG_LUC.items()):
        if ho in giu or bay_gio - luc < _NHA_SAU_GIAY or ram.get(ho, _NHE_MB) < _NHE_MB:
            continue
        truoc = _rss_mb()
        if not _bo_model(ho):
            continue
        gc.collect()
        # glibc giữ lại heap vừa giải phóng; không trả thì RSS chỉ giảm ~900/1240 MB
        # (đo 23/09/2026 với VieNeu). malloc_trim đưa phần trống về hệ điều hành.
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass
        ram[ho] = max(0.0, truoc - _rss_mb())
        _DUNG_LUC.pop(ho, None)
        da_nha.append(ho)
    if da_nha:
        _ghi_ram_ho(ram)
        logger.info("voice: nha model khong dung: %s (giu: %s)",
                    ", ".join(f"{ho} {ram[ho]:.0f} MB" for ho in da_nha), ",".join(sorted(giu)))
    return da_nha


def _rss_mb() -> float:
    import os
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20


def _ram_ho() -> dict[str, float]:
    global _RAM_HO
    if _RAM_HO is None:
        try:
            _RAM_HO = {str(k): float(v) for k, v in json.loads(_RAM_TEP.read_text()).items()}
        except (OSError, ValueError, AttributeError):
            _RAM_HO = {}
    return _RAM_HO


def _giong_cuoi() -> dict[str, str]:
    global _GIONG_CUOI
    if _GIONG_CUOI is None:
        try:
            _GIONG_CUOI = {str(k): str(v) for k, v in json.loads(_GIONG_TEP.read_text()).items()}
        except (OSError, ValueError, AttributeError):
            _GIONG_CUOI = {}
    return _GIONG_CUOI


def _nho_giong(voice: str) -> None:
    """Ghi giọng vừa đọc; chỉ ghi đĩa khi giọng của họ ấy đổi."""
    if not voice:
        return
    cu = _giong_cuoi()
    ho = _ho_engine(voice)
    if cu.get(ho) == voice:
        return
    cu[ho] = voice
    try:
        _GIONG_TEP.write_text(json.dumps(cu, ensure_ascii=False))
    except OSError as exc:
        logger.warning("voice: khong ghi duoc so giong gan nhat: %s", str(exc)[:120])


def nap_giong_da_dung(bo_qua: str = "") -> list[str]:
    """Nạp sẵn họ NHẸ đã từng đọc, bằng giọng gần nhất của họ ấy.

    Gọi nền lúc khởi động, sau `warmup_tts` (``bo_qua``: giọng nó vừa nạp).
    Chỉ họ đã đo là nhẹ (`_RAM_HO` < `_NHE_MB`): họ nặng như VieNeu Turbo không
    nạp sẵn. Lỗi họ nào bỏ họ ấy — lượt đọc thật tự nạp như cũ.
    """
    import time as _time

    ram = _ram_ho()
    da_nap = []
    for ho, giong in list(_giong_cuoi().items()):
        if giong == bo_qua or ram.get(ho, _NHE_MB) >= _NHE_MB:
            continue
        t0 = _time.perf_counter()
        try:
            synthesize("Xin chào.", giong)
        except Exception as exc:
            logger.warning("voice: nap san %s loi: %s", giong, str(exc)[:160])
            continue
        da_nap.append(ho)
        logger.info("voice: nap san %s (%d ms)", giong, int((_time.perf_counter() - t0) * 1000))
    return da_nap


def _ghi_ram_ho(ram: dict[str, float]) -> None:
    try:
        _RAM_TEP.write_text(json.dumps({k: round(v, 1) for k, v in ram.items()}))
    except OSError as exc:
        logger.warning("voice: khong ghi duoc so RAM ho model: %s", str(exc)[:120])


def _vong_nha() -> None:
    import time as _time

    while True:
        _time.sleep(_NHA_NHIP_GIAY)
        try:
            nha_model_nhan_roi()
        except Exception as exc:
            logger.warning("voice: vong nha model loi: %s", str(exc)[:160])


_vieneu_lock = threading.Lock()
_vieneu = None               # instance Vieneu (nạp 1 lần — mất vài giây + RAM)
_vieneu_loaded_precision: str = ""  # precision lúc nạp instance hiện tại


def _reset_vieneu() -> None:
    """Bỏ instance đã nạp (để load lại precision khác sau adaptive TTFA)."""
    global _vieneu, _vieneu_loaded_precision
    with _vieneu_lock:
        _vieneu = None
        _vieneu_loaded_precision = ""


def _get_vieneu():
    _dung("vieneu")
    if not vcfg.vieneu_model_ready():
        raise VoiceError(
            "Model VieNeu chưa tải (chạy scripts/download_vieneu_model.py).")
    global _vieneu, _vieneu_loaded_precision
    with _vieneu_lock:
        want = vcfg.vieneu_precision()
        if _vieneu is not None and _vieneu_loaded_precision == want:
            return _vieneu
        # Precision đổi (adaptive int8→fp32) → nạp lại.
        _vieneu = None
        # HF_HOME phải đặt TRƯỚC khi import huggingface_hub (đọc env lúc import).
        import os
        os.environ.setdefault("HF_HOME", str(vcfg.hf_cache_dir()))
        try:
            from vieneu import Vieneu
        except Exception as exc:
            raise VoiceError("Chưa cài gói vieneu trong image.") from exc
        try:
            # backend "auto": image :gpu → PyTorch; CPU → ONNX.
            # precision: VNNI→int8; không VNNI→fp32; adaptive TTFA có thể ép fp32.
            prec = want
            thr = vcfg.vieneu_threads()
            logger.info(
                "voice: nap VieNeu precision=%s vnni=%s threads=%s backend=%s",
                prec, vcfg.cpu_has_vnni(), thr, vcfg.vieneu_backend(),
            )
            _vieneu = Vieneu(backend=vcfg.vieneu_backend(),
                             precision=prec,
                             threads=thr)
            _vieneu_loaded_precision = prec
        except Exception as exc:
            raise VoiceError(f"Không nạp được VieNeu: {str(exc)[:160]}") from exc
        return _vieneu


def _vieneu_voice_name(voice: str) -> str:
    return voice[len(vcfg.VIENEU_PREFIX):].strip() \
        if voice.startswith(vcfg.VIENEU_PREFIX) else ""


# VieNeu v3 Turbo chỉ nhận đúng 3 style; ngoài danh sách → rơi về config.
VIENEU_STYLES = {"tu_nhien", "tin_tuc", "doc_truyen"}


def _vieneu_kwargs(voice: str, style: str = "") -> dict:
    st = style if style in VIENEU_STYLES else vcfg.vieneu_style()
    kwargs: dict = {
        "style": st,
        "apply_watermark": False,
        "max_chars": vcfg.vieneu_max_chars(),
    }
    name = _vieneu_voice_name(voice)
    if name:
        kwargs["voice"] = name
    return kwargs


def _float_to_pcm16(audio) -> bytes:
    """float32 [-1, 1] → PCM16 little-endian.

    nan_to_num trước khi clip: model ONNX thỉnh thoảng nhả NaN/inf ở đuôi câu,
    mà np.clip GIỮ NGUYÊN NaN, còn ép kiểu NaN sang số nguyên là hành vi không
    xác định — tuỳ CPU và bản numpy mà ra 0 hay ra giá trị hết biên (nghe thành
    tiếng "bụp"). Ép NaN thành im lặng để mọi máy cho cùng kết quả.
    """
    import numpy as np
    samples = np.nan_to_num(np.asarray(audio, dtype=np.float32),
                            nan=0.0, posinf=1.0, neginf=-1.0)
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def _vieneu_tts(text: str, voice: str, style: str = "") -> bytes:
    """Giọng "vieneu:<Tên>" → WAV 48 kHz. Tên rỗng = giọng mặc định của model."""
    eng = _get_vieneu()
    kwargs = _vieneu_kwargs(voice, style)
    # Khoá tuần tự: 2 câu cùng lúc trên CPU chỉ giành cache/nhân của nhau.
    with _vieneu_lock:
        audio = eng.infer(text, **kwargs)     # np.float32 mono @ 48 kHz
    if audio is None or len(audio) == 0:
        raise VoiceError("VieNeu không tạo được âm thanh.")
    return _pcm_to_wav(_float_to_pcm16(audio), 48000, 2, 1)


# ── TTS: Kokoro-82M (tiếng Anh, chạy qua sherpa-onnx sẵn có) ─────────────────

_kokoro_lock = threading.Lock()
_kokoro = None               # sherpa_onnx.OfflineTts (nạp 1 lần)


def _get_kokoro():
    _dung("kokoro")
    model_dir = vcfg.kokoro_model_dir()
    if model_dir is None:
        raise VoiceError(
            "Model Kokoro chưa tải (chạy scripts/download_kokoro_model.py).")
    global _kokoro
    with _kokoro_lock:
        if _kokoro is not None:
            return _kokoro
        try:
            import sherpa_onnx
        except Exception as exc:
            raise VoiceError("Chưa cài sherpa-onnx trong image.") from exc
        model_file = vcfg.kokoro_model_file() or (model_dir / "model.onnx")
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(model_file),
                    voices=str(model_dir / "voices.bin"),
                    tokens=str(model_dir / "tokens.txt"),
                    data_dir=str(model_dir / "espeak-ng-data"),
                ),
                provider="cpu",
                num_threads=vcfg.tts_threads(),
            ),
        )
        _kokoro = sherpa_onnx.OfflineTts(cfg)
        return _kokoro


_da_ngu_lock = threading.Lock()
_da_ngu: dict = {}   # "zh" | "ja-ko" → sherpa_onnx.OfflineTts (nạp 1 lần)


def _get_kokoro_zh():
    _dung("dangu")
    """Kokoro đa ngữ v1.1 — 100 giọng TRUNG (thu âm chuyên nghiệp) + 3 Anh.

    Khác gói kokoro-en đang chạy đúng phần frontend: thêm lexicon zh/en,
    dict/ và rule FST đọc số/ngày/số điện thoại kiểu Trung.
    """
    d = vcfg.KOKORO_ZH_DIR
    if not (d / "voices.bin").is_file() or not list(d.glob("model*.onnx")):
        raise VoiceError(
            "Model Kokoro tiếng Trung chưa tải (chạy scripts/download_tts_da_ngu.py zh).")
    with _da_ngu_lock:
        if "zh" in _da_ngu:
            return _da_ngu["zh"]
        import sherpa_onnx
        model_file = sorted(d.glob("model*.onnx"))[0]
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(model_file),
                    voices=str(d / "voices.bin"),
                    tokens=str(d / "tokens.txt"),
                    data_dir=str(d / "espeak-ng-data"),
                    dict_dir=str(d / "dict"),
                    lexicon=f"{d / 'lexicon-us-en.txt'},{d / 'lexicon-zh.txt'}",
                ),
                provider="cpu",
                num_threads=vcfg.tts_threads(),
            ),
            rule_fsts=",".join(str(d / f) for f in
                               ("date-zh.fst", "number-zh.fst", "phone-zh.fst")
                               if (d / f).is_file()),
        )
        _da_ngu["zh"] = sherpa_onnx.OfflineTts(cfg)
        return _da_ngu["zh"]


def _get_supertonic():
    _dung("dangu")
    """Supertonic-3 (31 ngôn ngữ, dùng cho ja/ko) — frontend theo Unicode,
    không cần espeak-ng-data; sherpa-onnx ≥1.13.2 (bản ghim 1.13.4 có)."""
    d = vcfg.SUPERTONIC_DIR
    if not (d / "tts.json").is_file():
        raise VoiceError(
            "Model Supertonic chưa tải (chạy scripts/download_tts_da_ngu.py ja-ko).")
    with _da_ngu_lock:
        if "ja-ko" in _da_ngu:
            return _da_ngu["ja-ko"]
        import sherpa_onnx

        def _mot(mau: str) -> str:
            hits = sorted(d.glob(mau))
            if not hits:
                raise VoiceError(f"Gói Supertonic thiếu file khớp '{mau}'.")
            return str(hits[0])

        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                supertonic=sherpa_onnx.OfflineTtsSupertonicModelConfig(
                    duration_predictor=_mot("duration_predictor*.onnx"),
                    text_encoder=_mot("text_encoder*.onnx"),
                    vector_estimator=_mot("vector_estimator*.onnx"),
                    vocoder=_mot("vocoder*.onnx"),
                    tts_json=str(d / "tts.json"),
                    unicode_indexer=_mot("unicode_indexer*"),
                    voice_style=_mot("voice*.bin"),
                ),
                provider="cpu",
                num_threads=vcfg.tts_threads(),
            ),
        )
        _da_ngu["ja-ko"] = sherpa_onnx.OfflineTts(cfg)
        return _da_ngu["ja-ko"]


def so_giong_da_ngu(lang: str) -> int:
    """Số giọng model của tiếng đó có (zh 103 · ja/ko 10 — đo 14/08).

    Cho UI dựng danh sách chọn. Model chưa tải → 0 (không raise).
    """
    try:
        lang = str(lang or "").lower()
        if lang == "zh":
            return int(_get_kokoro_zh().num_speakers)
        if lang in ("ja", "ko"):
            return int(_get_supertonic().num_speakers)
    except Exception as exc:
        logger.info("đếm giọng %s lỗi: %s", lang, str(exc)[:120])
    return 0


def synthesize_da_ngu(text: str, lang: str, sid: int = -1) -> bytes:
    """Đọc BẢN DỊCH tiếng zh/ja/ko → WAV bytes — cho phiên dịch đàm thoại.

    Tách khỏi ``synthesize`` (vi/en, nhiều giọng, chèn lặng theo câu): ở đây
    câu ngắn, mỗi tiếng một giọng mặc định, ưu tiên độ trễ.

    ``sid >= 0`` đè giọng trong config — để NGHE THỬ từng giọng trước khi lưu.
    """
    text = (text or "").strip()
    if not text:
        raise VoiceError("Không có nội dung để đọc.")
    lang = str(lang or "").lower()
    if lang == "zh":
        tts = _get_kokoro_zh()
        giong = sid if sid >= 0 else vcfg.kokoro_zh_sid()
        with _da_ngu_lock:
            audio = tts.generate(text, sid=giong, speed=1.0)
    elif lang in ("ja", "ko"):
        import sherpa_onnx
        tts = _get_supertonic()
        gc = sherpa_onnx.GenerationConfig()
        gc.sid = sid if sid >= 0 else vcfg.supertonic_sid(lang)
        # 8 bước, KHÔNG phải 4. Đo bằng scripts/kiem_phat_am.py (đọc lại 3 lần
        # mỗi câu, cho STT nghe lại): tiếng Hàn ở 4 bước rụng phụ âm — mất /s/
        # trong 음식 và ㅆ chập chờn — còn 8 và 16 bước đều đọc đủ 16/16 âm.
        # Chọn 8 vì đó là mức thấp nhất đã đạt: đọc 4,58 giây tiếng Hàn tốn
        # 2,83 giây (16 bước tốn 4,9 giây, tức CHẬM HƠN thời gian thực nên hại
        # cho đàm thoại trực tiếp). Đây là model kiểu flow-matching, ít bước thì
        # phụ âm là phần rụng trước tiên.
        gc.num_steps = 8
        gc.speed = 1.0
        gc.extra["lang"] = lang   # Supertonic bắt buộc khai tiếng theo lượt
        with _da_ngu_lock:
            audio = tts.generate(text, gc)
    else:
        raise VoiceError(f"Chưa có giọng đọc cho tiếng '{lang}'.")
    samples = audio.samples or []
    if not samples:
        raise VoiceError("Không tạo được âm thanh.")
    return _pcm_to_wav(_float_to_pcm16(samples), int(audio.sample_rate), 2, 1)


def _kokoro_cau(text: str, voice: str):
    """Một lần gọi Kokoro tiếng Anh, trả từng câu qua callback sherpa."""
    tts = _get_kokoro()
    name = voice[len(vcfg.KOKORO_PREFIX):].strip() \
        if voice.startswith(vcfg.KOKORO_PREFIX) else ""
    sid = vcfg.kokoro_sid(name)

    def chay(cb):
        with _kokoro_lock:
            return tts.generate(text, sid=sid, speed=1.0, callback=cb)

    yield from _tu_callback(chay)


def _kokoro_tts(text: str, voice: str) -> bytes:
    """Giọng "kokoro:<tên>" → WAV 24 kHz (chỉ đọc tiếng Anh)."""
    khuc = list(_phat_cau(text, 24000, lambda doan: _kokoro_cau(doan, voice), chen_nghi=False))
    pcm = b"".join(buf for _r, buf in khuc)
    if not pcm:
        raise VoiceError("Kokoro không tạo được âm thanh.")
    return _pcm_to_wav(pcm, 24000, 2, 1)


# ── TTS: NghiTTS (19 giọng tiếng Việt, VITS 22,05 kHz qua sherpa-onnx) ───────

_nghi_lock = threading.Lock()
# Mỗi giọng là MỘT model riêng (~60–80 MB) nên không nạp hết được: giữ vài
# giọng dùng gần đây theo kiểu LRU, quá hạn mức thì bỏ giọng cũ nhất.
_nghi: OrderedDict[str, object] = OrderedDict()


def _nghi_voice_id(voice: str) -> str:
    """"nghi:ban-mai" → "ban-mai"; không phải giọng NghiTTS → rỗng."""
    if not voice.startswith(vcfg.NGHI_PREFIX):
        return ""
    return voice[len(vcfg.NGHI_PREFIX):].strip()


def _get_nghi(voice_id: str):
    _dung("nghi")
    """Engine sherpa-onnx cho một giọng, nạp một lần rồi tái dùng."""
    from services.voice import nghitts_voices as nv

    if nv.get(voice_id) is None:
        raise VoiceError(f"Không có giọng NghiTTS '{voice_id}' trong danh mục.")
    model_dir = vcfg.nghi_voice_dir(voice_id)
    if model_dir is None:
        raise VoiceError(
            f"Giọng NghiTTS '{voice_id}' chưa tải "
            f"(chạy scripts/download_nghitts_voices.py {voice_id}).")
    espeak = vcfg.nghi_espeak_data_dir()
    if espeak is None:
        raise VoiceError(
            "Thiếu espeak-ng-data cho NghiTTS "
            "(chạy scripts/download_nghitts_voices.py --espeak).")
    with _nghi_lock:
        cached = _nghi.get(voice_id)
        if cached is not None:
            _nghi.move_to_end(voice_id)
            return cached
        try:
            import sherpa_onnx
        except Exception as exc:
            raise VoiceError("Chưa cài sherpa-onnx trong image.") from exc
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(model_dir / nv.MODEL_FILE),
                    tokens=str(model_dir / nv.TOKENS_FILE),
                    data_dir=str(espeak),
                ),
                provider="cpu",
                num_threads=vcfg.tts_threads(),
            ),
        )
        tts = sherpa_onnx.OfflineTts(cfg)
        _nghi[voice_id] = tts
        while len(_nghi) > vcfg.nghi_max_loaded():
            old_id, _ = _nghi.popitem(last=False)
            logger.info("voice: bo model NghiTTS '%s' khoi RAM (het han muc)", old_id)
        return tts


def _nghi_tts(text: str, voice: str) -> bytes:
    """Giọng "nghi:<mã>" → WAV 22,05 kHz tiếng Việt."""
    from services.voice import nghitts_voices as nv

    pcm = b"".join(buf for _rate, buf in _nghi_phat(text, voice, chen_nghi=False))
    if not pcm:
        raise VoiceError("NghiTTS không tạo được âm thanh.")
    return _pcm_to_wav(pcm, nv.SAMPLE_RATE, 2, 1)


def _tu_callback(chay):
    """Chạy ``chay(callback)`` ở thread riêng, yield từng câu float32.

    Callback trả 1 để model đọc tiếp (đo sherpa 1.13.4: trả 0 thì dừng sau
    câu đầu). Không có callback nào thì dùng mẫu trả về cuối.
    """
    import numpy as np

    hop: queue.Queue = queue.Queue()
    thay = False

    def cb(samples, _tien) -> int:
        nonlocal thay
        audio = np.array(samples, dtype=np.float32, copy=True).ravel()
        if audio.size:
            thay = True
            hop.put(audio)
        return 1

    def vong() -> None:
        try:
            xong = chay(cb)
            mau = getattr(xong, "samples", None)
            if not thay and mau is not None and len(mau):
                hop.put(np.array(mau, dtype=np.float32, copy=True).ravel())
        except Exception as exc:
            hop.put(exc)
        finally:
            hop.put(None)

    threading.Thread(target=vong, name="tts-cau", daemon=True).start()
    while True:
        muc = hop.get()
        if muc is None:
            return
        if isinstance(muc, Exception):
            raise muc
        yield muc


def _nghi_cau(text: str, voice: str):
    """Một lần gọi NghiTTS, trả từng câu ngay khi sherpa đọc xong câu đó."""
    from services.voice import nghitts_voices as nv

    tts = _get_nghi(_nghi_voice_id(voice) or nv.DEFAULT_ID)

    doc = _doc_vi(text)

    def chay(cb):
        with _nghi_lock:
            return tts.generate(doc, sid=0, speed=1.0, callback=cb)

    yield from _tu_callback(chay)


def _phat_cau(text: str, rate: int, lay_cau, *, chen_nghi: bool = True):
    """Yield (rate, pcm16). ``lay_cau(đoạn)`` yield float32 từng câu của một lần generate."""
    sent_ms, _clause, para_ms, jitter = _silence_plan() if chen_nghi else (0, 0, 0, 0)
    khoi = _tach_doan(text) or [(text, "")]
    da_co = False
    for piece, _sau in khoi:
        dau_doan = True
        for mau in lay_cau(piece):
            if da_co:
                kind = "paragraph" if dau_doan else "sentence"
                base = para_ms if kind == "paragraph" else sent_ms
                gap = _silence_pcm(_jitter_ms(base, jitter), rate) if base > 0 else b""
                if gap:
                    yield rate, gap
            dau_doan = False
            da_co = True
            pcm = _float_to_pcm16(mau)
            if pcm and chen_nghi:
                pcm = _cat_lang_hai_dau(pcm, rate)
            if pcm:
                yield rate, pcm


def _nghi_phat(text: str, voice: str, *, chen_nghi: bool = True):
    """Yield (22050, pcm16). Một lần generate cho cả đoạn, nghỉ chèn giữa câu."""
    from services.voice import nghitts_voices as nv

    return _phat_cau(
        text, nv.SAMPLE_RATE, lambda doan: _nghi_cau(doan, voice), chen_nghi=chen_nghi)


# ── TTS: Kokoro tiếng Việt + vig2p (14 giọng, 24 kHz, ONNX) ─────────────────
# Xem services/voice/kokoro_vi.py: vì sao thêm họ này (giữ thanh điệu tốt nhất
# trong các họ đo được) và vì sao phiên âm cả mệnh đề thay vì từng từ.

_kokoro_vi_lock = threading.Lock()
_kokoro_vi: tuple | None = None           # (session, vocab, context_length)
_kokoro_vi_vp: dict[str, object] = {}     # mã giọng → voicepack numpy (500 KB/giọng)


def _get_kokoro_vi(voice_id: str):
    _dung("kokorovi")
    from services.voice import kokoro_vi as kv

    if kv.get(voice_id) is None:
        raise VoiceError(f"Không có giọng Kokoro Việt '{voice_id}' trong danh mục.")
    base = vcfg.kokoro_vi_dir()
    if base is None or voice_id not in vcfg.kokoro_vi_downloaded_ids():
        raise VoiceError(
            f"Giọng Kokoro Việt '{voice_id}' chưa tải "
            f"(chạy scripts/download_kokoro_vi.py {voice_id}).")
    global _kokoro_vi
    with _kokoro_vi_lock:
        if _kokoro_vi is None:
            try:
                import onnxruntime as ort
            except Exception as exc:
                raise VoiceError("Chưa cài onnxruntime trong image.") from exc
            so = ort.SessionOptions()
            so.intra_op_num_threads = vcfg.tts_threads()
            so.inter_op_num_threads = 1
            from services import onnx_xa

            # Chạy trên GPU nhà khi được (onnx_xa), lỗi thì CPU tại chỗ — cùng graph.
            sess = onnx_xa.lai("kokoro_vi", ort.InferenceSession(
                str(base / kv.MODEL_FILE), so, providers=["CPUExecutionProvider"]))
            cfg = json.loads((base / kv.CONFIG_FILE).read_text(encoding="utf-8"))
            _kokoro_vi = (sess, cfg["vocab"], int(cfg["plbert"]["max_position_embeddings"]))
        if voice_id not in _kokoro_vi_vp:
            import numpy as np
            _kokoro_vi_vp[voice_id] = np.load(base / kv.get(voice_id).npy_file)
        return _kokoro_vi + (_kokoro_vi_vp[voice_id],)


def _kokoro_vi_tts(text: str, voice: str) -> bytes:
    """Giọng "kokorovi:<mã>" → WAV 24 kHz."""
    import numpy as np
    from services.voice import kokoro_vi as kv

    vid = voice[len(vcfg.KOKORO_VI_PREFIX):].strip() or kv.DEFAULT_ID
    sess, vocab, ctx_len, voicepack = _get_kokoro_vi(vid)
    parts = []
    # Kokoro nhận tối đa ~510 âm vị một lượt; mẩu 160 ký tự còn cách xa trần.
    for seg in _split_sentences(text, max_chars=160):
        ps = kv.phien_am(seg)
        if not ps:
            continue
        with _kokoro_vi_lock:
            wav, _dur = sess.run(None, {
                "input_ids": kv.input_ids(ps, vocab, ctx_len),
                "ref_s": kv.chon_style(voicepack, len(ps)),
                "speed": np.asarray(1.0, dtype=np.float32),
            })
        parts.append(np.asarray(wav, dtype=np.float32).reshape(-1))
    if not parts:
        raise VoiceError("Kokoro Việt không tạo được âm thanh.")
    audio = np.concatenate(parts)
    # Model thả biên độ vượt 1,0 (đo 15/09/2026: đỉnh 1,16 ở câu thử) — để
    # nguyên thì _float_to_pcm16 cắt đỉnh, nghe rè. Hạ cả câu cho vừa khung.
    dinh = float(np.abs(audio).max())
    if dinh > 0.99:
        audio = audio * (0.99 / dinh)
    return _pcm_to_wav(_float_to_pcm16(audio), kv.SAMPLE_RATE, 2, 1)


# ── TTS: VieNeu v3 Nano (11 giọng, 24 kHz, ONNX) ────────────────────────────
# Họ giọng NHANH cho máy yếu: đo 24/09/2026 trên máy chủ RTF 0,68 ở 16 bước
# (v3 Turbo ~2). Flow-matching sinh trọn một mẩu mỗi lần — không stream theo
# khung, nhưng mẩu ngắn (≤140 ký tự) và nhanh hơn thời gian thực. Engine tự
# chuẩn hoá số, tự cắt mẩu và tự chèn nghỉ giữa mẩu.

_vieneu_nano_lock = threading.Lock()
_vieneu_nano = None


def _get_vieneu_nano():
    _dung("vieneunano")
    base = vcfg.vieneu_nano_dir()
    if base is None:
        raise VoiceError("Model VieNeu Nano chưa tải (chạy scripts/download_vieneu_nano.py).")
    global _vieneu_nano
    with _vieneu_nano_lock:
        if _vieneu_nano is None:
            try:
                from vieneu.v3nano import V3NanoVieNeuTTS
            except Exception as exc:
                raise VoiceError("Gói vieneu trong image chưa có v3 Nano.") from exc
            _vieneu_nano = V3NanoVieNeuTTS(onnx_dir=str(base), threads=vcfg.vieneu_threads())
        return _vieneu_nano


def _vieneu_nano_ten(voice: str) -> str | None:
    return voice[len(vcfg.VIENEU_NANO_PREFIX):].strip() or None


def _vieneu_nano_tts(text: str, voice: str) -> bytes:
    """Giọng "vieneunano:<Tên>" → WAV 24 kHz."""
    import numpy as np

    tts = _get_vieneu_nano()
    with _vieneu_nano_lock:
        audio = np.asarray(tts.infer(text, voice=_vieneu_nano_ten(voice)), dtype=np.float32).reshape(-1)
    if not audio.size:
        raise VoiceError("VieNeu Nano không tạo được âm thanh.")
    return _pcm_to_wav(_float_to_pcm16(audio), int(tts.sample_rate), 2, 1)


def _vieneu_nano_stream(text: str, voice: str):
    """Yield (24000, pcm16) từng mẩu ngay khi xong (kể cả khoảng nghỉ engine chèn)."""
    import numpy as np

    tts = _get_vieneu_nano()
    rate = int(tts.sample_rate)
    with _vieneu_nano_lock:
        for mau in tts.infer_stream(text, voice=_vieneu_nano_ten(voice)):
            pcm = _float_to_pcm16(np.asarray(mau, dtype=np.float32).reshape(-1))
            if pcm:
                yield rate, pcm


# ── TTS: ZeroTTS (8 giọng tiếng Việt, 48 kHz, ONNX) ─────────────────────────
# Đo 15/09/2026 trên máy chủ: sai thanh 0/1409 âm tiết trong câu thường (ngang
# Kokoro Việt). RTF ~1,2 ở 4 luồng nên đoạn dài vẫn chậm hơn thời gian thực,
# nhưng synthesize_stream có tiếng sau khung đầu (~0,3s khi model đã nạp)
# thay vì chờ hết câu.

_zerotts_lock = threading.Lock()
_zerotts = None
#: Bản ZeroTTS chế độ auto đã chọn cho tiến trình này ("fp32"/"int8"). Nhớ qua
#: các lần model tự nhả để không đo lại mỗi lần nạp.
_zerotts_chon = ""
_ZEROTTS_CAU_DO = "Xin chào, hôm nay trời nhiều mây, chiều tối có mưa rào nhẹ."


def _nap_zerotts(base):
    from zerotts import ZeroTTS

    # Constructor warmup=True: đẩy một khung giả qua mọi session để lần đọc
    # thật không gánh allocator. Đo 23/09/2026: nạp + warm ~11s.
    return ZeroTTS(base, intra_op_num_threads=vcfg.zerotts_threads())


def _rtf_zerotts(tts) -> float:
    """Giây tạo cho mỗi giây tiếng, đo trên câu mẫu (lần đầu chỉ để làm nóng)."""
    import time as _time

    import numpy as np

    vid = _zerotts_voice_id("")
    tts.synthesize(_ZEROTTS_CAU_DO, voice=vid)
    t0 = _time.perf_counter()
    audio = np.asarray(tts.synthesize(_ZEROTTS_CAU_DO, voice=vid), dtype=np.float32).reshape(-1)
    return (_time.perf_counter() - t0) / max(audio.size / float(tts.sample_rate), 1e-6)


def _get_zerotts():
    """Nạp ZeroTTS. auto: fp32 kịp thời gian thực thì giữ, không thì int8.

    Đo 24/09/2026 trên máy chủ (Xeon E5-2630L v4, không VNNI), xen kẽ hai bản
    cùng câu: fp32 RTF 2,39, int8 1,13; tiếng đầu 1,22 → 0,63s; STT nghe lại
    sai 1/152 chữ ở cả hai. Máy khoẻ đọc fp32 kịp thì không đổi gì.
    """
    global _zerotts, _zerotts_chon
    _dung("zerotts")
    fp32 = vcfg.zerotts_model_dir()
    if fp32 is None:
        raise VoiceError("Model ZeroTTS chưa tải (chạy scripts/download_zerotts.py).")
    int8 = vcfg.zerotts_int8_dir()
    muon = vcfg.zerotts_precision()
    with _zerotts_lock:
        if _zerotts is None:
            try:
                import zerotts  # noqa: F401
            except Exception as exc:
                raise VoiceError("Chưa cài gói zerotts trong image.") from exc
            if int8 is None or muon == "fp32":
                _zerotts = _nap_zerotts(fp32)
            elif muon == "int8" or _zerotts_chon == "int8":
                _zerotts = _nap_zerotts(int8)
            elif _zerotts_chon == "fp32":
                _zerotts = _nap_zerotts(fp32)
            else:
                tts = _nap_zerotts(fp32)
                rtf = _rtf_zerotts(tts)
                _zerotts_chon = "fp32" if rtf <= 1.0 else "int8"
                logger.info("voice: ZeroTTS fp32 RTF=%.2f → dùng %s", rtf, _zerotts_chon)
                if _zerotts_chon == "int8":
                    del tts
                    tts = _nap_zerotts(int8)
                _zerotts = tts
        return _zerotts


def _zerotts_voice_id(voice: str) -> str:
    return voice[len(vcfg.ZEROTTS_PREFIX):].strip() or vcfg.ZEROTTS_VOICES[0][0]


def _zerotts_doan(text: str) -> list[str]:
    """Chuẩn hoá số/ngày rồi cắt đoạn dài — model học trên từng câu.

    Cả đường WAV lẫn đường stream dùng chung hàm này. Hai đường cắt khác nhau
    là hai giọng khác nhau cho cùng một câu.
    """
    from zerotts import normalize_vi_text
    from zerotts.chunking import chunk_text, clean_segment_punctuation, normalize_punctuation

    out: list[str] = []
    for seg in chunk_text(normalize_punctuation(normalize_vi_text(text)), max_chunk_sec=15):
        seg = clean_segment_punctuation(seg)
        if seg.strip():
            out.append(seg)
    return out


def _zerotts_tts(text: str, voice: str) -> bytes:
    """Giọng "zerotts:<mã>" → WAV 48 kHz. Chờ trọn câu — chỉ cho API không stream."""
    import numpy as np

    vid = _zerotts_voice_id(voice)
    tts = _get_zerotts()
    parts = []
    for seg in _zerotts_doan(text):
        with _zerotts_lock:
            parts.append(np.asarray(tts.synthesize(seg, voice=vid), dtype=np.float32).reshape(-1))
    if not parts:
        raise VoiceError("ZeroTTS không tạo được âm thanh.")
    return _pcm_to_wav(_float_to_pcm16(np.concatenate(parts)), int(tts.sample_rate), 2, 1)


def _zerotts_stream(text: str, voice: str):
    """Yield (48000, pcm16) theo khối đều `_ZEROTTS_KHUNG` frame.

    synthesize() gom hết frame: câu thời tiết ấm mất 8,5s mới có tiếng.
    Khối 1 frame rồi nhân đôi tới 16 có tiếng sau 0,24s nhưng im tới 1,0s
    khi khối phình lên. Giữ 6 frame: tiếng đầu 0,75s, lỗ dài nhất 0,18s.
    """
    import numpy as np

    vid = _zerotts_voice_id(voice)
    tts = _get_zerotts()
    segs = _zerotts_doan(text)
    if not segs:
        raise VoiceError("ZeroTTS không tạo được âm thanh.")
    rate = int(tts.sample_rate)
    yielded = False
    # Giữ khoá suốt stream: session ONNX không chịu hai request một lúc.
    with _zerotts_lock:
        for seg in segs:
            for chunk in tts.synthesize_stream(
                    seg, voice=vid,
                    first_chunk_frames=_ZEROTTS_KHUNG,
                    max_chunk_frames=_ZEROTTS_KHUNG):
                audio = np.asarray(chunk, dtype=np.float32).reshape(-1)
                if audio.size == 0:
                    continue
                yielded = True
                yield (rate, _float_to_pcm16(audio))
    if not yielded:
        raise VoiceError("ZeroTTS không tạo được âm thanh.")


# ── TTS ──────────────────────────────────────────────────────────────────────


def _doc_cong_thuc(text: str, voice: str) -> str:
    """Công thức hoá học → lời đọc (xem services/voice/hoa_hoc.py) cho mọi giọng
    tiếng Việt; Kokoro tiếng Anh và giọng đa ngữ giữ nguyên. Chạy nhiều lần vô
    hại: lần sau không còn công thức nào để đổi."""
    v = (voice or vcfg.tts_voice()).strip()
    if v.startswith("dangu:") or (v.startswith(vcfg.KOKORO_PREFIX)
                                  and not v.startswith(vcfg.KOKORO_VI_PREFIX)):
        return text
    from services.voice import hoa_hoc

    try:
        return hoa_hoc.doc(text)
    except Exception as exc:  # noqa: BLE001 — chữ người dùng tuỳ ý: lỗi đọc công thức không được làm câm TTS
        logger.warning("voice: doc cong thuc loi, doc nguyen van: %s", str(exc)[:160])
        return text


_chuan_hoa_vi = None
_chuan_hoa_khoa = threading.Lock()


def _doc_vi(text: str) -> str:
    """Chữ HIỂN THỊ → chữ để ĐỌC, cho engine không tự chuẩn hoá (NghiTTS, Piper).

    Hai engine này phiên âm bằng espeak nên đọc sai "24/09/2026", "TP.HCM",
    "H2SO4", "m/s²", "√16"… (chủ máy 24/09/2026). Dùng CHUNG bộ chuẩn hoá của
    `sea_g2p` mà VieNeu và Kokoro Việt đã dùng — một nguồn luật cho ngày tháng,
    đơn vị, viết tắt, toán, hoá, lý thay vì danh sách tự viết. Chữ hiển thị
    (tin nhắn, thẻ loa) không đổi; chỉ chuỗi đưa vào model.

    Thẻ ``<en>…</en>`` là cho chế độ song ngữ của VieNeu; engine tiếng Việt
    thuần bỏ thẻ, giữ chữ bên trong. Gói chưa cài thì đọc nguyên văn như cũ.
    """
    global _chuan_hoa_vi
    with _chuan_hoa_khoa:
        if _chuan_hoa_vi is None:
            try:
                from sea_g2p import Normalizer
            except ImportError:
                return text
            _chuan_hoa_vi = Normalizer("vi")
        ra = _chuan_hoa_vi.normalize(text)
    return _re.sub(r"</?en>", "", ra)


def _piper_local(text: str, voice: str = "") -> bytes:
    binary = vcfg.piper_binary()
    model = vcfg.voice_model_path(voice)
    if not binary or model is None:
        raise VoiceError("Piper local chưa sẵn sàng (thiếu binary hoặc file giọng).")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out:
        out_path = out.name
    try:
        proc = subprocess.run(
            [binary, "--model", str(model), "--output_file", out_path,
             "--length_scale", str(vcfg.tts_length_scale())],
            input=_doc_vi(text).encode("utf-8"), capture_output=True, timeout=180,
        )
        if proc.returncode != 0:
            raise VoiceError(
                f"piper lỗi: {proc.stderr.decode('utf-8', 'ignore')[:200]}")
        data = Path(out_path).read_bytes()
        if not data:
            raise VoiceError("piper không tạo được âm thanh.")
        return data
    finally:
        try:
            Path(out_path).unlink(missing_ok=True)
        except Exception:
            pass


def _backend_order(backend: str) -> list[str]:
    if backend in ("local", "wyoming"):
        return [backend]
    return ["local", "wyoming"]


def _synthesize_one(text: str, voice: str = "", *, style: str = "") -> bytes:
    """MỘT lần gọi engine cho trọn `text` → WAV bytes, KHÔNG chèn khoảng lặng.

    Ném VoiceError nếu không có đường nào chạy được.
    Giọng namespaced ("vieneu:<Tên>") đi thẳng engine tương ứng; lỗi thì rơi
    xuống Piper/Wyoming với giọng mặc định để trợ lý không bao giờ "câm".
    `style` (tu_nhien|tin_tuc|doc_truyen) chỉ tác dụng với VieNeu; engine khác bỏ qua.
    """
    text = (text or "").strip()
    if not text:
        raise VoiceError("Không có nội dung để đọc.")
    backend = vcfg.tts_backend()
    if backend == "off":
        raise VoiceError("TTS đang tắt.")
    errors: list[str] = []
    v = (voice or vcfg.tts_voice()).strip()
    ck = tts_cache.key("wav", text, v, style)
    cached = tts_cache.get(ck)
    if cached is not None:
        return cached

    def _done(wav: bytes) -> bytes:
        # CHỈ cache khi chưa engine nào lỗi: nếu VieNeu hỏng và rơi xuống Piper,
        # cache lại sẽ khoá cứng giọng dự phòng suốt cả ngày dù VieNeu đã hồi.
        if not errors:
            tts_cache.put(ck, wav, size_bytes=len(wav))
        return wav

    if v.startswith(vcfg.VIENEU_PREFIX):
        try:
            return _done(_vieneu_tts(text, v, style))
        except Exception as exc:
            errors.append(f"vieneu: {str(exc)[:120]}")
            logger.warning("voice: TTS vieneu that bai: %s", str(exc)[:160])
            v = ""          # fallback: giọng Piper mặc định
    elif v.startswith(vcfg.KOKORO_PREFIX):
        try:
            return _done(_kokoro_tts(text, v))
        except Exception as exc:
            errors.append(f"kokoro: {str(exc)[:120]}")
            logger.warning("voice: TTS kokoro that bai: %s", str(exc)[:160])
            v = ""          # fallback: giọng Piper mặc định
    elif v.startswith(vcfg.NGHI_PREFIX):
        try:
            return _done(_nghi_tts(text, v))
        except Exception as exc:
            errors.append(f"nghitts: {str(exc)[:120]}")
            logger.warning("voice: TTS nghitts that bai: %s", str(exc)[:160])
            v = ""          # fallback: giọng Piper mặc định
    elif v.startswith(vcfg.KOKORO_VI_PREFIX):
        try:
            return _done(_kokoro_vi_tts(text, v))
        except Exception as exc:
            errors.append(f"kokorovi: {str(exc)[:120]}")
            logger.warning("voice: TTS kokoro viet that bai: %s", str(exc)[:160])
            v = ""          # fallback: giọng Piper mặc định
    elif v.startswith(vcfg.VIENEU_NANO_PREFIX):
        try:
            return _done(_vieneu_nano_tts(text, v))
        except Exception as exc:
            errors.append(f"vieneunano: {str(exc)[:120]}")
            logger.warning("voice: TTS vieneu nano that bai: %s", str(exc)[:160])
            v = ""          # fallback: giọng Piper mặc định
    elif v.startswith(vcfg.ZEROTTS_PREFIX):
        try:
            return _done(_zerotts_tts(text, v))
        except Exception as exc:
            errors.append(f"zerotts: {str(exc)[:120]}")
            logger.warning("voice: TTS zerotts that bai: %s", str(exc)[:160])
            v = ""          # fallback: giọng Piper mặc định
    for mode in _backend_order(backend):
        try:
            if mode == "local":
                return _done(_piper_local(text, v))
            uri = vcfg.tts_wyoming_url()
            if not uri:
                continue
            return _done(_wyoming_tts(text, uri))
        except Exception as exc:
            errors.append(f"{mode}: {str(exc)[:120]}")
            logger.warning("voice: TTS %s that bai: %s", mode, str(exc)[:160])
    raise VoiceError("Không tổng hợp được giọng nói — " + "; ".join(errors))


def synthesize(text: str, voice: str = "", *, style: str = "") -> bytes:
    """Text → WAV bytes, có chèn khoảng lặng giữa câu / giữa mệnh đề.

    Khoảng lặng lấy từ config (`voice.tts.sentence_silence_ms`,
    `clause_silence_ms`, `silence_jitter_percent` — chỉnh trong Cài đặt) và áp
    cho engine trả WAV từng câu (Piper, Kokoro Việt, Wyoming): text được cắt
    thành mẩu, mỗi mẩu một lần gọi, nối lại bằng im lặng. VieNeu và ZeroTTS
    đọc trọn text một lần. Cả hai khoảng lặng = 0 → mọi engine đọc trọn text
    một lần.

    Hàm cắt/ghép nằm ở khối "TTS streaming" bên dưới (dùng chung với
    `stream_synthesize`).
    """
    text = (text or "").strip()
    if not text:
        raise VoiceError("Không có nội dung để đọc.")
    _nho_giong((voice or vcfg.tts_voice()).strip())
    if (voice or "").startswith("dangu:"):
        return synthesize_da_ngu(text, voice[len("dangu:"):])
    text = _doc_cong_thuc(text, voice)
    mot_lan = None
    if (voice or "").startswith(vcfg.NGHI_PREFIX):
        # Một lần generate cho cả đoạn, câu nào xong phát câu đó.
        mot_lan = lambda: _nghi_phat(text, voice)  # noqa: E731
    elif ((voice or "").startswith(vcfg.KOKORO_PREFIX)
            and not (voice or "").startswith(vcfg.KOKORO_VI_PREFIX)):
        mot_lan = lambda: _phat_cau(text, 24000, lambda doan: _kokoro_cau(doan, voice))  # noqa: E731
    if mot_lan is not None:
        try:
            khuc = list(mot_lan())
            if khuc:
                return _pcm_to_wav(b"".join(pcm for _r, pcm in khuc), khuc[0][0], 2, 1)
            raise VoiceError("Không tạo được âm thanh.")
        except Exception as exc:
            # Đường một lần hỏng (thiếu model, sherpa lỗi) thì đi đường thường,
            # nơi có sẵn lùi về Piper — 5d5da29 bỏ mất bước này, giọng NghiTTS
            # thiếu model là tin nhắn thoại và thông báo loa hỏng hẳn.
            logger.warning("voice: %s mot lan that bai, di duong thuong: %s",
                           voice, str(exc)[:160])
            return _synthesize_one(text, voice, style=style)
    if (voice or "").startswith((vcfg.VIENEU_PREFIX, vcfg.ZEROTTS_PREFIX, vcfg.VIENEU_NANO_PREFIX)):
        # Hai engine tự cắt câu và tự nghỉ. Cắt thêm từng vế là prefill lại —
        # đoạn thời tiết đo 23/09/2026 khựng tới 3,3 giây.
        return _synthesize_one(text, voice, style=style)
    sent_ms, clause_ms, para_ms, jitter = _silence_plan()
    if sent_ms <= 0 and clause_ms <= 0 and not ("\n" in text and para_ms > 0):
        return _synthesize_one(text, voice, style=style)
    segs = _split_segments(text, clause_ms=clause_ms)
    if len(segs) <= 1:
        return _synthesize_one(text, voice, style=style)

    fmt: tuple[int, int, int] | None = None
    pcm_parts: list[bytes] = []
    for i, (seg, kind) in enumerate(segs):
        rate, width, channels, pcm = _wav_parts(
            _synthesize_one(seg, voice, style=style))
        if fmt is None:
            fmt = (rate, width, channels)
        elif (rate, width, channels) != fmt:
            # Giữa chừng engine rơi xuống bản dự phòng (khác tần số / độ rộng
            # mẫu) — nối thẳng vào là méo tiếng. Bỏ ghép, đọc lại một lần.
            logger.warning("voice: dinh dang WAV doi giua chung → doc lai tron van ban")
            return _synthesize_one(text, voice, style=style)
        if not pcm:
            continue
        if (width, channels) == (2, 1):
            pcm = _cat_lang_hai_dau(pcm, rate)
        pcm_parts.append(pcm)
        if i < len(segs) - 1 and (width, channels) == (2, 1):
            gap = _silence_pcm(_nghi_ms(kind, sent_ms, clause_ms, para_ms, jitter), rate)
            if gap:
                pcm_parts.append(gap)
    if fmt is None or not pcm_parts:
        raise VoiceError("Không tổng hợp được giọng nói.")
    rate, width, channels = fmt
    return _pcm_to_wav(b"".join(pcm_parts), rate, width, channels)


# ── TTS streaming: "chữ sinh ra tới đâu đọc tới đó" ──────────────────────────
# stream_synthesize() yield (sample_rate, pcm16_mono_bytes) NGAY khi có, để
# caller phát dần. VieNeu và ZeroTTS nhả theo khung. Piper / Kokoro Việt /
# Wyoming không stream theo khung → cắt câu rồi đọc từng câu.

import random as _random
import re as _re

# Kết thúc câu, hoặc xuống dòng (đoạn văn). Nhóm 1 có dấu câu; nhóm 2 là
# xuống dòng trần. Khoảng trắng sau dấu mà chứa xuống dòng vẫn là đoạn văn.
_RANH_CAU = _re.compile(r"(?<=[.!?…。！？])([ \t]*\n[\t \n]*|[ \t]+)|(\n+)")

_MAX_GAP_MS = 3000
_gap_rng = _random.Random()


def _jitter_ms(base_ms: int, jitter_percent: int) -> int:
    """Rải khoảng lặng quanh giá trị đặt để nhịp nghỉ không đều như máy đếm.

    Khoảng nghỉ giống hệt nhau ở mọi ranh giới câu nghe ra ngay là máy đọc;
    lệch vài chục mili giây mỗi lần thì tự nhiên hơn (ý từ wyoming-vietnamese).
    """
    if base_ms <= 0 or jitter_percent <= 0:
        return max(0, base_ms)
    spread = base_ms * jitter_percent / 100
    ms = round(_gap_rng.uniform(base_ms - spread, base_ms + spread))
    return max(0, min(int(ms), _MAX_GAP_MS))


def _silence_pcm(ms: int, rate: int) -> bytes:
    """PCM16 mono im lặng dài `ms` mili giây ở tần số lấy mẫu `rate`."""
    if ms <= 0 or rate <= 0:
        return b""
    return bytes(round(rate * ms / 1000) * 2)


#: Im lặng đầu/cuối mẩu giữ lại (ms) — đủ để âm cuối tắt tự nhiên.
_GIU_BIEN_MS = 40


def _cat_lang_hai_dau(pcm: bytes, rate: int, *, dau: bool = True, cuoi: bool = True) -> bytes:
    """Bỏ im lặng model tự sinh ở hai đầu MỘT mẩu, chừa ``_GIU_BIEN_MS``.

    Khoảng nghỉ người nghe thấy = đuôi lặng mẩu trước + nghỉ cấu hình + đầu
    lặng mẩu sau. Đo 24/09/2026 trên máy chủ: Kokoro Việt tự thêm ~0,22 s mỗi
    đầu, nên phẩy cấu hình 180 ms nghe thành 0,6–0,7 s còn chấm 400 ms thành
    0,9 s — phẩy với chấm gần như nhau. Cắt đi thì số cấu hình là số nghe thấy.
    Ngưỡng tương đối với đỉnh của chính mẩu (âm lượng mỗi giọng một khác).
    """
    import numpy as np

    a = np.frombuffer(pcm, np.int16)
    o = max(1, rate // 100)                       # cửa sổ 10 ms
    n = a.size // o
    if n == 0:
        return pcm
    muc = np.abs(a[:n * o].reshape(n, o).astype(np.int32)).max(axis=1)
    co = np.nonzero(muc >= max(64, int(muc.max() * 0.015)))[0]
    if co.size == 0:
        return pcm
    giu = rate * _GIU_BIEN_MS // 1000
    tu = max(0, co[0] * o - giu) if dau else 0
    den = min(a.size, (co[-1] + 1) * o + giu) if cuoi else a.size
    return a[tu:den].tobytes()


def _comma_cut(s: str, limit: int) -> int:
    """Vị trí dấu phẩy gần `limit` nhất để xẻ câu dài, -1 nếu không có chỗ nào.

    Bỏ qua phẩy nằm GIỮA HAI CHỮ SỐ ("1,5 triệu", "33,8 độ") — cắt ngay đó thì
    engine đọc thành "một" … nghỉ … "năm triệu", sai hẳn con số. Mẹo này lấy từ
    wyoming-vietnamese (`_is_numeric_separator`).
    """
    cut = s.rfind(",", 0, limit)
    while cut > 0:
        after = s[cut + 1] if cut + 1 < len(s) else ""
        if not (s[cut - 1].isdigit() and after.isdigit()):
            return cut
        cut = s.rfind(",", 0, cut)
    return -1


def _la_cham_trong_so(text: str, dau: int, cuoi: int) -> bool:
    """Dấu chấm/phẩy nằm giữa hai chữ số thì không phải hết câu hay hết vế.

    "33,8" và "1.000" mà cắt ở đó thì engine đọc thành hai số rời. Cách này
    lấy từ wyoming-vietnamese (`_is_numeric_separator`).
    """
    if dau <= 0 or not text[dau - 1].isdigit():
        return False
    return cuoi >= len(text) or text[cuoi].isdigit()


def _tach_doan(text: str) -> list[tuple[str, str]]:
    """[(đoạn, loại ranh giới sau đoạn)]. Loại là paragraph, sentence, hoặc rỗng.

    Xuống dòng — kể cả sau dấu chấm — là hết đoạn văn, nghỉ dài hơn hết câu.
    Dấu chấm giữa hai chữ số không cắt.
    """
    s = text or ""
    out: list[tuple[str, str]] = []
    pos = 0
    for m in _RANH_CAU.finditer(s):
        sep = m.group(0)
        if m.group(1) and _la_cham_trong_so(s, m.start() - 1, m.end()):
            continue
        piece = s[pos:m.start()].strip()
        if piece:
            out.append((piece, "paragraph" if "\n" in sep else "sentence"))
        pos = m.end()
    tail = s[pos:].strip()
    if tail:
        out.append((tail, ""))
    return out


def _xe_dai(s: str, max_chars: int) -> list[str]:
    """Xẻ đoạn quá dài theo dấu phẩy (không cắt giữa số) để câu đầu ra tiếng sớm."""
    out: list[str] = []
    while len(s) > max_chars:
        cut = _comma_cut(s, max_chars)
        cut = cut if cut > max_chars // 2 else max_chars
        out.append(s[:cut].strip())
        s = s[cut:].strip(" ,")
    if s:
        out.append(s)
    return out


def _split_blocks(text: str, max_chars: int = 240) -> list[tuple[str, str]]:
    """[(mẩu, loại ranh giới sau mẩu)] sau khi xẻ đoạn dài và gộp mẩu tí hon."""
    tho: list[tuple[str, str]] = []
    for piece, kind in _tach_doan(text):
        khuc = _xe_dai(piece, max_chars)
        for i, s in enumerate(khuc):
            tho.append((s, kind if i == len(khuc) - 1 else "sentence"))
    merged: list[tuple[str, str]] = []
    buf = ""
    for s, kind in tho:
        if buf:
            s = (buf + " " + s).strip()
            buf = ""
        if len(s) < 15:
            buf = s
        else:
            merged.append((s, kind))
    if buf:
        if merged:
            merged[-1] = (merged[-1][0] + " " + buf, merged[-1][1])
        else:
            merged.append((buf, ""))
    return merged


def _split_sentences(text: str, max_chars: int = 240) -> list[str]:
    """Cắt text thành mẩu ngắn để đọc dần. Gộp mẩu quá ngắn, xẻ mẩu quá dài
    theo dấu phẩy để câu đầu ra audio sớm (giảm thời gian chờ)."""
    return [s for s, _k in _split_blocks(text, max_chars)]


# Ranh giới MỆNH ĐỀ trong một câu: phẩy, chấm phẩy, hai chấm, gạch ngang có
# khoảng trắng. Gạch dính chữ ("Wi-Fi", "TP-HCM") không phải ranh giới.
_CLAUSE_MARKS = ",;:，；："
_GACH_MENH_DE = "-–—"


def _split_clauses(s: str, min_chars: int = 12) -> list[str]:
    """Xẻ MỘT câu tại dấu phẩy/chấm phẩy/hai chấm, GIỮ dấu ở cuối mẩu.

    Giữ lại dấu để engine đọc mẩu như một mệnh đề (ngữ điệu lửng) chứ không
    như một câu trọn vẹn (ngữ điệu xuống hẳn).

    Bỏ qua dấu nằm GIỮA HAI CHỮ SỐ — "1,5 triệu" hay "12:30" mà cắt ở đó thì
    engine đọc thành hai số rời, sai nội dung. Mẩu ngắn hơn `min_chars` được
    gộp sang mẩu sau để không sinh clip audio vụn.
    """
    out: list[str] = []
    buf = ""
    for i, ch in enumerate(s):
        buf += ch
        if ch in _GACH_MENH_DE:
            truoc = s[i - 1] if i > 0 else ""
            sau = s[i + 1] if i + 1 < len(s) else ""
            # "Wi-Fi" dính chữ thì giữ. "Sài Gòn - Hà Nội" có khoảng trắng thì nghỉ.
            if not (truoc.isspace() or sau.isspace()):
                continue
        elif ch not in _CLAUSE_MARKS:
            continue
        else:
            truoc = s[i - 1] if i > 0 else ""
            sau = s[i + 1] if i + 1 < len(s) else ""
            if truoc.isdigit() and sau.isdigit():
                continue
        piece = buf.strip()
        if len(piece) >= min_chars:
            out.append(piece)
            buf = ""
    tail = buf.strip()
    if tail:
        if out and len(tail) < min_chars:
            out[-1] = (out[-1] + " " + tail).strip()
        else:
            out.append(tail)
    return out


def _split_segments(text: str, max_chars: int = 240, *,
                    clause_ms: int = 0) -> list[tuple[str, str]]:
    """Cắt text thành [(mẩu, loại ranh giới SAU mẩu)].

    Loại là paragraph (xuống dòng), sentence (hết câu) hoặc clause (hết vế).
    `clause_ms <= 0` → không xẻ theo mệnh đề.
    """
    out: list[tuple[str, str]] = []
    for sent, after in _split_blocks(text, max_chars):
        parts = _split_clauses(sent) if clause_ms > 0 else [sent]
        for i, p in enumerate(parts):
            if i < len(parts) - 1:
                out.append((p, "clause"))
            else:
                out.append((p, after or "sentence"))
    return out


def _silence_plan() -> tuple[int, int, int, int]:
    """(nghỉ hết câu, nghỉ hết vế, nghỉ hết đoạn, dao động %)."""
    return (vcfg.tts_sentence_silence_ms(), vcfg.tts_clause_silence_ms(),
            vcfg.tts_paragraph_silence_ms(), vcfg.tts_silence_jitter_percent())


def _nghi_ms(kind: str, sent_ms: int, clause_ms: int, para_ms: int, jitter: int) -> int:
    """Mili giây nghỉ sau một mẩu, đã rải ngẫu nhiên."""
    if kind == "paragraph":
        base = para_ms if para_ms > 0 else sent_ms
    elif kind == "clause":
        base = clause_ms
    else:
        base = sent_ms
    return _jitter_ms(base, jitter)


# Cỡ khối đều. Khối sau dài hơn audio đang phát thì loa im giữa chừng.
# Đo ấm 23/09/2026, đoạn thời tiết, trên model đang chạy:
#   VieNeu 1 frame rồi 25: tiếng đầu 0,82s, rồi im 3,2s.
#   VieNeu giữ 6 frame (0,48s): tiếng đầu 1,29s, lỗ dài nhất 0,38s.
#   ZeroTTS nhảy tới 16 frame: lỗ 1,0s. Giữ 6 frame: lỗ dài nhất 0,18s.
_VIENEU_KHUNG = 6
_ZEROTTS_KHUNG = 6


def _dat_so_khung_dau_vieneu(so: int) -> None:
    """Số frame VieNeu gom trước mỗi lần yield khi đang chậm hơn thời gian thực.

    Thư viện chốt 4 và không phóng khối khi phát không kịp. Giữ một cỡ suốt
    câu: nhảy từ 1 frame lên 25 làm im 3 giây sau tiếng đầu.
    """
    for ten in (
        "vieneu._v3_turbo_engine.onnx_runtime_lite",
        "vieneu._v3_turbo_engine.inference_v3_turbo",
    ):
        mod = sys.modules.get(ten)
        if mod is None:
            try:
                mod = __import__(ten, fromlist=["_STREAM_LEADIN_FRAMES"])
            except Exception:
                continue
        if hasattr(mod, "_STREAM_LEADIN_FRAMES"):
            mod._STREAM_LEADIN_FRAMES = so


def _vieneu_stream(text: str, voice: str, style: str = ""):
    """Frame-level: yield (48000, pcm16) từng khối infer_stream trả.

    Giữ đúng `_VIENEU_KHUNG` frame mỗi lần yield. max_chars (mặc định 128)
    giới hạn prefill của chunk chữ đầu.
    """
    eng = _get_vieneu()
    kwargs = _vieneu_kwargs(voice, style)
    # Giữ khoá suốt stream: session ONNX tuần tự; tránh 2 request giành graph.
    with _vieneu_lock:
        _dat_so_khung_dau_vieneu(_VIENEU_KHUNG)
        try:
            for chunk in eng.infer_stream(text, **kwargs):
                if chunk is None or len(chunk) == 0:
                    continue
                yield (48000, _float_to_pcm16(chunk))
        finally:
            _dat_so_khung_dau_vieneu(4)


def _probe_warm_ttfa(voice: str, min_pcm: int = 48000 // 5) -> float | None:
    """Đo TTFA (giây) trên engine ĐÃ warm: thời gian tới chunk PCM đầu.

    Trả None nếu không ra audio.
    """
    import time as _time
    t0 = _time.perf_counter()
    first: float | None = None
    n = 0
    for _rate, pcm in _vieneu_stream("Xin chào, kiem tra toc do.", voice):
        if first is None:
            first = _time.perf_counter() - t0
        n += len(pcm or b"")
        if n >= min_pcm:
            break
    return first


def _maybe_switch_int8_to_fp32(voice: str, warm_ttfa: float) -> dict:
    """Nếu đang int8 (auto) mà WARM TTFA > target và có fp32 → chuyển fp32.

    Không đổi khi user ép precision trong config. Trả thông tin quyết định.
    """
    target = vcfg.ttfa_target_s()
    info: dict = {
        "warm_ttfa_s": round(warm_ttfa, 3),
        "target_s": target,
        "switched": False,
        "from": vcfg.vieneu_precision(),
        "to": vcfg.vieneu_precision(),
    }
    vcfg.record_warm_ttfa(warm_ttfa)
    if vcfg.tts_precision_locked():
        info["detail"] = "precision locked by config"
        return info
    if vcfg.vieneu_precision() != "int8":
        info["detail"] = "already not int8"
        return info
    if warm_ttfa <= target:
        info["detail"] = "int8 meets TTFA target"
        return info
    if not vcfg._vieneu_model_present("fp32"):
        info["detail"] = "fp32 model missing — keep int8"
        logger.warning(
            "voice: int8 WARM TTFA=%.3fs > target=%.3fs nhưng chua co model fp32 "
            "(chay download_vieneu_model.py --fp32)",
            warm_ttfa, target,
        )
        return info
    reason = f"int8 warm_ttfa={warm_ttfa:.3f}s > target={target:.3f}s → fp32"
    logger.warning("voice: %s", reason)
    vcfg.set_tts_precision_override("fp32", reason)
    _reset_vieneu()
    # Nạp + warm fp32, đo lại TTFA.
    _ = list(_vieneu_stream("Xin chào.", voice))  # cold load fp32
    ttfa2 = _probe_warm_ttfa(voice)
    if ttfa2 is not None:
        vcfg.record_warm_ttfa(ttfa2)
        info["warm_ttfa_after_s"] = round(ttfa2, 3)
    info["switched"] = True
    info["to"] = "fp32"
    info["detail"] = reason
    return info


def _warm_zerotts() -> dict | None:
    """Nạp ZeroTTS (constructor đã warmup). None nếu chưa tải model.

    Không nạp thì request đầu của Home Assistant (giọng zerotts) trả tiền
    nạp model cộng thời gian đọc hết câu — đo lạnh 17s, ấm mà gọi synthesize()
    vẫn 8,5s mới có tiếng.
    """
    if vcfg.zerotts_model_dir() is None:
        return None
    import time as _time
    t0 = _time.perf_counter()
    _get_zerotts()
    ms = int((_time.perf_counter() - t0) * 1000)
    logger.info("voice: warmup ZeroTTS xong (%d ms)", ms)
    return {"ok": True, "engine": "zerotts", "ms": ms}


def warmup_tts(voice: str = "") -> dict:
    """Nạp model + warm + đo TTFA; int8 không đạt target → auto chuyển fp32.

    Gọi nền lúc startup. Best-effort: lỗi chỉ log, không ném ra ngoài.
    Trả dict {ok, engine, ms, warm_ttfa_s, precision, switched, …}.
    """
    import time as _time
    t0 = _time.perf_counter()
    v = (voice or vcfg.tts_voice()).strip()
    try:
        # Warm VieNeu chỉ khi nó LÀ giọng mặc định. Trước 24/09/2026 cứ có model
        # là nạp (kể cả mặc định Piper): ~1,2 GB và hàng chục giây CPU mỗi lần
        # đổi ảnh cho họ không ai gán, 30 phút sau lại nhả. Giọng thật sự đang
        # dùng thì `nap_giong_da_dung` nạp sẵn.
        if (v.startswith(vcfg.VIENEU_PREFIX)
                and vcfg.vieneu_installed() and vcfg.vieneu_model_ready()):
            # 1) Cold load + stream ngắn (bỏ qua TTFA cold).
            n = 0
            for _rate, pcm in _vieneu_stream("Xin chào.", v):
                n += len(pcm or b"")
                if n >= 48000 // 5:
                    break
            # 2) Đo WARM TTFA (lần stream thứ hai trên engine đã nạp).
            warm = _probe_warm_ttfa(v)
            adapt: dict = {}
            if warm is not None:
                adapt = _maybe_switch_int8_to_fp32(v, warm)
            ms = int((_time.perf_counter() - t0) * 1000)
            prec = vcfg.vieneu_precision()
            logger.info(
                "voice: warmup VieNeu xong (%d ms, voice=%s, precision=%s, "
                "warm_ttfa=%s, switched=%s)",
                ms, v, prec,
                f"{warm:.3f}s" if warm is not None else "n/a",
                adapt.get("switched"),
            )
            out = {
                "ok": True, "engine": "vieneu", "ms": ms, "voice": v,
                "precision": prec,
                "warm_ttfa_s": None if warm is None else round(warm, 3),
            }
            out.update({k: adapt[k] for k in adapt if k not in out})
            # ZeroTTS nạp thêm, không được làm hỏng kết quả VieNeu vừa warm.
            try:
                z = _warm_zerotts()
            except Exception as exc:
                logger.warning("voice: warmup ZeroTTS loi: %s", str(exc)[:160])
                z = None
            if z:
                out["zerotts_ms"] = z["ms"]
            return out
        if v.startswith(vcfg.NGHI_PREFIX) and vcfg.nghi_ready():
            # Nạp lạnh một model VITS mất vài giây; warm trước để lần đọc đầu
            # của người dùng không phải chờ.
            _nghi_tts("Xin chào.", v)
            ms = int((_time.perf_counter() - t0) * 1000)
            logger.info("voice: warmup NghiTTS xong (%d ms, voice=%s)", ms, v)
            return {"ok": True, "engine": "nghitts", "ms": ms, "voice": v}
        if v.startswith(vcfg.KOKORO_PREFIX) and vcfg.kokoro_model_dir():
            _kokoro_tts("Hello.", v)
            ms = int((_time.perf_counter() - t0) * 1000)
            logger.info("voice: warmup Kokoro xong (%d ms)", ms)
            return {"ok": True, "engine": "kokoro", "ms": ms, "voice": v}
        z = _warm_zerotts()
        if z:
            return z
        return {"ok": False, "engine": "", "ms": 0, "detail": "no local tts model"}
    except Exception as exc:
        ms = int((_time.perf_counter() - t0) * 1000)
        logger.warning("voice: warmup TTS loi (%d ms): %s", ms, str(exc)[:160])
        return {"ok": False, "engine": "", "ms": ms, "detail": str(exc)[:160]}


# ── Đệm đầu thông minh ───────────────────────────────────────────────────────
# VieNeu và ZeroTTS trên máy .38 tạo CHẬM hơn tốc độ đọc — đo 23/09/2026 qua
# /api/voice/stream, đoạn 30 giây: VieNeu RTF 1,61 (loa im tổng 17,9s, lần dài
# nhất 3,0s giữa câu), ZeroTTS 1,35 (11,6s). Thêm luồng không cứu: ZeroTTS 4/6/8
# luồng = RTF 1,45/2,05/2,83, VieNeu 2 và 4 luồng cùng ~1,7 (LXC dùng chung nhân).
# Phát ngay thì mọi chỗ hụt thành chỗ ngắt giữa câu. Chủ máy chọn 23/09/2026:
# chờ đầu vừa đủ rồi đọc liền mạch.
# Nếu tạo chậm hơn đọc r lần và đoạn dài D giây, bắt đầu phát khi đã có sẵn
# D·(1 − 1/r) giây thì tới cuối không còn hụt. r đo ngay trong lượt (thời gian
# từ lúc bắt đầu / số giây đã tạo), D ước theo số ký tự × giây-mỗi-ký-tự học
# được của HỌ engine đó. Engine nhanh hơn đọc (r ≤ 1) thì không giữ gì.
# Trong lúc giữ phát khoảng lặng đúng nhịp thời gian thực: cả hai nơi nhận
# (loa qua HTTP, Home Assistant qua Wyoming) đều phát ngay khi nhận, nên lặng
# chính là thời gian chờ — và loa không bỏ cuộc vì lâu không thấy byte nào.

_TOC_DO: dict[str, dict[str, float]] = {}   # họ engine → {"rtf", "giay_moi_chu"}
# Tiếng Việt đọc ~13 ký tự/giây. Chỉ dùng tới khi họ ấy đọc xong lượt đầu.
_GIAY_MOI_CHU_MAC_DINH = 0.075
_DU_PHONG_DEM = 1.1            # giữ dư 10% cho sai số ước lượng


def _ho_engine(voice: str) -> str:
    return voice.split(":", 1)[0] if ":" in voice else "piper"


def _dem_dau(nguon, text: str, ho: str):
    """Bọc một nguồn (rate, pcm16): giữ lại tới khi đủ để đọc liền mạch.

    Tốc độ r đo TỪ KHỐI TIẾNG ĐẦU TIÊN, không từ lúc gọi: thời gian nạp model
    và prefill đã trả xong trước khi có tiếng, không kéo dài phần còn lại.
    Bản đo từ lúc gọi (cbbca81) gộp cả nạp model — sau 30 phút model tự nhả,
    lượt kế ra r ~2,6 nên giữ ~70% đoạn mới phát (chủ máy 24/09/2026: "Kokoro
    lâu hơn trước, không theo kiểu tts dần"), rồi số sai còn được học lại.
    """
    import time as _time

    hoc = _TOC_DO.get(ho) or {}
    du_kien = len(text) * hoc.get("giay_moi_chu", _GIAY_MOI_CHU_MAC_DINH)
    giu: list[tuple[int, bytes]] = []
    da_tao = 0.0
    tha = False
    lang_da_phat = 0.0
    luc_co_tieng = None      # lúc khối tiếng đầu tiên tới
    dai_dau = 0.0            # độ dài khối đầu — không tính vào tốc độ
    for rate, pcm in nguon:
        dai = len(pcm) / (2 * rate) if rate else 0.0
        da_tao += dai
        if tha:
            yield rate, pcm
            continue
        giu.append((rate, pcm))
        bay_gio = _time.monotonic()
        if luc_co_tieng is None:
            luc_co_tieng, dai_dau = bay_gio, dai
        sau_dau = da_tao - dai_dau
        # r đo trong lượt khi đã có ≥1s tiếng SAU khối đầu; trước đó dùng số đã học.
        r = (bay_gio - luc_co_tieng) / sau_dau if sau_dau >= 1.0 else hoc.get("rtf")
        if r is not None and da_tao >= du_kien * max(0.0, 1.0 - 1.0 / r) * _DU_PHONG_DEM:
            tha = True
            yield from giu
            giu = []
            continue
        thieu = (bay_gio - luc_co_tieng) - lang_da_phat
        if thieu >= 0.25:
            lang_da_phat += thieu
            yield rate, _silence_pcm(int(thieu * 1000), rate)
    yield from giu
    if luc_co_tieng is not None and da_tao - dai_dau >= 1.0 and da_tao >= 2.0 and text:
        cu = _TOC_DO.get(ho)
        moi = {"rtf": (_time.monotonic() - luc_co_tieng) / (da_tao - dai_dau),
               "giay_moi_chu": da_tao / len(text)}
        _TOC_DO[ho] = moi if not cu else {k: 0.7 * cu[k] + 0.3 * moi[k] for k in moi}


def noi_cau(nguon, truoc: str = ""):
    """Audio của MỘT câu khi đọc nối từng câu (Wyoming theo luồng chữ).

    Chèn nghỉ cấu hình theo ranh giới của câu trước (``truoc``: sentence /
    clause / paragraph; rỗng = câu đầu) rồi bỏ im lặng model tự sinh ở đầu câu
    — cùng lý do `_cat_lang_hai_dau`. Đuôi câu KHÔNG cắt ở đây: phải giữ khối
    cuối lại chờ biết nó là cuối, tức chậm một khối; đường theo mẩu đã cắt
    đuôi sẵn, VieNeu/ZeroTTS tự nghỉ.
    """
    sent_ms, clause_ms, para_ms, jitter = _silence_plan()
    dau = True
    for rate, pcm in nguon:
        if dau and pcm.strip(b"\x00"):
            dau = False
            if truoc:
                gap = _silence_pcm(_nghi_ms(truoc, sent_ms, clause_ms, para_ms, jitter), rate)
                if gap:
                    yield rate, gap
            pcm = _cat_lang_hai_dau(pcm, rate, cuoi=False)
        yield rate, pcm


def stream_synthesize(text: str, voice: str = "", *, style: str = ""):
    """Như `_stream_tao`, cộng cache và đệm đầu thông minh (xem `_dem_dau`)."""
    text = (text or "").strip()
    v = (voice or vcfg.tts_voice()).strip()
    _nho_giong(v)
    if text and not v.startswith("dangu:"):
        hit = tts_cache.get(tts_cache.key("stream", text, v, style))
        if hit is not None:
            yield from hit
            return
    yield from _dem_dau(_stream_tao(text, voice, style=style), text, _ho_engine(v))


def _stream_tao(text: str, voice: str = "", *, style: str = ""):
    """Generator yield (sample_rate, pcm16_mono_bytes) — đọc tới đâu phát tới đó.

    VieNeu và ZeroTTS → một lần gọi cho cả đoạn, khung âm thanh ra ngay khi
    model nhả (không chờ hết câu, không cắt lại theo khoảng lặng cấu hình).
    Piper, Kokoro Việt và đường dự phòng → theo câu (đọc xong câu nào phát câu đó).
    Giữa hai mẩu của đường theo câu chèn khoảng lặng theo config: hết câu dùng
    `sentence_silence_ms`, hết mệnh đề (dấu phẩy…) dùng `clause_silence_ms`.
    Không bao giờ ném giữa chừng cho lỗi 1 câu: bỏ qua câu lỗi, đọc tiếp.
    `style` (tu_nhien|tin_tuc|doc_truyen) chỉ tác dụng với VieNeu.

    Đọc trọn vẹn không lỗi thì audio được cache (xem tts_cache); câu y hệt lần
    sau phát ra ngay, không gọi engine.
    """
    text = (text or "").strip()
    if not text:
        raise VoiceError("Không có nội dung để đọc.")
    if vcfg.tts_backend() == "off":
        raise VoiceError("TTS đang tắt.")
    v = (voice or vcfg.tts_voice()).strip()
    # Giọng "dangu:<zh|ja|ko>" — Kokoro đa ngữ / Supertonic (cổng Wyoming theo
    # tiếng dùng id này). Không stream theo câu: model đọc trọn rồi phát.
    if v.startswith("dangu:"):
        rate, _w, _c, pcm = _wav_parts(synthesize_da_ngu(text, v[len("dangu:"):]))
        yield rate, pcm
        return

    ck = tts_cache.key("stream", text, v, style)
    hit = tts_cache.get(ck)
    if hit is not None:
        yield from hit
        return
    # SAU khoá cache: khoá tính trên chữ hiển thị (stream_synthesize tra đúng khoá đó).
    text = _doc_cong_thuc(text, v)

    # Gom bản sao audio để cache. Vượt trần mỗi mục thì bỏ gom luôn (captured =
    # None) — đằng nào cũng không nhét vừa, giữ tiếp chỉ phí RAM.
    _limit = tts_cache.max_item_bytes()
    captured: list[tuple[int, bytes]] | None = [] if _limit > 0 else None
    _captured_bytes = 0

    def _keep(item: tuple[int, bytes]) -> None:
        nonlocal captured, _captured_bytes
        if captured is None:
            return
        _captured_bytes += len(item[1])
        if _captured_bytes > _limit:
            captured = None
        else:
            captured.append(item)

    if v.startswith(vcfg.NGHI_PREFIX) or (
            v.startswith(vcfg.KOKORO_PREFIX) and not v.startswith(vcfg.KOKORO_VI_PREFIX)):
        yielded = False
        try:
            nguon = (_nghi_phat(text, v) if v.startswith(vcfg.NGHI_PREFIX)
                     else _phat_cau(text, 24000, lambda doan: _kokoro_cau(doan, v)))
            for item in nguon:
                yielded = True
                _keep(item)
                yield item
            if captured:
                tts_cache.put(ck, captured, size_bytes=_captured_bytes)
            return
        except Exception as exc:
            # ĐÃ PHÁT MỘT PHẦN thì dừng ở đó. Rơi xuống đường dự phòng là đọc lại
            # cả đoạn từ đầu — người nghe nghe hai lần, lần sau bằng giọng khác.
            if yielded:
                logger.warning("voice: stream sherpa hong giua chung, dung: %s", str(exc)[:160])
                return
            logger.warning("voice: stream sherpa that bai, fallback cau: %s", str(exc)[:160])
            captured, _captured_bytes = ([] if _limit > 0 else None), 0

    if v.startswith(vcfg.VIENEU_NANO_PREFIX):
        yielded = False
        try:
            for item in _vieneu_nano_stream(text, v):
                yielded = True
                _keep(item)
                yield item
            if yielded:
                if captured:
                    tts_cache.put(ck, captured, size_bytes=_captured_bytes)
                return
        except Exception as exc:
            if yielded:   # đã phát một phần: không đọc lại từ đầu (xem nhánh sherpa)
                logger.warning("voice: stream vieneu nano hong giua chung, dung: %s",
                               str(exc)[:160])
                return
            logger.warning("voice: stream vieneu nano that bai, fallback cau: %s",
                           str(exc)[:160])
        captured, _captured_bytes = ([] if _limit > 0 else None), 0
        v = ""   # fallback về Piper mặc định theo câu ở dưới

    if v.startswith(vcfg.ZEROTTS_PREFIX):
        try:
            yielded = False
            for item in _zerotts_stream(text, v):
                yielded = True
                _keep(item)
                yield item
            if yielded:
                if captured:
                    tts_cache.put(ck, captured, size_bytes=_captured_bytes)
                return
        except Exception as exc:
            if yielded:   # đã phát một phần: không đọc lại từ đầu (xem nhánh sherpa)
                logger.warning("voice: stream zerotts hong giua chung, dung: %s",
                               str(exc)[:160])
                return
            logger.warning("voice: stream zerotts that bai, fallback cau: %s",
                           str(exc)[:160])
        captured, _captured_bytes = ([] if _limit > 0 else None), 0
        v = ""   # fallback về Piper mặc định theo câu ở dưới

    sent_ms, clause_ms, para_ms, jitter = _silence_plan()
    segs = _split_segments(text, clause_ms=clause_ms)

    def _gap_ms(kind: str) -> int:
        """Khoảng lặng (đã rải ngẫu nhiên) cho ranh giới vừa đọc xong."""
        return _nghi_ms(kind, sent_ms, clause_ms, para_ms, jitter)

    if v.startswith(vcfg.VIENEU_PREFIX):
        try:
            yielded = False
            # Một infer_stream cho cả đoạn. Engine tự cắt chunk và tự chèn nghỉ
            # (hết câu 0,5s, hết vế 0,3s, hết đoạn 0,7s). Cắt ngoài rồi gọi lại
            # từng vế thì mỗi vế prefill từ đầu — đo 23/09/2026 khựng 3,3s.
            for item in _vieneu_stream(text, v, style):
                yielded = True
                _keep(item)
                yield item
            if yielded:
                if captured:
                    tts_cache.put(ck, captured, size_bytes=_captured_bytes)
                return
        except Exception as exc:
            if yielded:   # đã phát một phần: không đọc lại từ đầu (xem nhánh sherpa)
                logger.warning("voice: stream vieneu hong giua chung, dung: %s",
                               str(exc)[:160])
                return
            logger.warning("voice: stream vieneu that bai, fallback cau: %s",
                           str(exc)[:160])
        captured, _captured_bytes = ([] if _limit > 0 else None), 0
        v = ""   # fallback về Piper mặc định theo câu ở dưới

    # Kokoro/Piper/Wyoming/fallback: đọc theo câu, dùng lại synthesize().
    last_rate = 0
    prev_kind = ""
    errors: list[str] = []
    for sent, kind in segs:
        try:
            wav = synthesize(sent, v, style=style)
            rate, width, _channels, pcm = _wav_parts(wav)
            if width == 2 and pcm:
                pcm = _cat_lang_hai_dau(pcm, rate)
            if width == 2 and pcm:
                if last_rate and prev_kind:
                    gap = _silence_pcm(_gap_ms(prev_kind), last_rate)
                    if gap:
                        _keep((last_rate, gap))
                        yield (last_rate, gap)
                last_rate = rate
                prev_kind = kind
                _keep((rate, pcm))
                yield (rate, pcm)
            else:
                # WAV không đúng định dạng mong đợi (không phải 16-bit hoặc
                # rỗng) — tính là câu lỗi để guard bên dưới đếm đúng, tránh
                # generator "thành công" mà không phát ra âm thanh nào.
                errors.append(f"wav khong hop le (width={width}, len={len(pcm)})")
        except Exception as exc:
            errors.append(str(exc)[:100])
            logger.warning("voice: stream cau that bai: %s", str(exc)[:160])
    if errors and len(errors) >= len(segs):
        raise VoiceError("Không đọc được câu nào — " + "; ".join(errors[:3]))
    if not errors and captured:
        tts_cache.put(ck, captured, size_bytes=_captured_bytes)


# ── STT ──────────────────────────────────────────────────────────────────────


def _normalize_stt(text: str) -> str:
    """Chuẩn hoá kết quả STT.

    Model Zipformer viết HOA (ALLCAPS do BPE token-level). Hàm này:
      - Bỏ trắng dư 2 đầu.
      - Noise gate: văn bản dưới 2 ký tự → trả rỗng (tạp âm, nghỉ ngơi ngắn).
      - Nếu toàn HOA → capitalize() (chữ đầu viết hoa, còn lại viết thường).
    """
    text = text.strip()
    if len(text) < 2:
        return ""
    if text == text.upper() and any(c.isalpha() for c in text):
        text = text.capitalize()
    return text


def _get_recognizer(lang: str = "vi"):
    """Nạp model STT 1 lần mỗi ngôn ngữ rồi tái dùng (nạp lại tốn giây + RAM).

    vi = Zipformer tiếng Việt; en = Parakeet-TDT (kiến trúc NeMo transducer).
    """
    sense_dir = (vcfg.stt_sense_model_dir()
                 if lang in vcfg.stt_sense_tieng() else None)
    if sense_dir is not None:
        return _get_sense_recognizer(lang, sense_dir)
    if lang == "en":
        model_dir = vcfg.stt_en_model_dir()
        if model_dir is None:
            # Phân biệt "tính năng đang tắt" (model có sẵn trên đĩa) với
            # "chưa tải model" — kẻo admin tưởng nhầm phải tải lại.
            if not vcfg.stt_en_enabled() and vcfg.stt_en_model_present():
                raise VoiceError(
                    "STT tiếng Anh đang TẮT (bật voice.stt.en_enabled trong cài đặt Giọng nói).")
            raise VoiceError(
                "Chưa tải model STT tiếng Anh (chạy scripts/download_stt_en_model.py).")
        model_type = "nemo_transducer"
    elif lang in vcfg.STT_THEM_DIR:
        model_dir = vcfg.stt_them_model_dir(lang)
        if model_dir is None:
            raise VoiceError(
                f"Chưa tải model STT '{lang}' "
                f"(chạy scripts/download_stt_da_ngu.py {lang}).")
        model_type = ""   # Zipformer chuẩn k2 — như tiếng Việt
    else:
        model_dir = vcfg.stt_model_dir()
        if model_dir is None:
            raise VoiceError("Chưa tải model STT (chạy scripts/download_stt_model.py).")
        model_type = ""
    decoding_method = vcfg.stt_decoding_method(lang)
    key = f"{model_dir}|{vcfg.stt_threads()}|{decoding_method}"
    with _stt_lock:
        cached = _recognizers.get(lang)
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            import sherpa_onnx
        except Exception as exc:
            raise VoiceError("Chưa cài sherpa-onnx trong image.") from exc

        def _one(pattern: str) -> str:
            hits = sorted(model_dir.glob(pattern))
            if not hits:
                raise VoiceError(f"Thiếu file model khớp '{pattern}' trong {model_dir}.")
            return str(hits[0])

        tokens = model_dir / "tokens.txt"
        if not tokens.is_file():
            # KHÔNG BAO GIỜ truyền bpe.model vào tokens= — ReadTokens phía C++
            # đọc file nhị phân sẽ exit() làm CHẾT CẢ TIẾN TRÌNH gateway.
            _bpe_to_tokens(model_dir, tokens)
        # CHỈ truyền model_type khi khác rỗng: default của sherpa-onnx là
        # "transducer"; đè bằng "" khiến auto-detect chạy và crash native
        # với model Zipformer tiếng Việt tùy biến.
        extra = {"model_type": model_type} if model_type else {}
        rec = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=_one("encoder*.onnx"),
            decoder=_one("decoder*.onnx"),
            joiner=_one("joiner*.onnx"),
            tokens=str(tokens),
            num_threads=vcfg.stt_threads(),
            sample_rate=16000,
            feature_dim=80,
            decoding_method=decoding_method,
            provider="cpu",
            **extra,
        )
        _lam_am_stt(rec)
        _recognizers[lang] = (key, rec)
        return rec


def _get_sense_recognizer(lang: str, model_dir: Path):
    """Bộ nhận dạng SenseVoice cho một tiếng (zh/ja/ko).

    Khai THẲNG tiếng thay vì để model tự dò: chỗ gọi đã biết chắc tiếng, còn
    tự dò là thêm một chỗ hỏng được mà lỗi lại tính vào điểm của model.

    Model trả `tokens` + `timestamps` như transducer nên đường cắt khung phụ đề
    (`video_asr.gom_khung`) dùng lại nguyên vẹn. Nó KHÔNG trả `ys_log_probs` —
    chỗ dò ngôn ngữ của phụ đề có nhánh riêng cho việc đó.

    Bản model phải là `…-2024-07-17`: bản `2025-09-09` đọc sai cả tệp mẫu của
    chính nó với sherpa-onnx 1.13.4 (đo 15/08/2026 — tiếng Nhật rụng sạch kana
    chỉ còn chữ Hán giản thể, tiếng Hàn lẫn chữ Trung).
    """
    key = f"sense|{model_dir}|{lang}|{vcfg.stt_threads()}"
    with _stt_lock:
        cached = _recognizers.get(lang)
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            import sherpa_onnx
        except Exception as exc:
            raise VoiceError("Chưa cài sherpa-onnx trong image.") from exc

        hits = sorted(model_dir.glob("model*.onnx"))
        if not hits:
            raise VoiceError(f"Thiếu file model*.onnx trong {model_dir}.")
        rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(hits[0]),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=vcfg.stt_threads(),
            language=lang,
            use_itn=True,
        )
        _lam_am_stt(rec)
        _recognizers[lang] = (key, rec)
        return rec


def _bpe_to_tokens(model_dir: Path, tokens: Path) -> None:
    """Sinh tokens.txt (bảng ký hiệu `piece id`) từ bpe.model — làm 1 lần,
    ghi cạnh model trên volume. Model Zipformer tiếng Việt chỉ phát hành kèm
    bpe.model, còn sherpa-onnx bắt buộc tokens.txt dạng text."""
    bpe = model_dir / "bpe.model"
    if not bpe.is_file():
        raise VoiceError(f"Thiếu cả tokens.txt lẫn bpe.model trong {model_dir}.")
    try:
        import sentencepiece as spm
    except Exception as exc:
        raise VoiceError(
            "Thiếu tokens.txt; cần gói sentencepiece để sinh từ bpe.model "
            "(có trong extra-requirements của image mới).") from exc
    sp = spm.SentencePieceProcessor()
    sp.load(str(bpe))
    tmp = tokens.with_name(tokens.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for i in range(sp.get_piece_size()):
            f.write(f"{sp.id_to_piece(i)} {i}\n")
    tmp.replace(tokens)
    logger.info("voice: da sinh %s tu bpe.model (%d token)",
                tokens, sp.get_piece_size())


def _lam_am_stt(rec) -> None:
    """Một lần decode im lặng lúc nạp model, để câu nói đầu không chịu lạnh.

    wyoming-vietnamese làm vậy trước request thật. Bộ giả trong test không có
    ``create_stream`` thì bỏ qua.
    """
    import numpy as np

    tao = getattr(rec, "create_stream", None)
    if tao is None:
        return
    try:
        stream = tao()
        stream.accept_waveform(16000, np.zeros(1600, dtype=np.float32))
        rec.decode_stream(stream)
    except Exception as exc:
        logger.info("voice: lam am STT bo qua: %s", str(exc)[:120])


def _sherpa_local(wav16: bytes, lang: str = "vi") -> str:
    import numpy as np

    rec = _get_recognizer(lang)
    rate, width, _channels, pcm = _wav_parts(wav16)
    if width != 2:
        raise VoiceError("STT cần WAV 16-bit.")
    # numpy nhanh hơn list comprehension ~15x — thấy rõ khi audio dài.
    # sherpa-onnx nhận thẳng mảng float32, đừng .tolist() kẻo mất cái lợi đó.
    # Một mảng float32, không astype rồi chia thêm một bản. Cách wyoming-vietnamese.
    floats = np.multiply(
        np.frombuffer(pcm, dtype="<i2"), np.float32(1.0 / 32768.0), dtype=np.float32)
    # OfflineRecognizer dùng CHUNG giữa các request không thread-safe ở tầng
    # native — decode đồng thời (2 voice note cùng lúc, VD Telegram+Zalo) có
    # thể crash cả tiến trình gateway. Khoá tuần tự quanh create_stream/decode.
    with _stt_lock:
        stream = rec.create_stream()
        stream.accept_waveform(rate, floats)
        rec.decode_stream(stream)
        text = str(stream.result.text or "")
    return _normalize_stt(text)


def transcribe(audio: bytes, src_hint: str = "", lang: str = "") -> str:
    """Audio → text. ``lang`` = vi | en | auto (rỗng = voice.stt.language).

    auto: thử VI rồi EN (cần cả 2 model local).
    """
    if not audio:
        raise VoiceError("Không có dữ liệu âm thanh.")
    backend = vcfg.stt_backend()
    if backend == "off":
        raise VoiceError("STT đang tắt.")
    lang = (lang or vcfg.stt_language()).strip().lower().replace("_", "-")
    if lang.startswith("en"):
        lang = "en"
    elif lang.startswith("vi"):
        lang = "vi"
    elif lang in {"auto", "mul", "multi", "und", "*"}:
        lang = "auto"
    elif lang.split("-", 1)[0] in vcfg.STT_THEM_DIR:
        lang = lang.split("-", 1)[0]   # zh/ja/ko — cổng Wyoming theo tiếng
    else:
        lang = "vi"
    wav16 = to_wav_16k_mono(audio, src_hint)
    # Bỏ quãng không có tiếng trước khi nghe: tin nhắn thoại hay có vài giây im
    # lặng đầu/cuối, và chính chỗ lặng dài là nơi mọi bộ nghe bịa chữ. Chưa tải
    # model VAD thì hàm này trả nguyên bản.
    try:
        from services.voice import vad_silero
        wav16 = vad_silero.cat_im_lang_wav(wav16)
    except Exception as exc:
        logger.debug("voice: bỏ qua VAD: %s", str(exc)[:80])
    if lang == "auto":
        # Local auto: thử theo nhóm tiếng của tính năng tin nhắn thoại (14/08 —
        # trước đây cứng vi rồi en). Thứ tự giữ vi trước: máy ưu tiên tiếng Việt.
        _nhom = vcfg.stt_nhom_tieng("tin_thoai", "", ["vi", "en"])
        _thu = [x for x in ("vi", "en", "ja", "zh", "ko") if x in _nhom] or ["vi"]
        for try_lang in _thu:
            try:
                if not vcfg.stt_co_model(try_lang):
                    continue
                if try_lang == "en" and vcfg.stt_en_model_dir() is None:
                    continue
                text = _normalize_stt(_sherpa_local(wav16, try_lang))
                if text:
                    return text
            except Exception as exc:
                logger.debug("voice: auto-detect %s fail: %s", try_lang, str(exc)[:80])
        # fallback wyoming client if configured
        uri = vcfg.stt_wyoming_url()
        if uri and backend in {"auto", "wyoming"}:
            try:
                text = _normalize_stt(_wyoming_stt(wav16, uri) or "")
                if text:
                    return text
            except Exception as exc:
                logger.warning("voice: STT wyoming auto fail: %s", str(exc)[:120])
        raise VoiceError("Không nhận dạng được giọng nói (auto VI→EN).")
    errors: list[str] = []
    for mode in _backend_order(backend):
        try:
            if mode == "local":
                text = _sherpa_local(wav16, lang)
            else:
                uri = vcfg.stt_wyoming_url()
                if not uri:
                    continue
                text = _wyoming_stt(wav16, uri)
            text = _normalize_stt(text) if text else ""
            if text:
                return text
            errors.append(f"{mode}: không nghe ra chữ nào")
        except Exception as exc:
            errors.append(f"{mode}: {str(exc)[:120]}")
            logger.warning("voice: STT %s that bai: %s", mode, str(exc)[:160])
    raise VoiceError("Không nhận dạng được giọng nói — " + "; ".join(errors))
