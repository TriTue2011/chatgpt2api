"""Đường nghe phụ đề qua máy GPU: định tuyến, chuyển đổi mốc, cầu dao, đường lui.

Không đụng mạng và không nạp model — `requests.post` bị thay bằng hàm giả.

Ca quan trọng nhất ở đây là ĐƯỜNG LUI: máy GPU chết thì phụ đề vẫn phải ra, chỉ
là nghe bằng model tại chỗ. Và cầu dao chỉ được ngắt khi máy GPU thật sự lỗi —
tệp không có tiếng nói thì máy vẫn tốt, ngắt cầu dao là phạt oan nó 5 phút.
"""

from __future__ import annotations

import os
import sys
import threading
import types
from unittest import mock

import numpy as np
import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import nghe_gpu  # noqa: E402
from services import video_asr as va  # noqa: E402


@pytest.fixture(autouse=True)
def _mo_cau_dao():
    """Mỗi ca bắt đầu với cầu dao đang mở."""
    nghe_gpu._nghi_toi = 0.0
    yield
    nghe_gpu._nghi_toi = 0.0


def _wav(tmp_path):
    """Một tệp wav bé có thật — nghe() mở tệp trước khi gửi."""
    tep = tmp_path / "doan.wav"
    tep.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    return tep


def _tra_loi(doan):
    """Hàm giả cho requests.post trả về JSON kiểu fw-nghe."""
    def _post(*_a, **_k):
        return types.SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"lang": "en", "doan": doan})
    return _post


# ── Định tuyến ──────────────────────────────────────────────────────────────


def test_khong_khai_dia_chi_thi_khong_dung(monkeypatch):
    monkeypatch.setattr("services.voice.config.stt_gpu_url", lambda: "")
    assert nghe_gpu.dung_duoc("en") is False


def test_chi_dung_cho_tieng_da_khai(monkeypatch):
    monkeypatch.setattr("services.voice.config.stt_gpu_url", lambda: "http://x:5002")
    monkeypatch.setattr("services.voice.config.stt_gpu_tieng", lambda: ("en", "ko"))
    assert nghe_gpu.dung_duoc("en") is True
    assert nghe_gpu.dung_duoc("KO") is True        # không phân biệt hoa thường
    assert nghe_gpu.dung_duoc("vi") is False       # tại chỗ nghe tốt, giữ tại chỗ


def test_cau_dao_dang_ngat_thi_khong_dung(monkeypatch):
    monkeypatch.setattr("services.voice.config.stt_gpu_url", lambda: "http://x:5002")
    monkeypatch.setattr("services.voice.config.stt_gpu_tieng", lambda: ("en",))
    nghe_gpu._ngat_cau_dao("thử")
    assert nghe_gpu.dung_duoc("en") is False


def test_tieng_mac_dinh_lay_theo_so_do(monkeypatch):
    from services.voice import config as vcfg

    # en và ko là hai tiếng mà model tại chỗ BỎ TRẮNG đoạn (7% và 45%).
    assert vcfg.STT_GPU_TIENG_MAC_DINH == ("en", "ko")
    monkeypatch.setattr(vcfg, "_sub", lambda name: {})
    assert vcfg.stt_gpu_tieng() == ("en", "ko")
    monkeypatch.setattr(vcfg, "_sub", lambda name: {"gpu_tieng": "en, ja ;zh"})
    assert vcfg.stt_gpu_tieng() == ("en", "ja", "zh")


# ── Chuyển đổi kết quả ──────────────────────────────────────────────────────


def test_moc_tung_chu_giu_nguyen_theo_gio_tuyet_doi(monkeypatch, tmp_path):
    monkeypatch.setattr("services.voice.config.stt_gpu_url", lambda: "http://x:5002")
    doan = [
        {"bat_dau": 1.0, "ket_thuc": 2.0, "chu": "hello there",
         "tu": [{"t": 1.0, "chu": " hello"}, {"t": 1.5, "chu": " there"}]},
        {"bat_dau": 9.0, "ket_thuc": 9.5, "chu": "bye",
         "tu": [{"t": 9.0, "chu": " bye"}]},
    ]
    with mock.patch("requests.post", _tra_loi(doan)):
        tokens, moc = nghe_gpu.nghe(str(_wav(tmp_path)), "en")
    assert tokens == [" hello", " there", " bye"]
    assert moc == [1.0, 1.5, 9.0]
    # Ghép bằng bộ cắt khung SẴN CÓ, không có bộ thứ hai để lệch nhau.
    khung = va.gom_khung(tokens, moc, 0.0)
    assert [k.chu for k in khung] == ["hello there", "bye"]
    assert khung[0].bat_dau == pytest.approx(1.0)


def test_doan_thieu_moc_tung_chu_van_giu_lai_chu(monkeypatch, tmp_path):
    monkeypatch.setattr("services.voice.config.stt_gpu_url", lambda: "http://x:5002")
    doan = [{"bat_dau": 3.0, "ket_thuc": 5.0, "chu": "cả đoạn", "tu": []}]
    with mock.patch("requests.post", _tra_loi(doan)):
        tokens, moc = nghe_gpu.nghe(str(_wav(tmp_path)), "en")
    assert tokens == ["cả đoạn"] and moc == [3.0]


# ── Cầu dao ─────────────────────────────────────────────────────────────────


def test_loi_mang_thi_ngat_cau_dao(monkeypatch, tmp_path):
    monkeypatch.setattr("services.voice.config.stt_gpu_url", lambda: "http://x:5002")
    monkeypatch.setattr("services.voice.config.stt_gpu_tieng", lambda: ("en",))

    def _no(*_a, **_k):
        raise OSError("máy tắt")

    with mock.patch("requests.post", _no):
        with pytest.raises(nghe_gpu.LoiNgheGpu):
            nghe_gpu.nghe(str(_wav(tmp_path)), "en")
    assert nghe_gpu.dung_duoc("en") is False, "phải nghỉ GPU sau khi lỗi"


def test_tep_khong_co_tieng_thi_KHONG_ngat_cau_dao(monkeypatch, tmp_path):
    """Máy GPU vẫn tốt — chỉ là tệp im lặng. Ngắt cầu dao là phạt oan nó."""
    monkeypatch.setattr("services.voice.config.stt_gpu_url", lambda: "http://x:5002")
    monkeypatch.setattr("services.voice.config.stt_gpu_tieng", lambda: ("en",))
    with mock.patch("requests.post", _tra_loi([])):
        with pytest.raises(nghe_gpu.LoiNgheGpu):
            nghe_gpu.nghe(str(_wav(tmp_path)), "en")
    assert nghe_gpu.dung_duoc("en") is True


# ── Điểm đấu nối trong đường phụ đề ─────────────────────────────────────────


def _lap_duong_phu_de(monkeypatch, ket_qua_local=("LOCAL",)):
    """Cắm đủ hàm giả để gọi được nghe_tep mà không cần ffmpeg lẫn model."""
    eng = types.ModuleType("services.voice.engines")
    eng._stt_lock = threading.Lock()
    eng._get_recognizer = lambda lang: object()
    eng._normalize_stt = lambda s: s.strip()
    goi = types.ModuleType("services.voice")
    goi.engines = eng
    monkeypatch.setitem(sys.modules, "services.voice", goi)
    monkeypatch.setitem(sys.modules, "services.voice.engines", eng)

    monkeypatch.setattr(va, "_boc_tieng", lambda d: "/tmp/khong-co-that.wav")
    monkeypatch.setattr(va, "_doc_wav",
                        lambda d: (np.zeros(1000, dtype=np.float32), 100))
    monkeypatch.setattr(va, "cat_doan_tieng", lambda mau, rate: [(0.0, 2.0)])
    monkeypatch.setattr(va, "_chon_ngon_ngu", lambda *a, **k: "en")
    monkeypatch.setattr(
        va, "_nghe_mot_doan",
        lambda rec, mau, rate: (list(ket_qua_local),
                                [0.0] * len(ket_qua_local)))


def test_dung_may_gpu_khi_dung_duoc(monkeypatch):
    _lap_duong_phu_de(monkeypatch)
    monkeypatch.setattr(nghe_gpu, "dung_duoc", lambda lang: True)
    monkeypatch.setattr(nghe_gpu, "nghe",
                        lambda wav, lang: ([" from", " gpu"], [0.0, 0.3]))
    cau, lang, giay = va.nghe_tep("/tmp/phim.mp4", ung_vien=("en",))
    assert [c.chu for c in cau] == ["from gpu"]
    assert lang == "en" and giay == pytest.approx(2.0)


def test_may_gpu_loi_thi_van_ra_phu_de_bang_model_tai_cho(monkeypatch):
    _lap_duong_phu_de(monkeypatch, ket_qua_local=("TAI", " CHO"))
    monkeypatch.setattr(nghe_gpu, "dung_duoc", lambda lang: True)

    def _no(wav, lang):
        raise nghe_gpu.LoiNgheGpu("máy GPU tắt")

    monkeypatch.setattr(nghe_gpu, "nghe", _no)
    cau, lang, _ = va.nghe_tep("/tmp/phim.mp4", ung_vien=("en",))
    assert [c.chu for c in cau] == ["TAI CHO"], "phải rơi về model tại chỗ"


def test_khong_bat_gpu_thi_di_duong_tai_cho(monkeypatch):
    _lap_duong_phu_de(monkeypatch, ket_qua_local=("TAI", " CHO"))
    monkeypatch.setattr(nghe_gpu, "dung_duoc", lambda lang: False)

    def _khong_duoc_goi(*_a, **_k):
        raise AssertionError("không được gọi máy GPU khi chưa bật")

    monkeypatch.setattr(nghe_gpu, "nghe", _khong_duoc_goi)
    cau, _, _ = va.nghe_tep("/tmp/phim.mp4", ung_vien=("en",))
    assert [c.chu for c in cau] == ["TAI CHO"]
