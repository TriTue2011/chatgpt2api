"""Warm HTTP clients must not launch Chromium or leave refresh loops behind."""
import asyncio
from unittest.mock import AsyncMock, Mock

from api import gemini_web as gma


def test_live_http_client_reuses_cookie_identity_without_reopening_browser(monkeypatch):
    cookies = {"__Secure-1PSID": "A" * 40, "__Secure-1PSIDTS": "seed"}
    monkeypatch.setattr(gma, "_cookie_cache", {"workspace_a": (0, cookies)})
    client = Mock(_running=True)
    monkeypatch.setattr(gma, "_clients", {"A" * 32: client})
    fetch = Mock(side_effect=AssertionError("Must not launch solver for a warm client"))
    monkeypatch.setattr(gma.requests, "get", fetch)
    assert gma._fetch_cookies_from_solver("workspace_a") == cookies
    fetch.assert_not_called()


def test_drop_closes_only_the_failed_client_and_refresh_task(monkeypatch):
    first, second = Mock(), Mock()
    first.close = AsyncMock()
    second.close = AsyncMock()
    monkeypatch.setattr(gma, "_clients", {"A" * 32: first, "B" * 32: second})
    monkeypatch.setattr(gma, "_init_locks", {})
    monkeypatch.setattr(gma, "_cookie_cache", {"workspace_a": (0, {"__Secure-1PSID": "A" * 40}), "workspace_b": (0, {"__Secure-1PSID": "B" * 40})})
    monkeypatch.setattr(gma, "_run", lambda coro, **kwargs: asyncio.run(coro))
    gma._drop_client("A" * 40, "workspace_a")
    first.close.assert_awaited_once()
    second.close.assert_not_called()
    assert "B" * 32 in gma._clients and "workspace_b" in gma._cookie_cache


def test_cookie_warmer_only_invokes_http_client_warmup(monkeypatch):
    from services import web_prewarmer
    warm = Mock(return_value=2)
    monkeypatch.setattr(gma, "prewarm_clients", warm)
    asyncio.run(web_prewarmer._warm_pass())
    warm.assert_called_once()
