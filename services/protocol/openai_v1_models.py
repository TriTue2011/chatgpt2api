from __future__ import annotations

from typing import Any

from services.openai_backend_api import OpenAIBackendAPI
from services.config import config
from utils.helper import IMAGE_MODELS
from utils.log import logger


# Static provider models (always available)
STATIC_MODELS = [
    # OpenCode free models
    {"id": "oc/auto", "object": "model", "created": 0, "owned_by": "opencode"},
    {"id": "oc/nemotron-3-super-free", "object": "model", "created": 0, "owned_by": "opencode"},
    {"id": "oc/minimax-m2.5-free", "object": "model", "created": 0, "owned_by": "opencode"},
    {"id": "oc/ring-2.6-1t-free", "object": "model", "created": 0, "owned_by": "opencode"},
    {"id": "oc/trinity-large-preview-free", "object": "model", "created": 0, "owned_by": "opencode"},
    # Codex OAuth models
    {"id": "cx/auto", "object": "model", "created": 0, "owned_by": "openai-oauth"},
    # Gemini models
    {"id": "gemini_free/auto", "object": "model", "created": 0, "owned_by": "google"},
    {"id": "gemini_free/gemini-2.5-flash", "object": "model", "created": 0, "owned_by": "google"},
    # Combo models
    {"id": "ha-agent", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
    # ChatGPT models
    {"id": "chatgpt/auto", "object": "model", "created": 0, "owned_by": "chatgpt"},
]


def list_models() -> dict[str, Any]:
    result = {"object": "list", "data": []}

    # Try fetching from ChatGPT backend (for DALL-E / image models)
    try:
        result = OpenAIBackendAPI().list_models()
    except Exception as exc:
        logger.warning({"event": "list_models_chatgpt_failed", "error": str(exc)})

    data = result.get("data")
    if not isinstance(data, list):
        data = []

    seen = {str(item.get("id") or "").strip() for item in data if isinstance(item, dict)}

    # Add image models
    for model in sorted(IMAGE_MODELS):
        if model not in seen:
            data.append({
                "id": model, "object": "model", "created": 0,
                "owned_by": "chatgpt2api", "permission": [],
                "root": model, "parent": None,
            })

    # Add static provider models (OpenCode, Codex, combos)
    for model_info in STATIC_MODELS:
        if model_info["id"] not in seen:
            data.append(model_info)

    # Add combo models from config
    combos = config.data.get("combo_models") or {}
    if isinstance(combos, dict):
        for combo_name in combos:
            if combo_name not in seen:
                data.append({
                    "id": combo_name, "object": "model", "created": 0,
                    "owned_by": "chatgpt2api",
                })

    # Add image provider models from config
    providers = config.data.get("providers") or {}
    if isinstance(providers, dict):
        for provider_name, provider_cfg in providers.items():
            if isinstance(provider_cfg, dict) and provider_cfg.get("enabled"):
                provider_id = f"{provider_name}/auto"
                if provider_id not in seen and provider_name not in ("gemini_free", "serper", "searxng", "brave"):
                    data.append({
                        "id": provider_id, "object": "model", "created": 0,
                        "owned_by": provider_name,
                    })

    result["data"] = data
    return result
