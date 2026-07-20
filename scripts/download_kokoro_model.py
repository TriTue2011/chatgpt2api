#!/usr/bin/env python3
"""Tải model TTS tiếng Anh Kokoro-82M (kokoro-en-v0_19) về data/kokoro/.

Gói do k2-fsa đóng sẵn cho sherpa-onnx: model.onnx + voices.bin (11 giọng) +
tokens.txt + espeak-ng-data/. Chạy CPU nhanh hơn real-time, chất lượng đứng
đầu nhóm TTS mở cỡ nhỏ. Cùng nguyên tắc: code trong image, model ngoài volume.

    python scripts/download_kokoro_model.py           # tải + giải nén (~305 MB)
    python scripts/download_kokoro_model.py --check   # chỉ kiểm tra

Chọn giọng trong WebUI: id dạng "kokoro:af_sky", "kokoro:bm_george"…
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# TỰ ĐỘNG theo CPU: có AVX512-VNNI / AVX-VNNI → int8 (nhỏ 3x, nhanh hơn);
# CPU cũ/VM chỉ AVX2 (vd Xeon E5 v4) → fp32 vì int8 KHÔNG có VNNI chạy chậm
# ~2.5x. Engine (kokoro_model_file) tự nhận model.onnx hoặc model.int8.onnx nên
# runtime không cần biết ta tải bản nào. Ép tay: --int8 / --fp32.
DEST = Path(__file__).resolve().parents[1] / "data" / "kokoro"


def _has_vnni() -> bool:
    """CPU có lệnh nhân int8 chuyên dụng (VNNI) không — quyết định int8 vs fp32."""
    try:
        info = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
        return ("avx512_vnni" in info) or ("avx_vnni" in info)
    except Exception:
        return False   # không đọc được (Windows/mac) → chọn fp32 cho an toàn


def _variant(force_int8: bool, force_fp32: bool) -> tuple[str, str]:
    """→ (NAME gói, tên file model). Ưu tiên cờ ép, còn lại theo VNNI."""
    use_int8 = force_int8 or (not force_fp32 and _has_vnni())
    if use_int8:
        return "kokoro-int8-en-v0_19", "model.int8.onnx"
    return "kokoro-en-v0_19", "model.onnx"


def _check(model_file: str) -> bool:
    ok = True
    for name in [model_file, "voices.bin", "tokens.txt", "espeak-ng-data"]:
        have = (DEST / name).exists()
        ok = ok and have
        print(f"[{'co' if have else 'THIEU'}] {DEST / name}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra")
    ap.add_argument("--int8", action="store_true", help="ép tải bản int8 (CPU có VNNI)")
    ap.add_argument("--fp32", action="store_true", help="ép tải bản fp32")
    args = ap.parse_args()

    name, model_file = _variant(args.int8, args.fp32)
    print(f"CPU VNNI: {'CO' if _has_vnni() else 'khong'} -> chon goi: {name} ({model_file})")

    if args.check:
        return 0 if _check(model_file) else 1
    if _check(model_file):
        print("Model da du — khong tai lai.")
        return 0

    # Đổi bản → dọn model .onnx cũ để không lẫn fp32/int8.
    for old in DEST.glob("model*.onnx"):
        old.unlink()
    url = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
           f"tts-models/{name}.tar.bz2")
    print(f"[tai] {url}\n      (~100–320 MB — có thể mất vài phút)")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "kokoro.tar.bz2"
        urllib.request.urlretrieve(url, tmp)
        print("[giai nen] ...")
        with tarfile.open(tmp, "r:bz2") as tar:
            tar.extractall(td, filter="data")
        src = Path(td) / name          # gói có 1 thư mục gốc cùng tên
        if not src.is_dir():
            print(f"[LOI] khong thay thu muc {name} trong goi", file=sys.stderr)
            return 1
        DEST.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            target = DEST / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(item), str(target))
            print(f"[ok] {item.name}")
    return 0 if _check(model_file) else 1


if __name__ == "__main__":
    sys.exit(main())
