"""Lớp dịch giao thức Ollama cho Home Assistant.

Home Assistant có sẵn integration Ollama (tạo được entity `ai_task` mà blueprint
cảnh báo camera đòi), nhưng nó chỉ nói giao thức Ollama. Đo 19/08/2026: cả
llama.cpp chạy model thị giác tại nhà lẫn gateway này đều không phục vụ
`/api/tags` — một cái trả 404, một cái trả trang web quản trị, nên HA không nối
được. Router này dịch qua lại, không chứa logic AI nào.

Phần dễ sai nhất và là lý do có tệp test này: Ollama để ảnh trong trường
`images` dạng base64 THUẦN, còn đường OpenAI đòi ảnh nằm trong `content` dạng
data URI. Dịch sai chỗ đó thì mọi lượt phân tích camera đi vào model mà không
có ảnh nào, và model vẫn trả lời trơn tru — hỏng âm thầm, không ai biết.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.pure

B64 = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAA"


def _doi(messages):
    from api.ollama_compat import _doi_messages
    return _doi_messages(messages)


class TestDichAnh:
    def test_anh_base64_thuan_thanh_data_uri(self):
        ra = _doi([{"role": "user", "content": "có ai không", "images": [B64]}])
        noi = ra[0]["content"]
        assert isinstance(noi, list), "có ảnh thì content phải là danh sách phần tử"
        assert noi[0] == {"type": "text", "text": "có ai không"}
        assert noi[1]["type"] == "image_url"
        assert noi[1]["image_url"]["url"] == "data:image/jpeg;base64," + B64

    def test_khong_boc_hai_lan_khi_da_co_tien_to(self):
        san = "data:image/png;base64," + B64
        ra = _doi([{"role": "user", "content": "x", "images": [san]}])
        assert ra[0]["content"][1]["image_url"]["url"] == san

    def test_nhieu_anh_giu_du_thu_tu(self):
        ra = _doi([{"role": "user", "content": "chuỗi ảnh", "images": [B64, B64 + "AA", B64 + "BB"]}])
        urls = [p["image_url"]["url"] for p in ra[0]["content"] if p["type"] == "image_url"]
        assert len(urls) == 3
        assert urls[1].endswith("AA") and urls[2].endswith("BB"), "sai thứ tự là AI đọc nhầm diễn biến"

    def test_tin_khong_anh_giu_nguyen_dang_chuoi(self):
        ra = _doi([{"role": "user", "content": "chỉ có chữ"}])
        assert ra[0]["content"] == "chỉ có chữ"

    def test_bo_qua_anh_rong(self):
        ra = _doi([{"role": "user", "content": "x", "images": ["", None]}])
        assert not [p for p in ra[0]["content"] if p["type"] == "image_url"]


class TestDichFormat:
    def test_json_thuong(self):
        from api.ollama_compat import _doi_format
        assert _doi_format("json") == {"type": "json_object"}

    def test_schema_thanh_json_schema(self):
        from api.ollama_compat import _doi_format
        schema = {"type": "object", "properties": {"humans_detected": {"type": "integer"}}}
        ra = _doi_format(schema)
        assert ra["type"] == "json_schema"
        assert ra["json_schema"]["schema"] == schema, "structured output của HA gửi schema thẳng ở đây"

    def test_khong_khai_gi_thi_khong_ep_dinh_dang(self):
        from api.ollama_compat import _doi_format
        assert _doi_format(None) is None
        assert _doi_format("") is None


class TestDangTraLoi:
    def test_dung_khuon_ollama(self):
        from api.ollama_compat import _tra_loi
        r = _tra_loi("lv/x", "Có 1 người đang quét nhà.", usage={"prompt_tokens": 12, "completion_tokens": 7})
        assert r["done"] is True
        assert r["message"]["role"] == "assistant"
        assert r["message"]["content"] == "Có 1 người đang quét nhà."
        assert r["prompt_eval_count"] == 12 and r["eval_count"] == 7
        assert "created_at" in r and r["model"] == "lv/x"

    def test_giu_tool_calls_khi_co(self):
        from api.ollama_compat import _tra_loi
        tc = [{"function": {"name": "x", "arguments": {}}}]
        assert _tra_loi("m", "", tool_calls=tc)["message"]["tool_calls"] == tc

    @pytest.mark.adapter
    def test_stream_giu_tool_calls_trong_tung_chunk(self, monkeypatch):
        from api import ollama_compat as oc

        chunks = iter([
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "type": "function",
                 "function": {"name": "bat_den", "arguments": "{\"phong\":"}},
            ]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "\"bep\"}"}},
            ]}}]},
        ])
        monkeypatch.setattr(oc, "require_identity", lambda _auth: {"id": "chu-nha"})
        monkeypatch.setattr(oc.openai_v1_chat_complete, "handle", lambda _payload: chunks)

        app = FastAPI()
        app.include_router(oc.create_router())
        with TestClient(app) as client:
            response = client.post("/api/chat", headers={"Authorization": "Bearer test"},
                                   json={"model": "local/model", "stream": True,
                                         "messages": [{"role": "user", "content": "bật đèn"}],
                                         "tools": [{"type": "function",
                                                    "function": {"name": "bat_den"}}]})

        assert response.status_code == 200
        lines = [json.loads(line) for line in response.text.splitlines() if line]
        assert lines[0]["done"] is False
        assert lines[0]["message"]["tool_calls"] == [{
            "id": "call_1", "type": "function",
            "function": {"name": "bat_den", "arguments": {"phong": "bep"}},
        }]
        assert lines[1]["done"] is True

    @pytest.mark.adapter
    def test_stream_khong_nhap_hai_tool_call_thieu_index_lam_mot(self, monkeypatch):
        from api import ollama_compat as oc

        calls = [
            {"id": "call_den", "type": "function",
             "function": {"name": "bat_den", "arguments": "{\"phong\":\"bep\"}"}},
            {"id": "call_quat", "type": "function",
             "function": {"name": "bat_quat", "arguments": "{\"phong\":\"ngu\"}"}},
        ]
        chunks = iter([{"choices": [{"delta": {"tool_calls": calls}}]}])
        monkeypatch.setattr(oc, "require_identity", lambda _auth: {"id": "chu-nha"})
        monkeypatch.setattr(oc.openai_v1_chat_complete, "handle", lambda _payload: chunks)

        app = FastAPI()
        app.include_router(oc.create_router())
        with TestClient(app) as client:
            response = client.post("/api/chat", headers={"Authorization": "Bearer test"},
                                   json={"model": "local/model", "stream": True,
                                         "messages": [{"role": "user", "content": "bật cả hai"}]})

        lines = [json.loads(line) for line in response.text.splitlines() if line]
        assert [tc["function"]["name"]
                for tc in lines[0]["message"]["tool_calls"]] == ["bat_den", "bat_quat"]
        assert [tc["function"]["arguments"]
                for tc in lines[0]["message"]["tool_calls"]] == [
                    {"phong": "bep"}, {"phong": "ngu"}]
