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
import urllib.request
from pathlib import Path

REPO = os.environ.get("C2A_REPO", "TriTue2011/chatgpt2api")
TAG = "stt-zipformer-v1"
HF_REPO = "hynt/Zipformer-30M-RNNT-6000h"

FILES = [
    "encoder-epoch-20-avg-10.onnx",
    "decoder-epoch-20-avg-10.onnx",
    "joiner-epoch-20-avg-10.onnx",
    "bpe.model",
    "config.json",
]

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
        if target.is_file() and target.stat().st_size > 0:
            print(f"[bo qua] {name} (da co)")
            ok += 1
            continue
        print(f"[tai] {name} ...")
        proc = subprocess.run(
            ["gh", "release", "download", TAG, "-R", REPO,
             "-p", name, "-D", str(dest), "--clobber"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            print(f"    LOI: {proc.stderr.strip()[:200]}", file=sys.stderr)
            continue
        ok += 1
    return 0 if ok == len(FILES) else 2


def _download_hf(dest: Path) -> int:
    """Nguon goc model — public, khong can token."""
    dest.mkdir(parents=True, exist_ok=True)
    ok = 0
    for name in FILES:
        target = dest / name
        if target.is_file() and target.stat().st_size > 0:
            print(f"[bo qua] {name} (da co)")
            ok += 1
            continue
        url = f"https://huggingface.co/{HF_REPO}/resolve/main/{name}?download=true"
        print(f"[tai] {name} <- HuggingFace ...")
        try:
            with urllib.request.urlopen(url, timeout=600) as resp, \
                    open(target, "wb") as out:
                shutil.copyfileobj(resp, out)
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
        print(f"Release: {REPO} @ {TAG}")
        print(f"Dich: {dest}")
        for name in FILES:
            mark = "co" if (dest / name).is_file() else "chua"
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
