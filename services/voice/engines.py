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


def _kokoro_tts(text: str, voice: str) -> bytes:
    """Giọng "kokoro:<tên>" → WAV 24 kHz (chỉ đọc tiếng Anh)."""
    tts = _get_kokoro()
    name = voice[len(vcfg.KOKORO_PREFIX):].strip() \
        if voice.startswith(vcfg.KOKORO_PREFIX) else ""
    with _kokoro_lock:
        audio = tts.generate(text, sid=vcfg.kokoro_sid(name), speed=1.0)
    samples = audio.samples or []
    if not samples:
        raise VoiceError("Kokoro không tạo được âm thanh.")
    # numpy nhanh hơn vòng lặp Python từng sample ~15x (giống _float_to_pcm16
    # dùng cho VieNeu phía trên).
    pcm = _float_to_pcm16(samples)
    return _pcm_to_wav(pcm, int(audio.sample_rate), 2, 1)


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

    tts = _get_nghi(_nghi_voice_id(voice) or nv.DEFAULT_ID)
    # Mỗi model một giọng (num_speakers = 1) nên sid luôn 0.
    with _nghi_lock:
        audio = tts.generate(text, sid=0, speed=1.0)
    samples = audio.samples if audio is not None else None
    if samples is None or len(samples) == 0:
        raise VoiceError("NghiTTS không tạo được âm thanh.")
    return _pcm_to_wav(_float_to_pcm16(samples), int(audio.sample_rate), 2, 1)


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
    cho MỌI engine: text được cắt thành mẩu, mỗi mẩu một lần gọi engine, nối
    lại bằng im lặng. Cả hai khoảng lặng = 0 → đọc trọn text một lần như cũ.

    Hàm cắt/ghép nằm ở khối "TTS streaming" bên dưới (dùng chung với
    `stream_synthesize`).
    """
    text = (text or "").strip()
    if not text:
        raise VoiceError("Không có nội dung để đọc.")
    if (voice or "").startswith("dangu:"):
        return synthesize_da_ngu(text, voice[len("dangu:"):])
    sent_ms, clause_ms, jitter = _silence_plan()
    if sent_ms <= 0 and clause_ms <= 0:
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
        pcm_parts.append(pcm)
        if i < len(segs) - 1 and (width, channels) == (2, 1):
            gap = _silence_pcm(
                _jitter_ms(sent_ms if kind == "sentence" else clause_ms, jitter),
                rate)
            if gap:
                pcm_parts.append(gap)
    if fmt is None or not pcm_parts:
        raise VoiceError("Không tổng hợp được giọng nói.")
    rate, width, channels = fmt
    return _pcm_to_wav(b"".join(pcm_parts), rate, width, channels)


# ── TTS streaming: "chữ sinh ra tới đâu đọc tới đó" ──────────────────────────
# stream_synthesize() yield (sample_rate, pcm16_mono_bytes) NGAY khi có, để
# caller phát dần. VieNeu chạy frame-level qua infer_stream (TTFA ~1s, RTF<1
# ở 1 thread nên mượt). Các engine còn lại (Kokoro/Piper/Wyoming) không stream
# theo frame → cắt câu rồi đọc từng câu: câu xong tới đâu phát tới đó.

import random as _random
import re as _re

# Kết thúc câu: . ! ? … và xuống dòng. Giữ ranh giới để không mất dấu.
_SENT_SPLIT = _re.compile(r"(?<=[.!?…。！？])\s+|\n+")

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


def _split_sentences(text: str, max_chars: int = 240) -> list[str]:
    """Cắt text thành mẩu ngắn để đọc dần. Gộp mẩu quá ngắn, xẻ mẩu quá dài
    theo dấu phẩy để câu đầu ra audio sớm (giảm thời gian chờ)."""
    out: list[str] = []
    for raw in _SENT_SPLIT.split(text or ""):
        s = raw.strip()
        if not s:
            continue
        while len(s) > max_chars:
            cut = _comma_cut(s, max_chars)
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


# Ranh giới MỆNH ĐỀ trong một câu: phẩy, chấm phẩy, hai chấm.
_CLAUSE_MARKS = ",;:，；："


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
        if ch not in _CLAUSE_MARKS:
            continue
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
    """Cắt text thành [(mẩu, loại ranh giới SAU mẩu)] — loại ∈ sentence|clause.

    Caller dựa vào loại ranh giới để chọn khoảng lặng dài (hết câu) hay ngắn
    (hết mệnh đề). `clause_ms <= 0` → không xẻ theo mệnh đề, mỗi mẩu là một câu
    y như `_split_sentences`.
    """
    out: list[tuple[str, str]] = []
    for sent in _split_sentences(text, max_chars):
        parts = _split_clauses(sent) if clause_ms > 0 else [sent]
        for i, p in enumerate(parts):
            out.append((p, "sentence" if i == len(parts) - 1 else "clause"))
    return out


def _silence_plan() -> tuple[int, int, int]:
    """(nghỉ hết câu, nghỉ hết mệnh đề, dao động %) — đọc config một lần/lượt."""
    return (vcfg.tts_sentence_silence_ms(), vcfg.tts_clause_silence_ms(),
            vcfg.tts_silence_jitter_percent())


def _vieneu_stream(text: str, voice: str, style: str = ""):
    """Frame-level: yield (48000, pcm16) từng khối np.float32 do infer_stream trả.

    max_chars nhỏ (config, mặc định 128) → prefill ngắn hơn câu đầu → TTFA thấp.
    """
    eng = _get_vieneu()
    kwargs = _vieneu_kwargs(voice, style)
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
        return {"ok": False, "engine": "", "ms": 0, "detail": "no local tts model"}
    except Exception as exc:
        ms = int((_time.perf_counter() - t0) * 1000)
        logger.warning("voice: warmup TTS loi (%d ms): %s", ms, str(exc)[:160])
        return {"ok": False, "engine": "", "ms": ms, "detail": str(exc)[:160]}


def stream_synthesize(text: str, voice: str = "", *, style: str = ""):
    """Generator yield (sample_rate, pcm16_mono_bytes) — đọc tới đâu phát tới đó.

    VieNeu → frame-level; còn lại → theo câu (đọc xong câu nào phát câu đó).
    Giữa hai mẩu chèn khoảng lặng theo config: hết câu dùng
    `sentence_silence_ms`, hết mệnh đề (dấu phẩy…) dùng `clause_silence_ms`.
    Cả hai = 0 thì VieNeu đọc trọn đoạn trong một lần gọi như trước.
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

    sent_ms, clause_ms, jitter = _silence_plan()
    segs = _split_segments(text, clause_ms=clause_ms)

    def _gap_ms(kind: str) -> int:
        """Khoảng lặng (đã rải ngẫu nhiên) cho ranh giới vừa đọc xong."""
        return _jitter_ms(sent_ms if kind == "sentence" else clause_ms, jitter)

    if v.startswith(vcfg.VIENEU_PREFIX):
        try:
            yielded = False
            last_rate = 0
            prev_kind = ""
            # Không đặt khoảng lặng nào → giữ đường cũ: một lần gọi cho cả đoạn,
            # engine tự lo nhịp (ngữ điệu liền mạch nhất).
            khuc = segs if (sent_ms > 0 or clause_ms > 0) else [(text, "")]
            for seg, kind in khuc:
                if prev_kind and last_rate:
                    gap = _silence_pcm(_gap_ms(prev_kind), last_rate)
                    if gap:
                        _keep((last_rate, gap))
                        yield (last_rate, gap)
                for item in _vieneu_stream(seg, v, style):
                    yielded = True
                    last_rate = item[0]
                    _keep(item)
                    yield item
                prev_kind = kind
            if yielded:
                if captured:
                    tts_cache.put(ck, captured, size_bytes=_captured_bytes)
                return
        except Exception as exc:
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
            **extra,
        )
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
