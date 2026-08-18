"""Token chết trên tài khoản trông vẫn khoẻ thì phải bị phát hiện.

Đo 18/08 trên máy chủ thật: hai tài khoản Codex mang ``quota`` 118 và 5, trạng
thái ``active``, nhưng gọi thật vào API trả **401** — token đã chết.

``_should_refresh`` chỉ soát khi ``quota < 5``, hoặc trạng thái ``limited`` /
``error``. Không điều kiện nào chạm tới hai tài khoản đó, nên chúng nằm
``active`` vĩnh viễn và bộ định tuyến vẫn giao việc, mỗi lần giao là một cú 401
vô ích. Cơ chế tắt-sau-3-lần-401 có sẵn nhưng chỉ chạy khi tài khoản ĐƯỢC DÙNG,
mà chúng thì hiếm khi được chọn nên không bao giờ tích đủ.
"""

from __future__ import annotations

import time

import pytest


def _w():
    from services import quota_watcher as qw
    return qw, qw.quota_watcher


def _gio(cach_day_giay: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(time.time() - cach_day_giay).strftime("%Y-%m-%d %H:%M:%S")


@pytest.mark.pure
def test_tai_khoan_lau_chua_soat_thi_phai_soat():
    """Đúng cảnh đo được: quota đẹp, status active, nhưng lâu rồi chưa ai kiểm."""
    qw, w = _w()
    acc = {"access_token": "t", "status": "active", "quota": 118,
           "last_checked_at": _gio(qw.XAC_MINH_LAI_SAU + 60)}
    assert w._should_refresh(acc), "token chết sẽ không bao giờ bị phát hiện"


@pytest.mark.pure
def test_vua_soat_xong_thi_thoi():
    """Không được soát lại mỗi vòng — nếu không watcher sẽ nện API liên tục."""
    qw, w = _w()
    acc = {"access_token": "t", "status": "active", "quota": 118,
           "last_checked_at": _gio(60)}
    assert not w._should_refresh(acc)


@pytest.mark.pure
def test_chua_tung_soat_thi_soat_ngay():
    """Tài khoản mới thêm, chưa có dấu giờ nào → phải kiểm."""
    _, w = _w()
    assert w._should_refresh({"access_token": "t", "status": "active", "quota": 50})


@pytest.mark.pure
def test_dung_last_used_khi_chua_co_dau_gio_soat():
    """Bản cũ chỉ có last_used_at; đừng bắt tài khoản vừa dùng phải soát lại."""
    qw, w = _w()
    acc = {"access_token": "t", "status": "active", "quota": 118,
           "last_used_at": _gio(60)}
    assert not w._should_refresh(acc)


@pytest.mark.pure
def test_cac_dieu_kien_cu_van_giu():
    """Vá xong không được đánh rơi ba điều kiện vốn có."""
    _, w = _w()
    moi = _gio(60)
    assert w._should_refresh({"access_token": "t", "status": "active",
                              "quota": 1, "last_checked_at": moi}), "quota thấp"
    assert w._should_refresh({"access_token": "t", "status": "error",
                              "quota": 100, "last_checked_at": moi}), "đang lỗi"
    assert not w._should_refresh({"access_token": "t", "status": "limited",
                                  "quota": 0, "restore_at": None,
                                  "last_checked_at": moi}), "đang nghỉ thì để yên"
