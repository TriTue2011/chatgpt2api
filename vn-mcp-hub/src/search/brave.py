"""Brave Search API — independent web index, privacy-focused (US).

Free tier: 2,000 queries/month. Requires BRAVE_API_KEY env var.
Covers general web with its own crawler, not Google/Bing dependent.
"""

from __future__ import annotations

import logging
from typing import Any
import httpx

logger = logging.getLogger(__name__)

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


def brave_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    from src.sources_config import get_api_keys
    from src.search.limiter import (RateLimited, is_rate_limited,
                                    mark_key_limited, usable_keys)
    keys = usable_keys("brave", get_api_keys("brave"))  # nhiều account, bỏ key đang cooldown
    if not keys:
        return []  # không có key dùng được → để API khác gánh (không phải lỗi)

    data = None
    for api_key in keys:
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(
                    BRAVE_URL,
                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                    params={"q": query, "count": min(limit, 10)},
                )
                r.raise_for_status()
            data = r.json()
            break
        except Exception as exc:
            if is_rate_limited(exc):
                mark_key_limited("brave", api_key)  # key này hết quota → xoay account khác
                logger.info("Brave key hết quota (429) — xoay account kế")
                continue
            logger.warning("Brave search failed: %s", exc)
            return []
    if data is None:
        raise RateLimited("brave")  # mọi account đều limit → orchestrator nghỉ backend

    results: list[dict[str, Any]] = []
    web = data.get("web", {}).get("results") or []
    for w in web[:limit]:
        results.append({
            "title": w.get("title", ""),
            "snippet": (w.get("description") or "")[:400],
            "url": w.get("url", ""),
            "source": "Brave (US)",
        })
    logger.info("Brave: %d results", len(results))
    return results
