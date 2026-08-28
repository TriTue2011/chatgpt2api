"""Endpoint tra cứu từ + đối chiếu Google — /api/dich/tra-cuu, /api/dich/google.

Kiểm phần ĐẤU NỐI (điều gì gọi điều gì, khi nào), không kiểm lại lõi: lõi từ
điển ở test_tu_dien.py, lõi Google ở test_google_dich.py.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.config as cfg  # noqa: E402
from api import dich as dich_api  # noqa: E402
from services import google_dich as gd  # noqa: E402

_LUOC_DO = """
CREATE TABLE words (id INTEGER PRIMARY KEY, word TEXT NOT NULL,
                    lang_code TEXT NOT NULL DEFAULT 'vi');
CREATE TABLE definitions (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          definition TEXT NOT NULL, pos TEXT, sub_pos TEXT,
                          definition_lang TEXT DEFAULT 'vi');
CREATE TABLE word_definitions (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               word_id INTEGER NOT NULL,
                               definition_id INTEGER NOT NULL, example TEXT);
CREATE TABLE pronunciations (id INTEGER PRIMARY KEY AUTOINCREMENT,
                             word_id INTEGER NOT NULL, ipa TEXT NOT NULL,
                             region TEXT);
"""


@pytest.fixture
def client(monkeypatch):
    """Client + DATA_DIR tạm có từ điển tí hon (chỉ mỗi từ 'stroke')."""
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        (data / "tudien").mkdir(parents=True)
        db = sqlite3.connect(data / "tudien" / "en-vi.db")
        db.executescript(_LUOC_DO)
        db.execute("INSERT INTO words (id, word, lang_code) VALUES (1,'stroke','en')")
        db.execute("INSERT INTO definitions (id, definition, pos) VALUES (1,'Đột quỵ.','N')")
        db.execute("INSERT INTO word_definitions (word_id, definition_id, example) "
                   "VALUES (1,1,'He had a stroke.')")
        db.commit(); db.close()
        monkeypatch.setattr(cfg, "DATA_DIR", data)
        monkeypatch.setattr(dich_api, "require_admin", lambda _a: {"role": "admin"})
        app = FastAPI()
        app.include_router(dich_api.create_router())
        yield TestClient(app)


@pytest.fixture(autouse=True)
def _tat_google():
    cu = cfg.config.data.get("dich_google")
    cfg.config.data["dich_google"] = {"bat": False}
    gd._nghi_toi = 0.0
    yield
    if cu is None:
        cfg.config.data.pop("dich_google", None)
    else:
        cfg.config.data["dich_google"] = cu


def test_tra_duoc_thi_tra_moi_nghia(client):
    r = client.get("/api/dich/tra-cuu", params={"q": "stroke", "src": "en"})
    assert r.status_code == 200
    d = r.json()
    assert d["co_tu_dien"] is True
    assert [n["vi"] for n in d["nghia"]] == ["Đột quỵ."]
    assert d["google"] == ""       # từ điển có rồi thì không hỏi Google


def test_google_tat_thi_khong_goi_du_tu_dien_khong_co(client):
    with mock.patch.object(gd, "dich") as mo:
        d = client.get("/api/dich/tra-cuu", params={"q": "biopsy", "src": "en"}).json()
    assert d["nghia"] == [] and d["google"] == ""
    mo.assert_not_called()


def test_tu_dien_khong_co_thi_hoi_google_khi_da_bat(client):
    cfg.config.data["dich_google"] = {"bat": True}
    with mock.patch.object(gd, "dich", return_value=("sinh thiết", "en")):
        d = client.get("/api/dich/tra-cuu", params={"q": "biopsy", "src": "en"}).json()
    assert d["nghia"] == []
    assert d["google"] == "sinh thiết"


def test_tieng_khong_co_tu_dien_van_tra_duoc_nho_google(client):
    """Nhật/Trung/Hàn chưa có từ điển tại chỗ — đây là lý do có nhánh Google."""
    cfg.config.data["dich_google"] = {"bat": True}
    with mock.patch.object(gd, "dich", return_value=("đột quỵ", "ja")):
        d = client.get("/api/dich/tra-cuu", params={"q": "脳卒中", "src": "ja"}).json()
    assert d["co_tu_dien"] is False
    assert d["google"] == "đột quỵ"


def test_google_loi_thi_o_google_trong_chu_khong_vo_ca_endpoint(client):
    cfg.config.data["dich_google"] = {"bat": True}
    with mock.patch.object(gd, "dich", side_effect=gd.LoiGoogle("bị chặn")):
        r = client.get("/api/dich/tra-cuu", params={"q": "biopsy", "src": "en"})
    assert r.status_code == 200
    assert r.json()["google"] == ""


def test_endpoint_google_tu_choi_khi_chua_bat(client):
    r = client.post("/api/dich/google", json={"q": "stroke", "target": "vi"})
    assert r.status_code == 400
