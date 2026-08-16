from pathlib import Path

import pytest

from test._fakes import (FakeAudioSeparatorTransport,
                         install_audio_separator_transport)


@pytest.mark.adapter
def test_preflight_bao_som_truoc_khi_nghe_dich_phim(monkeypatch):
    from services import tach_am_gpu as ta

    monkeypatch.setenv("TACH_AM_URL_GPU", "http://gpu:5004")
    monkeypatch.setenv("TACH_AM_API_TOKEN", "bi-mat-thu")
    ta._nghi_toi = 0.0
    fake = FakeAudioSeparatorTransport(b"")
    with install_audio_separator_transport(fake):
        ta.xac_nhan_san_sang(timeout=2)
    assert fake.calls[0]["url"] == "http://gpu:5004/health"
    assert fake.calls[0]["timeout"] == 2
    assert fake.calls[0]["headers"]["X-API-Key"] == "bi-mat-thu"


@pytest.mark.adapter
def test_preflight_may_ban_van_nhan_viec_de_cho_hang_doi_gpu(monkeypatch):
    from services import tach_am_gpu as ta

    monkeypatch.setenv("TACH_AM_URL_GPU", "http://gpu:5004")
    monkeypatch.setenv("TACH_AM_API_TOKEN", "bi-mat-thu")
    ta._nghi_toi = 0.0
    fake = FakeAudioSeparatorTransport(b"", busy=True)
    with install_audio_separator_transport(fake):
        ta.xac_nhan_san_sang(timeout=2)
    assert ta._nghi_toi == 0.0


@pytest.mark.adapter
def test_gui_soundtrack_day_du_nhan_track_nen_va_khong_dung_nham_job_sau(monkeypatch):
    from services import tach_am_gpu as ta

    monkeypatch.setenv("TACH_AM_URL_GPU", "http://gpu:5004")
    monkeypatch.setenv("TACH_AM_API_TOKEN", "bi-mat-thu")
    ta._nghi_toi = 0.0
    fake = FakeAudioSeparatorTransport(b"RIFF" + b"n" * 200, "mdx-thu")
    with install_audio_separator_transport(fake):
        ket = ta.tach_nen("phim.mp4", tran_giay=123)
    try:
        assert Path(ket.background_path).read_bytes() == b"RIFF" + b"n" * 200
        assert ket.model == "mdx-thu"
        cmd = fake.curl_calls[0]
        assert cmd[0] == "curl"
        assert cmd[-1] == "http://gpu:5004/tach?stem=nen"
        assert cmd[cmd.index("--max-time") + 1] == "123"
        # upload-file khiến libcurl và server cùng stream, không spool multipart.
        assert cmd[cmd.index("--upload-file") + 1].endswith(".wav")
        assert "X-API-Key: bi-mat-thu" in fake.request_header_texts[0]
        assert "X-Job-Token:" in fake.request_header_texts[0]
        # Response chỉ tới sau khi subprocess server đã thoát. Không gọi
        # /unload muộn vì lúc ấy service có thể đã nhận job kế tiếp.
        assert all(not c["url"].endswith("/unload") for c in fake.calls)
        assert all(not Path(p).exists() for p in fake.extracted)
    finally:
        Path(ket.background_path).unlink(missing_ok=True)


@pytest.mark.adapter
def test_unload_mang_dung_api_key_va_job_token(monkeypatch):
    from services import tach_am_gpu as ta

    monkeypatch.setenv("TACH_AM_API_TOKEN", "bi-mat-thu")
    fake = FakeAudioSeparatorTransport(b"")
    with install_audio_separator_transport(fake):
        assert ta._nha_model("http://gpu:5004", "job-123456789012") is True
    call = fake.calls[-1]
    assert call["headers"] == {
        "X-API-Key": "bi-mat-thu", "X-Job-Token": "job-123456789012"}


@pytest.mark.adapter
def test_track_nen_rong_ngat_cau_dao_va_khong_tra_video_sai(monkeypatch):
    from services import tach_am_gpu as ta

    monkeypatch.setenv("TACH_AM_URL_GPU", "http://gpu:5004")
    monkeypatch.setenv("TACH_AM_API_TOKEN", "bi-mat-thu")
    ta._nghi_toi = 0.0
    fake = FakeAudioSeparatorTransport(b"")
    with install_audio_separator_transport(fake):
        with pytest.raises(ta.LoiTachAm, match="tệp rỗng"):
            ta.tach_nen("phim.mp4")
    assert ta._nghi_toi > 0
    ta._nghi_toi = 0.0


@pytest.mark.adapter
def test_thieu_token_dung_ngay_khong_boc_wav_va_khong_ngat_cau_dao(monkeypatch):
    """Thiếu cấu hình là lỗi phía mình — đừng bóc WAV nhiều GB rồi phạt máy GPU."""
    from services import tach_am_gpu as ta

    monkeypatch.setenv("TACH_AM_URL_GPU", "http://gpu:5004")
    monkeypatch.setenv("TACH_AM_API_TOKEN", "")
    from services.config import config

    monkeypatch.setitem(config.data, "tach_am_api_token", "")
    ta._nghi_toi = 0.0

    fake = FakeAudioSeparatorTransport(b"")
    with install_audio_separator_transport(fake):
        with pytest.raises(ta.LoiTachAm, match="TACH_AM_API_TOKEN"):
            ta.tach_nen("/tmp/phim.mp4")
    # Cầu dao phải đứng yên: máy tách âm không có lỗi gì ở đây.
    assert ta._nghi_toi == 0.0
    assert fake.extracted == []
