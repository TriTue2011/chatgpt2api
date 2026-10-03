"""Xếp lại đoạn RAG bằng cross-encoder (jina-reranker-v2 đa ngữ) trên GPU nhà — chỉ GPU, không lùi CPU.

Chủ máy 03/10/2026: "đi theo hướng embe + reranking". Đo cùng ngày (140 câu hỏi đặt từ 140 đoạn thật của kho
RAG; ứng viên = 20 đoạn gte gần nhất): đoạn đúng lọt 4 đầu — gte 62,1%, gte + xếp lại trộn thứ hạng 67,1%;
đứng đầu 40,0% → 43,6%. Trên RTX 2060S (fw-tach-am, .220): ~94 ms / 20 đoạn.

KHÔNG lùi CPU: Xeon E5-2630L v4 không VNNI chạy ~100 ms MỖI cặp (đo 02/10) — 20 đoạn là 2 giây cho mỗi câu hỏi,
đổi lấy 5 điểm. GPU hỏng → `diem()` trả None, bên gọi giữ nguyên thứ tự gte.
Dùng chung đường GPU của `services/nhung.py` (`onnx_xa`, graph `jina_xep` trên fw-tach-am).
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

from utils.log import logger

#: (kho HF, phiên bản ghim, tokenizer) — trùng phiên bản graph `jina_xep` của fw-tach-am.
XEP = ("jinaai/jina-reranker-v2-base-multilingual", "9cfeff2df7d40d1b78e75e5e9cebec92a99813c9", "tokenizer.json")
TOI_DA_TOKEN = 512
TOI_DA_DOAN = 50

_khoa = threading.Lock()
_san: dict[str, Any] = {}


class _KhongChayCpu:
    """Thế chỗ phiên CPU cho `onnx_xa.PhienLai`: GPU hỏng thì báo lỗi rõ ràng thay vì nạp model lên CPU."""

    KHONG_CPU = True     # onnx_xa báo đúng: «bỏ qua bước này», không phải «chạy CPU»

    def get_outputs(self):
        return [SimpleNamespace(name="logits")]

    def get_inputs(self):
        return [SimpleNamespace(name="input_ids"), SimpleNamespace(name="attention_mask")]

    def run(self, output_names, feeds):
        raise RuntimeError("GPU xếp lại không chạy được — giữ thứ tự gte")


def _nap() -> tuple[Any, Any]:
    with _khoa:
        if "p" not in _san:
            from huggingface_hub import hf_hub_download
            from tokenizers import Tokenizer

            from services import onnx_xa
            kho, rev, tok = XEP
            t = Tokenizer.from_file(hf_hub_download(kho, tok, revision=rev))
            t.enable_truncation(max_length=TOI_DA_TOKEN)
            _san["p"] = (t, onnx_xa.lai("jina_xep", _KhongChayCpu()))
        return _san["p"]


def diem(cau: str, doan: list[str]) -> list[float] | None:
    """Điểm liên quan (cao = gần) của từng đoạn với câu hỏi; None khi không xếp được (GPU hỏng, lỗi tải)."""
    if not doan:
        return []
    try:
        import numpy as np
        tok, phien = _nap()
        enc = tok.encode_batch([(str(cau or ""), str(d or "")) for d in doan[:TOI_DA_DOAN]])
        dai = max(len(e.ids) for e in enc)
        ids = np.array([e.ids + [1] * (dai - len(e.ids)) for e in enc], dtype=np.int64)
        mat = np.array([[1] * len(e.ids) + [0] * (dai - len(e.ids)) for e in enc], dtype=np.int64)
        ra = phien.run(None, {"input_ids": ids, "attention_mask": mat})[0]
        return [float(x) for x in np.asarray(ra, dtype=np.float32).reshape(-1)]
    except Exception as exc:  # noqa: BLE001 — xếp lại là phần thêm: hỏng thì bên gọi giữ thứ tự gte
        logger.info({"event": "xep_lai_bo_qua", "loi": str(exc)[:160]})
        return None


def tron(thu_tu: list[Any], diem_xep: list[float], k: int = 60) -> list[Any]:
    """Trộn thứ tự gte với thứ tự xếp lại (cộng nghịch đảo thứ hạng, k=60) — trộn hơn dùng riêng xếp lại ở
    «lọt 4 đầu» (67,1% so với 62,9%, đo 03/10/2026)."""
    hang = {i: r for r, i in enumerate(sorted(range(len(diem_xep)), key=lambda j: -diem_xep[j]))}
    return [thu_tu[i] for i in sorted(range(len(thu_tu)), key=lambda i: -(1 / (k + i) + 1 / (k + hang.get(i, len(thu_tu)))))]
