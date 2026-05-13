from __future__ import annotations

import base64
import json
from typing import Any, Iterator

from curl_cffi import requests as cffi_requests

from services.protocol.conversation import (
    ConversationRequest,
    ImageOutput,
    collect_image_outputs,
    format_image_result,
    stream_image_chunks,
    stream_image_outputs_with_pool,
)
from services.backend_router import backend_router
from services.image_providers import get_image_adapter, is_noauth_image_provider
from services.image_providers._base import now_sec
from utils.log import logger


def _handle_adapter_image(route, body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Handle image generation through an adapter (sdwebui, huggingface, etc.)."""
    adapter = get_image_adapter(route.provider)
    if not adapter:
        # Custom providers don't have image adapters — raise to trigger combo fallback
        raise RuntimeError(f"Provider '{route.provider}' does not support image generation")

    prompt = str(body.get("prompt") or "")
    n = max(1, min(4, int(body.get("n") or 1)))
    response_format = str(body.get("response_format") or "b64_json")
    base_url_str = str(body.get("base_url") or "") or None
    stream = bool(body.get("stream"))

    # Build credentials from config
    provider_config = (__import__("services.config").config.data.get("providers") or {}).get(route.provider) or {}

    credentials = {}
    if route.no_auth:
        credentials = {"accessToken": "public"}
    else:
        credentials = {
            "apiKey": str(provider_config.get("api_key") or ""),
            "accessToken": str(provider_config.get("api_key") or ""),
        }

    # For sdwebui, use configured base_url
    if route.provider == "sdwebui":
        adapter.base_url = str(provider_config.get("base_url") or "http://localhost:7860").rstrip("/")

    # Generate n images
    all_data: list[dict[str, Any]] = []
    stream_outputs: list[ImageOutput] = []

    for idx in range(n):
        try:
            url = adapter.build_url(route.model, credentials)
            req_body = adapter.build_body(route.model, body)
            headers = adapter.build_headers(credentials, req_body, route.model, body)

            logger.info({
                "event": "image_adapter_request",
                "provider": route.provider,
                "model": route.model,
                "url": url,
            })

            resp = cffi_requests.post(
                url,
                headers=headers,
                json=req_body if "Content-Type" in str(headers) and "json" in str(headers).lower() else None,
                data=json.dumps(req_body).encode("utf-8") if "Content-Type" not in str(headers) or "json" in str(headers).lower() else req_body,
                timeout=300,
            )

            if resp.status_code >= 400:
                error_text = ""
                try:
                    error_text = resp.text[:500]
                except Exception:
                    pass
                logger.error({
                    "event": "image_adapter_error",
                    "provider": route.provider,
                    "status": resp.status_code,
                    "error": error_text,
                })
                raise RuntimeError(f"Image generation failed: {route.provider} status={resp.status_code}")

            # Try custom parse_response first (async adapters)
            parsed = adapter.parse_response(resp) if hasattr(adapter, "parse_response") else None

            if parsed is None:
                # Default: parse JSON + normalize
                try:
                    raw_json = resp.json()
                except Exception:
                    # Binary response (image bytes)
                    raw_json = {"image_bytes": resp.content}
                parsed = raw_json

            normalized = adapter.normalize(parsed, body)
            data_items = normalized.get("data") or []
            all_data.extend(data_items)

            if stream:
                stream_outputs.append(ImageOutput(
                    kind="result",
                    model=body.get("model", "unknown"),
                    index=idx + 1,
                    total=n,
                    data=data_items,
                ))

        except Exception as exc:
            logger.error({"event": "image_adapter_fatal", "provider": route.provider, "error": str(exc)})
            raise RuntimeError(f"Image generation failed: {exc}") from exc

    if stream and stream_outputs:
        # Yield stream chunks
        def _stream():
            for output in stream_outputs:
                yield output.to_chunk()
        return _stream()

    # Non-streaming response
    result = format_image_result(
        all_data,
        prompt,
        response_format,
        base_url_str,
    )
    if not result.get("data"):
        result["message"] = "Image generation completed but no images returned."
    return result


def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    prompt = str(body.get("prompt") or "")
    model = str(body.get("model") or "gpt-image-2")
    n = int(body.get("n") or 1)
    size = body.get("size")
    response_format = str(body.get("response_format") or "b64_json")
    base_url_str = str(body.get("base_url") or "") or None
    stream = bool(body.get("stream"))

    # Combo model support — try each model in the combo until one succeeds
    if backend_router.is_combo(model):
        routes = backend_router.route_combo(model)
        last_error = ""
        for route in routes:
            try:
                # Try all models in combo: image models + custom providers (may support image gen)
                if route.is_image or route.provider == "chatgpt" or route.provider.startswith("custom:"):
                    return _handle_single_image(route, body)
            except Exception as exc:
                last_error = str(exc)
                logger.warning({
                    "event": "image_combo_fallback",
                    "model": route.model,
                    "error": last_error,
                })
                continue
        raise RuntimeError(f"All image models in combo '{model}' failed: {last_error}")

    # Single model routing
    route = backend_router.route(model)
    return _handle_single_image(route, body)


def _handle_single_image(route, body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Handle image generation for a single model (adapter or ChatGPT DALL-E)."""
    prompt = str(body.get("prompt") or "")
    model = str(body.get("model") or "gpt-image-2")
    n = int(body.get("n") or 1)
    size = body.get("size")
    response_format = str(body.get("response_format") or "b64_json")
    base_url_str = str(body.get("base_url") or "") or None
    stream = bool(body.get("stream"))

    # If routed to a non-ChatGPT image provider, use adapter
    if route.provider != "chatgpt" and (route.is_image or route.provider.startswith("custom:")):
        logger.info({
            "event": "image_routed_to_adapter",
            "provider": route.provider,
            "model": route.model,
        })
        try:
            return _handle_adapter_image(route, body)
        except Exception as exc:
            logger.warning({
                "event": "image_adapter_fallback",
                "provider": route.provider,
                "error": str(exc),
            })
            raise  # Re-raise to trigger combo fallback

    # Default: use existing ChatGPT DALL-E flow (unchanged)
    outputs = stream_image_outputs_with_pool(ConversationRequest(
        prompt=prompt,
        model=route.model if route.model != "auto" else model,
        n=n,
        size=size,
        response_format=response_format,
        base_url=base_url_str,
        message_as_error=True,
    ))
    if stream:
        return stream_image_chunks(outputs)
    return collect_image_outputs(outputs)
