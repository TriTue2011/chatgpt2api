#!/usr/bin/env python3
"""Tải model TTS Trung / Nhật+Hàn cho tính năng phiên dịch đàm thoại.

Khảo sát 14/08 (kho model chính chủ k2-fsa/sherpa-onnx, URL đã kiểm chứng):

    zh     kokoro-int8-multi-lang-v1_1 (140MB) — CÙNG engine Kokoro đang đọc
           tiếng Anh; 100 giọng Trung thu âm chuyên nghiệp + 3 giọng Anh,
           24kHz, Apache-2.0. (Kokoro không đọc được ja/ko: thiếu G2P —
           issue sherpa-onnx#3766 còn mở.)
    ja+ko  supertonic-3 int8 (123MB) — MỘT model 31 ngôn ngữ của Supertone,
           44,1kHz, OpenRAIL; sherpa-onnx ≥1.13.2 hỗ trợ (bản ghim 1.13.4
           dùng được). Không cần espeak-ng-data hay lexicon.

Khác script STT (chỉ nhặt vài file), TTS cần NGUYÊN cây gói (espeak-ng-data/,
dict/, lexicon, FST…) nên giải nén toàn bộ, bỏ thư mục gốc của gói.

    python scripts/download_tts_da_ngu.py            # tải cả hai
    python scripts/download_tts_da_ngu.py zh         # chỉ tiếng Trung
    python scripts/download_tts_da_ngu.py --check    # chỉ kiểm tra
"""

from __future__ import annotations

import argparse
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

GOC = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models"
GOI = {
    "zh": ("kokoro-int8-multi-lang-v1_1", "kokoro-zh", "voices.bin", "~140 MB"),
    "ja-ko": ("sherpa-onnx-supertonic-3-tts-int8-2026-05-11", "supertonic",
              "tts.json", "~123 MB"),
}
DATA = Path(__file__).resolve().parents[1] / "data"


def _check(khoa: str) -> bool:
    _, thu_muc, dau_hieu, _ = GOI[khoa]
    d = DATA / thu_muc
    ok = (d / dau_hieu).is_file() and bool(list(d.glob("*.onnx")))
    print(f"[{'co' if ok else 'THIEU'}] {khoa}: {d}")
    return ok


def _tai(khoa: str) -> bool:
    ten, thu_muc, _, co = GOI[khoa]
    url = f"{GOC}/{ten}.tar.bz2"
    dest = DATA / thu_muc
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[tai] {url}\n      ({co} — có thể mất vài phút)")
    with tempfile.NamedTemporaryFile(suffix=".tar.bz2", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        urllib.request.urlretrieve(url, tmp_path)
        print("[giai nen] ...")
        with tarfile.open(tmp_path, "r:bz2") as tar:
            for m in tar.getmembers():
                # Bỏ thư mục gốc "<tên gói>/" — giữ cấu trúc con nguyên vẹn.
                phan = Path(m.name).parts
                if len(phan) < 2:
                    continue
                dich = dest.joinpath(*phan[1:])
                if not str(dich.resolve()).startswith(str(dest.resolve())):
                    continue   # chặn đường dẫn thoát ra ngoài (tar bẩn)
                if m.isdir():
                    dich.mkdir(parents=True, exist_ok=True)
                elif m.isfile():
                    src = tar.extractfile(m)
                    if src is None:
                        continue
                    dich.parent.mkdir(parents=True, exist_ok=True)
                    dich.write_bytes(src.read())
        print(f"[ok] {dest}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    return _check(khoa)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("goi", nargs="*", help="zh / ja-ko (bỏ trống = cả hai)")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra")
    args = ap.parse_args()
    chon = [x for x in (args.goi or list(GOI)) if x in GOI]
    if not chon:
        print("Không có gói hợp lệ (chọn: zh, ja-ko)")
        return 1
    if args.check:
        return 0 if all(_check(x) for x in chon) else 1
    ok = True
    for khoa in chon:
        if _check(khoa):
            print(f"[{khoa}] đã đủ — không tải lại.")
            continue
        ok = _tai(khoa) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
