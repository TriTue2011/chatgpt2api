"""Silero VAD: chưa có model thì mọi thứ chạy y như cũ; có model thì cắt đúng.

Máy dev không cài `sherpa_onnx` (nó nằm trong image), nên các bài có model dùng
một bộ dò GIẢ đúng theo API thật của sherpa-onnx — xem
`python-api-examples/vad-remove-non-speech-segments.py` của k2-fsa: `VadModelConfig`
có `silero_vad.model/threshold/window_size` và `sample_rate`, còn
`VoiceActivityDetector` có `accept_waveform / empty / front / pop / flush`, mỗi
đoạn trả về có `.start` (chỉ số mẫu) và `.samples`.
"""
from __future__ import annotations

import io
import os
import sys
import types
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

RATE = 16000
CUA = 512


def _wav(mau: np.ndarray) -> bytes:
    ra = io.BytesIO()
    with wave.open(ra, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(mau, -1, 1) * 32767).astype(np.int16).tobytes())
    return ra.getvalue()


def _tieng(giay: float, bien: float = 0.3) -> np.ndarray:
    t = np.arange(int(RATE * giay)) / RATE
    return (bien * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _lang(giay: float) -> np.ndarray:
    return np.zeros(int(RATE * giay), dtype=np.float32)


def _sherpa_gia(doan_giay: list[tuple[float, float]]):
    """Module sherpa_onnx giả trả đúng các đoạn đã định trước."""

    class _Doan:
        def __init__(self, bat: int, dai: int):
            self.start = bat
            self.samples = [0.0] * dai

    class _Vad:
        def __init__(self, config, buffer_size_in_seconds=30):
            self._da_nap = 0
            self._con = [_Doan(int(b * RATE), max(1, int((k - b) * RATE)))
                         for b, k in doan_giay]

        def accept_waveform(self, x):
            self._da_nap += len(x)

        def empty(self):
            return not self._con

        @property
        def front(self):
            return self._con[0]

        def pop(self):
            self._con.pop(0)

        def flush(self):
            pass

    class _Silero:
        model = ""
        threshold = 0.5
        min_silence_duration = 0.1
        min_speech_duration = 0.1
        window_size = CUA

    class _Cfg:
        def __init__(self):
            self.silero_vad = _Silero()
            self.sample_rate = RATE

    mod = types.ModuleType("sherpa_onnx")
    mod.VadModelConfig = _Cfg
    mod.VoiceActivityDetector = _Vad
    return mod


def _bat_vad(monkeypatch, tmp_path, doan_giay):
    """Giả lập: model có trên đĩa + sherpa_onnx nạp được."""
    from services.voice import vad_silero

    model = tmp_path / "silero_vad.onnx"
    model.write_bytes(b"gia")
    monkeypatch.setattr(vad_silero, "duong_model", lambda: model)
    monkeypatch.setattr(vad_silero, "_sherpa", lambda: _sherpa_gia(doan_giay))
    vad_silero._cache.clear()
    return vad_silero


def test_chua_co_model_thi_tra_none(monkeypatch):
    """Không model → None, để người gọi lùi về cách cũ chứ không phải 'im lặng'."""
    from services.voice import vad_silero

    monkeypatch.setattr(vad_silero, "duong_model", lambda: None)
    vad_silero._cache.clear()
    mau = np.concatenate([_lang(1.0), _tieng(1.0)])
    assert vad_silero.doan_co_tieng(mau, RATE) is None
    assert vad_silero.mat_na_khung(mau, RATE) is None
    assert vad_silero.co_san() is False


def test_chua_co_model_thi_khong_cat_gi(monkeypatch):
    from services.voice import vad_silero

    monkeypatch.setattr(vad_silero, "duong_model", lambda: None)
    vad_silero._cache.clear()
    goc = _wav(np.concatenate([_lang(2.0), _tieng(1.0)]))
    assert vad_silero.cat_im_lang_wav(goc) == goc


def test_cat_bo_khoang_lang_dau_cuoi(monkeypatch, tmp_path):
    """3 giây lặng + 1 giây tiếng + 3 giây lặng → chỉ còn quanh đoạn tiếng."""
    vad_silero = _bat_vad(monkeypatch, tmp_path, [(3.0, 4.0)])
    goc = _wav(np.concatenate([_lang(3.0), _tieng(1.0), _lang(3.0)]))
    ra = vad_silero.cat_im_lang_wav(goc)
    assert ra != goc
    with wave.open(io.BytesIO(ra), "rb") as w:
        giay = w.getnframes() / w.getframerate()
        assert w.getframerate() == RATE and w.getnchannels() == 1
    # 1 giây tiếng + 2×0,15 giây đệm hai đầu.
    assert 1.2 <= giay <= 1.4


def test_giu_nguyen_khi_gan_nhu_toan_tieng(monkeypatch, tmp_path):
    """Cắt dưới 15% thì không bõ rủi ro mất âm ở mép — trả nguyên bản."""
    vad_silero = _bat_vad(monkeypatch, tmp_path, [(0.0, 9.5)])
    goc = _wav(np.concatenate([_tieng(9.5), _lang(0.5)]))
    assert vad_silero.cat_im_lang_wav(goc) == goc


def test_vad_khong_thay_tieng_thi_giu_nguyen(monkeypatch, tmp_path):
    """Thà nghe cả tệp còn hơn trả về một tệp bị cắt trắng."""
    vad_silero = _bat_vad(monkeypatch, tmp_path, [])
    goc = _wav(np.concatenate([_lang(1.0), _tieng(1.0)]))
    assert vad_silero.cat_im_lang_wav(goc) == goc


def test_mat_na_khung_dung_vi_tri(monkeypatch, tmp_path):
    vad_silero = _bat_vad(monkeypatch, tmp_path, [(1.0, 2.0)])
    mau = np.concatenate([_lang(1.0), _tieng(1.0), _lang(1.0)])
    noi = vad_silero.mat_na_khung(mau, RATE, 0.1)
    assert noi is not None and len(noi) == 30
    assert not noi[:10].any()          # giây đầu: lặng
    assert noi[10:20].all()            # giây giữa: có tiếng
    assert not noi[21:].any()          # giây cuối: lặng (khung 20 là mép)


def test_video_asr_dung_vad_khi_co_model(monkeypatch, tmp_path):
    """video_asr ưu tiên Silero, và vẫn chạy được khi chưa có model."""
    from services import video_asr

    vad_silero = _bat_vad(monkeypatch, tmp_path, [(1.0, 2.0)])
    mau = np.concatenate([_lang(1.0), _tieng(1.0), _lang(1.0)])
    noi, khung = video_asr._khung_co_tieng(mau, RATE)
    assert khung == int(RATE * 0.1)
    assert noi is not None and noi[10:20].all() and not noi[:10].any()

    # Không model → mặt nạ năng lượng cũ, vẫn thấy đoạn giữa có tiếng.
    monkeypatch.setattr(vad_silero, "duong_model", lambda: None)
    vad_silero._cache.clear()
    noi2, _ = video_asr._khung_co_tieng(mau, RATE)
    assert noi2 is not None and noi2[10:19].any()
