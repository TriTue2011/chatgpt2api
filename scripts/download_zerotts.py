#!/usr/bin/env python3
"""Tải ZeroTTS (zeroweight-ai/ZeroTTS, MIT) về data/zerotts/ — KHÔNG nằm trong image.

Cả gói ~900 MB (3 graph ONNX fp32 + codec MOSS + 8 giọng dựng sẵn), tải một lần.

    python scripts/download_zerotts.py            # tải (bỏ qua file đã có)
    python scripts/download_zerotts.py --check    # chỉ kiểm tra
    python scripts/download_zerotts.py --int8     # tạo thêm bản int8 cho máy yếu

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
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = Path(os.environ.get("ZEROTTS_DIR") or ROOT / "data" / "zerotts")
REPO = "zeroweight-ai/ZeroTTS"
# GHIM đúng commit trọng số đã đo thanh điệu 15/09/2026 (0/1409 âm tiết sai thanh).
# Không dùng mặc định của gói: zerotts 0.1.4 ghim một commit cũ, 0.1.5 tải `main`
# — mà chính tác giả ghi `main` từng đổi graph làm hỏng ngược runtime đã phát hành.
REVISION = "c2bfbd67dc648cac455077333f7cf5c18a2e3bb4"
BAT_BUOC = ("config.json", "tokenizer.json", "null_voice_emb.npy", "onnx/text_encoder.onnx",
            "onnx/prefix_step.onnx", "onnx/local_frame_decode.onnx", "voices/index.json")


def _kiem() -> bool:
    du = True
    for ten in BAT_BUOC:
        co = (DEST / ten).is_file()
        du = du and co
        print(f"[{'co' if co else 'THIEU'}] {ten}")
    return du


DEST_INT8 = DEST.parent / "zerotts-int8"
#: Ba graph chạy mỗi khung. Codec giải mã giữ fp32 — không nằm trên đường nóng.
GRAPH_INT8 = ("text_encoder.onnx", "prefix_step.onnx", "local_frame_decode.onnx")


def _int8() -> int:
    """Lượng tử hoá động MatMul sang int8, theo tools/quantize_onnx_int8.py của ZeroTTS.

    Bẫy tác giả ghi lại: quantize thẳng chỉ bắt 41/561 MatMul của
    local_frame_decode vì trọng số đi qua nút Identity. Cho ORT gộp graph trước
    (ORT_ENABLE_BASIC) rồi mới quantize — ra 425 MatMulInteger.
    """
    import onnxruntime as ort
    from onnxruntime.quantization import QuantType, quantize_dynamic

    if not _kiem():
        print("Chưa có bản fp32 — chạy script không cờ trước.", file=sys.stderr)
        return 1
    tam = DEST_INT8.with_name(DEST_INT8.name + ".tam")
    shutil.rmtree(tam, ignore_errors=True)
    shutil.copytree(DEST, tam, ignore=shutil.ignore_patterns(".cache", *GRAPH_INT8))
    for ten in GRAPH_INT8:
        gop = tam / "onnx" / (ten + ".gop")
        tuy = ort.SessionOptions()
        tuy.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        tuy.optimized_model_filepath = str(gop)
        tuy.intra_op_num_threads = 1
        ort.InferenceSession(str(DEST / "onnx" / ten), tuy, providers=["CPUExecutionProvider"])
        quantize_dynamic(str(gop), str(tam / "onnx" / ten),
                         weight_type=QuantType.QInt8, op_types_to_quantize=["MatMul"])
        gop.unlink(missing_ok=True)
        print(f"int8 {ten}: {(tam / 'onnx' / ten).stat().st_size / 1e6:.0f} MB")
    # Thư mục chỉ xuất hiện khi ĐỦ file — engine không bao giờ nạp bản dở dang.
    shutil.rmtree(DEST_INT8, ignore_errors=True)
    tam.rename(DEST_INT8)
    print(f"Đã tạo {DEST_INT8}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra, không tải")
    ap.add_argument("--int8", action="store_true",
                    help="tạo bản int8 từ bản fp32 đã tải (máy không đọc kịp thời gian thực)")
    args = ap.parse_args()
    print(f"Thư mục: {DEST}")
    if args.check:
        return 0 if _kiem() else 1
    if args.int8:
        return _int8()
    try:
        from zerotts import hub
        mau = list(hub._ALLOW_PATTERNS)
    except Exception:
        print("Chưa có gói zerotts — cần image mới (deploy/extra-requirements.txt).", file=sys.stderr)
        return 1
    from huggingface_hub import snapshot_download

    DEST.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=REPO, revision=REVISION, allow_patterns=mau, local_dir=DEST)
    tong = sum(p.stat().st_size for p in DEST.rglob("*") if p.is_file()) / 1e6
    print(f"\nĐã tải ~{tong:.0f} MB.")
    return 0 if _kiem() else 1


if __name__ == "__main__":
    sys.exit(main())
