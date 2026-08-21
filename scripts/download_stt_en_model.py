#!/usr/bin/env python3
"""Tải model STT tiếng Anh (NVIDIA Parakeet-TDT 0.6B v2, int8) về data/stt-en/.

Model do k2-fsa đóng gói sẵn cho sherpa-onnx (kiến trúc NeMo transducer) —
top nhóm mở trên Open ASR Leaderboard, chạy CPU nhanh hơn Whisper nhiều lần.
Cùng nguyên tắc Piper/Zipformer: code trong image, model ngoài volume.

    python scripts/download_stt_en_model.py           # tải + giải nén
    python scripts/download_stt_en_model.py --check   # chỉ kiểm tra

Bật dùng: config voice.stt.language = "en" (hoặc form field `language=en`
khi gọi POST /v1/audio/transcriptions).
"""

from __future__ import annotations

import argparse
import sys
import tarfile
import tempfile
from pathlib import Path

try:
    from scripts.model_download import (
        MODEL_MANIFEST,
        download_verified,
        install_verified_files,
        installation_verified,
    )
except ModuleNotFoundError:  # chạy trực tiếp `python scripts/...py`
    from model_download import (  # type: ignore[no-redef]
        MODEL_MANIFEST,
        download_verified,
        install_verified_files,
        installation_verified,
    )

NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
       f"asr-models/{NAME}.tar.bz2")
SHA256 = "157c157bc51155e03e37d2466522a3a737dd9c72bb25f36eb18912964161e1ad"
DEST = Path(__file__).resolve().parents[1] / "data" / "stt-en"
NEED = ["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"]
MARKER = MODEL_MANIFEST


def _marker_ok() -> bool:
    return installation_verified(DEST, SHA256, NEED)


def _check() -> bool:
    ok = _marker_ok()
    for name in NEED:
        have = (DEST / name).is_file()
        ok = ok and have
        print(f"[{'co' if have else 'THIEU'}] {DEST / name}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra")
    args = ap.parse_args()
    if args.check:
        return 0 if _check() else 1
    if _check():
        print("Model da du — khong tai lai.")
        return 0

    DEST.mkdir(parents=True, exist_ok=True)
    print(f"[tai] {URL}\n      (~600 MB — có thể mất vài phút)")
    with tempfile.NamedTemporaryFile(suffix=".tar.bz2", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        download_verified(URL, tmp_path, SHA256)
        print("[giai nen] ...")
        with tempfile.TemporaryDirectory(
            prefix=".stt-en-extract-", dir=DEST.parent
        ) as raw_staging:
            staging = Path(raw_staging)
            with tarfile.open(tmp_path, "r:bz2") as tar:
                for m in tar.getmembers():
                    base = Path(m.name).name
                    # Chỉ lấy file model ở gốc gói (bỏ test_wavs/, thư mục lồng).
                    if m.isfile() and base in NEED:
                        src = tar.extractfile(m)
                        if src is None:
                            continue
                        (staging / base).write_bytes(src.read())
                        print(f"[ok] {base}")
            install_verified_files(
                staging,
                DEST,
                SHA256,
                NEED,
                managed_patterns=[
                    "encoder*.onnx", "decoder*.onnx", "joiner*.onnx", "tokens.txt",
                ],
            )
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    return 0 if _check() else 1


if __name__ == "__main__":
    sys.exit(main())
