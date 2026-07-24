"""Kênh giọng nói: TTS (Piper) · STT (sherpa-onnx/Zipformer) · phát ra loa.

Public API gọn cho phần còn lại của dự án:

    from services import voice
    wav  = voice.speak("Xin chào")          # text → WAV bytes
    text = voice.listen(ogg_bytes, "ogg")   # voice note → text
    url  = voice.media_url(voice.save_media(wav))
    voice.play_on(speaker, url)             # phát ra loa đã đặt tên

Model KHÔNG nằm trong image (xem config.py) — tải bằng script vào volume.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from services.voice import config as vcfg
from services.voice import speakers as vspk
from services.voice.engines import (
    VoiceError, stream_synthesize, synthesize, transcribe, warmup_tts,
    _split_sentences, _wav_parts,
)

logger = logging.getLogger(__name__)

__all__ = [
    "VoiceError", "speak", "speak_stream", "speak_reply", "listen",
    "save_media", "media_url", "play_on", "play_text_on", "cleanup_media",
    "status", "warmup_tts", "tts_ready", "stt_ready",
]


def tts_ready() -> bool:
    return vcfg.is_tts_enabled()


def stt_ready() -> bool:
    return vcfg.is_stt_enabled()


def status() -> dict[str, Any]:
    st = vcfg.status()
    st["speakers"] = len(vspk.list_speakers())
    return st


def speak(text: str, voice_name: str = "", *, style: str = "",
          session_id: str = "", subject: str = "") -> bytes:
    """Text → WAV bytes (ném VoiceError nếu chưa sẵn sàng).

    `style` (tu_nhien|tin_tuc|doc_truyen) chỉ tác dụng với giọng VieNeu.
    """
    if not voice_name:
        if subject:
            from services.agent import teacher
            voice_name = teacher.voice_for_subject(subject, text)
        elif session_id:
            from services.voice import session_voice
            voice_name = session_voice.get_tts_voice_for_session(session_id)
    return synthesize(text, voice_name, style=style)


def speak_stream(text: str, voice_name: str = "", *, style: str = "",
                 session_id: str = "", subject: str = ""):
    """Generator yield (sample_rate, pcm16_mono_bytes) — đọc tới đâu phát tới đó."""
    if not voice_name:
        if subject:
            from services.agent import teacher
            voice_name = teacher.voice_for_subject(subject, text)
        elif session_id:
            from services.voice import session_voice
            voice_name = session_voice.get_tts_voice_for_session(session_id)
    return stream_synthesize(text, voice_name, style=style)


def speak_reply(text: str, persona_key: str = "", *, session_id: str = "",
                voice_name: str = "", style: str = "") -> bytes:
    """TTS cho câu TRẢ LỜI của bot: chọn giọng theo phiên + style theo TÍNH CHẤT
    câu (đùa/nghiêm túc/an ủi) — 0 token model.

    Ưu tiên giọng:
      1. voice_name ép tay
      2. Cấu hình RIÊNG theo phiên (session_voice): user-trong-nhóm → nhóm/1-1
         → bot → kênh (Settings → Giọng theo phiên)
      3. Giọng suy từ persona của phiên
      4. Giọng mặc định hệ thống
    Lỗi tra cấu hình/persona không làm hỏng TTS — luôn có đường lùi.
    """
    v = voice_name
    base_style = ""
    # (2) Cấu hình riêng từng kênh / bot / nhóm / user / user-trong-nhóm.
    # Dùng get_session_voice_config (KHÔNG dùng get_tts_voice_for_session) để
    # khi phiên chưa cài riêng thì còn rơi xuống giọng theo persona bên dưới.
    if not v and session_id:
        try:
            from services.voice import session_voice as _sv
            v = str((_sv.get_session_voice_config(session_id) or {}).get("tts_voice") or "").strip()
        except Exception:
            pass
    if persona_key and not (v and style):
        try:
            from services.agent import persona as _persona
            pv = _persona.voice_for(persona_key) or {}
            v = voice_name or str(pv.get("voice") or "")
            base_style = str(pv.get("style") or "")
        except Exception:
            pass
    st = style
    if not st:
        try:
            from services.voice import tone as _tone
            st = _tone.style_for(text, base_style)
        except Exception:
            st = base_style
    return speak(text, v, style=st)


def listen(audio: bytes, src_hint: str = "", lang: str = "", *, session_id: str = "", subject: str = "") -> str:
    """Voice note (ogg/m4a/wav…) → text. `lang` = vi|en (rỗng = theo config)."""
    if not lang:
        if subject:
            from services.agent import teacher
            stt_cfg = teacher.stt_for_subject(subject)
            lang = stt_cfg.get("language") or ""
        elif session_id:
            from services.voice import session_voice
            stt_cfg = session_voice.get_stt_config_for_session(session_id)
            lang = stt_cfg.get("language") or ""
    return transcribe(audio, src_hint, lang)



# ── Media: loa cần URL HTTP, không nhận bytes ────────────────────────────────


def save_media(data: bytes, suffix: str = ".wav") -> Path:
    """Ghi audio vào data/voice/media và trả đường dẫn file."""
    d = vcfg.media_dir()
    path = d / f"{int(time.time())}_{uuid.uuid4().hex[:8]}{suffix}"
    path.write_bytes(data)
    return path


def media_url(path: Path) -> str:
    """URL công khai của file media để loa trong LAN kéo về.

    Loa Cast/DLNA nằm ở LAN nên KHÔNG dùng được localhost — phải cấu hình
    `voice.public_base_url` (hoặc `base_url`) trỏ đúng IP/domain của gateway.
    """
    base = vcfg.public_base_url()
    if not base:
        raise VoiceError(
            "Chưa đặt voice.public_base_url — loa trong nhà không tải được file "
            "từ localhost. Điền IP/domain của gateway trong Settings."
        )
    return f"{base}/media/voice/{path.name}"


def cleanup_media(max_age_hours: int = 0) -> int:
    """Xoá file audio cũ (mặc định theo voice.media_retention_hours)."""
    hours = max_age_hours or vcfg.media_retention_hours()
    cutoff = time.time() - hours * 3600
    removed = 0
    try:
        for p in vcfg.media_dir().glob("*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except Exception:
                continue
    except Exception as exc:
        logger.warning("voice: don media loi: %s", exc)
    return removed


def play_on(speaker: dict[str, Any], url: str) -> None:
    """Phát URL sẵn có ra loa."""
    vspk.play_url(speaker, url)


def _wav_duration_s(wav: bytes) -> float:
    """Độ dài WAV (giây). Lỗi → 0."""
    try:
        rate, width, channels, pcm = _wav_parts(wav)
        if rate <= 0 or width <= 0:
            return 0.0
        return len(pcm) / float(rate * width * max(int(channels) or 1, 1))
    except Exception:
        return 0.0


def play_text_on(text: str, speaker: dict[str, Any], voice_name: str = "") -> str:
    """Đọc `text` rồi phát ra loa. Trả URL file đã phát.

    Tối ưu TTFA (VieNeu / câu dài): synthesize **câu đầu** → phát ngay, vừa phát
    vừa synthesize phần còn lại, rồi phát tiếp khi câu đầu gần hết — người nghe
    không phải chờ full WAV (thường 1–2s+ prefill + full decode).
    """
    text = (text or "").strip()
    if not text:
        raise VoiceError("Không có nội dung để đọc.")
    v = (voice_name or vcfg.tts_voice()).strip()
    sents = _split_sentences(text, max_chars=180)

    # Câu ngắn / 1 mẩu / không phải pipeline có ích → đường cũ (1 file).
    if len(sents) <= 1:
        wav = speak(text, v)
        path = save_media(wav)
        url = media_url(path)
        play_on(speaker, url)
        cleanup_media()
        return url

    first_wav = speak(sents[0], v)
    path1 = save_media(first_wav)
    url1 = media_url(path1)

    rest = " ".join(sents[1:]).strip()
    rest_wav: bytes | None = None
    rest_err: Exception | None = None

    def _synth_rest() -> None:
        nonlocal rest_wav, rest_err
        try:
            rest_wav = speak(rest, v)
        except Exception as exc:
            rest_err = exc

    # Synth phần còn lại song song lúc loa bắt đầu câu 1 (VieNeu lock tuần tự
    # nhưng câu 1 đã xong → rest chiếm engine ngay khi play_on đang chờ cast).
    th = threading.Thread(target=_synth_rest, name="tts-rest", daemon=True)
    if rest:
        th.start()
    play_on(speaker, url1)
    if rest:
        th.join(timeout=180)
        if rest_err:
            logger.warning("play_text_on: synth phần sau lỗi: %s", rest_err)
        elif rest_wav:
            # Chờ gần hết câu 1 rồi mới push câu sau (tránh Cast cắt giữa chừng).
            wait = max(0.0, _wav_duration_s(first_wav) - 0.15)
            if wait > 0:
                time.sleep(wait)
            path2 = save_media(rest_wav)
            url2 = media_url(path2)
            try:
                play_on(speaker, url2)
                cleanup_media()
                return url2
            except Exception as exc:
                logger.warning("play_text_on: phát phần sau lỗi: %s", exc)
    cleanup_media()
    return url1
