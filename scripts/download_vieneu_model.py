#!/usr/bin/env python3
"""Tải model VieNeu-TTS v3 Turbo (ONNX) về volume data/hf — KHÔNG nằm trong image.

Cùng nguyên tắc với Piper/STT: code trong image, model ngoài volume. Cache theo
layout chuẩn HuggingFace nên engine vieneu tự thấy (HF_HOME=data/hf).

    python scripts/download_vieneu_model.py            # TỰ ĐỘNG theo CPU (VNNI)
    python scripts/download_vieneu_model.py --int8     # ép int8 (cần AVX-VNNI)
    python scripts/download_vieneu_model.py --fp32     # ép fp32 (Xeon E5 / không VNNI)
    python scripts/download_vieneu_model.py --clone    # kèm speaker_encoder (clone giọng)
    python scripts/download_vieneu_model.py --check    # chỉ kiểm tra, không tải

Auto: CPU có AVX512-VNNI/AVX-VNNI → int8 (nhanh); CPU chỉ AVX2 (Xeon E5 v3/v4…)
→ fp32 vì int8 thiếu VNNI chạy stream **chậm hơn ~2.5×**. Runtime
`services.voice.config.vieneu_precision()` cùng logic.

Cần gói huggingface_hub (có sẵn trong image; ngoài image: pip install huggingface_hub).
Chạy trong container:  docker exec -it chatgpt2api \
    /app/.venv/bin/python scripts/download_vieneu_model.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
# HF_HOME phải đặt TRƯỚC khi import huggingface_hub (đọc env lúc import).
os.environ.setdefault("HF_HOME", str(BASE / "data" / "hf"))

BACKBONE = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
CODEC = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"


def _has_vnni() -> bool:
    """CPU có lệnh nhân int8 chuyên dụng (VNNI) không."""
    try:
        info = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").lower()
        return ("avx512_vnni" in info) or ("avx_vnni" in info)
    except Exception:
        return False


def _pick_subfolder(force_int8: bool, force_fp32: bool) -> str:
    if force_fp32 and not force_int8:
        return "onnx_update"
    if force_int8 and not force_fp32:
        return "onnx_int8"
    return "onnx_int8" if _has_vnni() else "onnx_update"

# Danh sách file khớp _GRAPH_FILES/_CODEC_FILES trong vieneu (onnx_runtime_lite).
GRAPH_FILES = [
    "vieneu_prefill.onnx", "vieneu_decode_step.onnx",
    "vieneu_acoustic_cached.onnx", "vieneu_backbone_shared.data",
    "vieneu_v3_heads.npz", "config.json", "tokenizer.json",
]
CODEC_FILES = [
    "moss_audio_tokenizer_decode_full.onnx",
    "moss_audio_tokenizer_decode_shared.data",
    "moss_audio_tokenizer_decode_step.onnx",
    "codec_browser_onnx_meta.json",
    "moss_audio_tokenizer_encode.onnx",
    "moss_audio_tokenizer_encode.data",
]
ROOT_FILES = ["config.json"]              # engine đọc config.json ở gốc repo
OPTIONAL_ROOT = ["denoiser.onnx"]         # lọc ồn clip tham chiếu (không bắt buộc)
CLONE_FILES = ["speaker_encoder.onnx"]    # chỉ cần khi clone giọng (--clone)


def _fetch(repo: str, files: list[str], subfolder: str | None,
           optional: bool = False) -> int:
    from huggingface_hub import hf_hub_download
    ok = 0
    for name in files:
        label = f"{subfolder}/{name}" if subfolder else name
        try:
            path = hf_hub_download(repo, name, subfolder=subfolder or None)
            size = Path(path).stat().st_size / 1e6
            print(f"[ok] {repo} :: {label}  ({size:.1f} MB)")
            ok += 1
        except Exception as exc:
            if optional:
                print(f"[bo qua] {repo} :: {label} — {str(exc)[:100]}")
            else:
                print(f"[LOI] {repo} :: {label} — {str(exc)[:200]}", file=sys.stderr)
    return ok


def _check(subfolder: str) -> bool:
    hub = Path(os.environ["HF_HOME"]) / "hub"

    def has(repo: str, rel: str) -> bool:
        root = hub / ("models--" + repo.replace("/", "--")) / "snapshots"
        return any(root.glob(f"*/{rel}"))

    rows = [(BACKBONE, f"{subfolder}/{f}") for f in GRAPH_FILES]
    rows += [(CODEC, f) for f in CODEC_FILES]
    all_ok = True
    for repo, rel in rows:
        ok = has(repo, rel)
        all_ok = all_ok and ok
        print(f"[{'co' if ok else 'THIEU'}] {repo} :: {rel}")
    return all_ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--int8", action="store_true",
                    help="ép tải bản int8 (onnx_int8) — cần CPU VNNI để nhanh")
    ap.add_argument("--fp32", action="store_true",
                    help="ép tải bản fp32 (onnx_update) — Xeon E5 / không VNNI")
    ap.add_argument("--clone", action="store_true",
                    help="tải thêm speaker_encoder.onnx cho voice cloning")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra cache")
    args = ap.parse_args()

    subfolder = _pick_subfolder(args.int8, args.fp32)
    vnni = _has_vnni()
    print(f"HF_HOME = {os.environ['HF_HOME']}")
    print(f"CPU VNNI: {'CO' if vnni else 'khong'} -> chon {subfolder}"
          f" ({'int8' if subfolder == 'onnx_int8' else 'fp32'})")
    if args.check:
        return 0 if _check(subfolder) else 1

    need = len(GRAPH_FILES) + len(CODEC_FILES) + len(ROOT_FILES)
    got = _fetch(BACKBONE, GRAPH_FILES, subfolder)
    got += _fetch(CODEC, CODEC_FILES, None)
    got += _fetch(BACKBONE, ROOT_FILES, None)
    _fetch(BACKBONE, OPTIONAL_ROOT, None, optional=True)
    if args.clone:
        _fetch(BACKBONE, CLONE_FILES, None)

    if got < need:
        print(f"\nThieu {need - got}/{need} file — xem loi o tren.", file=sys.stderr)
        return 1
    print(f"\nXong: {got}/{need} file bat buoc da co trong cache.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
