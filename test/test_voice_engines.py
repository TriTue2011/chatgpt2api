from __future__ import annotations

import io
import os
import unittest
import wave
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.voice import config as vcfg  # noqa: E402
from services.voice import engines, tts_cache  # noqa: E402


def _wav16(ms: int = 100) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * (16 * ms))
    return buf.getvalue()


def _wav22(ms: int = 100) -> bytes:
    """WAV 22,05 kHz — giả engine dự phòng có tần số khác _wav16."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * round(22.05 * ms))
    return buf.getvalue()


class KokoroConfigTests(unittest.TestCase):
    def test_sid_mapping(self) -> None:
        self.assertEqual(vcfg.kokoro_sid("af"), 0)
        self.assertEqual(vcfg.kokoro_sid("af_sky"), 4)
        self.assertEqual(vcfg.kokoro_sid("bm_lewis"), 10)

    def test_unknown_name_falls_back_to_zero(self) -> None:
        self.assertEqual(vcfg.kokoro_sid("khong-ton-tai"), 0)


class VoiceCatalogTests(unittest.TestCase):
    def test_catalog_lists_kokoro_voices(self) -> None:
        ids = {v["id"] for v in vcfg.voice_catalog()}
        self.assertIn("kokoro:af_sky", ids)
        self.assertIn("kokoro:bm_george", ids)

    def test_kokoro_entries_marked_not_downloaded_without_model(self) -> None:
        with mock.patch.object(vcfg, "kokoro_model_dir", return_value=None):
            rows = [v for v in vcfg.voice_catalog()
                    if v["id"].startswith(vcfg.KOKORO_PREFIX)]
        self.assertTrue(rows)
        self.assertTrue(all(v["downloaded"] is False for v in rows))

    def test_prefixed_voice_never_resolves_to_piper_file_of_same_name(self) -> None:
        # Giọng namespaced phải quy về giọng Piper mặc định, không tìm file
        # "vieneu:X.onnx" trong data/piper.
        with mock.patch.object(vcfg, "tts_voice", return_value="vieneu:Ngọc Trân"):
            p = vcfg.voice_model_path()
        self.assertTrue(p is None or p.stem == vcfg._DEFAULT_VOICE)


class SttLanguageTests(unittest.TestCase):
    def test_default_language_is_vi(self) -> None:
        self.assertEqual(vcfg.stt_language(), "vi")

    def test_transcribe_passes_lang_to_local_engine(self) -> None:
        seen: list[str] = []

        def fake_sherpa(wav: bytes, lang: str = "vi") -> str:
            seen.append(lang)
            return "hello"

        with mock.patch.object(engines, "_sherpa_local", side_effect=fake_sherpa), \
                mock.patch.object(vcfg, "stt_backend", return_value="local"):
            out = engines.transcribe(_wav16(), lang="en")
        self.assertEqual(out, "hello")
        self.assertEqual(seen, ["en"])


class SynthesizeRoutingTests(unittest.TestCase):
    def test_vieneu_voice_falls_back_to_piper_when_engine_unavailable(self) -> None:
        # Model VieNeu chưa tải → synthesize phải rơi xuống Piper (mock) thay
        # vì ném lỗi, để trợ lý không bao giờ "câm".
        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(vcfg, "vieneu_model_ready", return_value=False), \
                mock.patch.object(engines, "_piper_local",
                                  return_value=b"RIFFxxx") as piper:
            out = engines.synthesize("xin chào", "vieneu:Ngọc Trân")
        self.assertEqual(out, b"RIFFxxx")
        piper.assert_called_once()
        # Fallback phải dùng giọng Piper mặc định, không truyền id vieneu.
        self.assertEqual(piper.call_args.args[1], "")

    def test_kokoro_voice_uses_kokoro_engine(self) -> None:
        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(engines, "_kokoro_tts",
                                  return_value=b"RIFFkok") as kok:
            out = engines.synthesize("hello there", "kokoro:af_sky")
        self.assertEqual(out, b"RIFFkok")
        kok.assert_called_once()


class SentenceSplitTests(unittest.TestCase):
    def test_splits_on_sentence_boundaries(self) -> None:
        parts = engines._split_sentences(
            "Hôm nay trời rất đẹp và nắng vàng rực rỡ. "
            "Chúng ta cùng nhau đi dạo ngoài công viên nhé! "
            "Bạn thấy ý tưởng này thế nào?")
        self.assertGreaterEqual(len(parts), 3)
        self.assertTrue(all(p.strip() for p in parts))

    def test_merges_tiny_fragments(self) -> None:
        parts = engines._split_sentences("Vâng. Đây là một câu dài đủ để đứng riêng.")
        # "Vâng." quá ngắn → gộp vào mẩu sau, không đứng lẻ.
        self.assertTrue(all(len(p) >= 10 for p in parts))

    def test_long_clause_split_by_comma(self) -> None:
        long = "phần đầu rất dài " * 20 + ", phần sau"
        parts = engines._split_sentences(long, max_chars=100)
        self.assertTrue(all(len(p) <= 120 for p in parts))


class ClauseSplitTests(unittest.TestCase):
    def test_splits_on_comma_and_keeps_the_mark(self) -> None:
        parts = engines._split_clauses(
            "Hôm nay trời rất đẹp, nắng vàng rực rỡ cả ngày.")
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].endswith(","))

    def test_comma_between_digits_is_not_a_boundary(self) -> None:
        # "1,5 triệu" cắt ở phẩy thì engine đọc thành hai số rời.
        s = "Giá bán khoảng 1,5 triệu đồng cho mỗi thùng hàng."
        self.assertEqual(engines._split_clauses(s), [s])
        gio = "Chuyến bay khởi hành lúc 12:30 chiều nay nhé."
        self.assertEqual(engines._split_clauses(gio), [gio])

    def test_short_clause_merged_into_neighbour(self) -> None:
        parts = engines._split_clauses("Vâng, tôi đã bật đèn phòng khách rồi.")
        self.assertEqual(len(parts), 1)      # "Vâng," quá ngắn → gộp

    def test_segments_mark_clause_and_sentence_boundaries(self) -> None:
        text = "Hôm nay trời rất đẹp, nắng vàng rực rỡ. Chúng ta đi dạo nhé."
        kinds = [k for _, k in engines._split_segments(text, clause_ms=180)]
        self.assertEqual(kinds, ["clause", "sentence", "sentence"])
        # clause_ms = 0 → không xẻ theo mệnh đề nữa
        kinds0 = [k for _, k in engines._split_segments(text, clause_ms=0)]
        self.assertEqual(kinds0, ["sentence", "sentence"])


class SynthesizeSilenceTests(unittest.TestCase):
    """Khoảng lặng phải có trong CẢ WAV một-lần (loa, voice note), không chỉ stream."""

    def setUp(self) -> None:
        tts_cache.clear()
        self.addCleanup(tts_cache.clear)
        self.calls: list[str] = []

    def _fake_one(self, text: str, voice: str = "", *, style: str = "") -> bytes:
        self.calls.append(text)
        return _wav16(50)

    def _patch(self, sentence_ms: int, clause_ms: int, jitter: int = 0):
        return (
            mock.patch.object(vcfg, "tts_sentence_silence_ms", return_value=sentence_ms),
            mock.patch.object(vcfg, "tts_clause_silence_ms", return_value=clause_ms),
            mock.patch.object(vcfg, "tts_silence_jitter_percent", return_value=jitter),
        )

    def test_gap_between_sentences_lands_in_the_wav(self) -> None:
        text = ("Hôm nay trời rất đẹp và nắng vàng rực rỡ. "
                "Chúng ta cùng nhau đi dạo ngoài công viên nhé.")
        p1, p2, p3 = self._patch(400, 0)
        with p1, p2, p3, mock.patch.object(engines, "_synthesize_one",
                                           side_effect=self._fake_one):
            wav = engines.synthesize(text, "ngochuyennew")
        self.assertEqual(len(self.calls), 2)
        rate, width, channels, pcm = engines._wav_parts(wav)
        self.assertEqual((rate, width, channels), (16000, 2, 1))
        # 2 mẩu 50 ms + 1 khoảng lặng 400 ms, PCM16 mono @16 kHz
        self.assertEqual(len(pcm), 2 * (16 * 50 * 2) + 16 * 400 * 2)

    def test_clause_gap_splits_inside_a_sentence(self) -> None:
        text = "Hôm nay trời rất đẹp, nắng vàng rực rỡ cả ngày."
        p1, p2, p3 = self._patch(0, 200)
        with p1, p2, p3, mock.patch.object(engines, "_synthesize_one",
                                           side_effect=self._fake_one):
            wav = engines.synthesize(text, "ngochuyennew")
        self.assertEqual(len(self.calls), 2)
        _rate, _w, _c, pcm = engines._wav_parts(wav)
        self.assertEqual(len(pcm), 2 * (16 * 50 * 2) + 16 * 200 * 2)

    def test_silence_off_reads_whole_text_in_one_call(self) -> None:
        text = ("Hôm nay trời rất đẹp và nắng vàng rực rỡ. "
                "Chúng ta cùng nhau đi dạo ngoài công viên nhé.")
        p1, p2, p3 = self._patch(0, 0)
        with p1, p2, p3, mock.patch.object(engines, "_synthesize_one",
                                           side_effect=self._fake_one):
            engines.synthesize(text, "ngochuyennew")
        self.assertEqual(self.calls, [text])

    def test_format_change_midway_falls_back_to_one_call(self) -> None:
        # Câu 2 rơi xuống engine dự phòng (tần số khác) → nối vào là méo tiếng.
        text = ("Hôm nay trời rất đẹp và nắng vàng rực rỡ. "
                "Chúng ta cùng nhau đi dạo ngoài công viên nhé.")

        def doi_dinh_dang(t: str, v: str = "", *, style: str = "") -> bytes:
            self.calls.append(t)
            return _wav16(50) if len(self.calls) != 2 else _wav22(50)

        p1, p2, p3 = self._patch(400, 0)
        with p1, p2, p3, mock.patch.object(engines, "_synthesize_one",
                                           side_effect=doi_dinh_dang):
            wav = engines.synthesize(text, "ngochuyennew")
        self.assertEqual(self.calls[-1], text)      # đọc lại trọn văn bản
        self.assertEqual(engines._wav_parts(wav)[0], 16000)


class StreamSynthesizeTests(unittest.TestCase):
    def setUp(self) -> None:
        # Cache audio dùng chung cả tiến trình — dọn để mỗi test tự đứng.
        tts_cache.clear()
        self.addCleanup(tts_cache.clear)

    def test_non_vieneu_streams_per_sentence(self) -> None:
        # Piper/Kokoro: mỗi câu gọi synthesize() 1 lần, yield (rate, pcm),
        # giữa hai câu chèn thêm một mẩu im lặng cho có nhịp nghỉ.
        calls: list[str] = []

        def fake_synth(sent: str, v: str = "", *, style: str = "") -> bytes:
            calls.append(sent)
            return _wav16(50)

        text = ("Hôm nay trời rất đẹp và nắng vàng rực rỡ. "
                "Chúng ta cùng nhau đi dạo ngoài công viên nhé.")
        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(engines, "synthesize", side_effect=fake_synth):
            out = list(engines.stream_synthesize(text, "ngochuyennew"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(out), 3)
        self.assertEqual(set(out[1][1]), {0})     # mẩu giữa là khoảng lặng
        self.assertTrue(all(r == 16000 and isinstance(p, bytes) for r, p in out))

    def test_vieneu_uses_frame_stream(self) -> None:
        def fake_stream(text: str, v: str, style: str = ""):
            yield (48000, b"\x00\x00" * 100)
            yield (48000, b"\x01\x00" * 100)

        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(engines, "_vieneu_stream", side_effect=fake_stream):
            out = list(engines.stream_synthesize("Xin chào.", "vieneu:Phạm Tuyên"))
        self.assertEqual(len(out), 2)
        self.assertTrue(all(r == 48000 for r, _ in out))

    def test_vieneu_gets_gap_between_sentences(self) -> None:
        # Khoảng lặng áp cho MỌI engine, VieNeu cũng đọc theo câu khi bật.
        seen: list[str] = []

        def fake_stream(text: str, v: str, style: str = ""):
            seen.append(text)
            yield (48000, b"\x01\x00" * 100)

        text = ("Hôm nay trời rất đẹp và nắng vàng rực rỡ. "
                "Chúng ta cùng nhau đi dạo ngoài công viên nhé.")
        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(vcfg, "tts_sentence_silence_ms", return_value=300), \
                mock.patch.object(vcfg, "tts_clause_silence_ms", return_value=0), \
                mock.patch.object(vcfg, "tts_silence_jitter_percent", return_value=0), \
                mock.patch.object(engines, "_vieneu_stream", side_effect=fake_stream):
            out = list(engines.stream_synthesize(text, "vieneu:Phạm Tuyên"))
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(out), 3)
        self.assertEqual(set(out[1][1]), {0})              # mẩu giữa im lặng
        self.assertEqual(len(out[1][1]), 48 * 300 * 2)     # 300 ms @48 kHz

    def test_vieneu_reads_whole_text_when_silence_off(self) -> None:
        seen: list[str] = []

        def fake_stream(text: str, v: str, style: str = ""):
            seen.append(text)
            yield (48000, b"\x01\x00" * 100)

        text = ("Hôm nay trời rất đẹp và nắng vàng rực rỡ. "
                "Chúng ta cùng nhau đi dạo ngoài công viên nhé.")
        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(vcfg, "tts_sentence_silence_ms", return_value=0), \
                mock.patch.object(vcfg, "tts_clause_silence_ms", return_value=0), \
                mock.patch.object(engines, "_vieneu_stream", side_effect=fake_stream):
            out = list(engines.stream_synthesize(text, "vieneu:Phạm Tuyên"))
        self.assertEqual(seen, [text])       # một lần gọi cho cả đoạn
        self.assertEqual(len(out), 1)

    def test_clause_gap_streams_per_clause(self) -> None:
        calls: list[str] = []

        def fake_synth(sent: str, v: str = "", *, style: str = "") -> bytes:
            calls.append(sent)
            return _wav16(50)

        text = "Hôm nay trời rất đẹp, nắng vàng rực rỡ cả ngày."
        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(vcfg, "tts_sentence_silence_ms", return_value=0), \
                mock.patch.object(vcfg, "tts_clause_silence_ms", return_value=200), \
                mock.patch.object(vcfg, "tts_silence_jitter_percent", return_value=0), \
                mock.patch.object(engines, "synthesize", side_effect=fake_synth):
            out = list(engines.stream_synthesize(text, "ngochuyennew"))
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].endswith(","))
        self.assertEqual(len(out), 3)
        self.assertEqual(len(out[1][1]), 16 * 200 * 2)     # 200 ms @16 kHz


class VieNeuThreadConfigTests(unittest.TestCase):
    def test_precision_auto_no_vnni_prefers_fp32(self) -> None:
        # Xeon E5 / không VNNI: int8 stream chậm → auto chọn fp32.
        with mock.patch.object(vcfg, "_sub", return_value={}), \
                mock.patch.object(vcfg, "cpu_has_vnni", return_value=False), \
                mock.patch.object(vcfg, "_vieneu_model_present", return_value=False):
            self.assertEqual(vcfg.tts_precision_prefer(), "fp32")
            self.assertEqual(vcfg.vieneu_precision(), "fp32")

    def test_precision_auto_vnni_prefers_int8(self) -> None:
        with mock.patch.object(vcfg, "_sub", return_value={}), \
                mock.patch.object(vcfg, "cpu_has_vnni", return_value=True), \
                mock.patch.object(vcfg, "_vieneu_model_present", return_value=False):
            self.assertEqual(vcfg.tts_precision_prefer(), "int8")
            self.assertEqual(vcfg.vieneu_precision(), "int8")

    def test_precision_explicit_int8(self) -> None:
        with mock.patch.object(vcfg, "_sub",
                               return_value={"precision": "int8"}), \
                mock.patch.object(vcfg, "_vieneu_model_present", return_value=False):
            self.assertEqual(vcfg.tts_precision_prefer(), "int8")
            self.assertEqual(vcfg.vieneu_precision(), "int8")

    def test_precision_falls_back_to_available_model(self) -> None:
        # Prefer fp32 nhưng chỉ có int8 trên disk → dùng int8.
        def present(p: str) -> bool:
            return p == "int8"

        with mock.patch.object(vcfg, "_sub", return_value={}), \
                mock.patch.object(vcfg, "cpu_has_vnni", return_value=False), \
                mock.patch.object(vcfg, "_vieneu_model_present", side_effect=present):
            self.assertEqual(vcfg.vieneu_precision(), "int8")

    def test_auto_threads_leaves_headroom_on_4cpu(self) -> None:
        # 4 CPU LXC → 2 thread TTS, chừa 2 cho LLM/PDF (không chiếm hết).
        with mock.patch.object(vcfg, "effective_cpu_count", return_value=4):
            self.assertEqual(vcfg.auto_tts_threads(), 2)
        with mock.patch.object(vcfg, "effective_cpu_count", return_value=2):
            self.assertEqual(vcfg.auto_tts_threads(), 1)
        with mock.patch.object(vcfg, "effective_cpu_count", return_value=16):
            self.assertEqual(vcfg.auto_tts_threads(), 3)

    def test_vieneu_threads_default_auto(self) -> None:
        with mock.patch.object(vcfg, "_sub", return_value={}), \
                mock.patch.object(vcfg, "auto_tts_threads", return_value=2):
            self.assertEqual(vcfg.vieneu_threads(), 2)
            self.assertEqual(vcfg.tts_threads(), 2)

    def test_vieneu_threads_explicit(self) -> None:
        with mock.patch.object(vcfg, "_sub", return_value={"num_threads": 1}):
            self.assertEqual(vcfg.vieneu_threads(), 1)
        with mock.patch.object(vcfg, "_sub",
                               return_value={"vieneu_threads": 4, "num_threads": 1}):
            self.assertEqual(vcfg.vieneu_threads(), 4)

    def test_kokoro_picks_fp32_without_vnni(self) -> None:
        from pathlib import Path
        from unittest.mock import MagicMock

        base = MagicMock()
        int8 = Path("/tmp/model.int8.onnx")
        fp32 = Path("/tmp/model.onnx")
        with mock.patch.object(vcfg, "kokoro_model_dir", return_value=base), \
                mock.patch.object(base, "glob",
                                  return_value=[int8, fp32]), \
                mock.patch.object(vcfg, "tts_precision_prefer", return_value="fp32"):
            # sorted glob order - we control list
            self.assertEqual(vcfg.kokoro_model_file(), fp32)

    def test_kokoro_picks_int8_with_vnni(self) -> None:
        from pathlib import Path
        from unittest.mock import MagicMock

        base = MagicMock()
        int8 = Path("/tmp/model.int8.onnx")
        fp32 = Path("/tmp/model.onnx")
        with mock.patch.object(vcfg, "kokoro_model_dir", return_value=base), \
                mock.patch.object(base, "glob", return_value=[int8, fp32]), \
                mock.patch.object(vcfg, "tts_precision_prefer", return_value="int8"):
            self.assertEqual(vcfg.kokoro_model_file(), int8)

    def test_max_chars_clamped(self) -> None:
        with mock.patch.object(vcfg, "_sub", return_value={}):
            self.assertEqual(vcfg.vieneu_max_chars(), 128)
        with mock.patch.object(vcfg, "_sub", return_value={"vieneu_max_chars": 10}):
            self.assertEqual(vcfg.vieneu_max_chars(), 48)
        with mock.patch.object(vcfg, "_sub", return_value={"vieneu_max_chars": 999}):
            self.assertEqual(vcfg.vieneu_max_chars(), 256)


class WarmupTests(unittest.TestCase):
    def test_warmup_calls_stream_for_vieneu(self) -> None:
        seen: list[str] = []

        def fake_stream(text: str, v: str):
            seen.append(text)
            yield (48000, b"\x00\x00" * 24000)  # 0.5s @ 48k

        with mock.patch.object(vcfg, "tts_voice", return_value="vieneu:Ngọc Trân"), \
                mock.patch.object(vcfg, "vieneu_installed", return_value=True), \
                mock.patch.object(vcfg, "vieneu_model_ready", return_value=True), \
                mock.patch.object(vcfg, "tts_precision_locked", return_value=False), \
                mock.patch.object(vcfg, "vieneu_precision", return_value="fp32"), \
                mock.patch.object(engines, "_vieneu_stream", side_effect=fake_stream), \
                mock.patch.object(engines, "_probe_warm_ttfa", return_value=0.4):
            out = engines.warmup_tts("vieneu:Ngọc Trân")
        self.assertTrue(out["ok"])
        self.assertEqual(out["engine"], "vieneu")
        self.assertTrue(seen)

    def test_int8_slow_ttfa_switches_to_fp32(self) -> None:
        # Chip có VNNI → int8, nhưng warm TTFA 0.9s > 0.56 → chuyển fp32.
        vcfg.set_tts_precision_override("", "")  # clear
        with mock.patch.object(vcfg, "tts_precision_locked", return_value=False), \
                mock.patch.object(vcfg, "vieneu_precision", return_value="int8"), \
                mock.patch.object(vcfg, "ttfa_target_s", return_value=0.56), \
                mock.patch.object(vcfg, "_vieneu_model_present",
                                  side_effect=lambda p: p in ("int8", "fp32")), \
                mock.patch.object(engines, "_reset_vieneu") as reset, \
                mock.patch.object(engines, "_vieneu_stream",
                                  return_value=iter([(48000, b"\x00\x00" * 100)])), \
                mock.patch.object(engines, "_probe_warm_ttfa", return_value=0.45):
            info = engines._maybe_switch_int8_to_fp32("vieneu:X", 0.90)
        self.assertTrue(info["switched"])
        self.assertEqual(info["to"], "fp32")
        self.assertEqual(vcfg.tts_precision_override(), "fp32")
        reset.assert_called_once()
        vcfg.set_tts_precision_override("", "")

    def test_int8_fast_ttfa_keeps_int8(self) -> None:
        vcfg.set_tts_precision_override("", "")
        with mock.patch.object(vcfg, "tts_precision_locked", return_value=False), \
                mock.patch.object(vcfg, "vieneu_precision", return_value="int8"), \
                mock.patch.object(vcfg, "ttfa_target_s", return_value=0.56):
            info = engines._maybe_switch_int8_to_fp32("vieneu:X", 0.50)
        self.assertFalse(info["switched"])
        self.assertIsNone(vcfg.tts_precision_override())

    def test_locked_precision_no_switch(self) -> None:
        vcfg.set_tts_precision_override("", "")
        with mock.patch.object(vcfg, "tts_precision_locked", return_value=True), \
                mock.patch.object(vcfg, "vieneu_precision", return_value="int8"):
            info = engines._maybe_switch_int8_to_fp32("vieneu:X", 1.5)
        self.assertFalse(info["switched"])
        self.assertIsNone(vcfg.tts_precision_override())


class PlayTextOnPipelineTests(unittest.TestCase):
    def test_multi_sentence_plays_first_then_rest(self) -> None:
        from pathlib import Path

        from services import voice as vmod

        calls_speak: list[str] = []
        plays: list[str] = []
        n = {"i": 0}

        def fake_speak(text: str, voice_name: str = "", *, style: str = "") -> bytes:
            calls_speak.append(text)
            return _wav16(200)

        def fake_save(data: bytes, suffix: str = ".wav") -> Path:
            n["i"] += 1
            return Path(f"/tmp/fake{n['i']}{suffix}")

        text = ("Hôm nay trời rất đẹp và nắng vàng rực rỡ. "
                "Chúng ta cùng nhau đi dạo ngoài công viên nhé!")
        with mock.patch.object(vmod, "speak", side_effect=fake_speak), \
                mock.patch.object(vmod, "play_on",
                                  side_effect=lambda spk, url: plays.append(url)), \
                mock.patch.object(vmod, "media_url",
                                  side_effect=lambda p: f"http://x/{p.name}"), \
                mock.patch.object(vmod, "save_media", side_effect=fake_save), \
                mock.patch.object(vmod, "cleanup_media", return_value=0), \
                mock.patch.object(vmod.time, "sleep", return_value=None), \
                mock.patch.object(vcfg, "tts_voice", return_value="vieneu:Ngọc Trân"):
            url = vmod.play_text_on(text, {"id": "s1", "kind": "cast", "name": "loa"})
        self.assertEqual(len(calls_speak), 2)
        self.assertEqual(len(plays), 2)
        self.assertTrue(url.startswith("http://x/"))


if __name__ == "__main__":
    unittest.main()


# ── Số luồng TTS khai được từ docker compose ────────────────────────────────
#
# Con số này tuỳ MÁY (số nhân, có VNNI hay không) chứ không tuỳ người dùng, nên
# chỗ khai đúng của nó là compose của từng máy. Đo 21/08/2026 trên máy chủ 10
# nhân không VNNI: 2 luồng → 3,91 giây/câu, 5 luồng → 3,10, 8 luồng → 4,07 —
# nâng lên có ăn rồi quay đầu, nên phải chỉnh được chứ không ghim cứng.


def test_env_VIENEU_THREADS_de_len_config_json(monkeypatch):
    from services.voice import config as vcfg

    monkeypatch.setenv("VIENEU_THREADS", "5")
    assert vcfg.vieneu_threads() == 5


def test_env_rong_thi_ve_duong_tu_tinh(monkeypatch):
    from services.voice import config as vcfg

    monkeypatch.setenv("VIENEU_THREADS", "")
    assert vcfg.vieneu_threads() == vcfg.auto_tts_threads()


def test_env_hong_thi_bo_qua_chu_khong_no(monkeypatch):
    """Gõ nhầm trong compose thì rơi về mặc định, đừng làm chết cả giọng nói."""
    from services.voice import config as vcfg

    monkeypatch.setenv("VIENEU_THREADS", "nhieu-vao")
    assert vcfg.vieneu_threads() == vcfg.auto_tts_threads()
