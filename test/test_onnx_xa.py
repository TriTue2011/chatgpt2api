"""Phiên ONNX lai: GPU nhà khi được, CPU tại chỗ khi GPU hỏng (24/09/2026)."""
from __future__ import annotations

import io
import os
import types

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from services import onnx_xa  # noqa: E402


class _PhienCpu:
    def __init__(self):
        self.lan = 0

    def get_inputs(self):
        return [types.SimpleNamespace(name="vao", shape=[1, 3])]

    def get_outputs(self):
        return [types.SimpleNamespace(name="a"), types.SimpleNamespace(name="b")]

    def run(self, output_names, feeds):
        self.lan += 1
        ra = {"a": feeds["vao"] + 1, "b": feeds["vao"] * 2}
        return [ra[n] for n in (output_names or ["a", "b"])]


class _TraLoi:
    def __init__(self, noi_dung: bytes, ma: int = 200):
        self.content, self.status_code = noi_dung, ma

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _npz(**mang) -> bytes:
    buf = io.BytesIO()
    np.savez(buf, **mang)
    return buf.getvalue()


@pytest.fixture
def gpu(monkeypatch):
    monkeypatch.setenv("TACH_AM_URL_GPU", "http://gpu:5004/")
    monkeypatch.setenv("TACH_AM_API_TOKEN", "bi-mat")
    monkeypatch.setattr(onnx_xa, "_nghi_toi", 0.0)
    monkeypatch.setattr(onnx_xa, "_bao_luc", -1e9)
    bao: list[str] = []
    import services.notifier as nf
    monkeypatch.setattr(nf, "notify_admin", lambda text, **_k: bao.append(text))
    return bao


def test_chay_tren_gpu_va_chon_dung_dau_ra(monkeypatch, gpu):
    goi = {}

    def post(url, data, headers, timeout):
        goi.update(url=url, headers=headers)
        with np.load(io.BytesIO(data), allow_pickle=False) as npz:
            v = npz["vao"]
        return _TraLoi(_npz(o0=v + 10, o1=v + 20))

    import requests
    monkeypatch.setattr(requests, "post", post)
    cpu = _PhienCpu()
    p = onnx_xa.lai("det_10g", cpu)
    x = np.ones((1, 3), np.float32)
    b, a = p.run(["b", "a"], {"vao": x})
    assert (a[0, 0], b[0, 0]) == (11.0, 21.0)
    assert goi["url"] == "http://gpu:5004/onnx/det_10g/chay"
    assert goi["headers"] == {"x-api-key": "bi-mat"}
    assert cpu.lan == 0                      # không đụng CPU


def test_gpu_hong_thi_chay_cpu_nghi_va_bao_mot_lan(monkeypatch, gpu):
    import requests
    lan_post = []

    def hong(*_a, **_k):
        lan_post.append(1)
        raise ConnectionError("no CUDA-capable device")

    monkeypatch.setattr(requests, "post", hong)
    cpu = _PhienCpu()
    p = onnx_xa.lai("w600k_r50", cpu)
    x = np.ones((1, 3), np.float32)
    assert p.run(None, {"vao": x})[0][0, 0] == 2.0
    assert p.run(None, {"vao": x})[0][0, 0] == 2.0
    assert (len(lan_post), cpu.lan, len(gpu)) == (1, 2, 1)   # nghỉ GPU, chỉ báo một lần
    assert "w600k_r50" in gpu[0]


def test_graph_ngoai_danh_muc_hoac_chua_khai_gpu_thi_giu_nguyen_cpu(monkeypatch):
    cpu = _PhienCpu()
    assert onnx_xa.lai("det_500m", cpu) is cpu
    monkeypatch.delenv("TACH_AM_URL_GPU", raising=False)
    p = onnx_xa.lai("kokoro_vi", cpu)
    assert p.run(None, {"vao": np.ones((1, 3), np.float32)})[0][0, 0] == 2.0
    assert cpu.lan == 1
