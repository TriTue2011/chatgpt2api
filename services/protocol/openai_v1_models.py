from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from curl_cffi import requests

from services.account_service import account_service, account_group
from services.openai_backend_api import OpenAIBackendAPI
from services.config import config, DATA_DIR
from utils.helper import IMAGE_MODELS, anonymize_token
from utils.log import logger


# Fallback static models — used when API fetch fails
# Model do CHÍNH TA định nghĩa mà thượng nguồn không có — LUÔN được ghép vào.
#
# Khác `FALLBACK_MODELS`: cái đó chỉ dùng khi lấy danh sách động THẤT BẠI.
# Để trống là đúng — mọi model hiện tại đều do thượng nguồn khai.
ALIAS_MODELS: dict[str, list[str]] = {}

FALLBACK_MODELS = {
    "opencode": [
        "oc/auto",
        "oc/nemotron-3-super-free",
        "oc/minimax-m2.5-free",
        "oc/ring-2.6-1t-free",
        "oc/trinity-large-preview-free",
    ],
    "gemini_free": [
        "gemini_free/auto",
        "gemini_free/gemini-2.5-flash",
        # Đo 08/08/2026: cả hai nhận được text, ảnh PNG và video MP4.
        # 3.6-flash cho chuỗi nhiều ảnh/video và cần mô tả chính xác hơn;
        # 3.5-flash-lite cho cảnh báo hàng loạt, nhanh và rẻ hơn.
        "gemini_free/gemini-3.6-flash",
        "gemini_free/gemini-3.5-flash-lite",
    ],
    "chatgpt": [
        "chatgpt/auto",
        "chatgpt/gpt-5-5",
        "chatgpt/gpt-5-5-instant",
        "chatgpt/gpt-5-5-thinking",
        "chatgpt/gpt-4.1-mini",
        "chatgpt/gpt-4.1-nano",
        "chatgpt/gpt-4o",
        "chatgpt/gpt-4o-mini",
        "chatgpt/o3",
        "chatgpt/o3-mini",
        "chatgpt/o4-mini",
    ],
    "chatgpt_web": [
        "cgw/auto",
        "cgw/gpt-5-5",
        "cgw/gpt-5-5-instant",
        "cgw/gpt-5-5-thinking",
        "cgw/gpt-4.1-mini",
        "cgw/gpt-4.1-nano",
        "cgw/gpt-4o",
        "cgw/gpt-4o-mini",
        "cgw/o3",
        "cgw/o3-mini",
        "cgw/o4-mini",
    ],
    "openai_oauth": [
        "cx/auto",
        # Danh sách này ĐO NGÀY 18/08/2026 bằng cách gọi thẳng
        # https://chatgpt.com/backend-api/codex/responses với token thật của một
        # tài khoản gói `go`, chứ không chép từ tài liệu.
        #
        # Cách phân biệt: model KHÔNG tồn tại thì API trả
        #   400 "The '<tên>' model is not supported when using Codex with a
        #        ChatGPT account."
        # còn model CÒN SỐNG thì đi tiếp một bước và trả
        #   400 "Stream must be set to true".
        # Đối chứng: một tên bịa ("khong-ton-tai-abc") nhận đúng câu thứ nhất,
        # nên câu đó đúng nghĩa là "không có model này".
        #
        # Kết quả: 5.3-codex, 5.3-codex-spark, 5.2, 5.1-codex, 5-codex đều đã
        # CHẾT — cả nhóm đó từng nằm ở đây và làm mọi request Codex trả 400.
        # GPT 5.6
        "cx/gpt-5.6-terra", "cx/gpt-5.6-terra-review",
        "cx/gpt-5.6-luna", "cx/gpt-5.6-luna-review",
        # GPT 5.5
        "cx/gpt-5.5", "cx/gpt-5.5-review",
        # GPT 5.4 — OpenAI báo ngừng cho đăng nhập ChatGPT từ 31/08/2026,
        # thay bằng 5.6-terra (cho 5.4) và 5.6-luna (cho 5.4-mini).
        "cx/gpt-5.4", "cx/gpt-5.4-review",
        "cx/gpt-5.4-mini", "cx/gpt-5.4-mini-review",
    ],
    # Static fallback only — the real catalogue is fetched live from the
    # captcha-solver (see `_fetch_web_models` below). These slugs match
    # what the upstream picker actually serves today so the static list
    # is at least directionally correct when the live fetch is offline.
    # Refreshed from live Gemini Web `wrb.fr` chat responses on 2026-05-25.
    # Tiers correspond to Google's reasoning effort levels:
    #   flash-lite  — fastest, no/low thinking
    #   flash       — default chat
    #   flash-extended — flash + extended thinking
    #   pro         — slower, deep thinking
    #   pro-thinking — pro + maximum reasoning (explicit deep-think mode)
    # Image generation models below — these never appear in the picker
    # because Gemini Web auto-routes image prompts through a
    # `data_analysis_tool` envelope. The RPC trace exposes the actual
    # model name (`Nano Banana 2`, `Imagen 4`) in the response footer.
    "gemini_web": [
        "gmw/pro",
        "gmw/deep-think",
        "gmw/nano-banana-2",
        "gmw/nano-banana-pro",
        "gmw/imagen-4",
    ],
    # Model ảnh NVIDIA — dò THẬT bằng key của máy chủ ngày 30/07 (POST
    # ai.api.nvidia.com/v1/genai/<model>), mỗi model chạy 3 lượt:
    #   flux.2-klein-4b   → 3/3 vẽ được, ~1,5s, ảnh ~200 KB  (steps trần 4)
    #   flux.1-dev        → 3/3 vẽ được, ~4,5s, ảnh ~70 KB   (steps 28)
    #   flux.1-schnell    → 3/3 HỎNG: nhận request rồi ngắt kết nối đúng 60,3s
    #                       (curl 56). Endpoint có tồn tại (gửi steps=8 trả 422
    #                       "≤ 4" ngay lập tức) nhưng SINH ẢNH không bao giờ
    #                       xong → bỏ, kẻo người dùng chọn rồi ngồi chờ 1 phút
    #                       để nhận lỗi.
    #   kontext-dev       → sống nhưng là model SỬA ảnh (422 "body.image
    #                       required"), không phải sinh ảnh từ chữ.
    #   stabilityai/* (sdxl-turbo, sd-3.5-large), briaai, consistory,
    #   generative-3d, flux.1-kontext-pro → 404, NVIDIA đã ngừng phục vụ.
    "nvidia_nim": [
        "nv/auto",
        "nv-image/black-forest-labs/flux.2-klein-4b",
        "nv-image/black-forest-labs/flux.1-dev",
    ],
    # TokenRouter (đường riêng tr/). Fallback tĩnh để trang Quản lý model vẫn có
    # model chọn khi /v1/models của TokenRouter tạm lỗi. list_models động sẽ ghi
    # đè bằng catalog thật của tài khoản.
    "tokenrouter": [
        "tr/moonshotai/kimi-k3-free",
    ],
    "chatgpt2api": [],
    "antigravity": [
        "ag/auto",
        "ag/gemini-3.1-pro-high",
        "ag/gemini-3.1-pro-high-thinking",
        "ag/gemini-3.1-flash-high",
    ],
}

GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _gemini_models_url() -> str:
    """Honor providers.gemini_free.base_url for VN-block proxy."""
    try:
        from services.config import config
        cfg = (config.data.get("providers") or {}).get("gemini_free") or {}
        override = str(cfg.get("base_url") or "").rstrip("/")
        if override:
            if not override.endswith("/v1beta"):
                override = override + "/v1beta"
            return override + "/models"
    except Exception:
        pass
    return GEMINI_MODELS_URL
OPENCODE_MODELS_URL = "https://opencode.ai/zen/v1/models"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
NVIDIA_MODELS_URL = "https://integrate.api.nvidia.com/v1/models"


def _get_gemini_keys() -> list[str]:
    cfg = config.data.get("providers") or {}
    gemini_cfg = cfg.get("gemini_free") or {}
    single = str(gemini_cfg.get("api_key") or "").strip()
    multi = gemini_cfg.get("api_keys") or []
    if not isinstance(multi, list):
        multi = []
    keys = [k.strip() for k in multi if k.strip()]
    if single and single not in keys:
        keys.insert(0, single)
    return keys


def _fetch_gemini_models() -> set[str]:
    """Fetch available models from Gemini API. Returns set of model IDs with gemini_free/ prefix."""
    keys = _get_gemini_keys()
    if not keys:
        logger.info({"event": "list_models_gemini_skip", "reason": "no_api_key"})
        return set()

    for key in keys:
        try:
            resp = requests.get(f"{_gemini_models_url()}?key={key}", timeout=10)
            if resp.status_code != 200:
                continue
            models = set()
            for item in resp.json().get("models", []):
                name = str(item.get("name", "")).replace("models/", "")
                methods = item.get("supportedGenerationMethods") or []
                if "generateContent" in methods:
                    models.add(f"gemini_free/{name}")
            if models:
                logger.info({"event": "list_models_gemini_fetched", "count": len(models)})
                return models
        except Exception as exc:
            logger.warning({"event": "list_models_gemini_error", "error": str(exc)})
            continue

    return set()


def _fetch_web_models(provider_key: str, endpoint_path: str) -> set[str]:
    """Shared helper for the captcha-solver-backed providers (gemini_web,
    gemini_web). Reads the profile + captcha-solver URL from
    `config.providers.<provider_key>`, hits the live-list endpoint,
    and returns the prefixed model IDs. Empty set when the provider
    isn't enabled / has no profile / the captcha-solver is unreachable —
    the caller then falls back to the static `FALLBACK_MODELS` entry.
    """
    cfg = (config.data.get("providers") or {}).get(provider_key) or {}
    if not cfg.get("enabled"):
        return set()
    profile = str(cfg.get("profile") or "").strip()
    if not profile:
        return set()
    # captcha_solver_url + key live on `providers.flow` historically; some
    # deployments duplicate them on each web provider. Check both.
    from services.captcha import captcha_base
    _raw = str(cfg.get("captcha_solver_url") or "").strip()
    cs_url = captcha_base(_raw) if _raw else ""  # /api/captcha (proxy) → internal
    cs_key = str(cfg.get("captcha_solver_api_key") or "").strip()
    if not cs_url or not cs_key:
        flow_cfg = (config.data.get("providers") or {}).get("flow") or {}
        _raw2 = str(flow_cfg.get("captcha_solver_url") or "").strip()
        cs_url = cs_url or (captcha_base(_raw2) if _raw2 else "")
        cs_key = cs_key or str(flow_cfg.get("captcha_solver_api_key") or "").strip()
    if not cs_url or not cs_key:
        logger.info({"event": "list_models_web_skip", "provider": provider_key, "reason": "no_captcha_solver_config"})
        return set()
    try:
        resp = requests.get(
            f"{cs_url}{endpoint_path}/{profile}/models",
            headers={"Authorization": f"Bearer {cs_key}"},
            timeout=45,
        )
        if resp.status_code != 200:
            logger.warning({"event": "list_models_web_http", "provider": provider_key,
                            "status": resp.status_code, "body": resp.text[:200]})
            return set()
        data = resp.json()
    except Exception as exc:
        logger.warning({"event": "list_models_web_error", "provider": provider_key, "error": str(exc)[:200]})
        return set()
    out: set[str] = set()
    for m in (data.get("models") or []):
        mid = str(m.get("id") or "").strip()
        if mid:
            out.add(mid)
    logger.info({"event": "list_models_web_fetched", "provider": provider_key,
                 "profile": profile, "count": len(out)})
    return out


def _fetch_gemini_web_models() -> set[str]:
    return _fetch_web_models("gemini_web", "/v1/gemini-web")


def _fetch_gemini_web_api_models() -> set[str]:
    """Model cookie-API do chính các GeminiClient đã init khám phá."""
    try:
        from api.gemini_web import available_model_ids

        return set(available_model_ids())
    except Exception as exc:
        logger.warning({"event": "list_models_gma_error", "error": str(exc)[:200]})
        return set()


def _merge_runtime_gma_models(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ghép registry GMA trong RAM vào cả cache đĩa còn hạn.

    Client được prewarm sau lúc cache model có thể đã nạp. Không ghép
    ở đường cache-hit thì model mới phải chờ tới lượt refresh 6 giờ.
    """
    merged = list(data)
    seen = {str(item.get("id") or "") for item in merged}
    for model_id in sorted(_fetch_gemini_web_api_models()):
        if model_id in seen:
            continue
        seen.add(model_id)
        merged.append({
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "gemini_web_api",
        })
    return merged


def _fetch_opencode_models() -> set[str]:
    """Fetch available free models from OpenCode API. Returns set of model IDs with oc/ prefix."""
    try:
        resp = requests.get(
            OPENCODE_MODELS_URL,
            headers={"Authorization": "Bearer public", "x-opencode-client": "desktop"},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning({"event": "list_models_opencode_failed", "status": resp.status_code})
            return set()

        models = set()
        for item in resp.json().get("data", []):
            slug = str(item.get("id") or "").strip()
            if not slug:
                continue
            # Only include free models (ending in -free)
            if slug.endswith("-free"):
                models.add(f"oc/{slug}")
        if models:
            logger.info({"event": "list_models_opencode_fetched", "count": len(models)})
            return models
    except Exception as exc:
        logger.warning({"event": "list_models_opencode_error", "error": str(exc)})

    return set()


def _fetch_openrouter_models() -> set[str]:
    """Fetch available models from OpenRouter API. Returns set of model IDs with openrouter/ prefix."""
    cfg = config.data.get("providers") or {}
    or_cfg = cfg.get("openrouter") or {}
    api_key = str(or_cfg.get("api_key") or "").strip()
    if not api_key:
        return set()

    try:
        resp = requests.get(
            OPENROUTER_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning({"event": "list_models_openrouter_failed", "status": resp.status_code})
            return set()

        models = set()
        for item in resp.json().get("data", []):
            slug = str(item.get("id") or "").strip()
            if slug:
                models.add(f"openrouter/{slug}")
        if models:
            logger.info({"event": "list_models_openrouter_fetched", "count": len(models)})
            return models
    except Exception as exc:
        logger.warning({"event": "list_models_openrouter_error", "error": str(exc)})

    return set()


def _fetch_tokenrouter_models() -> set[str]:
    """Model TokenRouter (đường riêng tr/) cho trang Quản lý model.

    Không có thì provider tokenrouter không hiện trong Quản lý model, và các mục
    (combo, mặc định…) không có gì để chọn — đúng lỗi người vận hành báo 30/07.
    Chỉ liệt kê khi provider BẬT + có key; gắn tiền tố tr/ đúng như router.
    """
    try:
        from services.providers.tokenrouter import tokenrouter_provider
        if not tokenrouter_provider.enabled:
            return set()
        out = set()
        for m in tokenrouter_provider.list_models():
            mid = str(m.get("id") or "").strip()
            if mid:
                out.add(mid if mid.startswith("tr/") else f"tr/{mid}")
        if out:
            logger.info({"event": "list_models_tokenrouter", "count": len(out)})
        return out
    except Exception as exc:
        logger.warning({"event": "list_models_tokenrouter_failed", "error": str(exc)[:160]})
        return set()


def _fetch_nvidia_models() -> set[str]:
    """Fetch available models from NVIDIA NIM API. Returns set of model IDs with nv/ prefix."""
    cfg = config.data.get("providers") or {}
    nv_cfg = cfg.get("nvidia_nim") or {}
    single = str(nv_cfg.get("api_key") or "").strip()
    multi = nv_cfg.get("api_keys") or []
    if not isinstance(multi, list):
        multi = []
    keys = [k.strip() for k in multi if k.strip()]
    if single and single not in keys:
        keys.insert(0, single)

    if not keys:
        logger.info({"event": "list_models_nvidia_skip", "reason": "no_api_key"})
        return set()

    for key in keys:
        try:
            resp = requests.get(
                f"{NVIDIA_MODELS_URL}",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            models = set()
            for item in resp.json().get("data", []):
                slug = str(item.get("id") or "").strip()
                if slug:
                    models.add(f"nv/{slug}")

            # NVIDIA image gen models are on a separate API (ai.api.nvidia.com/v1/genai/)
            # There's no list endpoint, so we hardcode known models with nv-image/ prefix.
            # Danh sách này đã DÒ THẬT ngày 30/07 (3 lượt/model) — xem chú thích đầy
            # đủ ở STATIC_MODELS. Chỉ giữ đúng hai model VẼ ĐƯỢC.
            nv_image_models = [
                "nv-image/black-forest-labs/flux.2-klein-4b",
                "nv-image/black-forest-labs/flux.1-dev",
            ]
            cfg = config.data.get("providers") or {}
            nv_cfg = cfg.get("nvidia_nim") or {}
            if nv_cfg.get("enabled", True):
                models.update(nv_image_models)

            if models:
                logger.info({"event": "list_models_nvidia_fetched", "count": len(models)})
                return models
        except Exception as exc:
            logger.warning({"event": "list_models_nvidia_error", "error": str(exc)})
            continue

    return set()


def _fetch_codex_models() -> set[str]:
    """Fetch models from Codex OAuth tokens + hardcoded 9router models."""
    from services.openai_backend_api import OpenAIBackendAPI

    # Always include hardcoded Codex models (not returned by API)
    models = set(_apply_fallback("openai_oauth"))

    codex_tokens: list[str] = []
    with account_service._lock:
        for token, account in account_service._accounts.items():
            if not token or token == "public":
                continue
            status = str(account.get("status") or "")
            if status in {"disabled", "error"}:
                continue
            if str(account.get("type") or "") == "codex" and token.startswith("eyJ"):
                codex_tokens.append(token)

    if not codex_tokens:
        logger.info({"event": "list_models_codex_skip", "reason": "no_codex_tokens",
                      "hardcoded_count": len(models)})
        return models

    for token in codex_tokens[:3]:
        try:
            api = OpenAIBackendAPI(access_token=token)
            result = api.list_models()
            for item in result.get("data", []):
                slug = str(item.get("id") or "").strip()
                if slug:
                    models.add(f"cx/{slug}")
            # Add reasoning effort variants for each Codex model so user can pick
            # different effort tiers from UI. Suffix is parsed client-side in
            # openai_oauth.chat_completions to set body["reasoning"]["effort"].
            base_models = [m for m in list(models) if m.startswith("cx/")]
            for base in base_models:
                slug = base[3:]
                # Skip variants that already have effort/review suffix
                if any(slug.endswith(f"-{eff}") for eff in ("low", "high", "xhigh", "none", "medium")):
                    continue
                if slug.endswith("-review"):
                    continue
                for effort in ("low", "high"):
                    models.add(f"{base}-{effort}")
            logger.info({"event": "list_models_codex_fetched",
                          "api_count": len(models) - len(_apply_fallback("openai_oauth")),
                          "total": len(models)})
            return models
        except Exception as exc:
            logger.warning({"event": "list_models_codex_token_failed", "error": str(exc)})
            continue

    return models


def _fetch_chatgpt_token_models() -> set[str]:
    """Fetch models from all ChatGPT tokens, compute intersection."""
    active_tokens: list[str] = []
    with account_service._lock:
        for token, account in account_service._accounts.items():
            if not token or token == "public":
                continue
            status = str(account.get("status") or "")
            if status in {"disabled", "error"}:
                continue
            if str(account.get("type") or "") == "codex" and token.startswith("eyJ"):
                continue
            active_tokens.append(token)

    if not active_tokens:
        # Fallback: anon
        try:
            result = OpenAIBackendAPI().list_models()
            models = set()
            for item in result.get("data", []):
                if isinstance(item, dict) and item.get("id"):
                    models.add(f"chatgpt/{str(item['id'])}")
            logger.info({"event": "list_models_chatgpt_anon", "count": len(models)})
            return models
        except Exception as exc:
            logger.warning({"event": "list_models_anon_failed", "error": str(exc)})
            return set()

    # Parallel fetch from all tokens
    token_sets: list[set[str]] = []
    with ThreadPoolExecutor(max_workers=min(8, len(active_tokens))) as executor:
        futures = {
            executor.submit(_fetch_models_for_token, token): token
            for token in active_tokens
        }
        for future in as_completed(futures):
            _, model_set = future.result()
            if model_set is not None:
                token_sets.append(model_set)

    if not token_sets:
        return set()

    # Intersection — add chatgpt/ prefix
    common = {f"chatgpt/{m}" for m in token_sets[0]}
    for s in token_sets[1:]:
        prefixed = {f"chatgpt/{m}" for m in s}
        common &= prefixed

    logger.info({
        "event": "list_models_chatgpt_intersection",
        "total_tokens": len(active_tokens),
        "successful": len(token_sets),
        "common_count": len(common),
    })
    return common


def _fetch_models_for_token(token: str) -> tuple[str, set[str] | None]:
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


def _apply_fallback(provider: str) -> set[str]:
    """Get fallback models for a provider when API fetch fails."""
    return set(FALLBACK_MODELS.get(provider, []))


# ── Persistent model cache (disk) ──
import os as _os
_CACHE_FILE = DATA_DIR / "models_cache.json"
_models_cache: dict[str, Any] | None = None
_cache_config_hash: str = ""
_cache_loaded_at: float = 0.0
# Auto-refresh cadence. The web-scraped catalogues (gmw/*) and the
# Codex / OpenAI live lists can change between deploys without any config
# edit on our side, so the cache deliberately expires even when the config
# hash is stable. 24h is the same cadence Google / OpenAI use for their
# own publicly-cached metadata.
_CACHE_TTL_SECONDS = 24 * 3600


def _load_cache_from_disk() -> dict[str, Any] | None:
    """Load cached model list from disk. Returns None if not found or corrupted."""
    try:
        if _CACHE_FILE.exists():
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "data" in data:
                # Verify cache consistency: combo_models in cache should match config
                cache_combos = set()
                for m in data.get("data", []):
                    mid = str(m.get("id") or "")
                    # Check if this is a combo model (owned_by == "chatgpt2api" and in combos)
                    if m.get("owned_by") == "chatgpt2api":
                        cache_combos.add(mid)
                current_combos = set((config.data.get("combo_models") or {}).keys())
                current_combos |= set((config.data.get("pipeline_models") or {}).keys())
                if cache_combos != current_combos:
                    logger.info({"event": "models_cache_stale_combos", "cache": list(cache_combos), "config": list(current_combos)})
                    return None
                logger.info({"event": "models_cache_disk_loaded", "count": len(data.get("data", []))})
                return data
    except Exception:
        pass
    return None


def _save_cache_to_disk(data: dict[str, Any]):
    """Persist model list to disk."""
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning({"event": "models_cache_save_error", "error": str(exc)})


def _config_hash() -> str:
    import hashlib, json as _json
    raw = _json.dumps({
        "cp": config.data.get("custom_providers") or {},
        "ms": config.data.get("model_settings") or {},
    }, sort_keys=True, default=str)
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()


def invalidate_models_cache():
    """Clear cache when config changes. Call from API endpoints after save."""
    global _models_cache, _cache_config_hash
    _models_cache = None
    _cache_config_hash = ""
    try:
        if _CACHE_FILE.exists():
            _CACHE_FILE.unlink()
    except Exception:
        pass


_DYNAMIC_PREFIXES = ("gmw/", "claude/", "gma/")

# Provider phải CÓ tài khoản (account-pool) hoặc API key thì model mới hiện.
# Model prefix → nhóm account cần kiểm.
_POOL_PREFIX_GROUP = {
    "cgf": "free", "free": "free", "chatgpt": "free",
    "cx": "codex", "codex": "codex", "paid": "codex",
    "oai": "openai",
    "claude": "claude", "cc": "claude", "clf": "claude", "cl": "claude",
    "gma": "gemini_web_api", "gemini-web": "gemini_web_api",
    "gmw": "gemini_web",
}
# Model prefix → provider config cần có api_key/key.
_KEY_PREFIX_PROVIDER = {
    "gemini_free": "gemini_free", "gemini-image": "gemini_free",
    "nv": "nvidia_nim", "nv-image": "nvidia_nim", "openrouter": "openrouter",
    # flow/* (veo-3.1-*, omni-flash) cần providers.flow.accounts — trước đây
    # thiếu entry này nên model video Flow VẪN hiện dù chưa thêm tài khoản nào,
    # user chọn xong mới báo lỗi ("chưa thêm provider mà lại hiện các model").
    "flow": "flow",
}


def _drop_unavailable(data: list[dict]) -> list[dict]:
    """Ẩn model của provider KHÔNG có tài khoản (account-pool, status != disabled)
    hoặc KHÔNG có API key. Provider free (oc/…), combo, image-config, custom (đã
    gate sẵn bởi fetcher) → giữ. Fail-open: lỗi đọc account → giữ nguyên."""
    try:
        accs = account_service.list_accounts()
    except Exception:
        return data
    cfg = config.data.get("providers") or {}

    def _tok_expired(tok: str) -> bool:
        try:
            from services.account_service import _decode_jwt_payload
            exp = (_decode_jwt_payload(tok) or {}).get("exp")
            return bool(exp) and float(exp) < time.time()
        except Exception:
            return False

    def _pool_ok(group: str) -> bool:
        _WEB = ("claude", "gemini_web_api", "gemini_web", "chatgpt_web")
        for a in accs:
            if account_group(a) != group:
                continue
            st = str(a.get("status"))
            if group in _WEB:
                # web-session: dùng session từ solver, status 'error' vẫn có thể chạy;
                # chỉ 'disabled' mới coi là tắt hẳn.
                if st != "disabled":
                    return True
            else:
                # token-based (free/codex/openai): loại disabled/error/limited; free &
                # openai KHÔNG tự refresh nên JWT hết hạn = không dùng được.
                if st in ("disabled", "error", "limited"):
                    continue
                if group in ("free", "openai") and _tok_expired(str(a.get("access_token") or "")):
                    continue
                return True
        # web-session: account có thể bị sync sang group khác (vd google-* vừa là
        # gemini_web_api), nhưng provider vẫn dùng được nếu config có PROFILE (reuse
        # Google qua solver). Coi là CÓ tài khoản → hiện model.
        if group in _WEB:
            c = cfg.get(group) or {}
            if c.get("profiles") or c.get("accounts") or c.get("profile") or c.get("psid"):
                return True
        return False

    def _key_ok(prov: str) -> bool:
        c = cfg.get(prov) or {}
        return bool(c.get("api_key") or c.get("api_keys") or c.get("psid")
                    or c.get("profiles") or c.get("accounts"))

    avail: dict[str, bool] = {}
    out: list[dict] = []
    for m in data:
        pfx = str(m.get("id") or "").split("/", 1)[0]
        if pfx in _POOL_PREFIX_GROUP:
            g = _POOL_PREFIX_GROUP[pfx]
            if g not in avail:
                avail[g] = _pool_ok(g)
            keep = avail[g]
        elif pfx in _KEY_PREFIX_PROVIDER:
            p = _KEY_PREFIX_PROVIDER[pfx]
            k = "k:" + p
            if k not in avail:
                avail[k] = _key_ok(p)
            keep = avail[k]
        else:
            keep = True  # oc/free, combo, image, custom → giữ
        if keep:
            out.append(m)
    return out


def _curate_models(data: list[dict]) -> list[dict]:
    """Tab quản lý model — dọn nhóm Codex OAuth:
      - BỎ mọi model tiền tố `codex/`.
      - BỎ cx/* cũ hơn 5.3 (giữ cx/auto = Model chính luôn hiện).
    Giữ nguyên biến thể ':text' của các model được giữ. Provider khác không đụng."""
    import re as _re
    out: list[dict] = []
    for m in data:
        base = str(m.get("id") or "").split(":")[0]  # bỏ ':text' khi xét
        if base.startswith("codex/"):
            continue
        if base.startswith("cx/"):
            slug = base[3:]
            if slug != "auto":
                mt = _re.search(r"gpt-(\d+(?:\.\d+)?)", slug)
                ver = float(mt.group(1)) if mt else 0.0
                if ver < 5.3:
                    continue
        out.append(m)
    return out


def _apply_enabled_filter(data: list[dict]) -> list[dict]:
    """Filter model list by model_settings.enabled_models. Used for HA /v1/models.

    Models whose IDs start with one of the dynamic web-provider prefixes
    (`gmw/`) bypass the filter entirely — the captcha-solver
    discovers their slugs at runtime so the user has no way to add them
    to `enabled_models` ahead of time, and the prefix already implies
    the source. Static providers (chatgpt/, cx/, gemini_free/, ...)
    still go through the enabled filter as before.
    """
    model_settings = config.data.get("model_settings") or {}
    if not isinstance(model_settings, dict):
        return data
    enabled_by_provider = model_settings.get("enabled_models") or {}
    if not isinstance(enabled_by_provider, dict) or not enabled_by_provider:
        return data

    all_enabled: set[str] = set()
    for provider_models in enabled_by_provider.values():
        if isinstance(provider_models, list):
            for m in provider_models:
                if isinstance(m, str) and m.strip():
                    all_enabled.add(m.strip())

    always_allow = {
        "cx/auto", "oc/auto",
        "cgf/auto", "paid/auto", "oai/auto",
        "gemini_free/auto", "ag/auto",
        "gmw/auto", "gmw/vision",
    }
    all_enabled |= always_allow

    combos = config.data.get("combo_models") or {}
    if isinstance(combos, dict):
        all_enabled |= set(combos.keys())

    # Combo Code (pipeline bố-con) — config key riêng, tách biệt combo thường
    pipelines = config.data.get("pipeline_models") or {}
    if isinstance(pipelines, dict):
        all_enabled |= set(pipelines.keys())

    all_enabled |= set(IMAGE_MODELS)

    from services.providers.custom_openai import get_custom_providers, CustomOpenAIProvider
    custom_providers = get_custom_providers()
    for cp_id, cp_cfg in custom_providers.items():
        try:
            provider = CustomOpenAIProvider(cp_cfg)
            for m in provider.list_models():
                mid = str(m.get("id") or "").strip()
                if mid:
                    all_enabled.add(mid)
        except Exception:
            pass

    import re as _re
    before = len(data)
    filtered = []
    for item in data:
        mid = str(item.get("id") or "").strip()
        # Biến thể ':text'/':tts' qua filter nếu MODEL GỐC được bật.
        base = _re.sub(r"[:#](tts|voice|vanxuoi|raw|text|chat|kytu|symbol)\b", "",
                       mid, flags=_re.IGNORECASE)
        # NOTE: dynamic-prefix models (gmw/ claude/ gma/) used to bypass the
        # filter — that made external apps show ALL of them regardless of the
        # Models-tab toggles. Now they go through the same enabled check, so the
        # list = enabled models + /auto (always_allow) + combos + pipelines.
        if base in all_enabled or mid in all_enabled:
            filtered.append(item)
    logger.info({"event": "list_models_filtered", "before": before, "after": len(filtered)})
    return filtered


def list_models(force_refresh: bool = False, apply_filter: bool = False) -> dict[str, Any]:
    """Return available models — cached to disk. apply_filter=True for HA /v1/models.
    Cache always stores UNFILTERED data; filter is applied at read time so the UI
    (which needs all models for toggle UI) and HA (which needs only enabled) share
    the same cache without one polluting the other."""
    global _models_cache, _cache_config_hash, _cache_loaded_at

    # Load from disk on first access
    if _models_cache is None:
        _models_cache = _load_cache_from_disk()
        _cache_config_hash = _config_hash()
        if _models_cache is not None:
            _cache_loaded_at = time.time()

    current_hash = _config_hash()
    config_changed = _cache_config_hash != current_hash
    cache_stale = (time.time() - _cache_loaded_at) > _CACHE_TTL_SECONDS

    # Use cache if: loaded, not forced, config stable, AND inside TTL.
    if _models_cache is not None and not force_refresh and not config_changed and not cache_stale:
        logger.info({"event": "list_models_cache_hit"})
        cached = _merge_runtime_gma_models(
            list((_models_cache or {}).get("data") or []))
        cdata = _curate_models(_drop_unavailable(cached))
        if apply_filter:
            cdata = _apply_enabled_filter(cdata)
        return {"object": "list", "data": cdata}

    if force_refresh:
        logger.info({"event": "list_models_manual_refresh"})
    elif config_changed:
        logger.info({"event": "list_models_config_changed"})
    else:
        logger.info({"event": "list_models_first_load"})

    data: list[dict[str, Any]] = []

    # Fetch from all built-in providers in parallel
    provider_fetchers = {
        # NOTE: the dynamic "chatgpt" group is intentionally NOT listed here.
        # ChatGPT free is exposed ONLY under the unified cgf/ group (built from
        # the hardcoded cgf_models list below, owned_by "ChatGPT_free"). The
        # free pool / chatgpt.com transport is unchanged — this only controls
        # what /v1/models advertises so the UI shows a single ChatGPT_free group.
        "openai_oauth": _fetch_codex_models,
        "gemini_free": _fetch_gemini_models,
        "opencode": _fetch_opencode_models,
        "openrouter": _fetch_openrouter_models,
        "nvidia_nim": _fetch_nvidia_models,
        "gemini_web": _fetch_gemini_web_models,
        "gemini_web_api": _fetch_gemini_web_api_models,
        "tokenrouter": _fetch_tokenrouter_models,
    }

    # Add custom providers dynamically
    from services.providers.custom_openai import get_custom_providers, CustomOpenAIProvider
    custom_providers = get_custom_providers()
    for cp_id, cp_cfg in custom_providers.items():
        def make_fetcher(cfg=cp_cfg):
            provider = CustomOpenAIProvider(cfg)
            def fetcher():
                models = set()
                for m in provider.list_models():
                    mid = str(m.get("id") or "").strip()
                    if mid:
                        models.add(mid)
                if models:
                    logger.info({"event": "list_models_custom", "provider": provider.name, "count": len(models)})
                return models
            return fetcher
        provider_fetchers[f"custom:{cp_id}"] = make_fetcher()

    all_models: dict[str, set[str]] = {}
    with ThreadPoolExecutor(max_workers=len(provider_fetchers)) as executor:
        futures = {
            executor.submit(fetcher): name
            for name, fetcher in provider_fetchers.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                models = future.result()
                if models:
                    all_models[name] = models
            except Exception as exc:
                logger.warning({"event": "list_models_provider_failed", "provider": name, "error": str(exc)})

    # Build seen set to avoid duplicates
    seen: set[str] = set()

    # Add dynamically fetched models
    for provider_name, models in sorted(all_models.items()):
        for model_id in sorted(models):
            if model_id not in seen:
                seen.add(model_id)
                data.append({
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": provider_name,
                })

    # Alias do ta định nghĩa: ghép LUÔN, không phụ thuộc lấy động thành công.
    for provider_name, alias_list in ALIAS_MODELS.items():
        for model_id in alias_list:
            if model_id not in seen:
                seen.add(model_id)
                data.append({
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": provider_name,
                })

    # Apply fallbacks for providers that returned nothing
    for provider_name in ["opencode", "gemini_free", "openai_oauth", "nvidia_nim", "tokenrouter", "chatgpt2api", "antigravity", "gemini_web"]:
        if provider_name not in all_models:
            for model_id in sorted(_apply_fallback(provider_name)):
                if model_id not in seen:
                    seen.add(model_id)
                    data.append({
                        "id": model_id,
                        "object": "model",
                        "created": 0,
                        "owned_by": provider_name,
                    })

    # Unified ChatGPT_free provider — ONE group under prefix cgf/. Merges the
    # old chatgpt/* and free/* lists (same module, same free pool) into one.
    # free/, chatgpt/, chatgpt/free/ still ROUTE as hidden aliases
    # (backend_router) so HA / n8n / saved combos keep working — not listed.
    #  - paid/auto → plus/go/business unified under Codex (also cx/ , codex/)
    #  - oai/auto  → raw OpenAI API (sk-/standard)
    cgf_models = ["cgf/auto",
                  # GPT-5 family (full chatgpt.com web line-up)
                  "cgf/gpt-5", "cgf/gpt-5-1", "cgf/gpt-5-2", "cgf/gpt-5-3",
                  "cgf/gpt-5-3-mini", "cgf/gpt-5-4-t-mini", "cgf/gpt-5-5",
                  "cgf/gpt-5-5-instant", "cgf/gpt-5-5-thinking", 
                  "cgf/gpt-5-4-thinking", "cgf/gpt-5-3-instant", "cgf/o3",
                  "cgf/gpt-5-mini", "cgf/research",
                  # legacy 4o / 4.1 / o-series
                  "cgf/gpt-4o", "cgf/gpt-4o-mini", "cgf/gpt-4.1-mini",
                  "cgf/gpt-4.1-nano", "cgf/o3-mini", "cgf/o4-mini"]
    for mid in cgf_models:
        if mid not in seen:
            seen.add(mid)
            data.append({"id": mid, "object": "model", "created": 0, "owned_by": "ChatGPT_free"})
    # Paid (Codex) + OpenAI-API entry points.
    for mid, owner in [("paid/auto", "openai_oauth"), ("oai/auto", "openai_api")]:
        if mid not in seen:
            seen.add(mid)
            data.append({"id": mid, "object": "model", "created": 0, "owned_by": owner})

    # Add image models — group by their natural prefix so the UI shows
    # them under their own provider section (e.g. flow/* under "Google
    # Labs Flow", gemini-image/* under Gemini) instead of all dumped into
    # the generic "chatgpt2api" combo bucket.
    def _model_owner(mid: str) -> str:
        # Dedicated "Image ChatGPT" card for the ChatGPT image models
        # (shared free+codex) so they don't hide inside the generic
        # "Hệ thống (combo)" bucket.
        if mid in ("gpt-image-2", "gpt-5-5-image"):
            return "image_chatgpt"
        if "/" in mid:
            prefix = mid.split("/", 1)[0]
            if prefix.startswith("gemini-image"):
                return "gemini_free"
            # Consolidate gma image (gma/image) under the gemini_web_api
            # provider so it groups with the gma chat models instead of a
            # separate "gma" bucket.
            if prefix == "gma":
                return "gemini_web_api"
            return prefix
        return "chatgpt2api"

    for model in sorted(IMAGE_MODELS):
        if model not in seen:
            seen.add(model)
            data.append({
                "id": model, "object": "model", "created": 0,
                "owned_by": _model_owner(model), "permission": [],
                "root": model, "parent": None,
            })

    # Add Flow video generation models
    from utils.helper import VIDEO_GEN_MODELS
    for model in sorted(VIDEO_GEN_MODELS):
        if model not in seen:
            seen.add(model)
            data.append({
                "id": model, "object": "model", "created": 0,
                "owned_by": "flow", "permission": [],
                "root": model, "parent": None,
            })

    # Add combo models from config
    combos = config.data.get("combo_models") or {}
    if isinstance(combos, dict):
        for combo_name in combos:
            if combo_name not in seen:
                seen.add(combo_name)
                data.append({
                    "id": combo_name, "object": "model", "created": 0,
                    "owned_by": "chatgpt2api",
                })

    # Add Combo Code (pipeline bố-con) from config — owned_by "chatgpt2api"
    # để khớp logic verify cache phía trên
    pipelines = config.data.get("pipeline_models") or {}
    if isinstance(pipelines, dict):
        for pipeline_name in pipelines:
            if pipeline_name not in seen:
                seen.add(pipeline_name)
                data.append({
                    "id": pipeline_name, "object": "model", "created": 0,
                    "owned_by": "chatgpt2api",
                })

    # Add image provider models from config
    providers = config.data.get("providers") or {}
    if isinstance(providers, dict):
        for provider_name, provider_cfg in providers.items():
            if isinstance(provider_cfg, dict) and provider_cfg.get("enabled"):
                provider_id = f"{provider_name}/auto"
                if provider_id not in seen and provider_name not in ("gemini_free", "openrouter", "serper", "searxng", "brave", "gemini_web", "claude"):
                    seen.add(provider_id)
                    data.append({
                        "id": provider_id, "object": "model", "created": 0,
                        "owned_by": provider_name,
                    })

    # Always inject Claude models to the global registry so they appear in UI
    # `sonnet-5` CÓ trong CLAUDE_MODEL_ALIASES và CÓ trong /v1/claude/models,
    # nhưng thiếu ở đây — hai danh sách lệch nhau, nên model chạy được mà không
    # chọn được từ giao diện chính. Đặt đầu danh sách vì đây là bản Sonnet mới nhất.
    claude_models = ["claude/auto"]
    for b in ["sonnet-5", "fable-5", "opus-4.8", "sonnet-4.6", "haiku-4.5",
              "opus-4.7", "opus-4.6", "opus-3"]:
        for e in ["", "-low", "-medium", "-high", "-max"]:
            for t in ["", "-thinking"]:
                claude_models.append(f"claude/{b}{e}{t}")
    for mid in claude_models:
        if mid not in seen:
            seen.add(mid)
            data.append({"id": mid, "object": "model", "created": 0, "owned_by": "claude"})

    # Gemini web-cookie API models
    # 3.5-* đã có trong _GMA_ALIASES của api/gemini_web.py (nên gọi thẳng vẫn
    # chạy — đo thật 08/08: gma/3.5-flash trả OK, adapter gọi BASIC_FLASH) nhưng
    # chưa từng được LIỆT KÊ ở đây, nên không chọn được trong giao diện và không
    # đưa vào enabled_models được.
    gma_models = ["gma/auto", "gma/image",
                  "gma/3.5-flash", "gma/3.5-flash-mo-rong",
                  "gma/3.1-flash", "gma/3.1-flash-thu-nghiem",
                  "gma/3.1-pro", "gma/3.1-pro-mo-rong",
                  "gma/3.1-flash-lite"]
    for mid in gma_models:
        if mid not in seen:
            seen.add(mid)
            data.append({"id": mid, "object": "model", "created": 0, "owned_by": "gemini_web_api"})

    # Biến thể ':text' cho MỌI model CHAT — chọn trong HA cho pipeline GÕ CHỮ để GIỮ
    # KÝ TỰ (không văn xuôi TTS). Model thường = mặc định (HA giọng nói → văn
    # xuôi). Gateway tự cắt ':text' khi dispatch nên vẫn route đúng provider.
    # KHÔNG tạo :text cho combo/pipeline và BỎ QUA MỌI model ẢNH/VIDEO (image, video, clip, ...).
    from utils.helper import VIDEO_GEN_MODELS
    _combo_ids = set((config.data.get("combo_models") or {}).keys()) | \
                 set((config.data.get("pipeline_models") or {}).keys())
    for _m in list(data):
        _mid = _m.get("id")
        if _mid and ":" not in _mid and "#" not in _mid:
            # Bỏ qua combo/pipeline
            if _mid in _combo_ids:
                continue

            # BỎ QUA model ẢNH / VIDEO (không tạo biến thể :text)
            _mid_lower = str(_mid).lower()
            _is_img_or_video = (
                (_mid in IMAGE_MODELS)
                or (_mid in VIDEO_GEN_MODELS)
                or _mid_lower.startswith(("flow/", "gemini-image/", "nv-image/", "codex-gpt-image", "gpt-image-", "dall-e-"))
                or any(k in _mid_lower for k in ("image", "video", "clip", "imagen", "flux", "schnell", "sdwebui", "dall-e"))
            )
            if _is_img_or_video:
                continue

            _tv = dict(_m)
            _tv["id"] = f"{_mid}:text"
            _tv["owned_by"] = f"{_m.get('owned_by') or 'chatgpt'}_text"
            data.append(_tv)

    # Sắp xếp toàn bộ danh sách model theo id A-Z (không phân biệt hoa/thường)
    # để /v1/models trả về thứ tự ổn định, dễ đọc.
    data.sort(key=lambda m: str(m.get("id") or "").lower())

    logger.info({"event": "list_models_done", "total_models": len(data)})
    # Save to persistent disk cache (always UNFILTERED — apply_filter is applied at read time)
    result = {"object": "list", "data": data}
    _models_cache = result
    _cache_config_hash = current_hash
    _cache_loaded_at = time.time()
    _save_cache_to_disk(result)
    logger.info({"event": "list_models_cached_to_disk", "total": len(data)})

    fdata = _curate_models(_drop_unavailable(list(data)))
    if apply_filter:
        fdata = _apply_enabled_filter(fdata)
    return {"object": "list", "data": fdata}
