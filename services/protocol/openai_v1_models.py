from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from services.account_service import account_service
from services.openai_backend_api import OpenAIBackendAPI
from services.config import config
from utils.helper import IMAGE_MODELS, anonymize_token
from utils.log import logger


# Static provider models (always available regardless of ChatGPT tokens)
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


def _fetch_models_for_token(token: str) -> tuple[str, set[str]]:
    """Fetch available model IDs for a single token. Returns (token_anon, model_id_set)."""
    try:
        api = OpenAIBackendAPI(access_token=token)
        result = api.list_models()
        models = set()
        for item in result.get("data", []):
            if isinstance(item, dict) and item.get("id"):
                models.add(str(item["id"]))
        return (anonymize_token(token), models)
    except Exception as exc:
        logger.warning({"event": "list_models_token_failed", "token": anonymize_token(token), "error": str(exc)})
        return (anonymize_token(token), None)


def list_models() -> dict[str, Any]:
    """Return available models — auto-fetch from all ChatGPT tokens, compute intersection."""
    data: list[dict[str, Any]] = []

    # Collect all active ChatGPT tokens (non-JWT, non-codex)
    active_tokens: list[str] = []
    with account_service._lock:
        for token, account in account_service._accounts.items():
            if not token or token == "public":
                continue
            status = str(account.get("status") or "")
            if status in {"禁用", "异常"}:
                continue
            # Skip JWT-only tokens (codex OAuth) — they can't query /backend-api/models
            if str(account.get("type") or "") == "codex" and token.startswith("eyJ"):
                continue
            active_tokens.append(token)

    # Fetch models from all tokens in parallel
    if active_tokens:
        token_model_sets: dict[str, set[str]] = {}
        failed_tokens: list[str] = []
        with ThreadPoolExecutor(max_workers=min(8, len(active_tokens))) as executor:
            futures = {
                executor.submit(_fetch_models_for_token, token): token
                for token in active_tokens
            }
            for future in as_completed(futures):
                token_anon, model_set = future.result()
                if model_set is not None:
                    token_model_sets[token_anon] = model_set
                else:
                    failed_tokens.append(token_anon)

        if token_model_sets:
            # Compute intersection — only models available to ALL tokens
            all_sets = list(token_model_sets.values())
            common_models = all_sets[0].copy()
            for s in all_sets[1:]:
                common_models &= s

            logger.info({
                "event": "list_models_intersection",
                "total_tokens": len(active_tokens),
                "successful": len(token_model_sets),
                "failed": len(failed_tokens),
                "common_count": len(common_models),
            })

            for slug in sorted(common_models):
                data.append({
                    "id": slug,
                    "object": "model",
                    "created": 0,
                    "owned_by": "chatgpt",
                    "permission": [],
                    "root": slug,
                    "parent": None,
                })
        else:
            logger.warning({"event": "list_models_all_failed", "tokens_attempted": len(active_tokens)})
    else:
        # Fallback: try anon (no token)
        try:
            result = OpenAIBackendAPI().list_models()
            for item in result.get("data", []):
                if isinstance(item, dict):
                    data.append(item)
        except Exception as exc:
            logger.warning({"event": "list_models_anon_failed", "error": str(exc)})

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

    return {"object": "list", "data": data}
