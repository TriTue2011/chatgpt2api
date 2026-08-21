"""Model STT là input nhị phân cho native runtime: phải ghim và kiểm hash."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_download_sai_hash_khong_de_len_file_tot(tmp_path: Path, monkeypatch) -> None:
    from scripts import model_download as guard

    target = tmp_path / "model.onnx"
    target.write_bytes(b"good-old-model")

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size: int = -1) -> bytes:
            if getattr(self, "done", False):
                return b""
            self.done = True
            return b"tampered-new-model"

    monkeypatch.setattr(guard.urllib.request, "urlopen", lambda *_a, **_k: _Response())
    expected = hashlib.sha256(b"expected-new-model").hexdigest()

    with pytest.raises(guard.IntegrityError):
        guard.download_verified("https://example.invalid/model", target, expected)

    assert target.read_bytes() == b"good-old-model"


def test_download_dung_hash_thay_file_nguyen_tu(tmp_path: Path, monkeypatch) -> None:
    from scripts import model_download as guard

    payload = b"verified-model"
    target = tmp_path / "model.onnx"

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size: int = -1) -> bytes:
            if getattr(self, "done", False):
                return b""
            self.done = True
            return payload

    monkeypatch.setattr(guard.urllib.request, "urlopen", lambda *_a, **_k: _Response())
    guard.download_verified(
        "https://example.invalid/model",
        target,
        hashlib.sha256(payload).hexdigest(),
    )
    assert target.read_bytes() == payload


def test_zipformer_vi_ghim_commit_va_hash_tung_file() -> None:
    from scripts import download_stt_model as vi

    assert len(vi.HF_REVISION) == 40
    assert set(vi.SHA256) == set(vi.FILES)
    assert all(len(value) == 64 for value in vi.SHA256.values())


def test_moi_goi_stt_release_deu_co_sha256() -> None:
    from scripts import download_stt_da_ngu as multi
    from scripts import download_stt_en_model as en

    assert len(en.SHA256) == 64
    assert set(multi.SHA256) == {*multi.MODELS, "sense"}
    assert all(len(value) == 64 for value in multi.SHA256.values())


def test_release_dat_file_tam_cung_filesystem_voi_dich(
    tmp_path: Path, monkeypatch
) -> None:
    """`os.replace` chỉ nguyên tử khi file tạm nằm cùng filesystem."""
    from scripts import download_stt_model as vi

    payload = b"verified-release-model"
    digest = hashlib.sha256(payload).hexdigest()
    destination = tmp_path / "models"
    observed: dict[str, Path] = {}

    monkeypatch.setattr(vi, "FILES", ["model.onnx"])
    monkeypatch.setattr(vi, "SHA256", {"model.onnx": digest})
    monkeypatch.setattr(vi, "_has_gh", lambda: True)

    def _run(command, **_kwargs):
        download_dir = Path(command[command.index("-D") + 1])
        observed["download_dir"] = download_dir
        (download_dir / "model.onnx").write_bytes(payload)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(vi.subprocess, "run", _run)

    assert vi._download_release(destination) == 0
    assert observed["download_dir"].parent == destination
    assert (destination / "model.onnx").read_bytes() == payload


def test_manifest_phat_hien_model_da_giai_nen_bi_sua(tmp_path: Path) -> None:
    from scripts import model_download as guard

    staging = tmp_path / "staging"
    destination = tmp_path / "model"
    staging.mkdir()
    (staging / "encoder.onnx").write_bytes(b"model-tot")

    guard.install_verified_files(
        staging, destination, "a" * 64, ["encoder.onnx"]
    )
    assert guard.installation_verified(
        destination, "a" * 64, ["encoder.onnx"]
    )

    (destination / "encoder.onnx").write_bytes(b"model-da-bi-sua")
    assert not guard.installation_verified(
        destination, "a" * 64, ["encoder.onnx"]
    )


def test_goi_giai_nen_thieu_file_khong_de_len_ban_cu(tmp_path: Path) -> None:
    from scripts import model_download as guard

    staging = tmp_path / "staging"
    destination = tmp_path / "model"
    staging.mkdir()
    destination.mkdir()
    (staging / "encoder.onnx").write_bytes(b"moi")
    (destination / "encoder.onnx").write_bytes(b"cu")

    with pytest.raises(guard.IntegrityError):
        guard.install_verified_files(
            staging,
            destination,
            "b" * 64,
            ["encoder.onnx", "tokens.txt"],
        )
    assert (destination / "encoder.onnx").read_bytes() == b"cu"


def test_cai_model_don_file_cu_va_chi_cong_bo_marker_sau_cung(
    tmp_path: Path,
) -> None:
    from scripts import model_download as guard

    staging = tmp_path / "staging"
    destination = tmp_path / "model"
    staging.mkdir()
    destination.mkdir()
    (staging / "encoder.int8.onnx").write_bytes(b"moi")
    (destination / "encoder.fp32.onnx").write_bytes(b"cu")

    guard.install_verified_files(
        staging,
        destination,
        "c" * 64,
        ["encoder.int8.onnx"],
        managed_patterns=["encoder*.onnx"],
    )

    assert not (destination / "encoder.fp32.onnx").exists()
    assert not (destination / guard.MODEL_INSTALLING).exists()
    assert guard.installation_verified(destination, "c" * 64)


def test_runtime_tu_choi_bo_model_bi_ngat_giua_lan_cai(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from scripts import model_download as guard
    from services.voice import config as vcfg

    staging = tmp_path / "staging"
    destination = tmp_path / "model"
    staging.mkdir()
    destination.mkdir()
    (staging / "encoder.onnx").write_bytes(b"encoder-moi")
    (staging / "tokens.txt").write_bytes(b"tokens-moi")

    real_replace = guard.os.replace

    def fail_second(source, target):
        if Path(source).name == "tokens.txt":
            raise OSError("mat dien")
        return real_replace(source, target)

    monkeypatch.setattr(guard.os, "replace", fail_second)
    with pytest.raises(OSError):
        guard.install_verified_files(
            staging,
            destination,
            "d" * 64,
            ["encoder.onnx", "tokens.txt"],
        )

    assert (destination / guard.MODEL_INSTALLING).is_file()
    assert not vcfg._stt_install_committed(destination)
