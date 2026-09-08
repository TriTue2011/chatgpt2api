"""MCP Presets API — list, install, uninstall, toggle MCP servers."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from services.config import config
from services.mcp_presets import PRESETS, find
from api.support import require_admin
from utils.log import logger


class ConnectionRequest(BaseModel):
    url: str = ""
    api_key: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    transport: str = "auto"


class InstallRequest(ConnectionRequest):
    id: str
    name: str = ""
    description: str = ""
    url_override: str = ""  # For GitMCP: user fills in owner/repo


_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$")
_RESERVED_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection",
    "content-type", "accept", "mcp-session-id", "mcp-protocol-version",
    "mcp-method", "mcp-name",
}


def _validated_connection(body: ConnectionRequest, url: str | None = None) -> tuple[str, dict[str, str], str]:
    from services.net_guard import is_http_url

    target = str(url if url is not None else body.url).strip()
    if len(target) > 2048 or not is_http_url(target):
        raise HTTPException(status_code=400, detail="URL MCP phải là http(s) và có hostname")
    parsed = urlparse(target)
    if parsed.username is not None or parsed.password is not None:
        raise HTTPException(status_code=400, detail="Không đặt credential trong URL MCP")
    if body.transport not in ("auto", "streamable_http", "sse"):
        raise HTTPException(status_code=400, detail="Transport MCP không hợp lệ")
    if len(body.api_key) > 8192:
        raise HTTPException(status_code=400, detail="API key quá dài")
    if len(body.headers) > 32:
        raise HTTPException(status_code=400, detail="Tối đa 32 custom headers")
    clean: dict[str, str] = {}
    total = 0
    for raw_name, raw_value in body.headers.items():
        name = str(raw_name).strip()
        value = str(raw_value).strip()
        if not _HEADER_NAME.fullmatch(name) or name.lower() in _RESERVED_HEADERS:
            raise HTTPException(status_code=400, detail=f"Header MCP không được phép: {name or '(trống)'}")
        if not value or "\r" in value or "\n" in value or len(value) > 8192:
            raise HTTPException(status_code=400, detail=f"Giá trị header không hợp lệ: {name}")
        total += len(name) + len(value)
        clean[name] = value
    if total > 32768:
        raise HTTPException(status_code=400, detail="Tổng custom headers quá lớn")
    return target, clean, body.transport


def _normalize_mcp(installed) -> dict:
    """mcp_servers có thể là list (bản cũ) hoặc dict → luôn trả dict."""
    if isinstance(installed, list):
        return {item.get("id", str(i)): item
                for i, item in enumerate(installed) if isinstance(item, dict)}
    return installed if isinstance(installed, dict) else {}


def _oauth_status(info: dict) -> dict:
    if not info.get("oauth_id"):
        return {"auth_type": "manual"}
    from services.mcp_oauth import get_manager, OAuthError
    try:
        status = get_manager().status(info["oauth_id"])
    except OAuthError as exc:
        status = {"status": "reauth_required", "error": str(exc)}
    return {"auth_type": "oauth", "oauth": status}


async def _disconnect_oauth(oauth_id):
    if oauth_id:
        from services.mcp_oauth import get_manager
        await run_in_threadpool(get_manager().disconnect, oauth_id, forget_client=True)


def create_router() -> APIRouter:
    router = APIRouter()
    from api.mcp_oauth import create_router as oauth_router
    router.include_router(oauth_router())

    @router.post("/api/mcp/validate")
    async def validate_server(
        body: ConnectionRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        url, headers, transport = _validated_connection(body)
        from services.mcp_client import validate_mcp_server

        return await run_in_threadpool(
            validate_mcp_server,
            url,
            body.api_key,
            headers=headers,
            transport=transport,
        )

    @router.get("/api/mcp/custom")
    async def list_custom(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        installed = _normalize_mcp(config.data.get("mcp_servers") or {})
        mcps = []
        for mcp_id, info in installed.items():
            # Không phải preset = MCP do người dùng tự khai. Lọc theo cờ
            # `custom`/tiền tố `ext_` thì mọi MCP thêm TRƯỚC khi có cờ này biến
            # mất khỏi danh sách — vẫn chạy, nhưng không ai xoá hay sửa được nữa.
            if any(preset.id == mcp_id for preset in PRESETS):
                continue
            raw_headers = info.get("headers") or {}
            header_names = sorted(raw_headers) if isinstance(raw_headers, dict) else []
            mcps.append({
                "id": mcp_id,
                "name": info.get("name", mcp_id),
                "description": info.get("description", ""),
                "url": info.get("url", ""),
                "transport": info.get("transport", "auto"),
                "enabled": bool(info.get("enabled", True)),
                "has_api_key": bool(info.get("api_key")),
                **_oauth_status(info),
                "header_names": header_names,
            })
        return {"mcps": mcps}

    @router.get("/api/mcp/presets")
    async def list_presets(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        installed = config.data.get("mcp_servers") or {}
        if isinstance(installed, list):
            installed = {item.get("id", str(i)): item for i, item in enumerate(installed) if isinstance(item, dict)}
        elif not isinstance(installed, dict):
            installed = {}

        result = []
        for p in PRESETS:
            info = installed.get(p.id) or {}
            result.append({
                "id": p.id, "name": p.name, "description": p.description,
                "url": p.url, "category": p.category, "icon": p.icon,
                "homepage": p.homepage, "requires_api_key": p.requires_api_key,
                "api_key_help": p.api_key_help, "tags": p.tags,
                "installed": p.id in installed,
                "enabled": bool(info.get("enabled", True)),
                "has_api_key": bool(info.get("api_key")),
                **_oauth_status(info),
            })

        # Also include hub-discovered MCPs not in PRESETS
        for mcp_id, info in installed.items():
            if not any(p.id == mcp_id for p in PRESETS):
                result.append({
                    "id": mcp_id, "name": info.get("name", mcp_id),
                    "description": info.get("description", ""), "url": info.get("url", ""),
                    "category": "hub", "icon": "🔌",
                    "homepage": "", "requires_api_key": False,
                    "api_key_help": "", "tags": ["hub"],
                    "installed": True,
                    "enabled": bool(info.get("enabled", True)),
                    "has_api_key": bool(info.get("api_key")),
                    **_oauth_status(info),
                    "has_headers": bool(info.get("headers")),
                    "transport": info.get("transport", "auto"),
                })

        result.sort(key=lambda x: (not x["installed"], x["category"], x["name"]))
        return {"presets": result}

    @router.post("/api/mcp/install")
    async def install_preset(
        body: InstallRequest,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        preset = find(body.id)
        # Allow hub-discovered MCPs not in PRESETS when url_override is provided
        if preset is None and not body.url_override:
            raise HTTPException(status_code=404, detail=f"Unknown preset: {body.id}")

        url = body.url_override or body.url or (preset.url if preset else "")
        if not url:
            raise HTTPException(
                status_code=400,
                detail=f"Preset '{body.id}' cần URL riêng của từng hệ thống — truyền url_override (vd URL webhook ha-mcp)",
            )
        url, headers, transport = _validated_connection(body, url)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", body.id):
            raise HTTPException(status_code=400, detail="ID MCP chỉ gồm chữ, số, _ và - (tối đa 64 ký tự)")
        name = preset.name if preset else (body.name.strip() or body.id)
        if len(name) > 120 or len(body.description) > 1000:
            raise HTTPException(status_code=400, detail="Tên hoặc mô tả MCP quá dài")
        import time
        entry = {
            "url": url,
            "name": name,
            "description": body.description.strip(),
            "enabled": True,
            "api_key": body.api_key or None,
            "headers": headers,
            "transport": transport,
            "custom": preset is None,
            "requires_api_key": preset.requires_api_key if preset else bool(body.api_key),
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        # ATOMIC: đọc lại + merge trong khoá (tránh hai request ghi đè mất cấu hình).
        def _apply(d):
            inst = _normalize_mcp(d.get("mcp_servers") or {})
            old_oauth_id = (inst.get(body.id) or {}).get("oauth_id")
            inst[body.id] = entry
            d["mcp_servers"] = inst
            return old_oauth_id
        old_oauth_id = config.mutate(_apply)
        await _disconnect_oauth(old_oauth_id)
        try:
            from services.mcp_client import invalidate_tools_cache
            invalidate_tools_cache()
        except Exception:
            pass
        parsed_log_url = urlparse(url)
        safe_log_url = parsed_log_url._replace(query="", fragment="").geturl()
        logger.info({"event": "mcp_installed", "id": body.id, "url": safe_log_url})
        return {"ok": True, "id": body.id}

    @router.post("/api/mcp/uninstall/{preset_id}")
    async def uninstall_preset(
        preset_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)

        def _apply(d):
            inst = _normalize_mcp(d.get("mcp_servers") or {})
            old_oauth_id = (inst.get(preset_id) or {}).get("oauth_id")
            existed = preset_id in inst
            if existed:
                del inst[preset_id]
                d["mcp_servers"] = inst
            return existed, old_oauth_id
        removed, old_oauth_id = config.mutate(_apply)
        await _disconnect_oauth(old_oauth_id)
        if removed:
            try:
                from services.mcp_client import invalidate_tools_cache
                invalidate_tools_cache()
            except Exception:
                pass
            logger.info({"event": "mcp_uninstalled", "id": preset_id})
        return {"ok": True, "id": preset_id}

    @router.post("/api/mcp/toggle/{preset_id}")
    async def toggle_preset(
        preset_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)

        _res: dict = {}

        def _apply(d):
            inst = _normalize_mcp(d.get("mcp_servers") or {})
            entry = inst.get(preset_id)
            if entry is None:
                return False
            entry["enabled"] = not bool(entry.get("enabled", True))
            inst[preset_id] = entry
            d["mcp_servers"] = inst
            _res["enabled"] = entry["enabled"]
            return True
        if not config.mutate(_apply):
            raise HTTPException(status_code=404, detail=f"Not installed: {preset_id}")
        try:
            from services.mcp_client import invalidate_tools_cache
            invalidate_tools_cache()
        except Exception:
            pass
        logger.info({"event": "mcp_toggled", "id": preset_id, "enabled": _res["enabled"]})
        return {"ok": True, "id": preset_id, "enabled": _res["enabled"]}

    @router.post("/api/mcp/ha-docs/refresh")
    async def refresh_ha_docs(authorization: str | None = Header(default=None)):
        """Sinh tài liệu nhà kiểu HADocs từ HA API rồi nạp vào KB `ha_docs` trên hub."""
        require_admin(authorization)
        import os
        import time

        import httpx

        from services.ha_docs_service import KB_LABEL, KB_NAME, build_ha_docs_markdown

        try:
            markdown = build_ha_docs_markdown()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Không sinh được tài liệu HA: {exc}")

        hub = os.getenv("MCP_HUB_INTERNAL_URL", "http://127.0.0.1:8005").rstrip("/")
        timeout = httpx.Timeout(connect=5.0, read=180.0, write=180.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Tạo lại từ đầu để không sót chunk của lần quét trước
            try:
                await client.delete(f"{hub}/api/studio/kb/{KB_NAME}")
            except Exception:
                pass
            try:
                resp = await client.post(
                    f"{hub}/api/studio/kb",
                    json={"name": KB_NAME, "label": KB_LABEL, "content": markdown},
                )
                data = resp.json()
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Không gọi được MCP Hub: {exc}")
        if not data.get("ok"):
            raise HTTPException(status_code=502, detail="; ".join(data.get("errors") or ["Hub không tạo được KB"]))

        # Đăng ký MCP ask_ha_docs vào gateway để agent gọi được (hub mount KB động lúc khởi động)
        _entry = {
            "url": f"http://127.0.0.1:8005/{KB_NAME}/mcp",
            "name": KB_LABEL,
            "enabled": True,
            "api_key": None,
            "requires_api_key": False,
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        def _apply(d):
            inst = _normalize_mcp(d.get("mcp_servers") or {})
            added = KB_NAME not in inst
            if added:
                inst[KB_NAME] = _entry
                d["mcp_servers"] = inst
            return added
        if config.mutate(_apply):
            try:
                from services.mcp_client import invalidate_tools_cache
                invalidate_tools_cache()
            except Exception:
                pass
        logger.info({"event": "ha_docs_refreshed", "chunks": data.get("chunks")})
        return {
            "ok": True,
            "kb": KB_NAME,
            "chunks": data.get("chunks", 0),
            "note": "KB đã nạp vào Chroma. Tool ask_ha_docs xuất hiện sau lần restart container kế tiếp (mount MCP động).",
        }

    @router.post("/api/mcp/discover")
    async def discover_hub(req: Request, authorization: str | None = Header(default=None)):
        """Discover MCPs from a hub URL. Body: {hub_url: 'http://...'}"""
        require_admin(authorization)
        import urllib.request, json as _json
        body = await req.json()
        hub_url = str((body or {}).get("hub_url", "")).strip().rstrip("/")
        if not hub_url:
            raise HTTPException(status_code=400, detail="hub_url is required")
        # Chỉ http/https (cho phép LAN vì hub có thể nội bộ) — chặn file://,
        # gopher://… biến hub_url thành đường đọc file/SSRF nếu admin token lộ.
        from services.net_guard import is_http_url
        if not is_http_url(hub_url):
            raise HTTPException(status_code=400, detail="hub_url phải là http(s)")
        # Threadpool: urlopen là lời gọi CHẶN. Gateway chạy uvicorn --workers 1
        # nên chặn event loop ở đây là đóng băng cả bot lẫn web UI tới 10 giây,
        # chỉ vì một hub không phản hồi.
        def _fetch() -> str:
            return urllib.request.urlopen(
                urllib.request.Request(f"{hub_url}/"), timeout=10).read().decode()

        try:
            hub_info = _json.loads(await run_in_threadpool(_fetch))
        except Exception as e:
            return {"ok": False, "error": f"Cannot connect to hub: {e}"}

        # VALIDATE dữ liệu hub (không tin tuyệt đối — hub méo có thể gây 500).
        if not isinstance(hub_info, dict):
            return {"ok": False, "error": "Hub trả về dữ liệu không hợp lệ"}
        _raw_names = hub_info.get("mcps") or []
        mcp_names = [str(n) for n in _raw_names if isinstance(n, (str, int)) and str(n).strip()] \
            if isinstance(_raw_names, list) else []
        _raw_details = hub_info.get("mcp_details") or []
        # Chỉ nhận detail là dict CÓ id (trước đây d["id"] thiếu key → KeyError → 500).
        detail_map = {str(d["id"]): d for d in _raw_details
                      if isinstance(d, dict) and d.get("id")} \
            if isinstance(_raw_details, list) else {}
        installed = _normalize_mcp(config.data.get("mcp_servers") or {})
        mcps = []
        for name in mcp_names:
            url = f"{hub_url}/{name}/mcp"
            info = installed.get(name) or {}
            detail = detail_map.get(name, {})
            mcps.append({
                "id": name, "name": detail.get("label", name),
                "description": detail.get("description", ""),
                "category": detail.get("category", "hub"),
                "url": url,
                "installed": name in installed,
                "enabled": bool(info.get("enabled", True)),
            })
        # Auto-update URLs for already installed MCPs — ATOMIC, đọc lại trong khoá.
        def _apply(d):
            inst = _normalize_mcp(d.get("mcp_servers") or {})
            upd = 0
            for name in mcp_names:
                url = f"{hub_url}/{name}/mcp"
                if name in inst and inst[name].get("url", "") != url:
                    inst[name]["url"] = url
                    upd += 1
            if upd:
                d["mcp_servers"] = inst
            return upd
        updated = config.mutate(_apply)
        if updated > 0:
            logger.info({"event": "mcp_urls_updated", "count": updated, "hub_url": hub_url})

        return {"ok": True, "hub_name": hub_info.get("name", ""), "mcps": mcps, "urls_updated": updated}

    return router
