"""Hỏi một module từ xa (custom provider) còn sống không, chậm bao nhiêu.

Vì sao cần: web2api sắp cho các module ở máy khác (máy GPU .220, máy trong
mạng, domain) nói chuyện qua chuẩn OpenAI bằng custom provider. Trước đây chỉ
có `is_available` — trả một bool và chỉ thử URL ĐẦU — còn `list_models` nuốt
lỗi, nên một URL chết trong bể nhiều URL, hay một tiền tố bị provider có sẵn
che mất, đều không ai thấy.

Ba điều phải giữ:
  * khoá API không bao giờ lọt vào kết quả trả ra giao diện;
  * kiểm TỪNG URL, không dừng ở URL đầu;
  * kiểm tra chỉ ĐỌC — không được hạ hạng URL (đổi đường đi của request thật).
"""
from __future__ import annotations

import json
import os
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

pytestmark = pytest.mark.pure

KHOA = "sk-bi-mat-khong-duoc-lo-123"


class _Resp:
    def __init__(self, status: int = 200, body=None, json_hong: bool = False):
        self.status_code = status
        self._body = body if body is not None else {"data": []}
        self._json_hong = json_hong
        self.closed = False

    def json(self):
        if self._json_hong:
            raise ValueError("không phải JSON")
        return self._body

    def close(self):
        self.closed = True


class _HttpTheoUrl:
    """Trả lời theo URL chứ không theo thứ tự gọi — test không phụ thuộc lượt."""

    def __init__(self, tra_loi):
        self.tra_loi = tra_loi
        self.calls: list[dict] = []

    def get(self, url, headers=None, timeout=None, **_kw):
        self.calls.append({"url": url, "headers": dict(headers or {}), "timeout": timeout})
        kq = self.tra_loi(url)
        if isinstance(kq, Exception):
            raise kq
        return kq


class ConnectionError(Exception):  # noqa: A001 — giả tên lớp lỗi mạng của curl_cffi
    pass


@pytest.fixture()
def co(monkeypatch):
    from services.config import config
    from services.providers import custom_openai
    monkeypatch.setattr(config, "data", {}, raising=False)
    for b in list(os.environ):
        if b.startswith("C2A_PROVIDER_") or b.startswith(("VISION_URL_GPU", "OLLAMA_URL")):
            monkeypatch.delenv(b, raising=False)
    monkeypatch.setattr(custom_openai.CustomOpenAIProvider, "_base_url_cooldown", {})
    return custom_openai


def _models(n: int) -> dict:
    return {"data": [{"id": f"m{i}"} for i in range(n)]}


class TestKiemTraTungUrl:
    def test_mot_song_mot_chet(self, co, monkeypatch):
        fake = _HttpTheoUrl(lambda url: _Resp(200, _models(3)) if "song" in url
                            else ConnectionError("refused"))
        monkeypatch.setattr(co, "requests", fake)
        p = co.CustomOpenAIProvider({"name": "pool", "prefix": "may1",
                                     "base_url": "http://song:1/v1",
                                     "base_urls": ["http://chet:2/v1"], "api_key": KHOA})
        kq = p.kiem_tra()
        assert kq["ok"] is True, "còn một URL sống thì provider vẫn dùng được"
        theo_url = {u["url"]: u for u in kq["urls"]}
        assert set(theo_url) == {"http://song:1/v1", "http://chet:2/v1"}, "phải thử TỪNG URL"
        song, chet = theo_url["http://song:1/v1"], theo_url["http://chet:2/v1"]
        assert song["ok"] is True and song["so_model"] == 3 and song["loi"] == ""
        assert isinstance(song["do_tre_ms"], int) and song["do_tre_ms"] >= 0
        assert chet["ok"] is False and "ConnectionError" in chet["loi"]
        # Đúng đường /models (base đã có /v1) và timeout ngắn.
        assert {c["url"] for c in fake.calls} == {"http://song:1/v1/models", "http://chet:2/v1/models"}
        assert all(c["timeout"] and c["timeout"] <= 5 for c in fake.calls)

    def test_tat_ca_chet_thi_ok_false(self, co, monkeypatch):
        monkeypatch.setattr(co, "requests", _HttpTheoUrl(lambda url: _Resp(503)))
        p = co.CustomOpenAIProvider({"name": "x", "prefix": "may1",
                                     "base_url": "http://a:1", "api_key": KHOA})
        kq = p.kiem_tra()
        assert kq["ok"] is False
        assert kq["urls"][0]["loi"] == "HTTP 503"
        assert kq["urls"][0]["ok"] is False

    def test_base_khong_co_v1_thi_hoi_v1_models(self, co, monkeypatch):
        fake = _HttpTheoUrl(lambda url: _Resp(200, _models(1)))
        monkeypatch.setattr(co, "requests", fake)
        co.CustomOpenAIProvider({"name": "x", "prefix": "may1", "base_url": "http://a:1",
                                 "api_key": KHOA}).kiem_tra()
        assert fake.calls[0]["url"] == "http://a:1/v1/models"

    def test_200_ma_khong_phai_json_openai_la_hong(self, co, monkeypatch):
        """Trang đăng nhập hay proxy trả 200 HTML không phải module OpenAI."""
        monkeypatch.setattr(co, "requests", _HttpTheoUrl(lambda url: _Resp(200, json_hong=True)))
        kq = co.CustomOpenAIProvider({"name": "x", "prefix": "may1", "base_url": "http://a:1/v1",
                                      "api_key": KHOA}).kiem_tra()
        assert kq["ok"] is False and kq["urls"][0]["loi"]

    def test_khong_co_khoa_thi_khong_goi_mang(self, co, monkeypatch):
        fake = _HttpTheoUrl(lambda url: _Resp(200, _models(1)))
        monkeypatch.setattr(co, "requests", fake)
        kq = co.CustomOpenAIProvider({"name": "x", "prefix": "may1",
                                      "base_url": "http://a:1/v1"}).kiem_tra()
        assert kq["ok"] is False
        assert kq["urls"][0]["loi"] == "chưa có khoá API"
        assert fake.calls == []

    def test_khoa_khong_lo_vao_ket_qua(self, co, monkeypatch):
        monkeypatch.setattr(co, "requests", _HttpTheoUrl(
            lambda url: ConnectionError(f"lỗi kèm Authorization: Bearer {KHOA}")))
        kq = co.CustomOpenAIProvider({"name": "x", "prefix": "may1", "base_url": "http://a:1/v1",
                                      "api_keys": [KHOA, "khoa-thu-hai"]}).kiem_tra()
        lo = json.dumps(kq, ensure_ascii=False)
        assert KHOA not in lo and "Bearer" not in lo and "khoa-thu-hai" not in lo

    def test_kiem_tra_khong_ha_hang_url(self, co, monkeypatch):
        """Kiểm tra chỉ đọc — hạ hạng URL ở đây là đổi đường đi của request thật."""
        monkeypatch.setattr(co, "requests", _HttpTheoUrl(lambda url: ConnectionError("x")))
        p = co.CustomOpenAIProvider({"name": "pool-ro", "prefix": "may1",
                                     "base_url": "http://a:1/v1", "base_urls": ["http://b:2/v1"],
                                     "api_key": KHOA})
        p.kiem_tra()
        assert co.CustomOpenAIProvider._base_url_cooldown.get("pool-ro", {}) == {}
        assert p._base_urls == ["http://a:1/v1", "http://b:2/v1"]


class TestBiChe:
    def test_tien_to_trung_provider_co_san_bi_bao(self, co, monkeypatch):
        from services.config import config
        cfg = {"name": "OC giả", "prefix": "oc", "base_url": "http://a:1/v1",
               "api_key": KHOA, "enabled": True}
        monkeypatch.setattr(config, "data", {"custom_providers": {"oc": cfg}}, raising=False)
        monkeypatch.setattr(co, "requests", _HttpTheoUrl(lambda url: _Resp(200, _models(1))))
        assert co.CustomOpenAIProvider(cfg).kiem_tra()["bi_che_boi"] == "opencode"

    def test_tien_to_rieng_thi_khong_bi_che(self, co, monkeypatch):
        from services.config import config
        cfg = {"name": "Máy 1", "prefix": "may1", "base_url": "http://a:1/v1",
               "api_key": KHOA, "enabled": True}
        monkeypatch.setattr(config, "data", {"custom_providers": {"may1": cfg}}, raising=False)
        monkeypatch.setattr(co, "requests", _HttpTheoUrl(lambda url: _Resp(200, _models(1))))
        assert co.CustomOpenAIProvider(cfg).kiem_tra()["bi_che_boi"] == ""


@pytest.fixture()
def khach(co):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import system
    app = FastAPI()
    with mock.patch("api.system.require_admin", lambda *a, **k: None):
        app.include_router(system.create_router("test"))
        yield TestClient(app)


class TestEndpoint:
    def test_health_provider_khong_co_thi_404(self, khach):
        r = khach.get("/api/v1/custom-providers/khong-co/health")
        assert r.status_code == 404
        assert r.json()["detail"] == {"error": "provider 'khong-co' not found"}

    def test_health_tim_ca_provider_khai_bang_env(self, khach, co, monkeypatch):
        monkeypatch.setenv("C2A_PROVIDER_MAY_GPU_URL", "http://172.16.10.220:8000")
        monkeypatch.setenv("C2A_PROVIDER_MAY_GPU_KEY", KHOA)
        monkeypatch.setattr(co, "requests", _HttpTheoUrl(lambda url: _Resp(200, _models(2))))
        r = khach.get("/api/v1/custom-providers/may_gpu/health")
        assert r.status_code == 200
        than = r.json()
        assert than["ok"] is True and than["urls"][0]["so_model"] == 2
        assert than["bi_che_boi"] == ""
        assert KHOA not in r.text

    def test_danh_sach_co_env_providers_da_che_khoa(self, khach, co, monkeypatch):
        from services.config import config
        monkeypatch.setenv("C2A_PROVIDER_MAY_GPU_URL", "http://172.16.10.220:8000")
        monkeypatch.setenv("C2A_PROVIDER_MAY_GPU_KEY", KHOA)
        monkeypatch.setattr(config, "data", {"custom_providers": {"agnes": {
            "name": "Agnes", "prefix": "agnes", "base_url": "https://a/v1",
            "api_key": "khoa-config", "enabled": True}}}, raising=False)
        r = khach.get("/api/v1/custom-providers")
        assert r.status_code == 200
        than = r.json()
        # Khoá cũ giữ nguyên hình dạng — giao diện đang đọc nó.
        assert set(than["custom_providers"]) == {"agnes"}
        env = than["env_providers"]
        assert set(env) == {"may_gpu"}
        assert env["may_gpu"]["base_url"] == "http://172.16.10.220:8000/v1"
        assert "api_key" not in env["may_gpu"] and "api_keys" not in env["may_gpu"]
        assert KHOA not in r.text

    def test_health_can_quyen_quan_tri(self, co, monkeypatch):
        """Endpoint này gửi request tới URL đã khai — để hở là thành máy dò mạng nội bộ."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import system
        monkeypatch.setenv("C2A_PROVIDER_MAY_GPU_URL", "http://172.16.10.220:8000")
        fake = _HttpTheoUrl(lambda url: _Resp(200, _models(1)))
        monkeypatch.setattr(co, "requests", fake)
        app = FastAPI()
        app.include_router(system.create_router("test"))
        r = TestClient(app).get("/api/v1/custom-providers/may_gpu/health")
        assert r.status_code in (401, 403)
        assert fake.calls == []
