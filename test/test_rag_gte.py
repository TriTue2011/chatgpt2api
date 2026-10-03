"""RAG của vn-mcp-hub chuyển MiniLM → gte (03/10/2026). Không cần chromadb thật, không gọi mạng.

Đo trên 140 câu hỏi đặt từ 140 đoạn thật của kho: đoạn đúng lọt 4 đoạn đầu — MiniLM 25,7%, gte 62,1%.
"""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")
HUB = Path(__file__).resolve().parents[1] / "vn-mcp-hub"
if str(HUB) not in sys.path:
    sys.path.insert(0, str(HUB))

from src.rag import chuyen_gte, retriever as rt  # noqa: E402


class _Kho:
    def __init__(self, ten, docs=None, metadata=None):
        self.name, self.metadata = ten, metadata
        self.d = dict(docs or {})          # id -> (doc, meta)

    def get(self, include=None):
        ids = list(self.d)
        return {"ids": ids, "documents": [self.d[i][0] for i in ids], "metadatas": [self.d[i][1] for i in ids]}

    def upsert(self, ids, documents, metadatas=None):
        for n, i in enumerate(ids):
            self.d[i] = (documents[n], (metadatas or [None] * len(ids))[n])

    def count(self):
        return len(self.d)


class _Client:
    def __init__(self, kho=None, path=""):
        self.kho, self.path = {k.name: k for k in (kho or [])}, path

    def list_collections(self):
        return list(self.kho)

    def get_collection(self, name):
        return self.kho[name]

    def get_or_create_collection(self, name, embedding_function=None, metadata=None):
        self.kho.setdefault(name, _Kho(name, metadata=metadata))
        self.kho[name].fn = embedding_function
        return self.kho[name]


def test_chuyen_du_moi_kho_va_chay_lai_khong_nhan_doi():
    cu = _Client([_Kho("kb_giao_duc", {f"a{i}": (f"đoạn {i}", {"source": "x"}) for i in range(150)}, {"hnsw:space": "l2"}),
                  _Kho("trong", {})])
    moi = _Client()
    kq = chuyen_gte.chuyen(cu, moi, fn="gte", dat_dau=False)
    assert kq == {"kho": {"kb_giao_duc": [150, 150], "trong": [0, 0]}, "du": True}
    assert moi.kho["kb_giao_duc"].fn == "gte" and moi.kho["kb_giao_duc"].metadata == {"hnsw:space": "l2"}
    assert chuyen_gte.chuyen(cu, moi, fn="gte", dat_dau=False)["kho"]["kb_giao_duc"] == [150, 150]


def test_chi_dat_dau_khi_du(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "DAU_GTE", tmp_path / ".xong")
    cu = _Client([_Kho("k", {"a": ("đoạn", None)})])

    class _Hong(_Client):
        def get_or_create_collection(self, name, embedding_function=None, metadata=None):
            k = super().get_or_create_collection(name, embedding_function, metadata)
            k.upsert = lambda **kw: None          # ghi không vào → thiếu đoạn
            return k
    assert chuyen_gte.chuyen(cu, _Hong(), fn="gte")["du"] is False and not (tmp_path / ".xong").exists()
    assert chuyen_gte.chuyen(cu, _Client(), fn="gte")["du"] is True and (tmp_path / ".xong").exists()


def test_retriever_tu_sang_kho_gte_khi_co_dau_va_bo_bo_dem_cu(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "CHROMA_DB_PATH", tmp_path / "cu")
    monkeypatch.setattr(rt, "CHROMA_GTE_PATH", tmp_path / "gte")
    monkeypatch.setattr(rt, "DAU_GTE", tmp_path / "gte" / ".xong")
    monkeypatch.setitem(sys.modules, "chromadb", types.SimpleNamespace(
        PersistentClient=lambda path: _Client([_Kho("kb", {})], path=path)))
    r = rt.RAGRetriever()
    assert r._get_collection("kb") is not None and r._client.path.endswith("cu")
    assert not isinstance(r._embed_fn, rt._GteFn)
    (tmp_path / "gte").mkdir()
    (tmp_path / "gte" / ".xong").write_text("{}")
    col = r._get_collection("kb")
    assert r._client.path.endswith("gte") and isinstance(r._embed_fn, rt._GteFn), "có dấu là sang gte, khỏi khởi động lại"
    assert col.fn is r._embed_fn, "không trả kho cũ còn trong bộ đệm"


def test_ham_nhung_gte_goi_c2a_theo_lo(monkeypatch):
    goi: list[int] = []

    class _Tra:
        def __init__(self, n):
            self.n = n

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"vectors": [[0.1, 0.2]] * self.n}).encode()

    def _mo(req, timeout=0):
        n = len(json.loads(req.data)["texts"])
        goi.append(n)
        assert req.headers["Authorization"] == "Bearer test-auth"
        return _Tra(n)
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _mo)
    assert len(rt._GteFn()([f"đoạn {i}" for i in range(70)])) == 70 and goi == [32, 32, 6]
    assert rt._GteFn().embed_query("câu hỏi") == [[0.1, 0.2]]


def test_endpoint_nhung(monkeypatch):
    from unittest import mock

    import numpy as np
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import system
    from services import nhung
    monkeypatch.setattr(nhung, "vec", lambda chu: np.array([0.5, 0.25], dtype=np.float32))
    monkeypatch.setattr(nhung, "ten_model", lambda: "gte|gpu")
    app = FastAPI()
    with mock.patch("api.system.require_admin", lambda *a, **k: None):
        app.include_router(system.create_router("test"))
        c = TestClient(app)
        r = c.post("/api/nhung", json={"texts": ["a", "b"]})
        assert r.status_code == 200 and r.json() == {"model": "gte|gpu", "vectors": [[0.5, 0.25], [0.5, 0.25]]}
        assert c.post("/api/nhung", json={"texts": []}).status_code == 400
