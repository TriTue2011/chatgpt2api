"""Lồng tiếng video: lựa chọn giọng, prosody sidecar và thay track gốc."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from io import BytesIO
from pathlib import Path

import pytest


def _wav_tone(hz: float, giay: float = 0.35, rate: int = 24000) -> bytes:
    import numpy as np

    t = np.arange(round(rate * giay), dtype=np.float32) / rate
    pcm = (np.sin(2 * math.pi * hz * t) * 0.2 * 32767).astype("<i2").tobytes()
    out = BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


@pytest.mark.integration
def test_long_tieng_thay_track_goc_va_ghi_prosody(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("máy test không có ffmpeg/ffprobe")

    # Track gốc 440 Hz; TTS giả 660 Hz. Video đầu ra phải chỉ map track TTS.
    src = tmp_path / "phim.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=160x90:d=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src),
    ], check=True)

    from services import video_dub as dub
    from services.voice import engines

    monkeypatch.setattr(engines, "synthesize",
                        lambda _text, _voice="", **_kw: _wav_tone(660))
    srt = ("1\n00:00:00,500 --> 00:00:01,300\nXin chào.\n\n"
           "2\n00:00:01,800 --> 00:00:02,600\nTôi đến đây.\n")

    ket = dub.long_tieng(str(src), srt.encode(), "vi", voice="giong-thu")
    try:
        assert Path(ket.video_path).is_file()
        assert Path(ket.prosody_path).is_file()
        meta = json.loads(Path(ket.prosody_path).read_text("utf-8"))
        assert meta["original_audio"] == "removed"
        assert meta["voice"] == "giong-thu"
        assert len(meta["cues"]) == 2
        cue = meta["cues"][0]
        for key in ("speaker", "rate", "pitch_relative", "energy",
                    "pause_before", "pause_after", "emotion", "emphasis"):
            assert key in cue
        assert cue["speaker"] == "UNKNOWN"
        assert cue["pause_before"] == pytest.approx(0.5, abs=0.02)
        assert cue["pause_after"] == pytest.approx(0.5, abs=0.02)

        probe = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0",
            ket.video_path,
        ], capture_output=True, text=True, check=True)
        assert probe.stdout.strip() == "audio"
    finally:
        Path(ket.video_path).unlink(missing_ok=True)
        Path(ket.prosody_path).unlink(missing_ok=True)


def test_khuyen_nghi_giong_ro_rang_va_chi_chon_giong_da_tai(monkeypatch):
    from services import video_dub as dub
    from services.voice import config as vcfg

    monkeypatch.setattr(vcfg, "voice_catalog", lambda: [
        {"id": "ngochuyennew", "language": "vi", "language_label": "Piper",
         "downloaded": True},
        {"id": "vieneu:Mai Anh", "language": "vi-en", "language_label": "VieNeu",
         "downloaded": True, "phat_am": {"dat": True}},
        {"id": "kokoro:af_sky", "language": "en", "language_label": "Kokoro",
         "downloaded": False},
    ])

    vi = dub.danh_sach_giong("vi")
    assert next(v for v in vi if v["recommended"])["id"] == "vieneu:Mai Anh"
    assert dub.chon_giong("vi", "") == "vieneu:Mai Anh"
    with pytest.raises(dub.LoiLongTieng, match="chưa được tải"):
        dub.chon_giong("en", "kokoro:af_sky")
