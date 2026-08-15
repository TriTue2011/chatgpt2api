#!/usr/bin/env python3
"""Tải model STT Trung / Nhật / Hàn (Zipformer transducer, k2-fsa) về data/stt-<lang>/.

**Đường CHÍNH bây giờ là SenseVoice, không phải ba model dưới đây.** Đo lại
15/08/2026 trên đúng 150 bản thu FLEURS mỗi tiếng (``scripts/kiem_nghe.py``):

    tiếng   ba Zipformer riêng              SenseVoice (một model)
    ko      55,5% sai ký tự · bỏ trắng 67   6,2% · bỏ trắng 0
    ja       9,8%                           7,0%
    zh      13,6%                          10,2%

Một model thay ba (tải 228 MB thay cho 1,3 GB; trên đĩa 229 MB so với 295 MB),
và tiếng Hàn hết cảnh bỏ trắng 45% số đoạn. Tải::

    python scripts/download_stt_da_ngu.py --sense       # đường chính
    python scripts/download_stt_da_ngu.py zh ja ko      # đường lui, xem dưới

Ba model Zipformer vẫn giữ làm ĐƯỜNG LUI: chưa tải SenseVoice thì code tự dùng
chúng, nên máy đang chạy không đứt khi nâng cấp.

Cùng dòng transducer với Zipformer tiếng Việt đang dùng — giữ nguyên hợp đồng
``ys_log_probs`` (độ tự tin, bộ dò ngôn ngữ đang dựa vào) + token timestamps
(khung phụ đề). Nguồn: kho model chính chủ k2-fsa/sherpa-onnx, license
Apache-2.0, đã đối chiếu CER công bố (khảo sát cộng đồng 14/08):

    zh  multi-zh-hans-2023-9-2       14k giờ, CER AiShell 3.04
    ja  reazonspeech-2024-08-01      35k giờ, CER JSUT 6.63 (int8) — hơn Whisper-v3
    ko  korean-2024-06-24            KsponSpeech, CER ~10.4

Gói nén chứa cả bản fp32 lẫn int8 — chỉ giữ int8 (nhanh hơn trên CPU, nhẹ đĩa;
riêng encoder fp32 tiếng Nhật đã 565 MB). Cùng nguyên tắc Piper/Zipformer:
code trong image, model ngoài volume.

    python scripts/download_stt_da_ngu.py zh ja ko    # tải các tiếng cần
    python scripts/download_stt_da_ngu.py --check     # chỉ kiểm tra
"""

from __future__ import annotations

import argparse
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

GOC = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
MODELS = {
    "zh": ("sherpa-onnx-zipformer-multi-zh-hans-2023-9-2", "~300 MB"),
    "ja": ("sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01", "~680 MB"),
    "ko": ("sherpa-onnx-zipformer-korean-2024-06-24", "~320 MB"),
}
DATA = Path(__file__).resolve().parents[1] / "data"

#: SenseVoice — GHIM bản 2024-07-17. Bản 2025-09-09 đọc SAI cả tệp mẫu của
#: chính nó với sherpa-onnx 1.13.4 (đo 15/08/2026): tiếng Nhật rụng sạch kana
#: chỉ còn chữ Hán giản thể, tiếng Hàn lẫn chữ Trung, và đo trên FLEURS ra 76%
#: sai ký tự. Đừng "nâng cấp" sang bản mới hơn mà không chạy lại kiem_nghe.py.
SENSE = ("sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17", "~228 MB")
SENSE_DEST = DATA / "stt-sense"


def _dest(lang: str) -> Path:
    return DATA / f"stt-{lang}"


def _check_sense() -> bool:
    ok = bool(list(SENSE_DEST.glob("model*.onnx"))) \
        and (SENSE_DEST / "tokens.txt").is_file()
    print(f"[{'co' if ok else 'THIEU'}] sense: {SENSE_DEST}")
    return ok


def _tai_sense() -> bool:
    ten, co = SENSE
    url = f"{GOC}/{ten}.tar.bz2"
    SENSE_DEST.mkdir(parents=True, exist_ok=True)
    print(f"[tai] {url}\n      ({co} — có thể mất vài phút)")
    with tempfile.NamedTemporaryFile(suffix=".tar.bz2", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        urllib.request.urlretrieve(url, tmp_path)
        print("[giai nen] ...")
        with tarfile.open(tmp_path, "r:bz2") as tar:
            for m in tar.getmembers():
                base = Path(m.name).name
                if not m.isfile() or "test_wavs" in m.name:
                    continue
                if base == "tokens.txt" or (base.startswith("model")
                                            and base.endswith(".onnx")):
                    src = tar.extractfile(m)
                    if src is not None:
                        (SENSE_DEST / base).write_bytes(src.read())
                        print(f"[ok] {base}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    return _check_sense()


def _check(lang: str) -> bool:
    d = _dest(lang)
    ok = bool(list(d.glob("encoder*.onnx"))) and (d / "tokens.txt").is_file() \
        and bool(list(d.glob("decoder*.onnx"))) and bool(list(d.glob("joiner*.onnx")))
    print(f"[{'co' if ok else 'THIEU'}] {lang}: {d}")
    return ok


def _tai(lang: str) -> bool:
    ten, co = MODELS[lang]
    url = f"{GOC}/{ten}.tar.bz2"
    dest = _dest(lang)
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[tai] {url}\n      ({co} — có thể mất vài phút)")
    with tempfile.NamedTemporaryFile(suffix=".tar.bz2", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        urllib.request.urlretrieve(url, tmp_path)
        print("[giai nen] ...")
        # Gom ứng viên theo bộ phận, ưu tiên int8; tokens.txt lấy nguyên.
        chon: dict[str, tarfile.TarInfo] = {}
        with tarfile.open(tmp_path, "r:bz2") as tar:
            for m in tar.getmembers():
                base = Path(m.name).name
                if not m.isfile() or "test_wavs" in m.name:
                    continue
                if base == "tokens.txt":
                    chon["tokens.txt"] = m
                    continue
                for phan in ("encoder", "decoder", "joiner"):
                    if base.startswith(phan) and base.endswith(".onnx"):
                        cu = chon.get(phan)
                        # int8 thắng fp32; đã có int8 thì thôi.
                        if cu is None or (".int8." in base
                                          and ".int8." not in Path(cu.name).name):
                            chon[phan] = m
            thieu = {"encoder", "decoder", "joiner", "tokens.txt"} - set(chon)
            if thieu:
                print(f"[LOI] gói {ten} thiếu: {thieu}")
                return False
            for m in chon.values():
                src = tar.extractfile(m)
                if src is None:
                    continue
                base = Path(m.name).name
                (dest / base).write_bytes(src.read())
                print(f"[ok] {base}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    return _check(lang)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("langs", nargs="*",
                    help="các tiếng cần tải: zh ja ko (bỏ trống = cả ba)")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra")
    ap.add_argument("--sense", action="store_true",
                    help="tải SenseVoice (đường CHÍNH cho zh/ja/ko)")
    args = ap.parse_args()
    if args.sense:
        if args.check:
            return 0 if _check_sense() else 1
        if _check_sense():
            print("[sense] model đã đủ — không tải lại.")
            return 0
        return 0 if _tai_sense() else 1
    langs = [x for x in (args.langs or list(MODELS)) if x in MODELS]
    if not langs:
        print("Không có tiếng hợp lệ (chọn: zh ja ko)")
        return 1
    if args.check:
        return 0 if all(_check(x) for x in langs) else 1
    ok = True
    for lang in langs:
        if _check(lang):
            print(f"[{lang}] model đã đủ — không tải lại.")
            continue
        ok = _tai(lang) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
