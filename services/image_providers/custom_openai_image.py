"""
Custom OpenAI-compatible Image Adapter — uses chat endpoint for image generation.

For custom providers that support image gen via their chat API (e.g., Gemini API
server with /v1/responses or built-in image generation tools).
"""

from __future__ import annotations

import base64
from typing import Any

from curl_cffi import requests

from services.image_providers._base import (
    BaseImageAdapter,
    now_sec,
    size_to_width_height,
)
from services.config import config
from utils.log import logger


class CustomOpenAIImageAdapter(BaseImageAdapter):
    """Generic image adapter for custom providers — uses chat endpoint."""

    def __init__(self, provider_id: str):
        self.provider_id = provider_id

    def _get_provider_config(self) -> dict[str, Any] | None:
        providers = config.data.get("custom_providers") or {}
        return providers.get(self.provider_id)

    def build_url(self, model: str, credentials: dict[str, Any] | None) -> str:
        cfg = self._get_provider_config()
        base_url = str(cfg.get("base_url") or "").rstrip("/") if cfg else ""
        return f"{base_url}/v1/chat/completions"

    def build_body(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        prompt = str(body.get("prompt") or "")
        size = str(body.get("size") or "1792x1024")
        w, h = size_to_width_height(size)

        return {
            "model": model,
            "messages": [{
                "role": "user",
                "content": (
                    f"Generate an image based on this description: {prompt}\n"
                    f"Size: {w}x{h}\n"
                    f"Return the image as a base64 data URL."
                ),
            }],
            "max_tokens": 4096,
            "temperature": 0.9,
        }

    def build_headers(
        self,
        credentials: dict[str, Any] | None,
        request_body: dict[str, Any],
        model: str,
        body: dict[str, Any],
    ) -> dict[str, str]:
        cfg = self._get_provider_config()
        api_key = ""
        if cfg:
            keys = cfg.get("api_keys") or []
            if not keys:
                api_key = str(cfg.get("api_key") or "")
            else:
                api_key = keys[0]
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def parse_response(self, response: Any) -> dict[str, Any] | None:
        """Parse chat response to extract generated image (base64)."""
        if not hasattr(response, "json"):
            return None

        try:
            data = response.json()
        except Exception as exc:
            logger.error({"event": "custom_image_parse_error", "error": str(exc)})
            return None

        choices = data.get("choices") or []
        for choice in choices:
            content = choice.get("message", {}).get("content") or ""
            if not content:
                continue

            # Try to extract base64 image from response
            import re
            # Match data:image/...;base64,...
            match = re.search(r'data:image/[^;]+;base64,([A-Za-z0-9+/=]+)', content)
            if match:
                return {"data": [{"b64_json": match.group(1)}]}

            # Maybe the entire response is a base64 image
            if content.startswith('/9j/') or content.startswith('iVBOR'):
                return {"data": [{"b64_json": content}]}

            # If the response contains a URL to an image
            url_match = re.search(r'https?://[^\s"]+\.(?:png|jpg|jpeg|webp)[^\s"]*', content)
            if url_match:
                from services.image_providers._base import url_to_base64
                try:
                    b64 = url_to_base64(url_match.group(0))
                    return {"data": [{"b64_json": b64}]}
                except Exception:
                    pass

        logger.warning({"event": "custom_image_no_data", "provider": self.provider_id})
        return None

    def normalize(self, parsed: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        data = parsed.get("data") or []
        normalized_data = []
        for item in data:
            b64 = item.get("b64_json") or ""
            if b64 and not b64.startswith("data:"):
                b64 = f"data:image/png;base64,{b64}"
            if b64:
                normalized_data.append({"b64_json": b64, "revised_prompt": str(body.get("prompt") or "")})
        return {"created": now_sec(), "data": normalized_data} if normalized_data else {"created": now_sec(), "data": []}

    def test_connection(self, credentials: dict[str, Any] | None = None) -> bool:
        cfg = self._get_provider_config()
        if not cfg:
            return False
        base_url = str(cfg.get("base_url") or "").rstrip("/")
        keys = cfg.get("api_keys") or [str(cfg.get("api_key") or "")]
        api_key = keys[0] if keys else ""
        try:
            resp = requests.get(
                f"{base_url}/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False
