"""Ba lỗi Flow chủ máy cho sửa 02/10/2026.

1. Vòng thử của dispatcher đi hết tài khoản còn dùng được thì build_headers rơi về `_next_account()` không loại trừ →
   lần thử thứ 3 quay lại đúng tài khoản vừa hỏng (giả lập 01/10: a → b → a khi c đang nghỉ).
2. «hết ngạch» khớp chuỗi con `"rate"` — nằm sẵn trong «generate».
3. Câu báo luôn ghi «cooldown 3600s» kể cả khi cả nhóm nghỉ 6 giờ vì cờ «hoạt động bất thường».
"""
from __future__ import annotations

import os
import time
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.image_providers import flow_google as fg  # noqa: E402

TK = [{"profile": "google-a", "project_id": "1"}, {"profile": "google-b", "project_id": "2"},
      {"profile": "google-c", "project_id": "3"}]


@pytest.fixture
def pool():
    with mock.patch.object(fg, "_pool_config", return_value={"accounts": TK, "captcha_solver_url": "http://x"}), \
            mock.patch("services.captcha.captcha_base", return_value="http://x"):
        fg._account_state.clear()
        yield
        fg._account_state.clear()


def test_khong_quay_lai_tai_khoan_vua_hong(pool):
    fg._account_state[fg._account_key(fg._accounts()[2])] = {"cooldown_until": time.time() + 3600}
    ad, cred, da_gui = fg.FlowImageAdapter(), {}, []
    for key_try in range(3):
        ad.build_url("flow/auto", cred, key_try)
        body: dict = {}
        try:
            ad.build_headers(cred, body, "flow/auto", {})
            da_gui.append(body["profile"])
        except RuntimeError as exc:
            assert "đã thử hết 2 tài khoản" in str(exc)
            break
    assert da_gui == ["google-a", "google-b"]


def test_het_ngach_khop_theo_tu():
    for sai in ("Failed to generate image", "moderate content", "accurate result", "sign in to generate"):
        assert not fg._la_het_ngach(500, sai), sai
    for dung in ("Quota exceeded", "RESOURCE_EXHAUSTED", "rate limit hit", "rate_limited", "usage_limit reached",
                 "Too Many Requests"):
        assert fg._la_het_ngach(500, dung), dung
    assert fg._la_het_ngach(429, "")


def test_loi_generate_khong_cho_tai_khoan_nghi(pool):
    acc = fg._accounts()[0]
    fg.FlowImageAdapter().on_key_failed({"_flow_account": acc}, 500, "Failed to generate image: internal")
    assert not fg._account_state.get(fg._account_key(acc), {}).get("cooldown_until")


def test_cau_bao_noi_dung_ly_do_va_thoi_gian(pool):
    fg._tam_nghi_ca_nhom("unusual_activity")
    with pytest.raises(RuntimeError) as e:
        fg.FlowImageAdapter().build_headers(None, {}, "flow/auto", {})
    assert "hoạt động bất thường" in str(e.value) and "3600" not in str(e.value)
    assert "phút" in str(e.value)
