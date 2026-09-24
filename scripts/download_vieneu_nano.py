#!/usr/bin/env python3
"""Tải VieNeu-TTS v3 Nano (pnnbao-ump/VieNeu-TTS-v3-Nano, Apache-2.0) về data/vieneu-nano/.

Họ giọng NHANH cho máy yếu (id "vieneunano:<Tên>", 11 giọng, 24 kHz). Đo
24/09/2026 trên máy chủ Xeon E5-2630L v4: RTF 0,68 ở 16 bước — v3 Turbo ~2.
Gói ~400 MB, không nằm trong image.

    python scripts/download_vieneu_nano.py            # tải (bỏ qua file đã có)
    python scripts/download_vieneu_nano.py --check    # chỉ kiểm tra

Chạy trong container:
    docker exec -it c2a /app/.venv/bin/python scripts/download_vieneu_nano.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = Path(os.environ.get("VIENEU_NANO_DIR") or ROOT / "data" / "vieneu-nano")
REPO = "pnnbao-ump/VieNeu-TTS-v3-Nano"
# GHIM đúng commit đã đo 24/09/2026 (RTF 0,68, STT nghe lại 0/76 chữ sai).
REVISION = "aba295eb96a6fa6003ebe417cc1f2802a7adc1dc"
BAT_BUOC = ("config.json", "constants.npz", "text_encoder.onnx", "duration_predictor.onnx",
            "vector_estimator.onnx", "codec_decoder.onnx")


def _kiem() -> bool:
    du = True
    for ten in BAT_BUOC:
        co = (DEST / ten).is_file()
        du = du and co
        print(f"[{'co' if co else 'THIEU'}] {ten}")
    return du


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra, không tải")
    args = ap.parse_args()
    print(f"Thư mục: {DEST}")
    if args.check:
        return 0 if _kiem() else 1
    from huggingface_hub import snapshot_download

    DEST.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=REPO, revision=REVISION, local_dir=DEST,
                      allow_patterns=["*.onnx", "*.json", "*.npz"])
    tong = sum(p.stat().st_size for p in DEST.rglob("*") if p.is_file()) / 1e6
    print(f"\nĐã tải ~{tong:.0f} MB.")
    return 0 if _kiem() else 1


if __name__ == "__main__":
    sys.exit(main())
