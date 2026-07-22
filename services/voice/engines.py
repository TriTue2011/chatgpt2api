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
import socket
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from urllib.parse import urlparse

from services.voice import config as vcfg

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


def _vieneu_kwargs(voice: str) -> dict:
    kwargs: dict = {
        "style": vcfg.vieneu_style(),
        "apply_watermark": False,
        "max_chars": vcfg.vieneu_max_chars(),
    }
    name = _vieneu_voice_name(voice)
    if name:
        kwargs["voice"] = name
    return kwargs


def _float_to_pcm16(audio) -> bytes:
    import numpy as np
    return (np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
            * 32767.0).astype("<i2").tobytes()


def _vieneu_tts(text: str, voice: str) -> bytes:
    """Giọng "vieneu:<Tên>" → WAV 48 kHz. Tên rỗng = giọng mặc định của model."""
    eng = _get_vieneu()
    kwargs = _vieneu_kwargs(voice)
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


def _kokoro_tts(text: str, voice: str) -> bytes:
    """Giọng "kokoro:<tên>" → WAV 24 kHz (chỉ đọc tiếng Anh)."""
    tts = _get_kokoro()
    name = voice[len(vcfg.KOKORO_PREFIX):].strip() \
        if voice.startswith(vcfg.KOKORO_PREFIX) else ""
    with _kokoro_lock:
        audio = tts.generate(text, sid=vcfg.kokoro_sid(name), speed=1.0)
    samples = list(audio.samples or [])
    if not samples:
        raise VoiceError("Kokoro không tạo được âm thanh.")
    import array
    pcm = array.array("h", (
        int(max(-1.0, min(1.0, s)) * 32767) for s in samples)).tobytes()
    return _pcm_to_wav(pcm, int(audio.sample_rate), 2, 1)


# ── TTS ──────────────────────────────────────────────────────────────────────


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
            input=text.encode("utf-8"), capture_output=True, timeout=180,
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


def synthesize(text: str, voice: str = "") -> bytes:
    """Text → WAV bytes. Ném VoiceError nếu không có đường nào chạy được.

    Giọng namespaced ("vieneu:<Tên>") đi thẳng engine tương ứng; lỗi thì rơi
    xuống Piper/Wyoming với giọng mặc định để trợ lý không bao giờ "câm".
    """
    text = (text or "").strip()
    if not text:
        raise VoiceError("Không có nội dung để đọc.")
    backend = vcfg.tts_backend()
    if backend == "off":
        raise VoiceError("TTS đang tắt.")
    errors: list[str] = []
    v = (voice or vcfg.tts_voice()).strip()
    if v.startswith(vcfg.VIENEU_PREFIX):
        try:
            return _vieneu_tts(text, v)
        except Exception as exc:
            errors.append(f"vieneu: {str(exc)[:120]}")
            logger.warning("voice: TTS vieneu that bai: %s", str(exc)[:160])
            v = ""          # fallback: giọng Piper mặc định
    elif v.startswith(vcfg.KOKORO_PREFIX):
        try:
            return _kokoro_tts(text, v)
        except Exception as exc:
            errors.append(f"kokoro: {str(exc)[:120]}")
            logger.warning("voice: TTS kokoro that bai: %s", str(exc)[:160])
            v = ""          # fallback: giọng Piper mặc định
    for mode in _backend_order(backend):
        try:
            if mode == "local":
                return _piper_local(text, v)
            uri = vcfg.tts_wyoming_url()
            if not uri:
                continue
            return _wyoming_tts(text, uri)
        except Exception as exc:
            errors.append(f"{mode}: {str(exc)[:120]}")
            logger.warning("voice: TTS %s that bai: %s", mode, str(exc)[:160])
    raise VoiceError("Không tổng hợp được giọng nói — " + "; ".join(errors))


# ── TTS streaming: "chữ sinh ra tới đâu đọc tới đó" ──────────────────────────
# stream_synthesize() yield (sample_rate, pcm16_mono_bytes) NGAY khi có, để
# caller phát dần. VieNeu chạy frame-level qua infer_stream (TTFA ~1s, RTF<1
# ở 1 thread nên mượt). Các engine còn lại (Kokoro/Piper/Wyoming) không stream
# theo frame → cắt câu rồi đọc từng câu: câu xong tới đâu phát tới đó.

import re as _re

# Kết thúc câu: . ! ? … và xuống dòng. Giữ ranh giới để không mất dấu.
_SENT_SPLIT = _re.compile(r"(?<=[.!?…。！？])\s+|\n+")


def _split_sentences(text: str, max_chars: int = 240) -> list[str]:
    """Cắt text thành mẩu ngắn để đọc dần. Gộp mẩu quá ngắn, xẻ mẩu quá dài
    theo dấu phẩy để câu đầu ra audio sớm (giảm thời gian chờ)."""
    out: list[str] = []
    for raw in _SENT_SPLIT.split(text or ""):
        s = raw.strip()
        if not s:
            continue
        while len(s) > max_chars:
            cut = s.rfind(",", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            out.append(s[:cut].strip())
            s = s[cut:].strip(" ,")
        if s:
            out.append(s)
    # Dồn mẩu tí hon (<15 ký tự, vd "Vâng.", "OK.") SANG mẩu sau để tránh clip
    # audio vụn <1s, nhưng vẫn giữ câu bình thường tách riêng cho stream mượt.
    merged: list[str] = []
    buf = ""
    for s in out:
        if buf:
            s = (buf + " " + s).strip()
            buf = ""
        if len(s) < 15:
            buf = s
        else:
            merged.append(s)
    if buf:
        if merged:
            merged[-1] = merged[-1] + " " + buf
        else:
            merged.append(buf)
    return merged


def _vieneu_stream(text: str, voice: str):
    """Frame-level: yield (48000, pcm16) từng khối np.float32 do infer_stream trả.

    max_chars nhỏ (config, mặc định 128) → prefill ngắn hơn câu đầu → TTFA thấp.
    """
    eng = _get_vieneu()
    kwargs = _vieneu_kwargs(voice)
    # Giữ khoá suốt stream: session ONNX tuần tự; tránh 2 request giành graph.
    with _vieneu_lock:
        for chunk in eng.infer_stream(text, **kwargs):
            if chunk is None or len(chunk) == 0:
                continue
            yield (48000, _float_to_pcm16(chunk))


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


def warmup_tts(voice: str = "") -> dict:
    """Nạp model + warm + đo TTFA; int8 không đạt target → auto chuyển fp32.

    Gọi nền lúc startup. Best-effort: lỗi chỉ log, không ném ra ngoài.
    Trả dict {ok, engine, ms, warm_ttfa_s, precision, switched, …}.
    """
    import time as _time
    t0 = _time.perf_counter()
    v = (voice or vcfg.tts_voice()).strip()
    try:
        # Ưu tiên warm VieNeu khi model đã tải (kể cả voice mặc định đang là Piper)
        # — cold load ONNX trên Xeon ~10s; warmup nền lúc startup cắt TTFA lần 1.
        if vcfg.vieneu_installed() and vcfg.vieneu_model_ready():
            if not v.startswith(vcfg.VIENEU_PREFIX):
                cats = [x["id"] for x in vcfg.voice_catalog()
                        if str(x.get("id", "")).startswith(vcfg.VIENEU_PREFIX)
                        and x.get("downloaded")]
                v = cats[0] if cats else f"{vcfg.VIENEU_PREFIX}"
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
            return out
        if v.startswith(vcfg.KOKORO_PREFIX) and vcfg.kokoro_model_dir():
            _kokoro_tts("Hello.", v)
            ms = int((_time.perf_counter() - t0) * 1000)
            logger.info("voice: warmup Kokoro xong (%d ms)", ms)
            return {"ok": True, "engine": "kokoro", "ms": ms, "voice": v}
        return {"ok": False, "engine": "", "ms": 0, "detail": "no local tts model"}
    except Exception as exc:
        ms = int((_time.perf_counter() - t0) * 1000)
        logger.warning("voice: warmup TTS loi (%d ms): %s", ms, str(exc)[:160])
        return {"ok": False, "engine": "", "ms": ms, "detail": str(exc)[:160]}


def stream_synthesize(text: str, voice: str = ""):
    """Generator yield (sample_rate, pcm16_mono_bytes) — đọc tới đâu phát tới đó.

    VieNeu → frame-level; còn lại → theo câu (đọc xong câu nào phát câu đó).
    Không bao giờ ném giữa chừng cho lỗi 1 câu: bỏ qua câu lỗi, đọc tiếp.
    """
    text = (text or "").strip()
    if not text:
        raise VoiceError("Không có nội dung để đọc.")
    if vcfg.tts_backend() == "off":
        raise VoiceError("TTS đang tắt.")
    v = (voice or vcfg.tts_voice()).strip()

    if v.startswith(vcfg.VIENEU_PREFIX):
        try:
            yielded = False
            for item in _vieneu_stream(text, v):
                yielded = True
                yield item
            if yielded:
                return
        except Exception as exc:
            logger.warning("voice: stream vieneu that bai, fallback cau: %s",
                           str(exc)[:160])
        v = ""   # fallback về Piper mặc định theo câu ở dưới

    # Kokoro/Piper/Wyoming/fallback: đọc theo câu, dùng lại synthesize().
    errors: list[str] = []
    for sent in _split_sentences(text):
        try:
            wav = synthesize(sent, v)
            rate, width, _channels, pcm = _wav_parts(wav)
            if width == 2 and pcm:
                yield (rate, pcm)
        except Exception as exc:
            errors.append(str(exc)[:100])
            logger.warning("voice: stream cau that bai: %s", str(exc)[:160])
    if errors and len(errors) >= len(_split_sentences(text)):
        raise VoiceError("Không đọc được câu nào — " + "; ".join(errors[:3]))


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
    if lang == "en":
        model_dir = vcfg.stt_en_model_dir()
        if model_dir is None:
            raise VoiceError(
                "Chưa tải model STT tiếng Anh (chạy scripts/download_stt_en_model.py).")
        model_type = "nemo_transducer"
    else:
        model_dir = vcfg.stt_model_dir()
        if model_dir is None:
            raise VoiceError("Chưa tải model STT (chạy scripts/download_stt_model.py).")
        model_type = ""
    key = f"{model_dir}|{vcfg.stt_threads()}"
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
            decoding_method="greedy_search",
            **extra,
        )
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


def _sherpa_local(wav16: bytes, lang: str = "vi") -> str:
    import numpy as np

    rec = _get_recognizer(lang)
    rate, width, _channels, pcm = _wav_parts(wav16)
    if width != 2:
        raise VoiceError("STT cần WAV 16-bit.")
    # numpy nhanh hơn list comprehension ~15x — thấy rõ khi audio dài.
    # sherpa-onnx nhận thẳng mảng float32, đừng .tolist() kẻo mất cái lợi đó.
    floats = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    stream = rec.create_stream()
    stream.accept_waveform(rate, floats)
    rec.decode_stream(stream)
    return _normalize_stt(str(stream.result.text or ""))


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
    else:
        lang = "vi"
    wav16 = to_wav_16k_mono(audio, src_hint)
    if lang == "auto":
        # Local auto: vi trước, en sau (cùng logic wyoming _transcribe_auto)
        for try_lang in ("vi", "en"):
            try:
                if try_lang == "vi" and vcfg.stt_model_dir() is None:
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
