"""Semantic Scholar — academic paper search (CS, engineering, medicine).

Free, no API key required. Rate limited to ~1 req/sec without key.
Covers 200M+ papers across all disciplines.
"""

from __future__ import annotations

import logging, time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SS_API = "https://api.semanticscholar.org/graph/v1/paper/search"
HEADERS = {"Accept": "application/json"}

# Simple in-memory cache to avoid 429 rate limits (1 req/s without API key)
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CACHE_TTL = 60  # seconds


def semantic_scholar_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search Semantic Scholar for academic papers.

    Returns list of {title, snippet, url, source, year, citations} dicts.
    Uses simple cache to stay within rate limits.
    """
    # Check cache
    cache_key = f"{query}:{limit}"
    if cache_key in _cache:
        ts, cached = _cache[cache_key]
        if time.time() - ts < _CACHE_TTL:
            return cached

    # Retrieve API key if available
    from src.sources_config import get_api_keys
    from src.search.limiter import (RateLimited, is_rate_limited,
                                    mark_key_limited, usable_keys)
    # Xoay vòng account khi 1 key dính 429; "" = gọi không key (public-limit).
    keys = usable_keys("semantic_scholar", get_api_keys("semantic_scholar")) or [""]

    data = {}
    got = False
    for api_key in keys:
        headers = dict(HEADERS)
        if api_key:
            headers["x-api-key"] = api_key
        try:
            with httpx.Client(timeout=10.0, headers=headers) as client:
                r = client.get(
                    SS_API,
                    params={
                        "query": query,
                        "limit": min(limit, 10),
                        "fields": "title,year,abstract,citationCount,url",
                    },
                )
                r.raise_for_status()
                data = r.json()
            got = True
            break
        except Exception as exc:
            if is_rate_limited(exc):
                if api_key:
                    mark_key_limited("semantic_scholar", api_key)
                logger.info("Semantic Scholar 429 — đánh dấu limit, thử key kế (nếu có)")
                continue
            logger.warning("Semantic Scholar search failed: %s", exc)
            return []
    if not got:
        # Hết key dùng được / public-limit → báo orchestrator nghỉ backend này
        # (fallback sang API khác), không gọi lại + không sleep phí thời gian.
        raise RateLimited("semantic_scholar")

    results: list[dict[str, Any]] = []
    for paper in (data.get("data") or [])[:limit]:
        title = paper.get("title") or ""
        abstract = paper.get("abstract") or ""
        year = paper.get("year") or ""
        citations = paper.get("citationCount") or 0
        url = paper.get("url") or f"https://api.semanticscholar.org/paper/{paper.get('paperId','')}"
        snippet = abstract[:400] if abstract else ""
        if year:
            snippet = f"({year}, {citations} citations) {snippet}"
        results.append({
            "title": title,
            "snippet": snippet.strip(),
            "url": url,
            "source": "Semantic Scholar",
            "year": year,
            "citations": citations,
        })
    logger.info("Semantic Scholar: %d results for '%s'", len(results), query[:50])
    # Save to cache
    _cache[cache_key] = (time.time(), results)
    # Clean old entries periodically
    if len(_cache) > 100:
        now = time.time()
        _cache.clear()  # simple: clear all when too many
    return results
