"""Chạy graph ONNX trên GPU nhà (máy NVR, mục /onnx của fw-tach-am), lùi về CPU tại chỗ.

Chủ máy 24/09/2026 chốt đưa nhận khuôn mặt và TTS lên GPU. Chỉ bước ``run``
đi qua mạng: tiền/hậu xử lý vẫn ở đây và phiên CPU tại chỗ vẫn nạp sẵn, nên
đầu ra giống hệt chạy CPU (sổ mặt không phải tính lại) và GPU hỏng thì đọc/nhận
tiếp ngay bằng CPU — không bao giờ câm.

GPU hỏng thì NGHỈ ``NGHI_GIAY`` rồi mới thử lại, và BÁO admin — bài học
24/09/2026: fw-nghe mất GPU từ 15/09, gateway lặng lẽ lùi về CPU suốt 8 ngày
mà không ai biết.

Danh mục graph phải khớp ``ONNX_GRAPH`` trong ``fw-tach-am/app.py``.
"""
from __future__ import annotations

import io
import os
import threading
import time
from typing import Any

from utils.log import logger

#: Graph máy GPU chạy được (tên = tên tệp bỏ ".onnx").
TREN_GPU = frozenset({"det_10g", "w600k_r50", "kokoro_vi"})
NGHI_GIAY = 60.0
_BAO_CACH_GIAY = 1800.0
_HET_GIO = {"det_10g": 10.0, "w600k_r50": 5.0, "kokoro_vi": 30.0}

_khoa = threading.Lock()
_nghi_toi = 0.0
_bao_luc = 0.0


def _dia_chi() -> tuple[str, str]:
    """(URL, token) của máy GPU; rỗng = không dùng GPU."""
    if os.getenv("ONNX_GPU", "1").strip() == "0":
        return "", ""
    url = os.getenv("TACH_AM_URL_GPU", "").strip().rstrip("/")
    token = os.getenv("TACH_AM_API_TOKEN", "").strip()
    return (url, token) if url and token else ("", "")


def _hong(ten: str, exc: Exception) -> None:
    global _nghi_toi, _bao_luc
    bay_gio = time.monotonic()
    with _khoa:
        _nghi_toi = bay_gio + NGHI_GIAY
        bao = bay_gio - _bao_luc >= _BAO_CACH_GIAY
        if bao:
            _bao_luc = bay_gio
    logger.warning({"event": "onnx_gpu_hong", "graph": ten, "loi": str(exc)[:200]})
    if bao:
        try:
            from services.notifier import notify_admin

            notify_admin(f"⚠️ GPU nhà lỗi khi chạy {ten}: {str(exc)[:160]} — "
                         "nhận mặt/TTS đang chạy CPU tại chỗ.", category="system")
        except Exception as loi:  # noqa: BLE001 — báo hỏng không được làm hỏng việc chính
            logger.warning({"event": "onnx_gpu_bao_loi", "loi": str(loi)[:120]})


class PhienLai:
    """Giống ``onnxruntime.InferenceSession`` ở ba chỗ dùng: get_inputs, get_outputs, run."""

    def __init__(self, ten: str, tai_cho: Any) -> None:
        self.ten = ten
        self._tai_cho = tai_cho
        self._ten_ra = [o.name for o in tai_cho.get_outputs()]

    def get_inputs(self):
        return self._tai_cho.get_inputs()

    def get_outputs(self):
        return self._tai_cho.get_outputs()

    def run(self, output_names, feeds):
        url, token = _dia_chi()
        if url and time.monotonic() >= _nghi_toi:
            try:
                return self._chay_gpu(url, token, output_names, feeds)
            except Exception as exc:  # noqa: BLE001 — mọi lỗi mạng/GPU đều lùi về CPU
                _hong(self.ten, exc)
        return self._tai_cho.run(output_names, feeds)

    def _chay_gpu(self, url: str, token: str, output_names, feeds) -> list:
        import numpy as np
        import requests

        buf = io.BytesIO()
        np.savez(buf, **{k: np.asarray(v) for k, v in feeds.items()})
        r = requests.post(f"{url}/onnx/{self.ten}/chay", data=buf.getvalue(),
                          headers={"x-api-key": token}, timeout=_HET_GIO.get(self.ten, 10.0))
        r.raise_for_status()
        with np.load(io.BytesIO(r.content), allow_pickle=False) as npz:
            ra = [npz[f"o{i}"] for i in range(len(self._ten_ra))]
        if output_names is None:
            return ra
        return [ra[self._ten_ra.index(n)] for n in output_names]


def lai(ten: str, tai_cho: Any) -> Any:
    """Bọc phiên CPU thành phiên lai nếu máy GPU chạy được graph này."""
    return PhienLai(ten, tai_cho) if ten in TREN_GPU else tai_cho
