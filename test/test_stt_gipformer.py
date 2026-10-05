"""Model nghe tiếng Việt THỨ HAI (Gipformer 68M) — chủ máy 06/10/2026 chọn tích hợp làm LỰA CHỌN, mặc định giữ
Zipformer. Chọn Gipformer mà chưa tải thì phải lùi về Zipformer, không được mất tai."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.voice import config as vcfg  # noqa: E402


@pytest.fixture
def hai_model(tmp_path, monkeypatch):
    zi, gi = tmp_path / "stt", tmp_path / "stt-gipformer"
    for d, ten in ((zi, "encoder-epoch-20-avg-10.onnx"), (gi, "encoder.int8.onnx")):
        d.mkdir()
        (d / ten).write_bytes(b"x")
    monkeypatch.setattr(vcfg, "STT_DIR", zi)
    monkeypatch.setattr(vcfg, "STT_GIP_DIR", gi)
    stt: dict = {}
    monkeypatch.setattr(vcfg, "_sub", lambda name: stt if name == "stt" else {})
    return zi, gi, stt


def test_mac_dinh_zipformer(hai_model):
    zi, _, _ = hai_model
    assert vcfg.stt_engine() == "zipformer" and vcfg.stt_model_dir() == zi


def test_chon_gipformer_da_tai(hai_model):
    _, gi, stt = hai_model
    stt["engine"] = "Gipformer"
    assert vcfg.stt_engine() == "gipformer" and vcfg.stt_model_dir() == gi


def test_chon_gipformer_chua_tai_thi_lui_zipformer(hai_model):
    zi, gi, stt = hai_model
    (gi / "encoder.int8.onnx").unlink()
    stt["engine"] = "gipformer"
    assert vcfg.stt_gip_model_dir() is None
    assert vcfg.stt_model_dir() == zi, "chưa tải Gipformer: vẫn nghe bằng Zipformer, không mất tai"


def test_gia_tri_la_va_khai_tay(hai_model, tmp_path):
    zi, _, stt = hai_model
    stt["engine"] = "whisper"
    assert vcfg.stt_engine() == "zipformer"
    tay = tmp_path / "tay"
    tay.mkdir()
    (tay / "encoder.onnx").write_bytes(b"x")
    stt.update(engine="gipformer", model_dir=str(tay))
    assert vcfg.stt_model_dir() == tay, "voice.stt.model_dir khai tay thì thắng"


def test_script_tai_ghim_dung_commit_va_sha():
    from scripts import download_stt_model as d
    assert d.GIP_HF_REPO == "g-group-ai-lab/gipformer1.5-68M-rnnt"
    assert d.GIP_HF_REVISION == "dd9227dcd8705c13f33bdbe59728d546ab94480f"
    assert set(d.GIP_SHA256) == {"encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "bpe.model"}
    assert all(len(h) == 64 for h in d.GIP_SHA256.values())
