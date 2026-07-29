"""Profile placeholder (…-default) không được vào vòng xoay tài khoản Gemini web.

Chuyện đã xảy ra trên máy chủ: kho tài khoản có entry `gemini-web-default` với
status=active — sinh ra từ ô "profile" mặc định của thẻ Cài đặt, chứ không phải
một tài khoản Google đã onboard. Nó nằm cùng 9 profile thật, nên mỗi vòng lấy
cookie hệ thống lại gọi captcha-solver cho nó, solver mở một phiên trình duyệt
rồi trả 404 "__Secure-1PSID missing" (log 22:59 ngày 2026-07-29).

Hai hậu quả người dùng thấy được:
  · phiên trình duyệt rác giành lock đúng lúc họ đang đăng nhập tay → "đăng nhập
    xong lại bắt đăng nhập", cảm giác nhiều tầng;
  · nếu profile rỗng đó được chọn để trả lời → Gemini đáp "Permission denied or
    unauthenticated".

Điều kiện biên quan trọng: khi CHƯA có profile thật nào thì vẫn phải giữ
placeholder, nếu không người dùng không còn đường onboard lần đầu.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GW = ROOT / "api" / "gemini_web.py"


def _mo_ta_loc():
    """Trích đúng đoạn lọc trong _profiles() để chạy độc lập (module cần curl_cffi)."""
    src = GW.read_text("utf-8")
    ph = re.search(r'_PLACEHOLDER_RE = re\.compile\((.+?)\)\n', src)
    assert ph, "không thấy _PLACEHOLDER_RE"
    ns: dict = {"re": re}
    exec(f"_PLACEHOLDER_RE = re.compile({ph.group(1)})", ns)  # noqa: S102
    rx = ns["_PLACEHOLDER_RE"]

    def loc(profiles: list[str]) -> list[str]:
        thuc = [p for p in profiles if not rx.search(p)]
        return thuc if thuc else profiles

    return loc


class TestLocPlaceholder:
    def test_bo_default_khi_con_profile_that(self):
        loc = _mo_ta_loc()
        vao = ["google-tritue0610", "google-benbap115", "gemini-web-default"]
        assert loc(vao) == ["google-tritue0610", "google-benbap115"]

    def test_giu_lai_khi_chua_onboard_cai_nao(self):
        """Chưa có profile thật thì KHÔNG được lọc sạch — mất đường onboard."""
        loc = _mo_ta_loc()
        assert loc(["gemini-web-default"]) == ["gemini-web-default"]
        assert loc([]) == []

    @pytest.mark.parametrize("ten", [
        "gemini-web-default", "claude-web-default", "chatgpt-default",
        "default", "some_default", "PROFILE-DEFAULT",
    ])
    def test_cac_dang_placeholder_deu_bi_bat(self, ten):
        loc = _mo_ta_loc()
        assert loc(["google-that", ten]) == ["google-that"]

    @pytest.mark.parametrize("ten", [
        "google-tritue0610", "google-default-user", "default-google",
        "google-benbap2011",
    ])
    def test_khong_bat_oan_ten_that(self, ten):
        """Chỉ đuôi `default` mới là placeholder — `default-google` hay
        `google-default-user` là tên thật, giữ nguyên."""
        loc = _mo_ta_loc()
        assert ten in loc(["google-khac", ten])


class TestDungMotQuyTacBaNoi:
    def test_khop_bieu_thuc_voi_accounts_py(self):
        """api/accounts và api/gemini_web phải cùng một biểu thức, lệch là UI ẩn
        mà đường chạy vẫn dùng (hoặc ngược lại)."""
        acc = (ROOT / "api" / "accounts.py").read_text("utf-8")
        gw = GW.read_text("utf-8")
        assert r'r"(^|[-_])default$"' in acc
        assert r'r"(^|[-_])default$"' in gw

    def test_co_log_khi_bo_profile(self):
        """Bỏ bớt tài khoản là việc đáng ghi log — im lặng thì lần sau không ai
        hiểu vì sao profile biến mất khỏi vòng xoay."""
        gw = GW.read_text("utf-8")
        assert "gma_bo_profile_placeholder" in gw
