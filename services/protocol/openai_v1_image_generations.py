from __future__ import annotations

import base64
import json
import time
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
from services.config import config
from services.image_providers import get_image_adapter, is_noauth_image_provider
from services.image_providers._base import now_sec
from services.request_context import note_provider_account
from utils.log import logger


def _nhan_khoa(credentials: dict[str, Any] | None, key_try: int) -> str:
    """Tên gọi được của KHOÁ API đang dùng, để nhật ký chỉ ra đúng cái nào.

    Chỉ lấy 4 ký tự cuối. Đủ để đối chiếu với danh sách khoá trong cấu hình khi
    một khoá bị chặn, mà không ghi bí mật vào nhật ký.
    """
    c = credentials or {}
    ds = [str(k) for k in (c.get("apiKeys") or []) if k] or \
         ([str(c.get("apiKey"))] if c.get("apiKey") else [])
    if not ds:
        return ""
    k = ds[key_try % len(ds)]
    duoi = k[-4:] if len(k) >= 4 else "?"
    return f"khoá #{key_try % len(ds) + 1}/{len(ds)} (…{duoi})"


def _khai_tai_khoan(route: Any, credentials: dict[str, Any] | None,
                    key_try: int) -> None:
    """Ghi provider + model + khoá đang dùng vào ngữ cảnh yêu cầu.

    KHÔNG ghi đè khi adapter đã tự khai một tài khoản có tên thật: Flow gọi
    `note_provider_account` ngay trong `build_headers` với nhãn hồ sơ ("Main",
    "Spare 2") — thông tin đó giá trị hơn "khoá #1" nên phải để nguyên.
    """
    try:
        from services.request_context import get_dest, note_provider_account
        cu = get_dest() or {}
        if str(cu.get("provider") or "") == str(route.provider) and cu.get("account"):
            return
        note_provider_account(route.provider, _nhan_khoa(credentials, key_try),
                              model=route.model)
    except Exception:
        pass


def _handle_adapter_image(route, body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    """Handle image generation through an adapter (sdwebui, huggingface, etc.)."""
    adapter = get_image_adapter(route.provider)
    if not adapter:
        # Custom providers don't have image adapters — raise to trigger combo fallback
        raise RuntimeError(f"Provider '{route.provider}' does not support image generation")

    # Per-call structured log for the Logs UI. Mirrors web_proxy._log_web_call
    # so flow / gemini_web rows appear in the same image-gen
    # bucket regardless of which code path executes them.
    _img_log_started_at = time.time()
    _img_log_provider = route.provider
    _img_log_profile = ""
    try:
        _img_providers_cfg = config.data.get("providers") or {}
        _img_log_profile = str((_img_providers_cfg.get(_img_log_provider) or {}).get("profile") or "")
    except Exception:
        pass

    prompt = str(body.get("prompt") or "")
    body = {**body, "prompt": prompt}
    n = max(1, min(4, int(body.get("n") or 1)))
    response_format = str(body.get("response_format") or "b64_json")
    base_url_str = str(body.get("base_url") or "") or None
    stream = bool(body.get("stream"))

    # Build credentials from config
    provider_key = route.provider
    providers_cfg = config.data.get("providers") or {}
    provider_config = providers_cfg.get(provider_key) or {}
    # Map image adapter key → chat provider key for credentials
    if not provider_config and provider_key == "gemini":
        provider_config = providers_cfg.get("gemini_free") or {}
    elif not provider_config and provider_key == "nvidia_nim_image":
        provider_config = providers_cfg.get("nvidia_nim") or {}

    credentials = {}
    if route.no_auth:
        credentials = {"accessToken": "public"}
    else:
        credentials = {
            "apiKey": str(provider_config.get("api_key") or ""),
            "apiKeys": provider_config.get("api_keys") or [],
            "accessToken": str(provider_config.get("api_key") or ""),
        }

    # For sdwebui, use configured base_url; pre-set img2img flag because
    # build_url() runs before build_body() in the loop below.
    if route.provider == "sdwebui":
        adapter.base_url = str(provider_config.get("base_url") or "http://localhost:7860").rstrip("/")
        try:
            from services.image_providers._base import first_image_bytes_mime
            _raw, _ = first_image_bytes_mime(body.get("images") or [])
            adapter._use_img2img = bool(_raw)
        except Exception:
            adapter._use_img2img = False

    # Generate n images
    all_data: list[dict[str, Any]] = []
    stream_outputs: list[ImageOutput] = []
    # Get key count for retry
    max_keys = getattr(adapter, 'get_key_count', lambda c: 1)(credentials)

    for idx in range(n):
        last_error = ""
        for key_try in range(max(max_keys, 1)):
            try:
                # Try with key_index for adapters that support key rotation
                try:
                    url = adapter.build_url(route.model, credentials, key_try)
                except TypeError:
                    url = adapter.build_url(route.model, credentials)
                req_body = adapter.build_body(route.model, body)
                headers = adapter.build_headers(credentials, req_body, route.model, body)

                logger.info({
                    "event": "image_adapter_request",
                    "provider": route.provider,
                    "model": route.model,
                    "url": url[:120],
                    "key_try": key_try,
                })
                # Khai lại cho TỪNG lần thử khoá. Lượt đầu đã khai ở
                # `_handle_single_image`, nhưng khai một lần là chỉ biết khoá
                # ĐẦU TIÊN: khi khoá 1 bị 429 và khoá 3 mới chạy được, nhật ký
                # vẫn chỉ ra khoá 1 — đúng lúc cần biết khoá nào còn sống thì
                # nó nói sai. Đo 10/08/2026: cột tài khoản trống với mọi nhà
                # dùng khoá API (NVIDIA, Agnes…) vì chỉ Flow tự khai tên hồ sơ.
                _khai_tai_khoan(route, credentials, key_try)

                resp = cffi_requests.post(
                    url,
                    headers=headers,
                    json=req_body,
                    timeout=300,
                )

                if resp.status_code >= 400:
                    error_text = ""
                    try:
                        error_text = resp.text[:500]
                    except Exception:
                        pass
                    # Health-based rotation: let the adapter demote a dead
                    # account (e.g. Flow logged-out profile) to the back of
                    # its pool so the next request skips it.
                    if hasattr(adapter, "on_key_failed"):
                        try:
                            adapter.on_key_failed(credentials, resp.status_code, error_text)
                        except Exception:
                            pass
                    if resp.status_code in (400, 429) and key_try < max_keys - 1:
                        logger.warning({
                            "event": "image_adapter_retry",
                            "provider": route.provider,
                            "status": resp.status_code,
                            "key_try": key_try,
                            "error": error_text[:200],
                        })
                        last_error = error_text
                        continue  # try next key
                    logger.error({
                        "event": "image_adapter_error",
                        "provider": route.provider,
                        "status": resp.status_code,
                        "error": error_text,
                    })
                    raise RuntimeError(f"Image generation failed: {route.provider} status={resp.status_code} detail={error_text[:300]}")

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

                # Health-based rotation: promote the account that just worked
                # to the front of its pool (mirrors ChatGPT's promote_account).
                if data_items and hasattr(adapter, "on_key_success"):
                    try:
                        adapter.on_key_success(credentials)
                    except Exception:
                        pass

                if stream:
                    stream_outputs.append(ImageOutput(
                        kind="result",
                        model=body.get("model", "unknown"),
                        index=idx + 1,
                        total=n,
                        data=data_items,
                    ))
                break  # success — stop trying keys

            except Exception as exc:
                logger.error({"event": "image_adapter_fatal", "provider": route.provider, "error": str(exc)})
                if key_try < max_keys - 1:
                    continue  # try next key
                # Structured log entry — surfaces in the Logs UI under
                # web_image bucket alongside gemini_web.
                try:
                    from services.log_service import LOG_TYPE_WEB_IMAGE, log_service
                    log_service.add(LOG_TYPE_WEB_IMAGE,
                                     f"{_img_log_provider}/image_gen FAIL {int((time.time() - _img_log_started_at) * 1000)}ms",
                                     {
                                         "provider": _img_log_provider,
                                         "profile": _img_log_profile,
                                         "op": "image_gen",
                                         "duration_ms": int((time.time() - _img_log_started_at) * 1000),
                                         "prompt_len": len(prompt),
                                         "ok": False,
                                         "error": str(exc)[:300],
                                         "model": route.model,
                                     })
                except Exception:
                    pass
                # Lỗi ném ở trên đã có sẵn tiền tố này (dòng `status=... detail=...`),
                # bọc thêm lần nữa ra "Image generation failed: Image generation
                # failed: gemini status=429 …" — người đọc log tưởng hai lỗi khác nhau.
                loi = str(exc)
                raise RuntimeError(
                    loi if loi.startswith("Image generation failed:")
                    else f"Image generation failed: {loi}"
                ) from exc

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
    # Success log — only when at least one image came back so partial-fail
    # paths still record the failure above.
    if result.get("data"):
        try:
            from services.log_service import LOG_TYPE_WEB_IMAGE, log_service
            log_service.add(LOG_TYPE_WEB_IMAGE,
                             f"{_img_log_provider}/image_gen OK {int((time.time() - _img_log_started_at) * 1000)}ms",
                             {
                                 "provider": _img_log_provider,
                                 "profile": _img_log_profile,
                                 "op": "image_gen",
                                 "duration_ms": int((time.time() - _img_log_started_at) * 1000),
                                 "prompt_len": len(prompt),
                                 "ok": True,
                                 "got": len(result.get("data") or []),
                                 "model": route.model,
                             })
        except Exception:
            pass
    return result


def handle(body: dict[str, Any]) -> dict[str, Any] | Iterator[dict[str, Any]]:
    prompt = str(body.get("prompt") or "")
    model = str(body.get("model") or "gpt-image-2")
    n = int(body.get("n") or 1)
    size = body.get("size") or config.default_image_size  # configurable default (16:9)
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
    # Ghi NGAY model thật vào ngữ cảnh yêu cầu, TRƯỚC khi gọi adapter.
    #
    # Combo "AI image" gồm tám model chênh nhau rất xa về chất lượng, và khi
    # model đầu bận thì nó lặng lẽ tụt xuống model sau. Nhật ký chỉ có tên combo
    # (`log_service` lấy `dest_model or self.model`, mà `self.model` chính là
    # "AI image"), nên ảnh ra mờ hay sai khung hình là không cách nào truy được
    # model nào đã dựng. Từ đây mọi lượt đều có ít nhất provider + model thật.
    #
    # Provider nào biết TÀI KHOẢN cụ thể (Flow) vẫn gọi lại `note_provider_account`
    # bên trong adapter; `set_dest` ghi đè nên bản đầy đủ hơn thắng, còn cả hai
    # đều được giữ trong `dest_trail`.
    note_provider_account(route.provider, model=route.model)

    prompt = str(body.get("prompt") or "")
    model = str(body.get("model") or "gpt-image-2")
    n = int(body.get("n") or 1)
    size = body.get("size") or config.default_image_size  # configurable default (16:9)
    response_format = str(body.get("response_format") or "b64_json")
    base_url_str = str(body.get("base_url") or "") or None
    stream = bool(body.get("stream"))

    # Core providers have their own built-in implementation below.
    # Non-core image models (custom or image-specific prefixes) use adapters.
    if route.provider == "agnes" or "agnes" in route.provider.lower() or "agnes" in model.lower():
        from services.providers.agnes import agnes_provider
        # Agnes nhận `image` là MẢNG (tài liệu 31/07) — đừng cắt còn một tấm;
        # sửa-ảnh-nhiều-tấm (ghép, tham chiếu) cần đủ danh sách.
        src_image = body.get("image") or body.get("images")
        if src_image is not None and not isinstance(src_image, list):
            src_image = [src_image]
        # `size` kiểu OpenAI ("1792x1024") → suy TỈ LỆ cho đời 2.1 (khoá `ratio`).
        # Không suy thì mọi ảnh dọc người dùng chọn vẫn ra khung 16:9 mặc định.
        ratio = body.get("ratio") or body.get("aspect_ratio") or ""
        if not ratio:
            try:
                w_s, h_s = str(size).lower().split("x")
                w_i, h_i = int(w_s), int(h_s)
                muc = (("1:1", 1.0), ("4:3", 4 / 3), ("3:2", 3 / 2), ("16:9", 16 / 9),
                       ("21:9", 21 / 9), ("3:4", 3 / 4), ("2:3", 2 / 3), ("9:16", 9 / 16))
                ti = w_i / h_i if h_i else 1.0
                ratio = min(muc, key=lambda m: abs(m[1] - ti))[0]
            except Exception:
                ratio = "16:9"
        return agnes_provider.generate_image(
            prompt=prompt,
            model=model,
            n=n,
            size=size,
            aspect_ratio=ratio,
            image=src_image,
        )

    core_providers = {"chatgpt", "chatgpt_free", "openai_oauth", "gemini_web", "gemini_web_api"}
    if route.provider not in core_providers and (route.is_image or route.provider.startswith("custom:")):
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

    # Web-scrape providers: gemini_web (Imagen)
    if route.provider == "gemini_web":
        logger.info({
            "event": "image_routed_to_web",
            "provider": route.provider,
            "n": n,
        })
        from services.providers.web_proxy import handle_gemini_web_image_gen
        return handle_gemini_web_image_gen(prompt, n=n, response_format=response_format,
                                           base_url=base_url_str or "")
        
    # HTTP API providers: gemini_web_api
    if route.provider == "gemini_web_api":
        logger.info({
            "event": "image_routed_to_gma",
            "provider": route.provider,
            "n": n,
        })
        from api.gemini_web import handle_gemini_web_api_image_gen
        return handle_gemini_web_api_image_gen(prompt, n=n, response_format=response_format, base_url=base_url_str)

    # For chatgpt/ DALL-E: use original chatgpt.com backend flow (same as upstream)
    # Let combo fallback handle failures if token can't access chatgpt.com
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
