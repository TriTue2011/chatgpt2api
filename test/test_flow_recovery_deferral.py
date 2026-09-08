"""A CAPTCHA hold and an inconclusive probe are not failed account recovery."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from services import account_recovery as ar


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(ar, '_last_attempt', {})
    monkeypatch.setattr(ar, '_LAST_LOGIN_STATE', {})
    monkeypatch.setattr(ar, '_LAST_LOGIN_NOTE', {})
    monkeypatch.setattr(ar, '_glogin_captcha_until', 0)
    monkeypatch.setattr(ar, '_glogin_captcha_profile', '')
    monkeypatch.setattr(ar, '_notify', Mock())
    monkeypatch.setattr(ar.time, 'sleep', lambda _: None)
    monkeypatch.setattr(ar, '_solver_cfg', lambda: ('http://solver', 'test'))
    monkeypatch.setattr(ar, '_flow_project_id', lambda _: 'project')


@pytest.mark.parametrize('status,body', [(502, {}), (503, {}), (403, {}), (200, {}), (200, {'ready': False})])
def test_inconclusive_probe_does_not_claim_expired_session(monkeypatch, status, body):
    monkeypatch.setattr('requests.post', Mock(return_value=SimpleNamespace(status_code=status, json=lambda: body)))
    assert ar._flow_session_trang_thai('google-a') == 'chua_ro'


def test_unrelated_healthy_profile_cannot_clear_captcha_hold(monkeypatch):
    until = ar.time.time() + 20000
    monkeypatch.setattr(ar, '_glogin_captcha_until', until)
    monkeypatch.setattr(ar, '_glogin_captcha_profile', 'google-captcha')
    monkeypatch.setattr('requests.post', Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {'ready': True})))
    assert ar._flow_session_trang_thai('google-other') == 'ok'
    assert ar._glogin_captcha_until == until


def test_pending_captcha_defers_other_accounts_without_failure_or_browser_probe(monkeypatch):
    monkeypatch.setattr(ar, '_glogin_captcha_until', ar.time.time() + 20000)
    monkeypatch.setattr(ar, '_glogin_captcha_profile', 'google-captcha')
    monkeypatch.setattr('requests.get', Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {'state': 'need_captcha'})))
    probe = Mock(side_effect=AssertionError('No browser needed during hold'))
    freshen = Mock(side_effect=AssertionError('No login during hold'))
    monkeypatch.setattr(ar, '_flow_session_trang_thai', probe)
    monkeypatch.setattr(ar, '_freshen_google', freshen)
    ar.flow_recover_and_notify('google-other')
    ar._notify.assert_not_called()
    probe.assert_not_called()


def test_manual_success_releases_hold_early_without_restarting_same_login(monkeypatch):
    monkeypatch.setattr(ar, '_glogin_captcha_until', ar.time.time() + 20000)
    monkeypatch.setattr(ar, '_glogin_captcha_profile', 'google-captcha')
    monkeypatch.setattr('requests.get', Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {'state': 'success'})))
    post = Mock(side_effect=AssertionError('Already completed by user'))
    monkeypatch.setattr('requests.post', post)
    assert ar._freshen_google('google-captcha') is True
    assert ar._glogin_captcha_until == 0
    post.assert_not_called()


def test_unknown_probe_never_escalates_to_google_login(monkeypatch):
    monkeypatch.setattr(ar, '_flow_session_trang_thai', lambda _: 'chua_ro')
    freshen = Mock(side_effect=AssertionError('Unknown is not expired'))
    monkeypatch.setattr(ar, '_freshen_google', freshen)
    ar.flow_recover_and_notify('google-a')
    ar._notify.assert_not_called()


def test_captcha_during_login_reports_waiting_for_user_not_failure(monkeypatch):
    monkeypatch.setattr(ar, '_flow_session_trang_thai', lambda _: 'mat')
    def freshen(profile, **kwargs):
        ar._ghi_ket_qua(profile, 'need_captcha')
        return False
    monkeypatch.setattr(ar, '_freshen_google', freshen)
    ar.flow_recover_and_notify('google-a')
    messages = [call.args[0] for call in ar._notify.call_args_list]
    assert 'CAPTCHA' in messages[-1]
    assert not any('KHÔNG tự khôi phục được' in text for text in messages)


@pytest.mark.parametrize('detail,expected', [('invalid api key', 'chua_ro'), ({'code': 'flow_login_required'}, 'mat')])
def test_solver_authentication_error_is_not_google_session_expiry(monkeypatch, detail, expected):
    monkeypatch.setattr('requests.post', Mock(return_value=SimpleNamespace(status_code=401, json=lambda: {'detail': detail})))
    assert ar._flow_session_trang_thai('google-a') == expected
