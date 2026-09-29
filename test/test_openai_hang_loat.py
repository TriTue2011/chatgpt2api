"""Đăng nhập hàng loạt tài khoản OpenAI gốc (29/09/2026): xong một tài khoản mới sang tài khoản kế."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from services import openai_hang_loat as hl  # noqa: E402


class _Tl:
    def __init__(self, d):
        self._d = d

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


@pytest.fixture
def gia(monkeypatch):
    """Solver giả: mỗi tài khoản trả ``kq[email]`` ("success" / "failed") sau một nhịp đang chạy."""
    monkeypatch.setattr(hl, "NGHI_GIAY", 0.0)
    monkeypatch.setattr(hl, "_NHIP_GIAY", 0.001)
    monkeypatch.setattr("services.account_recovery._solver_cfg", lambda: ("http://s", "k"))
    nhat_ky: list[str] = []
    kq: dict[str, str] = {}
    nhip: dict[str, int] = {}
    dang: list[str] = []

    def post(url, json=None, **k):
        assert not dang, "chưa xong tài khoản trước đã sang tài khoản kế"
        dang.append(json["profile"])
        nhat_ky.append(f"bat_dau {json['email']} {json['password']} {json['totp_secret']}")
        return _Tl({"state": "starting"})

    def get(url, **k):
        p = url.split("/")[-2]
        email = next(e for e in kq if hl._profile(e) == p)
        if url.endswith("/token"):
            return _Tl({"access_token": f"eyJ.{p}", "email": email})
        nhip[p] = nhip.get(p, 0) + 1
        if nhip[p] < 2:
            return _Tl({"state": "running", "message": "Đang điền mật khẩu"})
        dang.clear()
        return _Tl({"state": kq[email], "error": "Sai mật khẩu"})

    them: list[str] = []
    song: dict[str, str] = {}
    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("requests.get", get)
    from services.account_service import account_service
    monkeypatch.setattr(account_service, "add_accounts", lambda t: them.extend(t) or {})
    monkeypatch.setattr(account_service, "refresh_accounts", lambda t: {})
    monkeypatch.setattr(account_service, "find_free_by_email",
                        lambda e: {"status": song[e]} if e in song else None)
    yield {"kq": kq, "them": them, "song": song, "nhat_ky": nhat_ky}
    hl._dung.set()
    if hl._luong:
        hl._luong.join(5)


def _chay_het(van_ban: str) -> dict:
    hl.bat_dau(van_ban)
    hl._luong.join(10)
    return hl.trang_thai()


def test_doc_danh_sach():
    ds = hl.doc_danh_sach("# ghi chú\nA@x.com|p:1|ABCD EFGH\n\nb@y.com|p2\na@x.com|khac|")
    assert ds == [{"email": "a@x.com", "mat_khau": "p:1", "totp": "ABCDEFGH"},
                  {"email": "b@y.com", "mat_khau": "p2", "totp": ""}]
    with pytest.raises(ValueError, match="Dòng 2"):
        hl.doc_danh_sach("a@x.com|p\nkhong-phai-email|p")
    with pytest.raises(ValueError):
        hl.doc_danh_sach("  \n")


def test_lan_luot_bo_qua_tai_khoan_con_song(gia):
    gia["kq"].update({"a@x.com": "success", "b@x.com": "success", "c@x.com": "success"})
    gia["song"].update({"b@x.com": "active", "c@x.com": "error"})
    tt = _chay_het("a@x.com|pa|T1\nb@x.com|pb|T2\nc@x.com|pc|T3")
    assert [x["state"] for x in tt["ds"]] == ["xong", "da_co", "xong"]
    assert gia["them"] == ["eyJ.openai-a", "eyJ.openai-c"]
    assert gia["nhat_ky"] == ["bat_dau a@x.com pa T1", "bat_dau c@x.com pc T3"]
    assert not tt["dang_chay"]
    assert all("mat_khau" not in x for x in tt["ds"])
    assert all(x["mat_khau"] == "" and x["totp"] == "" for x in hl._hang)   # không ở lại bộ nhớ


def test_hong_lien_hai_tai_khoan_thi_dung_ca_hang(gia):
    gia["kq"].update({"a@x.com": "failed", "b@x.com": "success", "c@x.com": "failed",
                      "d@x.com": "failed", "e@x.com": "success"})
    tt = _chay_het("a@x.com|p|t\nb@x.com|p|t\nc@x.com|p|t\nd@x.com|p|t\ne@x.com|p|t")
    assert [x["state"] for x in tt["ds"]] == ["loi", "xong", "loi", "loi", "bo"]
    assert tt["ds"][0]["message"] == "Sai mật khẩu"


def test_khong_chay_hai_danh_sach_cung_luc(gia):
    gia["kq"]["a@x.com"] = "success"
    with mock.patch.object(hl, "_chay", lambda: hl._dung.wait(5)):
        hl.bat_dau("a@x.com|p|t")
        with pytest.raises(ValueError, match="Đang chạy"):
            hl.bat_dau("a@x.com|p|t")
