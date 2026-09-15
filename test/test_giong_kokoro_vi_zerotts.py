"""Hai họ giọng giữ thanh điệu: Kokoro tiếng Việt + vig2p ("kokorovi:") và ZeroTTS ("zerotts:").

Đo 15/09/2026 trên máy chủ (vòng đọc → STT nghe lại, 18 câu thường): sai thanh
Kokoro Việt 0,04 %, ZeroTTS 0 %, so với VieNeu 0,65 %, Piper 0,73 %, NghiTTS
0,80 % — mốc giọng người thật 0,14 %. Chi tiết trong services/voice/kokoro_vi.py.

Môi trường test KHÔNG có vig2p / sea-g2p / onnxruntime / zerotts (chỉ có trong
image), nên các gói đó được giả lập; phần chạy model thật được kiểm trên máy chủ.
"""

from __future__ import annotations

import io
import os
import pickle
import sys
import tempfile
import types
import unittest
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.voice import config as vcfg  # noqa: E402
from services.voice import engines as eng  # noqa: E402
from services.voice import kokoro_vi as kv  # noqa: E402


# ── Giả lập vig2p + sea-g2p ────────────────────────────────────────────────

def _vig2p_gia():
    """vig2p giả: fix_phonemes gắn «~» để thấy đã đi qua; phonemize_text đánh
    dấu «TUNG_TU» để thấy đường lùi."""
    goc = types.ModuleType("vig2p")
    core = types.ModuleType("vig2p.core")
    core.fix_phonemes = lambda p, source_text=None: (p + "~") if source_text else p
    goc.phonemize_text = lambda t: "TUNG_TU(" + t + ")"
    goc.core = core
    return {"vig2p": goc, "vig2p.core": core}


class _PipelineGia:
    """sea-g2p giả: chuẩn hoá «8h» → «tám giờ»; g2p theo NGỮ CẢNH — «bay» đứng
    một mình đọc kiểu Anh, có «máy» đứng trước thì đọc tiếng Việt."""

    class normalizer:
        @staticmethod
        def normalize(t):
            return t.replace("8h", "tám giờ")

    class g2p:
        @staticmethod
        def convert(doan):
            tu = doan.split()
            ra = []
            for i, w in enumerate(tu):
                if w == "bay":
                    ra.append("baj" if i and tu[i - 1] == "máy" else "beɪ")
                elif w == "gộp":
                    ra.append("gop hai")        # cố tình lệch số từ
                else:
                    ra.append(w.upper())
            return " ".join(ra)


class PhienAmTheoMenhDe(unittest.TestCase):
    def _pa(self, text):
        with patch.dict(sys.modules, _vig2p_gia()):
            return kv.phien_am(text, pipeline=_PipelineGia())

    def test_giu_ngu_canh_nen_may_bay_doc_tieng_viet(self):
        """Đo thật: vig2p tách từng từ nên «bay» → `beɪ`; cả mệnh đề thì → `baj`."""
        self.assertEqual(self._pa("đi máy bay"), "ĐI~ MÁY~ baj~")

    def test_chuan_hoa_truoc_khi_tach_menh_de(self):
        self.assertEqual(self._pa("lúc 8h, về"), "LÚC~ TÁM~ GIỜ~, VỀ~")

    def test_lech_so_tu_thi_lui_ve_duong_vig2p(self):
        self.assertEqual(self._pa("gộp lại. xong"), "TUNG_TU(gộp lại). XONG~")

    def test_dau_cau_dinh_lien_chu_truoc(self):
        self.assertEqual(self._pa("xong !"), "XONG~!")


# ── Voicepack .pt không cần torch ──────────────────────────────────────────

def _pt_gia(mang: np.ndarray) -> bytes:
    """Dựng file đúng định dạng torch.save cho MỘT tensor float32, không cần torch.

    Đã đối chiếu trên máy chủ: đọc 14 voicepack thật bằng `doc_voicepack_pt`
    ra mảng giống hệt `torch.load`.
    """
    torch_mod = types.ModuleType("torch")
    utils_mod = types.ModuleType("torch._utils")

    class FloatStorage:
        pass

    def _rebuild_tensor_v2(*a):
        raise AssertionError("không gọi lúc ghi")

    FloatStorage.__module__, FloatStorage.__qualname__ = "torch", "FloatStorage"
    _rebuild_tensor_v2.__module__, _rebuild_tensor_v2.__qualname__ = "torch._utils", "_rebuild_tensor_v2"
    torch_mod.FloatStorage = FloatStorage
    utils_mod._rebuild_tensor_v2 = _rebuild_tensor_v2

    class _Tensor:
        def __reduce__(self):
            import collections
            return (_rebuild_tensor_v2, (_Storage(), 0, tuple(mang.shape),
                                         (256, 256, 1), False, collections.OrderedDict()))

    class _Storage:
        pass

    class _P(pickle.Pickler):
        def persistent_id(self, obj):
            if isinstance(obj, _Storage):
                return ("storage", FloatStorage, "0", "cpu", int(mang.size))
            return None

    buf = io.BytesIO()
    with patch.dict(sys.modules, {"torch": torch_mod, "torch._utils": utils_mod}):
        _P(buf, protocol=2).dump(_Tensor())
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("gia/data.pkl", buf.getvalue())
        zf.writestr("gia/data/0", mang.astype("<f4").tobytes())
    return z.getvalue()


class DocVoicepack(unittest.TestCase):
    def test_doc_dung_mang(self):
        mang = np.arange(510 * 256, dtype=np.float32).reshape(510, 1, 256) / 7
        self.assertTrue(np.array_equal(kv.doc_voicepack_pt(_pt_gia(mang)), mang))

    def test_tu_choi_pickle_goi_ham_la(self):
        """File tải từ mạng không được gọi hàm tuỳ ý qua pickle."""
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("x/data.pkl", pickle.dumps(os.getcwd, protocol=2))
        with self.assertRaises(pickle.UnpicklingError):
            kv.doc_voicepack_pt(z.getvalue())

    def test_chon_style_theo_do_dai_am_vi(self):
        mang = np.arange(5, dtype=np.float32).reshape(5, 1, 1)
        self.assertEqual(float(kv.chon_style(mang, 3)[0, 0]), 2.0)
        self.assertEqual(float(kv.chon_style(mang, 99)[0, 0]), 4.0)


# ── Danh mục + cờ đã tải ────────────────────────────────────────────────────

class DanhMucGiong(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._va = [patch.object(vcfg, "KOKORO_VI_DIR", self.tmp / "kokoro-vi"),
                    patch.object(vcfg, "ZEROTTS_DIR", self.tmp / "zerotts")]
        for v in self._va:
            v.start()

    def tearDown(self):
        for v in self._va:
            v.stop()

    def _giong(self, tien_to):
        return {v["id"]: v for v in vcfg.voice_catalog() if v["id"].startswith(tien_to)}

    def test_chua_tai_van_hien_du_giong(self):
        self.assertEqual(len(self._giong(vcfg.KOKORO_VI_PREFIX)), 14)
        self.assertEqual(len(self._giong(vcfg.ZEROTTS_PREFIX)), 8)
        self.assertFalse(any(v["downloaded"] for v in self._giong("kokorovi:").values()))
        self.assertTrue(all(v["language"] == "vi" for v in self._giong("zerotts:").values()),
                        "cổng Wyoming và lồng tiếng chọn giọng theo trường language")

    def test_kokoro_viet_da_tai_xet_tung_giong(self):
        d = self.tmp / "kokoro-vi"
        (d / "voices").mkdir(parents=True)
        (d / kv.MODEL_FILE).write_bytes(b"x")
        (d / kv.CONFIG_FILE).write_text("{}")
        np.save(d / "voices" / "mai_linh.npy", np.zeros((1, 1, 256), dtype=np.float32))
        self.assertEqual(vcfg.kokoro_vi_downloaded_ids(), ["mai_linh"])
        self.assertTrue(self._giong("kokorovi:")["kokorovi:mai_linh"]["downloaded"])
        self.assertFalse(self._giong("kokorovi:")["kokorovi:hung_thinh"]["downloaded"])

    def test_zerotts_thieu_mot_file_bat_buoc_la_chua_tai(self):
        d = self.tmp / "zerotts"
        for ten in ("config.json", "tokenizer.json", "null_voice_emb.npy",
                    "onnx/text_encoder.onnx", "onnx/prefix_step.onnx", "voices/index.json"):
            (d / ten).parent.mkdir(parents=True, exist_ok=True)
            (d / ten).write_bytes(b"x")
        self.assertIsNone(vcfg.zerotts_model_dir())
        (d / "onnx/local_frame_decode.onnx").write_bytes(b"x")
        self.assertEqual(vcfg.zerotts_model_dir(), d)

    def test_giong_moi_khong_bi_hieu_la_file_piper(self):
        self.assertNotEqual(vcfg.voice_model_path("kokorovi:hung_thinh"),
                            vcfg.PIPER_DIR / "kokorovi:hung_thinh.onnx")


# ── Rẽ nhánh engine ─────────────────────────────────────────────────────────

def _wav(rate: int, so_mau: int = 10) -> bytes:
    return eng._pcm_to_wav(b"\x00\x00" * so_mau, rate, 2, 1)


class RenhanhEngine(unittest.TestCase):
    def setUp(self):
        self._va = [patch.object(eng.tts_cache, "get", return_value=None),
                    patch.object(eng.tts_cache, "put", return_value=False),
                    patch.object(vcfg, "tts_backend", return_value="local")]
        for v in self._va:
            v.start()

    def tearDown(self):
        for v in self._va:
            v.stop()

    def test_moi_tien_to_toi_dung_engine(self):
        with patch.object(eng, "_kokoro_vi_tts", return_value=_wav(24000)) as k, \
             patch.object(eng, "_zerotts_tts", return_value=_wav(48000)) as z:
            eng._synthesize_one("xin chào", "kokorovi:mai_linh")
            eng._synthesize_one("xin chào", "zerotts:maichi")
        k.assert_called_once_with("xin chào", "kokorovi:mai_linh")
        z.assert_called_once_with("xin chào", "zerotts:maichi")

    def test_engine_hong_thi_roi_ve_piper_khong_cam(self):
        with patch.object(eng, "_zerotts_tts", side_effect=eng.VoiceError("chưa tải")), \
             patch.object(eng, "_piper_local", return_value=_wav(22050)) as p:
            self.assertEqual(eng._synthesize_one("xin chào", "zerotts:maichi"), _wav(22050))
        p.assert_called_once_with("xin chào", "")

    def test_kokoro_viet_cat_cau_dai_va_noi_lai(self):
        class _Sess:
            def __init__(self):
                self.goi = []

            def run(self, _out, feeds):
                self.goi.append(feeds["input_ids"].shape[1])
                return [np.full(2400, 0.1, dtype=np.float32), None]

        sess = _Sess()
        vocab = {c: i + 1 for i, c in enumerate("abcdefghijklmnopqrstuvwxyz ")}
        voicepack = np.zeros((510, 1, 256), dtype=np.float32)
        cau = "Câu thứ nhất khá dài. " * 12
        with patch.object(eng, "_get_kokoro_vi", return_value=(sess, vocab, 510, voicepack)), \
             patch.object(kv, "phien_am", side_effect=lambda s: "abc def"):
            wav = eng._kokoro_vi_tts(cau, "kokorovi:hung_thinh")
        self.assertGreater(len(sess.goi), 1, "câu dài phải được cắt thành nhiều lượt")
        with wave.open(io.BytesIO(wav)) as w:
            self.assertEqual(w.getframerate(), 24000)
            self.assertEqual(w.getnframes(), 2400 * len(sess.goi))

    def test_kokoro_viet_ha_bien_do_thay_vi_cat_dinh(self):
        class _Sess:
            def run(self, _out, feeds):
                return [np.array([0.0, 1.16, -0.58], dtype=np.float32), None]

        with patch.object(eng, "_get_kokoro_vi",
                          return_value=(_Sess(), {"a": 1}, 510, np.zeros((5, 1, 256), np.float32))), \
             patch.object(kv, "phien_am", return_value="a"):
            wav = eng._kokoro_vi_tts("a", "kokorovi:hung_thinh")
        with wave.open(io.BytesIO(wav)) as w:
            mau = np.frombuffer(w.readframes(3), dtype="<i2")
        self.assertLess(int(mau[1]), 32767, "đỉnh bị cắt thay vì hạ biên độ")
        self.assertAlmostEqual(int(mau[2]) / int(mau[1]), -0.5, places=2)

    def test_chua_tai_bao_dung_lenh_can_chay(self):
        with patch.object(vcfg, "kokoro_vi_dir", return_value=None):
            with self.assertRaisesRegex(eng.VoiceError, "download_kokoro_vi.py mai_linh"):
                eng._get_kokoro_vi("mai_linh")
        with patch.object(vcfg, "zerotts_model_dir", return_value=None):
            with self.assertRaisesRegex(eng.VoiceError, "download_zerotts.py"):
                eng._get_zerotts()


if __name__ == "__main__":
    unittest.main()
