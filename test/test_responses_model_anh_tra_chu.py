"""/v1/responses: yêu cầu CHỮ mang tên model ẢNH.

Đo 02/10/2026 (runs.sqlite + gọi thử): HA đặt grok/imagine cho AI Task — lượt «lấy dữ liệu»
mỗi giờ (không kèm image_generation) trả status=completed với chữ RỖNG. Responses API phân
biệt vẽ/chữ bằng công cụ, nên chữ phải đi model trò chuyện cùng nhà; nhà chỉ vẽ thì 400 + lý do.
"""
from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.protocol import openai_v1_response as r  # noqa: E402


@pytest.fixture
def bat(monkeypatch):
    gap: list[str] = []
    monkeypatch.setattr(r, "text_backend", lambda: None)
    monkeypatch.setattr(r, "stream_text_response", lambda be, body: gap.append(body["model"]) or iter([]))
    return gap


def test_grok_imagine_tra_chu_bang_grok_chat(bat):
    list(r.response_events({"model": "grok/imagine", "input": "thủ đô Việt Nam?"}))
    assert bat == ["grok/fast"]


def test_model_chat_khong_doi(bat):
    list(r.response_events({"model": "grok/fast", "input": "x"}))
    assert bat == ["grok/fast"]


def test_nha_chi_ve_thi_400_kem_ly_do(bat):
    with pytest.raises(HTTPException) as e:
        list(r.response_events({"model": "flow/banana-pro", "input": "x"}))
    assert e.value.status_code == 400 and "chỉ vẽ ảnh" in e.value.detail["error"]
    assert bat == []


def test_co_cong_cu_ve_thi_van_di_duong_ve(monkeypatch, bat):
    from services.protocol import openai_v1_image_generations as ig
    goi = []
    monkeypatch.setattr(ig, "handle", lambda b: goi.append(b["model"]) or {"data": []})
    monkeypatch.setattr(r, "stream_image_response", lambda outs, p, m: iter([]))
    list(r.response_events({"model": "grok/imagine", "input": "vẽ mèo", "tools": [{"type": "image_generation"}]}))
    assert goi == ["grok/imagine"] and bat == []
