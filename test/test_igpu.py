"""iGPU (OpenVINO): có thì chạy iGPU, không có / hỏng thì chạy phiên CPU — không bao giờ câm.

Đo trên model thật 27/09/2026 (OpenVINO thiết bị CPU thay iGPU): hộp mặt trùng khớp, vector
mặt cosine 1,000000 so với onnxruntime, YOLO cùng người cùng điểm — xem commit.
"""
from __future__ import annotations

import pytest

from services import igpu

pytestmark = pytest.mark.pure


class _Ra:
    name = "out"


class _PhienCpu:
    def __init__(self):
        self.goi = 0

    def get_outputs(self):
        return [_Ra()]

    def get_inputs(self):
        return ["vao"]

    def get_modelmeta(self):
        return "meta"

    def run(self, output_names, feeds):
        self.goi += 1
        return ["cpu"]


@pytest.fixture
def sach(monkeypatch):
    monkeypatch.setattr(igpu, "_co", None)
    monkeypatch.setattr(igpu, "_nghi_toi", 0.0)
    monkeypatch.setattr(igpu, "_dang_hong", False)
    monkeypatch.setattr(igpu, "_DRI", "/")          # giả như container có /dev/dri
    monkeypatch.delenv("IGPU", raising=False)


def test_khong_co_igpu_thi_tra_nguyen_phien_cpu(sach, monkeypatch):
    class _Core:
        available_devices = ["CPU"]

    monkeypatch.setattr(igpu, "_core", _Core())
    cpu = _PhienCpu()
    assert igpu.lai("m.onnx", cpu) is cpu
    assert igpu.trang_thai() == {"co": False}


def test_thieu_openvino_la_khong_co_igpu(sach, monkeypatch):
    def _hong():
        raise ImportError("No module named 'openvino'")

    monkeypatch.setattr(igpu, "_lay_core", _hong)
    assert igpu.co_igpu() is False


def test_khong_gan_dev_dri_thi_khong_nap_openvino(sach, monkeypatch):
    def _cam():
        raise AssertionError("không được nạp openvino khi không có /dev/dri")

    monkeypatch.setattr(igpu, "_DRI", "/khong/co/dri")
    monkeypatch.setattr(igpu, "_lay_core", _cam)
    assert igpu.co_igpu() is False


def test_tat_bang_bien_moi_truong(sach, monkeypatch):
    class _Core:
        available_devices = ["CPU", "GPU.0"]

    monkeypatch.setattr(igpu, "_core", _Core())
    assert igpu.co_igpu() is True                      # "GPU.0" cũng là iGPU
    monkeypatch.setenv("IGPU", "0")
    assert igpu.co_igpu() is False


def test_igpu_hong_thi_chay_cpu_va_nghi(sach, monkeypatch):
    bien_dich = {"lan": 0}

    class _Model:
        def reshape(self, _co):
            pass

    class _Core:
        available_devices = ["GPU"]

        def read_model(self, _duong):
            return _Model()

        def compile_model(self, *_a):
            bien_dich["lan"] += 1
            raise RuntimeError("CL_OUT_OF_RESOURCES")

    monkeypatch.setattr(igpu, "_core", _Core())
    cpu = _PhienCpu()
    p = igpu.lai("/m/det_10g.onnx", cpu)
    assert isinstance(p, igpu.PhienIGPU)
    assert p.get_modelmeta() == "meta" and p.get_inputs() == ["vao"]   # hồ sơ lấy từ CPU
    assert p.run(None, {"vao": [[1.0]]}) == ["cpu"]
    assert igpu._dang_hong and bien_dich["lan"] == 1
    # Trong lúc nghỉ: không thử iGPU lại, đi thẳng CPU.
    assert p.run(None, {"vao": [[1.0]]}) == ["cpu"]
    assert bien_dich["lan"] == 1 and cpu.goi == 2
