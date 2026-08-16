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

from test._fakes import FakeFfmpeg, FakeTTS, install_tts, install_video_dub_media


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
def test_long_tieng_thay_track_goc_va_ghi_prosody(tmp_path):
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
    srt = ("1\n00:00:00,500 --> 00:00:01,300\nXin chào.\n\n"
           "2\n00:00:01,800 --> 00:00:02,600\nTôi đến đây.\n")

    with install_tts(FakeTTS(wav=_wav_tone(660))):
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

        # Chứng minh track đầu ra là giọng giả 660 Hz, không phải track gốc
        # 440 Hz. Chỉ đếm stream thì chưa chứng minh âm thanh cũ đã bị bỏ.
        pcm = subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.60",
            "-t", "0.40", "-i", ket.video_path, "-vn", "-ac", "1", "-ar",
            "24000", "-f", "s16le", "pipe:1",
        ], capture_output=True, check=True).stdout
        import numpy as np

        mau = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        pho = np.abs(np.fft.rfft(mau * np.hanning(len(mau))))
        tan = np.fft.rfftfreq(len(mau), 1 / 24000)
        mien = (tan >= 300) & (tan <= 900)
        tan_chinh = float(tan[mien][int(np.argmax(pho[mien]))])
        assert tan_chinh == pytest.approx(660, abs=35)
    finally:
        Path(ket.video_path).unlink(missing_ok=True)
        Path(ket.prosody_path).unlink(missing_ok=True)


@pytest.mark.adapter
def test_khuyen_nghi_giong_ro_rang_va_chi_chon_giong_da_tai():
    from services import video_dub as dub

    fake = FakeTTS(catalog=[
        {"id": "ngochuyennew", "language": "vi", "language_label": "Piper",
         "downloaded": True},
        {"id": "vieneu:Mai Anh", "language": "vi-en", "language_label": "VieNeu",
         "downloaded": True, "phat_am": {"dat": True}},
        {"id": "kokoro:af_sky", "language": "en", "language_label": "Kokoro",
         "downloaded": False},
    ])
    with install_tts(fake):
        vi = dub.danh_sach_giong("vi")
        assert next(v for v in vi if v["recommended"])["id"] == "vieneu:Mai Anh"
        assert dub.chon_giong("vi", "") == "vieneu:Mai Anh"
        with pytest.raises(dub.LoiLongTieng, match="chưa được tải"):
            dub.chon_giong("en", "kokoro:af_sky")


@pytest.mark.adapter
def test_tieng_anh_uu_tien_kokoro_ban_ngu_hon_diem_phat_am_viet():
    from services import video_dub as dub

    fake = FakeTTS(catalog=[
        {"id": "vieneu:Mai Anh", "language": "vi-en", "language_label": "VieNeu",
         "downloaded": True, "phat_am": {"dat": True}},
        {"id": "kokoro:af_sky", "language": "en", "language_label": "Kokoro",
         "downloaded": True},
    ])
    with install_tts(fake):
        en = dub.danh_sach_giong("en")
        assert next(v for v in en if v["recommended"])["id"] == "kokoro:af_sky"


@pytest.mark.adapter
def test_cam_xuc_chon_style_khac_nhau_tren_engine_ho_tro():
    from services import video_dub as dub

    fake = FakeTTS(wav=_wav_tone(440))
    with install_tts(fake):
        dub._tong_hop("Bình tĩnh nào.", "vieneu:Mai Anh", "calm")
        dub._tong_hop("Nhanh lên!", "vieneu:Mai Anh", "energetic")
    assert [c["style"] for c in fake.calls] == ["doc_truyen", "tin_tuc"]


@pytest.mark.adapter
def test_ffmpeg_timeout_xoa_pcm_va_mp4_tam():
    from services import video_dub as dub

    fake = FakeFfmpeg(TimeoutError("quá giờ"))
    with install_video_dub_media(fake):
        with pytest.raises(TimeoutError):
            dub._boc_pcm_goc("phim.mp4")
        pcm_tam = Path(fake.calls[-1][-1])
        assert not pcm_tam.exists()

        with pytest.raises(TimeoutError):
            dub._mux("phim.mp4", "track.wav", 10.0)
        mp4_tam = Path(fake.calls[-1][-1])
        assert not mp4_tam.exists()


@pytest.mark.pure
def test_bo_loc_tts_dung_cao_do_va_nang_luong_tuong_doi():
    """Prosody không chỉ ghi JSON: pitch/energy phải đi vào filter âm thanh."""
    from services import video_dub as dub

    loc, tempo = dub._bo_loc_tts(24000, 0.35, 0.5,
                                 pitch_relative=3.0, energy_relative_db=-2.0)
    assert "asetrate=" in loc
    assert "volume=-2.000dB" in loc
    assert tempo == pytest.approx(0.7)
