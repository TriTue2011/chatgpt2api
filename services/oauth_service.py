"""
OAuth Service — PKCE login flow for Codex (chat) and Google (image).
Port from 9router oauth/ directory.

Codex OAuth:
- Client ID: app_EMoamEEZ73f0CkXaXp7hrann
- Auth: https://auth.openai.com/oauth/authorize
- Token: https://auth.openai.com/oauth/token

Google OAuth (chatgpt.com):
- Direct session token from chatgpt.com/api/auth/session
- User logs in via browser, copy token
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import urllib.parse
from typing import Any

from curl_cffi import requests

from services.account_service import account_service
from utils.log import logger

# Codex OAuth config (from 9router)
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_AUTH_URL = "https://auth.openai.com/oauth/authorize"
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_REDIRECT_URI = "http://localhost:3030/api/oauth/codex/callback"
CODEX_SCOPE = "openid profile email offline_access model.request model.read"


def generate_pkce() -> dict[str, str]:
    """Generate PKCE code verifier and challenge."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    state = secrets.token_hex(16)
    return {
        "code_verifier": code_verifier,
        "code_challenge": code_challenge,
        "state": state,
    }


def get_codex_auth_url(base_url: str = "http://localhost:3030") -> dict[str, str]:
    """Generate Codex OAuth authorization URL with PKCE.

    IMPORTANT: redirect_uri MUST be localhost for Codex CLI OAuth.
    OpenAI only trusts localhost redirects — remote IPs require phone verification.
    If chatgpt2api is not on your local machine, use the manual exchange flow:
    1. Open auth_url in browser
    2. Authorize
    3. Copy the full redirect URL (localhost:3030/auth/callback?code=...)
    4. POST that URL to /api/oauth/codex/exchange
    """
    pkce = generate_pkce()
    redirect_uri = "http://localhost:1455/auth/callback"

    params = {
        "response_type": "code",
        "client_id": CODEX_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email offline_access",
        "code_challenge": pkce["code_challenge"],
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": "codex_cli_rs",
        "state": pkce["state"],
    }

    # Build query string manually to use %20 instead of + (like 9router does)
    query_parts = []
    for k, v in params.items():
        encoded_key = urllib.parse.quote(str(k), safe="")
        encoded_val = urllib.parse.quote(str(v), safe="")
        query_parts.append(f"{encoded_key}={encoded_val}")
    query_string = "&".join(query_parts)

    auth_url = f"{CODEX_AUTH_URL}?{query_string}"

    # Store PKCE data temporarily (in-memory, short-lived)
    _pending_auths[pkce["state"]] = {
        "code_verifier": pkce["code_verifier"],
        "redirect_uri": redirect_uri,
    }

    return {
        "auth_url": auth_url,
        "state": pkce["state"],
    }


# In-memory store for pending OAuth flows (state → {code_verifier, redirect_uri})
_pending_auths: dict[str, dict[str, str]] = {}


def exchange_codex_code(code: str, state: str) -> dict[str, Any]:
    """Exchange authorization code for Codex OAuth token."""
    pending = _pending_auths.pop(state, None)
    if not pending:
        raise ValueError("Invalid or expired OAuth state. Please try again.")

    body = {
        "client_id": CODEX_CLIENT_ID,
        "code": code,
        "redirect_uri": pending["redirect_uri"],
        "code_verifier": pending["code_verifier"],
        "grant_type": "authorization_code",
    }

    resp = requests.post(
        CODEX_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
        timeout=30,
        impersonate="chrome110",
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {resp.status_code} {resp.text[:200]}")

    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")

    if access_token:
        # Add to account pool with default quota for both chat and images
        account_service.add_accounts([access_token])
        account_service.update_account(access_token, {
            "image_quota_unknown": True,
            "quota": 10,
            "status": "active",
        })

    return {
        "ok": True,
        "message": "Đăng nhập Codex OAuth thành công! Token đã được thêm.",
        "access_token_prefix": access_token[:20] + "..." if access_token else "",
        "has_refresh_token": bool(refresh_token),
    }


def get_chatgpt_session_url() -> str:
    """Return URL for getting chatgpt.com session token."""
    return "https://chatgpt.com/api/auth/session"


# ===== Token từ backup 9router =====

def detect_token_type(access_token: str) -> str:
    """Detect token type from JWT claims.

    Returns: "codex" | "google" | "unknown"
    """
    try:
        parts = access_token.split(".")
        if len(parts) < 2:
            return "unknown"
        payload = parts[1]
        payload += "=" * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))

        client_id = decoded.get("client_id", "")
        sub = decoded.get("sub", "")

        if client_id == CODEX_CLIENT_ID:
            return "codex"
        if sub.startswith("google-oauth2"):
            return "google"
        if "chatgpt_account_id" in str(decoded.get("https://api.openai.com/auth", {})):
            return "codex"
        return "unknown"
    except Exception:
        return "unknown"
