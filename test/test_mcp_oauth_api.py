from __future__ import annotations

import json
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api import mcp as mcp_api
from services import mcp_oauth
from test.test_mcp_oauth import Provider, RESOURCE, ISSUER


class Config:
    def __init__(self):
        self.data = {"mcp_servers": {"existing": {"url": "http://127.0.0.1:8005/mcp", "name": "Existing"}}}

    def mutate(self, fn):
        return fn(self.data)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from api import mcp_oauth as routes
    cfg = Config()
    provider = Provider()
    manager = mcp_oauth.OAuthManager(mcp_oauth.OAuthStore(tmp_path), provider)
    monkeypatch.setattr(mcp_api, "config", cfg)
    monkeypatch.setattr(routes, "config", cfg)
    monkeypatch.setattr(mcp_oauth, "_manager", manager)
    monkeypatch.setenv("MCP_OAUTH_PUBLIC_URL", "https://gateway.example.com")
    app = FastAPI()
    app.include_router(mcp_api.create_router())
    client = TestClient(app, base_url="https://gateway.example.com")
    return client, cfg, provider, manager


def test_admin_start_cookie_callback_listing_and_disconnect(setup):
    client, cfg, provider, manager = setup
    body = {"id": "ext_test", "name": "Test OAuth", "url": RESOURCE}
    assert client.post("/api/mcp/oauth/start", json=body).status_code == 401
    with mock.patch("api.mcp_oauth.require_admin", return_value={"id": "admin"}), mock.patch.object(mcp_api, "require_admin"):
        response = client.post("/api/mcp/oauth/start", json=body)
        assert response.status_code == 200, response.text
        assert "HttpOnly" in response.headers["set-cookie"] and "Secure" in response.headers["set-cookie"]
        data = response.json()
        from urllib.parse import parse_qs, urlsplit
        state = parse_qs(urlsplit(data["authorization_url"]).query)["state"][0]
        # No cookie => no login CSRF, even with a valid provider code/state.
        other = TestClient(client.app, base_url="https://gateway.example.com")
        assert other.get("/api/mcp/oauth/callback", params={"state": state, "code": "code"}).status_code == 400
        result = client.get("/api/mcp/oauth/callback", params={"state": state, "code": "code", "iss": ISSUER})
        assert result.status_code == 200
        assert result.headers["referrer-policy"] == "no-referrer"
        assert "no-store" in result.headers["cache-control"]
        assert "secret-access" not in result.text and "code" not in result.text
        listed = client.get("/api/mcp/custom").json()
        row = next(r for r in listed["mcps"] if r["id"] == "ext_test")
        assert row["oauth"]["status"] == "connected"
        assert row["auth_type"] == "oauth"
        assert "secret-" not in json.dumps(listed) and "secret-" not in json.dumps(cfg.data)
        assert client.post("/api/mcp/oauth/ext_test/disconnect").status_code == 200
        row = next(r for r in client.get("/api/mcp/custom").json()["mcps"] if r["id"] == "ext_test")
        assert row["oauth"]["status"] == "disconnected"
        assert "existing" in cfg.data["mcp_servers"]


def test_uninstall_cancels_pending_oauth_and_metadata_is_canonical(setup):
    client, cfg, _, manager = setup
    with mock.patch("api.mcp_oauth.require_admin"), mock.patch.object(mcp_api, "require_admin"):
        result = client.post("/api/mcp/oauth/start", json={"id": "ext_test", "name": "OAuth", "url": RESOURCE}).json()
        oauth_id = cfg.data["mcp_servers"]["ext_test"]["oauth_id"]
        client.post("/api/mcp/uninstall/ext_test")
        assert manager.status(oauth_id)["status"] == "disconnected"
    document = client.get("/api/mcp/oauth/client-metadata", headers={"Host": "attacker.invalid"}).json()
    assert document["client_id"] == "https://gateway.example.com/api/mcp/oauth/client-metadata"
    assert document["redirect_uris"] == ["https://gateway.example.com/api/mcp/oauth/callback"]


def test_reconnect_preserves_headers_and_registration_and_old_state_cannot_finish(setup):
    client, cfg, provider, manager = setup
    from urllib.parse import parse_qs, urlsplit
    with mock.patch("api.mcp_oauth.require_admin"), mock.patch.object(mcp_api, "require_admin"):
        body = {"id": "ext_test", "name": "OAuth", "url": RESOURCE, "client_id": "private-client", "client_secret": "private-secret", "headers": {"User-Agent": "custom-agent"}}
        first = client.post("/api/mcp/oauth/start", json=body).json()
        old_id = cfg.data["mcp_servers"]["ext_test"]["oauth_id"]
        second = client.post("/api/mcp/oauth/start", json={"id": "ext_test", "url": RESOURCE, "preserve_headers": True}).json()
        assert parse_qs(urlsplit(second["authorization_url"]).query)["client_id"] == ["private-client"]
        assert cfg.data["mcp_servers"]["ext_test"]["headers"] == {"User-Agent": "custom-agent"}
        assert "client_secret" not in manager.store.get(old_id)
        old_state = parse_qs(urlsplit(first["authorization_url"]).query)["state"][0]
        assert client.get("/api/mcp/oauth/callback", params={"state": old_state, "code": "code"}).status_code == 400
        state = parse_qs(urlsplit(second["authorization_url"]).query)["state"][0]
        assert client.get("/api/mcp/oauth/callback", params=[("state", state), ("state", "other"), ("code", "code")]).status_code == 400
        # Install manual auth destroys the OAuth flow and client secret.
        oauth_id = cfg.data["mcp_servers"]["ext_test"]["oauth_id"]
        client.post("/api/mcp/install", json={"id": "ext_test", "url_override": RESOURCE})
        assert "oauth_id" not in cfg.data["mcp_servers"]["ext_test"]
        assert manager.store.get(oauth_id) == {"status": "disconnected"}
