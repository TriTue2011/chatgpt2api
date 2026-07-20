"""Wyoming server nhúng — Home Assistant trỏ THẲNG vào gateway làm TTS + STT,
không cần chạy container tiếng nói riêng (vieneu-wyoming / wyoming-stt / piper).

Giao thức Wyoming (mỗi event = 1 dòng JSON header + `data_length` byte JSON +
`payload_length` byte nhị phân) tự viết bằng stdlib — khớp client sẵn có trong
engines.py, không thêm thư viện.

Điểm sống còn cho HA (học từ apps/wyoming_server.py của tts-vietneu):
  - info phải khai `supports_synthesize_streaming: true`, nếu không HA đệm
    TRỌN bài rồi mới phát — mất sạch lợi thế streaming.
  - Sau AudioStop PHẢI gửi thêm `synthesize-stopped` — reader streaming của HA
    chỉ dừng chờ khi thấy event này.
  - HA gửi synthesize-start/chunk/stop rồi LUÔN kèm 1 event `synthesize`
    full-text (tương thích ngược) — chỉ cần xử lý cái sau, bộ ba kia bỏ qua.
  - TTS blocking chạy ở worker thread, đẩy chunk qua asyncio.Queue để event
    loop rảnh mà ghi socket ngay khi chunk sẵn sàng.

Bật/tắt: config `voice.wyoming_server.enabled` (mặc định BẬT) + `.port`
(mặc định 10600). Container phải publish port trong docker-compose:
`ports: ["10600:10600"]` thì máy HA mới gọi tới được.
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

_thread: threading.Thread | None = None
_loop: asyncio.AbstractEventLoop | None = None

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


def _info_data() -> dict[str, Any]:
    """Danh mục TTS voices + ASR models cho HA — chỉ liệt kê thứ đã tải model."""
    voices = []
    for v in vcfg.voice_catalog():
        if not v.get("downloaded"):
            continue
        langs = {"vi": ["vi"], "vi-en": ["vi", "en"], "en": ["en"]}.get(
            str(v.get("language") or "vi"), ["vi"])
        label = str(v.get("language_label") or "").strip()
        desc = f"{v['id']} ({label})" if label else v["id"]
        voices.append({
            "name": v["id"],
            "description": desc,
            "attribution": _ATTR, "installed": True, "version": None,
            "languages": langs,
        })
    models = []
    has_vi = vcfg.stt_model_dir() is not None
    has_en = vcfg.stt_en_model_dir() is not None
    if has_vi:
        models.append({"name": "vi", "description": "Zipformer tiếng Việt (6000h)",
                       "attribution": _ATTR, "installed": True, "version": None,
                       "languages": ["vi"]})
    if has_en:
        models.append({"name": "en", "description": "NVIDIA Parakeet-TDT 0.6B (English)",
                       "attribution": _ATTR, "installed": True, "version": None,
                       "languages": ["en"]})
    # Model "auto": tự nhận diện — thử ngôn ngữ nào có model trước, dùng kết quả có chữ.
    if has_vi or has_en:
        models.insert(0, {"name": "auto",
                          "description": "Auto-detect (vi→en, nhận diện ngôn ngữ tự động)",
                          "attribution": _ATTR, "installed": True, "version": None,
                          "languages": ["vi", "en"]})
    data: dict[str, Any] = {}
    if voices:
        data["tts"] = [{
            "name": "chatgpt2api-tts", "description": "Gateway TTS (VieNeu/Kokoro/Piper)",
            "attribution": _ATTR, "installed": True, "version": None,
            "voices": voices,
            # BẮT BUỘC true: HA mới phát AudioChunk ngay khi tới (streaming).
            "supports_synthesize_streaming": True,
        }]
    if models:
        data["asr"] = [{
            "name": "chatgpt2api-stt", "description": "Gateway STT (auto / vi / en)",
            "attribution": _ATTR, "installed": True, "version": None,
            "models": models,
        }]
    return data


# ── STT auto-detect language ─────────────────────────────────────────────────


def _transcribe_auto(wav: bytes) -> str:
    """Thử nhận diện vi trước, nếu trả về rỗng thì thử en.

    Ưu tiên tiếng Việt vì đó là ngôn ngữ chính. Nếu cả hai đều
    rỗng (im lặng / tạp âm) trả rỗng. Không ném exception.
    """
    has_vi = vcfg.stt_model_dir() is not None
    has_en = vcfg.stt_en_model_dir() is not None
    candidates: list[str] = []
    if has_vi:
        candidates.append("vi")
    if has_en:
        candidates.append("en")
    for lang in candidates:
        try:
            text = engines.transcribe(wav, "", lang)
            if text.strip():
                return text.strip()
        except Exception as exc:
            logger.debug("wyoming: auto-detect %s that bai: %s", lang, str(exc)[:120])
    return ""


# ── TTS: stream frame/câu từ engines.stream_synthesize ──────────────────────


def _produce(text: str, voice: str, queue: asyncio.Queue,
             loop: asyncio.AbstractEventLoop) -> None:
    """Worker thread: kéo (rate, pcm16) từ generator blocking, đẩy vào queue.
    queue.put chạy trên loop; .result() chặn thread NÀY (không chặn loop) khi
    queue đầy → backpressure thật."""
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
        pass  # client rớt giữa chừng
    finally:
        # Xả queue tới khi worker xong để nó không kẹt ở put() rồi rò thread.
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
            if not started:   # không ra được audio nào — vẫn phải đóng chu trình
                await _write_event(writer, "audio-start",
                                   {"rate": 48000, "width": 2, "channels": 1})
            await _write_event(writer, "audio-stop")
            await _write_event(writer, "synthesize-stopped")
        except Exception:
            pass


# ── Kết nối ──────────────────────────────────────────────────────────────────


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    sock = writer.get_extra_info("socket")
    if sock is not None:
        try:      # Nagle gom các gói audio-chunk nhỏ → tắt cho stream mượt.
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
    asr = {"rate": 16000, "width": 2, "channels": 1,
           "pcm": bytearray(), "lang": ""}
    loop = asyncio.get_running_loop()
    try:
        while True:
            ev = await _read_event(reader)
            if ev is None:
                break
            t = ev["type"]
            if t == "describe":
                await _write_event(writer, "info", _info_data())
            elif t == "synthesize":
                v = ev["data"].get("voice") or {}
                await _handle_synthesize(
                    writer, str(ev["data"].get("text") or ""),
                    str(v.get("name") or "") if isinstance(v, dict) else "")
            elif t in ("synthesize-start", "synthesize-chunk", "synthesize-stop"):
                # HA luôn gửi kèm `synthesize` full-text — cái đó mới chạy.
                pass
            elif t == "transcribe":
                lang = str(ev["data"].get("language") or "").lower()
                model = str(ev["data"].get("name") or "").lower()
                if model == "auto" or lang == "auto" or not lang:
                    asr["lang"] = "auto"   # tự nhận diện khi HA không chỉ định
                elif lang.startswith("en"):
                    asr["lang"] = "en"
                else:
                    # HA KHÔNG BAO GIỜ gửi tên model (chỉ gửi language) và UI
                    # pipeline lọc ngôn ngữ theo trợ lý → model "auto" không thể
                    # chọn từ HA. Vì thế pipeline Tiếng Việt cũng auto-fallback:
                    # vi trước, vi không nghe ra chữ mới thử en (nếu có model en)
                    # — nói tiếng Việt kết quả y hệt, chỉ thêm đường cứu câu Anh.
                    asr["lang"] = "auto" if vcfg.stt_en_model_dir() is not None else "vi"
            elif t == "audio-start":
                asr["rate"] = int(ev["data"].get("rate") or 16000)
                asr["width"] = int(ev["data"].get("width") or 2)
                asr["channels"] = int(ev["data"].get("channels") or 1)
                asr["pcm"] = bytearray()
            elif t == "audio-chunk":
                asr["pcm"] += ev["payload"]
            elif t == "audio-stop":
                text = ""
                t0 = time.time()
                try:
                    wav = engines._pcm_to_wav(bytes(asr["pcm"]), asr["rate"],
                                              asr["width"], asr["channels"])
                    if asr["lang"] == "auto":
                        text = await loop.run_in_executor(
                            None, _transcribe_auto, wav)
                    else:
                        text = await loop.run_in_executor(
                            None, engines.transcribe, wav, "", asr["lang"])
                    dt = time.time() - t0
                    audio_len_s = len(asr["pcm"]) / (asr["rate"] * asr["width"] * asr["channels"])
                    rtf = dt / audio_len_s if audio_len_s > 0 else 0
                    logger.info("wyoming: STT [%s] '%s' | %d chars | audio=%.2fs infer=%.2fs RTF=%.2f",
                                asr["lang"], text, len(text), audio_len_s, dt, rtf)
                except Exception as exc:
                    logger.warning("wyoming: STT loi: %s", str(exc)[:160])
                await _write_event(writer, "transcript", {"text": text})
            elif t == "ping":
                await _write_event(writer, "pong")
            # event lạ: bỏ qua, giữ kết nối
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


async def _main() -> None:
    port = vcfg.wyoming_port()
    server = await asyncio.start_server(_handle, "0.0.0.0", port)
    logger.info("voice: Wyoming server (TTS+STT cho HA) nghe tai 0.0.0.0:%d", port)
    async with server:
        await server.serve_forever()


def _run() -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(_main())
    except Exception as exc:
        logger.warning("voice: Wyoming server dung: %s", str(exc)[:160])
    finally:
        try:
            _loop.close()
        except Exception:
            pass


def start() -> None:
    """Chạy server ở thread riêng (event loop riêng, không đụng loop uvicorn).
    No-op nếu voice.wyoming_server.enabled = false hoặc đã chạy."""
    global _thread
    if not vcfg.wyoming_enabled():
        logger.info("voice: Wyoming server tat (voice.wyoming_server.enabled=false)")
        return
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=_run, name="wyoming-voice", daemon=True)
    _thread.start()


def stop() -> None:
    if _loop is not None:
        try:
            _loop.call_soon_threadsafe(_loop.stop)
        except Exception:
            pass
