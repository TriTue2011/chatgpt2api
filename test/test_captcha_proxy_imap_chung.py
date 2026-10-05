"""Proxy captcha điền IMAP DÙNG CHUNG cho v1/codex-onboard khi trình duyệt để trống mật khẩu (05/10/2026).

Bật che bí mật ở /api/settings thì trình duyệt không còn thấy `codex_imap_gmail_app_password`; trước đó nó gửi
nguyên chuỗi "[object Object]" làm mật khẩu IMAP."""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from api import captcha_proxy as cp  # noqa: E402


@pytest.fixture(autouse=True)
def imap_chung(monkeypatch):
    monkeypatch.setitem(cp.config.data, "codex_imap_gmail_email", "Chung@Gmail.com")
    monkeypatch.setitem(cp.config.data, "codex_imap_gmail_app_password", "abcd efgh")


def _goi(body: dict, path: str = "v1/codex-onboard", method: str = "POST") -> dict:
    return json.loads(cp._dien_imap_chung(path, method, json.dumps(body).encode()))


def test_o_trong_thi_dien_ca_email_lan_mat_khau():
    d = _goi({"github_email": "a@x", "gmail_email": "", "gmail_app_password": ""})
    assert d["gmail_email"] == "Chung@Gmail.com" and d["gmail_app_password"] == "abcd efgh"


def test_dung_email_chung_khong_phan_biet_hoa_thuong():
    assert _goi({"gmail_email": "chung@gmail.com", "gmail_app_password": ""})["gmail_app_password"] == "abcd efgh"


def test_email_khac_thi_khong_dien_mat_khau_chung():
    d = _goi({"gmail_email": "rieng@gmail.com", "gmail_app_password": ""})
    assert d["gmail_app_password"] == "", "mật khẩu chung cho hộp thư khác là đăng nhập hỏng"


def test_da_go_mat_khau_thi_giu_nguyen():
    assert _goi({"gmail_email": "", "gmail_app_password": "rieng"})["gmail_app_password"] == "rieng"


def test_chi_dung_dung_duong_va_post():
    body = {"gmail_email": "", "gmail_app_password": ""}
    assert _goi(body, path="v1/multi-onboard")["gmail_app_password"] == ""
    raw = json.dumps(body).encode()
    assert cp._dien_imap_chung("v1/codex-onboard", "GET", raw) == raw


def test_chua_luu_imap_chung_hoac_body_la_thi_khong_dung(monkeypatch):
    monkeypatch.setitem(cp.config.data, "codex_imap_gmail_app_password", "")
    assert _goi({"gmail_email": "", "gmail_app_password": ""})["gmail_app_password"] == ""
    assert cp._dien_imap_chung("v1/codex-onboard", "POST", b"khong-phai-json") == b"khong-phai-json"
