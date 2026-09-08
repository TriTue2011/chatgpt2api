"""Admin OAuth lifecycle; the provider callback uses a one-use browser-bound state."""
from __future__ import annotations

import hashlib
import html
import os
import re
import secrets

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import Field

from api.mcp import InstallRequest, _normalize_mcp, _validated_connection
from api.support import require_admin
from services.config import config
from services.mcp_oauth import CALLBACK_PATH, METADATA_PATH, FLOW_TTL, OAuthError, get_manager, public_base


class OAuthStart(InstallRequest):
    client_id: str = Field(default="", max_length=2048)
    client_secret: str = Field(default="", max_length=8192)
    scope: str | None = Field(default=None, max_length=2048)
    preserve_headers: bool = False


def _cookie(state):
    return "mcp_oauth_" + hashlib.sha256(state.encode()).hexdigest()[:24]


def _invalidate():
    from services.mcp_client import invalidate_tools_cache
    invalidate_tools_cache()


def _entry(server_id):
    entry = _normalize_mcp(config.data.get("mcp_servers")).get(server_id)
    if not entry or not entry.get("oauth_id"):
        raise HTTPException(404, "Không tìm thấy MCP OAuth.")
    return entry


def create_router():
    router = APIRouter()

    @router.get(METADATA_PATH)
    def client_metadata():
        try:
            base = public_base(os.environ.get("MCP_OAUTH_PUBLIC_URL", ""))
        except OAuthError:
            raise HTTPException(503, "Cần cấu hình MCP_OAUTH_PUBLIC_URL.") from None
        return {"client_id": base + METADATA_PATH, "client_name": "chatgpt2api",
                "redirect_uris": [base + CALLBACK_PATH], "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"], "token_endpoint_auth_method": "none"}

    @router.post("/api/mcp/oauth/start")
    async def start(body: OAuthStart, request: Request, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        url, headers, _ = _validated_connection(body)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", body.id) or len(body.name) > 120 or len(body.description) > 1000:
            raise HTTPException(400, "ID, tên hoặc mô tả MCP không hợp lệ.")
        if body.api_key or any(k.lower() == "authorization" for k in headers):
            raise HTTPException(400, "OAuth tự quản lý Authorization; hãy bỏ Bearer/API key và header Authorization.")
        previous = _normalize_mcp(config.data.get("mcp_servers")).get(body.id, {})
        if previous and previous.get("url") != url:
            raise HTTPException(409, "ID MCP đã dùng cho URL khác; hãy chọn tên khác.")
        if body.preserve_headers and previous:
            _, headers, _ = _validated_connection(OAuthStart(id=body.id, url=url, headers=previous.get("headers") or {}))
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
        binding = secrets.token_urlsafe(32)
        try:
            configured_base = os.environ.get("MCP_OAUTH_PUBLIC_URL", "")
            base = public_base(configured_base or str(request.base_url))
            manager = get_manager()
            flow = await run_in_threadpool(manager.begin, url, base + CALLBACK_PATH, binding,
                client_id=body.client_id.strip(), client_secret=body.client_secret,
                reuse_oauth_id=previous.get("oauth_id", ""),
                scope=body.scope, client_metadata_url=base + METADATA_PATH if configured_base and base.startswith("https://") else "")
        except OAuthError as exc:
            raise HTTPException(400, str(exc)) from None
        # Compare inside the config lock so two starts cannot orphan a live flow.
        def install(data):
            installed = _normalize_mcp(data.get("mcp_servers"))
            if installed.get(body.id, {}) != previous:
                raise HTTPException(409, "MCP vừa thay đổi; hãy thử lại.")
            installed[body.id] = {**previous, "name": body.name.strip() or body.id,
                "description": body.description.strip(), "url": url, "enabled": True,
                "custom": True, "auth_type": "oauth", "oauth_id": flow["oauth_id"],
                "api_key": None, "headers": headers, "transport": "streamable_http"}
            data["mcp_servers"] = installed
        try:
            config.mutate(install)
        except Exception:
            await run_in_threadpool(manager.disconnect, flow["oauth_id"], forget_client=True)
            raise
        if previous.get("oauth_id"):
            await run_in_threadpool(manager.disconnect, previous["oauth_id"], forget_client=True)
        _invalidate()
        response = JSONResponse({"ok": True, "id": body.id, "authorization_url": flow["authorization_url"],
                                 "redirect_uri": base + CALLBACK_PATH}, headers={"Cache-Control": "no-store"})
        response.set_cookie(_cookie(flow["state"]), binding, max_age=FLOW_TTL,
                            secure=base.startswith("https://"), httponly=True, samesite="lax", path=CALLBACK_PATH)
        return response

    @router.get(CALLBACK_PATH)
    async def callback(request: Request):
        state = request.query_params.get("state", "")
        try:
            if any(len(request.query_params.getlist(k)) > 1 for k in ("state", "code", "error", "iss")):
                raise OAuthError("Phản hồi đăng nhập không hợp lệ.")
            manager = get_manager()
            oauth_id = await run_in_threadpool(manager.store.find_state, state)
            if not oauth_id or not any(info.get("oauth_id") == oauth_id for info in _normalize_mcp(config.data.get("mcp_servers")).values()):
                raise OAuthError("Phiên đăng nhập đã bị hủy hoặc MCP đã bị xóa.")
            await run_in_threadpool(manager.finish, state, request.cookies.get(_cookie(state), ""),
                code=request.query_params.get("code", ""), error=request.query_params.get("error", ""),
                issuer=request.query_params.get("iss", ""))
            _invalidate()
            message, status = "Đã kết nối tài khoản. Bạn có thể đóng cửa sổ này và quay lại trang MCP.", 200
        except OAuthError as exc:
            message, status = str(exc), 400
        response = HTMLResponse('<!doctype html><html lang="vi"><meta charset="utf-8"><title>Kết nối MCP</title>'
                                '<body><h1>Kết nối MCP</h1><p>' + html.escape(message) + '</p></body></html>',
                                status_code=status, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"})
        response.delete_cookie(_cookie(state), path=CALLBACK_PATH)
        return response

    @router.post("/api/mcp/oauth/{server_id}/disconnect")
    async def disconnect(server_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        result = await run_in_threadpool(get_manager().disconnect, _entry(server_id)["oauth_id"])
        _invalidate()
        return result

    @router.post("/api/mcp/oauth/{server_id}/validate")
    async def validate(server_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        entry = _entry(server_id)
        from services.mcp_client import validate_mcp_server
        return await run_in_threadpool(validate_mcp_server, entry["url"], headers=entry.get("headers"),
                                      transport="streamable_http", oauth_id=entry["oauth_id"])

    return router
