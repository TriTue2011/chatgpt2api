"""19 giọng NghiTTS: danh mục, tìm model trên volume, và điểm rẽ trong engine.

Không đụng mạng và không nạp sherpa-onnx thật — phần tải về đã kiểm riêng bằng
tay với máy chủ thật (xem scripts/download_nghitts_voices.py).
"""

from __future__ import annotations

import io
import os
import sys
import types
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.voice import config as vcfg  # noqa: E402
from services.voice import engines, nghitts_voices as nv, tts_cache  # noqa: E402

try:                       # numpy có trong image; máy dev có thể chưa cài
    import numpy  # noqa: F401
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


def _make_voice_files(root: Path, voice_id: str) -> Path:
    d = root / voice_id
    d.mkdir(parents=True, exist_ok=True)
    for name in (nv.MODEL_FILE, nv.CONFIG_FILE, nv.TOKENS_FILE):
        (d / name).write_text("x", encoding="utf-8")
    return d


def _make_espeak(root: Path) -> Path:
    d = root / "espeak-ng-data"
    (d / "lang" / "aav").mkdir(parents=True, exist_ok=True)
    for name in ("phondata", "phontab", "vi_dict"):
        (d / name).write_text("x", encoding="utf-8")
    (d / "lang" / "aav" / "vi").write_text("x", encoding="utf-8")
    return d


class CatalogTests(unittest.TestCase):
    def test_nineteen_voices_with_unique_ids(self) -> None:
        self.assertEqual(len(nv.VOICES), 19)
        self.assertEqual(len({v.id for v in nv.VOICES}), 19)
        self.assertEqual(len({v.name for v in nv.VOICES}), 19)

    def test_default_voice_exists(self) -> None:
        self.assertIn(nv.DEFAULT_ID, nv.BY_ID)

    def test_every_sha256_is_well_formed(self) -> None:
        for v in nv.VOICES:
            self.assertRegex(v.model_sha256, r"^[0-9a-f]{64}$", v.id)
            self.assertRegex(v.config_sha256, r"^[0-9a-f]{64}$", v.id)

    def test_south_voices_use_the_south_config(self) -> None:
        # Hai nhóm khác nhau đúng một chỗ: espeak.voice vi vs vi-vn-x-south.
        north = {v.config_sha256 for v in nv.VOICES if not v.south}
        south = {v.config_sha256 for v in nv.VOICES if v.south}
        self.assertEqual(len(north), 1)
        self.assertEqual(len(south), 1)
        self.assertNotEqual(north, south)
        self.assertEqual({v.language for v in nv.VOICES if v.south}, {nv.LANG_SOUTH})

    def test_remote_names_come_from_display_name(self) -> None:
        v = nv.BY_ID["ngoc-huyen-moi"]
        self.assertEqual(v.model_remote, "Ngọc Huyền (mới).onnx")
        self.assertEqual(v.config_remote, "Ngọc Huyền (mới).onnx.json")

    def test_unknown_id_returns_none(self) -> None:
        self.assertIsNone(nv.get("khong-ton-tai"))
        self.assertIsNone(nv.get(""))

    def test_voice_catalog_lists_all_nghi_voices(self) -> None:
        rows = [r for r in vcfg.voice_catalog()
                if str(r["id"]).startswith(vcfg.NGHI_PREFIX)]
        self.assertEqual(len(rows), 19)
        self.assertIn(f"{vcfg.NGHI_PREFIX}ngoc-huyen-moi", {r["id"] for r in rows})
        south = next(r for r in rows if r["id"] == f"{vcfg.NGHI_PREFIX}thien-tam")
        self.assertEqual(south["language"], "vi-vn-x-south")
        self.assertIn("Nam bộ", south["language_label"])

    def test_catalog_marks_only_downloaded_voices(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _make_voice_files(root, "my-tam")
            with mock.patch.object(vcfg, "_sub", return_value={"nghi_dir": str(root)}):
                rows = {r["id"]: r for r in vcfg.voice_catalog()
                        if str(r["id"]).startswith(vcfg.NGHI_PREFIX)}
        self.assertTrue(rows[f"{vcfg.NGHI_PREFIX}my-tam"]["downloaded"])
        self.assertFalse(rows[f"{vcfg.NGHI_PREFIX}ban-mai"]["downloaded"])


class TokensFromConfigTests(unittest.TestCase):
    def test_builds_tokens_ordered_by_id(self) -> None:
        cfg = {"phoneme_id_map": {"_": [0], "a": [1], "b": [2, 3]}}
        self.assertEqual(nv.tokens_from_config(cfg), ["_", "a", "b", "b"])

    def test_rejects_missing_map(self) -> None:
        for bad in ({}, {"phoneme_id_map": {}}, {"phoneme_id_map": []}):
            with self.assertRaises(ValueError):
                nv.tokens_from_config(bad)

    def test_rejects_duplicate_id(self) -> None:
        with self.assertRaises(ValueError):
            nv.tokens_from_config({"phoneme_id_map": {"a": [0], "b": [0]}})

    def test_rejects_gap_in_ids(self) -> None:
        # Bảng lệch id sẽ làm model đọc ra tiếng vô nghĩa — thà dừng.
        with self.assertRaises(ValueError):
            nv.tokens_from_config({"phoneme_id_map": {"a": [0], "b": [2]}})

    def test_rejects_bad_token_types(self) -> None:
        for bad in ({"a": "0"}, {"a": [True]}, {"a": [-1]}, {"a\nb": [0]}):
            with self.assertRaises(ValueError):
                nv.tokens_from_config({"phoneme_id_map": bad})


class ModelDirTests(unittest.TestCase):
    def test_none_until_all_three_files_exist(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            d = root / "ban-mai"
            d.mkdir()
            with mock.patch.object(vcfg, "_sub", return_value={"nghi_dir": str(root)}):
                (d / nv.MODEL_FILE).write_text("x", encoding="utf-8")
                self.assertIsNone(vcfg.nghi_voice_dir("ban-mai"))
                (d / nv.CONFIG_FILE).write_text("x", encoding="utf-8")
                self.assertIsNone(vcfg.nghi_voice_dir("ban-mai"))
                (d / nv.TOKENS_FILE).write_text("x", encoding="utf-8")
                self.assertEqual(vcfg.nghi_voice_dir("ban-mai"), d)

    def test_unknown_id_never_touches_disk(self) -> None:
        # Mã lạ bị chặn ở danh mục nên "../../etc" không đi ra ngoài được.
        with TemporaryDirectory() as td:
            with mock.patch.object(vcfg, "_sub", return_value={"nghi_dir": td}):
                self.assertIsNone(vcfg.nghi_voice_dir("../../etc"))
                self.assertIsNone(vcfg.nghi_voice_dir("khong-ton-tai"))

    def test_downloaded_ids_lists_only_complete_voices(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _make_voice_files(root, "my-tam")
            (root / "ban-mai").mkdir()
            with mock.patch.object(vcfg, "_sub", return_value={"nghi_dir": str(root)}):
                self.assertEqual(vcfg.nghi_downloaded_ids(), ["my-tam"])


class EspeakDataTests(unittest.TestCase):
    def test_found_next_to_models(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            want = _make_espeak(root)
            with mock.patch.object(vcfg, "_sub", return_value={"nghi_dir": str(root)}):
                self.assertEqual(vcfg.nghi_espeak_data_dir(), want)

    def test_incomplete_directory_is_rejected(self) -> None:
        # Thiếu vi_dict thì đọc tiếng Việt sẽ hỏng — coi như không có.
        with TemporaryDirectory() as td:
            root = Path(td)
            d = _make_espeak(root)
            (d / "vi_dict").unlink()
            with mock.patch.object(vcfg, "_sub", return_value={"nghi_dir": str(root)}), \
                    mock.patch.object(vcfg, "KOKORO_DIR", root / "khong-co"):
                self.assertIsNone(vcfg.nghi_espeak_data_dir())

    def test_forced_path_from_config(self) -> None:
        with TemporaryDirectory() as td:
            want = _make_espeak(Path(td))
            with mock.patch.object(vcfg, "_sub",
                                   return_value={"nghi_espeak_dir": str(want)}):
                self.assertEqual(vcfg.nghi_espeak_data_dir(), want)

    def test_ready_needs_both_voice_and_espeak(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            _make_voice_files(root, "my-tam")
            with mock.patch.object(vcfg, "_sub", return_value={"nghi_dir": str(root)}), \
                    mock.patch.object(vcfg, "nghi_espeak_data_dir", return_value=None):
                self.assertFalse(vcfg.nghi_ready())
            with mock.patch.object(vcfg, "_sub", return_value={"nghi_dir": str(root)}), \
                    mock.patch.object(vcfg, "nghi_espeak_data_dir", return_value=root):
                self.assertTrue(vcfg.nghi_ready())


class MaxLoadedConfigTests(unittest.TestCase):
    def test_default_and_clamp(self) -> None:
        with mock.patch.object(vcfg, "_sub", return_value={}):
            self.assertEqual(vcfg.nghi_max_loaded(), 2)
        with mock.patch.object(vcfg, "_sub", return_value={"nghi_max_loaded": 0}):
            self.assertEqual(vcfg.nghi_max_loaded(), 1)
        with mock.patch.object(vcfg, "_sub", return_value={"nghi_max_loaded": 999}):
            self.assertEqual(vcfg.nghi_max_loaded(), 19)
        with mock.patch.object(vcfg, "_sub", return_value={"nghi_max_loaded": "rac"}):
            self.assertEqual(vcfg.nghi_max_loaded(), 2)


class _FakeAudio:
    def __init__(self, n: int = 2205) -> None:
        self.samples = [0.0] * n
        self.sample_rate = nv.SAMPLE_RATE


class _FakeTts:
    def __init__(self, *a, **k) -> None:
        self.calls: list[tuple[str, int]] = []

    def generate(self, text, sid=0, speed=1.0):
        self.calls.append((text, sid))
        return _FakeAudio()


def _fake_sherpa() -> types.ModuleType:
    """Module sherpa_onnx giả — chỉ đủ cho _get_nghi dựng config và nạp engine."""
    m = types.ModuleType("sherpa_onnx")
    m.OfflineTtsVitsModelConfig = lambda **k: k
    m.OfflineTtsModelConfig = lambda **k: k
    m.OfflineTtsConfig = lambda **k: k
    m.OfflineTts = _FakeTts
    return m


class EngineDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        engines._nghi.clear()
        tts_cache.clear()
        self.addCleanup(engines._nghi.clear)
        self.addCleanup(tts_cache.clear)

    def test_voice_id_parsing(self) -> None:
        self.assertEqual(engines._nghi_voice_id("nghi:ban-mai"), "ban-mai")
        self.assertEqual(engines._nghi_voice_id("nghi: ban-mai "), "ban-mai")
        self.assertEqual(engines._nghi_voice_id("kokoro:af"), "")
        self.assertEqual(engines._nghi_voice_id("ngochuyennew"), "")

    def test_unknown_voice_reports_catalog_error(self) -> None:
        with self.assertRaises(engines.VoiceError) as cm:
            engines._get_nghi("khong-ton-tai")
        self.assertIn("danh mục", str(cm.exception))

    def test_missing_model_points_at_the_download_command(self) -> None:
        with mock.patch.object(vcfg, "nghi_voice_dir", return_value=None):
            with self.assertRaises(engines.VoiceError) as cm:
                engines._get_nghi("ban-mai")
        self.assertIn("download_nghitts_voices.py ban-mai", str(cm.exception))

    def test_missing_espeak_is_reported_separately(self) -> None:
        with mock.patch.object(vcfg, "nghi_voice_dir", return_value=Path("/tmp/x")), \
                mock.patch.object(vcfg, "nghi_espeak_data_dir", return_value=None):
            with self.assertRaises(engines.VoiceError) as cm:
                engines._get_nghi("ban-mai")
        self.assertIn("espeak-ng-data", str(cm.exception))

    def _loaded_engine_ctx(self, max_loaded: int = 2):
        return (
            mock.patch.dict(sys.modules, {"sherpa_onnx": _fake_sherpa()}),
            mock.patch.object(vcfg, "nghi_voice_dir", side_effect=lambda vid: Path("/m") / vid),
            mock.patch.object(vcfg, "nghi_espeak_data_dir", return_value=Path("/e")),
            mock.patch.object(vcfg, "nghi_max_loaded", return_value=max_loaded),
        )

    def test_engine_is_loaded_once_per_voice(self) -> None:
        a, b, c, d = self._loaded_engine_ctx()
        with a, b, c, d:
            first = engines._get_nghi("ban-mai")
            self.assertIs(engines._get_nghi("ban-mai"), first)

    def test_drops_least_recently_used_engine_over_the_limit(self) -> None:
        # 19 model × ~64 MB không nạp hết được; giữ vài giọng dùng gần đây.
        a, b, c, d = self._loaded_engine_ctx(max_loaded=2)
        with a, b, c, d:
            engines._get_nghi("ban-mai")
            engines._get_nghi("my-tam")
            engines._get_nghi("ban-mai")        # ban-mai vừa dùng → my-tam cũ nhất
            engines._get_nghi("ngoc-ngan")
            self.assertEqual(set(engines._nghi), {"ban-mai", "ngoc-ngan"})

    @unittest.skipUnless(_HAS_NUMPY, "cần numpy để đổi float → PCM16")
    def test_synthesize_routes_nghi_prefix_and_returns_wav(self) -> None:
        a, b, c, d = self._loaded_engine_ctx()
        with a, b, c, d, mock.patch.object(vcfg, "tts_backend", return_value="local"):
            wav = engines.synthesize("Xin chào.", "nghi:ban-mai")
        with wave.open(io.BytesIO(wav), "rb") as w:
            self.assertEqual(w.getframerate(), nv.SAMPLE_RATE)
            self.assertEqual(w.getsampwidth(), 2)
            self.assertEqual(w.getnchannels(), 1)

    def test_empty_audio_raises_instead_of_silent_wav(self) -> None:
        class _Silent(_FakeTts):
            def generate(self, text, sid=0, speed=1.0):
                return _FakeAudio(0)

        fake = _fake_sherpa()
        fake.OfflineTts = _Silent
        with mock.patch.dict(sys.modules, {"sherpa_onnx": fake}), \
                mock.patch.object(vcfg, "nghi_voice_dir", return_value=Path("/m")), \
                mock.patch.object(vcfg, "nghi_espeak_data_dir", return_value=Path("/e")):
            with self.assertRaises(engines.VoiceError):
                engines._nghi_tts("Xin chào.", "nghi:ban-mai")

    def test_failure_falls_back_to_piper_like_other_engines(self) -> None:
        called: list[str] = []

        def fake_piper(text: str, voice: str = "") -> bytes:
            called.append(voice)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\x00\x00" * 100)
            return buf.getvalue()

        with mock.patch.object(vcfg, "tts_backend", return_value="local"), \
                mock.patch.object(engines, "_nghi_tts", side_effect=RuntimeError("hong")), \
                mock.patch.object(engines, "_piper_local", side_effect=fake_piper):
            engines.synthesize("Xin chào.", "nghi:ban-mai")
        self.assertEqual(called, [""])   # rơi về giọng Piper mặc định

    def test_prefixed_voice_never_resolves_to_a_piper_file(self) -> None:
        p = vcfg.voice_model_path("nghi:ban-mai")
        self.assertTrue(p is None or p.stem == vcfg._DEFAULT_VOICE)


class StatusTests(unittest.TestCase):
    def test_status_reports_nghitts(self) -> None:
        st = vcfg.status()
        self.assertIn("nghitts", st)
        self.assertEqual(st["nghitts"]["voices"], 19)
        self.assertIn("downloaded", st["nghitts"])


if __name__ == "__main__":
    unittest.main()
