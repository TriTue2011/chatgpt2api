"""API vn-translate — kiểm HỢP ĐỒNG LibreTranslate + tầng thuật ngữ.

Engine thật (NLLB) không nạp trong test: thay bằng engine giả dịch
"<đích>:<chữ>" — đủ để khẳng định (1) khuôn phản hồi đúng LibreTranslate,
(2) thuật ngữ đi bằng BẢNG chứ không qua engine, (3) tự nhận diện ngành.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.engine import KhongCoNgonNgu


class EngineGia:
    def __init__(self):
        self.da_nhan: list[str] = []

    def dich(self, texts, nguon, dich):
        if nguon not in main.ISO2FLORES or dich not in main.ISO2FLORES:
            raise KhongCoNgonNgu(f"{nguon}/{dich} is not supported")
        self.da_nhan.extend(texts)
        return [f"{dich}:{t}" for t in texts]

    def khoi_dong(self):
        pass


@pytest.fixture()
def client(monkeypatch):
    gia = EngineGia()
    monkeypatch.setattr(main, "engine", gia)
    c = TestClient(main.app)
    c.engine = gia
    return c


# ── Hợp đồng LibreTranslate ─────────────────────────────────────────────────

def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_languages_dung_khuon(client):
    ds = client.get("/languages").json()
    ma = [x["code"] for x in ds]
    assert "vi" in ma and "en" in ma
    assert all(set(x) >= {"code", "name", "targets"} for x in ds)


def test_translate_chuoi_va_lo(client):
    r = client.post("/translate", json={"q": "hello", "source": "en", "target": "vi"})
    assert r.json()["translatedText"] == "vi:hello"
    r = client.post("/translate", json={"q": ["a", "b"], "source": "en", "target": "vi"})
    assert r.json()["translatedText"] == ["vi:a", "vi:b"]


def test_translate_form_nhu_json(client):
    r = client.post("/translate", data={"q": "hello", "source": "en", "target": "vi"})
    assert r.json()["translatedText"] == "vi:hello"


def test_thieu_tham_so_tra_400_kem_error(client):
    r = client.post("/translate", json={"q": "x", "target": "vi"})
    assert r.status_code == 400 and "error" in r.json()


def test_auto_tra_detectedLanguage(client):
    r = client.post("/translate", json={"q": "xin chào cả nhà mình hôm nay",
                                        "source": "auto", "target": "en"}).json()
    assert r["translatedText"].startswith("en:")
    assert r["detectedLanguage"]["language"] == "vi"


def test_ngon_ngu_la_tra_400(client):
    r = client.post("/translate", json={"q": "x", "source": "xx", "target": "vi"})
    assert r.status_code == 400


def test_detect(client):
    r = client.post("/detect", json={"q": "xin chào các bạn thân mến của tôi"}).json()
    assert r[0]["language"] == "vi" and r[0]["confidence"] > 0


# ── Tầng thuật ngữ chuyên ngành ─────────────────────────────────────────────

def test_thuat_ngu_dich_bang_bang_khong_qua_engine(client):
    """'circuit breaker' + 'relay' (≥2 mục điện tử) → bảng áp: bản dịch chứa
    'áp-tô-mát', và thuật ngữ CHƯA TỪNG được gửi cho engine."""
    r = client.post("/translate", json={
        "q": "Install the circuit breaker next to the relay",
        "source": "en", "target": "vi"}).json()
    assert "áp-tô-mát" in r["translatedText"]
    assert "rơ-le" in r["translatedText"]
    assert "Điện tử" in r.get("nganh", [])
    assert all("circuit breaker" not in x for x in client.engine.da_nhan)


def test_mot_thuat_ngu_don_le_khong_keo_ca_bang(client):
    """Dưới ngưỡng 2 mục thì không áp — chữ "relay" lạc trong câu thường không
    biến cả câu thành văn bản điện tử."""
    r = client.post("/translate", json={
        "q": "please relay this message", "source": "en", "target": "vi"}).json()
    assert "nganh" not in r
    assert "rơ-le" not in r["translatedText"]


def test_huong_khong_co_bang_thi_bo_qua(client):
    r = client.post("/translate", json={
        "q": "Install the circuit breaker next to the relay",
        "source": "en", "target": "ja"}).json()
    assert r["translatedText"].startswith("ja:")
    assert "nganh" not in r
