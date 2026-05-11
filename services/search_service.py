"""
Search Service — cấu hình chọn backend search ngay trong chatgpt2api.

Port pattern from 9router web search providers.
Supports: chatgpt (built-in), gemini (Google Grounding), serper, searxng, brave.

Flow:
1. auto_detect: analyze user intent → cần search không?
2. If needed → call configured search backend
3. Format results → inject vào messages
4. Send enriched messages to LLM
"""

from __future__ import annotations

import json
import re
from typing import Any

from curl_cffi import requests

from services.config import config
from utils.log import logger

# Keywords that trigger search intent detection
SEARCH_INTENT_PATTERNS = [
    r"(?:giá|bao nhiêu|mấy nghìn|mấy triệu)\s+\w+",
    r"(?:hôm nay|hôm qua|tuần này|tháng này|năm nay)\s+\w+",
    r"(?:thời tiết|nhiệt độ|dự báo)\s+\w+",
    r"(?:tin tức|tin mới|báo chí)\s+\w+",
    r"(?:kết quả|tỉ số|trận đấu)\s+\w+",
    r"\b(?:search|tìm kiếm|tìm hiểu|tra cứu)\b",
    r"\b(?:ai là|ở đâu|khi nào|thế nào|làm sao)\b",
]


class SearchBackend:
    """Base class for search backends."""

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        raise NotImplementedError


class ChatGPTSearch(SearchBackend):
    """Passthrough — let ChatGPT handle search internally (built-in web search tool)."""

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        return []  # ChatGPT handles search internally, no injection needed


class SerperSearch(SearchBackend):
    """Serper.dev Google Search API (free 2,500 req/month)."""

    BASE_URL = "https://google.serper.dev/search"

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        provider_config = (config.data.get("providers") or {}).get("serper") or {}
        api_key = str(provider_config.get("api_key") or "").strip()

        if not api_key:
            logger.warning({"event": "serper_no_api_key"})
            return []

        try:
            resp = requests.post(
                self.BASE_URL,
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": max_results},
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning({"event": "serper_error", "status": resp.status_code})
                return []

            data = resp.json()
            results: list[dict[str, str]] = []
            for item in (data.get("organic") or [])[:max_results]:
                results.append({
                    "title": str(item.get("title") or ""),
                    "snippet": str(item.get("snippet") or ""),
                    "url": str(item.get("link") or ""),
                })
            return results

        except Exception as exc:
            logger.warning({"event": "serper_exception", "error": str(exc)})
            return []


class SearXNGSearcher(SearchBackend):
    """SearXNG self-hosted search (no API key, no limits)."""

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        provider_config = (config.data.get("providers") or {}).get("searxng") or {}
        base_url = str(provider_config.get("base_url") or "http://localhost:8080").strip().rstrip("/")

        try:
            resp = requests.get(
                f"{base_url}/search",
                params={"q": query, "format": "json", "categories": "general"},
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning({"event": "searxng_error", "status": resp.status_code})
                return []

            data = resp.json()
            results: list[dict[str, str]] = []
            for item in (data.get("results") or [])[:max_results]:
                results.append({
                    "title": str(item.get("title") or ""),
                    "snippet": str(item.get("content") or item.get("snippet") or ""),
                    "url": str(item.get("url") or ""),
                })
            return results

        except Exception as exc:
            logger.warning({"event": "searxng_exception", "error": str(exc)})
            return []


class BraveSearch(SearchBackend):
    """Brave Search API (free 2,000 req/month)."""

    BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        provider_config = (config.data.get("providers") or {}).get("brave") or {}
        api_key = str(provider_config.get("api_key") or "").strip()

        if not api_key:
            logger.warning({"event": "brave_no_api_key"})
            return []

        try:
            resp = requests.get(
                self.BASE_URL,
                headers={
                    "X-Subscription-Token": api_key,
                    "Accept": "application/json",
                },
                params={"q": query, "count": max_results},
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning({"event": "brave_error", "status": resp.status_code})
                return []

            data = resp.json()
            results: list[dict[str, str]] = []
            for item in (data.get("web", {}).get("results") or [])[:max_results]:
                results.append({
                    "title": str(item.get("title") or ""),
                    "snippet": str(item.get("description") or ""),
                    "url": str(item.get("url") or ""),
                })
            return results

        except Exception as exc:
            logger.warning({"event": "brave_exception", "error": str(exc)})
            return []


class GeminiGrounding(SearchBackend):
    """Google Search grounding via Gemini API (free tier: 15 RPM per key).

    Supports multiple API keys — round-robin when one hits rate limit.
    Config in config.json:
      "providers": {
        "gemini_free": {
          "api_key": "AIza...",        // single key
          "api_keys": ["AIza...", ...]  // or multiple keys (auto round-robin)
        }
      }
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    def __init__(self):
        self._key_index = 0
        self._rate_limited: dict[str, float] = {}  # key → locked_until timestamp

    def _get_keys(self) -> list[str]:
        provider_config = (config.data.get("providers") or {}).get("gemini_free") or {}
        single = str(provider_config.get("api_key") or "").strip()
        multi = provider_config.get("api_keys") or []
        if not isinstance(multi, list):
            multi = []
        keys = [k.strip() for k in multi if k.strip()]
        if single and single not in keys:
            keys.insert(0, single)
        return keys

    def _next_key(self) -> str | None:
        keys = self._get_keys()
        if not keys:
            return None
        import time
        now = time.time()
        for _ in range(len(keys)):
            key = keys[self._key_index % len(keys)]
            self._key_index += 1
            locked_until = self._rate_limited.get(key, 0)
            if now < locked_until:
                continue
            return key
        return keys[0]  # all limited, return first anyway

    def _mark_limited(self, key: str) -> None:
        import time
        self._rate_limited[key] = time.time() + 60
        logger.warning({"event": "gemini_rate_limited", "key_prefix": key[:10]})

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        api_key = self._next_key()
        if not api_key:
            logger.warning({"event": "gemini_no_api_key"})
            return []

        try:
            resp = requests.post(
                f"{self.BASE_URL}?key={api_key}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": query}]}], "tools": [{"google_search": {}}]},
                timeout=30,
            )

            if resp.status_code == 429:
                self._mark_limited(api_key)
                return self.search(query, max_results)  # retry with next key

            if resp.status_code != 200:
                logger.warning({"event": "gemini_error", "status": resp.status_code})
                return []

            data = resp.json()
            results: list[dict[str, str]] = []
            candidates = data.get("candidates") or []
            for c in candidates:
                grounding = c.get("groundingMetadata") or {}
                chunks = grounding.get("groundingChunks") or []
                sources = grounding.get("webSearchQueries") or []
                for chunk in chunks[:max_results]:
                    web = chunk.get("web") or {}
                    results.append({
                        "title": str(web.get("title") or (sources[0] if sources else query)),
                        "snippet": str(web.get("snippet") or ""),
                        "url": str(web.get("uri") or ""),
                    })
            return results[:max_results]

        except Exception as exc:
            logger.warning({"event": "gemini_exception", "error": str(exc)})
            return []


# Backend registry
SEARCH_BACKENDS: dict[str, SearchBackend] = {
    "chatgpt": ChatGPTSearch(),
    "gemini": GeminiGrounding(),
    "serper": SerperSearch(),
    "searxng": SearXNGSearcher(),
    "brave": BraveSearch(),
}


def needs_search(messages: list[dict[str, Any]]) -> bool:
    """Analyze last user message to detect search intent.

    Returns True if the user is likely asking for real-time information.
    """
    if not messages:
        return False

    # Get last user message
    last_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_text = str(msg.get("content") or "").strip().lower()
            break

    if not last_text:
        return False

    # Check against search intent patterns
    for pattern in SEARCH_INTENT_PATTERNS:
        if re.search(pattern, last_text):
            return True

    return False


def inject_search_results(
    messages: list[dict[str, Any]],
    results: list[dict[str, str]],
    inject_as: str = "user_message",
) -> list[dict[str, Any]]:
    """Inject search results into the message list.

    Args:
        messages: Current message list
        results: Search results [{title, snippet, url}, ...]
        inject_as: How to inject — 'user_message' or 'system_message'

    Returns:
        Modified message list with search results injected
    """
    if not results:
        return messages

    # Format search results
    lines = ["[Kết quả tìm kiếm thực tế — hãy dùng thông tin này để trả lời chính xác]"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        url = r.get("url", "")
        lines.append(f"{i}. {title}")
        if snippet:
            lines.append(f"   {snippet}")
        if url:
            lines.append(f"   Nguồn: {url}")

    search_text = "\n".join(lines)

    result = list(messages)

    if inject_as == "system_message":
        # Add as system message (before the last user message)
        insert_pos = len(result)
        for i in range(len(result) - 1, -1, -1):
            if result[i].get("role") == "user":
                insert_pos = i
                break
        result.insert(insert_pos, {"role": "system", "content": search_text})
    else:
        # Add to last user message content
        for i in range(len(result) - 1, -1, -1):
            if result[i].get("role") == "user":
                content = result[i].get("content", "")
                if isinstance(content, str):
                    result[i] = dict(result[i])
                    result[i]["content"] = f"{search_text}\n\n---\nCâu hỏi của người dùng: {content}"
                break

    return result


class SearchService:
    """Orchestrates search across configured backend."""

    def __init__(self):
        self._config_cache: dict[str, Any] = {}

    def _get_config(self) -> dict[str, Any]:
        search_config = config.data.get("search")
        if isinstance(search_config, dict):
            return dict(search_config)
        return {}

    @property
    def backend_name(self) -> str:
        cfg = self._get_config()
        return str(cfg.get("backend") or "chatgpt").strip()

    @property
    def is_enabled(self) -> bool:
        cfg = self._get_config()
        if isinstance(cfg.get("enabled"), bool):
            return cfg["enabled"]
        return True  # Default enabled

    @property
    def auto_detect(self) -> bool:
        cfg = self._get_config()
        if isinstance(cfg.get("auto_detect"), bool):
            return cfg["auto_detect"]
        return True

    @property
    def max_results(self) -> int:
        cfg = self._get_config()
        try:
            return max(1, min(10, int(cfg.get("max_results") or 3)))
        except (TypeError, ValueError):
            return 3

    @property
    def inject_as(self) -> str:
        cfg = self._get_config()
        return str(cfg.get("inject_as") or "user_message").strip()

    def search(self, query: str) -> list[dict[str, str]]:
        """Execute search using configured backend."""
        backend = SEARCH_BACKENDS.get(self.backend_name, SEARCH_BACKENDS["chatgpt"])
        return backend.search(query, self.max_results)

    def process_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Process messages: detect if search needed, execute, inject results.

        If backend is 'chatgpt', this is a no-op — ChatGPT handles search internally.
        """
        if not self.is_enabled:
            return messages

        if self.backend_name == "chatgpt":
            # ChatGPT built-in search — no injection needed
            return messages

        if self.auto_detect and not needs_search(messages):
            return messages

        # Extract query from last user message
        query = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                query = str(msg.get("content") or "").strip()
                break

        if not query:
            return messages

        logger.info({
            "event": "search_executing",
            "backend": self.backend_name,
            "query": query[:200],
        })

        results = self.search(query)
        if results:
            logger.info({
                "event": "search_results",
                "backend": self.backend_name,
                "count": len(results),
            })
            return inject_search_results(messages, results, self.inject_as)

        return messages


# Singleton
search_service = SearchService()
