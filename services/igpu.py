"""Chạy graph ONNX trên iGPU Intel (OpenVINO) khi máy có, lùi về phiên CPU tại chỗ.

Chủ máy 27/09/2026: "nếu máy có igpu, không có gpu thì phải dùng được igpu". Thứ tự
chạy của nhận mặt: GPU nhà qua mạng (``onnx_xa``) → iGPU (ở đây) → CPU. Phiên CPU của
onnxruntime vẫn nạp sẵn và giữ vai "hồ sơ" của graph (tên vào/ra, metadata): chỉ bước
``run`` đổi chỗ chạy, tiền/hậu xử lý giữ nguyên.

Tính bằng f32 (không để GPU tự hạ xuống f16): vector mặt so với sổ đã tính trên CPU/CUDA
f32 — lệch độ chính xác là lệch điểm giống, phải tính lại cả sổ.

Cần ba thứ, thiếu thứ nào cũng chạy CPU như cũ: container thấy iGPU (compose ``devices:
[/dev/dri:/dev/dri]``), gói ``openvino`` trong venv, và driver OpenCL của Intel. **Image
chung CHƯA cài hai thứ sau** — chủ máy 27/09/2026 chọn chưa cài vì đo thật nặng ~0,8 GB mỗi
image (OpenVINO 179 MB + driver 628 MB: intel-igc-core-2 / intel-igc-opencl-2 v2.41.5,
intel-opencl-icd 26.35.39758.10, libigdgmm12 22.10.0 từ GitHub của Intel — Debian 13 không
còn đóng gói — cộng ``ocl-icd-libopencl1``). ``IGPU=0`` tắt hẳn.

Đo 27/09/2026 trên buffalo_l + yolo26s thật (OpenVINO thiết bị CPU thay iGPU): hộp mặt
trùng khớp, vector mặt cosine 1,000000 so với onnxruntime, YOLO cùng người cùng điểm.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

from utils.log import logger

#: Tên thiết bị OpenVINO: "GPU" là iGPU/Arc Intel (card NVIDIA không hiện ở đây).
THIET_BI = "GPU"
#: iGPU hỏng thì nghỉ ngần này rồi mới thử lại — trong lúc nghỉ chạy CPU.
NGHI_GIAY = 300.0
#: Số bản biên dịch giữ cho một graph (mỗi cỡ ảnh vào một bản — dò mặt có cỡ động).
_TOI_DA_BAN = 4
#: Thư mục thiết bị GPU trong container (compose ``devices: [/dev/dri:/dev/dri]``).
_DRI = "/dev/dri"

_khoa = threading.Lock()
_core: Any = None
_co: bool | None = None
_nghi_toi = 0.0
_dang_hong = False


def _lay_core() -> Any:
    global _core
    if _core is None:
        import openvino as ov

        _core = ov.Core()
    return _core


def co_igpu() -> bool:
    """Máy có iGPU Intel mà OpenVINO chạy được không. Dò một lần rồi nhớ."""
    global _co
    if os.getenv("IGPU", "1").strip() == "0":
        return False
    with _khoa:
        if _co is None and not os.path.isdir(_DRI):
            # Container không được gắn GPU nào: khỏi nạp openvino (~180 MB thư viện) vào RAM.
            _co = False
        if _co is None:
            try:
                ds = list(_lay_core().available_devices)
            except Exception as exc:  # noqa: BLE001 — thiếu openvino/driver = không có iGPU
                ds, loi = [], str(exc)[:160]
            else:
                loi = ""
            _co = any(d.split(".")[0] == THIET_BI for d in ds)
            logger.info({"event": "igpu_do", "co": _co, "thiet_bi": ds, "loi": loi})
        return _co


def trang_thai() -> dict[str, Any]:
    """Cho trang trạng thái: có iGPU không, tên chip, đang hỏng (chạy CPU) không."""
    if not co_igpu():
        return {"co": False}
    try:
        ten = str(_lay_core().get_property(THIET_BI, "FULL_DEVICE_NAME"))
    except Exception:  # noqa: BLE001 — chỉ để hiển thị
        ten = THIET_BI
    return {"co": True, "ten": ten, "dang_hong": _dang_hong}


def _hong(ten: str, exc: Exception) -> None:
    global _nghi_toi, _dang_hong
    with _khoa:
        _nghi_toi = time.monotonic() + NGHI_GIAY
        bao, _dang_hong = not _dang_hong, True
    if bao:
        logger.warning({"event": "igpu_hong", "graph": ten, "loi": str(exc)[:200]})


def _da_lanh(ten: str) -> None:
    global _dang_hong
    if _dang_hong:
        with _khoa:
            _dang_hong = False
        logger.info({"event": "igpu_da_lanh", "graph": ten})


class PhienIGPU:
    """Giống ``onnxruntime.InferenceSession``: ``run`` chạy iGPU, mọi thứ khác hỏi phiên CPU."""

    def __init__(self, duong: str, tai_cho: Any) -> None:
        self._duong = str(duong)
        self.ten = os.path.splitext(os.path.basename(self._duong))[0]
        self._tai_cho = tai_cho
        self._ten_ra = [o.name for o in tai_cho.get_outputs()]
        self._ban: dict[tuple, Any] = {}
        self._khoa = threading.Lock()

    def __getattr__(self, ten: str) -> Any:
        # get_inputs / get_outputs / get_modelmeta … — hồ sơ graph lấy từ phiên CPU.
        return getattr(self._tai_cho, ten)

    def run(self, output_names, feeds):
        if time.monotonic() >= _nghi_toi:
            try:
                ra = self._chay(output_names, feeds)
            except Exception as exc:  # noqa: BLE001 — mọi lỗi iGPU/driver đều lùi về CPU
                _hong(self.ten, exc)
            else:
                _da_lanh(self.ten)
                return ra
        return self._tai_cho.run(output_names, feeds)

    def _ban_dich(self, feeds: dict[str, Any]) -> Any:
        khoa = tuple(sorted((k, v.shape) for k, v in feeds.items()))
        with self._khoa:
            ban = self._ban.get(khoa)
            if ban is None:
                core = _lay_core()
                m = core.read_model(self._duong)
                m.reshape({k: list(v.shape) for k, v in feeds.items()})
                ban = core.compile_model(m, THIET_BI, {"INFERENCE_PRECISION_HINT": "f32"})
                if len(self._ban) >= _TOI_DA_BAN:
                    self._ban.clear()
                self._ban[khoa] = ban
                logger.info({"event": "igpu_bien_dich", "graph": self.ten,
                             "co": [list(v.shape) for v in feeds.values()]})
        return ban

    def _chay(self, output_names, feeds) -> list:
        import numpy as np

        feeds = {k: np.asarray(v) for k, v in feeds.items()}
        ban = self._ban_dich(feeds)
        kq = ban.create_infer_request().infer(feeds)   # yêu cầu riêng mỗi lần: an toàn đa luồng
        return [np.asarray(kq[ban.output(n)]) for n in (output_names or self._ten_ra)]


def lai(duong: str, tai_cho: Any) -> Any:
    """Bọc phiên CPU để chạy iGPU nếu máy có; không có thì trả nguyên phiên CPU."""
    return PhienIGPU(duong, tai_cho) if co_igpu() else tai_cho
