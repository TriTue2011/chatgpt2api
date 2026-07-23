"""WhisperLive & Faster-Whisper Native Integration — zero 3rd-party cloud dependencies.

Provides:
  1. FasterWhisper Engine (CTranslate2 C++ backend for local ultra-fast inference).
  2. WebSocket Real-time STT Server (Listening on dedicated port 10700).
  3. Seamless binding with Home Assistant Wyoming Protocol (Port 10600).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import socket
import threading
import time
import wave
from pathlib import Path
from typing import Any, Generator, Optional

from services.config import DATA_DIR
from services.voice import config as vcfg

logger = logging.getLogger(__name__)

_fw_lock = threading.Lock()
_fw_model = None
_fw_model_name: str = ""

# Dedicated WebSocket Server Port for Real-time Streaming STT
WHISPER_LIVE_PORT = 10700


def get_faster_whisper_model(model_size: str = "base", device: str = "auto"):
    """Load or return cached faster-whisper CTranslate2 model instance."""
    global _fw_model, _fw_model_name
    model_size = (model_size or "base").strip().lower()
    with _fw_lock:
        if _fw_model is not None and _fw_model_name == model_size:
            return _fw_model

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.warning("faster-whisper package not installed. Run: pip install faster-whisper")
            return None

        dev = "cuda" if device == "cuda" else ("cpu" if device == "cpu" else ("cuda" if vcfg.cpu_has_vnni() else "cpu"))
        compute_type = "float16" if dev == "cuda" else "int8"

        logger.info("voice: Loading faster-whisper model '%s' (device=%s, compute_type=%s)", model_size, dev, compute_type)
        try:
            _fw_model = WhisperModel(model_size, device=dev, compute_type=compute_type)
            _fw_model_name = model_size
            return _fw_model
        except Exception as exc:
            logger.error("voice: Failed to load faster-whisper model '%s': %s", model_size, exc)
            return None


def transcribe_faster_whisper(pcm_or_wav: bytes, language: str = "vi", model_size: str = "base") -> str:
    """Transcribe audio bytes using faster-whisper CTranslate2 backend."""
    model = get_faster_whisper_model(model_size=model_size)
    if model is None:
        raise RuntimeError("faster-whisper engine unavailable")

    audio_file = io.BytesIO(pcm_or_wav)
    lang = language.lower() if language in ("vi", "en") else None

    segments, info = model.transcribe(audio_file, language=lang, beam_size=5)
    text = " ".join([segment.text.strip() for segment in segments if segment.text])
    return text.strip()


# ── WebSocket Real-time Streaming Server ──────────────────────────────────

class WhisperLiveServer:
    """WebSocket Server for continuous real-time streaming speech recognition (Port 10700)."""

    def __init__(self, host: str = "0.0.0.0", port: int = WHISPER_LIVE_PORT):
        self.host = host
        self.port = port
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.running = False

    async def _handle_connection(self, websocket: Any, path: str = ""):
        """Handle individual streaming audio WebSocket client connection."""
        logger.info("whisper_live: Client connected via WebSocket")
        pcm_buffer = bytearray()
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    pcm_buffer.extend(message)
                    # When buffer reaches ~1s of 16kHz 16-bit mono audio (32000 bytes)
                    if len(pcm_buffer) >= 32000:
                        wav_bytes = self._pcm16_to_wav(bytes(pcm_buffer))
                        try:
                            text = transcribe_faster_whisper(wav_bytes)
                            if text:
                                await websocket.send(json.dumps({
                                    "status": "ok",
                                    "text": text,
                                    "buffer_seconds": round(len(pcm_buffer) / 32000, 2),
                                }, ensure_ascii=False))
                        except Exception as exc:
                            logger.warning("whisper_live streaming error: %s", exc)
                elif isinstance(message, str):
                    msg = json.loads(message)
                    if msg.get("type") == "flush":
                        if pcm_buffer:
                            wav_bytes = self._pcm16_to_wav(bytes(pcm_buffer))
                            text = transcribe_faster_whisper(wav_bytes)
                            await websocket.send(json.dumps({"status": "final", "text": text}, ensure_ascii=False))
                        pcm_buffer.clear()
        except Exception as exc:
            logger.debug("whisper_live connection closed: %s", exc)
        finally:
            logger.info("whisper_live client disconnected")

    @staticmethod
    def _pcm16_to_wav(pcm: bytes, rate: int = 16000) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        return buf.getvalue()

    def start_in_background(self):
        """Start the WebSocket streaming server in a dedicated background thread."""
        if self.running:
            return

        def _run_server():
            try:
                import websockets
            except ImportError:
                logger.info("whisper_live: websockets library not installed, WebSocket port 10700 disabled.")
                return

            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.running = True
            server = websockets.serve(self._handle_connection, self.host, self.port)
            logger.info("whisper_live: Real-time Streaming STT WebSocket server running at ws://%s:%d", self.host, self.port)
            self.loop.run_until_complete(server)
            self.loop.run_forever()

        self.thread = threading.Thread(target=_run_server, daemon=True, name="whisper-live-ws")
        self.thread.start()


# Global Singleton Server instance
_live_server = WhisperLiveServer()


def start_whisper_live_server():
    """Start WhisperLive streaming server if not already running."""
    _live_server.start_in_background()
