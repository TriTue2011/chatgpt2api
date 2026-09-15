#!/usr/bin/env python3
"""Tải ZeroTTS (zeroweight-ai/ZeroTTS, MIT) về data/zerotts/ — KHÔNG nằm trong image.

Cả gói ~900 MB (3 graph ONNX fp32 + codec MOSS + 8 giọng dựng sẵn), tải một lần.

    python scripts/download_zerotts.py            # tải (bỏ qua file đã có)
    python scripts/download_zerotts.py --check    # chỉ kiểm tra

Chạy trong container:
    docker exec -it c2a /app/.venv/bin/python scripts/download_zerotts.py

Chọn giọng trong WebUI: id dạng "zerotts:maichi" (maichi, baotrang, kimoanh,
hamy, giahuy, huuduc, quangminh, tiendat).

Lấy đúng bộ file mà chính gói `zerotts` tải (`zerotts.hub._ALLOW_PATTERNS`),
nên không kéo `voice.bin` — bản trùng chỉ dành cho demo trình duyệt.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = Path(os.environ.get("ZEROTTS_DIR") or ROOT / "data" / "zerotts")
REPO = "zeroweight-ai/ZeroTTS"
BAT_BUOC = ("config.json", "tokenizer.json", "null_voice_emb.npy", "onnx/text_encoder.onnx",
            "onnx/prefix_step.onnx", "onnx/local_frame_decode.onnx", "voices/index.json")


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
    try:
        from zerotts import hub
        mau = list(hub._ALLOW_PATTERNS)
    except Exception:
        print("Chưa có gói zerotts — cần image mới (deploy/extra-requirements.txt).", file=sys.stderr)
        return 1
    from huggingface_hub import snapshot_download

    DEST.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=REPO, revision=hub.DEFAULT_REVISION, allow_patterns=mau,
                      local_dir=DEST)
    tong = sum(p.stat().st_size for p in DEST.rglob("*") if p.is_file()) / 1e6
    print(f"\nĐã tải ~{tong:.0f} MB.")
    return 0 if _kiem() else 1


if __name__ == "__main__":
    sys.exit(main())
