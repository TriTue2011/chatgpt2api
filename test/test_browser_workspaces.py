"""Workspace isolation: only explicit close may close a user-owned context."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from test._goi_captcha import nap

pytest.importorskip("patchright")
pytest.importorskip("pydantic_settings")


@pytest.fixture
def pool(tmp_path, monkeypatch):
    module = nap("browser_pool")
    monkeypatch.setattr(module.settings, "data_dir", tmp_path)
    pool = module.BrowserPool()
    pool.start = AsyncMock()
    async def open_context(profile, headless):
        directory = pool._profile_dir(profile)
        context = type("Context", (), {})()
        context.close = AsyncMock()
        context.pages = []
        context.directory = directory
        return context, None
    pool._open_context = open_context
    pool._is_alive = AsyncMock(return_value=True)
    return pool


def test_manual_workspace_survives_other_profile_and_background_cleanup(pool):
    async def run():
        first = await pool.get("workspace_a", headless=False, manual=True)
        (first.directory / "cookies").write_text("account-a")
        second = await pool.get("workspace_b", headless=False, manual=True)
        assert first is not second
        assert not await pool.close_profile("workspace_a", bo_qua_khi_dang_nhap=True)
        assert not await pool.close_profile("workspace_a")
        with pytest.raises(Exception, match="bận"):
            await pool.get("workspace_a", headless=True)
        with pytest.raises(HTTPException) as error:
            async with pool.page("workspace_a"):
                pytest.fail("Automation must not claim an open manual workspace")
        assert error.value.status_code == 429
        first.close.assert_not_called()
        await pool.close_profile("workspace_b", user_requested=True)
        second.close.assert_awaited_once()
        first.close.assert_not_called()
        await pool.close_profile("workspace_a", user_requested=True)
        reopened = await pool.get("workspace_a", headless=False, manual=True)
        assert (reopened.directory / "cookies").read_text() == "account-a"
    asyncio.run(run())


def test_workspace_api_allocates_unique_profiles_and_close_keeps_files(pool, tmp_path):
    routes = nap("workspaces")
    app = FastAPI()
    app.include_router(routes.create_router(pool, lambda: None))
    client = TestClient(app)
    first = client.post("/v1/workspaces", json={"name": "Same name"}).json()
    second = client.post("/v1/workspaces", json={"name": "Same name"}).json()
    assert first["profile"] != second["profile"]
    (pool._profile_dir(first["profile"]) / "cookies").write_text("private")
    response = client.post(f"/v1/workspaces/{first['profile']}/close")
    assert response.status_code == 200
    rows = client.get("/v1/workspaces").json()["workspaces"]
    assert len(rows) == 2
    assert "private" not in json.dumps(rows)
    assert (pool._profile_dir(first["profile"]) / "cookies").read_text() == "private"
    assert client.post("/v1/workspaces/missing/open", json={}).status_code == 404


def test_checkbox_uses_one_normal_click_only_in_recaptcha_frame():
    module = nap("workspaces")
    checkbox = type("Checkbox", (), {})()
    checkbox.is_visible = AsyncMock(return_value=True)
    checkbox.get_attribute = AsyncMock(return_value="false")
    checkbox.click = AsyncMock()
    checkbox.first = checkbox
    frame = type("Frame", (), {"url": "https://www.google.com/recaptcha/api2/anchor?k=test", "locator": lambda self, selector: checkbox})()
    page = type("Page", (), {"frames": [frame]})()
    result = asyncio.run(module.click_checkbox(page))
    assert result["status"] == "clicked"
    checkbox.click.assert_awaited_once()
    checkbox.click.reset_mock()
    frame.url = "https://www.google.com.attacker.invalid/recaptcha/api2/anchor"
    assert asyncio.run(module.click_checkbox(page))["status"] == "not_found"
    checkbox.click.assert_not_called()
    frame.url = "https://www.google.com/recaptcha/api2/anchor"
    checkbox.get_attribute = AsyncMock(return_value="true")
    assert asyncio.run(module.click_checkbox(page))["status"] == "already_checked"
    checkbox.click.assert_not_called()


def test_cookie_reader_closes_cold_context_but_preserves_manual_window(pool):
    async def run():
        original = pool._open_context
        opened = []
        async def open_context(profile, headless):
            ctx, page = await original(profile, headless)
            ctx.cookies = AsyncMock(return_value=[{"name": "session", "value": profile}])
            opened.append(ctx)
            return ctx, page
        pool._open_context = open_context
        pool._profile_dir("cold")
        assert await pool.read_cookies("missing", "https://claude.ai") == []
        assert not opened
        assert await pool.read_cookies("cold", "https://claude.ai") == [{"name": "session", "value": "cold"}]
        opened[0].close.assert_awaited_once()
        assert not pool.is_loaded("cold")
        manual = await pool.get("manual", headless=False, manual=True)
        await pool.read_cookies("manual", "https://claude.ai")
        manual.close.assert_not_called()
        assert pool.is_manual("manual")
        manual.cookies.side_effect = RuntimeError("read failed")
        with pytest.raises(RuntimeError):
            await pool.read_cookies("manual", "https://claude.ai")
        manual.close.assert_not_called()
        assert not (await pool._lock_for("manual")).locked()
    asyncio.run(run())


def test_claude_recovers_saved_cookie_after_restart_without_relogin(pool, monkeypatch):
    module = nap("claude_web_login")
    monkeypatch.setattr(module, "pool", pool)
    monkeypatch.setattr(module, "_sessions", {})
    pool.read_cookies = AsyncMock(return_value=[{"name": "sessionKey", "value": "stored-a"}])
    async def run():
        first = await module.get_saved_session("workspace_a")
        assert first.session_key == "stored-a" and first.state == "stored"
        assert await module.get_saved_session("workspace_a") is first
        pool.read_cookies.assert_awaited_once()
        pool.read_cookies.return_value = []
        assert await module.get_saved_session("workspace_b") is None
    asyncio.run(run())


def test_cleanup_waiting_for_lock_does_not_close_new_login(pool):
    async def run():
        context = await pool.get('workspace_a')
        lock = await pool._lock_for('workspace_a')
        await lock.acquire()
        closing = asyncio.create_task(pool.close_profile('workspace_a', bo_qua_khi_dang_nhap=True))
        await asyncio.sleep(0)
        pool.dau_dang_nhap('workspace_a')
        lock.release()
        assert await closing is False
        context.close.assert_not_called()
    asyncio.run(run())
