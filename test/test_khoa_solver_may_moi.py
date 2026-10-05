"""Máy mới cài (05/10/2026): chưa ai lưu thẻ Flow → config.data không có captcha_solver_api_key → c2a gửi khoá RỖNG
tới solver nội bộ → «401 Unauthorized … /v1/openai-native/onboard». Khoá cho lời gọi phía máy chủ phải lấy từ
CAPTCHA_SOLVER_API_KEY (thứ solver nội bộ dùng để kiểm)."""
from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import captcha  # noqa: E402


def test_solver_noi_bo_lay_khoa_bien_moi_truong(monkeypatch):
    monkeypatch.setenv("CAPTCHA_SOLVER_API_KEY", "khoa-env")
    assert captcha.khoa_solver({}) == "khoa-env", "máy mới: cấu hình trống vẫn có khoá"
    assert captcha.khoa_solver(None) == "khoa-env"
    assert captcha.khoa_solver({"captcha_solver_url": "/api/captcha", "captcha_solver_api_key": "cu"}) == "khoa-env", \
        "solver nội bộ kiểm bằng biến môi trường — khoá cũ trong cấu hình không được thắng"


def test_solver_rieng_giu_khoa_rieng(monkeypatch):
    monkeypatch.setenv("CAPTCHA_SOLVER_API_KEY", "khoa-env")
    cfg = {"captcha_solver_url": "https://solver.vidu.vn", "captcha_solver_api_key": "khoa-rieng"}
    assert captcha.khoa_solver(cfg) == "khoa-rieng"


def test_chua_dat_bien_moi_truong_thi_dung_cau_hinh(monkeypatch):
    monkeypatch.delenv("CAPTCHA_SOLVER_API_KEY", raising=False)
    assert captcha.khoa_solver({"captcha_solver_api_key": "cu"}) == "cu"


def test_account_recovery_may_moi_khong_gui_khoa_rong(monkeypatch):
    from services import account_recovery
    from services.config import config
    monkeypatch.setenv("CAPTCHA_SOLVER_API_KEY", "khoa-env")
    monkeypatch.setitem(config.data, "providers", {})
    url, key = account_recovery._solver_cfg()
    assert url == captcha.INTERNAL and key == "khoa-env"
