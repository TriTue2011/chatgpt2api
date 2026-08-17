"""Lồng tiếng video: bỏ lời gốc, giữ nền, thêm TTS và prosody sidecar."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest

from test._fakes import (FakeAudioSeparator, FakeFfmpeg, FakeTTS,
                         install_audio_separator, install_tts,
                         install_video_dub_media)


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
def test_long_tieng_bo_loi_goc_nhung_giu_nhac_hieu_ung_va_ghi_prosody(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("máy test không có ffmpeg/ffprobe")

    # Track gốc trộn nền 330 Hz + lời 440 Hz. Separator giả trả riêng nền
    # 330 Hz; TTS là 660 Hz. Đầu ra phải có 330 + 660 nhưng không có 440.
    src = tmp_path / "phim.mp4"
    background = tmp_path / "nen.wav"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=3",
        "-c:a", "pcm_s16le", str(background),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=160x90:d=3",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-filter_complex", "[1:a][2:a]amix=inputs=2:normalize=0[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac",
        "-shortest", str(src),
    ], check=True)

    from services import video_dub as dub
    srt = ("1\n00:00:00,500 --> 00:00:01,300\nXin chào.\n\n"
           "2\n00:00:01,800 --> 00:00:02,600\nTôi đến đây.\n")

    separator = FakeAudioSeparator(str(background))
    with install_audio_separator(separator), install_tts(FakeTTS(wav=_wav_tone(660))):
        ket = dub.long_tieng(str(src), srt.encode(), "vi", voice="giong-thu")
    try:
        assert Path(ket.video_path).is_file()
        assert Path(ket.prosody_path).is_file()
        meta = json.loads(Path(ket.prosody_path).read_text("utf-8"))
        assert meta["original_dialogue"] == "removed_by_source_separation_best_effort"
        assert meta["background_audio"] == "preserved_by_source_separation_best_effort"
        assert meta["separation_quality"] == "model_estimate_not_lossless"
        assert meta["separator_model"] == "fake-separator"
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

        # Chứng minh nền 330 Hz còn, TTS 660 Hz có mặt, lời gốc 440 Hz mất.
        pcm = subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.60",
            "-t", "0.40", "-i", ket.video_path, "-vn", "-ac", "1", "-ar",
            "24000", "-f", "s16le", "pipe:1",
        ], capture_output=True, check=True).stdout
        import numpy as np

        mau = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        pho = np.abs(np.fft.rfft(mau * np.hanning(len(mau))))
        tan = np.fft.rfftfreq(len(mau), 1 / 24000)
        def nang_luong(hz: float) -> float:
            mien = (tan >= hz - 18) & (tan <= hz + 18)
            return float(pho[mien].max())

        nen = nang_luong(330)
        loi_goc = nang_luong(440)
        tts = nang_luong(660)
        assert nen > loi_goc * 5
        assert tts > loi_goc * 5
        assert separator.calls == [str(src)]
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
            dub._mux("phim.mp4", "nen.wav", "track.wav", 10.0)
        mp4_tam = Path(fake.calls[-1][-1])
        assert not mp4_tam.exists()


@pytest.mark.adapter
def test_mux_bat_buoc_mix_nen_da_tach_loi_voi_tts():
    """Không được map audio gốc hay chỉ map TTS rồi làm mất nhạc/hiệu ứng."""
    import subprocess

    from services import video_dub as dub

    fake = FakeFfmpeg(result=subprocess.CompletedProcess([], 1, b"", b"loi"))
    with install_video_dub_media(fake):
        with pytest.raises(dub.LoiLongTieng):
            dub._mux("phim.mp4", "nen.wav", "tts.wav", 10.0)
    # Lệnh đầu là lượt ĐO độ to (không map gì cả); lệnh ghép là lệnh có -map.
    cmd = next(c for c in fake.calls if "-map" in c)
    assert cmd[cmd.index("-filter_complex") + 1].startswith("[1:a][2:a]amix=")
    assert cmd[cmd.index("-map") + 1] == "0:v:0"
    assert "[dub]" in cmd


@pytest.mark.pure
def test_bu_am_dua_ve_muc_to_thong_dung_va_chan_hai_dau():
    """Đường ống không có bước chuẩn hoá nào nên bản chạy thật ra -21,3 LUFS."""
    from services import video_dub as dub

    assert dub._bu_am(-21.3) == pytest.approx(dub.DO_TO_MUC_TIEU + 21.3)
    assert dub._bu_am(dub.DO_TO_MUC_TIEU) == pytest.approx(0.0)
    # Đo hỏng hoặc phim gần như im lặng: giữ nguyên, đừng khuếch đại số vô nghĩa.
    assert dub._bu_am(None) == 0.0
    assert dub._bu_am(float("-inf")) == 0.0
    assert dub._bu_am(-70.0) == 0.0
    # Chặn hai đầu.
    assert dub._bu_am(-50.0) == pytest.approx(dub.BU_AM_TOI_DA)
    assert dub._bu_am(0.0) == pytest.approx(-dub.BU_AM_TOI_DA)


@pytest.mark.adapter
def test_mux_do_do_to_roi_bu_dung_luong_vao_lenh_ghep():
    """Đo trên đúng hỗn hợp sẽ ghi ra, rồi bù bằng một hệ số tĩnh."""
    import subprocess

    from services import video_dub as dub

    bao_cao = (b"[Parsed_ebur128_0 @ 0x1] Summary:\n\n"
               b"  Integrated loudness:\n    I:         -21.3 LUFS\n"
               b"    Threshold: -31.5 LUFS\n")
    goi: list[list[str]] = []

    def _chay_gia(cmd, **_kw):
        goi.append(list(cmd))
        if "-f" in cmd and cmd[cmd.index("-f") + 1] == "null":
            return subprocess.CompletedProcess(cmd, 0, b"", bao_cao)
        return subprocess.CompletedProcess(cmd, 1, b"", b"loi")

    with mock.patch.object(dub, "_chay", side_effect=_chay_gia):
        with pytest.raises(dub.LoiLongTieng):
            dub._mux("phim.mp4", "nen.wav", "tts.wav", 10.0)

    do = goi[0]
    assert "ebur128" in do[do.index("-filter_complex") + 1]
    ghep = next(c for c in goi if "-map" in c)
    loc = ghep[ghep.index("-filter_complex") + 1]
    assert f"volume={dub.DO_TO_MUC_TIEU + 21.3:.2f}dB" in loc
    # Vẫn giữ giới hạn đỉnh SAU khi bù, kẻo bù xong thành méo.
    assert loc.index("volume=") < loc.index("alimiter=")
    # level=disabled là điều kiện SỐNG CÒN: để mặc định thì alimiter tự kéo tín
    # hiệu lên sát trần, lượng bù vừa tính thành vô nghĩa và đỉnh chạm 0 dBFS.
    assert "level=disabled" in loc


@pytest.mark.pure
def test_bo_loc_tts_dung_cao_do_va_nang_luong_tuong_doi():
    """Prosody không chỉ ghi JSON: pitch/energy phải đi vào filter âm thanh."""
    from services import video_dub as dub

    loc, tempo = dub._bo_loc_tts(0.35, 0.5, energy_relative_db=-2.0)
    assert "volume=-2.000dB" in loc
    assert tempo == pytest.approx(0.7)


@pytest.mark.pure
def test_do_cao_do_khong_bat_nham_hoa_am_bac_hai():
    """Giọng người thường có hoạ âm bậc hai to hơn cả tần số cơ bản.

    Bản cũ lấy vạch phổ TO NHẤT nên với tín hiệu dưới đây nó trả về 240 Hz cho
    một giọng 120 Hz — lệch đúng một quãng tám. Tự tương quan bám chu kỳ thật
    nên không dính lỗi đó.
    """
    import numpy as np

    from services import video_dub as dub

    rate = dub.RATE_GOC
    t = np.arange(int(rate * 1.0)) / rate
    x = (0.2 * np.sin(2 * np.pi * 120 * t)
         + 0.6 * np.sin(2 * np.pi * 240 * t)
         + 0.3 * np.sin(2 * np.pi * 360 * t)).astype(np.float32)
    assert dub._pitch_acf(x, rate) == pytest.approx(120.0, rel=0.05)


@pytest.mark.pure
def test_cue_khong_tuan_hoan_thi_khong_bia_ra_cao_do():
    """Không có gì tuần hoàn thì trả None, đừng gán bừa một con số.

    Con số bịa ở đây đi thẳng vào bộ lọc âm thanh, nên thà không chỉnh cao độ
    còn hơn chỉnh theo tiếng va đập.
    """
    import numpy as np

    from services import video_dub as dub

    rate = dub.RATE_GOC
    rng = np.random.default_rng(7)
    on = rng.normal(0.0, 0.2, int(rate * 1.0)).astype(np.float32)
    assert dub._pitch_acf(on, rate) is None
    assert dub._pitch_acf(np.zeros(int(rate * 1.0), dtype=np.float32), rate) is None


@pytest.mark.pure
def test_cao_do_nang_giong_da_chon_chu_khong_doi_sang_giong_khac():
    """Cài một giọng thì phải nghe ra một người, dù cao độ có thay đổi.

    asetrate kéo giãn cả phổ nên dịch luôn formant — thứ mã hoá chiều dài đường
    thanh, tức tai người nghe ra một người có vóc khác. Bản cũ cho lệch tới ±4
    nửa cung theo cách đó nên một video ra như cả một dàn diễn viên.
    """
    from services import video_dub as dub

    loc, _ = dub._bo_loc_tts(1.0, 1.0, pitch_relative=9.0)
    assert "asetrate=" not in loc, "asetrate dịch formant nên đổi luôn người nói"
    assert "formant=preserved" in loc
    # Trần đang là 0: đo được 9 nửa cung thì vẫn KHÔNG dịch. Phép đo chạy trên
    # track lẫn nhạc nhiễu tới mức kẹp vào ±2 cũng bão hoà, khiến câu liên tiếp
    # nhảy giữa hai đầu biên và nghe thành hai người thay phiên.
    assert f"pitch={2.0 ** (dub.PITCH_TOI_DA / 12.0):.6f}" in loc
    tram, _ = dub._bo_loc_tts(1.0, 1.0, pitch_relative=-9.0)
    assert f"pitch={2.0 ** (-dub.PITCH_TOI_DA / 12.0):.6f}" in tram
    assert loc == tram, "trần 0 thì cao độ đo được bao nhiêu cũng ra cùng filter"
    # Bật lại thì vẫn phải nằm trong vùng một người tự lên/xuống giọng.
    assert dub.PITCH_TOI_DA <= 2.0


@pytest.mark.pure
def test_cau_ngan_trong_khung_dai_khong_bi_keo_nhoe():
    """Khung 7 giây không bắt câu 0,5 giây đọc chậm 14× rồi thành tiếng rên."""
    from services import video_dub as dub

    loc, tempo = dub._bo_loc_tts(0.5, 7.0)
    assert tempo == pytest.approx(dub.TEMPO_CHAM_NHAT)
    # Đúng MỘT hệ số tốc độ, không phải chuỗi 0,5 nhân dồn như bản cũ kéo giọng
    # cho đầy khung. rubberband nhận thẳng hệ số nên không cần ghép nhiều tầng.
    assert loc.count("tempo=") == 1
    assert f"tempo={dub.TEMPO_CHAM_NHAT:.6f}" in loc
    # Câu dài hơn khung vẫn phải tăng tốc như cũ, không bị trần này chặn.
    assert dub._bo_loc_tts(6.0, 2.0)[1] == pytest.approx(3.0)


@pytest.mark.pure
def test_track_nen_bi_cut_hoac_tts_thieu_mot_cau_deu_khong_xuat_mp4(monkeypatch):
    from services import video_dub as dub

    monkeypatch.setattr(dub, "_thoi_luong", lambda _path, _fallback: 42.0)
    with pytest.raises(dub.LoiLongTieng, match="sai thời lượng"):
        dub._kiem_tra_nen_du_dai("nen.wav", 100.0)
    with pytest.raises(dub.LoiLongTieng, match="không xuất MP4 bị thiếu lời"):
        dub._bao_dam_khong_thieu_cau_tts({"cues": []}, 1, 20)


@pytest.mark.pure
def test_tts_hong_thi_bao_ro_cau_nao_chu_khong_chi_dem_so():
    """prosody.json chỉ ghi SAU bước này, nên lỗi phải tự mang manh mối theo."""
    from services import video_dub as dub

    meta = {"cues": [
        {"index": 1, "start": 0.5, "tts_status": "ok"},
        {"index": 2, "start": 12.25, "tts_status": "error",
         "tts_error": "engine trả WAV rỗng"},
    ]}
    with pytest.raises(dub.LoiLongTieng) as loi:
        dub._bao_dam_khong_thieu_cau_tts(meta, 1, 2)
    tin = str(loi.value)
    assert "câu 2" in tin and "12.2s" in tin
    assert "engine trả WAV rỗng" in tin
    assert "SRT vẫn được giữ" in tin


@pytest.mark.integration
def test_tts_loi_thoang_qua_chi_thu_lai_dung_cau_do_va_giu_track_da_lam():
    """Câu 700 lỗi một lần không được buộc tổng hợp lại 699 câu trước."""
    from services import video_dub as dub

    wav = _wav_tone(440, giay=0.1)
    tts = FakeTTS(responses=[
        wav, RuntimeError("engine bận thoáng qua"), wav])
    media = FakeFfmpeg(result=subprocess.CompletedProcess(
        [], 0, b"\x01\x00" * 2400, b""))
    meta = {"cues": [
        {"index": 1, "start": 0.0, "end": 0.1, "text": "câu một",
         "emotion": "neutral"},
        {"index": 2, "start": 0.1, "end": 0.2, "text": "câu hai",
         "emotion": "neutral"},
    ]}

    with install_tts(tts), install_video_dub_media(media):
        track, errors, _warnings = dub._tao_track(
            meta, 0.2, "giong-thu", None)
    try:
        assert errors == 0
        assert [c["text"] for c in tts.calls] == [
            "câu một", "câu hai", "câu hai"]
        assert meta["cues"][0]["tts_attempts"] == 1
        assert meta["cues"][0]["tts_recovered_after_retry"] is False
        assert meta["cues"][1]["tts_attempts"] == 2
        assert meta["cues"][1]["tts_recovered_after_retry"] is True
    finally:
        Path(track).unlink(missing_ok=True)


@pytest.mark.integration
def test_tts_loi_sau_retry_dung_som_khong_lam_cau_sau_va_khong_dem_silence():
    """Biết MP4 sẽ bị từ chối thì không đốt tiếp TTS hay ghi track im lặng dài."""
    from services import video_dub as dub

    tts = FakeTTS(responses=[
        RuntimeError("engine bận tạm thời"),
        RuntimeError("engine vẫn bận tạm thời"),
    ])
    meta = {"cues": [
        {"index": 1, "start": 0.0, "end": 1.0, "text": "câu hỏng",
         "emotion": "neutral"},
        {"index": 2, "start": 1.0, "end": 2.0, "text": "không được gọi",
         "emotion": "neutral"},
    ]}

    with install_tts(tts):
        track, errors, _warnings = dub._tao_track(
            meta, 3600.0, "giong-thu", None)
    try:
        assert errors == 1
        assert [c["text"] for c in tts.calls] == ["câu hỏng", "câu hỏng"]
        assert meta["cues"][0]["tts_attempts"] == 2
        assert "tts_status" not in meta["cues"][1]
        assert Path(track).stat().st_size < 1024
        with pytest.raises(dub.LoiLongTieng) as caught:
            dub._bao_dam_khong_thieu_cau_tts(meta, errors, 2)
        message = str(caught.value)
        assert "đã thử 2 lần" in message
        assert "1 câu chưa tổng hợp" in message
    finally:
        Path(track).unlink(missing_ok=True)


@pytest.mark.integration
def test_tts_loi_vinh_vien_va_loi_can_thoi_luong_deu_khong_retry():
    """Text/config/media hỏng không tự hết; chạy model lần hai chỉ tốn thời gian."""
    from services import video_dub as dub

    cue = {"index": 1, "start": 0.0, "end": 0.1, "text": "câu lỗi",
           "emotion": "neutral"}
    tts_vinh_vien = FakeTTS(responses=[ValueError("text không hợp lệ")])
    with install_tts(tts_vinh_vien):
        track, errors, _ = dub._tao_track(
            {"cues": [dict(cue)]}, 0.1, "giong-thu", None)
    try:
        assert errors == 1
        assert len(tts_vinh_vien.calls) == 1
    finally:
        Path(track).unlink(missing_ok=True)

    wav = _wav_tone(440, giay=0.1)
    tts_media = FakeTTS(responses=[wav, wav])
    media = FakeFfmpeg(FileNotFoundError("thiếu ffmpeg"))
    meta = {"cues": [dict(cue)]}
    with install_tts(tts_media), install_video_dub_media(media):
        track, errors, _ = dub._tao_track(meta, 0.1, "giong-thu", None)
    try:
        assert errors == 1
        assert len(tts_media.calls) == 1
        assert meta["cues"][0]["tts_attempts"] == 1
    finally:
        Path(track).unlink(missing_ok=True)


@pytest.mark.pure
def test_loi_la_thi_van_thu_lai_thay_vi_vut_ca_buoi_tong_hop():
    """Không nhận ra lỗi thì thử lại: dừng nhầm đắt hơn thử thừa rất nhiều."""
    import subprocess

    from services import video_dub as dub

    # Kiểu lỗi hay gặp nhất của engine chạy tiến trình con, không khớp mẫu nào.
    assert dub._loi_tts_tam_thoi(subprocess.CalledProcessError(1, "piper")) is True
    assert dub._loi_tts_tam_thoi(RuntimeError("engine trả WAV rỗng")) is True
    # Nhưng lỗi chắc chắn không tự hết thì vẫn phải dừng ngay, khỏi phí lượt.
    assert dub._loi_tts_tam_thoi(RuntimeError("CUDA out of memory")) is False
    assert dub._loi_tts_tam_thoi(dub.LoiLongTieng("Thiếu ffmpeg/ffprobe")) is False
    assert dub._loi_tts_tam_thoi(FileNotFoundError("piper")) is False


@pytest.mark.pure
def test_ffmpeg_qua_gio_duoc_thu_lai_chu_khong_giet_ca_phim():
    """Quá giờ là máy đang tải, không phải tệp hỏng — phải phân biệt được."""
    from services import video_dub as dub

    assert issubclass(dub.LoiLongTiengTamThoi, dub.LoiLongTieng)
    assert dub._loi_tts_tam_thoi(dub.LoiLongTiengTamThoi("quá giờ")) is True
