"""
BackendRouter — route requests to the appropriate AI backend.

Port pattern from 9router getProviderCredentials() + combo model routing:
- Model prefix determines provider: oc/ → OpenCode, gmw/ → Gemini Web, etc.
- Payload > 100KB (FREE_PAYLOAD_LIMIT) → ưu tiên provider không giới hạn (opencode, gemini, openrouter)
- Payload ≤ 100KB → dùng ChatGPT free
- Image models stay on ChatGPT DALL-E path
- Combo models fallback qua nhiều provider
"""

from __future__ import annotations

import json
import re
from typing import Any

from services.config import config
from utils.helper import IMAGE_MODELS, VIDEO_GEN_MODELS


def la_model_video(provider: str, model: str) -> bool:
    """True khi `model` là model TẠO VIDEO của `provider`.

    Provider `flow` giữ cả model ảnh lẫn model video trong cùng một không gian
    tên, nên chỉ nhìn tiền tố `flow/` là không phân biệt được. `VIDEO_GEN_MODELS`
    trong `utils/helper.py` là danh sách đã có sẵn cho đúng việc này.
    """
    m = str(model or "").strip()
    if not m:
        return False
    day_du = m if "/" in m else f"{provider}/{m}"
    return day_du in VIDEO_GEN_MODELS

# Internal output-format markers appended to combo steps (cx/auto:text, .../auto:tts…).
# They pick voice-vs-text phrasing (decided once at top level) and are NOT real
# model names, so strip them before routing a combo step to its provider.
_COMBO_MARKER_RE = re.compile(r"[:#](tts|voice|vanxuoi|raw|text|chat|kytu|symbol)\b", re.IGNORECASE)

# Provider prefixes ported from 9router src/shared/constants/providers.js
PROVIDER_PREFIXES: dict[str, str] = {
    "9r/": "ninerouter",
    "cgf/": "chatgpt_free",   # CANONICAL ChatGPT_free prefix (chatgpt.com web, free pool)
    "free/": "chatgpt_free",   # alias of cgf/
    "chatgpt/codex/": "openai_oauth",  # legacy alias — keep BEFORE chatgpt/
    "chatgpt/free/": "chatgpt_free",   # legacy alias — keep BEFORE chatgpt/
    "chatgpt/": "chatgpt_free",   # legacy alias → unified free module
    "cgw/": "chatgpt_web",        # chatgpt web provider (captcha solver)
    "paid/": "openai_oauth",   # plus/go/business — unified under Codex OAuth
    "cx/": "openai_oauth",
    "codex/": "openai_oauth",
    "oai/": "openai_api",      # raw sk- key / standard JWT → api.openai.com
    "openai_api/": "openai_api",
    "oc/": "opencode",
    "ocg/": "opencode_go",
    "sc/": "supercode",       # supercode-cli backend — CHỈ text/code, KHÔNG ảnh
    "gemini_free/": "gemini_free",
    "gemini/": "gemini_free",
    "pw/": "perplexity_web",
    "gmw/": "gemini_web",     # gemini.google.com via captcha-solver DOM scrape
    "gc/": "gemini_cli",
    "kr/": "kiro",
    "qw/": "qwen",
    "if/": "iflow",
    "gh/": "github",
    "cu/": "cursor",
    "cc/": "claude",
    "claude/": "claude",  # claude.ai free (sessionKey) — same backend as /v1/claude/*
    "clf/": "claude",     # alias of claude/
    "gma/": "gemini_web_api",         # gemini.google.com qua cookie 1PSID (gemini_webapi)
    "gemini-web/": "gemini_web_api",  # alias of gma/
    "nv/": "nvidia_nim",
    "ag/": "antigravity",
    "agnes/": "agnes",
    # TokenRouter đường RIÊNG (services/providers/tokenrouter.py). Tiền tố
    # `tokenrouter/` của mục trong custom_providers KHÔNG đổi — vẫn đi đường
    # Custom Providers dùng chung như trước. Hai đường sống song song.
    "tr/": "tokenrouter",
}

# NoAuth providers — no credentials needed (port from 9router FREE_PROVIDERS)
NO_AUTH_PROVIDERS: set[str] = {"opencode"}

# Providers that accept API key (not OAuth)
API_KEY_PROVIDERS: set[str] = {
    "gemini_free",
    "openrouter",
    "deepseek",
    "groq",
    "xai",
    "mistral",
    "perplexity",
    "together",
    "nvidia_nim",
    "agnes",
    "tokenrouter",
}

# Image providers from 9router image adapter system
IMAGE_PROVIDER_PREFIXES: dict[str, str] = {
    "sdwebui/": "sdwebui",
    "comfyui/": "comfyui",
    "huggingface/": "huggingface",
    "fal-ai/": "fal_ai",
    "stability/": "stability_ai",
    "bfl/": "black_forest_labs",
    "cloudflare/": "cloudflare_ai",
    "recraft/": "recraft",
    "runwayml/": "runwayml",
    "nv-image/": "nvidia_nim_image",
    "gemini-image/": "gemini",
    "flow/": "flow",
    "agnes-image/": "agnes",
    "agnes-video/": "agnes",
}


class BackendRoute:
    """Result of routing decision."""
    def __init__(
        self,
        provider: str,
        model: str,
        no_auth: bool = False,
        api_key: str = "",
        base_url: str = "",
        is_image: bool = False,
        fallback_providers: list[str] | None = None,
    ):
        self.provider = provider
        self.model = model
        self.no_auth = no_auth
        self.api_key = api_key
        self.base_url = base_url
        self.is_image = is_image
        self.fallback_providers = fallback_providers or []


class BackendRouter:
    """
    Route request đến backend phù hợp nhất:
    - Payload > 100KB (FREE_PAYLOAD_LIMIT) → ưu tiên provider không giới hạn (opencode, gemini, openrouter)
    - Payload ≤ 100KB → có thể dùng ChatGPT free
    - Model có prefix oc/ → OpenCode, gmw/ → Gemini Web, v.v.
    - Combo model → fallback qua nhiều provider
    """

    # Payload threshold for free ChatGPT accounts. Raised 24KB → 80KB
    # (2026-05) and again → 100KB (2026-05-25). chatgpt.com/backend-api
    # tolerates payloads close to its 100KB hard limit; we stay at the
    # cap and rely on RTK compression in conversation.py for spill-over.
    FREE_PAYLOAD_LIMIT = 100_000

    # Default model per provider (for "auto" resolution)
    PROVIDER_DEFAULT_MODELS: dict[str, str] = {
        "ninerouter": "auto",
        "openai_oauth": "gpt-5.3-codex",
        "opencode": "nemotron-3-super-free",
        "chatgpt": "auto",
        "chatgpt_free": "auto",
        "gemini_free": "gemini-3-flash-preview",
        "openrouter": "openai/gpt-4o",
        "nvidia_nim": "openai/gpt-oss-120b",
        "antigravity": "gemini-3.1-pro-high",
    }

    @staticmethod
    def resolve_model(model_str: str) -> tuple[str, str]:
        """Parse model string → (provider, model_name).

        Examples:
            "gpt-4" → ("chatgpt", "gpt-4")
            "oc/nemotron-free" → ("opencode", "nemotron-free")
            "sdwebui/sd-v1.5" → ("sdwebui", "sd-v1.5")
            "huggingface/black-forest-labs/FLUX.1-schnell" → ("huggingface", "black-forest-labs/FLUX.1-schnell")
        """
        model_str = str(model_str or "").strip()

        # Check image provider prefixes first
        for prefix, provider in IMAGE_PROVIDER_PREFIXES.items():
            if model_str.startswith(prefix):
                return (provider, model_str[len(prefix):])
            if model_str == prefix.rstrip("/"):
                return (provider, "auto")

        # Check chat provider prefixes
        for prefix, provider in PROVIDER_PREFIXES.items():
            if model_str.startswith(prefix):
                return (provider, model_str[len(prefix):])
            if model_str == prefix.rstrip("/"):
                return (provider, "auto")

        # Check custom providers (dynamic, configured via UI)
        from services.providers.custom_openai import resolve_custom_provider
        custom_cfg, custom_rest = resolve_custom_provider(model_str)
        if custom_cfg is not None:
            provider_id = str(custom_cfg.get("prefix") or "")
            return (f"custom:{provider_id}", custom_rest)

        # Default: use ChatGPT
        return ("chatgpt", model_str)

    @staticmethod
    def is_image_model(model_str: str) -> bool:
        """Check if model is an image generation model."""
        model_str = str(model_str or "").strip()
        if model_str in IMAGE_MODELS:
            return True
        for prefix in IMAGE_PROVIDER_PREFIXES:
            if model_str.startswith(prefix) or model_str == prefix.rstrip("/"):
                return True
        return False

    @staticmethod
    def get_payload_size(messages: list[dict[str, Any]]) -> int:
        """Calculate JSON payload size in bytes."""
        try:
            payload = json.dumps(messages, ensure_ascii=False, default=str)
            return len(payload.encode("utf-8"))
        except Exception:
            return 0

    @staticmethod
    def _get_enabled_models(provider: str) -> list[str] | None:
        """Return list of enabled model IDs for a provider, or None if no filter."""
        ms = config.data.get("model_settings") or {}
        if not isinstance(ms, dict):
            return None
        enabled = ms.get("enabled_models") or {}
        if not isinstance(enabled, dict) or not enabled:
            return None
        provider_enabled = enabled.get(provider)
        if not provider_enabled:
            return None  # No filter for this provider
        return [m for m in provider_enabled if isinstance(m, str) and m.strip()]

    def route(
        self,
        model: str,
        messages: list[dict[str, Any]] | None = None,
        payload_size: int | None = None,
    ) -> BackendRoute:
        """Determine the best backend for a request.

        Args:
            model: Model string from request
            messages: Normalized messages (for payload size calculation)
            payload_size: Pre-calculated payload size in bytes (optional)

        Returns:
            BackendRoute with provider, model, auth info
        """
        provider, resolved_model = self.resolve_model(model)
        is_image = self.is_image_model(model)

        # Resolve "auto" to provider's default model (check user config first)
        if resolved_model == "auto" or not resolved_model:
            # Nguồn model mặc định: tab QUẢN LÝ MODEL (`default_models`).
            #
            # Đó là nơi duy nhất nên đặt model cho chat/vision/HA/ảnh. Trường
            # `providers.<tên>.model` chỉ còn để đọc CẤU HÌNH CŨ — giữ lại để
            # bản đang chạy không đổi hành vi sau khi cập nhật, nhưng không có
            # giao diện nào ghi vào nó nữa.
            #
            # Trước đây hai chỗ cùng nói về "model mặc định" nên chúng lệch
            # nhau được, và bước lọc `enabled_models` bên dưới lặng lẽ đè lên
            # cái ở Cài đặt.
            ms = config.data.get("model_settings") or {}
            mac_dinh = str(((ms.get("default_models") or {}).get(provider) or "")).strip()
            # Một yêu cầu ẢNH không bao giờ được giải ra model VIDEO.
            #
            # Provider `flow` giữ cả hai loại trong cùng một không gian tên: ba
            # model ảnh (banana-pro, banana-2, banana-2-lite) và bốn model video
            # (omni-flash, veo-3.1-*). Tab Quản lý Model gom chúng thành MỘT thẻ
            # với MỘT ô mặc định, nên đặt nhầm một tên veo vào đó là đường ảnh
            # lấy luôn tên đó. Nó không dừng ở đấy: `flow_google._resolve_model`
            # không biết alias veo nên trả về chính chuỗi viết hoa
            # ("VEO-3.1-FAST") rồi gửi thẳng cho Flow làm `imageModelName`.
            #
            # Đường video KHÔNG đi qua đây (`api/veo_video.py` nhận tên nguyên
            # văn), nên lọc ở đây không cắt mất đường nào của video.
            if mac_dinh.startswith(f"{provider}/"):
                mac_dinh = mac_dinh[len(provider) + 1:]
            if is_image and mac_dinh and la_model_video(provider, mac_dinh):
                from utils.log import logger as _lg
                _lg.warning({
                    "event": "mac_dinh_anh_la_model_video",
                    "provider": provider,
                    "bi_bo": mac_dinh,
                    "msg": "Model mặc định của provider này là model VIDEO — bỏ "
                           "qua cho yêu cầu ảnh. Đặt lại bằng một model ảnh.",
                })
                mac_dinh = ""
            provider_cfg = (config.data.get("providers") or {}).get(provider) or {}
            user_model = mac_dinh or str(provider_cfg.get("model") or "").strip()
            resolved_model = user_model or self.PROVIDER_DEFAULT_MODELS.get(provider, "auto")

            # Filter to enabled models only (model_settings)
            enabled = self._get_enabled_models(provider)
            if enabled:
                # Skip auto placeholders, strip provider prefix for matching
                real_models = []
                for m in enabled:
                    m = m.strip()
                    # Rủi ro thật không nằm ở ô mặc định mà ở các ô TICK: bỏ tick
                    # hết model ảnh của Flow và chỉ giữ veo thì `flow/auto` rơi
                    # xuống `real_models[0]` — một tên video — mà không ai chạm
                    # vào ô mặc định lần nào.
                    if is_image and la_model_video(provider, m):
                        continue
                    if m in ("auto", f"{provider}/auto"):
                        continue
                    if m.startswith(f"{provider}/"):
                        m = m[len(provider) + 1:]
                    if m:
                        real_models.append(m)
                if real_models and (resolved_model == "auto" or resolved_model not in real_models):
                    # `enabled_models` (tab Quản lý Model) ĐÈ LÊN
                    # `providers.<tên>.model` (ô "Model mặc định" ở Cài đặt).
                    #
                    # Hai chỗ cùng nói về "model mặc định của provider" nên
                    # chúng lệch nhau được: bỏ tick đúng model đang đặt làm mặc
                    # định thì hệ thống lặng lẽ chuyển sang model đầu danh sách.
                    # Không ai thấy gì, chỉ thấy "sao nó trả lời bằng model
                    # khác". Ghi log để lần sau tra ra được trong một phút.
                    if resolved_model != "auto" and resolved_model not in real_models:
                        from utils.log import logger as _lg
                        _lg.warning({
                            "event": "model_mac_dinh_bi_de",
                            "provider": provider,
                            "cau_hinh": resolved_model,
                            "dung_thay": real_models[0],
                            "msg": "Model mặc định ở Cài đặt KHÔNG có trong danh "
                                   "sách đã tick ở Quản lý Model — dùng model đầu "
                                   "danh sách. Tick nó, hoặc đổi model mặc định.",
                        })
                    resolved_model = real_models[0]  # First real enabled model

        # Calculate payload size if not provided
        if payload_size is None and messages:
            payload_size = self.get_payload_size(messages)

        # Image models always use their configured provider
        if is_image:
            if provider == "chatgpt":
                # ChatGPT DALL-E — existing path
                return BackendRoute(
                    provider="chatgpt",
                    model=model,
                    is_image=True,
                )
            else:
                # External image provider (sdwebui, huggingface, etc.)
                return BackendRoute(
                    provider=provider,
                    model=resolved_model,
                    no_auth=provider in NO_AUTH_PROVIDERS,
                    is_image=True,
                )

        # Text chat routing
        if provider in ("chatgpt", "chatgpt_free"):
            # If payload is large and we have free providers, suggest fallback
            if payload_size and payload_size > self.FREE_PAYLOAD_LIMIT:
                # Don't redirect if active accounts exist (OpenAI API handles large payloads)
                from services.account_service import account_service as _acct2
                has_active = any(
                    a.get("status") == "active"
                    for a in _acct2._accounts.values()
                )
                if not has_active:
                    opencode_config = (config.data.get("providers") or {}).get("opencode") or {}
                    if opencode_config.get("enabled", True):
                        return BackendRoute(
                            provider="opencode",
                            model=model if model != "auto" else "auto",
                            no_auth=True,
                            fallback_providers=[provider],
                        )

            # Use ChatGPT as normal
            return BackendRoute(
                provider=provider,
                model=model,
            )

        # Non-ChatGPT provider (opencode, gemini_free, etc.)
        provider_config = (config.data.get("providers") or {}).get(provider) or {}
        return BackendRoute(
            provider=provider,
            model=resolved_model or model,
            no_auth=provider in NO_AUTH_PROVIDERS,
            api_key=str(provider_config.get("api_key") or ""),
            base_url=str(provider_config.get("base_url") or ""),
            fallback_providers=["chatgpt"],
        )

    @staticmethod
    def _provider_da_mat(model_str: str, provider: str) -> bool:
        """Thành viên combo trỏ tới provider KHÔNG còn tồn tại?

        Dấu hiệu chắc chắn: chuỗi có tiền tố dạng `x/…` nhưng `resolve_model` lại
        rơi về provider mặc định "chatgpt". Nghĩa là `x/` từng là tiền tố của một
        provider (built-in hoặc Custom Provider) mà giờ không phân giải được nữa —
        thường vì mục Custom Provider đã bị xoá. Để nguyên thì mỗi lượt chat vẫn
        gửi một tên model vô nghĩa sang ChatGPT rồi mới rơi xuống thành viên sau.

        KHÔNG áp cho chuỗi không có '/' (vd 'gpt-image-2') — đó là model ChatGPT
        thật, đi đúng đường mặc định.
        """
        if provider != "chatgpt":
            return False
        tho = str(model_str or "").strip()
        pfx, sep, _ = tho.partition("/")
        if not sep or not pfx:
            return False
        # 'chatgpt/…' phân giải ra provider chatgpt_free nên không tới đây; còn
        # tiền tố nào rơi về đây thật thì đúng là đã mất provider.
        return True

    @staticmethod
    def _het_credential(model_id: str) -> bool:
        """Provider của model này còn tài khoản / API key không?

        Dùng LẠI đúng luật của tab Quản lý model (`_drop_unavailable`) thay vì
        viết định nghĩa thứ hai cho "provider còn sống" — hai định nghĩa lệch nhau
        là kiểu sai lệch âm thầm khó thấy nhất.
        """
        try:
            from services.protocol.openai_v1_models import _drop_unavailable
            return not _drop_unavailable([{"id": model_id}])
        except Exception:
            return False        # fail-open: không đọc được thì cứ giữ

    def _loc_thanh_vien_song(self, models: list[str], combo_name: str = "") -> list[str]:
        """Bỏ thành viên combo đã mất provider hoặc hết credential.

        Lọc sạch hết thì trả NGUYÊN danh sách gốc — combo không còn đường nào để
        thử còn tệ hơn thử một đường đã chết.
        """
        song: list[str] = []
        bo: list[str] = []
        for model_str in models:
            clean = _COMBO_MARKER_RE.sub("", str(model_str)).strip()
            if not clean:
                continue
            provider, resolved = self.resolve_model(clean)
            if self._provider_da_mat(clean, provider) or self._het_credential(clean):
                bo.append(clean)
                continue
            song.append(str(model_str))
        if not song:
            return list(models)
        if bo:
            from utils.log import logger
            logger.info({"event": "combo_bo_thanh_vien_chet", "combo": combo_name,
                         "bo": bo[:8], "con_lai": len(song)})
        return song

    def route_combo(self, combo_name: str) -> list[BackendRoute]:
        """Resolve a combo model into its fallback chain (case-insensitive).

        Thành viên nào mất provider (Custom Provider đã xoá) hoặc provider hết
        tài khoản/API key thì BỎ khỏi chuỗi — thêm provider mới vào là nó tự có
        mặt, xoá provider là nó tự rút, không phải sửa lại combo bằng tay.
        Lọc sạch hết thì GIỮ NGUYÊN danh sách gốc: thà thử và hỏng còn hơn không
        còn đường nào để thử.
        """
        models = self._get_combo_models(combo_name)
        if not models:
            return []
        models = self._loc_thanh_vien_song(models, combo_name)

        routes: list[BackendRoute] = []
        for model_str in models:
            # Strip internal formatting markers (:text/:tts/#raw…) from each combo
            # step BEFORE routing. They control voice-vs-text output (decided once
            # at the top level) and are NOT real model names — leaving them on
            # made Codex reject "auto:text" (400: model not supported), forcing an
            # avoidable fall-through to the free tier on every request.
            clean = _COMBO_MARKER_RE.sub("", str(model_str)).strip()
            route = self.route(clean)
            routes.append(route)

        return routes

    def is_combo(self, model_str: str) -> bool:
        """Check if a model string is a combo name (case-insensitive)."""
        combos = config.data.get("combo_models") or {}
        if not isinstance(combos, dict):
            return False
        model_lower = model_str.lower().strip()
        return any(k.lower().strip() == model_lower for k in combos)

    def get_pipeline(self, name: str) -> dict[str, list[str]] | None:
        """Combo Code (pipeline bố-con) — TÁCH BIỆT hoàn toàn với combo_models.

        Config key riêng `pipeline_models`:
            {"code": {"architects": ["claude/auto"], "editors": ["cgf/auto", ...]}}
        Trả {"architects": [...], "editors": [...]} hoặc None (case-insensitive).
        """
        pipelines = config.data.get("pipeline_models") or {}
        if not isinstance(pipelines, dict):
            return None
        name_lower = str(name or "").lower().strip()
        for k, v in pipelines.items():
            if k.lower().strip() != name_lower or not isinstance(v, dict):
                continue
            architects = [str(m).strip() for m in (v.get("architects") or []) if str(m).strip()]
            editors = [str(m).strip() for m in (v.get("editors") or []) if str(m).strip()]
            if architects and editors:
                return {"architects": architects, "editors": editors}
        return None

    def is_pipeline(self, name: str) -> bool:
        return self.get_pipeline(name) is not None

    def _get_combo_models(self, combo_name: str) -> list[str] | None:
        """Get combo model list by name (case-insensitive)."""
        combos = config.data.get("combo_models") or {}
        if not isinstance(combos, dict):
            return None
        name_lower = combo_name.lower().strip()
        for k, v in combos.items():
            if k.lower().strip() == name_lower and isinstance(v, list):
                return v
        return None


# Singleton
backend_router = BackendRouter()
