#!/usr/bin/env python3
"""Tải model STT tiếng Việt (Zipformer) về data/stt/ — KHÔNG nằm trong image.

Cùng nguyên tắc với giọng Piper: code ở trong image, model ở ngoài volume, nên
image không phình thêm ~100 MB.

    python scripts/download_stt_model.py            # tải từ GitHub Release
    python scripts/download_stt_model.py --hf       # tải thẳng từ HuggingFace
    python scripts/download_stt_model.py --list

Repo private → cần `gh auth login` hoặc biến môi trường GH_TOKEN.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from scripts.model_download import (
        IntegrityError,
        download_verified,
        is_verified,
        replace_verified,
    )
except ModuleNotFoundError:  # chạy trực tiếp `python scripts/...py`
    from model_download import IntegrityError, download_verified, is_verified, replace_verified

REPO = os.environ.get("C2A_REPO", "TriTue2011/chatgpt2api")
TAG = "stt-zipformer-v1"
HF_REPO = "hynt/Zipformer-30M-RNNT-6000h"
# Commit đã đối chiếu trên Hugging Face ngày 21/08/2026. Không dùng
# `main`: chủ repo thay file cùng tên sẽ đổi model mà không qua review.
HF_REVISION = "24ed30248e1c96bb690c81c24ab4e056f8cd9fce"

FILES = [
    "encoder-epoch-20-avg-10.onnx",
    "decoder-epoch-20-avg-10.onnx",
    "joiner-epoch-20-avg-10.onnx",
    "bpe.model",
    "config.json",
]

# SHA-256 từ assets release `stt-zipformer-v1`, đối chiếu cùng file tại
# HF_REPO@HF_REVISION. Model native sai một byte cũng không được nạp.
SHA256 = {
    "encoder-epoch-20-avg-10.onnx": "b0daa9842a1f39d146e57d6e951edc8910ddd234cbb00e9b5015a5280a5ba221",
    "decoder-epoch-20-avg-10.onnx": "cf2aa385b82c9d5d40cd29c3188af52d0249b3b78f0d4b7eb84ad502d50c7e7f",
    "joiner-epoch-20-avg-10.onnx": "d861afe55f7ff43c90069cad0a5d07261a408be5c7fd2aac8c84b1f3225da021",
    "bpe.model": "002894e7a82d80ffa5e25008ec8c5496159db804005e2103de96b01b4c13d445",
    "config.json": "ca8171f8bbd516c050b627582f2125c8f5f1f6ed967ab41b0fa9aae2cf61b492",
}

DEST = Path(__file__).resolve().parents[1] / "data" / "stt"


def _has_gh() -> bool:
    return shutil.which("gh") is not None


def _download_release(dest: Path) -> int:
    if not _has_gh():
        print("Chua co GitHub CLI (gh). Cai gh roi `gh auth login`, "
              "hoac dung --hf de tai tu HuggingFace.", file=sys.stderr)
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    ok = 0
    for name in FILES:
        target = dest / name
        if is_verified(target, SHA256[name]):
            print(f"[bo qua] {name} (da co, SHA-256 dung)")
            ok += 1
            continue
        print(f"[tai] {name} ...")
        with tempfile.TemporaryDirectory(prefix="stt-release-") as raw_tmp:
            tmp_dir = Path(raw_tmp)
            proc = subprocess.run(
                ["gh", "release", "download", TAG, "-R", REPO,
                 "-p", name, "-D", str(tmp_dir), "--clobber"],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                print(f"    LOI: {proc.stderr.strip()[:200]}", file=sys.stderr)
                continue
            try:
                replace_verified(tmp_dir / name, target, SHA256[name])
            except (IntegrityError, OSError) as exc:
                print(f"    LOI TOAN VEN: {exc}", file=sys.stderr)
                continue
            ok += 1
    return 0 if ok == len(FILES) else 2


def _download_hf(dest: Path) -> int:
    """Nguon goc model — public, khong can token."""
    dest.mkdir(parents=True, exist_ok=True)
    ok = 0
    for name in FILES:
        target = dest / name
        if is_verified(target, SHA256[name]):
            print(f"[bo qua] {name} (da co, SHA-256 dung)")
            ok += 1
            continue
        url = (
            f"https://huggingface.co/{HF_REPO}/resolve/"
            f"{HF_REVISION}/{name}?download=true"
        )
        print(f"[tai] {name} <- HuggingFace ...")
        try:
            download_verified(url, target, SHA256[name])
            ok += 1
        except Exception as exc:
            print(f"    LOI: {str(exc)[:200]}", file=sys.stderr)
    return 0 if ok == len(FILES) else 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Tai model STT Zipformer tieng Viet")
    ap.add_argument("--hf", action="store_true",
                    help="Tai tu HuggingFace thay vi GitHub Release")
    ap.add_argument("--list", action="store_true", help="Chi liet ke file can tai")
    ap.add_argument("--dest", default=str(DEST), help="Thu muc dich (mac dinh data/stt)")
    args = ap.parse_args()

    dest = Path(args.dest)
    if args.list:
        print(f"Model: {HF_REPO}")
        print(f"Revision: {HF_REVISION}")
        print(f"Release: {REPO} @ {TAG}")
        print(f"Dich: {dest}")
        for name in FILES:
            path = dest / name
            mark = "co+dung" if is_verified(path, SHA256[name]) else (
                "SAI-HASH" if path.is_file() else "chua"
            )
            print(f"  [{mark}] {name}")
        return 0

    rc = _download_hf(dest) if args.hf else _download_release(dest)
    if rc == 0:
        total = sum((dest / n).stat().st_size for n in FILES if (dest / n).is_file())
        print(f"\nXong: {dest} ({total / 1048576:.0f} MB)")
        print("Bat STT trong Settings (voice.stt.backend = local hoac auto).")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
