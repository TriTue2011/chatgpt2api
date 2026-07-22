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


def _mixed_catalog() -> list[dict]:
    return [
        {"id": "ngochuyennew", "language": "vi", "language_label": "Giọng Bắc",
         "downloaded": True, "default": True},
        {"id": "vieneu:Phạm Tuyên", "language": "vi-en",
         "language_label": "VieNeu 48kHz", "downloaded": True, "default": False},
        {"id": "kokoro:af_sky", "language": "en", "language_label": "Kokoro EN",
         "downloaded": True, "default": False},
    ]


class InfoTests(unittest.TestCase):
    """Pattern microsoft-stt/tts: 1 program, 1 model, languages list."""

    def test_info_lists_downloaded_voices_and_single_asr_model(self) -> None:
        catalog = [
            {"id": "ngochuyennew", "language": "vi", "language_label": "Giọng Bắc",
             "downloaded": True, "default": True},
            {"id": "vieneu:Phạm Tuyên", "language": "vi-en",
             "language_label": "VieNeu 48kHz", "downloaded": True, "default": False},
            {"id": "kokoro:af_sky", "language": "en", "language_label": "Kokoro EN",
             "downloaded": False, "default": False},
        ]
        with mock.patch.object(vcfg, "voice_catalog", return_value=catalog), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value=None):
            info = wy._info_data()
        names = [v["name"] for v in info["tts"][0]["voices"]]
        self.assertIn("vieneu:Phạm Tuyên", names)
        self.assertNotIn("kokoro:af_sky", names)
        self.assertTrue(info["tts"][0]["supports_synthesize_streaming"])
        # Một program, một model (microsoft-stt)
        self.assertEqual(len(info["asr"]), 1)
        self.assertEqual(info["asr"][0]["name"], "chatgpt2api-stt")
        self.assertEqual(len(info["asr"][0]["models"]), 1)
        langs = info["asr"][0]["languages"]
        self.assertIn("vi", langs)
        self.assertNotIn("vi-VN", langs)
        self.assertNotIn("vi_VN", langs)

    def test_info_multi_one_model_both_langs(self) -> None:
        catalog = [{"id": "v1", "language": "vi", "downloaded": True}]
        with mock.patch.object(vcfg, "voice_catalog", return_value=catalog), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value="y"):
            info = wy._info_data()
        self.assertEqual([p["name"] for p in info["asr"]], ["chatgpt2api-stt"])
        models = info["asr"][0]["models"]
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["name"], "chatgpt2api")
        langs = info["asr"][0]["languages"]
        self.assertIn("auto", langs)
        self.assertIn("vi", langs)
        self.assertIn("en", langs)
        self.assertNotIn("en-US", langs)

    def test_vieneu_voice_advertises_bilingual(self) -> None:
        catalog = [{"id": "vieneu:Ngọc Trân", "language": "vi-en",
                    "language_label": "VieNeu", "downloaded": True, "default": False}]
        with mock.patch.object(vcfg, "voice_catalog", return_value=catalog), \
                mock.patch.object(vcfg, "stt_model_dir", return_value=None), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value=None):
            info = wy._info_data()
        langs = info["tts"][0]["voices"][0]["languages"]
        self.assertIn("vi", langs)
        self.assertIn("en", langs)
        self.assertNotIn("asr", info)

    def test_lang_codes_iso639_1_only(self) -> None:
        self.assertEqual(wy._lang_codes("vi"), ["vi"])
        self.assertEqual(wy._lang_codes("en"), ["en"])
        self.assertEqual(wy._lang_codes("vi-VN"), ["vi"])
        self.assertEqual(wy._lang_codes("en_US"), ["en"])
        self.assertEqual(wy._lang_codes("auto", "vi"), ["auto", "vi"])

    def test_native_voice_languages_not_forced_multi(self) -> None:
        """Piper VI stays vi-only; Kokoro EN also lists vi/en-US for HA pipeline filter."""
        with mock.patch.object(vcfg, "voice_catalog", return_value=_mixed_catalog()), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value="y"):
            info = wy._info_data("")
        piper = next(v for v in info["tts"][0]["voices"] if v["name"] == "ngochuyennew")
        self.assertEqual(piper["languages"], ["vi"])
        kokoro = next(v for v in info["tts"][0]["voices"] if v["name"] == "kokoro:af_sky")
        self.assertIn("en", kokoro["languages"])
        self.assertIn("vi", kokoro["languages"])  # visible on default VI Assist pipeline
        self.assertIn("en-US", kokoro["languages"])
        vieneu = next(
            v for v in info["tts"][0]["voices"] if v["name"] == "vieneu:Phạm Tuyên")
        self.assertIn("vi", vieneu["languages"])
        self.assertIn("en", vieneu["languages"])


class LangLockedInfoTests(unittest.TestCase):
    """_info_data('vi'/'en') legacy filter — không mở cổng thứ hai."""

    def test_vi_filter_only_vietnamese_voices_and_asr(self) -> None:
        with mock.patch.object(vcfg, "voice_catalog", return_value=_mixed_catalog()), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value="y"):
            info = wy._info_data("vi")
        names = [v["name"] for v in info["tts"][0]["voices"]]
        self.assertIn("ngochuyennew", names)
        self.assertIn("vieneu:Phạm Tuyên", names)
        self.assertNotIn("kokoro:af_sky", names)
        self.assertEqual([p["name"] for p in info["asr"]], ["chatgpt2api-stt-vi"])
        self.assertEqual(info["tts"][0]["name"], "chatgpt2api-tts-vi")
        self.assertEqual(len(info["asr"][0]["models"]), 1)
        langs = info["asr"][0]["languages"]
        self.assertIn("vi", langs)
        self.assertNotIn("en", langs)
        self.assertNotIn("languages", info["tts"][0])

    def test_en_filter_only_english_voices_and_asr(self) -> None:
        with mock.patch.object(vcfg, "voice_catalog", return_value=_mixed_catalog()), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value="y"):
            info = wy._info_data("en")
        names = [v["name"] for v in info["tts"][0]["voices"]]
        self.assertIn("kokoro:af_sky", names)
        self.assertNotIn("ngochuyennew", names)
        self.assertNotIn("vieneu:Phạm Tuyên", names)
        self.assertEqual([p["name"] for p in info["asr"]], ["chatgpt2api-stt-en"])
        langs = info["asr"][0]["languages"]
        self.assertIn("en", langs)
        self.assertNotIn("vi", langs)

    def test_en_filter_tts_without_en_stt_omits_asr(self) -> None:
        with mock.patch.object(vcfg, "voice_catalog", return_value=_mixed_catalog()), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value=None):
            info = wy._info_data("en")
        names = [v["name"] for v in info["tts"][0]["voices"]]
        self.assertIn("kokoro:af_sky", names)
        self.assertNotIn("asr", info)


class MultiLangInfoTests(unittest.TestCase):
    def test_multi_has_both_tts_and_stt_langs(self) -> None:
        with mock.patch.object(vcfg, "voice_catalog", return_value=_mixed_catalog()), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value="y"):
            info = wy._info_data("")
        names = [v["name"] for v in info["tts"][0]["voices"]]
        self.assertIn("ngochuyennew", names)
        self.assertIn("kokoro:af_sky", names)
        self.assertIn("vieneu:Phạm Tuyên", names)
        self.assertEqual(info["tts"][0]["name"], "chatgpt2api-tts")
        self.assertEqual(info["asr"][0]["name"], "chatgpt2api-stt")
        self.assertEqual(len(info["asr"][0]["models"]), 1)
        self.assertIn("vi", info["asr"][0]["languages"])
        self.assertIn("en", info["asr"][0]["languages"])
        # Kokoro visible on VI pipeline (1-port multi)
        klangs = next(
            v["languages"] for v in info["tts"][0]["voices"] if v["name"] == "kokoro:af_sky")
        self.assertIn("en", klangs)
        self.assertIn("vi", klangs)
        self.assertIn("en-US", klangs)


class AutoPickTranscriptTests(unittest.TestCase):
    def test_prefers_english_when_en_has_markers(self) -> None:
        # Zipformer often invents Vietnamese for English audio
        self.assertEqual(
            wy._pick_auto_transcript("Quách tham", "what time"),
            "what time",
        )

    def test_prefers_english_without_marker_lexicon(self) -> None:
        # Arbitrary EN phrase not in Assist marker set — script score must still pick EN
        self.assertEqual(
            wy._pick_auto_transcript("mấy giờ rồi nhỉ", "open the garage door please"),
            "open the garage door please",
        )
        self.assertEqual(
            wy._pick_auto_transcript("xin chào bạn", "increase brightness a little"),
            "increase brightness a little",
        )

    def test_prefers_vietnamese_with_diacritics(self) -> None:
        self.assertEqual(
            wy._pick_auto_transcript("bật đèn phòng khách", "bat den"),
            "bật đèn phòng khách",
        )

    def test_single_side(self) -> None:
        self.assertEqual(wy._pick_auto_transcript("", "hello"), "hello")
        self.assertEqual(wy._pick_auto_transcript("xin chào", ""), "xin chào")


class ResolveSttLangTests(unittest.TestCase):
    def test_locked_ports_force_language(self) -> None:
        self.assertEqual(wy._resolve_stt_lang("vi"), "vi")
        self.assertEqual(wy._resolve_stt_lang("en"), "en")

    def test_multi_auto_when_both_engines_and_config_auto(self) -> None:
        with mock.patch.object(vcfg, "stt_language", return_value="auto"), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value="y"):
            self.assertEqual(wy._resolve_stt_lang(""), "auto")
            self.assertTrue(wy._is_multi_stt())

    def test_en_stt_disabled_defaults_to_vi(self) -> None:
        """EN STT off (default): no Parakeet even if model files exist."""
        with mock.patch.object(vcfg, "stt_en_enabled", return_value=False), \
                mock.patch.object(vcfg, "stt_language", return_value="vi"), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value=None):
            self.assertFalse(wy._is_multi_stt())
            self.assertEqual(wy._resolve_stt_lang(""), "vi")
            self.assertEqual(wy._ha_lang_to_stt("en-US", ""), "vi")
            info = wy._info_data()
            self.assertEqual(info["asr"][0]["languages"], ["vi"])

    def test_config_fixed_en(self) -> None:
        with mock.patch.object(vcfg, "stt_language", return_value="en"), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value="y"):
            self.assertEqual(wy._resolve_stt_lang(""), "en")
            self.assertFalse(wy._is_multi_stt())

    def test_ha_lang_multi_respects_pipeline_en_vi(self) -> None:
        """Pipeline EN/VI must force engine when EN STT is available."""
        with mock.patch.object(vcfg, "stt_language", return_value="auto"), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value="y"):
            self.assertEqual(wy._ha_lang_to_stt("vi", ""), "vi")
            self.assertEqual(wy._ha_lang_to_stt("vi-VN", ""), "vi")
            self.assertEqual(wy._ha_lang_to_stt("en-US", ""), "en")
            self.assertEqual(wy._ha_lang_to_stt("en", ""), "en")
            self.assertEqual(wy._ha_lang_to_stt("auto", ""), "auto")
            self.assertEqual(wy._ha_lang_to_stt("", ""), "auto")
            # locked still forces
            self.assertEqual(wy._ha_lang_to_stt("en-US", "vi"), "vi")

    def test_ha_lang_fixed_config_vi(self) -> None:
        with mock.patch.object(vcfg, "stt_language", return_value="vi"), \
                mock.patch.object(vcfg, "stt_model_dir", return_value="x"), \
                mock.patch.object(vcfg, "stt_en_model_dir", return_value="y"):
            self.assertEqual(wy._ha_lang_to_stt("en-US", ""), "vi")

    def test_multi_tts_en_hint_uses_kokoro(self) -> None:
        with mock.patch.object(vcfg, "wyoming_en_voice", return_value="kokoro:af_sky"), \
                mock.patch.object(vcfg, "tts_voice", return_value="ngochuyennew"):
            self.assertEqual(
                wy._resolve_tts_voice("", "ngochuyennew", lang_hint="en-US"),
                "kokoro:af_sky",
            )
            self.assertEqual(
                wy._resolve_tts_voice("", "", lang_hint="en"),
                "kokoro:af_sky",
            )
            self.assertEqual(
                wy._resolve_tts_voice("", "kokoro:af_sky", lang_hint="en"),
                "kokoro:af_sky",
            )


class ResolveTtsVoiceTests(unittest.TestCase):
    def test_en_port_empty_uses_en_default_not_vietnamese(self) -> None:
        with mock.patch.object(vcfg, "wyoming_en_voice",
                               return_value="kokoro:af_sky"), \
                mock.patch.object(vcfg, "tts_voice", return_value="ngochuyennew"):
            self.assertEqual(wy._resolve_tts_voice("en", ""), "kokoro:af_sky")

    def test_en_port_rejects_vietnamese_voice(self) -> None:
        catalog = _mixed_catalog()
        with mock.patch.object(vcfg, "voice_catalog", return_value=catalog), \
                mock.patch.object(vcfg, "wyoming_en_voice",
                                  return_value="kokoro:af_sky"):
            self.assertEqual(
                wy._resolve_tts_voice("en", "ngochuyennew"), "kokoro:af_sky")
            self.assertEqual(
                wy._resolve_tts_voice("en", "kokoro:af_sky"), "kokoro:af_sky")

    def test_vi_port_rejects_english_voice(self) -> None:
        catalog = _mixed_catalog()
        with mock.patch.object(vcfg, "voice_catalog", return_value=catalog), \
                mock.patch.object(vcfg, "tts_voice", return_value="ngochuyennew"):
            self.assertEqual(
                wy._resolve_tts_voice("vi", "kokoro:af_sky"), "ngochuyennew")
            self.assertEqual(
                wy._resolve_tts_voice("vi", "vieneu:Phạm Tuyên"),
                "vieneu:Phạm Tuyên")

    def test_multi_keeps_client_voice(self) -> None:
        self.assertEqual(wy._resolve_tts_voice("", "anything"), "anything")
        self.assertEqual(wy._resolve_tts_voice("", ""), "")


class PortConfigTests(unittest.TestCase):
    def test_single_port_en_aliases_to_main(self) -> None:
        with mock.patch.object(vcfg, "_wy", return_value={"port": 10600, "en_port": 10601}):
            self.assertEqual(vcfg.wyoming_port(), 10600)
            self.assertEqual(vcfg.wyoming_vi_port(), 10600)
            self.assertEqual(vcfg.wyoming_en_port(), 10600)  # no second port


class WyomingEnVoiceConfigTests(unittest.TestCase):
    def test_en_voice_never_empty_when_kokoro_names_exist(self) -> None:
        with mock.patch.object(vcfg, "_wy", return_value={}), \
                mock.patch.object(vcfg, "kokoro_model_dir", return_value=None), \
                mock.patch.object(vcfg, "voice_catalog", return_value=[]):
            v = vcfg.wyoming_en_voice()
        self.assertTrue(v.startswith(vcfg.KOKORO_PREFIX), v)
        self.assertNotEqual(v, "")


if __name__ == "__main__":
    unittest.main()
