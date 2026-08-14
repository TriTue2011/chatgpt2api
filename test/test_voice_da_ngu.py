"""Giọng đọc Nhật/Hàn (Supertonic) — ghim số bước đã ĐO ĐƯỢC là đủ chất lượng.

Vì sao ghim bằng test: `num_steps` trông như một cái núm tốc độ vô hại, rất dễ
bị hạ xuống cho nhanh. Đo thật (`scripts/kiem_phat_am.py ko --buoc 4,8,16
--lap 3`) thì 4 bước LÀM RỤNG phụ âm tiếng Hàn — mất /s/ trong 음식 — còn 8 bước
đọc đủ 16/16 âm. Hạ lại về 4 thì tai nghe ra ngay mà không test nào báo, nên
mới cần ca này.

Không nạp sherpa-onnx thật: thay bằng module giả, chỉ ghi lại cấu hình mà engine
truyền xuống.
"""

from __future__ import annotations

import os
import sys
import types
import unittest
import wave
from io import BytesIO
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.voice import engines  # noqa: E402

try:
    import numpy  # noqa: F401
    _CO_NUMPY = True
except ImportError:
    _CO_NUMPY = False


class _CauHinhGia:
    """Bản giả của sherpa_onnx.GenerationConfig — chỉ giữ thuộc tính."""

    def __init__(self) -> None:
        self.sid = -1
        self.num_steps = 0
        self.speed = 0.0
        self.extra: dict[str, str] = {}


class _AmThanhGia:
    def __init__(self) -> None:
        self.samples = [0.0, 0.5, -0.5, 0.0]
        self.sample_rate = 24000


class _TtsGia:
    def __init__(self) -> None:
        self.da_nhan: list[_CauHinhGia] = []

    def generate(self, text, gc):        # noqa: D401 - khớp chữ ký thật
        self.da_nhan.append(gc)
        return _AmThanhGia()


@unittest.skipUnless(_CO_NUMPY, "cần numpy để đóng gói PCM")
class SoBuocSupertonic(unittest.TestCase):
    def _goi(self, lang: str) -> _CauHinhGia:
        gia = _TtsGia()
        mod = types.ModuleType("sherpa_onnx")
        mod.GenerationConfig = _CauHinhGia
        with mock.patch.dict(sys.modules, {"sherpa_onnx": mod}), \
                mock.patch.object(engines, "_get_supertonic", lambda: gia):
            wav = engines.synthesize_da_ngu("안녕하세요", lang)
        self.assertTrue(wav.startswith(b"RIFF"), "phải trả về WAV")
        with wave.open(BytesIO(wav)) as w:      # đọc được nghĩa là WAV hợp lệ
            self.assertEqual(w.getnchannels(), 1)
        self.assertEqual(len(gia.da_nhan), 1)
        return gia.da_nhan[0]

    def test_tam_buoc_khong_phai_bon(self):
        for lang in ("ko", "ja"):
            with self.subTest(lang=lang):
                self.assertEqual(
                    self._goi(lang).num_steps, 8,
                    "4 bước làm rụng phụ âm tiếng Hàn — xem docstring")

    def test_khai_dung_tieng_cho_moi_luot(self):
        # Supertonic không có nhúng ngôn ngữ trong model (tts.json: n_langs 0)
        # nên tiếng phải khai theo từng lượt, không suy ra được từ chữ.
        for lang in ("ko", "ja"):
            with self.subTest(lang=lang):
                self.assertEqual(self._goi(lang).extra.get("lang"), lang)


if __name__ == "__main__":
    unittest.main()
