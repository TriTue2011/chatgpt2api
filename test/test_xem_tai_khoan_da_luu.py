"""Xem mật khẩu / hạt giống TOTP đã lưu — chỉ khi bấm 👁, có khoá, có nhật ký.

Chủ máy 06/10/2026 duyệt «Hiện đủ, có nút 👁 mới lộ»: trước đó kho không bao giờ trả credential về trình duyệt (08/08).
Đọc mã nguồn (captcha-solver/src/main.py kéo theo trình duyệt — các test khác của nó cũng đọc AST).
"""
from __future__ import annotations

import ast
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]


def _ham(ten: str) -> ast.AsyncFunctionDef:
    cay = ast.parse((GOC / "captcha-solver" / "src" / "main.py").read_text(encoding="utf-8"))
    return next(n for n in ast.walk(cay) if isinstance(n, ast.AsyncFunctionDef) and n.name == ten)


def test_duong_xem_co_khoa_va_ghi_nhat_ky():
    f = _ham("api_accounts_reveal")
    deco = ast.unparse(f.decorator_list[0])
    assert "/v1/accounts/saved/{email}/reveal" in deco and "require_api_key" in deco
    than = ast.unparse(f)
    assert "vault_reveal" in than, "mỗi lần xem phải ghi nhật ký"


def test_chon_tai_khoan_KHONG_tu_lo_mat_khau():
    """Chọn tài khoản vẫn chỉ nhận cờ; mật khẩu chỉ về khi gọi đúng /reveal (nút 👁)."""
    ui = (GOC / "web" / "src" / "components" / "saved-accounts-select.tsx").read_text(encoding="utf-8")
    assert "/reveal?loai=" in ui
    i = ui.index("async function loadAccount")
    assert "/reveal" not in ui[i:ui.index("async function deleteAccount")]
