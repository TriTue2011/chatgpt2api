"""Đường tắt theo dõi chủ đề: chọn rõ ràng, không để model tự đoán."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


def _patch_dir(tmp_path, monkeypatch):
    import services.config as cfg
    monkeypatch.setattr(cfg, "DATA_DIR", str(tmp_path), raising=False)


def test_co_gi_moi_khong_mot_chu_de_tra_cuu_thang(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import orchestrator as orch
    from services.agent import tracked_topic as tt

    assert tt.them("zalo_123", "giá vàng")
    web = SimpleNamespace(handler=lambda args, _ctx: {"text": f"Tin: {args['query']}"})
    monkeypatch.setattr(orch.caps, "get", lambda name: web if name == "web_search" else None)

    out = orch._tracked_topic_shortcut("có gì mới không", "zalo_123")
    assert out is not None
    assert "Tin: giá vàng" in out["text"]


def test_co_gi_moi_khong_nhieu_chu_de_bat_chon_so(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import orchestrator as orch
    from services.agent import tracked_topic as tt

    assert tt.them("zalo_123", "giá vàng")
    assert tt.them("zalo_123", "bão số 3")

    out = orch._tracked_topic_shortcut("có gì mới không", "zalo_123")
    assert out is not None
    assert "chọn" in out["text"].lower()
    assert [x["label"] for x in out["choices"]] == ["bão số 3", "giá vàng"]
    assert all(x["send"].startswith("__tracked_topic__:view:") for x in out["choices"])


def test_luu_chu_de_hien_menu_bao_tu_nguyen(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    from services.agent import orchestrator as orch

    out = orch._tracked_topic_shortcut("theo dõi giá vàng", "zalo_123")
    assert out is not None
    assert "đã lưu" in out["text"].lower()
    assert any("Báo" in x["label"] for x in out["choices"])
