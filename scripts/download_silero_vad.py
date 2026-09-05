#!/usr/bin/env python3
"""Tải model Silero VAD về data/vad/ — KHÔNG nằm trong image.

Cùng nguyên tắc với model STT/TTS: code ở trong image, model ở ngoài volume.
File chỉ 629 KB nên nhẹ hơn hẳn các model khác, nhưng vẫn để ngoài cho nhất
quán và để thay model không phải build lại image.

    python scripts/download_silero_vad.py

Không có model thì phần nghe tự lùi về cắt đoạn theo năng lượng như trước —
đây là tính năng cộng thêm, không phải điều kiện để chạy.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from scripts.model_download import IntegrityError, download_verified, is_verified
except ModuleNotFoundError:  # chạy trực tiếp `python scripts/...py`
    from model_download import IntegrityError, download_verified, is_verified

# Lấy từ release `asr-models` của k2-fsa/sherpa-onnx — CÙNG nguồn với thư viện
# đọc nó, nên không lệch phiên bản đồ hình. Bản gốc ở snakers4/silero-vad có
# cùng tên nhưng nặng gấp bốn và không được sherpa-onnx bảo đảm tương thích.
URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
TEN = "silero_vad.onnx"
# Đối chiếu ngày 05/09/2026. Model native sai một byte cũng không được nạp.
SHA256 = "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"

DEST = Path(__file__).resolve().parents[1] / "data" / "vad"


def main() -> int:
    dich = DEST / TEN
    if is_verified(dich, SHA256):
        print(f"[bo qua] {TEN} (da co, SHA-256 dung)")
        return 0
    print(f"[tai] {TEN} ...")
    try:
        download_verified(URL, dich, SHA256)
    except (IntegrityError, OSError) as exc:
        print(f"    LOI: {exc}", file=sys.stderr)
        return 1
    print(f"[xong] {dich}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
