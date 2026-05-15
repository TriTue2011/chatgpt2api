"""
Gemini Image Adapter — port from 9router gemini.js.

Google Gemini image generation via Imagen.
Uses Gemini API: https://generativelanguage.googleapis.com/v1beta/models/
"""

from __future__ import annotations

import base64
from typing import Any

from curl_cffi import requests

from services.image_providers._base import BaseImageAdapter, now_sec
from utils.log import logger


class GeminiImageAdapter(BaseImageAdapter):
    """Gemini Imagen image generation adapter.

    Model format: gemini-image/imagen-3.0-generate-001
    Uses Gemini generateContent API with image generation config.
    Supports API key rotation from api_keys array.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    _key_index: int = 0

    def _get_api_keys(self, credentials: dict[str, Any] | None) -> list[str]:
        """Get all available API keys from credentials."""
        if not credentials or not isinstance(credentials, dict):
            return []
        keys = credentials.get("apiKeys") or credentials.get("api_keys") or []
        if isinstance(keys, list) and keys:
            return [str(k) for k in keys if k]
        single = str(credentials.get("apiKey") or credentials.get("api_key") or "")
        return [single] if single else []

    def build_url(self, model: str, credentials: dict[str, Any] | None) -> str:
        api_key = ""
        if credentials and isinstance(credentials, dict):
            keys = self._get_api_keys(credentials)
            if keys:
                self._key_index = (self._key_index + 1) % len(keys)
                api_key = keys[self._key_index]
        return f"{self.BASE_URL}/{model}:generateContent?key={api_key}"

    def build_body(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        prompt = str(body.get("prompt") or "")
        n = max(1, min(4, int(body.get("n") or 1)))

        return {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageGenerationConfig": {
                    "numberOfImages": n,
                },
            },
        }

    def build_headers(
        self,
        credentials: dict[str, Any] | None,
        request_body: dict[str, Any],
        model: str,
        body: dict[str, Any],
    ) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def parse_response(self, response: Any) -> dict[str, Any] | None:
        """Extract inline image data from Gemini response."""
        if not hasattr(response, "json"):
            return None

        data = response.json()

        # Check for error
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"Gemini API error {err.get('status','')}: {err.get('message','')[:200]}")

        images = []

        candidates = data.get("candidates") or []
        for candidate in candidates:
            content = candidate.get("content") or {}
            parts = content.get("parts") or []
            for part in parts:
                if "inlineData" in part:
                    inline = part["inlineData"]
                    b64 = inline.get("data") or ""
                    if b64:
                        images.append({"b64_json": b64})

        return {"data": images} if images else None

    def normalize(self, parsed: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        data = parsed.get("data") or []
        return {"created": now_sec(), "data": data}

    def test_connection(self, credentials: dict[str, Any] | None = None) -> bool:
        try:
            resp = requests.get("https://generativelanguage.googleapis.com", timeout=10)
            return resp.status_code < 500
        except Exception:
            return False


gemini_image_adapter = GeminiImageAdapter()
