"""Semantic Scholar — academic paper search (CS, engineering, medicine).

Free, no API key required. Rate limited to ~1 req/sec without key.
Covers 200M+ papers across all disciplines.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SS_API = "https://api.semanticscholar.org/graph/v1/paper/search"
HEADERS = {"Accept": "application/json"}


def semantic_scholar_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search Semantic Scholar for academic papers.

    Returns list of {title, snippet, url, source, year, citations} dicts.
    Empty list on failure or no results.
    """
    for attempt in range(2):
        try:
            with httpx.Client(timeout=10.0, headers=HEADERS) as client:
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
        break
    except Exception as exc:
        if attempt == 0 and "429" in str(exc):
            import time; time.sleep(2)
            continue
        logger.warning("Semantic Scholar search failed: %s", exc)
        return []

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
    return results
