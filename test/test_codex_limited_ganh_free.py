"""Tài khoản Codex hết lượt Codex thì gánh giúp pool free (quota web riêng).

Ý tưởng của chủ máy: các tài khoản codex và free thực ra là CÙNG tài khoản
Google, chỉ khác cách đăng nhập. Codex hết lượt (status="limited") nhưng đường
web free là quota RIÊNG — đo 03/09/2026 trên máy chủ: token của tài khoản codex
đang limited vẫn gọi chatgpt.com web free ra gpt-5-6 bình thường. Lúc đó tài
khoản đang nhàn rỗi (không phục vụ Codex được), nên cho nó gánh free là lãi ròng,
và khi quota Codex hồi (quota_watcher lật status về "active") thì tự quay lại
phục vụ Codex — "hết limit về lại".

Bộ test giữ năm tính chất:

  1. Phục vụ free: tài khoản codex đang `limited` ĐƯỢC chọn (vượt qua cả hai rào
     cũ: bỏ status="limited", và lọc group=="free").
  2. Free THẬT được ưu tiên: có free thật đang khoẻ thì chọn free thật, tài khoản
     mượn chỉ đỡ khi free bận/vắng.
  3. Bậc gói của tài khoản mượn KHÔNG lấn: một codex gói `go` limited không được
     nuốt lượt chỉ vì gói cao hơn free.
  4. Chỉ MƯỢN khi phục vụ free: gọi account_type="codex" thì tài khoản limited
     vẫn bị loại như cũ (không tự dưng sống lại cho Codex).
  5. Codex đang `active` KHÔNG bị kéo sang free (chỉ tài khoản limited mới mượn;
     active vẫn dành riêng cho Codex).

Và một tính chất an toàn: việc chọn KHÔNG đổi type/nhóm/status của tài khoản mượn
— đó là chốt chặn để không lặp lỗi trôi nhóm 15/08 (xem
test_codex_khong_tut_xuong_free).
"""
from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from services import account_service as mod
from services.account_service import AccountService, account_group


class KhoTam:
    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self.rows = [dict(r) for r in (rows or [])]

    def load_accounts(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rows]

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        self.rows = [dict(a) for a in accounts]


def _dich_vu(rows: list[dict[str, Any]]) -> AccountService:
    with mock.patch.object(mod, "log_service", mock.Mock()):
        return AccountService(KhoTam(rows))


def _codex(tok, plan="free", status="active"):
    return {"access_token": tok, "email": f"{tok}@gmail.com", "type": "codex",
            "plan": plan, "refresh_token": "rt", "status": status}


def _free(tok, status="active"):
    # Free web JWT: không có refresh_token, plan=free.
    return {"access_token": tok, "email": f"{tok}@gmail.com", "plan": "free",
            "status": status}


@pytest.mark.pure
def test_codex_limited_duoc_muon_khi_khong_con_free():
    svc = _dich_vu([_codex("cx-lim", status="limited")])
    tok = svc.get_text_access_token(account_type="free")
    assert tok == "cx-lim", "codex limited phải được mượn khi pool free trống"


@pytest.mark.pure
def test_uu_tien_free_that_hon_codex_muon():
    svc = _dich_vu([_codex("cx-lim", plan="go", status="limited"),
                    _free("free-that")])
    # bật weighted có thể né account vừa dùng; ở đây chưa ai dùng nên free thật thắng.
    tok = svc.get_text_access_token(account_type="free")
    assert tok == "free-that", "phải ưu tiên free thật, không để codex mượn nuốt"


@pytest.mark.pure
def test_bac_goi_cua_ban_muon_khong_lan_free():
    # go > free về bậc gói; nếu không trung hoà thì cx-lim(go) sẽ thắng free thật.
    svc = _dich_vu([_codex("cx-go-lim", plan="go", status="limited"),
                    _free("free-that")])
    tok = svc.get_text_access_token(account_type="free")
    assert tok == "free-that"


@pytest.mark.pure
def test_chi_muon_khi_phuc_vu_free_khong_muon_cho_codex():
    svc = _dich_vu([_codex("cx-lim", status="limited")])
    # Xin nhóm codex: tài khoản limited vẫn bị loại như cũ.
    assert svc.get_text_access_token(account_type="codex") == ""


@pytest.mark.pure
def test_codex_active_khong_bi_keo_sang_free():
    svc = _dich_vu([_codex("cx-active", status="active")])
    # active (chưa limited) KHÔNG được mượn — dành riêng cho Codex.
    assert svc.get_text_access_token(account_type="free") == ""


@pytest.mark.pure
def test_chon_khong_doi_type_nhom_status_cua_ban_muon():
    svc = _dich_vu([_codex("cx-lim", plan="go", status="limited")])
    svc.get_text_access_token(account_type="free")
    a = svc._accounts["cx-lim"]
    assert a["type"] == "codex"
    assert a["status"] == "limited"
    assert account_group(a) == "codex"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
