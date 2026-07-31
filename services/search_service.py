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


def _gemini_search_base() -> str:
    """Honor providers.gemini_free.base_url for VN-block proxy."""
    try:
        from services.config import config
        cfg = (config.data.get("providers") or {}).get("gemini_free") or {}
        override = str(cfg.get("base_url") or "").rstrip("/")
        if override:
            if not override.endswith("/v1beta"):
                override = override + "/v1beta"
            return override
    except Exception:
        pass
    return "https://generativelanguage.googleapis.com/v1beta"

import json
import os
import re
import time
import urllib.request
from typing import Any

from curl_cffi import requests

from services.config import config
from utils.log import logger

# Vietnamese word character class (includes diacritics)
_VI_WORD = r"[a-zA-ZàáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđĐ]+"

# Keywords that trigger search intent detection
SEARCH_INTENT_PATTERNS = [
    rf"(?:giá|bao nhiêu|mấy nghìn|mấy triệu)\s+{_VI_WORD}",
    rf"(?:hôm nay|hôm qua|tuần này|tháng này|năm nay)\s+{_VI_WORD}",
    r"\b(?:thời tiết|nhiệt độ|dự báo|nắng|mưa|bão|lũ)\b",
    rf"(?:tin tức|tin mới|báo chí)\s+{_VI_WORD}",
    rf"(?:kết quả|tỉ số|trận đấu)\s+{_VI_WORD}",
    r"\b(?:search|tìm kiếm|tìm hiểu|tra cứu)\b",
    r"\b(?:ai là|ở đâu|khi nào|thế nào|làm sao)\b",
    r"\b(?:giá|hỏi\s+giá)\b",
    r"\b(?:luật|nghị định|thông tư|pháp luật|quy định|hiệu lực)\b",
    r"\b(?:mới nhất|cập nhật|hiện nay|2024|2025|2026)\b",
]

# Dấu hiệu người dùng nói về KHO MEDIA CỦA CHÍNH HỆ THỐNG (ảnh/video/nhạc bot đã
# tạo, lưu ở config.images_dir), không phải nhờ tra Internet. Dùng ở needs_search.
_DAU_HIEU_KHO_NHA = (
    "thư viện", "trong kho", "trong máy", "vừa tạo", "đã tạo", "vừa vẽ",
    "đã vẽ", "vừa làm", "gửi lại", "xem lại", "lúc trước", "vừa rồi",
)
_TU_CHI_MEDIA = ("ảnh", "hình", "video", "clip", "nhạc", "bài hát")


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


# Engine mặc định cho tiếng Việt — chọn theo engine_traits.json của SearXNG:
# duckduckgo và startpage có đủ `vi` + `vi-VN`; bing chỉ có region `vi-VN` nhưng
# vẫn hơn hẳn brave/qwant/mojeek (KHÔNG có `vi` nào, sẽ trả kết quả tiếng Anh
# trộn vào). Google bị bản gốc đánh `inactive: true` — engine không được nạp, nên
# truyền `engines=google` là bị bỏ qua IM LẶNG, tưởng đang tra Google mà không.
#
# Truyền `engines=` tường minh còn để chặn độ trễ: nếu để SearXNG tự chọn cả
# nhóm general thì thời gian chờ bằng engine chậm nhất được chọn, mà settings gốc
# có engine tự khai timeout tới 20s.
#
# Đo thật 2026-07-30 trên chính container này, 5 truy vấn tiếng Việt: startpage
# ăn CAPTCHA NGAY từ lượt đầu, duckduckgo ăn CAPTCHA từ lượt thứ tư — chỉ bing
# gánh cả năm lượt. SearXNG treo engine ăn captcha 3600s (cf_ tới 15 ngày), nên
# nếu chỉ khai ba engine "đúng tiếng Việt" thì có ngày cả ba treo cùng lúc và
# kết quả rỗng sạch. Thêm mojeek + brave làm dự phòng: chúng KHÔNG có `vi` trong
# engine_traits nên trả kết quả trộn tiếng Anh — thà vậy còn hơn rỗng, và chúng
# chỉ có tiếng nói khi mấy engine trên chết.
_SEARXNG_ENGINES = "bing,duckduckgo,startpage,mojeek,brave"
_SEARXNG_LANG = "vi-VN"


def searxng_base_url() -> str:
    """URL SearXNG — tự tìm, KHÔNG bắt người dùng khai.

    Thứ tự: cấu hình tay → biến môi trường → tên service trong compose. Bản cũ
    mặc định `http://localhost:8080`, mà trong Docker thì localhost là chính
    container gateway: đường tìm kiếm này chưa bao giờ chạy được và cũng không
    ai biết vì sao.
    """
    cfg = (config.data.get("providers") or {}).get("searxng") or {}
    return str(
        cfg.get("base_url")
        or os.environ.get("SEARXNG_URL")
        or "http://searxng:8080"
    ).strip().rstrip("/")


# UA "giống trình duyệt" + Accept có text/html: chi phí bằng 0 mà tránh được cả
# họ lỗi khi instance có bật limiter — botdetection chặn thẳng UA chứa
# "python-requests" và chặn request không nhận text/html.
_SEARXNG_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate",
}


_searxng_health: tuple[float, bool] = (0.0, False)
_SEARXNG_HEALTH_TTL = 120.0


def searxng_ready() -> bool:
    """SearXNG có sống và có bật format=json không (cache 2 phút).

    Kiểm `/search?format=json` chứ không chỉ `/healthz`: mặc định của SearXNG là
    `formats: [html]` và webapp trả **403 không kèm body** cho json. Instance
    "khoẻ" mà chưa mở json thì với ta là vô dụng — phải phân biệt được hai ca đó
    để nói đúng nguyên nhân thay vì báo "không có kết quả".
    """
    global _searxng_health
    now = time.time()
    if now - _searxng_health[0] < _SEARXNG_HEALTH_TTL:
        return _searxng_health[1]
    ok = False
    base = searxng_base_url()
    try:
        r = requests.get(f"{base}/search",
                         params={"q": "ping", "format": "json",
                                 "engines": "duckduckgo", "timeout_limit": 3},
                         headers=_SEARXNG_HEADERS, timeout=8)
        if r.status_code == 403:
            logger.warning({"event": "searxng_json_bi_chan",
                            "hint": "settings.yml thiếu search.formats: [html, json]"})
        elif r.status_code == 429:
            logger.warning({"event": "searxng_bi_rate_limit",
                            "hint": "tắt server.limiter hoặc whitelist IP nội bộ "
                                    "trong limiter.toml (pass_ip)"})
        else:
            ok = r.status_code == 200 and isinstance(r.json(), dict)
    except Exception as exc:
        logger.info({"event": "searxng_chua_san_sang", "url": base,
                     "error": str(exc)[:100]})
    _searxng_health = (now, ok)
    return ok


class SearXNGSearcher(SearchBackend):
    """SearXNG tự host — không API key, không hạn mức."""

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        base_url = searxng_base_url()
        try:
            resp = requests.get(
                f"{base_url}/search",
                params={"q": query, "format": "json", "categories": "general",
                        # language BẮT BUỘC truyền tường minh: mặc định của
                        # SearXNG là "auto" — nó đoán theo header Accept-Language
                        # của phía gọi, tức phụ thuộc thứ ta tình cờ gửi.
                        "language": _SEARXNG_LANG,
                        "engines": _SEARXNG_ENGINES,
                        "safesearch": 0,
                        # Trần thời gian, tính cả engine chậm nhất.
                        "timeout_limit": 5},
                headers=_SEARXNG_HEADERS,
                timeout=12,
            )
            if resp.status_code != 200:
                # Nói ra nguyên nhân THẬT: 403 = chưa bật json, 429 = limiter.
                # Bản cũ log trơ status rồi trả rỗng, nhìn y như "không có kết
                # quả" nên không ai sửa được cấu hình.
                hint = ""
                if resp.status_code == 403:
                    hint = "settings.yml thiếu search.formats: [html, json]"
                elif resp.status_code == 429:
                    hint = "limiter đang chặn (API_MAX = 4 request/IP/giờ)"
                logger.warning({"event": "searxng_error", "status": resp.status_code,
                                "url": base_url, "hint": hint})
                return []

            data = resp.json()
            # unresponsive_engines là DẤU HIỆU DUY NHẤT trong JSON cho biết engine
            # nào vừa bị chặn/captcha. Không log thì kết quả rỗng trông giống
            # "không có gì trên Internet", trong khi thực ra engine đang bị treo
            # (SearXNG treo engine ăn captcha từ 3600s tới 15 ngày).
            chet = data.get("unresponsive_engines") or []
            if chet:
                logger.warning({"event": "searxng_engine_khong_tra_loi",
                                "engines": [list(x)[:2] for x in chet][:5]})

            results: list[dict[str, str]] = []
            for item in (data.get("results") or [])[:max_results]:
                results.append({
                    "title": str(item.get("title") or ""),
                    "snippet": str(item.get("content") or item.get("snippet") or ""),
                    "url": str(item.get("url") or ""),
                })
            if not results:
                logger.warning({"event": "searxng_rong", "query_len": len(query),
                                "engine_chet": len(chet)})
            return results

        except Exception as exc:
            logger.warning({"event": "searxng_exception", "error": str(exc)[:160]})
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
    """Google Search grounding via Gemini API. Uses model from providers.gemini_free.model."""

    def __init__(self):
        self._key_index = 0
        self._rate_limited: dict[str, float] = {}

    def _get_model(self) -> str:
        cfg = (config.data.get("providers") or {}).get("gemini_free") or {}
        # Use search-specific model if set, otherwise use chat model
        return str(cfg.get("search_model") or cfg.get("model") or "gemini-2.5-flash")

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
        # Log only once per key per minute
        last_log = getattr(self, '_last_log', {})
        now = time.time()
        if key not in last_log or now - last_log[key] > 60:
            last_log[key] = now
            self._last_log = last_log
            logger.warning({"event": "gemini_rate_limited", "key_prefix": key[:10]})

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        api_key = self._next_key()
        if not api_key:
            logger.warning({"event": "gemini_no_api_key"})
            return []

        try:
            kwargs = {"timeout": 30}
            proxy = str(config.data.get("proxy") or "").strip()
            if proxy:
                kwargs["proxies"] = {"http": proxy, "https": proxy}

            resp = requests.post(
                f"{_gemini_search_base()}/models/{self._get_model()}:generateContent?key={api_key}",
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                json={"contents": [{"parts": [{"text": query}]}], "tools": [{"google_search": {}}]},
                **kwargs
            )

            if resp.status_code in (429, 403):
                self._mark_limited(api_key)
                now = time.time()
                available = [k for k in self._get_keys() if self._rate_limited.get(k, 0) < now]
                if available:
                    return self.search(query, max_results)
                logger.warning({"event": "gemini_all_keys_blocked", "status": resp.status_code})
                return []

            if resp.status_code != 200:
                logger.warning({"event": "gemini_error", "status": resp.status_code, "body": resp.text[:200]})
                return []

            data = resp.json()
            results: list[dict[str, str]] = []
            candidates = data.get("candidates") or []

            # Get the model's search-grounded text for actual data
            model_text = ""
            for c in candidates:
                parts = (c.get("content") or {}).get("parts") or []
                model_text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))

            if model_text:
                results.append({
                    "title": "Tổng hợp Google Search (Gemini)",
                    "snippet": model_text[:2000],
                    "url": ""
                })

            for c in candidates:
                grounding = c.get("groundingMetadata") or {}
                chunks = grounding.get("groundingChunks") or []
                sources = grounding.get("webSearchQueries") or []
                for chunk in chunks[:max_results]:
                    web = chunk.get("web") or {}
                    snippet = str(web.get("snippet") or "")
                    if snippet:
                        results.append({
                            "title": str(web.get("title") or (sources[0] if sources else query)),
                            "snippet": snippet,
                            "url": str(web.get("uri") or ""),
                        })
            return results[:max_results + 1]

        except Exception as exc:
            logger.warning({"event": "gemini_exception", "error": str(exc)})
            return []


class CustomProviderSearch(SearchBackend):
    """Use a custom provider's chat model for search (e.g., Gemini API server).

    Sends the query as a chat message with search instruction. Useful for
    Gemini-compatible APIs that support Google grounding natively.
    """

    def __init__(self, provider_id: str = ""):
        self.provider_id = provider_id

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        if not self.provider_id:
            return []

        from services.providers.custom_openai import get_custom_providers, CustomOpenAIProvider
        providers = get_custom_providers()
        cfg = providers.get(self.provider_id)
        if not cfg:
            return []

        provider = CustomOpenAIProvider(cfg)
        prefix = str(cfg.get("prefix") or self.provider_id)

        # Get available models and prefer a fast variant. "First model" is
        # often the heaviest (gemini-3-pro) and burns 7-8s on a simple search
        # synthesis. Prefer flash/lite/mini if the provider exposes one —
        # they're 3-4× faster for grounding queries with no real quality loss.
        models = provider.list_models()
        if not models:
            return []

        # Prefer a fast variant. Substring matching ("mini" in name) is too
        # loose: "mini" appears inside both "geMINIapi2" prefix AND "geMINI-3"
        # model family, so every Gemini model would match and the loop would
        # silently pick the heaviest one. Tokenize on /, -, _ and require a
        # WHOLE token match against the hint set.
        _FAST_HINTS = {"flash", "lite", "mini", "small", "fast", "nano"}
        prefix_lower = f"{prefix}/".lower()
        import re as _re

        def _tokens(model: dict) -> set[str]:
            mid = str(model.get("id") or "").lower()
            if mid.startswith(prefix_lower):
                mid = mid[len(prefix_lower):]
            return set(_re.split(r"[/_\-.]", mid))

        chosen = None
        for m in models:
            if _tokens(m) & _FAST_HINTS:
                chosen = m
                break
        if chosen is None:
            chosen = models[0]
        model_id = str(chosen.get("id") or "").replace(f"{prefix}/", "")
        if not model_id:
            return []
        logger.info({
            "event": "custom_provider_search_model",
            "provider": prefix, "model": model_id,
        })

        try:
            result = provider.chat_completions(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Tìm kiếm trên Google: {query}\n\n"
                        f"Hãy trả lời với thông tin thực tế, cập nhật mới nhất. "
                        f"Trả về tối đa {max_results} kết quả với định dạng:\n"
                        f"1. [Tiêu đề](URL): mô tả ngắn\n"
                        f"2. [Tiêu đề](URL): mô tả ngắn"
                    ),
                }],
                model=model_id,
                stream=False,
                max_tokens=1000,
                temperature=0.3,
            )

            content = ""
            if isinstance(result, dict):
                choices = result.get("choices") or []
                if choices:
                    content = str(choices[0].get("message", {}).get("content") or "")

            if not content:
                return []

            # Parse the response into structured results
            results: list[dict[str, str]] = []
            import re
            lines = content.strip().split("\n")
            for line in lines[:max_results]:
                # Parse "1. [Title](URL): description" or "1. Title: description"
                match = re.match(r"\d+\.\s*\[?(.+?)\]?(?:\((.+?)\))?:\s*(.*)", line.strip())
                if match:
                    results.append({
                        "title": match.group(1).strip(),
                        "url": match.group(2) or "",
                        "snippet": match.group(3).strip(),
                    })
                elif line.strip() and len(results) < max_results:
                    # Fallback: use whole line as snippet
                    text = re.sub(r"^\d+\.\s*", "", line.strip())
                    if text and len(text) > 10:
                        results.append({
                            "title": text[:80],
                            "url": "",
                            "snippet": text,
                        })

            if results:
                logger.info({
                    "event": "custom_provider_search_ok",
                    "provider": self.provider_id,
                    "model": model_id,
                    "results": len(results),
                })
            return results

        except Exception as exc:
            logger.warning({
                "event": "custom_provider_search_error",
                "provider": self.provider_id,
                "error": str(exc),
            })
            return []


class GeminiWebApiSearch(SearchBackend):
    """gemini.google.com (bản WEB qua cookie 1PSID, nhiều account xoay) — Gemini web
    tự tra Google rồi trả lời. Bổ sung cho GeminiGrounding (API chính thức): nguồn
    khác, quota khác, nên khi 1 cái hết lượt vẫn còn cái kia."""

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        try:
            from api.gemini_web import handle_gemini_web_api_chat
            prompt = (f"Tìm trên web và trả lời NGẮN GỌN, chính xác, cập nhật mới nhất "
                      f"cho câu hỏi: {query}")
            res = handle_gemini_web_api_chat(
                "gma/auto", [{"role": "user", "content": prompt}], False, {})
            content = ""
            if isinstance(res, dict):
                ch = res.get("choices") or []
                if ch:
                    content = str((ch[0].get("message") or {}).get("content") or "")
            if not content.strip():
                return []
            return [{"title": "Tổng hợp Gemini Web", "snippet": content.strip()[:3000], "url": ""}]
        except Exception as exc:
            logger.warning({"event": "gemini_web_search_error", "error": str(exc)[:120]})
            return []


class MCPSearch(SearchBackend):
    """Search via enabled MCP search tools (vn_search, federated_search, etc.)."""

    @property
    def name(self) -> str:
        return "mcp"

    # Chỉ tool TÌM KIẾM. Bản cũ gọi cả `get_news` và `get_current_weather` cho
    # MỌI câu hỏi — hai tool đó không tìm được gì, nhưng mỗi lần gọi vẫn chờ hết
    # timeout. Đo thật 30/07: một lượt tìm mất 89 giây, có lượt 601 giây.
    # Tên tham số giới hạn số kết quả KHÁC NHAU theo từng tool — gửi sai tên thì
    # pydantic ném "Unexpected keyword argument" và cả lượt tìm kiếm chết.
    # Đo thật 31/07 trên log máy chủ: `search_all` nhận `limit_per_source`, code
    # gửi `limit` ⇒ mọi lượt gọi search_all đều lỗi, DDG cũng lỗi SSL cùng lúc
    # nên không còn nguồn nào ⇒ /v1/chat/completions trả 502 cho người dùng.
    _TOOLS = (
        ("search_web", "limit"),         # vn_search.search_web(query, limit)
        ("search_all", "limit_per_source"),  # federated_search.search_all(query, limit_per_source)
        ("search", "limit"),             # wikipedia.search(query, lang, limit)
    )

    # Câu "không có kết quả" của tool — phải coi là RỖNG.
    _RONG = ("không tìm thấy", "khong tim thay", "no result", "không có kết quả")

    # Dấu hiệu tool trả về LỖI, không phải kết quả. Đo thật 30/07: gọi
    # `call_mcp_tool("search_web", {...,"limit":...})` không chỉ server nên bị
    # định tuyến sang một server MCP khác có chữ ký khác, pydantic ném
    # "Unexpected keyword argument" — và text lỗi đó có kèm URL
    # errors.pydantic.dev, nên bộ tách coi LỖI là một kết quả tìm kiếm hợp lệ.
    _LOI = ("unexpected keyword", "validation error", "errors.pydantic.dev",
            "traceback", "internal server error", "-32600", "-32602")

    _URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        """Dùng MCP search tool làm backend dự phòng.

        Bản cũ trả về ``{"title": <TÊN TOOL>, "snippet": text, "url": ""}`` —
        ba chỗ sai cùng lúc, và cả ba đều im lặng:

        1. `title` là TÊN TOOL ("search_web"), không phải tiêu đề trang. Ai đọc
           `title` cũng nhận rác.
        2. `url` LUÔN rỗng. `sgk_fetch` lọc ứng viên bằng `_looks_like_pdf(url)`
           nên không bao giờ có ứng viên nào — cả đường tìm sách chết đứng mà
           log vẫn ghi "search_success results=5".
        3. `len(text) > 10` khiến chuỗi "Không tìm thấy kết quả." (23 ký tự)
           được tính là MỘT kết quả thành công.

        Nay tách text thành từng kết quả có URL thật, và dừng ở tool đầu tiên có
        kết quả dùng được thay vì gọi hết mọi tool.
        """
        try:
            from services.mcp_client import call_mcp_tool
        except ImportError:
            return []

        for tool, ten_gioi_han in self._TOOLS:
            try:
                text = str(call_mcp_tool(tool, {"query": query, ten_gioi_han: max_results}) or "")
            except Exception:
                continue
            if not text.strip():
                continue
            low = text.lower()
            if any(m in low for m in self._LOI):
                # Text LỖI có thể kèm URL (errors.pydantic.dev) nên bộ tách sẽ
                # coi là kết quả nếu không chặn ở đây. Chặn TRƯỚC khi tách.
                # logger của module này chỉ nhận MỘT tham số — không dùng %-format.
                logger.warning(f"MCPSearch: tool {tool} trả về lỗi: {text[:160]}")
                continue
            if any(m in low for m in self._RONG) and not self._URL_RE.search(text):
                continue        # tool trả lời "không có gì" → đi tool tiếp
            ket = self._tach(text, max_results)
            if ket:
                return ket
        return []

    def _tach(self, text: str, max_results: int) -> list[dict[str, str]]:
        """Tách text của MCP thành [{title, url, snippet}].

        Khuôn text của các tool này là: dòng tiêu đề, dòng URL, rồi mô tả. Lấy
        MỐC là dòng chứa URL — dòng ngay TRƯỚC nó là tiêu đề. Không có URL thì
        bỏ hẳn: một kết quả tìm kiếm không có link thì không dùng được vào việc
        gì, giữ lại chỉ để đếm cho đẹp.
        """
        lines = [l.strip() for l in text.splitlines()]
        out: list[dict[str, str]] = []
        for i, line in enumerate(lines):
            m = self._URL_RE.search(line)
            if not m:
                continue
            url = m.group(0).rstrip(").,;]>\"'")
            title = ""
            for j in range(i - 1, max(-1, i - 4), -1):
                cand = lines[j].lstrip("-*0123456789. )")
                if cand and not self._URL_RE.search(cand):
                    title = cand[:200]
                    break
            snippet = " ".join(x for x in lines[i + 1:i + 3] if x and not self._URL_RE.search(x))
            out.append({"title": title or url, "url": url, "snippet": snippet[:500]})
            if len(out) >= max(1, max_results):
                break
        return out


# Backend registry
SEARCH_BACKENDS: dict[str, SearchBackend] = {
    "chatgpt": ChatGPTSearch(),
    "gemini": GeminiGrounding(),
    "gemini_web": GeminiWebApiSearch(),
    "serper": SerperSearch(),
    "searxng": SearXNGSearcher(),
    "brave": BraveSearch(),
    "mcp": MCPSearch(),
}


class IntentRouter:
    """Phan tich y dinh cau hoi, tra ve danh sach MCP tool ID can goi."""

    # MCP server IDs (phai khop voi ID trong config mcp_servers)
    _WEATHER_TOOLS = ["vn_weather"]
    _NEWS_TOOLS    = ["vn_news"]
    _FINANCE_TOOLS = ["vn_currency"]
    _PETROL_TOOLS  = ["vn_petrol"]
    _STOCK_TOOLS   = ["vn_stock"]
    _LAW_TOOLS     = ["vn_law"]
    _SEARCH_TOOLS  = ["federated_search", "vn_search"]

    # KB mapping: tu khoa -> collection ID
    _KB_MAP = {
        "dien": "kb_dien_nuoc", "nuoc": "kb_dien_nuoc", "mcb": "kb_dien_nuoc",
        "mccb": "kb_dien_nuoc", "dieu hoa": "kb_dien_nuoc", "chiller": "kb_dien_nuoc",
        "y te": "kb_y_te", "bong": "kb_y_te", "so cuu": "kb_y_te",
        "benh": "kb_y_te", "thuoc": "kb_y_te",
        "giao duc": "kb_giao_duc", "hoc": "kb_giao_duc", "truong": "kb_giao_duc",
        "ngoai ngu": "kb_ngoai_ngu", "tieng anh": "kb_ngoai_ngu", "ngu phap": "kb_ngoai_ngu",
        "khoa hoc": "kb_khoa_hoc", "vat ly": "kb_khoa_hoc", "hoa hoc": "kb_khoa_hoc",
        "tu nhien": "kb_tu_nhien", "dong vat": "kb_tu_nhien", "thuc vat": "kb_tu_nhien",
        "xa hoi": "kb_xa_hoi", "lich su": "kb_xa_hoi", "van hoa": "kb_xa_hoi",
        "pccc": "kb_xa_hoi", "phap luat": "kb_xa_hoi",
        # Natural phenomena / general science — multi-char keys to avoid
        # collisions; routes these into the science KBs so the self-enriching
        # loop can serve them once populated (e.g. "nguồn gốc sấm sét").
        "sam set": "kb_tu_nhien", "khi tuong": "kb_tu_nhien", "khi hau": "kb_tu_nhien",
        "nui lua": "kb_tu_nhien", "dong dat": "kb_tu_nhien", "thuy trieu": "kb_tu_nhien",
        "cau vong": "kb_tu_nhien", "thien tai": "kb_tu_nhien",
        "thien van": "kb_khoa_hoc", "vu tru": "kb_khoa_hoc", "hanh tinh": "kb_khoa_hoc",
        "nguyen tu": "kb_khoa_hoc", "trong luc": "kb_khoa_hoc", "nang luong": "kb_khoa_hoc",
    }

    _WEATHER_KW = ["thoi tiet", "thời tiết", "nhiet do", "nhiệt độ", "du bao",
                   "dự báo", "mua", "mưa", "nang", "nắng", "bao", "bão", "lu", "lũ"]
    _NEWS_KW    = ["tin tuc", "tin tức", "tin moi", "tin mới", "bao chi", "báo chí",
                   "thoi su", "thời sự"]
    _FINANCE_KW = ["gia vang", "giá vàng", "ty gia", "tỷ giá", "ngoai te", "ngoại tệ",
                   "do la", "đô la", "usd", "euro"]
    _PETROL_KW  = ["gia xang", "giá xăng", "gia dau", "giá dầu", "ron 95", "ron95",
                   "e5 ron", "xang dau", "xăng dầu", "dau do", "dầu do", "dau hoa",
                   "dầu hỏa", "petrolimex", "mazut", "mazút"]
    _STOCK_KW   = ["co phieu", "cổ phiếu", "vn-index", "vnindex", "chung khoan",
                   "chứng khoán", "hnx", "hose"]
    _LAW_KW     = ["luat", "luật", "nghi dinh", "nghị định", "thong tu", "thông tư",
                   "phap luat", "pháp luật", "quy dinh", "quy định", "hieu luc",
                   "hiệu lực", "pccc"]
    _LIVE_KW    = ["moi nhat", "mới nhất", "cap nhat", "cập nhật", "hien nay",
                   "hiện nay", "2024", "2025", "2026", "gan day", "gần đây"]

    def _normalize(self, text: str) -> str:
        """Lowercase + strip Vietnamese diacritics including đ → d."""
        import unicodedata
        # NFKD strips most diacritic combining marks but Unicode does NOT
        # decompose "đ" (LATIN SMALL LETTER D WITH STROKE) — it's a single
        # codepoint without decomposition. Replace it manually so keyword
        # checks like "dien" match the folded form of "điện".
        s = text.lower().replace("đ", "d").replace("Đ", "d")
        nfkd = unicodedata.normalize('NFKD', s)
        return ''.join(c for c in nfkd if not unicodedata.combining(c))

    def detect(self, query: str) -> dict:
        """Phan tich query, tra ve:
        {
          'mcp_tools': [list MCP server IDs can goi],
          'kb_collections': [list KB collections lien quan],
          'needs_live': bool,  # can search them ngoai KB
        }"""
        q = self._normalize(query)
        tools = list(self._SEARCH_TOOLS)  # mac dinh luon co
        kb_hits = []
        needs_live = any(k in q for k in self._LIVE_KW)

        if any(k in q for k in self._WEATHER_KW):
            tools.extend(self._WEATHER_TOOLS)
        if any(k in q for k in self._NEWS_KW):
            tools.extend(self._NEWS_TOOLS)
        if any(k in q for k in self._FINANCE_KW):
            tools.extend(self._FINANCE_TOOLS)
        if any(k in q for k in self._PETROL_KW):
            tools.extend(self._PETROL_TOOLS)
        if any(k in q for k in self._STOCK_KW):
            tools.extend(self._STOCK_TOOLS)
        if any(k in q for k in self._LAW_KW):
            tools.extend(self._LAW_TOOLS)
            needs_live = True  # Phap luat luon can kiem tra phien ban moi

        # Phat hien KB lien quan
        for kw, col in self._KB_MAP.items():
            if kw in q and col not in kb_hits:
                kb_hits.append(col)

        # Neu co KB hits -> bo search general, KB se tu query
        # Nhung neu co needs_live -> van giu search de bo sung
        if kb_hits and not needs_live:
            tools = [t for t in tools if t not in ["federated_search", "vn_search"]]

        # Loai tru trung lap
        tools = list(dict.fromkeys(tools))
        return {"mcp_tools": tools, "kb_collections": kb_hits, "needs_live": needs_live}


_intent_router = IntentRouter()


# Common Vietnamese cities (folded) so we can extract them from queries like
# "thời tiết Hà Nội" → "Hà Nội". Order matters — longer phrases first so
# "Hồ Chí Minh" matches before "Chí".
_KNOWN_CITIES = [
    ("ho chi minh", "Hồ Chí Minh"),
    ("tp hcm", "Hồ Chí Minh"),
    ("sai gon", "Hồ Chí Minh"),
    ("ha noi", "Hà Nội"),
    ("da nang", "Đà Nẵng"),
    ("can tho", "Cần Thơ"),
    ("hai phong", "Hải Phòng"),
    ("nha trang", "Nha Trang"),
    ("vung tau", "Vũng Tàu"),
    ("hue", "Huế"),
    ("da lat", "Đà Lạt"),
    ("quy nhon", "Quy Nhơn"),
    ("vinh", "Vinh"),
    ("nam dinh", "Nam Định"),
    ("ha long", "Hạ Long"),
    ("london", "London"),
    ("new york", "New York"),
    ("tokyo", "Tokyo"),
    ("bangkok", "Bangkok"),
    ("singapore", "Singapore"),
]


def _extract_city(query: str) -> str | None:
    """Strip "thời tiết / dự báo / weather" prefix + return the city name.
    Falls back to known-city scan if no prefix is found."""
    if not query:
        return None
    q = query.strip()
    qlow = q.lower()
    # Strip common Vietnamese weather prefixes
    for prefix in (
        "thời tiết tại ", "thời tiết ở ", "thời tiết ",
        "dự báo thời tiết ", "dự báo ",
        "weather in ", "weather at ", "weather ",
    ):
        if qlow.startswith(prefix):
            return q[len(prefix):].strip().rstrip("?.,!")
    # Otherwise try matching a known city anywhere in the (folded) query
    import unicodedata
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", qlow)
        if not unicodedata.combining(c)
    )
    for kw, city in _KNOWN_CITIES:
        if kw in folded:
            return city
    return None


def get_all_search_backends() -> dict[str, dict[str, str]]:
    """Get all available search backends including custom providers."""
    backends = dict(SEARCH_BACKENDS)
    # Add custom providers as potential search backends
    from services.providers.custom_openai import get_custom_providers
    for cp_id, cp_cfg in get_custom_providers().items():
        key = f"custom:{cp_id}"
        if key not in backends:
            backends[key] = CustomProviderSearch(cp_id)
    return {k: {"name": getattr(v, "provider_id", k) if hasattr(v, "provider_id") else k,
                "label": _get_backend_label(k)} for k, v in backends.items()}


def _get_backend_label(key: str) -> str:
    labels = {
        "chatgpt": "ChatGPT (có sẵn)",
        "gemini": "Gemini Google Search",
        "serper": "Serper.dev",
        "searxng": "SearXNG (tự cài)",
        "brave": "Brave Search",
    }
    if key.startswith("custom:"):
        cp_id = key[len("custom:"):]
        from services.providers.custom_openai import get_custom_providers
        providers = get_custom_providers()
        cfg = providers.get(cp_id) or {}
        return f"{cfg.get('name', cp_id)} (Custom API)"
    return labels.get(key, key)

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
            # Chỉ lấy PHẦN CHỮ: tin nhắn kèm ảnh có content dạng danh sách, làm
            # str() lên nó là kéo cả chuỗi base64 (ảnh camera HA ~1MB) vào rồi
            # strip/lower/so khớp — đốt hàng giây CPU cho thứ không phải ý định.
            _c = msg.get("content")
            if isinstance(_c, list):
                last_text = " ".join(
                    str(p.get("text") or "") for p in _c
                    if isinstance(p, dict) and p.get("type") == "text"
                ).strip().lower()
            else:
                last_text = str(_c or "").strip().lower()
            break

    if not last_text:
        return False

    # Skip AI task / image analysis prompts (long prompts with JSON templates)
    if len(last_text) > 500 and ("{" in last_text and "}" in last_text and "json" in last_text.lower()):
        return False

    # Skip RAG / knowledge-synthesis / HA-vision prompts — the caller
    # already has all the raw context inline, running our own search
    # would just cost the 8 s OVERALL_TIMEOUT (gemini-block + fan-out
    # to MCP tools) for nothing useful. Matches vn-mcp-hub's scheduler
    # synthesis prompt and HA's camera-snapshot assistant prompt.
    _SKIP_MARKERS = (
        "chuyên gia tổng hợp",
        "tổng hợp tri thức",
        "knowledge base",
        "knowledge-base",
        "synthesize the following",
        "summarize the search results",
        "dựa vào các kết quả tìm kiếm",
        "raw search results",
        "đây là chuỗi hình ảnh",
        "you are a home assistant expert",
    )
    if len(last_text) > 300 and any(m in last_text for m in _SKIP_MARKERS):
        return False

    # LỆNH lấy media trong THƯ VIỆN của chính hệ thống — KHÔNG phải câu hỏi cần
    # tra web. Đo thật 31/07 trên log máy chủ: "Gửi 3 ảnh mới nhất trong thư
    # viện ảnh" khớp mẫu `mới nhất` ⇒ đem cả câu lệnh đi tìm trên Internet (12
    # kết quả, có cả CrossRef báo khoa học), rồi bot trả lời "em không truy cập
    # được thư viện ảnh cá nhân của anh" thay vì gọi tool `library_media`.
    # "mới nhất" ở đây là ảnh mới nhất TRONG MÁY, không phải tin tức mới nhất.
    # Chỉ chặn khi có ĐỒNG THỜI dấu hiệu "kho của mình" và một từ chỉ media —
    # để "tìm ảnh Hà Nội mới nhất" vẫn được tra web như cũ.
    if (any(k in last_text for k in _DAU_HIEU_KHO_NHA)
            and any(k in last_text for k in _TU_CHI_MEDIA)):
        return False

    # Check against search intent patterns
    for pattern in SEARCH_INTENT_PATTERNS:
        if re.search(pattern, last_text):
            return True

    # KB hit check — knowledge questions like "điện ba pha là gì" don't trip
    # the live-search patterns but a local KB collection may have the answer.
    # Detect via the intent router's KB keyword map (diacritic-folded match).
    try:
        folded = _intent_router._normalize(last_text)
        for kw in _intent_router._KB_MAP:
            if kw in folded:
                return True
    except Exception:
        pass

    return False


def inject_search_results(
    messages: list[dict[str, Any]],
    results: list[dict[str, str]],
    inject_as: str = "user_message",
    max_inject_chars: int = 12000,  # Hard cap for ChatGPT free (413 guard)
) -> list[dict[str, Any]]:
    """Inject search results into the message list."""
    if not results:
        return messages

    import re as _re

    # Phrases that indicate KB meta-content / ingestion garbage rather than real knowledge
    _GARBAGE_PATTERNS = [
        "khung nội dung phù hợp",
        "kb_tu_nhien cập nhật mới nhất",
        "dữ liệu tìm kiếm được cung cấp",
        "kết quả không liên quan",
        "loại bỏ các dữ liệu không liên quan",
        "bài viết này tập trung vào việc tổng hợp",
        "Đánh giá dữ liệu tìm kiếm",
        "auto_ai/20",  # Auto-generated AI noise entries
    ]

    def _is_garbage_snippet(snippet: str) -> bool:
        """Return True if snippet is KB meta-content / ingestion garbage."""
        s = snippet.lower()
        for pat in _GARBAGE_PATTERNS:
            if pat.lower() in s:
                return True
        return False

    def _clean_snippet(snippet: str) -> str:
        """Remove raw MCP artifacts like entity[\"city\",\"...\"] from snippets."""
        # Remove entity[...] prefix patterns from MCP weather/other tools
        snippet = _re.sub(r'entity\[.*?\]', '', snippet)
        # Remove leftover \"  from JSON-escaped strings
        snippet = snippet.replace('\\"', '')
        return snippet.strip()

    # Format search results with strong instruction so HA's smart-home-focused
    # system prompt doesn't cause the AI to ignore search data and greet instead.
    lines = [
        "[SEARCH_RESULTS - BẮT BUỘC ĐỌC VÀ TRẢ LỜI DỰA TRÊN ĐÂY]",
        "Dưới đây là dữ liệu tìm kiếm/kiến thức cho câu hỏi này.",
        "KHÔNG chào hỏi, KHÔNG nói 'Xin chào'. Trả lời TRỰC TIẾP bằng các thông tin sau:",
    ]
    total_chars = sum(len(l) for l in lines)
    valid_count = 0
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        snippet = _clean_snippet(r.get("snippet", ""))
        if _is_garbage_snippet(snippet):
            continue  # Skip KB garbage entries
        line = f"{valid_count + 1}. {title}: {snippet}"
        if total_chars + len(line) > max_inject_chars:
            break
        lines.append(line)
        total_chars += len(line)
        valid_count += 1

    # If all results were garbage, skip injection (better no context than wrong context)
    if valid_count == 0:
        return messages

    search_text = "\n".join(lines)

    result = list(messages)

    if inject_as == "system_message":
        # Add as system message before the last user message
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
                elif isinstance(content, list):
                    # HA format: [{"type":"text","text":"..."}]
                    result[i] = dict(result[i])
                    search_part = {"type": "text", "text": search_text}
                    result[i]["content"] = [search_part] + [dict(c) for c in content]
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

    @property
    def search_combo(self) -> list[str]:
        """Thứ tự backend sẽ thử (combo/fallback).

        SearXNG được TỰ THÊM vào cuối chuỗi khi nó đang chạy — không cần ai bấm
        bật. Nó là đường duy nhất không cần API key và không hạn mức, nên để làm
        lưới đỡ cuối là đúng vai: các đường có khoá đi trước, hết mới tới nó.
        Thêm ở CUỐI, không chen lên trước, để không đổi thứ tự người dùng đã
        chọn; và chỉ thêm khi `searxng_ready()` báo sống + đã mở format=json,
        nếu không thì mỗi lượt tìm lại tốn một request chết.
        """
        cfg = self._get_config()
        combo = cfg.get("search_combo")
        if isinstance(combo, list) and combo:
            valid = set(SEARCH_BACKENDS.keys())
            # Also allow custom provider backends
            from services.providers.custom_openai import get_custom_providers
            for cp_id in get_custom_providers():
                valid.add(f"custom:{cp_id}")
            ds = [str(b).strip() for b in combo if str(b).strip() in valid]
        else:
            # Default: single backend from config
            backend = self._get_active_backend()
            ds = [backend] if backend in SEARCH_BACKENDS else ["chatgpt"]
        return self._them_searxng(ds)

    @staticmethod
    def _them_searxng(ds: list[str]) -> list[str]:
        """Nối searxng vào cuối chuỗi nếu chưa có và instance đang sống."""
        if "searxng" in ds:
            return ds
        # Cho phép tắt hẳn bằng cấu hình — người vận hành phải có đường nói
        # "đừng dùng", nhưng mặc định là DÙNG.
        if (config.data.get("providers") or {}).get("searxng", {}).get("enabled") is False:
            return ds
        if not searxng_ready():
            return ds
        return ds + ["searxng"]

    def _get_backend(self, name: str):
        """Get a search backend by name, including custom providers."""
        if name in SEARCH_BACKENDS:
            return SEARCH_BACKENDS[name]
        if name.startswith("custom:"):
            cp_id = name[len("custom:"):]
            return CustomProviderSearch(cp_id)
        return None

    def _get_active_backend(self) -> str:
        """Get actual search backend to use."""
        return self.backend_name

    def search(self, query: str) -> list[dict[str, str]]:
        """Execute search using configured backends in combo order. Falls back on failure."""
        combo = self.search_combo

        for backend_name in combo:
            backend = self._get_backend(backend_name)
            if not backend:
                continue

            # Skip chatgpt backend — it's passthrough (no injection)
            if backend_name == "chatgpt" or backend_name.startswith("custom:"):
                # ChatGPT handles search internally via chat model — skip injection
                # Custom providers: let's inject their search results
                if backend_name == "chatgpt":
                    logger.info({"event": "search_combo_chatgpt_skip", "reason": "passthrough"})
                    return []
                # custom provider — search and inject results
                pass

            logger.info({"event": "search_try_backend", "backend": backend_name, "query_len": len(query)})
            try:
                results = backend.search(query, self.max_results)
                if results:
                    logger.info({"event": "search_success", "backend": backend_name, "results": len(results)})
                    return results
                logger.warning({"event": "search_empty", "backend": backend_name})
            except Exception as exc:
                logger.warning({"event": "search_backend_error", "backend": backend_name, "error": str(exc)})

        logger.warning({"event": "search_all_backends_failed", "tried": combo})
        return []

    def search_all(self, query: str) -> list[dict[str, str]]:
        """Smart search: phan tich intent, goi song song dung MCP tools + combo backends.

        Flow:
        1. IntentRouter phan tich query -> chon dung MCP tools
        2. Combo backends (Gemini Grounding, custom provider...)
        3. Goi song song tat ca bang ThreadPoolExecutor
        4. Merge ket qua, loai trung lap
        """
        import concurrent.futures
        all_results: list[dict[str, str]] = []
        seen: set[str] = set()

        def _add(results: list[dict], source: str) -> None:
            for r in results:
                key = r.get("url") or r.get("title", "") or r.get("snippet", "")[:50]
                if key and key not in seen:
                    seen.add(key)
                    all_results.append(r)

        def _trim_mcp_result(server_id: str, text: str, limit: int = 4000) -> str:
            """Head-truncating a huge MCP table can drop the rows the user asked
            for. vn_currency.get_gold_prices returns ~100KB with SILVER rows
            listed BEFORE gold, so a blind text[:limit] head-cut fed the LLM only
            silver on "giá vàng". When the query targets gold, surface gold rows
            first so they survive the cut."""
            if len(text) <= limit:
                return text
            ql = query.lower()
            wants_gold = any(k in ql for k in ("vàng", "vang", "gold", "sjc", "doji", "pnj", "9999", "nhẫn", "24k", "18k"))
            if server_id == "vn_currency" and wants_gold:
                gold, silver = [], []
                for ln in text.splitlines():
                    low = ln.lower()
                    (silver if ("bạc" in low or "ag 999" in low or "ancarat" in low) else gold).append(ln)
                text = "\n".join(gold + silver)
            return text[:limit]

        # --- Luong 1: Smart MCP tool call dua theo intent ---
        intent = _intent_router.detect(query)
        mcp_server_ids = list(intent["mcp_tools"])
        kb_collections = intent["kb_collections"]

        # Đảm bảo có WEB SEARCH (federated) cho câu KIẾN THỨC: kho có thể rỗng/thiếu
        # nên cần web bổ sung; câu chung (mcp_tools rỗng) cũng cần web. Trước đây
        # câu khớp kho → mcp_tools=[] → chỉ hỏi kho (rỗng) → KHÔNG có web. Bỏ qua
        # khi là intent realtime chuyên dụng (giá vàng/thời tiết/cổ phiếu/xăng) đã
        # có tool số liệu riêng.
        _REALTIME_SERVERS = {"vn_currency", "vn_weather", "vn_petrol", "vn_stock", "vn_lunar"}
        if not any(s in _REALTIME_SERVERS for s in mcp_server_ids):
            if (kb_collections or not mcp_server_ids) and "federated_search" not in mcp_server_ids:
                mcp_server_ids.append("federated_search")

        logger.info({
            "event": "search_intent",
            "mcp_tools": mcp_server_ids,
            "kb_hits": kb_collections,
            "needs_live": intent["needs_live"],
        })

        def _call_mcp_server(server_id: str) -> tuple[str, str | None]:
            """Goi mot MCP server, tra ve (server_id, ket_qua_text).

            vn_currency exposes 3 tools (get_gold_prices / get_exchange_rate /
            get_vcb_rates). Pick by query so "giá vàng" gets the gold tool and
            "tỷ giá USD" gets the exchange-rate tool — previously we always
            called the non-existent "get_exchange_rates" and got
            `Unknown tool` back, leaving the LLM with no real numbers.
            """
            try:
                from services.mcp_client import call_mcp_tool
                _TOOL_MAP = {
                    "vn_search":       "search_web",
                    "federated_search": "search_all",
                    "vn_weather":      "get_current_weather",
                    "vn_news":         "get_news",
                    "vn_petrol":       "get_petrol_prices",
                    "vn_stock":        "get_stock_price",
                    "vn_law":          "search_law",
                }

                args: dict = {}
                if server_id == "vn_currency":
                    ql = query.lower()
                    if any(k in ql for k in ("vàng", "vang", "gold", "sjc", "doji", "pnj", "9999", "24k", "18k")):
                        tool_name = "get_gold_prices"
                    elif "vcb" in ql or "vietcombank" in ql:
                        tool_name = "get_vcb_rates"
                    else:
                        tool_name = "get_exchange_rate"
                elif server_id == "vn_weather":
                    # vn_weather.get_current_weather takes `city`, not `location`,
                    # and expects just the city name — passing the full query
                    # ("thời tiết Hà Nội") makes wttr.in 404 and falls back to URL-only
                    # results in our search synthesis.
                    tool_name = _TOOL_MAP[server_id]
                    city = _extract_city(query) or "Hà Nội"
                    args = {"city": city}
                elif server_id == "vn_petrol":
                    # get_petrol_prices(region) — extract Vùng 1/2 hint from
                    # the query, default "all" so the LLM sees both zones.
                    tool_name = _TOOL_MAP[server_id]
                    ql = query.lower()
                    if "vùng 1" in ql or "vung 1" in ql or "đô thị" in ql:
                        region = "vung1"
                    elif "vùng 2" in ql or "vung 2" in ql or "vùng sâu" in ql:
                        region = "vung2"
                    else:
                        region = "all"
                    args = {"region": region}
                else:
                    tool_name = _TOOL_MAP.get(server_id, "search_web")
                    args = {"query": query}
                    if server_id in ("vn_search", "vn_news", "vn_law", "vn_stock"):
                        args["limit"] = max(2, self.max_results)

                text = call_mcp_tool(
                    tool_name,
                    args,
                    server_id=server_id,
                )
                return server_id, text
            except Exception as exc:
                logger.debug("search_all: mcp %s skipped: %s", server_id, exc)
                return server_id, None

        # --- Luong 2: Combo backends (Gemini Grounding, custom provider...) ---
        combo = self.search_combo
        # Chỉ rơi về backend đơn khi combo THẬT SỰ trống hoặc đúng bằng
        # ["chatgpt"]. Trước đây so `combo == ["chatgpt"]` là đủ, nhưng giờ
        # `search_combo` tự nối "searxng" vào cuối nên chuỗi mặc định thành
        # ["chatgpt", "searxng"] — so bằng sẽ không khớp và ta mất luôn nhánh
        # này; còn nếu so lỏng thì lại bỏ mất searxng vừa thêm. Giữ cả hai: lấy
        # backend đang cấu hình, rồi nối lại searxng.
        if not combo or [c for c in combo if c != "searxng"] == ["chatgpt"]:
            combo = self._them_searxng([self._get_active_backend()])

        def _call_backend(name: str) -> tuple[str, list]:
            try:
                backend = self._get_backend(name)
                if not backend:
                    return name, []
                results = backend.search(query, max(2, self.max_results))
                return name, results
            except Exception as exc:
                logger.debug("search_all: backend %s skipped: %s", name, exc)
                return name, []

        # ChatGPT backend returns [] so it won't add duplicates, but we keep it in the list
        # so that native search tool injection still works alongside MCP injection.
        backend_names = [n for n in combo]

        # --- Luong 3: Tim kiem trong Vector DB (Neu co collection hop le) ---
        def _call_rag(collection: str) -> tuple[str, list]:
            # KB is queried through the per-collection MCP tool `ask_<suffix>`
            # (kb_tu_nhien -> ask_tu_nhien). The old POST /api/rag/query endpoint
            # never existed on vn-mcp-hub (404) and used the unresolvable
            # `mcp_hub_url` default — so KB grounding silently returned nothing.
            # ask_<> reaches the hub via the working mcp_servers URL and does the
            # KB-first hybrid lookup (with its own live fallback when needed).
            try:
                from services.mcp_client import call_mcp_tool
                suffix = collection[3:] if collection.startswith("kb_") else collection
                text = str(call_mcp_tool(f"ask_{suffix}", {"question": query}, server_id=collection) or "")
                low = text.lower()
                if not text or "chưa có dữ liệu" in low or "chưa sẵn sàng" in low:
                    return "rag", []
                return "rag", [{"title": f"[KB {suffix}]", "snippet": text[:3000], "url": ""}]
            except Exception as exc:
                logger.debug("search_all: KB %s skipped: %s", collection, exc)
                return "rag", []

        # --- Thuc thi song song ca MCP, Backend va RAG cung luc ---
        import concurrent.futures
        import time
        start_t = time.time()
        
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=12)
        futures = {}
        if mcp_server_ids:
            for sid in mcp_server_ids:
                futures[ex.submit(_call_mcp_server, sid)] = ("mcp", sid)
        
        if backend_names:
            for n in backend_names:
                futures[ex.submit(_call_backend, n)] = ("backend", n)
                
        if kb_collections:
            for c in kb_collections:
                futures[ex.submit(_call_rag, c)] = ("rag", c)
                
        # Domain MCP tools (vn_currency ~0.3s, vn_petrol, vn_weather...) are fast
        # and authoritative. federated_search.search_all can take 25s+ and returns
        # academic noise for VN queries, so it always hit the 8s wall and forced
        # EVERY search to cost the full 8s. Track the authoritative futures and
        # stop as soon as they finish instead of blocking on the slow crawler.
        priority = {f for f, (jt, nm) in futures.items()
                    if jt == "mcp" and nm != "federated_search"}
        done_priority: set = set()
        try:
            # Giam timeout xuong 8 giay de can bang giua toc do va do chinh xac
            for future in concurrent.futures.as_completed(futures, timeout=8):
                try:
                    job_type, name = futures[future]
                    if job_type == "mcp":
                        sid, text = future.result()
                        if text and len(text) > 20:
                            # _trim_mcp_result keeps the commodity the user asked
                            # about (gold-first reorder before the 4000-char cut)
                            # so "giá vàng" no longer gets only the silver rows
                            # that get_gold_prices happens to list first.
                            _add([{"title": f"[{sid}]", "snippet": _trim_mcp_result(sid, text), "url": ""}], sid)
                    else:
                        _, results = future.result()
                        _add(results, name)
                except Exception:
                    pass
                if future in priority:
                    done_priority.add(future)
                # Authoritative tools done + we already have data → don't wait out
                # the slow federated crawler (8s → sub-second for VN price queries).
                if priority and len(done_priority) == len(priority) and all_results:
                    break
        except concurrent.futures.TimeoutError:
            logger.warning({"event": "search_all_timeout", "took": time.time() - start_t})
        finally:
            ex.shutdown(wait=False)

        logger.info({"event": "search_all_done", "total": len(all_results), "took": time.time() - start_t})

        # Fallback: nếu KB được query nhưng trả về rỗng → search live để bù vào
        if kb_collections and not all_results:
            logger.info({"event": "search_kb_empty_fallback_live", "collections": kb_collections})
            for n in backend_names:
                try:
                    backend = self._get_backend(n)
                    if not backend:
                        continue
                    results = backend.search(query, max(2, self.max_results))
                    if results:
                        all_results.extend(results)
                        logger.info({"event": "search_kb_fallback_ok", "backend": n, "count": len(results)})
                        break
                except Exception:
                    continue

        return all_results[:self.max_results * 4]

    def curate_response(self, query: str, response: str, collection: str = "") -> bool:
        """Store a Q&A pair to vn-mcp-hub RAG. Best-effort, non-blocking."""
        if not response or len(response) < 50:
            return False
        # Hub là dịch vụ NỘI BỘ. Xem services.config.hub_base_url — chốt chỉ
        # nhận host nội bộ, vì bản cũ suy ra từ MCP server đầu tiên và bắn
        # curate sang MCP công khai (Exa) rồi ăn 404 im lặng.
        from services.config import hub_base_url
        hub_url = hub_base_url()
        if not collection:
            collection = "kb_general"
        try:
            import threading
            def _post():
                try:
                    req = urllib.request.Request(
                        f"{hub_url}/api/rag/curate/{collection}",
                        data=json.dumps({"title": query[:200], "text": response[:3000],
                                        "source": "chatgpt2api_curate"}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    urllib.request.urlopen(req, timeout=10)
                except Exception:
                    pass
            threading.Thread(target=_post, daemon=True).start()
            return True
        except Exception:
            return False

    def process_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Process messages: detect if search needed, execute, inject results.

        Injects MCP/Gemini context for ALL models including chatgpt/cx/auto.
        ChatGPT/CX models also run their own native web search tool in parallel,
        so they get BOTH injected context AND live search — best of both worlds.
        """
        if not self.is_enabled:
            return messages

        if self.auto_detect and not needs_search(messages):
            return messages

        # Extract query from last user message
        query = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                # Handle list content format [{"type":"text","text":"..."}]
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            query = str(part.get("text") or "").strip()
                            break
                elif isinstance(content, str):
                    query = content.strip()
                break

        if not query:
            return messages

        logger.info({
            "event": "search_executing",
            "backend": self.backend_name,
            "query": query[:200],
        })

        results = self.search_all(query)  # Use all backends + MCP tools in parallel
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
