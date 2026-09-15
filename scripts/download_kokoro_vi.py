#!/usr/bin/env python3
"""Tải Kokoro tiếng Việt (contextboxai/Kokoro-Vietnamese) về data/kokoro-vi/ — KHÔNG nằm trong image.

Cùng nguyên tắc Piper/NghiTTS/VieNeu: code trong image, model ngoài volume.
Model chung ~326 MB + mỗi giọng một voicepack ~0,5 MB.

    python scripts/download_kokoro_vi.py                    # model + giọng mặc định (hung_thinh)
    python scripts/download_kokoro_vi.py mai_linh manh_dung # thêm vài giọng
    python scripts/download_kokoro_vi.py --all              # cả 14 giọng
    python scripts/download_kokoro_vi.py --list             # xem danh mục
    python scripts/download_kokoro_vi.py --check            # chỉ kiểm tra

Chạy trong container:
    docker exec -it c2a /app/.venv/bin/python scripts/download_kokoro_vi.py --all

Chọn giọng trong WebUI: id dạng "kokorovi:hung_thinh".

Voicepack gốc là file `.pt` của torch. Image KHÔNG có torch, nên lúc tải script
đổi luôn sang `voices/<mã>.npy` (đọc bằng `kokoro_vi.doc_voicepack_pt`, không
cần torch) — engine chỉ đọc bản .npy.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = Path(os.environ.get("KOKORO_VI_DIR") or ROOT / "data" / "kokoro-vi")

# Nạp THẲNG file danh mục, không qua `from services.voice import ...` (import cả
# gói kéo theo services.config và đòi CHATGPT2API_AUTH_KEY) — cùng nếp
# download_nghitts_voices.py.
_spec = importlib.util.spec_from_file_location(
    "kokoro_vi", ROOT / "services" / "voice" / "kokoro_vi.py")
kv = importlib.util.module_from_spec(_spec)          # type: ignore[arg-type]
sys.modules["kokoro_vi"] = kv
_spec.loader.exec_module(kv)                          # type: ignore[union-attr]


def _tai(ten: str, noi: Path) -> Path:
    # local_dir: ghi thẳng vào thư mục đích, KHÔNG để thêm một bản trong cache
    # Hugging Face — đĩa máy chủ chật, model 326 MB mà nằm hai nơi là phí.
    from huggingface_hub import hf_hub_download
    return Path(hf_hub_download(kv.REPO, ten, local_dir=noi))


def _kiem(ids: list[str]) -> bool:
    du = True
    for ten in (kv.MODEL_FILE, kv.CONFIG_FILE):
        co = (DEST / ten).is_file()
        du = du and co
        print(f"[{'co' if co else 'THIEU'}] {ten}")
    for vid in ids:
        co = (DEST / kv.get(vid).npy_file).is_file()
        du = du and co
        print(f"[{'co' if co else 'THIEU'}] giọng {vid}")
    return du


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("giong", nargs="*", help="mã giọng (mặc định: hung_thinh)")
    ap.add_argument("--all", action="store_true", help="tải cả 14 giọng")
    ap.add_argument("--list", action="store_true", help="liệt kê danh mục")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra, không tải")
    args = ap.parse_args()

    if args.list:
        for v in kv.VOICES:
            co = (DEST / v.npy_file).is_file()
            print(f"{'✓' if co else ' '} kokorovi:{v.id:12} {v.name}")
        return 0
    ids = [v.id for v in kv.VOICES] if args.all else (args.giong or [kv.DEFAULT_ID])
    la = [i for i in ids if kv.get(i) is None]
    if la:
        print(f"Mã giọng không có trong danh mục: {', '.join(la)} (xem --list)", file=sys.stderr)
        return 2
    print(f"Thư mục: {DEST}")
    if args.check:
        return 0 if _kiem(ids) else 1

    import tempfile

    import numpy as np

    DEST.mkdir(parents=True, exist_ok=True)
    for ten in (kv.MODEL_FILE, kv.CONFIG_FILE):
        if (DEST / ten).is_file():
            print(f"[da co] {ten}")
            continue
        _tai(ten, DEST)
        print(f"[ok] {ten} ({(DEST / ten).stat().st_size / 1e6:.1f} MB)")

    (DEST / kv.VOICE_DIR).mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DEST) as tam:
        for vid in ids:
            v = kv.get(vid)
            dich = DEST / v.npy_file
            if dich.is_file():
                print(f"[da co] giọng {vid}")
                continue
            mang = kv.doc_voicepack_pt(_tai(v.hf_file, Path(tam)).read_bytes())
            tmp = dich.with_name(dich.stem + ".tmp.npy")
            np.save(tmp, mang)
            os.replace(tmp, dich)
            print(f"[ok] giọng {vid} → {v.npy_file} {tuple(mang.shape)}")
    print("\nXong. Chọn giọng trong Cài đặt → Giọng nói & Loa: kokorovi:<mã>.")
    return 0 if _kiem(ids) else 1


if __name__ == "__main__":
    sys.exit(main())
