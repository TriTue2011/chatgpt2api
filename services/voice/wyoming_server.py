"""Wyoming server nhúng — Home Assistant trỏ THẲNG vào gateway làm TTS + STT,
không cần chạy container tiếng nói riêng (vieneu-wyoming / wyoming-stt / piper).

Giao thức Wyoming (mỗi event = 1 dòng JSON header + `data_length` byte JSON +
`payload_length` byte nhị phân) tự viết bằng stdlib — khớp client sẵn có trong
engines.py, không thêm thư viện.

Multi-language bám wyoming-microsoft-stt + wyoming-microsoft-tts:
  - **Một cổng** (mặc định 10600) — một integration HA, không mirror 10601.
  - **Một** TtsProgram + **một** AsrProgram (không tách -vi/-en entity).
  - ASR: **một** model, ``languages`` = mọi engine có sẵn (vi/en) — HA không xám
    khi pipeline đổi ngôn ngữ.
  - STT mặc định **chỉ tiếng Việt** (Zipformer). Parakeet EN tắt
    (``voice.stt.en_enabled: false``) — offline EN không đủ chuẩn.
  - TTS multi: vẫn có Kokoro EN; pipeline en + voice VI → fallback Kokoro.

Điểm sống còn cho HA (học từ apps/wyoming_server.py của tts-vietneu):
  - info phải khai ``supports_synthesize_streaming: true``
  - Sau AudioStop PHẢI gửi ``synthesize-stopped``
  - HA gửi synthesize-start/chunk/stop + 1 event ``synthesize`` full-text —
    chỉ xử lý cái sau

Bật/tắt: ``voice.wyoming_server.enabled`` (mặc định BẬT).
Cổng: ``voice.wyoming_server.port`` (mặc định 10600).
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
import time
from typing import Any

from services.voice import config as vcfg
from services.voice import engines

logger = logging.getLogger(__name__)

# Một server multi trên :port — thread + event loop riêng.
# Mỗi phần tử: {"thread","loop","port","lang"}.
_servers: list[dict[str, Any]] = []
_servers_lock = threading.Lock()

_DONE = object()          # sentinel: worker thread đã hết audio
_QUEUE_MAX = 8            # lookahead có backpressure, chặn phình RAM


# ── Khung giao thức ──────────────────────────────────────────────────────────


async def _read_event(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    """Đọc 1 event → {"type", "data", "payload"}. None = client đóng kết nối.

    Chấp nhận cả hai kiểu client: data inline trong header ("data": {...})
    lẫn data tách dòng ("data_length": N) — thư viện wyoming dùng kiểu sau.
    """
    try:
        line = await reader.readline()
    except (ConnectionError, asyncio.IncompleteReadError):
        return None
    if not line:
        return None
    try:
        header = json.loads(line)
    except Exception:
        return None
    data = dict(header.get("data") or {})
    dlen = int(header.get("data_length") or 0)
    plen = int(header.get("payload_length") or 0)
    if dlen:
        try:
            data.update(json.loads(await reader.readexactly(dlen)))
        except Exception:
            return None
    payload = b""
    if plen:
        try:
            payload = await reader.readexactly(plen)
        except Exception:
            return None
    return {"type": str(header.get("type") or ""), "data": data, "payload": payload}


async def _write_event(writer: asyncio.StreamWriter, ev_type: str,
                       data: dict | None = None, payload: bytes = b"") -> None:
    data_bytes = json.dumps(data or {}, ensure_ascii=False).encode()
    header: dict[str, Any] = {"type": ev_type, "data_length": len(data_bytes)}
    if payload:
        header["payload_length"] = len(payload)
    writer.write(json.dumps(header).encode() + b"\n" + data_bytes + payload)
    await writer.drain()


# ── Info (describe) ──────────────────────────────────────────────────────────


_ATTR = {"name": "chatgpt2api", "url": "https://github.com/TriTue2011/chatgpt2api"}


def _lang_codes(*base: str) -> list[str]:
    """Mã ngôn ngữ cho Wyoming → HA Assist.

    **Chỉ ISO 639-1** (``vi``, ``en``, ``auto``) — gọn dropdown HA.
    Không quảng cáo ``vi-VN`` / ``en-US`` (mỗi mã = 1 dòng UI lặp).
    """
    out: list[str] = []
    for b in base:
        b = str(b or "").strip().replace("_", "-")
        if not b:
            continue
        low = b.lower()
        if low in {"auto", "mul", "multi", "und", "*"}:
            if "auto" not in out:
                out.insert(0, "auto")
            continue
        primary = low.split("-", 1)[0]
        if primary in {"vi", "en"} and primary not in out:
            out.append(primary)
    return out


def _stt_engines() -> tuple[bool, bool]:
    """(has_vi Zipformer, has_en Parakeet)."""
    return (
        vcfg.stt_model_dir() is not None,
        vcfg.stt_en_model_dir() is not None,
    )


def _is_multi_stt() -> bool:
    """Giống microsoft-stt khi ``--language`` ≥ 2: auto-detect, bỏ qua HA lang."""
    has_vi, has_en = _stt_engines()
    return has_vi and has_en and vcfg.stt_language() == "auto"


def _info_data(lang: str = "") -> dict[str, Any]:
    """Danh mục TTS + ASR cho HA Wyoming — pattern microsoft-stt/tts.

    ``lang`` giữ tương thích test cũ (``""`` | ``vi`` | ``en``) nhưng production
    luôn gọi ``""`` (multi một cổng). Khi ``lang`` khoá: lọc giọng + STT theo
    ngôn ngữ đó (mode locked legacy, không mở cổng thứ hai).
    """
    lang = (lang or "").strip().lower()
    has_vi, has_en = _stt_engines()

    if lang == "vi":
        iso_available = ["vi"] if has_vi else []
    elif lang == "en":
        iso_available = ["en"] if has_en else []
    else:
        iso_available = []
        if has_vi:
            iso_available.append("vi")
        if has_en:
            iso_available.append("en")

    # ── TTS voices (microsoft-tts: mỗi voice 1+ language của chính nó) ──
    voices: list[dict[str, Any]] = []
    for v in vcfg.voice_catalog():
        if not v.get("downloaded"):
            continue
        vlang = str(v.get("language") or "vi")
        primary = vcfg._lang_primary(vlang)
        # Legacy filter (lang=vi|en): chỉ giọng thuộc ngôn ngữ đó
        if lang == "vi" and primary != "vi":
            continue
        if lang == "en" and primary != "en":
            continue

        # Native languages of the voice.
        base = {"vi": ["vi"], "vi-en": ["vi", "en"], "en": ["en"]}.get(
            vlang, ["vi"])
        if lang == "vi":
            bases = [x for x in base if x == "vi"] or ["vi"]
        elif lang == "en":
            bases = [x for x in base if x == "en"] or ["en"]
        else:
            bases = list(base)
        langs = _lang_codes(*bases)
        label = str(v.get("language_label") or "").strip()
        # HA Assist lọc voice theo ngôn ngữ pipeline. Multi 1 cổng: Kokoro
        # chỉ có ``en`` sẽ biến mất khi pipeline mặc định là ``vi``.
        # Quảng cáo thêm en-US + vi để hiện trong dropdown (vẫn 1 port / 1 integration).
        if not lang and primary == "en":
            for extra in ("en", "en-US", "vi"):
                if extra not in langs:
                    langs.append(extra)
            if label and "EN" not in label.upper() and "Kokoro" not in label:
                label = f"EN · {label}"
            elif not label:
                label = "EN · Kokoro"
        desc = f"{v['id']} ({label})" if label else v["id"]
        voices.append({
            "name": v["id"],
            "description": desc,
            "attribution": _ATTR, "installed": True, "version": None,
            "languages": langs,
        })

    # ── ASR: một program + một model (microsoft-stt) ──
    asr_programs: list[dict[str, Any]] = []
    if iso_available:
        model_langs = _lang_codes(*iso_available)
        # Multi (cả vi+en): thêm auto vào languages để HA hiểu auto-detect
        if len(iso_available) >= 2:
            model_langs = _lang_codes("auto", *iso_available)
        model_name = "chatgpt2api"
        if lang in {"vi", "en"}:
            model_name = lang
            desc = (
                f"{'Vietnamese Zipformer' if lang == 'vi' else 'English Parakeet'}"
            )
        elif len(iso_available) >= 2:
            desc = "Zipformer (vi) + Parakeet (en) — multi auto-detect"
        else:
            only = iso_available[0]
            desc = (
                "Vietnamese Zipformer" if only == "vi" else "English Parakeet"
            )
        asr_programs.append({
            "name": "chatgpt2api-stt" if not lang else f"chatgpt2api-stt-{lang}",
            "description": f"Gateway STT — {desc}",
            "attribution": _ATTR,
            "installed": True,
            "version": None,
            "languages": list(model_langs),
            "models": [{
                "name": model_name,
                "description": desc,
                "attribution": _ATTR,
                "installed": True,
                "version": None,
                "languages": list(model_langs),
            }],
            "supports_transcript_streaming": False,
        })

    data: dict[str, Any] = {}
    if voices:
        if lang == "vi":
            tts_name, tts_desc = "chatgpt2api-tts-vi", "Gateway TTS Tiếng Việt"
        elif lang == "en":
            tts_name, tts_desc = "chatgpt2api-tts-en", "Gateway TTS English"
        else:
            tts_name, tts_desc = "chatgpt2api-tts", "Gateway TTS (VieNeu/Kokoro/Piper)"
        data["tts"] = [{
            "name": tts_name,
            "description": tts_desc,
            "attribution": _ATTR,
            "installed": True,
            "version": None,
            "voices": voices,
            "supports_synthesize_streaming": True,
        }]
    if asr_programs:
        data["asr"] = asr_programs
    return data


# ── STT language resolve ─────────────────────────────────────────────────────


def _resolve_stt_lang(server_lang: str = "") -> str:
    """Ngôn ngữ STT mặc định khi chưa có Transcribe / multi override.

    - server_lang vi/en (legacy locked) → ép.
    - Multi engines + stt.language=auto → ``auto`` (microsoft multi).
    - Ngược lại theo config stt.language, kẹp model có sẵn.
    """
    sl = (server_lang or "").strip().lower()
    if sl in {"vi", "en"}:
        return sl
    has_vi, has_en = _stt_engines()
    if has_vi and has_en and vcfg.stt_language() == "auto":
        return "auto"
    lang = vcfg.stt_language()  # vi | en | auto
    if lang == "auto" and not (has_vi and has_en):
        lang = "en" if has_en and not has_vi else "vi"
    elif lang == "en" and not has_en:
        lang = "auto" if has_vi and has_en else "vi"
    elif lang == "vi" and not has_vi:
        lang = "en" if has_en else "vi"
    return lang


def _ha_lang_to_stt(ha_lang: str, server_lang: str = "") -> str:
    """Map language HA gửi trong Transcribe → vi | en | auto.

    - legacy locked server_lang → ép cổng
    - config ``stt.language`` khóa vi|en → tôn trọng config
    - multi + HA ``en*`` / ``vi*`` → **ép engine** (pipeline EN/VI Assist)
    - multi + HA auto/rỗng → dual-pass auto-detect
    """
    sl = (server_lang or "").strip().lower()
    if sl in {"vi", "en"}:
        return sl
    # Operator khóa cứng vi|en trong Settings
    cfg = vcfg.stt_language()
    has_vi, has_en = _stt_engines()
    if cfg in {"vi", "en"}:
        if cfg == "vi" and has_vi:
            return "vi"
        if cfg == "en" and has_en:
            return "en"
    h = (ha_lang or "").strip().lower().replace("_", "-")
    # Explicit pipeline language from HA — do NOT ignore (EN Assist needs Parakeet)
    if h.startswith("en"):
        return "en" if has_en else ("vi" if has_vi else "en")
    if h.startswith("vi"):
        return "vi" if has_vi else ("en" if has_en else "vi")
    # auto / empty / unknown
    if not h or h in {"auto", "mul", "multi", "und", "*"}:
        if has_vi and has_en and cfg == "auto":
            return "auto"
        return "en" if has_en and not has_vi else "vi"
    if has_vi and has_en and cfg == "auto":
        return "auto"
    return "vi" if has_vi else "en"


def _voice_primary(voice_id: str) -> str:
    """Ngôn ngữ chính của id giọng (catalog); rỗng nếu không biết."""
    vid = (voice_id or "").strip()
    if not vid:
        return ""
    if vid.startswith(vcfg.KOKORO_PREFIX):
        return "en"
    if vid.startswith(vcfg.VIENEU_PREFIX):
        return "vi"
    for v in vcfg.voice_catalog():
        if str(v.get("id") or "") == vid:
            return vcfg._lang_primary(str(v.get("language") or "vi"))
    return ""


def _resolve_tts_voice(
    server_lang: str,
    client_voice: str = "",
    lang_hint: str = "",
) -> str:
    """Chọn id giọng TTS.

    Multi (server_lang ``""``):
      - voice client EN → giữ
      - pipeline/language hint ``en`` + voice VI/rỗng → Kokoro EN (tránh đọc EN bằng giọng VI)
      - hint ``vi`` + voice EN → giọng VI mặc định
    Legacy locked en/vi: không cho rơi sang ngôn ngữ kia.
    """
    sl = (server_lang or "").strip().lower()
    vname = (client_voice or "").strip()
    hint = (lang_hint or "").strip().lower().replace("_", "-")
    if sl == "en":
        if vname and _voice_primary(vname) == "en":
            return vname
        if vname:
            logger.info(
                "wyoming[en]: bo giọng không-Anh %r → mặc định EN", vname[:60],
            )
        return vcfg.wyoming_en_voice()
    if sl == "vi":
        if not vname:
            return vcfg.tts_voice()
        if _voice_primary(vname) == "en":
            logger.info(
                "wyoming[vi]: bo giọng Anh %r → mặc định VI", vname[:60],
            )
            return vcfg.tts_voice()
        return vname
    # multi
    want_en = hint.startswith("en")
    want_vi = hint.startswith("vi")
    primary = _voice_primary(vname) if vname else ""
    if want_en:
        if primary == "en":
            return vname
        if vname and primary != "en":
            logger.info(
                "wyoming[multi]: pipeline EN, bo giọng %r → Kokoro EN", vname[:60],
            )
        return vcfg.wyoming_en_voice()
    if want_vi:
        if primary == "en":
            logger.info(
                "wyoming[multi]: pipeline VI, bo giọng EN %r → VI", vname[:60],
            )
            return vcfg.tts_voice()
        return vname or vcfg.tts_voice()
    return vname


# Optional Assist EN lexicon — *bonus only*, not the main signal.
# Main pick uses script scoring (ASCII Latin vs Vietnamese diacritics) so
# arbitrary English (not in this set) still wins over VI hallucinations.
_EN_WORD_MARKERS = frozenset({
    # WH / copula / articles
    "what", "when", "where", "who", "why", "how", "which", "whose",
    "is", "are", "am", "was", "were", "be", "been", "being",
    "the", "a", "an", "this", "that", "these", "those",
    # common Assist / smart-home
    "please", "turn", "on", "off", "light", "lights", "lamp", "switch",
    "temperature", "weather", "humidity", "thermostat",
    "play", "stop", "pause", "resume", "volume", "mute", "unmute",
    "hello", "hi", "yes", "no", "ok", "okay", "thanks", "thank", "you",
    "good", "morning", "afternoon", "evening", "night",
    "today", "tomorrow", "yesterday", "time", "clock", "o", "clock",
    "open", "close", "set", "make", "call", "tell", "show", "give",
    "kitchen", "bedroom", "living", "room", "bathroom", "garage",
    "door", "window", "fan", "ac", "heater", "camera", "lock", "unlock",
})


def _is_viet_letter(ch: str) -> bool:
    o = ord(ch)
    # Latin-1 supplement + Latin extended + Vietnamese block
    return (0x00C0 <= o <= 0x024F) or (0x1EA0 <= o <= 0x1EF9)


def _has_viet_diacritics(text: str) -> bool:
    return any(_is_viet_letter(ch) for ch in (text or "") if ch.isalpha())


def _letter_stats(text: str) -> tuple[int, int, int]:
    """Return (ascii_letters, viet_letters, total_letters)."""
    ascii_n = viet_n = total = 0
    for ch in text or "":
        if not ch.isalpha():
            continue
        total += 1
        if _is_viet_letter(ch):
            viet_n += 1
        elif ord(ch) < 128:
            ascii_n += 1
    return ascii_n, viet_n, total


def _en_marker_hits(text: str) -> int:
    import re
    words = set(re.findall(r"[a-zA-Z']+", (text or "").lower()))
    return len(words & _EN_WORD_MARKERS)


def _word_count(text: str) -> int:
    import re
    return len(re.findall(r"[A-Za-z\u00C0-\u1EF9']+", text or ""))


def _score_as_english(text: str) -> float:
    """How much *text* looks like English (for Parakeet output)."""
    if not (text or "").strip():
        return -1e9
    ascii_n, viet_n, total = _letter_stats(text)
    if total <= 0:
        return -1e9
    ascii_r = ascii_n / total
    viet_r = viet_n / total
    wc = _word_count(text)
    hits = _en_marker_hits(text)
    # Clean English: almost all ASCII letters, almost no VI diacritics
    score = ascii_r * 3.0 - viet_r * 4.0
    score += min(wc, 8) * 0.12
    score += hits * 0.35  # Assist lexicon bonus only
    # Short pure-ASCII without markers is weak (often EN model noise on VI speech)
    if wc <= 2 and hits == 0 and viet_n == 0:
        score -= 1.6
    return score


def _score_as_vietnamese(text: str) -> float:
    """How much *text* looks like Vietnamese (for Zipformer output)."""
    if not (text or "").strip():
        return -1e9
    ascii_n, viet_n, total = _letter_stats(text)
    if total <= 0:
        return -1e9
    viet_r = viet_n / total
    ascii_r = ascii_n / total
    # Diacritics are the strongest offline signal for real VI speech
    score = viet_r * 4.0 + (1.0 - ascii_r) * 0.5
    score += min(_word_count(text), 8) * 0.1
    # Any real VI letters strongly suggests Zipformer heard Vietnamese
    if viet_n >= 1:
        score += 1.6
    if viet_n >= 3:
        score += 0.8
    # Pure-ASCII "VI" is often Zipformer garbage on EN audio — downrank
    if viet_n == 0 and ascii_n >= 3:
        score -= 1.2
    return score


def _pick_auto_transcript(vi: str, en: str) -> str:
    """Chọn bản transcript khi cả Zipformer và Parakeet đều non-empty.

    Không phụ thuộc từ điển EN đầy đủ: so sánh
      score(en_text as English)  vs  score(vi_text as Vietnamese).
    Marker list chỉ là *bonus* cho lệnh Assist thường gặp.
    """
    if not vi:
        return en
    if not en:
        return vi
    s_en = _score_as_english(en)
    s_vi = _score_as_vietnamese(vi)
    # Tie-break: slight VI preference (primary home language) only if nearly equal
    if s_en > s_vi + 0.05:
        return en
    if s_vi > s_en + 0.05:
        return vi
    # Near tie — prefer more English markers, else VI
    if _en_marker_hits(en) > _en_marker_hits(vi):
        return en
    return vi


def _transcribe_auto(wav: bytes) -> str:
    """Multi offline: chạy cả vi + en (khi có), chọn bản tốt hơn.

    Không dừng ở kết quả VI đầu tiên — Zipformer hay «bịa» tiếng Việt cho
    audio tiếng Anh (vd. «what time» → «Quách tham»).
    """
    has_vi, has_en = _stt_engines()
    results: dict[str, str] = {}
    for lang in ("vi", "en"):
        if lang == "vi" and not has_vi:
            continue
        if lang == "en" and not has_en:
            continue
        try:
            text = (engines.transcribe(wav, "", lang) or "").strip()
            if text:
                results[lang] = text
        except Exception as exc:
            logger.debug("wyoming: auto-detect %s that bai: %s", lang, str(exc)[:120])
    if not results:
        return ""
    if len(results) == 1:
        return next(iter(results.values()))
    pick = _pick_auto_transcript(results.get("vi", ""), results.get("en", ""))
    logger.info(
        "wyoming: auto-pick vi=%r en=%r → %r",
        (results.get("vi") or "")[:48],
        (results.get("en") or "")[:48],
        pick[:48],
    )
    return pick


# ── TTS stream ───────────────────────────────────────────────────────────────


def _produce(text: str, voice: str, queue: asyncio.Queue,
             loop: asyncio.AbstractEventLoop) -> None:
    """Worker thread: kéo (rate, pcm16) từ generator blocking, đẩy vào queue."""
    try:
        for item in engines.stream_synthesize(text, voice):
            asyncio.run_coroutine_threadsafe(queue.put(item), loop).result()
    except Exception as exc:
        try:
            asyncio.run_coroutine_threadsafe(queue.put(exc), loop).result()
        except Exception:
            pass
    finally:
        try:
            asyncio.run_coroutine_threadsafe(queue.put(_DONE), loop).result()
        except Exception:
            pass


async def _handle_synthesize(writer: asyncio.StreamWriter, text: str,
                             voice: str) -> None:
    text = (text or "").strip()
    voice = (voice or "").strip()
    logger.info("wyoming: synthesize %d chars, voice=%s", len(text), voice or "(mặc định)")
    queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
    loop = asyncio.get_running_loop()
    producer = loop.run_in_executor(None, _produce, text, voice, queue, loop)

    started = False
    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            if isinstance(item, Exception):
                logger.warning("wyoming: TTS loi: %s", str(item)[:160])
                break
            rate, pcm = item
            if not started:
                await _write_event(writer, "audio-start",
                                   {"rate": int(rate), "width": 2, "channels": 1})
                started = True
            await _write_event(writer, "audio-chunk",
                               {"rate": int(rate), "width": 2, "channels": 1}, pcm)
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        while True:
            try:
                leftover = queue.get_nowait()
                if leftover is _DONE:
                    break
            except asyncio.QueueEmpty:
                if producer.done():
                    break
                await asyncio.sleep(0.05)
        try:
            if not started:
                await _write_event(writer, "audio-start",
                                   {"rate": 48000, "width": 2, "channels": 1})
            await _write_event(writer, "audio-stop")
            await _write_event(writer, "synthesize-stopped")
        except Exception:
            pass


# ── Kết nối ──────────────────────────────────────────────────────────────────


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                  server_lang: str = "") -> None:
    sock = writer.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
    asr = {
        "rate": 16000, "width": 2, "channels": 1,
        "pcm": bytearray(),
        "lang": _resolve_stt_lang(server_lang),
        "program": "",
        "ha_lang": "",  # last HA language (for TTS voice pick)
    }
    loop = asyncio.get_running_loop()
    try:
        while True:
            ev = await _read_event(reader)
            if ev is None:
                break
            t = ev["type"]
            if t == "describe":
                await _write_event(writer, "info", _info_data(server_lang))
            elif t == "select-program":
                asr["program"] = str(ev["data"].get("name") or "").strip()
                logger.info("wyoming: select-program %s", asr["program"])
            elif t == "synthesize":
                v = ev["data"].get("voice") or {}
                raw = str(v.get("name") or "") if isinstance(v, dict) else ""
                vlang = ""
                if isinstance(v, dict):
                    vlang = str(v.get("language") or "")
                lang_hint = (
                    vlang
                    or str(ev["data"].get("language") or "")
                    or str(asr.get("ha_lang") or "")
                    or str(asr.get("lang") or "")
                )
                vname = _resolve_tts_voice(server_lang, raw, lang_hint=lang_hint)
                await _handle_synthesize(
                    writer, str(ev["data"].get("text") or ""), vname)
            elif t in ("synthesize-start", "synthesize-chunk", "synthesize-stop"):
                pass
            elif t == "transcribe":
                ha_lang = str(ev["data"].get("language") or "").lower().replace("_", "-")
                asr["ha_lang"] = ha_lang
                asr["lang"] = _ha_lang_to_stt(ha_lang, server_lang)
                logger.info(
                    "wyoming[%s]: transcribe ha_lang=%s → %s",
                    server_lang or "multi", ha_lang or "-", asr["lang"],
                )
            elif t == "audio-start":
                asr["rate"] = int(ev["data"].get("rate") or 16000)
                asr["width"] = int(ev["data"].get("width") or 2)
                asr["channels"] = int(ev["data"].get("channels") or 1)
                asr["pcm"] = bytearray()
                if not asr["lang"]:
                    asr["lang"] = _resolve_stt_lang(server_lang)
            elif t == "audio-chunk":
                asr["pcm"] += ev["payload"]
            elif t == "audio-stop":
                text = ""
                t0 = time.time()
                sl = (server_lang or "").strip().lower()
                if sl in {"vi", "en"}:
                    stt_lang = sl
                else:
                    stt_lang = str(asr.get("lang") or "") or _resolve_stt_lang("")
                asr["lang"] = stt_lang
                try:
                    wav = engines._pcm_to_wav(bytes(asr["pcm"]), asr["rate"],
                                              asr["width"], asr["channels"])
                    if stt_lang == "auto":
                        text = await loop.run_in_executor(
                            None, _transcribe_auto, wav)
                    else:
                        text = await loop.run_in_executor(
                            None, engines.transcribe, wav, "", stt_lang)
                    dt = time.time() - t0
                    audio_len_s = len(asr["pcm"]) / (
                        asr["rate"] * asr["width"] * asr["channels"])
                    rtf = dt / audio_len_s if audio_len_s > 0 else 0
                    logger.info(
                        "wyoming: STT [%s] '%s' | %d chars | audio=%.2fs "
                        "infer=%.2fs RTF=%.2f",
                        stt_lang, text, len(text), audio_len_s, dt, rtf)
                except Exception as exc:
                    logger.warning("wyoming: STT loi: %s", str(exc)[:160])
                await _write_event(writer, "transcript", {"text": text})
            elif t == "ping":
                await _write_event(writer, "pong")
    except (ConnectionError, asyncio.CancelledError):
        pass
    except Exception as exc:
        logger.warning("wyoming: ket noi loi: %s", str(exc)[:160])
    finally:
        try:
            writer.close()
        except Exception:
            pass


# ── Vòng đời ─────────────────────────────────────────────────────────────────


async def _main(port: int, server_lang: str) -> None:
    server = await asyncio.start_server(
        lambda r, w: _handle(r, w, server_lang), "0.0.0.0", port)
    logger.info("voice: Wyoming server [%s] (TTS+STT cho HA) nghe tai 0.0.0.0:%d",
                server_lang or "multi", port)
    async with server:
        await server.serve_forever()


def _run(port: int, server_lang: str) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    with _servers_lock:
        for s in _servers:
            if s["port"] == port:
                s["loop"] = loop
    try:
        loop.run_until_complete(_main(port, server_lang))
    except Exception as exc:
        logger.warning("voice: Wyoming server [%s] :%d dung: %s",
                       server_lang or "multi", port, str(exc)[:160])
    finally:
        try:
            loop.close()
        except Exception:
            pass


def _has_capability(server_lang: str = "") -> bool:
    """Có ít nhất 1 TTS voice HOẶC STT model."""
    if not server_lang:
        has_tts = any(v.get("downloaded") for v in vcfg.voice_catalog())
        has_vi, has_en = _stt_engines()
        return has_tts or has_vi or has_en
    has_tts = any(
        v.get("downloaded")
        and vcfg._lang_primary(str(v.get("language") or "vi")) == server_lang
        for v in vcfg.voice_catalog()
    )
    has_vi, has_en = _stt_engines()
    if server_lang == "vi":
        return has_tts or has_vi
    if server_lang == "en":
        return has_tts or has_en
    return True


def _start_one(port: int, server_lang: str = "") -> None:
    with _servers_lock:
        for s in _servers:
            if s["port"] == port and s["thread"].is_alive():
                return
        th = threading.Thread(
            target=_run, args=(port, server_lang),
            name=f"wyoming-voice-{server_lang or 'multi'}", daemon=True)
        _servers.append({"thread": th, "loop": None, "port": port, "lang": server_lang})
    th.start()


def start() -> None:
    """Khởi động Wyoming multi trên **một** cổng (mặc định 10600).

    Pattern microsoft-stt/tts: 1 URI, 1 catalog TTS+STT đa ngôn ngữ.
    Không mở mirror 10601.

    No-op nếu ``voice.wyoming_server.enabled = false``.
    """
    if not vcfg.wyoming_enabled():
        logger.info("voice: Wyoming server tat (voice.wyoming_server.enabled=false)")
        return
    port = vcfg.wyoming_port()
    if not _has_capability(""):
        logger.info("voice: bo qua Wyoming (khong co TTS/STT)")
        return
    _start_one(port, "")
    has_vi, has_en = _stt_engines()
    langs = []
    if has_vi:
        langs.append("vi")
    if has_en:
        langs.append("en")
    mode = "multi-auto" if _is_multi_stt() else (
        f"fixed-{vcfg.stt_language()}" if langs else "tts-only")
    logger.info(
        "voice: Wyoming MULTI :%d — STT=%s TTS=all voices — mode=%s",
        port, "+".join(langs) or "none", mode,
    )


def stop() -> None:
    with _servers_lock:
        servers = list(_servers)
        _servers.clear()
    for s in servers:
        loop = s.get("loop")
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
