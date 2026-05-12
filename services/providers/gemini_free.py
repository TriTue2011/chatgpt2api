"""
Gemini AI Studio Provider — Google Gemini API.

Free tier: 15 RPM, 1M tokens/day on gemini-2.5-flash via AI Studio.
Paid: unlimited via Google Cloud billing.
API key from: https://aistudio.google.com/apikey

Translates OpenAI format → Gemini format (port from 9router open-sse/translator/).
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from curl_cffi import requests

from services.config import config
from utils.log import logger

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"


def _openai_to_gemini_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI message format → Gemini contents format."""
    contents: list[dict[str, Any]] = []
    system_parts: list[str] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            text_parts = []
            image_parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(str(part.get("text", "")))
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "") if isinstance(part.get("image_url"), dict) else ""
                        if url.startswith("data:"):
                            header, b64 = url.split(",", 1)
                            mime = header.split(";")[0].replace("data:", "")
                            image_parts.append({"inlineData": {"mimeType": mime, "data": b64}})
            content = " ".join(text_parts) if text_parts else ""
            if image_parts:
                contents.append({"role": "user", "parts": [{"text": content}, *image_parts]})
                continue
        else:
            content = str(content or "")

        if role == "system":
            system_parts.append(content)
            continue

        gemini_role = "user" if role == "user" else "model"
        contents.append({"role": gemini_role, "parts": [{"text": content}]})

    system_instruction = None
    if system_parts:
        system_instruction = {"parts": [{"text": "\n".join(system_parts)}]}

    return contents, system_instruction


class GeminiProvider:
    """Google Gemini API provider — free & paid tiers."""

    @property
    def api_key(self) -> str:
        cfg = config.data.get("providers") or {}
        gemini_cfg = cfg.get("gemini_free") or {}
        return str(gemini_cfg.get("api_key") or "").strip()

    @property
    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            resp = requests.get(
                f"{GEMINI_BASE_URL}/models?key={self.api_key}",
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[dict[str, Any]]:
        """Fetch available Gemini models."""
        if not self.api_key:
            return []

        try:
            resp = requests.get(
                f"{GEMINI_BASE_URL}/models?key={self.api_key}",
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            models = data.get("models") or []
            return [
                {
                    "id": f"gemini/{m.get('name', '').replace('models/', '')}",
                    "object": "model",
                    "created": 0,
                    "owned_by": "google",
                }
                for m in models
                if isinstance(m, dict)
                and "generateContent" in (m.get("supportedGenerationMethods") or [])
            ]
        except Exception as exc:
            logger.warning({"event": "gemini_models_error", "error": str(exc)})
            return []

    def chat_completions(
        self,
        messages: list[dict[str, Any]],
        model: str = GEMINI_DEFAULT_MODEL,
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Send chat request to Gemini API.

        Translates OpenAI format → Gemini format internally.
        """
        if not self.api_key:
            raise RuntimeError("Gemini API key not configured")

        contents, system_instruction = _openai_to_gemini_messages(messages)

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {},
        }
        if system_instruction:
            body["systemInstruction"] = system_instruction
        if temperature is not None:
            body["generationConfig"]["temperature"] = temperature
        if max_tokens:
            body["generationConfig"]["maxOutputTokens"] = max_tokens

        url = f"{GEMINI_BASE_URL}/models/{model}:{'streamGenerateContent' if stream else 'generateContent'}?key={self.api_key}"

        logger.info({
            "event": "gemini_request",
            "model": model,
            "stream": stream,
            "message_count": len(messages),
        })

        try:
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=body,
                timeout=300,
                stream=stream,
            )

            if resp.status_code != 200:
                error_text = ""
                try:
                    error_text = resp.text[:500]
                except Exception:
                    pass
                raise RuntimeError(f"Gemini error: status={resp.status_code}, body={error_text}")

            if stream:
                return self._stream_response(resp, model)
            else:
                return self._to_openai_format(resp.json(), model)

        except requests.RequestsError as exc:
            raise RuntimeError(f"Gemini connection failed: {exc}") from exc

    def _to_openai_format(self, data: dict[str, Any], model: str) -> dict[str, Any]:
        """Convert Gemini response → OpenAI chat completion format."""
        import time
        import uuid

        text_parts: list[str] = []
        candidates = data.get("candidates") or []
        for candidate in candidates:
            content = candidate.get("content") or {}
            parts = content.get("parts") or []
            for part in parts:
                if "text" in part:
                    text_parts.append(part["text"])

        content = "".join(text_parts)

        usage = data.get("usageMetadata") or {}
        prompt_tokens = int(usage.get("promptTokenCount") or 0)
        completion_tokens = int(usage.get("candidatesTokenCount") or 0)

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    def _stream_response(self, response, model: str) -> Iterator[dict[str, Any]]:
        """Convert Gemini SSE → OpenAI chat completion chunks (dicts)."""
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        sent_role = False

        try:
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="ignore") if isinstance(raw_line, bytes) else str(raw_line)

                # Gemini streams JSON arrays
                if line.startswith("["):
                    line = line[1:]
                if line.endswith(","):
                    line = line[:-1]
                if line.endswith("]"):
                    line = line[:-1]

                if not line.strip():
                    continue

                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                candidates = chunk.get("candidates") or []
                for candidate in candidates:
                    content = candidate.get("content") or {}
                    parts = content.get("parts") or []
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            if not sent_role:
                                sent_role = True
                                yield {
                                    "id": completion_id, "object": "chat.completion.chunk",
                                    "created": created, "model": model,
                                    "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
                                }
                            else:
                                yield {
                                    "id": completion_id, "object": "chat.completion.chunk",
                                    "created": created, "model": model,
                                    "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                                }

        except Exception as exc:
            logger.error({"event": "gemini_stream_error", "error": str(exc)})

        if not sent_role:
            yield {
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
            }
        yield {
            "id": completion_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }


# Singleton
gemini_provider = GeminiProvider()
