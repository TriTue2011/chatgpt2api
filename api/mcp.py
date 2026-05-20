"""MCP Presets API — list, install, uninstall, toggle MCP servers."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
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
        if not isinstance(installed, dict):
            installed = {}

        result = []
        for p in PRESETS:
            info = installed.get(p.id) or {}
            result.append({
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "url": p.url,
                "category": p.category,
                "icon": p.icon,
                "homepage": p.homepage,
                "requires_api_key": p.requires_api_key,
                "api_key_help": p.api_key_help,
                "tags": p.tags,
                "installed": p.id in installed,
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
        if preset is None:
            raise HTTPException(status_code=404, detail=f"Unknown preset: {body.id}")

        installed = config.data.get("mcp_servers") or {}
        if not isinstance(installed, dict):
            installed = {}

        url = body.url_override or preset.url
        installed[preset.id] = {
            "url": url,
            "name": preset.name,
            "enabled": True,
            "api_key": body.api_key or None,
            "requires_api_key": preset.requires_api_key,
            "installed_at": None,  # Will be set below
        }
        import time
        installed[preset.id]["installed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        config.data["mcp_servers"] = installed
        config._save()
        logger.info({"event": "mcp_installed", "id": preset.id, "url": url})
        return {"ok": True, "id": preset.id}

    @router.post("/api/mcp/uninstall/{preset_id}")
    async def uninstall_preset(
        preset_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        installed = config.data.get("mcp_servers") or {}
        if not isinstance(installed, dict):
            installed = {}

        if preset_id in installed:
            del installed[preset_id]
            config.data["mcp_servers"] = installed
            config._save()
            logger.info({"event": "mcp_uninstalled", "id": preset_id})
        return {"ok": True, "id": preset_id}

    @router.post("/api/mcp/toggle/{preset_id}")
    async def toggle_preset(
        preset_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        installed = config.data.get("mcp_servers") or {}
        if not isinstance(installed, dict):
            installed = {}

        entry = installed.get(preset_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Not installed: {preset_id}")

        entry["enabled"] = not bool(entry.get("enabled", True))
        config.data["mcp_servers"] = installed
        config._save()
        logger.info({"event": "mcp_toggled", "id": preset_id, "enabled": entry["enabled"]})
        return {"ok": True, "id": preset_id, "enabled": entry["enabled"]}

    @router.post("/api/mcp/discover")
    async def discover_hub(request: dict, authorization: str | None = Header(default=None)):
        """Discover MCPs from a hub URL. Body: {hub_url: 'http://...'}"""
        require_admin(authorization)
        import urllib.request, json as _json
        hub_url = str((request or {}).get("hub_url", "")).strip().rstrip("/")
        if not hub_url:
            raise HTTPException(status_code=400, detail="hub_url is required")
        try:
            raw = urllib.request.urlopen(urllib.request.Request(f"{hub_url}/"), timeout=10).read().decode()
            hub_info = _json.loads(raw)
        except Exception as e:
            return {"ok": False, "error": f"Cannot connect to hub: {e}"}

        mcp_names = hub_info.get("mcps") or []
        installed = config.data.get("mcp_servers") or {}
        if not isinstance(installed, dict):
            installed = {}
        mcps = []
        for name in mcp_names:
            url = f"{hub_url}/{name}/mcp"
            info = installed.get(name) or {}
            mcps.append({"id": name, "name": name, "url": url,
                         "installed": name in installed,
                         "enabled": bool(info.get("enabled", True))})
        return {"ok": True, "hub_name": hub_info.get("name", ""), "mcps": mcps}

    return router
