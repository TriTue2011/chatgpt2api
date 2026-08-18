"""Tài khoản dùng session web bị 'disabled' cũng phải được bật lại.

Đo thật 18/08 trên máy chủ đang chạy: 3 tài khoản ``gemini_web_api`` nằm ở
trạng thái ``disabled``, một cái mang dấu hết hạn mức từ **06/07** — hơn một
tháng không có gì đụng tới.

Nguyên nhân: ``quota_watcher._rebuild`` có sẵn đoạn tự bật lại tài khoản
``disabled``, nhưng nó nằm SAU cửa bỏ qua nhóm web-session. Cửa đó có lý do
riêng — nhóm web-session không có endpoint hạn mức nên không xếp vào lịch đo —
nhưng đoạn bật lại thì không gọi endpoint nào cả, nó chỉ đọc ``last_used_at``
rồi đặt lại status. Đặt sau cửa nghĩa là Gemini web một khi bị tắt thì nằm đó
vĩnh viễn, và bộ khôi phục Codex cũng không nhận (``_is_recoverable_group`` trả
rỗng cho nhóm này), tức KHÔNG CÓ AI lo cho chúng.
"""

from __future__ import annotations

import pytest


def _watcher(monkeypatch):
    from services import quota_watcher as qw

    da_dat: list[tuple[str, dict]] = []
    monkeypatch.setattr(qw.account_service, "update_account",
                        lambda tok, up: da_dat.append((tok, up)), raising=False)
    monkeypatch.setattr(qw.account_service, "revive_stuck_limited",
                        lambda **kw: 0, raising=False)
    return qw, da_dat


def _chay(qw, monkeypatch, accounts):
    monkeypatch.setattr(qw.account_service, "list_accounts",
                        lambda: list(accounts), raising=False)
    qw.QuotaWatcher._rebuild(qw.quota_watcher)


@pytest.mark.pure
def test_gemini_web_bi_tat_thi_duoc_bat_lai(monkeypatch):
    """Đúng cảnh đo được: gemini_web_api 'disabled', không có last_used_at."""
    qw, da_dat = _watcher(monkeypatch)
    _chay(qw, monkeypatch, [{
        "access_token": "tok-gemini",
        "email": "google-trianhtuenhi",
        "type": "gemini_web_api",
        "status": "disabled",
    }])
    assert da_dat, "tài khoản Gemini web bị tắt mà không ai bật lại"
    tok, up = da_dat[0]
    assert tok == "tok-gemini"
    assert up.get("status") == "active"


@pytest.mark.pure
def test_van_khong_xep_lich_do_han_muc_cho_nhom_web(monkeypatch):
    """Bật lại thì bật, nhưng KHÔNG được kéo chúng vào lịch đo hạn mức.

    Đó mới là lý do thật sự của cửa bỏ qua: nhóm này không có endpoint hạn mức,
    gọi vào chỉ nhận 401 rồi bị đánh dấu lỗi oan.
    """
    qw, _ = _watcher(monkeypatch)
    qw.quota_watcher._heap.clear()
    qw.quota_watcher._index.clear()
    _chay(qw, monkeypatch, [{
        "access_token": "tok-gemini",
        "email": "google-trianhtuenhi",
        "type": "gemini_web_api",
        "status": "active",
    }])
    assert not qw.quota_watcher._heap, "không được xếp tài khoản web vào lịch đo hạn mức"


@pytest.mark.pure
def test_tai_khoan_thuong_van_vao_lich_nhu_cu(monkeypatch):
    """Chiều ngược lại: đừng vá xong lại đánh rơi tài khoản chatgpt thường."""
    qw, _ = _watcher(monkeypatch)
    qw.quota_watcher._heap.clear()
    qw.quota_watcher._index.clear()
    _chay(qw, monkeypatch, [{
        "access_token": "tok-thuong",
        "email": "ai_do@gmail.com",
        "status": "active",
        "quota": 10,
    }])
    assert qw.quota_watcher._heap, "tài khoản thường phải còn trong lịch đo"


@pytest.mark.pure
def test_khong_ai_lo_cho_gemini_web_thi_bat_lai_la_duy_nhat(monkeypatch):
    """Ghi lại lý do vì sao chỗ bật lại này là lưới cuối cùng.

    Bộ khôi phục Codex loại thẳng nhóm này, nên nếu quota_watcher cũng bỏ qua
    thì không còn đường nào khác.
    """
    from services.codex_error_recovery_scheduler import _is_recoverable_group

    assert _is_recoverable_group({"type": "gemini_web_api"}) == "", (
        "nếu bộ khôi phục Codex nhận nhóm này thì test trên cần viết lại")
