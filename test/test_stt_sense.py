"""Đường nghe SenseVoice cho zh/ja/ko, và chỗ nó suýt làm hỏng bộ dò ngôn ngữ.

Đo 15/08/2026 trên 150 bản thu FLEURS mỗi tiếng: SenseVoice hạ tiếng Hàn từ
55,5% sai ký tự (bỏ trắng 67/150 bản) xuống 6,2% (bỏ trắng 0), tiếng Nhật 9,8%
→ 7,0%, tiếng Trung 13,6% → 10,2%. Nhưng nó KHÔNG trả ``ys_log_probs`` — thứ
bộ dò ngôn ngữ của phụ đề đang dùng để chấm điểm — nên nếu không có nhánh chấm
theo tiếng-model-tự-khai thì mọi tiếng dùng SenseVoice bị chấm -9,9 và thua
trắng: video tiếng Nhật bị nghe bằng model tiếng Việt, không lỗi, không ai báo.
"""

from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from services.voice import config as vcfg  # noqa: E402


def test_tieng_mac_dinh_khong_gom_vi_va_en():
    """Tiếng Việt: SenseVoice không biết. Tiếng Anh: đổi là đụng phép so
    vi/en của bộ dò ngôn ngữ, mà phép so đó đang chạy đúng."""
    assert vcfg.STT_SENSE_TIENG_MAC_DINH == ("zh", "ja", "ko")
    assert "vi" not in vcfg.stt_sense_tieng()
    assert "en" not in vcfg.stt_sense_tieng()


def test_chua_tai_model_thi_khong_nhan_bua(monkeypatch, tmp_path):
    """Chưa tải thì phải trả None để code rơi về ba Zipformer cũ."""
    monkeypatch.setattr(vcfg, "STT_SENSE_DIR", tmp_path / "khong-co")
    assert vcfg.stt_sense_model_dir() is None
    trong = tmp_path / "rong"
    trong.mkdir()
    monkeypatch.setattr(vcfg, "STT_SENSE_DIR", trong)
    assert vcfg.stt_sense_model_dir() is None, "thư mục rỗng vẫn bị nhận là có model"
    (trong / "model.int8.onnx").write_bytes(b"x")
    assert vcfg.stt_sense_model_dir() == trong


class _KetQua:
    """Kết quả kiểu SenseVoice: có tokens + lang, KHÔNG có ys_log_probs."""

    def __init__(self, lang: str, so_token: int = 8):
        self.lang = f"<|{lang}|>"
        self.tokens = ["x"] * so_token
        self.timestamps = [0.1 * i for i in range(so_token)]
        self.ys_log_probs: list[float] = []
        self.text = "x" * so_token


class _KetQuaTransducer:
    def __init__(self, lp: float, so_token: int = 8):
        self.tokens = ["x"] * so_token
        self.timestamps = [0.1 * i for i in range(so_token)]
        self.ys_log_probs = [lp] * so_token
        self.text = "x" * so_token


class _Rec:
    def __init__(self, ket_qua):
        self._kq = ket_qua

    def create_stream(self):
        rec = self

        class _Stream:
            def accept_waveform(self, rate, mau):
                pass

            @property
            def result(self):
                return rec._kq

        return _Stream()

    def decode_stream(self, stream):
        pass


def _do_ngon_ngu(monkeypatch, recs: dict, ung_vien: tuple[str, ...]) -> str:
    np = pytest.importorskip("numpy")
    import services.video_asr as va
    from services.voice import engines as eng

    monkeypatch.setattr(eng, "_get_recognizer", lambda lang: recs[lang])
    rate = 16000
    mau = np.zeros(rate * 30, dtype=np.float32)
    return va._chon_ngon_ngu(mau, rate, [(0.0, 30.0)], ung_vien)


def test_do_ngon_ngu_khong_cam_khi_model_la_sense(monkeypatch):
    """Model SenseVoice khai đúng tiếng thì phải THẮNG model tiếng Việt đang
    nghe nhoè — không có nhánh này thì nó bị chấm -9,9 và thua trắng."""
    ra = _do_ngon_ngu(monkeypatch, {
        "vi": _Rec(_KetQuaTransducer(-0.55)),    # nghe nhoè: sai tiếng
        "ja": _Rec(_KetQua("ja")),               # tự khai đúng tiếng Nhật
    }, ("vi", "ja"))
    assert ra == "ja"


def test_tieng_viet_khong_bi_sense_cuop(monkeypatch):
    """Âm tiếng Việt: model Việt tự tin, còn SenseVoice khai bừa tiếng khác
    (nó không biết tiếng Việt) → phải chọn vi."""
    ra = _do_ngon_ngu(monkeypatch, {
        "vi": _Rec(_KetQuaTransducer(-0.04)),
        "ja": _Rec(_KetQua("zh")),               # khai zh, không phải ja
    }, ("vi", "ja"))
    assert ra == "vi"
