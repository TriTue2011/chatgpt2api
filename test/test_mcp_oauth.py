"""OAuth contract tests: use a fake provider, real encrypted on-disk state."""
from __future__ import annotations

import base64
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import pytest

from services.mcp_oauth import OAuthError, OAuthManager, OAuthStore

pytestmark = pytest.mark.integration
RESOURCE = "https://mcp.example.com/mcp"
ISSUER = "https://login.example.com"
CALLBACK = "https://gateway.example.com/api/mcp/oauth/callback"


class Provider:
    def __init__(self):
        self.calls = []
        self.refreshes = 0
        self.fail_refresh = False
        self.metadata = {
            "issuer": ISSUER,
            "authorization_endpoint": ISSUER + "/authorize",
            "token_endpoint": ISSUER + "/token",
            "registration_endpoint": ISSUER + "/register",
            "revocation_endpoint": ISSUER + "/revoke",
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
        }

    def request(self, url, *, method="GET", body=None, headers=None):
        self.calls.append((url, method, body, headers))
        if url == RESOURCE:
            return 401, {"www-authenticate": 'Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource", scope="search"'}, {}
        if "oauth-protected-resource" in url:
            return 200, {}, {"resource": RESOURCE, "authorization_servers": [ISSUER], "scopes_supported": ["search", "write"]}
        if "oauth-authorization-server" in url:
            return 200, {}, self.metadata
        if url.endswith("/register"):
            return 201, {}, {"client_id": "registered-client", "token_endpoint_auth_method": "none"}
        if url.endswith("/token"):
            if body.get("grant_type") == "refresh_token":
                self.refreshes += 1
                if self.fail_refresh:
                    return 400, {}, {"error": "invalid_grant", "error_description": "secret-refresh must never leak"}
                return 200, {}, {"access_token": "refreshed-access", "refresh_token": "rotated-refresh", "token_type": "Bearer", "expires_in": 3600}
            return 200, {}, {"access_token": "secret-access", "refresh_token": "secret-refresh", "token_type": "Bearer", "expires_in": 3600, "scope": "search"}
        if url.endswith("/revoke"):
            return 200, {}, {}
        return 404, {}, {}


@pytest.fixture
def setup(tmp_path):
    provider = Provider()
    store = OAuthStore(tmp_path)
    clock = [1000.0]
    manager = OAuthManager(store, provider, now=lambda: clock[0])
    return manager, provider, store, clock


def connect(manager):
    start = manager.begin(RESOURCE, CALLBACK, "browser-proof")
    manager.finish(start["state"], "browser-proof", code="authorization-code", issuer=ISSUER)
    return start


def test_pkce_resource_binding_and_encrypted_restart(setup, tmp_path):
    manager, provider, store, clock = setup
    start = connect(manager)
    params = parse_qs(urlsplit(start["authorization_url"]).query)
    token_request = next(c[2] for c in provider.calls if c[0].endswith("/token"))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(token_request["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == [challenge]
    assert params["code_challenge_method"] == ["S256"]
    assert params["resource"] == [RESOURCE] and token_request["resource"] == RESOURCE
    assert params["scope"] == ["search"]  # Do not silently request every advertised scope.
    assert manager.token(start["oauth_id"], RESOURCE) == "secret-access"
    with pytest.raises(OAuthError):
        manager.token(start["oauth_id"], "https://other.example.com/mcp")
    public = json.dumps(manager.status(start["oauth_id"]))
    assert "secret-access" not in public and "secret-refresh" not in public
    for path in tmp_path.glob("*.sqlite*"):
        assert b"secret-access" not in path.read_bytes()
        assert b"secret-refresh" not in path.read_bytes()
    restarted = OAuthManager(OAuthStore(tmp_path), provider, now=lambda: clock[0])
    assert restarted.token(start["oauth_id"], RESOURCE) == "secret-access"


def test_callback_browser_binding_one_use_and_expiry(setup):
    manager, _, _, clock = setup
    start = manager.begin(RESOURCE, CALLBACK, "browser-proof")
    with pytest.raises(OAuthError):
        manager.finish(start["state"], "another-browser", code="code")
    manager.finish(start["state"], "browser-proof", code="code")
    with pytest.raises(OAuthError):
        manager.finish(start["state"], "browser-proof", code="code")
    expired = manager.begin(RESOURCE, CALLBACK, "browser-proof")
    clock[0] += 601
    with pytest.raises(OAuthError):
        manager.finish(expired["state"], "browser-proof", code="code")
    assert manager.status(expired["oauth_id"])["status"] == "disconnected"


def test_refresh_rotation_serialized_and_disconnect_removes_credentials(setup):
    manager, provider, _, clock = setup
    start = connect(manager)
    clock[0] += 3601
    with ThreadPoolExecutor(max_workers=5) as pool:
        tokens = list(pool.map(lambda _: manager.token(start["oauth_id"], RESOURCE), range(5)))
    assert tokens == ["refreshed-access"] * 5 and provider.refreshes == 1
    manager.disconnect(start["oauth_id"])
    with pytest.raises(OAuthError):
        manager.token(start["oauth_id"], RESOURCE)
    assert manager.status(start["oauth_id"])["status"] == "disconnected"


def test_revoked_refresh_requires_reconnect_without_leaking_provider_error(setup):
    manager, provider, _, clock = setup
    start = connect(manager)
    clock[0] += 3601
    provider.fail_refresh = True
    with pytest.raises(OAuthError) as error:
        manager.token(start["oauth_id"], RESOURCE)
    assert "secret-refresh" not in str(error.value)
    assert manager.status(start["oauth_id"])["status"] == "reauth_required"


def test_rejected_token_refreshes_once_and_reuses_rotated_token(setup):
    manager, provider, _, _ = setup
    start = connect(manager)
    assert manager.token(start["oauth_id"], RESOURCE, rejected_token="secret-access") == "refreshed-access"
    assert manager.token(start["oauth_id"], RESOURCE, rejected_token="secret-access") == "refreshed-access"
    assert provider.refreshes == 1


def test_missing_pkce_and_issuer_mismatch_fail_closed(setup):
    manager, provider, _, _ = setup
    provider.metadata["code_challenge_methods_supported"] = ["plain"]
    with pytest.raises(OAuthError):
        manager.begin(RESOURCE, CALLBACK, "proof")
    provider.metadata["code_challenge_methods_supported"] = ["S256"]
    provider.metadata["issuer"] = "https://wrong.example.com"
    with pytest.raises(OAuthError):
        manager.begin(RESOURCE, CALLBACK, "proof")


def test_denial_and_wrong_callback_issuer_never_exchange_code(setup):
    manager, provider, _, _ = setup
    start = manager.begin(RESOURCE, CALLBACK, "proof")
    with pytest.raises(OAuthError):
        manager.finish(start["state"], "proof", code="code", issuer="https://wrong.example.com")
    denied = manager.begin(RESOURCE, CALLBACK, "proof")
    with pytest.raises(OAuthError):
        manager.finish(denied["state"], "proof", error="access_denied")
    assert not any(c[0].endswith("/token") for c in provider.calls)


def test_pre_registered_client_and_metadata_document_registration(setup):
    manager, provider, _, _ = setup
    start = manager.begin(RESOURCE, CALLBACK, "proof", client_id="my-client", client_secret="my-secret")
    manager.finish(start["state"], "proof", code="code")
    assert not any(c[0].endswith("/register") for c in provider.calls)
    request = next(c for c in provider.calls if c[0].endswith("/token"))
    assert request[3]["Authorization"].startswith("Basic ")
    provider.metadata["client_id_metadata_document_supported"] = True
    start = manager.begin(RESOURCE, CALLBACK, "proof", client_metadata_url="https://gateway.example.com/api/mcp/oauth/client-metadata")
    assert parse_qs(urlsplit(start["authorization_url"]).query)["client_id"] == ["https://gateway.example.com/api/mcp/oauth/client-metadata"]


def test_issuer_required_when_advertised_and_malformed_metadata_safe(setup):
    manager, provider, _, _ = setup
    provider.metadata["authorization_response_iss_parameter_supported"] = True
    start = manager.begin(RESOURCE, CALLBACK, "proof")
    with pytest.raises(OAuthError):
        manager.finish(start["state"], "proof", code="code")
    assert not any(c[0].endswith("/token") for c in provider.calls)
    for invalid in (None, 42, "S256", ["S256", 42]):
        provider.metadata["code_challenge_methods_supported"] = invalid
        with pytest.raises(OAuthError):
            manager.begin(RESOURCE, CALLBACK, "proof")


def test_scope_fallback_and_reconnect_reuses_private_registration(setup):
    manager, provider, store, _ = setup
    original = provider.request
    def no_challenge_scope(url, **kwargs):
        status, headers, body = original(url, **kwargs)
        if url == RESOURCE:
            headers = {}
        return status, headers, body
    provider.request = no_challenge_scope
    start = manager.begin(RESOURCE, CALLBACK, "proof", client_id="private-client", client_secret="private-secret")
    assert parse_qs(urlsplit(start["authorization_url"]).query)["scope"] == ["search write"]
    manager.finish(start["state"], "proof", code="code")
    manager.disconnect(start["oauth_id"])
    old = store.get(start["oauth_id"])
    assert not any(old.get(k) for k in ("access_token", "refresh_token", "verifier", "browser_hash", "state_hash"))
    again = manager.begin(RESOURCE, CALLBACK, "proof", reuse_oauth_id=start["oauth_id"])
    assert parse_qs(urlsplit(again["authorization_url"]).query)["client_id"] == ["private-client"]
    assert not any(c[0].endswith("/register") for c in provider.calls)


def test_oauth_http_blocks_private_endpoints_and_dns_before_network(monkeypatch):
    from services.mcp_oauth import OAuthHTTP
    from services import net_guard
    transport = OAuthHTTP()
    for url in ("http://public.example.com/token", "https://127.0.0.1/token", "https://169.254.169.254/token", "https://user:secret@public.example.com/token"):
        with pytest.raises(OAuthError):
            transport.request(url)
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", lambda *args: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(OAuthError):
        transport.request("https://rebind.example.com/token")


def test_reconnect_keeps_registered_client_auth_method(setup):
    manager, provider, _, _ = setup
    provider.metadata["token_endpoint_auth_methods_supported"] = ["none", "client_secret_basic", "client_secret_post"]
    original = provider.request
    def registered_post(url, **kwargs):
        if url.endswith("/register"):
            return 201, {}, {"client_id": "post-client", "client_secret": "post-secret", "token_endpoint_auth_method": "client_secret_post"}
        return original(url, **kwargs)
    provider.request = registered_post
    first = connect(manager)
    second = manager.begin(RESOURCE, CALLBACK, "proof", reuse_oauth_id=first["oauth_id"])
    manager.finish(second["state"], "proof", code="code")
    token_request = [c for c in provider.calls if c[0].endswith("/token")][-1]
    assert token_request[2]["client_secret"] == "post-secret"
    assert "Authorization" not in token_request[3]


def test_canonical_resource_origin_is_allowed_but_token_stays_endpoint_bound(setup):
    manager, provider, _, _ = setup
    original = provider.request
    audience = ["https://mcp.example.com"]
    def resource_document(url, **kwargs):
        status, headers, body = original(url, **kwargs)
        if "oauth-protected-resource" in url:
            body["resource"] = audience[0]
        return status, headers, body
    provider.request = resource_document
    first = connect(manager)
    assert parse_qs(urlsplit(first["authorization_url"]).query)["resource"] == [audience[0]]
    assert manager.token(first["oauth_id"], RESOURCE) == "secret-access"
    with pytest.raises(OAuthError):
        manager.token(first["oauth_id"], audience[0] + "/other")
    for invalid in ("https://other.example.com", "https://mcp.example.com/other", "https://mcp.example.com:8443", "https://mcp.example.com?tenant=other"):
        audience[0] = invalid
        with pytest.raises(OAuthError):
            manager.begin(RESOURCE, CALLBACK, "proof")
