from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from api.support import require_admin, require_identity, resolve_image_base_url
from services.backup_service import BackupError, backup_service
from services.config import config
from services.image_service import delete_images, download_images_zip, get_image_download_response, get_thumbnail_response, list_images
from services.image_tags_service import delete_tag, get_all_tags, set_tags
from services.log_service import log_service
from services.proxy_service import test_proxy
from services.state_backup import state_backup
from services.backend_router import backend_router
from services.model_cooldown import model_cooldown
from services.providers.opencode import opencode_provider
from services.rate_limit_backoff import rate_limit_backoff
from services.quota_watcher import quota_watcher
from services.ninerouter_backup_import import import_9router_backup_from_api
from services.oauth_service import get_codex_auth_url, exchange_codex_code, get_chatgpt_session_url, detect_token_type


def _provider_circuit_stats() -> dict:
    """Trạng thái circuit-breaker per provider (smart pool) — best-effort."""
    try:
        from services.provider_circuit import provider_circuit
        return provider_circuit.get_stats()
    except Exception:
        return {}


def _session_affinity_stats() -> dict:
    """Số phiên sticky đang giữ (smart pool) — best-effort."""
    try:
        from services.session_affinity import session_affinity
        return session_affinity.get_stats()
    except Exception:
        return {}


def _check_gemini_status() -> dict:
    """Check Gemini API and ALL custom provider instances (all ports)."""
    import requests as req

    result = {
        "gemini_api": "unknown",
        "models_count": 0,
        "instances": [],  # list of all provider instances with per-key status
    }

    # Check Gemini API with ALL keys individually
    provider_config = (config.data.get("providers") or {}).get("gemini_free") or {}
    gemini_single_key = str(provider_config.get("api_key") or "").strip()
    gemini_multi_keys = provider_config.get("api_keys") or []
    if not isinstance(gemini_multi_keys, list):
        gemini_multi_keys = []
    gemini_all_keys = [k.strip() for k in gemini_multi_keys if k.strip()]
    if gemini_single_key and gemini_single_key not in gemini_all_keys:
        gemini_all_keys.insert(0, gemini_single_key)

    gemini_key_statuses = []
    gemini_available = 0
    total_models = 0

    for key in gemini_all_keys:
        ks = {"key_preview": key[:12] + "..." + key[-4:] if len(key) > 20 else key, "status": "unknown", "error": None, "models": 0}
        try:
            resp = req.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                timeout=10
            )
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                ks["status"] = "available"
                ks["models"] = len(models)
                gemini_available += 1
                total_models = max(total_models, len(models))
            elif resp.status_code == 429:
                ks["status"] = "rate_limited"
                ks["error"] = "Rate limit exceeded — too many requests"
            elif resp.status_code in (401, 403):
                ks["status"] = "auth_error"
                ks["error"] = f"HTTP {resp.status_code} — API key invalid"
            else:
                ks["status"] = f"error_{resp.status_code}"
                try:
                    ks["error"] = resp.json().get("error", {}).get("message", str(resp.status_code))
                except Exception:
                    ks["error"] = str(resp.status_code)
        except Exception as e:
            ks["status"] = "network_error"
            ks["error"] = str(e)[:80]
        gemini_key_statuses.append(ks)

    # Overall Gemini status
    if gemini_available == len(gemini_all_keys) and len(gemini_all_keys) > 0:
        result["gemini_api"] = "available"
    elif gemini_available > 0:
        result["gemini_api"] = "partial"
    elif any(k["status"] == "rate_limited" for k in gemini_key_statuses):
        result["gemini_api"] = "rate_limited"
    elif any(k["status"] == "auth_error" for k in gemini_key_statuses):
        result["gemini_api"] = "auth_error"
    elif gemini_all_keys:
        result["gemini_api"] = gemini_key_statuses[0]["status"]
    else:
        result["gemini_api"] = "no_key"
    result["models_count"] = total_models

    # Add Gemini as an instance with per-key details
    if gemini_all_keys:
        result["instances"].append({
            "id": "gemini_free",
            "name": "Gemini API",
            "prefix": "gemini_free",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "status": result["gemini_api"],
            "port": "443",
            "models": total_models,
            "clients": 0,
            "entries": 0,
            "total_keys": len(gemini_all_keys),
            "available_keys": gemini_available,
            "keys": gemini_key_statuses,
            "error": next((k["error"] for k in gemini_key_statuses if k["status"] != "available" and k["error"]), None),
        })

    # Check ALL custom providers (all ports/instances) with per-key status
    custom_providers = config.data.get("custom_providers") or {}
    for cp_id, cp_cfg in custom_providers.items():
        if not isinstance(cp_cfg, dict) or not cp_cfg.get("enabled", True):
            continue
        base_url = cp_cfg.get("base_url") or ""
        name = cp_cfg.get("name") or cp_id
        prefix = cp_cfg.get("prefix") or cp_id

        # Multi-endpoint support — a provider can pool several base_urls
        # (e.g. 4 Gemini Custom instances on different ports sharing one
        # API key). We surface each as a numbered endpoint so the UI can
        # render the rotation order with #1..#N pills.
        base_urls_extra = cp_cfg.get("base_urls") if isinstance(cp_cfg.get("base_urls"), list) else []
        all_urls_ordered: list[str] = []
        if base_url:
            all_urls_ordered.append(base_url.rstrip("/"))
        for u in base_urls_extra:
            u = str(u or "").strip().rstrip("/")
            if u and u not in all_urls_ordered:
                all_urls_ordered.append(u)
        endpoints_payload = [
            {"ordinal": i + 1, "url": u, "is_primary": i == 0}
            for i, u in enumerate(all_urls_ordered)
        ]

        # Collect all API keys (single + multi)
        single_key = str(cp_cfg.get("api_key") or "").strip()
        multi_keys = cp_cfg.get("api_keys") or []
        if not isinstance(multi_keys, list):
            multi_keys = []
        all_keys = [k.strip() for k in multi_keys if k.strip()]
        if single_key and single_key not in all_keys:
            all_keys.insert(0, single_key)

        # Auto-detect API style and paths
        is_no_v1 = "deepseek.com" in base_url or "perplexity.ai" in base_url
        base_has_v1 = base_url.rstrip("/").endswith("/v1")
        if is_no_v1:
            models_path = "/models" if "deepseek.com" in base_url else "/v1/models"
            chat_path = "/chat/completions" if "deepseek.com" in base_url else "/v1/chat/completions"
        elif base_has_v1:
            models_path = "/models"
            chat_path = "/chat/completions"
        else:
            models_path = "/v1/models"
            chat_path = "/v1/chat/completions"

        # Check each key's status
        key_statuses = []
        available_keys = 0
        for key in all_keys:
            key_status = {"key_preview": key[:12] + "..." + key[-4:] if len(key) > 20 else key, "status": "unknown", "error": None}
            try:
                resp = req.get(f"{base_url}{models_path}", headers={"Authorization": f"Bearer {key}"}, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    models_list = data.get("data") or data.get("models") or []
                    key_status["status"] = "available"
                    key_status["models"] = len(models_list)
                    available_keys += 1
                elif resp.status_code == 401 or resp.status_code == 403:
                    key_status["status"] = "auth_error"
                    key_status["error"] = f"HTTP {resp.status_code} — API key invalid"
                elif resp.status_code == 429:
                    key_status["status"] = "rate_limited"
                    key_status["error"] = "Rate limited"
                elif resp.status_code >= 500:
                    key_status["status"] = "server_error"
                    key_status["error"] = f"HTTP {resp.status_code}"
                else:
                    key_status["status"] = f"http_{resp.status_code}"
                    key_status["error"] = f"HTTP {resp.status_code}"
            except Exception as e:
                key_status["status"] = "network_error"
                key_status["error"] = str(e)[:80]
            key_statuses.append(key_status)

        # Determine overall status
        if available_keys == len(all_keys) and len(all_keys) > 0:
            overall_status = "available"
        elif available_keys > 0:
            overall_status = "partial"
        elif any(k["status"] == "auth_error" for k in key_statuses):
            overall_status = "auth_error"
        elif any(k["status"] == "network_error" for k in key_statuses):
            overall_status = "network_error"
        else:
            overall_status = key_statuses[0]["status"] if key_statuses else "no_keys"

        # Also check /health for geminiapi-style providers
        clients = 0
        entries = 0
        if not is_no_v1:
            try:
                resp = req.get(f"{base_url}/health", timeout=4)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        clients = len(data.get("clients") or {})
                        entries = data.get("storage", {}).get("entries", 0)
            except Exception:
                pass

        instance = {
            "id": cp_id,
            "name": name,
            "prefix": prefix,
            "base_url": base_url,
            "base_urls": [u for u in all_urls_ordered if u != base_url],
            "endpoints": endpoints_payload,
            "endpoint_count": len(endpoints_payload),
            "status": overall_status,
            "port": base_url.split(":")[-1].rstrip("/") if ":" in base_url else "—",
            "models": sum(k.get("models", 0) for k in key_statuses),
            "clients": clients,
            "entries": entries,
            "total_keys": len(all_keys),
            "available_keys": available_keys,
            "keys": key_statuses,
            "error": None,
        }
        # Set primary error from first failing key
        for k in key_statuses:
            if k["status"] != "available" and k["error"]:
                instance["error"] = k["error"]
                break

        result["instances"].append(instance)

    return result


def _is_model_enabled(model_id: str, enabled_by_provider: dict) -> bool:
    """Check if a model is in the enabled list. If no providers configured, all models are enabled.

    Biến thể ':text'/':tts' KẾ THỪA trạng thái enabled của model GỐC (vd
    'cx/auto:text' bật iff 'cx/auto' bật) — nhờ vậy UI (combo/pipeline picker
    lọc enabled) hiện được các biến thể giữ-ký-tự."""
    if not enabled_by_provider:
        return True
    import re
    model_id = re.sub(r"[:#](tts|voice|vanxuoi|raw|text|chat|kytu|symbol)\b", "",
                      model_id, flags=re.IGNORECASE).strip()
    from utils.helper import IMAGE_MODELS, VIDEO_GEN_MODELS
    # Core models + image/video models always enabled
    if model_id in {"cx/auto", "oc/auto", "chatgpt/auto", "gemini_free/auto", "gpt-image-2", "codex-gpt-image-2"}:
        return True
    if model_id in IMAGE_MODELS or model_id in VIDEO_GEN_MODELS:
        return True
    for provider_models in enabled_by_provider.values():
        if isinstance(provider_models, list) and model_id in provider_models:
            return True
    return False


def _create_backup(passphrase: str = "") -> dict:
    """Create local full-state backup (passphrase → mã hóa Fernet)."""
    payload = state_backup.export_all()
    filepath = state_backup.save_to_file(payload, passphrase=passphrase or None)
    return {
        "status": "ok",
        "path": str(filepath),
        "size_bytes": filepath.stat().st_size,
        "created_at": payload["created_at"],
    }


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProfileNameRequest(BaseModel):
    name: str = ""


class ProxyTestRequest(BaseModel):
    url: str = ""


class ImageDeleteRequest(BaseModel):
    paths: list[str] = []
    start_date: str = ""
    end_date: str = ""
    all_matching: bool = False

class ImageDownloadRequest(BaseModel):
    paths: list[str]

class ImageTagsRequest(BaseModel):
    path: str
    tags: list[str]

class LogDeleteRequest(BaseModel):
    ids: list[str] = []
class BackupDeleteRequest(BaseModel):
    key: str = ""

class Import9RouterRequest(BaseModel):
    path: str = ""

class RestoreRequest(BaseModel):
    path: str = ""
    passphrase: str = ""  # bắt buộc nếu file backup được mã hóa


class BackupCreateRequest(BaseModel):
    passphrase: str = ""  # có giá trị → mã hóa file backup bằng Fernet


class CodexExchangeRequest(BaseModel):
    redirect_url: str = ""


class AntigravityExchangeRequest(BaseModel):
    redirect_url: str = ""


def create_router(app_version: str) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/login")
    async def login(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        # Brute-force guard: rate-limit + temporary lockout per client IP.
        from services import login_guard
        ip = login_guard.client_ip_from_request(request)
        login_guard.check_allowed(ip)
        try:
            identity = require_identity(authorization)
        except HTTPException as exc:
            if exc.status_code == 401:
                login_guard.record_failure(ip)
            raise
        login_guard.record_success(ip)
        return {
            "ok": True,
            "version": app_version,
            "role": identity.get("role"),
            "subject_id": identity.get("id"),
            "name": identity.get("name"),
        }

    @router.post("/api/v1/profile/name")
    async def update_profile_name(body: ProfileNameRequest, authorization: str | None = Header(default=None)):
        """Đổi tên hiển thị của người dùng đang đăng nhập (admin mặc định hoặc khóa)."""
        identity = require_identity(authorization)
        new_name = (body.name or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail={"error": "名字不能为空"})
        if len(new_name) > 40:
            raise HTTPException(status_code=400, detail={"error": "名字最长40个字符"})
        if identity.get("id") == "admin":
            config.update({"admin_name": new_name})
        else:
            from services.auth_service import auth_service
            try:
                updated = auth_service.update_key(
                    str(identity.get("id")), {"name": new_name}, role=identity.get("role"),
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
            if updated is None:
                raise HTTPException(status_code=404, detail={"error": "找不到这个密钥"})
        return {"ok": True, "name": new_name}

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/api/settings")
    async def get_settings(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"config": config.get()}

    @router.get("/api/privacy/status")
    async def privacy_status(authorization: str | None = Header(default=None)):
        """P0–P2 privacy gate status (MK/PII không đẩy vào AI)."""
        require_admin(authorization)
        from services.privacy_gate import privacy_public_status
        return {"ok": True, "privacy": privacy_public_status()}

    @router.post("/api/settings")
    async def save_settings(body: SettingsUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        # exclude_unset: only apply fields the client actually sent — avoids
        # wiping multi-key providers when a partial settings body is posted.
        _changed = body.model_dump(mode="python", exclude_unset=True)
        result = config.update(_changed)
        # If tunnel token changed, restart tunnel
        if "cloudflare_tunnel_token" in _changed:
            try:
                from services.cloudflare_tunnel import restart_tunnel
                restart_tunnel()
            except Exception:
                pass
        # If telegram token changed, re-register webhook
        if any(k in _changed for k in ("telegram_bot_token", "telegram_bots", "telegram_webhook_url")):
            try:
                from services.telegram_bot import register_webhook
                register_webhook()
            except Exception:
                pass
        # Zalo dùng chung telegram_webhook_url (cloudflare) → đổi token Zalo hoặc
        # đổi URL cloudflare đều phải đăng ký lại webhook Zalo.
        if any(k in _changed for k in ("zalo_bot_token", "zalo_bots", "zalo_webhook_secret", "telegram_webhook_url")):
            try:
                from services.zalo_bot import register_webhook as _z_reg
                _z_reg()
            except Exception:
                pass
        # Zalo Cá Nhân (bot server zca-js) — đổi server/user/pass/webhook base
        # thì reset client + tự đăng ký lại webhook về gateway.
        if any(k.startswith("zalo_personal_") for k in _changed):
            try:
                from services.zalo_personal import on_settings_changed as _zp_changed
                _zp_changed()
            except Exception:
                pass
        return {"config": result}

    # ── Cloudflare Tunnel ──
    @router.get("/api/tunnel/status")
    async def tunnel_status(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.cloudflare_tunnel import get_status
        return get_status()

    @router.post("/api/tunnel/restart")
    async def tunnel_restart(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.cloudflare_tunnel import restart_tunnel
        return {"ok": restart_tunnel()}

    # ── Telegram ──
    @router.get("/api/telegram/status")
    async def telegram_status(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.telegram_bot import get_status
        return get_status()

    @router.post("/telegram/webhook")
    async def telegram_webhook(request: Request):
        """Public endpoint for Telegram to send messages to."""
        from services.telegram_bot import handle_webhook
        return await handle_webhook(request)

    # ── Zalo (chung tab + cloudflare với Telegram) ──
    @router.get("/api/zalo/status")
    async def zalo_status(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.zalo_bot import get_status
        return get_status()

    @router.get("/api/bot-names")
    async def bot_names(authorization: str | None = Header(default=None)):
        """Tên bot theo bot_id (getMe, cache trong RAM) — UI Settings hiển thị
        TÊN bot thay mã số trong danh sách bot + dropdown lọc theo thread."""
        require_admin(authorization)
        out: dict[str, dict[str, str]] = {"telegram": {}, "zalo": {}}
        try:
            from services.zalo_bot import get_bot_names as _zalo_names
            out["zalo"] = _zalo_names()
        except Exception:
            pass
        try:
            from services.telegram_bot import get_bot_names as _tg_names
            out["telegram"] = _tg_names()
        except Exception:
            pass
        return out

    @router.post("/api/telegram/resolve-chat")
    async def telegram_resolve_chat(request: Request, authorization: str | None = Header(default=None)):
        """getChat — lấy title + type (private/group) cho admin thread UI.

        Body: {token, chat_id}. Heuristic kind nếu API lỗi (bot chưa từng thấy chat).
        """
        require_admin(authorization)
        try:
            body = await request.json()
        except Exception:
            body = {}
        token = str((body or {}).get("token") or "").strip()
        chat_id = str((body or {}).get("chat_id") or "").strip()
        from services.admin_workspace import guess_chat_kind
        kind = guess_chat_kind(chat_id)
        name = ""
        ok = False
        if token and chat_id:
            try:
                from services.telegram import get_client
                r = get_client(token).get_chat(chat_id)
                if r.get("ok") and isinstance(r.get("result"), dict):
                    res = r["result"]
                    ok = True
                    ctype = str(res.get("type") or "")
                    if ctype in {"group", "supergroup", "channel"}:
                        kind = "group"
                    elif ctype == "private":
                        kind = "private"
                    name = (
                        str(res.get("title") or "").strip()
                        or " ".join(
                            x for x in (
                                str(res.get("first_name") or "").strip(),
                                str(res.get("last_name") or "").strip(),
                            ) if x
                        ).strip()
                        or str(res.get("username") or "").strip()
                    )
            except Exception:
                pass
        return {"ok": ok, "chat_id": chat_id, "name": name, "kind": kind}

    @router.post("/api/zalo/resolve-chat")
    async def zalo_resolve_chat(request: Request, authorization: str | None = Header(default=None)):
        """Zalo Bot Platform getChat — tên + private/group cho admin UI.

        Body: {token, chat_id}. Heuristic kind nếu API chưa từng thấy chat.
        """
        require_admin(authorization)
        try:
            body = await request.json()
        except Exception:
            body = {}
        token = str((body or {}).get("token") or "").strip()
        chat_id = str((body or {}).get("chat_id") or "").strip()
        from services.zalo_bot import resolve_chat
        return resolve_chat(token, chat_id)

    @router.post("/api/zalo-personal/resolve-thread")
    async def zalo_personal_resolve_thread(
        request: Request, authorization: str | None = Header(default=None),
    ):
        """zca-js getUserInfo / getGroupInfo — nhận diện thread Zalo Cá Nhân.

        Body: {account_id|ownId, thread_id|chat_id, kind?}.
        """
        require_admin(authorization)
        try:
            body = await request.json()
        except Exception:
            body = {}
        from services.zalo_personal import resolve_thread
        return resolve_thread(
            account=str((body or {}).get("account_id")
                        or (body or {}).get("ownId")
                        or (body or {}).get("account") or "").strip(),
            thread_id=str((body or {}).get("thread_id")
                          or (body or {}).get("chat_id") or "").strip(),
            prefer_kind=str((body or {}).get("kind") or "").strip().lower(),
        )

    @router.post("/zalo/webhook")
    async def zalo_webhook(request: Request):
        """Public endpoint for Zalo to send messages to."""
        from services.zalo_bot import handle_webhook
        return await handle_webhook(request)

    @router.post("/api/telegram/test")
    async def telegram_test(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.telegram_bot import _chat_ids, send_message
        ids = _chat_ids()
        if not ids:
            raise HTTPException(400, "Chưa cấu hình telegram_chat_ids")
        r = send_message(ids[0], "✅ Test từ chatgpt2api")
        return {"ok": r.get("ok", False)}

    @router.get("/api/images")
    async def get_images(request: Request, start_date: str = "", end_date: str = "", media_type: str = "image", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        referer = request.headers.get("referer", "")
        if "video-manager" in referer:
            media_type = "all"
        return list_images(resolve_image_base_url(request), start_date=start_date.strip(), end_date=end_date.strip(), media_type=media_type.strip())

    @router.get("/image-thumbnails/{image_path:path}", include_in_schema=False)
    async def get_image_thumbnail(image_path: str):
        return get_thumbnail_response(image_path)

    @router.post("/api/images/delete")
    async def delete_images_endpoint(body: ImageDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return delete_images(body.paths, start_date=body.start_date.strip(), end_date=body.end_date.strip(), all_matching=body.all_matching)

    @router.post("/api/images/download")
    async def download_images_endpoint(body: ImageDownloadRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        buf = download_images_zip(body.paths)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="images.zip"'},
        )

    @router.get("/api/images/download/{image_path:path}")
    async def download_single_image_endpoint(image_path: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return get_image_download_response(image_path)

    @router.get("/api/logs")
    async def get_logs(type: str = "", start_date: str = "", end_date: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"items": log_service.list(type=type.strip(), start_date=start_date.strip(), end_date=end_date.strip())}

    @router.post("/api/logs/delete")
    async def delete_logs(body: LogDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return log_service.delete(body.ids)

    @router.post("/api/proxy/test")
    async def test_proxy_endpoint(body: ProxyTestRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        candidate = (body.url or "").strip() or config.get_proxy_settings()
        if not candidate:
            raise HTTPException(status_code=400, detail={"error": "proxy url is required"})
        return {"result": await run_in_threadpool(test_proxy, candidate)}

    @router.get("/api/storage/info")
    async def get_storage_info(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        storage = config.get_storage_backend()
        return {
            "backend": storage.get_backend_info(),
            "health": storage.health_check(),
        }

    @router.post("/api/backup/test")
    async def test_backup_connection(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(backup_service.test_connection)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups")
    async def get_backups(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {
                "items": await run_in_threadpool(backup_service.list_backups),
                "state": backup_service.get_status(),
                "settings": backup_service.get_settings(),
            }
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/backups/run")
    async def run_backup_endpoint(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"result": await run_in_threadpool(backup_service.run_backup)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/backups/delete")
    async def delete_backup_endpoint(body: BackupDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            await run_in_threadpool(backup_service.delete_backup, body.key)
            return {"ok": True}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups/detail")
    async def get_backup_detail(key: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            return {"item": await run_in_threadpool(backup_service.get_backup_detail, key)}
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/backups/download")
    async def download_backup_endpoint(key: str = "", authorization: str | None = Header(default=None)):
        require_admin(authorization)
        try:
            item = await run_in_threadpool(backup_service.download_backup, key)
        except BackupError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        filename = str(item.get("name") or "backup.bin")
        quoted = quote(filename)
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "Content-Length": str(int(item.get("size") or 0)),
        }
        return Response(
            content=bytes(item.get("payload") or b""),
            media_type=str(item.get("content_type") or "application/octet-stream"),
            headers=headers,
        )


    @router.get("/api/images/tags")
    async def list_image_tags(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"tags": get_all_tags()}

    @router.post("/api/images/tags")
    async def update_image_tags(body: ImageTagsRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        rel = body.path.strip().lstrip("/")
        if not rel:
            raise HTTPException(status_code=400, detail={"error": "path is required"})
        tags = set_tags(rel, body.tags)
        return {"ok": True, "tags": tags}

    @router.delete("/api/images/tags/{tag}")
    async def delete_image_tag(tag: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        count = delete_tag(tag)
        return {"ok": True, "removed_from": count}

    # ── Backup / Restore (local full-state) ──

    @router.post("/api/v1/import-9router")
    async def import_9router_backup(
        body: Import9RouterRequest,
        authorization: str | None = Header(default=None),
    ):
        """Import token từ file backup 9router vào chatgpt2api (theo đường dẫn file)."""
        require_admin(authorization)
        path = (body.path or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail={"error": "path is required"})

        def _import():
            return import_9router_backup_from_api(path)

        result = await run_in_threadpool(_import)
        return result

    @router.post("/api/v1/import-9router-upload")
    async def import_9router_backup_upload(
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        """Import token từ nội dung file backup 9router (upload trực tiếp)."""
        require_admin(authorization)
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail={"error": "Invalid JSON body"})

        def _import():
            import tempfile
            import os
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
                json.dump(body, f)
                tmp_path = f.name
            try:
                return import_9router_backup_from_api(tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        result = await run_in_threadpool(_import)
        return result

    @router.post("/api/v1/backup")
    async def create_local_backup(
        body: BackupCreateRequest | None = None,
        authorization: str | None = Header(default=None),
    ):
        """Export toàn bộ state ra file JSON và lưu local.

        Body tùy chọn {"passphrase": "..."} → mã hóa file (backup chứa token thô)."""
        require_admin(authorization)
        passphrase = (body.passphrase if body else "").strip()
        result = await run_in_threadpool(_create_backup, passphrase)
        return result

    @router.get("/api/v1/backups")
    async def list_local_backups(authorization: str | None = Header(default=None)):
        """Danh sách backup local."""
        require_admin(authorization)
        return {"backups": state_backup.list_backups()}

    @router.post("/api/v1/restore")
    async def restore_from_backup(
        body: RestoreRequest,
        authorization: str | None = Header(default=None),
    ):
        """Phục hồi state từ file backup local."""
        require_admin(authorization)
        path = (body.path or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail={"error": "path is required"})

        def _restore():
            payload = state_backup.load_from_file(path, passphrase=body.passphrase.strip() or None)
            return state_backup.import_all(payload)

        report = await run_in_threadpool(_restore)
        return report.to_dict()

    @router.delete("/api/v1/backups/{filename}")
    async def delete_local_backup(filename: str, authorization: str | None = Header(default=None)):
        """Xóa một file backup local."""
        require_admin(authorization)
        ok = state_backup.delete_backup(filename)
        return {"ok": ok}

    # ── Health / Providers ──

    @router.get("/api/v1/health")
    async def system_health(authorization: str | None = Header(default=None)):
        """Trạng thái hệ thống: backends, providers, accounts."""
        require_admin(authorization)
        from services.account_service import account_service, account_group
        accounts = account_service.list_accounts()
        backoff_stats = rate_limit_backoff.get_stats()

        # Per-provider account breakdown so the total is explainable.
        by_group: dict[str, dict[str, int]] = {}
        for acc in accounts:
            grp = account_group(acc)
            bucket = by_group.setdefault(grp, {"total": 0, "active": 0})
            bucket["total"] += 1
            if acc.get("status") == "active":
                bucket["active"] += 1

        return {
            "status": "ok",
            "version": app_version,
            "accounts": {
                "total": len(accounts),
                "active": sum(1 for a in accounts if a.get("status") == "active"),
                "limited": sum(1 for a in accounts if a.get("status") == "limited"),
                "error": sum(1 for a in accounts if a.get("status") in ("error", "disabled")),
                "by_group": by_group,
            },
            "backoff": backoff_stats,
            "quota_watcher": quota_watcher.get_stats(),
            "model_cooldown": model_cooldown.get_stats(),
            "provider_circuits": _provider_circuit_stats(),
            "session_affinity": _session_affinity_stats(),
            "opencode": {
                "available": opencode_provider.is_available,
            },
            "gemini": _check_gemini_status(),
        }

    @router.get("/api/v1/usage/stats")
    async def usage_stats(period: str = "30d", authorization: str | None = Header(default=None)):
        """Usage statistics: total requests, tokens, costs from actual usage log."""
        require_admin(authorization)
        from services.usage_tracker import get_usage_stats, get_active_providers
        stats = get_usage_stats(period)
        stats["activeProviders"] = get_active_providers()
        return stats

    @router.get("/api/v1/usage/recent")
    async def recent_requests(authorization: str | None = Header(default=None)):
        """Recent API requests from usage log."""
        require_admin(authorization)
        from services.usage_tracker import get_recent_requests
        return {"requests": get_recent_requests()}

    @router.get("/api/v1/usage/timeseries")
    async def usage_timeseries(granularity: str = "day", period: str = "30d", authorization: str | None = Header(default=None)):
        """Per-provider token usage over time. period = range, granularity = bucket size."""
        require_admin(authorization)
        from services.usage_tracker import get_usage_timeseries
        return get_usage_timeseries(granularity, period)

    @router.get("/api/v1/usage/daily")
    async def usage_daily(days: int = 14, authorization: str | None = Header(default=None)):
        """Per-day request/token totals for the last N days (filled zeros, max 90)."""
        require_admin(authorization)
        from services.usage_tracker import get_usage_daily
        return get_usage_daily(days)

    @router.get("/api/v1/agent/runs")
    async def agent_runs(
        limit: int = 50,
        user_id: str = "",
        channel: str = "",
        status: str = "",
        source_kind: str = "",
        authorization: str | None = Header(default=None),
    ):
        """Agent run journal (tools, latency, model, source/dest account) for the Runs UI."""
        require_admin(authorization)
        from services.agent import run_journal as rj
        rows = rj.list_runs(
            limit=limit, user_id=user_id, channel=channel, status=status,
            source_kind=source_kind,
        )
        return {"ok": True, "rows": rows, "stats": rj.stats(24)}

    @router.get("/api/v1/agent/runs/{run_id}")
    async def agent_run_detail(run_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.agent import run_journal as rj
        row = rj.get_run(run_id)
        if not row:
            return {"ok": False, "error": "not found"}
        return {"ok": True, "row": row}

    @router.get("/api/v1/agent/model-hints")
    async def agent_model_hints(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services.agent import model_hints as mh
        return {"ok": True, "enabled": mh.is_enabled(), "hints": mh.describe()}

    @router.get("/api/v1/email/status")
    async def email_status(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import email_channel as ec
        return {"ok": True, **ec.status()}

    @router.post("/api/v1/email/test")
    async def email_test(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import email_channel as ec
        return await run_in_threadpool(ec.test_connection)

    @router.post("/api/v1/email/poll")
    async def email_poll(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import email_channel as ec
        return await run_in_threadpool(ec.poll_once)

    @router.get("/api/v1/providers")
    async def list_providers(authorization: str | None = Header(default=None)):
        """Danh sách provider đang active."""
        require_admin(authorization)
        provider_configs = config.data.get("providers") or {}

        providers = []
        for name, cfg in provider_configs.items():
            if isinstance(cfg, dict):
                providers.append({
                    "name": name,
                    "enabled": cfg.get("enabled", False),
                    "noAuth": cfg.get("noAuth", False),
                    "has_api_key": bool(cfg.get("api_key")),
                    "has_base_url": bool(cfg.get("base_url")),
                })

        return {"providers": providers}

    @router.get("/api/v1/providers/{provider_id}/models")
    async def provider_models(provider_id: str, authorization: str | None = Header(default=None)):
        """Lấy danh sách model của một provider."""
        require_admin(authorization)
        if provider_id == "opencode":
            models = opencode_provider.list_models()
            return {"models": models}
        return {"models": []}

    @router.post("/api/v1/providers/{provider_id}/test")
    async def test_provider(provider_id: str, authorization: str | None = Header(default=None)):
        """Test kết nối đến một provider."""
        require_admin(authorization)
        if provider_id == "opencode":
            available = opencode_provider.is_available
            return {"provider": provider_id, "available": available}
        if provider_id == "nvidia_nim":
            from services.providers.nvidia_nim import nvidia_nim_provider
            available = nvidia_nim_provider.is_available
            return {"provider": provider_id, "available": available}
        raise HTTPException(status_code=404, detail={"error": f"unknown provider: {provider_id}"})

    # ── OAuth Login ──

    @router.get("/api/oauth/codex/start")
    async def start_codex_oauth(request: Request, authorization: str | None = Header(default=None)):
        """Generate Codex OAuth URL for user to login."""
        require_admin(authorization)
        host = request.headers.get("host", "localhost:1455")
        scheme = "https" if request.url.scheme == "https" else "http"
        base = config.base_url or f"{scheme}://{host}"
        result = get_codex_auth_url(base)
        result["help"] = (
            "1. Mở URL trên trong browser. "
            "2. Đăng nhập và authorize. "
            "3. Browser chuyển tới http://localhost:1455/auth/callback?code=... "
            "(OpenAI chỉ whitelist cổng 1455 — không phải 3030). "
            "4. Nếu listener :1455 đang chạy trên máy mở browser → token tự lưu. "
            "5. Nếu không: copy TOÀN BỘ URL thanh địa chỉ (localhost:1455/...) dán vào form exchange."
        )
        result["redirect_uri"] = "http://localhost:1455/auth/callback"
        return result

    @router.get("/api/oauth/codex/last-callback")
    async def codex_last_callback(authorization: str | None = Header(default=None)):
        """Poll after opening OAuth — returns last :1455 auto-exchange result if any."""
        require_admin(authorization)
        from services.codex_callback_listener import get_last_result
        return {"result": get_last_result()}

    @router.get("/auth/callback")
    async def codex_auth_callback(code: str = "", state: str = ""):
        """Handle Codex OAuth callback (matches 9router path)."""
        if not code or not state:
            raise HTTPException(status_code=400, detail={"error": "Missing code or state"})
        try:
            result = exchange_codex_code(code, state)
            return HTMLResponse(content=f"""
            <html><body style="font-family:sans-serif;padding:40px;text-align:center">
            <h2>{result['message']}</h2>
            <p>Bạn có thể đóng tab này.</p>
            <script>setTimeout(function(){{window.close()}},3000)</script>
            </body></html>
            """)
        except Exception as exc:
            return HTMLResponse(content=f"""
            <html><body style="font-family:sans-serif;padding:40px;text-align:center">
            <h2 style="color:red">Lỗi: {str(exc)}</h2>
            <p>Copy URL này và dùng API exchange thủ công.</p>
            </body></html>
            """, status_code=400)

    @router.get("/api/oauth/codex/callback")
    async def codex_oauth_callback(code: str = "", state: str = ""):
        """Handle Codex OAuth callback — exchange code for token."""
        if not code or not state:
            raise HTTPException(status_code=400, detail={"error": "Missing code or state"})
        try:
            result = exchange_codex_code(code, state)
            return HTMLResponse(content=f"""
            <html><body style="font-family:sans-serif;padding:40px;text-align:center">
            <h2>{result['message']}</h2>
            <p>Bạn có thể đóng tab này.</p>
            <script>setTimeout(function(){{window.close()}},3000)</script>
            </body></html>
            """)
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)})

    @router.post("/api/oauth/codex/exchange")
    async def codex_oauth_exchange(body: CodexExchangeRequest, authorization: str | None = Header(default=None)):
        """Exchange Codex OAuth code manually — user pastes redirect URL."""
        require_admin(authorization)
        from urllib.parse import urlparse, parse_qs
        url = (body.redirect_url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail={"error": "redirect_url is required"})
        # Replace localhost with actual host if needed
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [""])[0]
        if not code or not state:
            raise HTTPException(status_code=400, detail={"error": "URL không chứa code và state. Copy TOÀN Bộ URL sau khi redirect."})
        try:
            result = exchange_codex_code(code, state)
            return result
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)})

    # ── Antigravity Google OAuth Login ──

    @router.get("/api/oauth/antigravity/start")
    async def start_antigravity_oauth(request: Request, authorization: str | None = Header(default=None)):
        """Generate Antigravity Google OAuth URL for user to login."""
        require_admin(authorization)
        from services.oauth_service import get_antigravity_auth_url
        result = get_antigravity_auth_url()
        result["help"] = (
            "1. Mở URL trên trong browser. "
            "2. Đăng nhập Google và cấp quyền. "
            "3. Sau khi redirect, copy TOÀN BỘ URL trên thanh địa chỉ (có dạng http://localhost:8080/callback?code=...). "
            "4. Dán URL đó vào POST /api/oauth/antigravity/exchange với body {\"redirect_url\": \"URL_DA_COPY\"}"
        )
        return result

    @router.post("/api/oauth/antigravity/exchange")
    async def antigravity_oauth_exchange(body: AntigravityExchangeRequest, authorization: str | None = Header(default=None)):
        """Exchange Antigravity Google OAuth code manually — user pastes redirect URL."""
        require_admin(authorization)
        from urllib.parse import urlparse, parse_qs
        from services.oauth_service import exchange_antigravity_code
        url = (body.redirect_url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail={"error": "redirect_url is required"})
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [""])[0]
        if not code or not state:
            raise HTTPException(status_code=400, detail={"error": "URL không chứa code và state. Copy TOÀN BỘ URL sau khi redirect."})
        try:
            result = exchange_antigravity_code(code, state)
            return result
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)})

    @router.get("/api/oauth/session-url")
    async def get_session_url(authorization: str | None = Header(default=None)):
        """Return chatgpt.com session URL for getting image token."""
        require_admin(authorization)
        return {"url": get_chatgpt_session_url()}

    @router.post("/api/oauth/detect-token")
    async def detect_token(body: dict, authorization: str | None = Header(default=None)):
        """Detect token type (codex vs google)."""
        require_admin(authorization)
        token = str(body.get("token") or "").strip()
        if not token:
            raise HTTPException(status_code=400, detail={"error": "token is required"})
        return {"type": detect_token_type(token)}

    # ── Custom Providers ──

    @router.get("/api/v1/custom-providers")
    async def list_custom_providers(authorization: str | None = Header(default=None)):
        """Lấy danh sách custom providers."""
        require_admin(authorization)
        from services.providers.custom_openai import get_custom_providers
        return {"custom_providers": get_custom_providers()}

    @router.post("/api/v1/custom-providers")
    async def save_custom_provider(body: dict, authorization: str | None = Header(default=None)):
        """Thêm hoặc cập nhật một custom provider."""
        require_admin(authorization)
        provider = body.get("provider") or {}
        if not isinstance(provider, dict):
            raise HTTPException(status_code=400, detail={"error": "provider object is required"})

        provider_id = str(provider.get("prefix") or provider.get("name") or "").strip().lower().replace(" ", "_")
        if not provider_id:
            raise HTTPException(status_code=400, detail={"error": "provider prefix or name is required"})

        base_url = str(provider.get("base_url") or "").strip().rstrip("/")
        # Optional `base_urls[]` array — pool extra endpoints sharing the
        # same API key. CustomOpenAIProvider rotates them in FIFO order.
        base_urls_raw = provider.get("base_urls") or []
        if not isinstance(base_urls_raw, list):
            base_urls_raw = []
        base_urls = [str(u or "").strip().rstrip("/") for u in base_urls_raw if str(u or "").strip()]
        api_key = str(provider.get("api_key") or "").strip()
        api_keys = provider.get("api_keys") or []
        if not isinstance(api_keys, list):
            api_keys = []
        api_keys = [k.strip() for k in api_keys if k.strip()]
        # Support api_key + api_keys combination
        if api_key and api_key not in api_keys:
            api_keys.insert(0, api_key)
        name = str(provider.get("name") or provider_id).strip()
        enabled = provider.get("enabled", True)
        prefix = str(provider.get("prefix") or provider_id).strip().lower().replace(" ", "_")

        # Soft validate: probe endpoint if key provided, but NEVER block saving
        test_key = api_keys[0] if api_keys else api_key
        warning = None
        if not test_key:
            warning = "No API key specified"
        else:
            try:
                from curl_cffi import requests as cffi_req
                _burl = base_url.rstrip("/")
                _models_path = "/models" if _burl.endswith("/v1") else "/v1/models"
                resp = cffi_req.get(
                    f"{_burl}{_models_path}",
                    headers={"Authorization": f"Bearer {test_key}"},
                    timeout=5,
                )
                if resp.status_code >= 400:
                    warning = f"Cannot reach {base_url}: HTTP {resp.status_code}"
            except Exception as exc:
                warning = f"Cannot reach {base_url}: {exc}"

        # Save to config (always persist)
        custom_providers = dict(config.data.get("custom_providers") or {})
        if not isinstance(custom_providers, dict):
            custom_providers = {}
        custom_providers[provider_id] = {
            "name": name,
            "base_url": base_url,
            "base_urls": base_urls,
            "api_key": api_keys[0] if api_keys else "",
            "api_keys": api_keys,
            "prefix": prefix,
            "enabled": enabled,
        }
        config.data["custom_providers"] = custom_providers
        config._save()
        from services.protocol.openai_v1_models import invalidate_models_cache
        invalidate_models_cache()

        return {
            "custom_providers": custom_providers,
            "saved": True,
            "provider_id": provider_id,
            "warning": warning,
        }

    @router.delete("/api/v1/custom-providers/{provider_id}")
    async def delete_custom_provider(provider_id: str, authorization: str | None = Header(default=None)):
        """Xóa một custom provider."""
        require_admin(authorization)
        custom_providers = dict(config.data.get("custom_providers") or {})
        if not isinstance(custom_providers, dict):
            custom_providers = {}
        if provider_id in custom_providers:
            del custom_providers[provider_id]
            config.data["custom_providers"] = custom_providers
            config._save()
            from services.protocol.openai_v1_models import invalidate_models_cache
            invalidate_models_cache()
            return {"deleted": True, "provider_id": provider_id}
        raise HTTPException(status_code=404, detail={"error": f"provider '{provider_id}' not found"})

    # ── Model Settings ──

    @router.get("/api/v1/model-settings")
    async def get_model_settings(authorization: str | None = Header(default=None)):
        """Lấy cấu hình model (enabled models + defaults per provider)."""
        require_admin(authorization)
        ms = config.data.get("model_settings") or {}
        if not isinstance(ms, dict):
            ms = {}
        return {
            "model_settings": {
                "enabled_models": ms.get("enabled_models") or {},
                "default_models": ms.get("default_models") or {},
            }
        }

    @router.get("/api/v1/available-models")
    async def get_available_models(authorization: str | None = Header(default=None), refresh: str = ""):
        """Lấy toàn bộ model có sẵn từ cache (nhanh). Thêm ?refresh=true để tải lại."""
        require_admin(authorization)
        from services.protocol.openai_v1_models import list_models
        force = refresh.lower() == "true"
        result = list_models(force_refresh=force, apply_filter=False)
        # Group models by owned_by
        grouped: dict[str, list[str]] = {}
        for item in result.get("data", []):
            owner = str(item.get("owned_by") or "chatgpt")
            mid = str(item.get("id") or "").strip()
            if mid:
                if owner not in grouped:
                    grouped[owner] = []
                grouped[owner].append(mid)
        # Sort each group
        for owner in grouped:
            grouped[owner].sort()
        return {"providers": grouped}

    @router.get("/api/v1/models-with-capabilities")
    async def get_models_with_capabilities(authorization: str | None = Header(default=None)):
        """Lấy danh sách model kèm phân loại capability (chat/vision/image)."""
        require_admin(authorization)
        from utils.helper import classify_model_capability, get_model_capability_label

        # Get enabled models from model_settings
        ms = config.data.get("model_settings") or {}
        if not isinstance(ms, dict):
            ms = {}
        enabled_by_provider = ms.get("enabled_models") or {}
        if not isinstance(enabled_by_provider, dict):
            enabled_by_provider = {}

        # Fetch all available models (unfiltered — UI decides what to show)
        from services.protocol.openai_v1_models import list_models
        result = list_models(apply_filter=False)
        all_models = result.get("data", [])

        enriched: list[dict] = []
        for model in all_models:
            mid = str(model.get("id") or "").strip()
            if not mid:
                continue
            caps = classify_model_capability(mid)
            enriched.append({
                "id": mid,
                "owned_by": str(model.get("owned_by") or ""),
                "capability": caps[0] if caps else "chat",  # Primary capability
                "capabilities": caps,  # All capabilities
                "capability_labels": [get_model_capability_label(c) for c in caps],
                "enabled": _is_model_enabled(mid, enabled_by_provider),
            })

        # Sort: chat first, then vision, then image, then video
        def _sort_key(m):
            caps = m.get("capabilities", ["chat"])
            if "video" in caps: return 3
            if "image" in caps: return 2
            if "vision" in caps: return 1
            return 0
        enriched.sort(key=lambda m: (_sort_key(m), m["id"]))

        return {
            "models": enriched,
            "counts": {
                "chat": sum(1 for m in enriched if "chat" in (m.get("capabilities") or ["chat"])),
                "vision": sum(1 for m in enriched if "vision" in (m.get("capabilities") or [])),
                "image": sum(1 for m in enriched if "image" in (m.get("capabilities") or [])),
                "video": sum(1 for m in enriched if "video" in (m.get("capabilities") or [])),
            },
        }

    @router.post("/api/v1/model-settings")
    async def save_model_settings(body: dict, authorization: str | None = Header(default=None)):
        """Lưu cấu hình model."""
        require_admin(authorization)
        model_settings = body.get("model_settings")
        if not isinstance(model_settings, dict):
            raise HTTPException(status_code=400, detail={"error": "model_settings is required"})
        enabled = model_settings.get("enabled_models")
        defaults = model_settings.get("default_models")
        if not isinstance(enabled, dict):
            enabled = {}
        if not isinstance(defaults, dict):
            defaults = {}
        config.data["model_settings"] = {
            "enabled_models": enabled,
            "default_models": defaults,
        }
        config._save()
        from services.protocol.openai_v1_models import invalidate_models_cache
        invalidate_models_cache()
        return {"model_settings": config.data["model_settings"], "saved": True}

    return router
