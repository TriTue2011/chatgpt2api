"""
OpenAI OAuth Provider — use Codex OAuth tokens to call OpenAI API directly.

9router's Codex tokens are OpenAI OAuth tokens — they work with api.openai.com
exactly like API keys. No 24KB limit, no browser impersonation, no PoW.

Flow:
1. Import 9router backup → extract Codex tokens → store as type="codex"
2. When model uses cx/ prefix → pick a Codex token → call api.openai.com/v1/chat/completions
3. Token refresh via OAuth (port from 9router tokenRefresh.js)

This is the SAME as how 9router does ChatGPT via OAuth.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from curl_cffi import requests

from services.config import config
from services.account_service import account_service
from utils.log import logger

OPENAI_API_BASE = "https://api.openai.com"


class OpenAIOAuthProvider:
    """OpenAI API via OAuth token (from 9router Codex provider).

    Uses access_token as Bearer token to api.openai.com.
    """

    def chat_completions(
        self,
        access_token: str,
        messages: list[dict[str, Any]],
        model: str = "auto",
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        **kwargs,
    ) -> dict[str, Any] | Iterator[str]:
        """Send chat request to OpenAI API using OAuth token."""

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        body.update(kwargs)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        }

        url = f"{OPENAI_API_BASE}/v1/chat/completions"

        logger.info({
            "event": "openai_oauth_request",
            "model": model,
            "stream": stream,
            "message_count": len(messages),
        })

        try:
            resp = requests.post(
                url, headers=headers, json=body, timeout=300, stream=stream
            )

            if resp.status_code == 401:
                raise RuntimeError("OpenAI OAuth token expired or invalid")
            if resp.status_code == 429:
                raise RuntimeError("OpenAI rate limited")
            if resp.status_code >= 400:
                error_text = ""
                try:
                    error_text = resp.text[:500]
                except Exception:
                    pass
                raise RuntimeError(f"OpenAI error: status={resp.status_code}, body={error_text}")

            if stream:
                return self._stream_response(resp)
            else:
                return resp.json()

        except requests.RequestsError as exc:
            raise RuntimeError(f"OpenAI connection failed: {exc}") from exc

    def _stream_response(self, response) -> Iterator[str]:
        """Pass through SSE from OpenAI API."""
        try:
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="ignore") if isinstance(raw_line, bytes) else str(raw_line)
                yield line + "\n"
        except Exception as exc:
            logger.error({"event": "openai_oauth_stream_error", "error": str(exc)})
            error_chunk = json.dumps({
                "error": {"message": str(exc), "type": "stream_error"}
            }, ensure_ascii=False)
            yield f"data: {error_chunk}\n\n"
            yield "data: [DONE]\n\n"

    def list_models(self, access_token: str) -> list[dict[str, Any]]:
        """Fetch available models from OpenAI API."""
        try:
            resp = requests.get(
                f"{OPENAI_API_BASE}/v1/models",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            models = data.get("data") or []
            return [
                {
                    "id": f"cx/{m.get('id', '')}",
                    "object": "model",
                    "created": m.get("created", 0),
                    "owned_by": m.get("owned_by", "openai-oauth"),
                }
                for m in models
                if isinstance(m, dict)
            ]
        except Exception as exc:
            logger.warning({"event": "openai_models_error", "error": str(exc)})
            return []

    def get_token_for_request(self, exclude_tokens: set[str] | None = None) -> str:
        """Get next available Codex OAuth token from account pool."""
        excluded = set(exclude_tokens or set())
        with account_service._lock:
            candidates = [
                token
                for item in account_service._accounts.values()
                if item.get("type") == "codex"
                and item.get("status") not in {"禁用", "异常"}
                and (token := item.get("access_token") or "")
                and token not in excluded
            ]
            if not candidates:
                raise RuntimeError("No Codex OAuth tokens available. Import 9router backup first.")
            token = candidates[account_service._index % len(candidates)]
            account_service._index += 1
            return token


# Singleton
openai_oauth = OpenAIOAuthProvider()
