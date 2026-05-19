"""HTTP API for managing MCP servers from the dashboard UI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from api.support import require_admin
from services.mcp.client import MCPServerConfig
from services.mcp.presets import get_preset, list_presets
from services.mcp.registry import mcp_registry


class MCPServerBody(BaseModel):
    """Add/update payload. `id` is optional on create — server will assign."""

    id: str = ""
    name: str = ""
    url: str
    api_key: str = ""
    enabled: bool = True
    transport: str = "http"
    headers: dict[str, str] = Field(default_factory=dict)


def _serialize(cfg: MCPServerConfig) -> dict[str, Any]:
    return {
        "id": cfg.id,
        "name": cfg.name,
        "url": cfg.url,
        # Mask the api_key in list responses to avoid leaking it back to UI logs.
        "api_key_set": bool(cfg.api_key),
        "enabled": cfg.enabled,
        "transport": cfg.transport,
        "headers": dict(cfg.headers or {}),
    }


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/mcp/servers")
    async def list_servers(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        servers = mcp_registry.list_servers()
        return {"servers": [_serialize(s) for s in servers]}

    @router.post("/api/mcp/servers")
    async def add_or_update_server(
        body: MCPServerBody,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        if not body.url.strip():
            raise HTTPException(status_code=400, detail="url is required")
        cfg = MCPServerConfig(
            id=body.id.strip(),
            name=body.name.strip() or body.url,
            url=body.url.strip(),
            api_key=body.api_key,
            enabled=body.enabled,
            transport=body.transport or "http",
            headers=dict(body.headers or {}),
        )
        saved = mcp_registry.add_or_update(cfg)
        return {"server": _serialize(saved)}

    @router.delete("/api/mcp/servers/{server_id}")
    async def delete_server(
        server_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        ok = mcp_registry.remove(server_id)
        if not ok:
            raise HTTPException(status_code=404, detail="server not found")
        return {"deleted": server_id}

    @router.post("/api/mcp/servers/{server_id}/test")
    async def test_server(
        server_id: str,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        ok, message = mcp_registry.test(server_id)
        return {"ok": ok, "message": message}

    @router.get("/api/mcp/tools")
    async def list_tools(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        items = []
        for tool, prefixed_name in mcp_registry.collect_tools():
            items.append(
                {
                    "server_id": tool.server_id,
                    "name": tool.name,
                    "prefixed_name": prefixed_name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
            )
        return {"tools": items}

    @router.get("/api/mcp/presets")
    async def get_presets(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"presets": list_presets()}

    @router.post("/api/mcp/presets/{preset_id}/install")
    async def install_preset(
        preset_id: str,
        body: dict[str, Any] | None = None,
        authorization: str | None = Header(default=None),
    ):
        require_admin(authorization)
        preset = get_preset(preset_id)
        if not preset:
            raise HTTPException(status_code=404, detail="preset not found")
        api_key = ""
        if isinstance(body, dict):
            api_key = str(body.get("api_key") or "")
        if preset.requires_api_key and not api_key:
            raise HTTPException(status_code=400, detail=f"api_key required: {preset.api_key_help}")
        cfg = MCPServerConfig(
            id="",
            name=preset.name,
            url=preset.url,
            api_key=api_key,
            enabled=True,
            transport=preset.transport,
        )
        try:
            saved = mcp_registry.add_or_update(cfg)
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            raise HTTPException(status_code=500, detail=f"install failed: {exc} | {tb[-500:]}")
        return {"server": _serialize(saved)}

    return router
