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
import urllib.request
from pathlib import Path

NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
       f"asr-models/{NAME}.tar.bz2")
DEST = Path(__file__).resolve().parents[1] / "data" / "stt-en"
NEED = ["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"]


def _check() -> bool:
    ok = True
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
        urllib.request.urlretrieve(URL, tmp_path)
        print("[giai nen] ...")
        with tarfile.open(tmp_path, "r:bz2") as tar:
            for m in tar.getmembers():
                base = Path(m.name).name
                # Chỉ lấy file model ở gốc gói (bỏ test_wavs/, thư mục lồng).
                if m.isfile() and base in NEED:
                    src = tar.extractfile(m)
                    if src is None:
                        continue
                    (DEST / base).write_bytes(src.read())
                    print(f"[ok] {base}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    return 0 if _check() else 1


if __name__ == "__main__":
    sys.exit(main())
