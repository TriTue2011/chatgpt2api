"""MCP Presets API — list, install, uninstall, toggle MCP servers."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from services.config import config
from services.mcp_presets import PRESETS, find
from api.support import require_admin
from utils.log import logger


class InstallRequest(BaseModel):
    id: str
    api_key: str = ""
    url_override: str = ""  # For GitMCP: user fills in owner/repo


def create_router() -> APIRouter:
    router = APIRouter()

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
            })

        # Also include hub-discovered MCPs not in PRESETS
        for mcp_id, info in installed.items():
            if not any(p.id == mcp_id for p in PRESETS):
                result.append({
                    "id": mcp_id, "name": info.get("name", mcp_id),
                    "description": "", "url": info.get("url", ""),
                    "category": "hub", "icon": "🔌",
                    "homepage": "", "requires_api_key": False,
                    "api_key_help": "", "tags": ["hub"],
                    "installed": True,
                    "enabled": bool(info.get("enabled", True)),
                    "has_api_key": bool(info.get("api_key")),
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

        installed = config.data.get("mcp_servers") or {}
        if isinstance(installed, list):
            installed = {item.get("id", str(i)): item for i, item in enumerate(installed) if isinstance(item, dict)}
        elif not isinstance(installed, dict):
            installed = {}

        url = body.url_override or (preset.url if preset else "")
        if not url:
            raise HTTPException(
                status_code=400,
                detail=f"Preset '{body.id}' cần URL riêng của từng hệ thống — truyền url_override (vd URL webhook ha-mcp)",
            )
        name = preset.name if preset else body.id
        installed[body.id] = {
            "url": url,
            "name": name,
            "enabled": True,
            "api_key": body.api_key or None,
            "requires_api_key": preset.requires_api_key if preset else bool(body.api_key),
            "installed_at": None,
        }
        import time
        installed[body.id]["installed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        config.data["mcp_servers"] = installed
        config._save()
        try:
            from services.mcp_client import invalidate_tools_cache
            invalidate_tools_cache()
        except Exception:
            pass
        logger.info({"event": "mcp_installed", "id": body.id, "url": url})
        return {"ok": True, "id": body.id}

    @router.post("/api/mcp/uninstall/{preset_id}")
    async def uninstall_preset(
        preset_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        installed = config.data.get("mcp_servers") or {}
        if isinstance(installed, list):
            installed = {item.get("id", str(i)): item for i, item in enumerate(installed) if isinstance(item, dict)}
        elif not isinstance(installed, dict):
            installed = {}

        if preset_id in installed:
            del installed[preset_id]
            config.data["mcp_servers"] = installed
            config._save()
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
        installed = config.data.get("mcp_servers") or {}
        if isinstance(installed, list):
            installed = {item.get("id", str(i)): item for i, item in enumerate(installed) if isinstance(item, dict)}
        elif not isinstance(installed, dict):
            installed = {}

        entry = installed.get(preset_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Not installed: {preset_id}")

        entry["enabled"] = not bool(entry.get("enabled", True))
        config.data["mcp_servers"] = installed
        config._save()
        try:
            from services.mcp_client import invalidate_tools_cache
            invalidate_tools_cache()
        except Exception:
            pass
        logger.info({"event": "mcp_toggled", "id": preset_id, "enabled": entry["enabled"]})
        return {"ok": True, "id": preset_id, "enabled": entry["enabled"]}

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
        installed = config.data.get("mcp_servers") or {}
        if isinstance(installed, list):
            installed = {item.get("id", str(i)): item for i, item in enumerate(installed) if isinstance(item, dict)}
        elif not isinstance(installed, dict):
            installed = {}
        if KB_NAME not in installed:
            installed[KB_NAME] = {
                "url": f"http://127.0.0.1:8005/{KB_NAME}/mcp",
                "name": KB_LABEL,
                "enabled": True,
                "api_key": None,
                "requires_api_key": False,
                "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            config.data["mcp_servers"] = installed
            config._save()
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
        try:
            raw = urllib.request.urlopen(urllib.request.Request(f"{hub_url}/"), timeout=10).read().decode()
            hub_info = _json.loads(raw)
        except Exception as e:
            return {"ok": False, "error": f"Cannot connect to hub: {e}"}

        mcp_names = hub_info.get("mcps") or []
        mcp_details = hub_info.get("mcp_details") or []
        # Build a lookup for labels/descriptions
        detail_map = {d["id"]: d for d in mcp_details}
        installed = config.data.get("mcp_servers") or {}
        if isinstance(installed, list):
            installed = {item.get("id", str(i)): item for i, item in enumerate(installed) if isinstance(item, dict)}
        elif not isinstance(installed, dict):
            installed = {}
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
        # Auto-update URLs for already installed MCPs
        updated = 0
        for name in mcp_names:
            url = f"{hub_url}/{name}/mcp"
            if name in installed:
                old_url = installed[name].get("url", "")
                if old_url != url:
                    installed[name]["url"] = url
                    updated += 1
        if updated > 0:
            config.data["mcp_servers"] = installed
            config._save()
            logger.info({"event": "mcp_urls_updated", "count": updated, "hub_url": hub_url})

        return {"ok": True, "hub_name": hub_info.get("name", ""), "mcps": mcps, "urls_updated": updated}

    return router
