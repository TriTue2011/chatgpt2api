"""Chép MỌI kho RAG từ MiniLM (`CHROMA_DB_PATH`) sang gte (`CHROMA_GTE_PATH`), rồi đặt dấu `.xong`.

Đo 03/10/2026 (140 câu hỏi đặt từ 140 đoạn thật): đoạn đúng lọt 4 đoạn đầu — MiniLM 25,7%, gte 62,1%.
Chạy lại được nhiều lần: đoạn đã có (cùng id) thì bỏ qua. Dấu `.xong` CHỈ đặt khi mọi kho chép đủ — có dấu là
`retriever.duong_kho` chuyển mọi đọc/ghi sang gte; kho cũ để nguyên (xoá dấu là quay về MiniLM).

    cd /app/mcp_hub && /app/.venv/bin/python -m src.rag.chuyen_gte
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

LO = 64


def _ten(col: Any) -> str:
    return col if isinstance(col, str) else col.name   # chromadb ≥0.6 trả tên, bản cũ trả object


def chuyen(cu_client: Any = None, moi_client: Any = None, fn: Any = None, *, dat_dau: bool = True) -> dict[str, Any]:
    """Trả {"kho": {tên: [số đoạn cũ, số đoạn gte]}, "du": bool}. Tham số client/fn cho test; mặc định là kho thật."""
    from src.rag import retriever as rt

    if cu_client is None or moi_client is None:
        import chromadb
        cu_client = cu_client or chromadb.PersistentClient(path=str(rt.CHROMA_DB_PATH))
        rt.CHROMA_GTE_PATH.mkdir(parents=True, exist_ok=True)
        moi_client = moi_client or chromadb.PersistentClient(path=str(rt.CHROMA_GTE_PATH))
    fn = fn or rt._GteFn()
    bao: dict[str, list[int]] = {}
    for col in cu_client.list_collections():
        ten = _ten(col)
        nguon = cu_client.get_collection(name=ten)
        d = nguon.get(include=["documents", "metadatas"])
        meta = {k: v for k, v in (nguon.metadata or {}).items() if v is not None} or None
        dich = moi_client.get_or_create_collection(name=ten, embedding_function=fn, metadata=meta)
        co = set(dich.get(include=[])["ids"])
        moi = [i for i, doc in enumerate(d["documents"]) if d["ids"][i] not in co and doc]
        t = time.time()
        for a in range(0, len(moi), LO):
            phan = moi[a:a + LO]
            metas = [d["metadatas"][i] for i in phan]
            dich.upsert(ids=[d["ids"][i] for i in phan], documents=[d["documents"][i] for i in phan],
                        **({"metadatas": metas} if all(metas) else {}))
        so_cu = sum(1 for x in d["documents"] if x)
        bao[ten] = [so_cu, dich.count()]
        logger.info("chuyen_gte %s: %d đoạn mới, %d/%d (%.0fs)", ten, len(moi), dich.count(), so_cu, time.time() - t)
    du = all(moi >= cu for cu, moi in bao.values())
    if du and dat_dau:
        rt.DAU_GTE.write_text(json.dumps({"luc": time.time(), "kho": bao}, ensure_ascii=False), encoding="utf-8")
    return {"kho": bao, "du": du}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    kq = chuyen()
    print(json.dumps(kq, ensure_ascii=False))
    raise SystemExit(0 if kq["du"] else 1)
