"""Cache audio TTS, khoảng lặng giữa câu, và cắt câu không phạm vào số.

Ba thứ này đi cùng nhau vì cùng nằm trên đường đọc-theo-câu của
``engines.stream_synthesize``. Ý tưởng lấy từ luuquangvu/wyoming-vietnamese.
"""

from __future__ import annotations

import io
import os
import time
import unittest
import wave
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.voice import config as vcfg  # noqa: E402
from services.voice import engines, tts_cache  # noqa: E402


def _wav(rate: int = 22050, ms: int = 100) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(int(rate * ms / 1000) * 2))
    return buf.getvalue()


class BoundedLruCacheTests(unittest.TestCase):
    def _cache(self, **kw) -> tts_cache.BoundedLruCache:
        args = {"max_entries": 3, "max_bytes": 1000,
                "max_item_bytes": 100, "max_idle_seconds": 0}
        args.update(kw)
        return tts_cache.BoundedLruCache(**args)

    def test_put_then_get(self) -> None:
        c = self._cache()
        self.assertTrue(c.put(b"k", b"x" * 10, size_bytes=10))
        self.assertEqual(c.get(b"k"), b"x" * 10)
        self.assertIsNone(c.get(b"khong-co"))

    def test_item_over_limit_is_refused(self) -> None:
        c = self._cache()
        self.assertFalse(c.put(b"big", b"y" * 200, size_bytes=200))
        self.assertEqual(c.total_bytes, 0)

    def test_evicts_least_recently_used(self) -> None:
        c = self._cache()
        for k in (b"a", b"b", b"c"):
            c.put(k, k * 10, size_bytes=10)
        c.get(b"a")                       # 'a' vừa dùng → 'b' thành cũ nhất
        c.put(b"d", b"d" * 10, size_bytes=10)
        self.assertIsNone(c.get(b"b"))
        self.assertIsNotNone(c.get(b"a"))
        self.assertEqual(len(c), 3)

    def test_evicts_until_under_byte_budget(self) -> None:
        c = self._cache(max_entries=100, max_bytes=50, max_item_bytes=50)
        c.put(b"1", b"x" * 30, size_bytes=30)
        c.put(b"2", b"x" * 30, size_bytes=30)
        self.assertLessEqual(c.total_bytes, 50)

    def test_entry_expires_when_idle(self) -> None:
        c = self._cache(max_idle_seconds=0.05)
        c.put(b"k", b"v", size_bytes=1)
        time.sleep(0.08)
        self.assertIsNone(c.get(b"k"))
        self.assertEqual(c.total_bytes, 0)

    def test_zero_limits_disable_cache(self) -> None:
        c = self._cache(max_entries=0, max_bytes=0, max_item_bytes=0)
        self.assertFalse(c.enabled)
        self.assertFalse(c.put(b"k", b"v", size_bytes=1))


class CacheKeyTests(unittest.TestCase):
    def test_same_input_same_key(self) -> None:
        a = tts_cache.key("wav", "xin chào", "vieneu:A", "tu_nhien")
        b = tts_cache.key("wav", "xin chào", "vieneu:A", "tu_nhien")
        self.assertEqual(a, b)

    def test_every_field_changes_the_key(self) -> None:
        base = tts_cache.key("wav", "xin chào", "vieneu:A", "tu_nhien")
        self.assertNotEqual(base, tts_cache.key("wav", "xin chào!", "vieneu:A", "tu_nhien"))
        self.assertNotEqual(base, tts_cache.key("wav", "xin chào", "vieneu:B", "tu_nhien"))
        self.assertNotEqual(base, tts_cache.key("wav", "xin chào", "vieneu:A", "tin_tuc"))
        self.assertNotEqual(base, tts_cache.key("stream", "xin chào", "vieneu:A", "tu_nhien"))

    def test_engine_config_changes_the_key(self) -> None:
        # Đổi precision là audio khác — khoá phải khác, kẻo phát lại bản cũ.
        with mock.patch.object(vcfg, "vieneu_precision", return_value="int8"):
            a = tts_cache.key("wav", "xin chào", "vieneu:A", "")
        with mock.patch.object(vcfg, "vieneu_precision", return_value="fp32"):
            b = tts_cache.key("wav", "xin chào", "vieneu:A", "")
        self.assertNotEqual(a, b)


class CommaCutTests(unittest.TestCase):
    def test_skips_comma_between_digits(self) -> None:
        self.assertEqual(engines._comma_cut("gia 1,5 trieu dong", 20), -1)

    def test_takes_clause_comma(self) -> None:
        self.assertEqual(engines._comma_cut("mua he nong, mua dong lanh", 20), 11)

    def test_prefers_clause_comma_over_numeric_ones(self) -> None:
        # Dấu phẩy ở 4 và 11 nằm trong số; chỉ dấu ở 13 ngăn cách mệnh đề.
        self.assertEqual(engines._comma_cut("so 1,5 va 2,7, con lai", 30), 13)

    def test_long_sentence_never_split_inside_a_number(self) -> None:
        text = ("Nhiet do ngoai troi hom nay o Ha Noi duoc du bao vao khoang 33,8 do C "
                "va do am tuong doi giu quanh muc 78 phan tram trong suot buoi chieu, "
                "buoi toi troi chuyen mat hon nen ban co the mo cua so cho thoang.")
        parts = engines._split_sentences(text, max_chars=100)
        self.assertGreater(len(parts), 1)
        self.assertFalse(any(p.rstrip().endswith("33") for p in parts), parts)
        # Không được nuốt chữ khi xẻ.
        self.assertEqual("".join(p.replace(" ", "") for p in parts),
                         text.replace(" ", ""))


class SilenceTests(unittest.TestCase):
    def test_jitter_zero_returns_base(self) -> None:
        self.assertEqual(engines._jitter_ms(350, 0), 350)
        self.assertEqual(engines._jitter_ms(0, 25), 0)

    def test_jitter_stays_within_range_and_varies(self) -> None:
        vals = {engines._jitter_ms(400, 25) for _ in range(300)}
        self.assertTrue(all(300 <= v <= 500 for v in vals), (min(vals), max(vals)))
        self.assertGreater(len(vals), 10)

    def test_silence_length_and_content(self) -> None:
        self.assertEqual(len(engines._silence_pcm(500, 48000)), 48000 // 2 * 2)
        self.assertEqual(set(engines._silence_pcm(10, 16000)), {0})
        self.assertEqual(engines._silence_pcm(0, 48000), b"")


class StreamSynthesizeCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        tts_cache.clear()
        self.addCleanup(tts_cache.clear)
        self.calls: list[str] = []

    def _fake_synth(self, text: str, voice: str = "", *, style: str = "") -> bytes:
        self.calls.append(text)
        return _wav()

    def test_inserts_silence_between_sentences(self) -> None:
        text = "Cau mot day du chu. Cau hai cung day du chu."
        with mock.patch.object(engines, "synthesize", self._fake_synth):
            out = list(engines.stream_synthesize(text, "piper:test"))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(out), 3)             # câu + khoảng lặng + câu
        self.assertEqual(set(out[1][1]), {0})     # mẩu giữa là im lặng

    def test_second_read_comes_from_cache(self) -> None:
        text = "Cau mot day du chu. Cau hai cung day du chu."
        with mock.patch.object(engines, "synthesize", self._fake_synth):
            first = list(engines.stream_synthesize(text, "piper:test"))
            self.calls.clear()
            second = list(engines.stream_synthesize(text, "piper:test"))
        self.assertEqual(self.calls, [])
        self.assertEqual(second, first)

    def test_different_voice_is_a_different_entry(self) -> None:
        text = "Cau mot day du chu. Cau hai cung day du chu."
        with mock.patch.object(engines, "synthesize", self._fake_synth):
            list(engines.stream_synthesize(text, "piper:test"))
            self.calls.clear()
            list(engines.stream_synthesize(text, "piper:khac"))
        self.assertEqual(len(self.calls), 2)

    def test_failed_sentence_is_never_cached(self) -> None:
        # Đọc hỏng một câu mà vẫn cache thì lỗi tạm thời bị đóng băng cả ngày.
        text = "Cau mot day du chu. Cau hai cung day du chu."
        state = {"n": 0}

        def flaky(t: str, v: str = "", *, style: str = "") -> bytes:
            state["n"] += 1
            if state["n"] == 1:
                raise engines.VoiceError("loi gia lap")
            return _wav()

        with mock.patch.object(engines, "synthesize", flaky):
            list(engines.stream_synthesize(text, "piper:test"))
            before = state["n"]
            list(engines.stream_synthesize(text, "piper:test"))
        self.assertGreater(state["n"], before)

    def test_cache_disabled_by_config(self) -> None:
        text = "Cau mot day du chu. Cau hai cung day du chu."
        with mock.patch.object(vcfg, "tts_cache_mb", return_value=0), \
                mock.patch.object(engines, "synthesize", self._fake_synth):
            list(engines.stream_synthesize(text, "piper:test"))
            self.calls.clear()
            list(engines.stream_synthesize(text, "piper:test"))
        self.assertEqual(len(self.calls), 2)


class ConfigDefaultsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        with mock.patch.object(vcfg, "_sub", return_value={}):
            self.assertEqual(vcfg.tts_cache_mb(), 64)
            self.assertEqual(vcfg.tts_sentence_silence_ms(), 350)
            self.assertEqual(vcfg.tts_silence_jitter_percent(), 25)

    def test_values_are_clamped(self) -> None:
        with mock.patch.object(vcfg, "_sub", return_value={
                "cache_mb": 9999, "sentence_silence_ms": 99999,
                "silence_jitter_percent": 500}):
            self.assertEqual(vcfg.tts_cache_mb(), 512)
            self.assertEqual(vcfg.tts_sentence_silence_ms(), 3000)
            self.assertEqual(vcfg.tts_silence_jitter_percent(), 100)

    def test_garbage_falls_back_to_default(self) -> None:
        with mock.patch.object(vcfg, "_sub", return_value={
                "cache_mb": "rac", "sentence_silence_ms": "rac",
                "silence_jitter_percent": "rac"}):
            self.assertEqual(vcfg.tts_cache_mb(), 64)
            self.assertEqual(vcfg.tts_sentence_silence_ms(), 350)
            self.assertEqual(vcfg.tts_silence_jitter_percent(), 25)


if __name__ == "__main__":
    unittest.main()
