"""RAG retriever — query Chroma vector DB for kb_* MCPs.

Each knowledge base lives in its own Chroma collection (e.g. "dien_nuoc").
The retriever loads a single embedding model once and reuses it across all
collections. First query against a collection opens it lazily.

Uses fastembed (ONNX runtime, ~200MB) instead of sentence-transformers
(torch, ~3GB) to keep the Docker image under 5GB.

Designed to fail soft: if Chroma can't initialise (missing model, missing
data dir), `query()` returns an empty list instead of raising — the kb_*
MCPs surface a friendly error to the LLM rather than crashing the hub.
"""

from __future__ import annotations

import logging
import threading
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# All collections share one persist dir; ingest.py writes here too.
CHROMA_DB_PATH = Path("/app/chroma_db")

# Kho vector gte (03/10/2026). Đo trên 140 câu hỏi đặt từ 140 đoạn THẬT của kho: đoạn đúng lọt 4 đoạn đầu —
# MiniLM 25,7%, gte 62,1% (đứng đầu: 10,0% → 40,0%). gte 768 chiều, MiniLM 384 — không trộn được trong một
# kho, nên gte nằm ở THƯ MỤC RIÊNG, cùng tên kho; kho MiniLM cũ để nguyên làm đường lùi. `chuyen_gte.py` chép
# xong mới đặt dấu `.xong` — có dấu thì mọi đường đọc/ghi tự sang gte (`duong_kho`), không cần khởi động lại.
CHROMA_GTE_PATH = Path("/app/data/chroma_gte")
DAU_GTE = CHROMA_GTE_PATH / ".xong"
#: c2a (cùng container) giữ model gte — GPU .220 lùi CPU — xem api/system.py `/api/nhung`.
C2A_NHUNG_URL = os.getenv("C2A_NHUNG_URL", "http://127.0.0.1:80/api/nhung")
#: Xếp lại 20 đoạn gte gần nhất bằng cross-encoder trên GPU (c2a `/api/xep_lai`, chỉ GPU) rồi trộn thứ hạng.
#: Đo 03/10/2026: đoạn đúng lọt 4 đầu 62,1% → 67,1%. Không xếp được (GPU hỏng) thì giữ thứ tự gte.
C2A_XEP_URL = os.getenv("C2A_XEP_URL", "http://127.0.0.1:80/api/xep_lai")
UNG_VIEN_XEP = 20


def _goi_c2a(url: str, body: dict, timeout: float) -> dict:
    import json as _json
    import urllib.request
    req = urllib.request.Request(url, data=_json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {os.getenv('CHATGPT2API_AUTH_KEY', '')}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — URL nội bộ cố định
        return _json.loads(r.read().decode())


def _thu_tu_xep_lai(cau: str, docs: list[str]) -> list[int] | None:
    """Thứ tự mới (chỉ số) sau khi trộn gte với xếp lại; None = giữ nguyên. Trộn = cộng nghịch đảo thứ hạng
    (k=60), như `services/xep_lai.tron` của c2a — trộn hơn dùng riêng xếp lại (67,1% so với 62,9%)."""
    try:
        d = _goi_c2a(C2A_XEP_URL, {"cau": cau, "doan": docs}, timeout=10)["diem"]
    except Exception as exc:  # noqa: BLE001 — xếp lại là phần thêm
        logger.info("RAG: bỏ xếp lại (%s)", str(exc)[:120])
        return None
    if len(d) != len(docs):
        return None
    hang = {j: r for r, j in enumerate(sorted(range(len(d)), key=lambda j: -d[j]))}
    return sorted(range(len(docs)), key=lambda i: -(1 / (60 + i) + 1 / (60 + hang[i])))


def dung_gte() -> bool:
    return DAU_GTE.is_file()


def duong_kho() -> Path:
    return CHROMA_GTE_PATH if dung_gte() else CHROMA_DB_PATH

# Light, multilingual model — good enough for VN + EN technical content.
# fastembed downloads this to its cache on first use (~120MB).
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Default top-k chunks returned per query. Tuned to fit ~2000 tokens.
DEFAULT_TOP_K = 4


class _FastEmbedFn:
    """Custom ChromaDB embedding function backed by fastembed (ONNX, no torch)."""

    def __init__(self, model_name: str = EMBED_MODEL) -> None:
        self._model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self._model_name)

    def __call__(self, input: list[str]) -> list[list[float]]:
        self._load()
        return [e.tolist() for e in self._model.embed(input)]

    def embed_documents(self, *args, **kwargs) -> list[list[float]]:
        """ChromaDB v0.5+ batch embedding. Handles various call signatures."""
        docs = args[0] if args else kwargs.get("texts", kwargs.get("input", []))
        if isinstance(docs, str):
            docs = [docs]
        self._load()
        try:
            return [e.tolist() for e in self._model.embed(docs)]
        except Exception:
            return [e.tolist() for e in self._model.embed(list(docs))]

    def embed_query(self, *args, **kwargs) -> list[list[float]]:
        """ChromaDB v0.5+ single-query embedding. Returns List[List[float]]."""
        query_text = ""
        if args:
            q = args[0]
            if isinstance(q, list) and q:
                query_text = str(q[0])
            elif isinstance(q, str):
                query_text = q
        if not query_text:
            query_text = str(kwargs.get("text", "") or kwargs.get("input", "") or "")
            if isinstance(query_text, list):
                query_text = str(query_text[0]) if query_text else ""
        if not query_text:
            return [[0.0] * 384]
        self._load()
        result = list(self._model.embed([query_text]))
        return [result[0].tolist()] if result else [[0.0] * 384]

    def name(self) -> str:
        return self._model_name


class _GteFn:
    """Hàm nhúng ChromaDB gọi c2a `/api/nhung` (gte). Lỗi thì RAISE — retriever log rồi trả rỗng (đường web
    lo tiếp), không âm thầm nhúng bằng model khác: vector khác không gian thì kết quả sai mà không ai biết."""

    LO = 32

    def __call__(self, input: list[str]) -> list[list[float]]:
        return self._nhung(list(input))

    def _nhung(self, texts: list[str]) -> list[list[float]]:
        ra: list[list[float]] = []
        for i in range(0, len(texts), self.LO):
            ra += _goi_c2a(C2A_NHUNG_URL, {"texts": texts[i:i + self.LO]}, timeout=120)["vectors"]
        return ra

    def embed_documents(self, *args, **kwargs) -> list[list[float]]:
        docs = args[0] if args else kwargs.get("texts", kwargs.get("input", []))
        return self._nhung([docs] if isinstance(docs, str) else list(docs))

    def embed_query(self, *args, **kwargs) -> list[list[float]]:
        q = args[0] if args else kwargs.get("text", kwargs.get("input", ""))
        return self._nhung([q] if isinstance(q, str) else list(q))

    def name(self) -> str:
        return "c2a-gte"


class RAGRetriever:
    """Singleton-ish retriever shared by all kb_* MCPs.

    Lazy: doesn't load the embedding model until the first query, so the
    hub starts fast even if RAG is never used.
    """

    _instance: "RAGRetriever | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._client = None
        self._embed_fn = None
        self._duong: Path | None = None
        self._collections: dict[str, Any] = {}

    @classmethod
    def get(cls) -> "RAGRetriever":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _ensure_loaded(self) -> bool:
        """Load Chroma client + embedding model on first use. Returns False on failure.
        Kho gte vừa chép xong (có dấu `.xong`) thì nạp lại sang kho đó ngay lượt sau."""
        duong = duong_kho()
        if self._client is not None and self._duong == duong:
            return True
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(duong))
            self._embed_fn = _GteFn() if duong == CHROMA_GTE_PATH else _FastEmbedFn(EMBED_MODEL)
            self._collections = {}
            self._duong = duong
            logger.info("RAG: chroma loaded from %s (%s)", duong, self._embed_fn.name())
            return True
        except Exception as exc:
            logger.error("RAG: failed to load chroma/embeddings: %s", exc)
            return False

    def _get_collection(self, name: str):
        # _ensure_loaded TRƯỚC bộ đệm: vừa chuyển sang kho gte thì bộ đệm cũ (kho MiniLM) phải bỏ.
        if not self._ensure_loaded():
            return None
        if name in self._collections:
            return self._collections[name]
        try:
            col = self._client.get_or_create_collection(
                name=name,
                embedding_function=self._embed_fn,
            )
            self._collections[name] = col
            return col
        except Exception as exc:
            logger.error("RAG: get_or_create_collection(%s) failed: %s", name, exc)
            return None

    def query(self, collection: str, text: str, top_k: int = DEFAULT_TOP_K,
              where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return top-k matching chunks as a list of {text, source, score}.

        ``where`` lọc theo metadata TRƯỚC khi xếp hạng. Cần cho kho gộp nhiều
        lớp: kho SGK chứa cả 12 lớp, mà embedding không mang thông tin "lớp
        mấy" — nội dung các lớp dùng chung từ vựng môn học. Đo thật trên
        ``kb_giao_duc`` (585 chunk, 12 lớp): hỏi kèm tên lớp trong câu chỉ ra
        đúng lớp–môn 4/12 lần; nhồi thêm "lop=9 mon=toan" vào câu còn tệ hơn
        (0/8) vì chuỗi kĩ thuật làm loãng vector. Lọc metadata: 12/12.
        """
        col = self._get_collection(collection)
        if col is None:
            return []
        xep = self._duong == CHROMA_GTE_PATH
        try:
            kw: dict[str, Any] = {"query_texts": [text], "n_results": max(top_k, UNG_VIEN_XEP) if xep else top_k}
            if where:
                kw["where"] = where
            res = col.query(**kw)
        except Exception as exc:
            logger.warning("RAG: query(%s) failed: %s", collection, exc)
            return []

        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        if xep and len(docs) > top_k:
            thu_tu = _thu_tu_xep_lai(text, list(docs))
            if thu_tu:
                docs = [docs[i] for i in thu_tu]
                metas = [metas[i] for i in thu_tu] if len(metas) == len(thu_tu) else metas
                dists = [dists[i] for i in thu_tu] if len(dists) == len(thu_tu) else dists
        docs, metas, dists = docs[:top_k], metas[:top_k], dists[:top_k]
        logger.info("RAG query(%s): '%s' -> %d docs, distances=%s",
                    collection, text[:50], len(docs),
                    [round(d, 3) if d else None for d in dists[:3]] if dists else [])
        out: list[dict[str, Any]] = []
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            dist = dists[i] if i < len(dists) else None
            out.append({
                "text": doc,
                "source": (meta or {}).get("source", "unknown"),
                "score": 1.0 - float(dist) if dist is not None else None,
            })
        return out

    def collection_stats(self, collection: str) -> dict[str, Any]:
        """Useful for admin/debug — returns document count, etc."""
        col = self._get_collection(collection)
        if col is None:
            return {"available": False}
        try:
            count = col.count()
        except Exception:
            count = -1
        return {"available": True, "count": count}


def query(collection: str, text: str, top_k: int = DEFAULT_TOP_K,
          where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Module-level shortcut so kb_* MCPs can `from src.rag.retriever import query`."""
    return RAGRetriever.get().query(collection, text, top_k, where=where)


def format_results(results: list[dict[str, Any]]) -> str:
    """Convert hits into a markdown block ready to feed back to the LLM."""
    if not results:
        return "Không tìm thấy thông tin liên quan trong kho tri thức."
    lines = []
    for i, r in enumerate(results, 1):
        src = r.get("source") or "unknown"
        text = (r.get("text") or "").strip()
        if len(text) > 1500:
            text = text[:1500] + "…"
        lines.append(f"## Kết quả {i} — nguồn: `{src}`\n\n{text}")
    return "\n\n---\n\n".join(lines)
