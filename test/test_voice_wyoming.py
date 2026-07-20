from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.voice import config as vcfg  # noqa: E402
from services.voice import wyoming_server as wy  # noqa: E402


class _DummyWriter:
    """Gom bytes _write_event ghi ra để parse lại bằng _read_event."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def write(self, data: bytes) -> None:
        self.buf += data

    async def drain(self) -> None:
        pass


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FramingTests(unittest.TestCase):
    def test_write_then_read_roundtrip(self) -> None:
        async def go():
            w = _DummyWriter()
            await wy._write_event(w, "audio-chunk",
                                  {"rate": 48000, "width": 2, "channels": 1},
                                  b"\x01\x02\x03\x04")
            r = asyncio.StreamReader()
            r.feed_data(bytes(w.buf))
            r.feed_eof()
            return await wy._read_event(r)

        ev = _run(go())
        self.assertEqual(ev["type"], "audio-chunk")
        self.assertEqual(ev["data"]["rate"], 48000)
        self.assertEqual(ev["payload"], b"\x01\x02\x03\x04")

    def test_read_inline_data_style(self) -> None:
        # Client kiểu cũ nhét data inline trong header — phải đọc được.
        async def go():
            frame = json.dumps(
                {"type": "transcribe", "data": {"language": "en-US"}}).encode() + b"\n"
            r = asyncio.StreamReader()
            r.feed_data(frame)
            r.feed_eof()
            return await wy._read_event(r)

        ev = _run(go())
        self.assertEqual(ev["type"], "transcribe")
        self.assertEqual(ev["data"]["language"], "en-US")

    def test_read_eof_returns_none(self) -> None:
        async def go():
            r = asyncio.StreamReader()
            r.feed_eof()
            return await wy._read_event(r)

        self.assertIsNone(_run(go()))


class InfoTests(unittest.TestCase):
    def test_info_lists_downloaded_voices_and_models(self) -> None:
        catalog = [
            {"id": "ngochuyennew", "language": "vi", "language_label": "Giọng Bắc",
             "downloaded": True, "default": True},
            {"id": "vieneu:Phạm Tuyên", "language": "vi-en",
             "language_label": "VieNeu 48kHz", "downloaded": True, "default": False},
            {"id": "kokoro:af_sky", "language": "en", "language_label": "Kokoro EN",
             "downloaded": False, "default": False},   # chưa tải → phải ẨN
        ]
        with mock.patch.object(vcfg, "voice_catalog", return_value=catalog), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value=None):
            info = wy._info_data()
        names = [v["name"] for v in info["tts"][0]["voices"]]
        self.assertIn("vieneu:Phạm Tuyên", names)
        self.assertNotIn("kokoro:af_sky", names)
        self.assertTrue(info["tts"][0]["supports_synthesize_streaming"])
        models = [m["name"] for m in info["asr"][0]["models"]]
        self.assertEqual(models, ["auto", "vi"])

    def test_vieneu_voice_advertises_bilingual(self) -> None:
        catalog = [{"id": "vieneu:Ngọc Trân", "language": "vi-en",
                    "language_label": "VieNeu", "downloaded": True, "default": False}]
        with mock.patch.object(vcfg, "voice_catalog", return_value=catalog), \
                mock.patch.object(vcfg, "stt_model_dir", return_value=None), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value=None):
            info = wy._info_data()
        self.assertEqual(info["tts"][0]["voices"][0]["languages"], ["vi", "en"])
        self.assertNotIn("asr", info)


if __name__ == "__main__":
    unittest.main()
