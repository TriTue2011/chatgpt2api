"""Hybrid RAG + web search fallback for kb_* MCPs.

When the local knowledge base (Chroma) returns empty or low-quality results,
this module falls back to DuckDuckGo and Wikipedia so the LLM always gets
something useful — no LLM-merge, just raw text from both sources.

Usage in kb_* tools:
    results = hybrid_query(COLLECTION, question, top_k)
    return format_hybrid_results(results)
"""

from __future__ import annotations

import logging
from typing import Any

from src.rag.retriever import RAGRetriever, DEFAULT_TOP_K

logger = logging.getLogger(__name__)

# If RAG returns fewer chunks than this, we fall back to web search.
MIN_RAG_CHUNKS = 2


def hybrid_query(collection: str, text: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """Query RAG + optional web search fallback.

    Returns:
        {"rag": [...], "web": [...], "total": int} — caller can format however it likes.
        web is empty list if RAG had enough good results.
    """
    retriever = RAGRetriever.get()
    rag_results = retriever.query(collection, text, top_k)

    # Decide whether to fall back to web search
    need_web = _should_search_web(retriever, collection, rag_results)

    web_results: list[dict[str, Any]] = []
    if need_web:
        web_results = _fallback_search(text)
        logger.info("Hybrid(%s): RAG=%d, web=%d", collection, len(rag_results), len(web_results))

    return {
        "rag": rag_results,
        "web": web_results,
        "total": len(rag_results) + len(web_results),
    }


def _should_search_web(retriever: RAGRetriever, collection: str, rag: list[dict[str, Any]]) -> bool:
    """True if RAG is insufficient and we should try web search."""
    # Empty collection — definitely search
    stats = retriever.collection_stats(collection)
    if not stats.get("available") or stats.get("count", 0) == 0:
        return True

    # Too few results
    if len(rag) < MIN_RAG_CHUNKS:
        return True

    # All results have low relevance
    scores = [r.get("score") for r in rag if r.get("score") is not None]
    if scores and all(s < 0.5 for s in scores):
        return True

    return False


def _fallback_search(query: str) -> list[dict[str, Any]]:
    """Run DuckDuckGo + Wikipedia search in parallel.

    Returns up to 10 results total (5 DDG + 5 Wiki), each as {title, snippet, url, source}.
    """
    search_results: list[dict[str, Any]] = []
    try:
        from src.search.orchestrator import federated_search as _fs
        search_results = _fs(query, limit_per_source=3)
    except Exception as exc:
        logger.warning("Hybrid: federated search fallback failed: %s", exc)

    return search_results


def format_hybrid_results(result: dict[str, Any]) -> str:
    """Format hybrid query results into a markdown block for the LLM."""
    if result["total"] == 0:
        return "Không tìm thấy thông tin liên quan trong kho tri thức hay trên web."

    parts: list[str] = []

    rag = result.get("rag") or []
    if rag:
        from src.rag.retriever import format_results
        parts.append(f"## Kho tri thức ({len(rag)} kết quả)\n\n{format_results(rag)}")

    web = result.get("web") or []
    if web:
        from src.search.orchestrator import format_federated_results
        parts.append(format_federated_results(web))

    return "\n\n---\n\n".join(parts)
