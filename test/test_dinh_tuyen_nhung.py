"""Định tuyến nhóm tool bằng model embedding — chọn trước khi gọi LLM (chủ máy 02/10/2026).

Không tải model: conftest chặn `_nap`; ở đây dựng sẵn bộ tokenizer/phiên giả với vector đặt tay."""
from __future__ import annotations

import numpy as np
import pytest

from services.agent import dinh_tuyen_nhung as dtn
from services.agent import orchestrator as orch


class _Tok:
    def encode(self, chu):
        class E:
            ids = [len(chu)]
            attention_mask = [1]
        return E()


class _Phien:
    """Câu «vẽ…» gần tool vẽ ảnh, câu khác gần tool tra web."""

    def run(self, _ra, vao):
        n = int(vao["input_ids"][0][0])
        v = [1.0, 0.0, 0.1] if n == len("vẽ con mèo") else [0.0, 1.0, 0.1]
        return [np.array([[v]], dtype=np.float32)]


@pytest.fixture
def san(monkeypatch):
    vec = np.array([[1, 0, 0], [0.9, 0.1, 0], [0, 1, 0]], dtype=np.float32)
    monkeypatch.setattr(dtn, "_san", {"tok": _Tok(), "phien": _Phien(), "vec": vec,
                                      "nhom": ["image", "image", "web"]})


def test_chua_san_thi_tra_none_de_dung_tu_khoa():
    assert dtn._san is None
    assert dtn.nhom_theo_nghia("bật đèn") is None


def test_nhom_cua_k_tool_gan_nhat(san):
    assert dtn.nhom_theo_nghia("vẽ con mèo") == {"image"}, "hai tool gần nhất cùng nhóm → một nhóm"
    assert dtn.nhom_theo_nghia("giá vàng hôm nay") == {"web", "image"}
    assert dtn.nhom_theo_nghia("  ") == set()


def test_nhom_model_van_qua_cua_quyen(san):
    assert "image" in orch._nhom_viec("vẽ con mèo", None, theo_nghia=True)
    assert "image" not in orch._nhom_viec("vẽ con mèo", {"web"}, theo_nghia=True), "thread không được vẽ"


def test_lich_su_khong_qua_model(san, monkeypatch):
    goi: list[str] = []
    that = dtn.nhom_theo_nghia
    monkeypatch.setattr(dtn, "nhom_theo_nghia", lambda chu, k=2: goi.append(chu) or that(chu, k))
    orch._nhom_ngu_canh("vẽ con mèo", [{"role": "user", "content": "giá vàng hôm nay"}], None)
    assert goi == ["vẽ con mèo"]
