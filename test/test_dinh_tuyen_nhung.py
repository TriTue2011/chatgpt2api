"""Chọn nhóm tool bằng model nhúng tại chỗ, trước khi gọi LLM (chủ máy 02/10/2026).

Không tải model: conftest chặn `nhung._nap`; ở đây giả `nhung.vec` với vector đặt tay."""
from __future__ import annotations

import numpy as np
import pytest

from services import nhung
from services.agent import dinh_tuyen_nhung as dtn
from services.agent import orchestrator as orch

_VEC = {"vẽ con mèo": [1.0, 0.0, 0.1], "giá vàng hôm nay": [0.0, 1.0, 0.1]}


@pytest.fixture
def san(monkeypatch):
    monkeypatch.setattr(nhung, "vec", lambda chu: np.array(_VEC.get(chu, [0.0, 1.0, 0.1]), dtype=np.float32))
    monkeypatch.setattr(dtn, "_san", {"vec": np.array([[1, 0, 0], [0.9, 0.1, 0], [0, 1, 0]], dtype=np.float32),
                                      "nhom": ["image", "image", "web"], "model": nhung.ten_model()})


def test_model_chua_san_thi_tra_none_de_dung_tu_khoa():
    assert dtn.nhom_theo_nghia("bật đèn") is None


def test_nhom_cua_k_tool_gan_nhat(san):
    assert dtn.nhom_theo_nghia("vẽ con mèo") == {"image"}, "hai tool gần nhất cùng nhóm → một nhóm"
    assert dtn.nhom_theo_nghia("giá vàng hôm nay") == {"web", "image"}
    assert dtn.nhom_theo_nghia("  ") == set()


def test_doi_model_thi_tinh_lai_vector_tool(san, monkeypatch):
    monkeypatch.setitem(dtn._san, "model", "model-cu")
    monkeypatch.setattr(dtn, "_tinh", lambda: None)
    assert dtn.nhom_theo_nghia("vẽ con mèo") is None


def test_nhom_model_van_qua_cua_quyen(san):
    assert "image" in orch._nhom_viec("vẽ con mèo", None, theo_nghia=True)
    assert "image" not in orch._nhom_viec("vẽ con mèo", {"web"}, theo_nghia=True), "thread không được vẽ"


def test_lich_su_khong_qua_model(san, monkeypatch):
    goi: list[str] = []
    that = dtn.nhom_theo_nghia
    monkeypatch.setattr(dtn, "nhom_theo_nghia", lambda chu, k=2: goi.append(chu) or that(chu, k))
    orch._nhom_ngu_canh("vẽ con mèo", [{"role": "user", "content": "giá vàng hôm nay"}], None)
    assert goi == ["vẽ con mèo"]


def test_tim_lich_su_chon_luot_gan_nghia_giu_thu_tu_moi_nhat(monkeypatch):
    """FTS «OR» khớp cả lượt chỉ chung một chữ thường; model chọn lượt gần nghĩa, vẫn trả mới nhất trước."""
    from services.agent import session as sess
    hits = [{"role": "user", "content": f"lượt {i}", "created_at": 100 - i} for i in range(6)]
    gan = {"x", "lượt 4", "lượt 1"}
    monkeypatch.setattr(nhung, "vec", lambda chu: np.array([1.0, 0.0] if chu in gan else [0.0, 1.0], dtype=np.float32))
    assert [h["content"] for h in sess._lien_quan_nhat("x", hits, 2)] == ["lượt 1", "lượt 4"]
    monkeypatch.setattr(nhung, "vec", lambda chu: None)
    assert [h["content"] for h in sess._lien_quan_nhat("x", hits, 2)] == ["lượt 0", "lượt 1"], "chưa có model: như cũ"
