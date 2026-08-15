"""Tài khoản Codex không được tụt xuống nhóm free rồi biến mất.

SỰ CỐ đo trên máy chủ 15/08/2026. Chủ máy: "đăng nhập codex mà cứ mất dần".
Số liệu lúc đo: 18 email từng nằm nhóm codex, chỉ còn **3**; 8 tài khoản Gmail
nằm nhóm free và KHÔNG cái nào có ``refresh_token``; nhật ký ghi 27 lần MỘT
dòng tài khoản đổi nhóm, nhiều lần theo chiều codex → free. Cờ tự động xoá tài
khoản bị giới hạn đang tắt, nên không phải bị xoá.

Cơ chế: nhóm được suy từ ``plan``. Một tài khoản Codex vừa hết gói trả phí tạm
thời trông như free; đúng lúc đó ``upsert_free_token`` nhận nó là "dòng free cũ
của email này" rồi đóng đinh ``type="free"`` — tụt hạng thành vĩnh viễn. Nặng
hơn: nếu trùng luôn access_token thì dòng free ghi đè dòng Codex ở cùng khoá,
tức mất cả ``refresh_token``.
"""
from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from services import account_service as mod
from services.account_service import AccountService, account_group


class KhoTam:
    """Kho lưu trong bộ nhớ — test không đụng đĩa lẫn Postgres."""

    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self.rows = [dict(r) for r in (rows or [])]

    def load_accounts(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rows]

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        self.rows = [dict(a) for a in accounts]


def _dich_vu(rows: list[dict[str, Any]]) -> AccountService:
    with mock.patch.object(mod, "log_service", mock.Mock()):
        return AccountService(KhoTam(rows))


#: Dòng Codex thật: có refresh_token, và gói đọc ra "free" vì vừa hết hạn —
#: đúng trạng thái của các tài khoản đã biến mất.
CODEX = {"access_token": "codex-token", "email": "a@gmail.com",
         "type": "codex", "plan": "free", "refresh_token": "rt-song",
         "status": "active"}


@pytest.mark.pure
def test_dong_codex_het_goi_khong_bi_dong_dinh_thanh_free():
    svc = _dich_vu([CODEX])

    with mock.patch.object(mod, "log_service", mock.Mock()):
        svc.upsert_free_token("jwt-web-moi", {"email": "a@gmail.com"})

    con_lai = {t: a for t, a in svc._accounts.items()}
    assert "codex-token" in con_lai, "dòng Codex bị nuốt mất"
    assert con_lai["codex-token"]["type"] == "codex"
    assert con_lai["codex-token"]["refresh_token"] == "rt-song"
    assert account_group(con_lai["codex-token"]) == "codex"
    # Bản free là một dòng RIÊNG, không phải bản thay thế.
    assert "jwt-web-moi" in con_lai
    assert account_group(con_lai["jwt-web-moi"]) == "free"


@pytest.mark.pure
def test_khong_ghi_de_dong_codex_khi_trung_access_token():
    svc = _dich_vu([CODEX])

    with mock.patch.object(mod, "log_service", mock.Mock()):
        ket = svc.upsert_free_token("codex-token", {"email": "a@gmail.com"})

    assert ket == {"added": 0, "updated": 0, "skipped": 1}
    giu = svc._accounts["codex-token"]
    assert giu["refresh_token"] == "rt-song"
    assert giu["type"] == "codex"


@pytest.mark.pure
def test_dong_free_that_van_duoc_re_key_nhu_cu():
    """Bản vá không được làm hỏng việc gộp free theo email."""
    svc = _dich_vu([{"access_token": "jwt-cu", "email": "b@gmail.com",
                     "type": "free", "plan": "free", "status": "active"}])

    with mock.patch.object(mod, "log_service", mock.Mock()):
        ket = svc.upsert_free_token("jwt-moi", {"email": "b@gmail.com"})

    assert ket["updated"] == 1 and ket["added"] == 0
    assert "jwt-cu" not in svc._accounts
    assert "jwt-moi" in svc._accounts


@pytest.mark.pure
def test_nhat_ky_xoa_ghi_ro_da_xoa_email_nao():
    svc = _dich_vu([CODEX, {"access_token": "jwt-web", "email": "c@gmail.com",
                            "type": "free", "status": "active"}])
    ghi = mock.Mock()

    with mock.patch.object(mod, "log_service", ghi):
        svc.delete_accounts(["codex-token"])

    tom_tat, chi_tiet = ghi.add.call_args[0][1], ghi.add.call_args[0][2]
    assert "Đã xóa 1 tài khoản" in tom_tat
    assert chi_tiet["removed"] == 1
    assert chi_tiet["emails"] == ["a@gmail.com"]
