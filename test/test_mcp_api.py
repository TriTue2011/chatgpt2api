from __future__ import annotations

import os
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from api import mcp as mcp_api  # noqa: E402


class _Config:
    def __init__(self) -> None:
        self.data: dict = {}

    def mutate(self, change):
        return change(self.data)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(mcp_api.create_router())
    return TestClient(app)


def test_custom_mcp_validation_install_and_listing_never_echo_secrets() -> None:
    cfg = _Config()
    report = {
        "ok": True,
        "name": "n8n-instance",
        "version": "2.33.0",
        "protocol_version": "2026-07-28",
        "transport": "streamable_http",
        "tools": [{"name": "execute_workflow", "description": "Run it"}],
        "capabilities": {"tools": {}},
        "errors": [],
    }
    body = {
        "url": "https://n8n.example.com/mcp-server/http",
        "api_key": "top-secret-token",
        "headers": {"X-N8N-Project": "secret-project"},
        "transport": "auto",
    }
    with mock.patch.object(mcp_api, "config", cfg), \
         mock.patch.object(mcp_api, "require_admin", lambda _auth: {"role": "admin"}), \
         mock.patch("services.mcp_client.validate_mcp_server", return_value=report):
        client = _client()
        validated = client.post("/api/mcp/validate", json=body).json()
        installed = client.post("/api/mcp/install", json={
            "id": "ext_n8n",
            "name": "My n8n",
            "description": "Production workflows",
            **body,
            "url_override": body["url"],
        }).json()
        listed = client.get("/api/mcp/custom").json()

    assert validated["ok"] is True
    assert installed == {"ok": True, "id": "ext_n8n"}
    assert listed["mcps"][0]["header_names"] == ["X-N8N-Project"]
    rendered = str(listed)
    assert "top-secret-token" not in rendered
    assert "secret-project" not in rendered


def test_custom_mcp_rejects_non_http_urls_and_protocol_owned_headers() -> None:
    cfg = _Config()
    with mock.patch.object(mcp_api, "config", cfg), \
         mock.patch.object(mcp_api, "require_admin", lambda _auth: {"role": "admin"}):
        client = _client()
        bad_url = client.post("/api/mcp/validate", json={"url": "file:///etc/passwd"})
        bad_header = client.post("/api/mcp/validate", json={
            "url": "https://mcp.example.com/mcp",
            "headers": {"Host": "attacker.invalid"},
        })

    assert bad_url.status_code == 400
    assert bad_header.status_code == 400
