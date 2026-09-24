from __future__ import annotations

import io
import os
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
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


class SttDecodingMethodTests(unittest.TestCase):
    def tearDown(self) -> None:
        engines._recognizers.clear()

    def test_mac_dinh_vi_dung_modified_beam_search(self) -> None:
        with mock.patch.object(vcfg, "_sub", return_value={}):
            self.assertEqual(vcfg.stt_decoding_method("vi"), "modified_beam_search")
            self.assertEqual(vcfg.stt_decoding_method("en"), "greedy_search")

    def test_config_co_the_quay_lai_greedy(self) -> None:
        with mock.patch.object(
            vcfg, "_sub", return_value={"decoding_method": "greedy_search"}
        ):
            self.assertEqual(vcfg.stt_decoding_method("vi"), "greedy_search")

    def test_recognizer_truyen_phuong_phap_da_cau_hinh(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            model_dir = Path(raw)
            for name in ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"):
                (model_dir / name).write_bytes(b"x")

            seen: dict = {}

            class _OfflineRecognizer:
                @staticmethod
                def from_transducer(**kwargs):
                    seen.update(kwargs)
                    return object()

            fake = types.SimpleNamespace(OfflineRecognizer=_OfflineRecognizer)
            with mock.patch.dict(sys.modules, {"sherpa_onnx": fake}), \
                    mock.patch.object(vcfg, "stt_sense_model_dir", return_value=None), \
                    mock.patch.object(vcfg, "stt_model_dir", return_value=model_dir), \
                    mock.patch.object(vcfg, "stt_threads", return_value=2), \
                    mock.patch.object(
                        vcfg, "stt_decoding_method", return_value="modified_beam_search"
                    ):
                engines._get_recognizer("vi")

        self.assertEqual(seen["decoding_method"], "modified_beam_search")


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
        # Từ 5d5da29 Kokoro tiếng Anh gọi sherpa MỘT lần cho cả đoạn (_phat_cau +
        # _kokoro_cau), không còn qua _kokoro_tts — test cũ vá theo hợp đồng mới.
        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(engines, "_kokoro_cau") as cau, \
                mock.patch.object(engines, "_phat_cau",
                                  side_effect=lambda _t, _r, lay: (lay("hello there"),
                                                                   [(24000, b"\x01\x00" * 8)])[1]):
            out = engines.synthesize("hello there", "kokoro:af_sky")
        self.assertTrue(out.startswith(b"RIFF"))
        cau.assert_called_once_with("hello there", "kokoro:af_sky")


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

    def test_spaced_dash_is_a_clause_hyphenated_word_is_not(self) -> None:
        # "Wi-Fi" dính chữ. "Sài Gòn - Hà Nội" có khoảng trắng nên là hai vế.
        mot = "Mạng Wi-Fi trong nhà hôm nay đang chậm hơn mọi ngày."
        self.assertEqual(engines._split_clauses(mot), [mot])
        hai = engines._split_clauses(
            "Từ Sài Gòn đi ra Hà Nội bằng tàu, chặng này khá dài.")
        # phẩy vẫn cắt; gạch nối trong Wi-Fi thì không.
        gach = engines._split_clauses(
            "Đoạn đường Sài Gòn - Hà Nội mất khoảng một ngày đêm.")
        self.assertEqual(len(gach), 2)
        self.assertTrue(gach[0].rstrip().endswith("-"))
        self.assertGreaterEqual(len(hai), 1)

    def test_newline_is_a_paragraph_not_a_sentence(self) -> None:
        text = ("Đoạn đầu đủ dài để đứng một mình.\n\n"
                "Đoạn sau cũng đủ dài để đứng một mình.")
        kinds = [k for _, k in engines._split_segments(text, clause_ms=0)]
        self.assertEqual(kinds, ["paragraph", "sentence"])

    def test_period_inside_a_number_is_not_a_sentence(self) -> None:
        text = "Giá niêm yết là 1.000 đồng cho mỗi suất ăn trưa hôm nay."
        self.assertEqual(len(engines._split_sentences(text)), 1)

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

    def test_vieneu_and_zerotts_wav_skip_the_silence_split(self) -> None:
        text = ("Hôm nay trời rất đẹp và nắng vàng rực rỡ. "
                "Chúng ta cùng nhau đi dạo ngoài công viên nhé.")
        p1, p2, p3 = self._patch(400, 180)
        for voice in ("vieneu:Phạm Tuyên", "zerotts:maichi"):
            self.calls.clear()
            with p1, p2, p3, mock.patch.object(engines, "_synthesize_one",
                                               side_effect=self._fake_one):
                engines.synthesize(text, voice)
            self.assertEqual(self.calls, [text], voice)

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

    def test_zerotts_streams_whole_text(self) -> None:
        # Không cắt câu rồi synthesize(): khung đầu phải ra trước khi hết câu.
        seen: list[str] = []

        def fake_stream(text: str, voice: str):
            seen.append(text)
            yield (48000, b"\x01\x00" * 80)
            yield (48000, b"\x02\x00" * 80)

        text = ("Hôm nay trời rất đẹp và nắng vàng rực rỡ. "
                "Chúng ta cùng nhau đi dạo ngoài công viên nhé.")
        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(engines, "_zerotts_stream", side_effect=fake_stream), \
                mock.patch.object(engines, "synthesize",
                                  side_effect=AssertionError("khong duoc cho het cau")):
            out = list(engines.stream_synthesize(text, "zerotts:maichi"))
        self.assertEqual(seen, [text])
        self.assertEqual(len(out), 2)
        self.assertTrue(all(r == 48000 for r, _ in out))

    def test_vieneu_uses_frame_stream(self) -> None:
        def fake_stream(text: str, v: str, style: str = ""):
            yield (48000, b"\x00\x00" * 100)
            yield (48000, b"\x01\x00" * 100)

        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(engines, "_vieneu_stream", side_effect=fake_stream):
            out = list(engines.stream_synthesize("Xin chào.", "vieneu:Phạm Tuyên"))
        self.assertEqual(len(out), 2)
        self.assertTrue(all(r == 48000 for r, _ in out))

    def test_vieneu_streams_whole_text_even_when_silence_on(self) -> None:
        # Khoảng lặng cấu hình không được cắt VieNeu: mỗi vế là một prefill mới.
        seen: list[str] = []

        def fake_stream(text: str, v: str, style: str = ""):
            seen.append(text)
            yield (48000, b"\x01\x00" * 100)

        text = ("Hôm nay trời rất đẹp và nắng vàng rực rỡ. "
                "Chúng ta cùng nhau đi dạo ngoài công viên nhé.")
        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(vcfg, "tts_sentence_silence_ms", return_value=300), \
                mock.patch.object(vcfg, "tts_clause_silence_ms", return_value=180), \
                mock.patch.object(vcfg, "tts_paragraph_silence_ms", return_value=600), \
                mock.patch.object(vcfg, "tts_silence_jitter_percent", return_value=0), \
                mock.patch.object(engines, "_vieneu_stream", side_effect=fake_stream):
            out = list(engines.stream_synthesize(text, "vieneu:Phạm Tuyên"))
        self.assertEqual(seen, [text])
        self.assertEqual(len(out), 1)

    def test_vieneu_giu_sau_khung_deu(self) -> None:
        # 1 frame rồi 25 frame làm im 3 giây sau tiếng đầu. Giữ một cỡ suốt câu.
        import numpy as np

        ten = "vieneu._v3_turbo_engine.onnx_runtime_lite"
        mod = types.ModuleType(ten)
        mod._STREAM_LEADIN_FRAMES = 4
        seen: list[int] = []

        class Eng:
            def infer_stream(self, text: str, **kwargs):
                seen.append(mod._STREAM_LEADIN_FRAMES)
                yield np.ones(4, dtype=np.float32)
                seen.append(mod._STREAM_LEADIN_FRAMES)
                yield np.ones(4, dtype=np.float32)

        with mock.patch.dict(sys.modules, {ten: mod}), \
                mock.patch.object(engines, "_get_vieneu", return_value=Eng()), \
                mock.patch.object(engines, "_vieneu_kwargs", return_value={}):
            out = list(engines._vieneu_stream("xin chào", "vieneu:Mai Anh"))
        self.assertEqual(seen, [engines._VIENEU_KHUNG, engines._VIENEU_KHUNG])
        self.assertEqual(engines._VIENEU_KHUNG, 6)
        self.assertEqual(mod._STREAM_LEADIN_FRAMES, 4)
        self.assertEqual(len(out), 2)

    def test_zerotts_giu_sau_khung_deu(self) -> None:
        import numpy as np

        kw: dict = {}

        class TTS:
            sample_rate = 48000

            def synthesize_stream(self, seg: str, voice: str | None = None, **kwargs):
                kw.update(kwargs)
                yield np.ones((1, 16), dtype=np.float32)

        with mock.patch.object(engines, "_get_zerotts", return_value=TTS()), \
                mock.patch.object(engines, "_zerotts_doan", return_value=["xin chào"]):
            out = list(engines._zerotts_stream("xin chào", "zerotts:maichi"))
        self.assertEqual(kw["first_chunk_frames"], engines._ZEROTTS_KHUNG)
        self.assertEqual(kw["max_chunk_frames"], engines._ZEROTTS_KHUNG)
        self.assertEqual(engines._ZEROTTS_KHUNG, 6)
        self.assertEqual(len(out), 1)

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
        # Không có hạn mức CFS: 4 CPU → 2 thread, chừa chỗ cho LLM/PDF.
        with mock.patch.object(vcfg, "_cpu_quota", return_value=None), \
                mock.patch.object(vcfg, "effective_cpu_count", return_value=4):
            self.assertEqual(vcfg.auto_tts_threads(), 2)
        with mock.patch.object(vcfg, "_cpu_quota", return_value=None), \
                mock.patch.object(vcfg, "effective_cpu_count", return_value=2):
            self.assertEqual(vcfg.auto_tts_threads(), 1)
        with mock.patch.object(vcfg, "_cpu_quota", return_value=None), \
                mock.patch.object(vcfg, "effective_cpu_count", return_value=16):
            self.assertEqual(vcfg.auto_tts_threads(), 3)

    def test_auto_threads_equals_docker_cpu_limit(self) -> None:
        with mock.patch.object(vcfg, "_cpu_quota", return_value=2):
            self.assertEqual(vcfg.auto_tts_threads(), 2)

    def test_cpu_max_max_means_no_quota(self) -> None:
        self.assertIsNone(vcfg._so_nhan_tu_cpu_max("max 100000"))
        self.assertEqual(vcfg._so_nhan_tu_cpu_max("200000 100000"), 2)
        self.assertEqual(vcfg._so_nhan_tu_cpu_max("50000 100000"), 1)

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
                mock.patch.object(engines, "_probe_warm_ttfa", return_value=0.4), \
                mock.patch.object(engines, "_warm_zerotts", return_value=None):
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


class ZeroWarmupTests(unittest.TestCase):
    def test_warmup_loads_zerotts_when_model_present(self) -> None:
        with mock.patch.object(vcfg, "tts_voice", return_value="ngochuyennew"), \
                mock.patch.object(vcfg, "vieneu_installed", return_value=False), \
                mock.patch.object(vcfg, "vieneu_model_ready", return_value=False), \
                mock.patch.object(vcfg, "zerotts_model_dir", return_value="/data/zerotts"), \
                mock.patch.object(engines, "_get_zerotts", return_value=object()) as nap:
            out = engines.warmup_tts("zerotts:maichi")
        self.assertTrue(out["ok"])
        self.assertEqual(out["engine"], "zerotts")
        nap.assert_called_once()


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


# ── Đệm đầu thông minh (23/09/2026) ─────────────────────────────────────────


class _DongHo:
    """Đồng hồ giả: nguồn giả gọi `buoc(giay)` để mô phỏng thời gian tạo tiếng."""

    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def buoc(self, giay):
        self.t += giay


def _nguon(dong_ho, rtf, tong_giay, khuc=0.25, rate=48000):
    """Engine giả: mỗi khúc `khuc` giây tiếng mất `khuc*rtf` giây để tạo."""
    da = 0.0
    while da < tong_giay - 1e-9:
        dong_ho.buoc(khuc * rtf)
        da += khuc
        yield rate, b"\x01\x00" * int(rate * khuc)


def _loa(dong_ho_ra):
    """Loa phát ngay từ khúc đầu nhận được; trả (tổng giây phải chờ, số giây lặng đầu)."""
    phat_tu = None
    het = 0.0
    cho = 0.0
    lang = 0.0
    thay_tieng = False
    for luc, rate, pcm in dong_ho_ra:
        dai = len(pcm) / (2 * rate)
        if phat_tu is None:
            phat_tu = het = luc
        if luc > het:
            cho += luc - het
            het = luc
        het += dai
        if not thay_tieng and pcm.strip(b"\x00"):
            thay_tieng = True
        elif not thay_tieng:
            lang += dai
    return cho, lang


def _chay(monkeypatch, rtf, tong_giay, text_len, hoc=None):
    dong_ho = _DongHo()
    monkeypatch.setattr(engines, "_TOC_DO", dict(hoc or {}))
    import time as _time
    monkeypatch.setattr(_time, "monotonic", dong_ho)
    ra = [(dong_ho(), r, p) for r, p in engines._dem_dau(
        _nguon(dong_ho, rtf, tong_giay), "x" * text_len, "vieneu")]
    return ra


def test_dem_dau_engine_cham_doc_lien_mach_khong_ngat(monkeypatch):
    # VieNeu đo thật: RTF 1,61, đoạn ~28s cho ~370 ký tự.
    ra = _chay(monkeypatch, 1.61, 28.0, 370,
               hoc={"vieneu": {"rtf": 1.6, "giay_moi_chu": 28.0 / 370}})
    cho, lang = _loa(ra)
    assert cho < 0.3            # không còn ngắt giữa chừng (trước là 17,9s)
    assert 5.0 < lang < 25.0    # đổi lại: chờ đầu, phát bằng khoảng lặng


def test_dem_dau_engine_nhanh_khong_cho_gi(monkeypatch):
    ra = _chay(monkeypatch, 0.1, 20.0, 260,
               hoc={"vieneu": {"rtf": 0.1, "giay_moi_chu": 20.0 / 260}})
    cho, lang = _loa(ra)
    assert (cho, lang) == (0.0, 0.0)
    assert all(p.strip(b"\x00") for _, _, p in ra)   # không chèn lặng nào


def test_dem_dau_lan_dau_chua_hoc_van_do_duoc_ngay_trong_luot(monkeypatch):
    ra = _chay(monkeypatch, 1.4, 30.0, 400)          # chưa có số học
    cho, _lang = _loa(ra)
    assert cho < 1.0
    hoc = engines._TOC_DO["vieneu"]
    assert abs(hoc["rtf"] - 1.4) < 0.1               # học được cho lượt sau
    assert abs(hoc["giay_moi_chu"] - 30.0 / 400) < 1e-6


def test_dem_dau_nap_model_lau_khong_bi_tinh_la_engine_cham(monkeypatch):
    """Model vừa tự nhả phải nạp lại 5s, rồi đọc theo câu nhanh hơn thời gian
    thực (Kokoro Việt). Trước đây r tính cả lúc nạp nên giữ gần hết đoạn."""
    dong_ho = _DongHo()
    monkeypatch.setattr(engines, "_TOC_DO", {})
    import time as _time
    monkeypatch.setattr(_time, "monotonic", dong_ho)

    def kokoro(rate=24000):
        dong_ho.buoc(5.0)                       # nạp model
        for _ in range(6):                      # sáu câu, mỗi câu 2s tiếng, tạo mất 1,6s
            dong_ho.buoc(1.6)
            yield rate, b"\x01\x00" * (rate * 2)

    ra = [(dong_ho(), r, p) for r, p in engines._dem_dau(kokoro(), "x" * 160, "kokorovi")]
    cho, lang = _loa(ra)
    assert cho == 0.0
    assert lang < 2.0                           # phát sau câu thứ hai, không đợi cả đoạn
    assert abs(engines._TOC_DO["kokorovi"]["rtf"] - 0.8) < 1e-6   # học không dính lúc nạp


def test_cat_lang_hai_dau_giu_bien_ngan():
    rate = 24000
    lang = b"\x00\x00" * (rate // 4)            # 0,25s im lặng model tự sinh
    tieng = (b"\x10\x27" + b"\xf0\xd8") * (rate // 2)   # 1s tiếng ±10000
    ra = engines._cat_lang_hai_dau(lang + tieng + lang, rate)
    thua = len(ra) // 2 - rate
    assert abs(thua - 2 * rate * engines._GIU_BIEN_MS // 1000) <= rate // 100
    assert engines._cat_lang_hai_dau(lang, rate) == lang      # toàn lặng: để nguyên


def test_khoang_nghi_phay_ngan_hon_cham_sau_khi_ghep(monkeypatch):
    """Engine theo câu tự thêm 0,22s lặng mỗi đầu mẩu (đo Kokoro Việt). Nghỉ
    nghe thấy phải là số cấu hình: phẩy 180ms, chấm 400ms — không phải 0,6/0,9s."""
    import numpy as np
    rate = 24000
    monkeypatch.setattr(vcfg, "tts_backend", lambda: "local")
    monkeypatch.setattr(tts_cache, "get", lambda _k: None)
    monkeypatch.setattr(engines, "_silence_plan", lambda: (400, 180, 600, 0))
    dem = b"\x00\x00" * int(rate * 0.22)

    def mot(text, voice="", *, style=""):
        pcm = dem + (b"\x10\x27" + b"\xf0\xd8") * (rate // 2) + dem
        return engines._pcm_to_wav(pcm, rate, 2, 1)

    monkeypatch.setattr(engines, "_synthesize_one", mot)
    pcm = b"".join(p for _r, p in engines._stream_tao(
        "Sáng nay trời nhiều mây, có lúc nắng nhẹ rải rác. Chiều tối có mưa rào.", "piper:x"))
    a = np.abs(np.frombuffer(pcm, np.int16).astype(np.int32))
    im = a < 64
    doan, i = [], 0
    while i < a.size:
        if im[i]:
            j = i
            while j < a.size and im[j]:
                j += 1
            doan.append((j - i) / rate)
            i = j
        else:
            i += 1
    giua = [round(d, 2) for d in doan if 0.1 < d < 1.0]
    assert giua == [0.26, 0.48], giua          # phẩy 180+2×40ms, chấm 400+2×40ms


def test_hong_giua_chung_khong_doc_lai_tu_dau(monkeypatch):
    """ZeroTTS phát 2 khúc rồi hỏng: KHÔNG được rơi xuống Piper đọc lại cả đoạn."""
    monkeypatch.setattr(vcfg, "tts_backend", lambda: "local")
    monkeypatch.setattr(tts_cache, "get", lambda _k: None)

    def hong(_text, _voice):
        yield 48000, b"\x01\x00" * 4800
        yield 48000, b"\x01\x00" * 4800
        raise RuntimeError("onnx hong")

    monkeypatch.setattr(engines, "_zerotts_stream", hong)
    goi_lai = mock.Mock(side_effect=AssertionError("doc lai tu dau"))
    monkeypatch.setattr(engines, "synthesize", goi_lai)
    ra = list(engines._stream_tao("Một câu. Hai câu.", "zerotts:maichi"))
    assert len(ra) == 2
    goi_lai.assert_not_called()


# ── Nhả model TTS không dùng (23/09/2026) ───────────────────────────────────


def _dat_nha(monkeypatch, gan_mac_dinh="manhdung", loa=()):
    monkeypatch.setattr(vcfg, "tts_voice", lambda: gan_mac_dinh)
    from services.voice import speakers
    monkeypatch.setattr(speakers, "list_speakers", lambda: [{"voice": v} for v in loa])
    monkeypatch.setattr(engines, "_GIU_ASSIST", set())
    monkeypatch.setattr(engines, "_vieneu", object())
    monkeypatch.setattr(engines, "_zerotts", object())
    monkeypatch.setattr(engines, "_DUNG_LUC", {"vieneu": 0.0, "zerotts": 0.0})


def test_nha_model_khong_gan_sau_30_phut_giu_model_dang_gan(monkeypatch):
    _dat_nha(monkeypatch, loa=["zerotts:maichi"])
    assert engines.nha_model_nhan_roi(bay_gio=29 * 60) == []          # chưa đủ 30 phút
    assert engines.nha_model_nhan_roi(bay_gio=31 * 60) == ["vieneu"]
    assert engines._vieneu is None
    assert engines._zerotts is not None                                 # loa phòng khách dùng
    assert "vieneu" not in engines._DUNG_LUC


def test_giong_assist_da_goi_thi_giu(monkeypatch):
    _dat_nha(monkeypatch)
    engines.giu_cho_assist("vieneu:Trúc Ly")
    assert engines.nha_model_nhan_roi(bay_gio=31 * 60) == ["zerotts"]
    assert engines._vieneu is not None


def test_model_dang_doc_do_thi_de_luot_sau(monkeypatch):
    _dat_nha(monkeypatch)
    import threading as _th
    khoa = _th.Lock()
    monkeypatch.setattr(engines, "_vieneu_lock", khoa)
    with khoa:                                                          # đang đọc dở
        assert "vieneu" not in engines.nha_model_nhan_roi(bay_gio=31 * 60)
    assert engines._vieneu is not None
    assert "vieneu" in engines._DUNG_LUC                                # còn chờ lượt sau
