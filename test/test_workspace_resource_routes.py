"""Session maintenance releases browsers, and busy accounts never trigger login."""
import ast
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException


def route(name, **environment):
    source = Path('captcha-solver/src/main.py').read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    node.decorator_list = []
    node.returns = None
    for arg in node.args.args:
        arg.annotation = None
    namespace = {'HTTPException': HTTPException, 'HoSoDangBan': TimeoutError, **environment}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<route>', 'exec'), namespace)
    return namespace[name]


def test_flow_check_closes_browser_after_success_and_failure():
    async def run():
        page = SimpleNamespace(evaluate=AsyncMock(return_value=True))
        @asynccontextmanager
        async def browser(**kwargs):
            yield page
        pool = SimpleNamespace(page=browser, close_profile=AsyncMock())
        check = route('api_flow_check_project', pool=pool, flow_open_project=AsyncMock(), FLOW_READY='ready',
                      logger=Mock(), _loi_flow_rest=lambda exc: HTTPException(503, 'failed'))
        req = SimpleNamespace(profile='workspace_a', project_id='project', headless=True)
        assert (await check(req))['ready'] is True
        pool.close_profile.assert_awaited_once()
        page.evaluate.side_effect = RuntimeError('failed')
        with pytest.raises(HTTPException):
            await check(req)
        assert pool.close_profile.await_count == 2
    asyncio.run(run())


def test_chatgpt_busy_does_not_attempt_relogin():
    @asynccontextmanager
    async def busy(**kwargs):
        raise HTTPException(429, 'Account Busy')
        yield
    pool = SimpleNamespace(page=busy, close_profile=AsyncMock())
    resolve = Mock(side_effect=AssertionError('Busy is not expired'))
    refresh = route('api_chatgpt_refresh_jwt', pool=pool, _ho_so_ung_vien=lambda profile: [profile], resolve_account=resolve)
    with pytest.raises(HTTPException) as error:
        asyncio.run(refresh('workspace_a'))
    assert error.value.status_code == 429
    resolve.assert_not_called()


def test_captcha_proxy_accepts_admin_cookie_but_rejects_user_cookie_and_wrong_bearer():
    from api.captcha_proxy import _authorized
    from services.browser_session_middleware import danh_tinh_cookie
    for identity, allowed in [(None, False), ({'role': 'user'}, False), ({'role': 'admin'}, True)]:
        token = danh_tinh_cookie.set(identity)
        try:
            assert _authorized(None) is allowed
            assert not _authorized('Bearer intentionally-invalid-workspace-test-key')
        finally:
            danh_tinh_cookie.reset(token)


@pytest.mark.parametrize('status', [429, 503])
def test_claude_busy_or_unavailable_solver_does_not_relogin(status, monkeypatch):
    from api import claude
    monkeypatch.setattr(claude, '_solver_key_cache', {})
    monkeypatch.setattr(claude, '_relogin_cooldown', {})
    notify = Mock()
    monkeypatch.setattr(claude, '_claude_notify', notify)
    monkeypatch.setattr('api.gemini_web._store_profiles', lambda groups: [])
    monkeypatch.setattr('services.captcha.captcha_base', lambda value: 'http://solver')
    monkeypatch.setattr(claude.requests, 'get', Mock(return_value=SimpleNamespace(status_code=status)))
    post = Mock(side_effect=AssertionError('Busy/unavailable must not trigger login'))
    monkeypatch.setattr(claude.requests, 'post', post)
    assert claude._fetch_session_key_from_solver({'profiles': ['workspace_a']}) == ''
    post.assert_not_called()
    notify.assert_not_called()


def test_relogin_cleanup_reports_manual_workspace_as_busy():
    pool = SimpleNamespace(is_manual=lambda profile: True, close_profile=AsyncMock())
    cleanup = route('_don_ho_so_truoc_khi_dang_nhap', pool=pool)
    assert 'thủ công' in asyncio.run(cleanup('workspace_a'))
    pool.close_profile.assert_not_called()
