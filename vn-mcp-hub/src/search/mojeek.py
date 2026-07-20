"""Mojeek Search API — independent crawler, UK-based.

Free tier available. Requires MOJEEK_API_KEY env var.
Mojeek has its own independent index (not Google/Bing), ~6 billion pages.
Strong on UK/European content — fills the regional search gap.
"""

from __future__ import annotations

import logging
from typing import Any
import httpx

logger = logging.getLogger(__name__)

MOJEEK_URL = "https://api.mojeek.com/search"


def mojeek_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    from src.sources_config import get_api_keys
    from src.search.limiter import (RateLimited, is_rate_limited,
                                    mark_key_limited, usable_keys)
    keys = usable_keys("mojeek", get_api_keys("mojeek"))
    if not keys:
        return []

    data = None
    for api_key in keys:
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(
                    MOJEEK_URL,
                    headers={"Accept": "application/json"},
                    params={"q": query, "api_key": api_key, "results": min(limit, 10)},
                )
                r.raise_for_status()
            data = r.json()
            break
        except Exception as exc:
            if is_rate_limited(exc):
                mark_key_limited("mojeek", api_key)
                logger.info("Mojeek key hết quota (429) — xoay account kế")
                continue
            logger.warning("Mojeek search failed: %s", exc)
            return []
    if data is None:
        raise RateLimited("mojeek")

    results: list[dict[str, Any]] = []
    for w in (data.get("results") or [])[:limit]:
        results.append({
            "title": w.get("title", ""),
            "snippet": (w.get("desc") or w.get("description") or "")[:400],
            "url": w.get("url", ""),
            "source": "Mojeek (UK)",
        })
    logger.info("Mojeek: %d results", len(results))
    return results
