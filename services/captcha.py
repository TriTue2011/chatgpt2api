"""Resolve the captcha-solver base URL for SERVER-SIDE calls.

The captcha-solver runs in this same container on 127.0.0.1:8010. The web UI
now talks to it through the same-origin /api/captcha proxy, so the stored
`captcha_solver_url` may be a relative proxy path ("/api/captcha"), empty, or a
stale cross-container hostname. Any of those must resolve to the internal base
for code that makes a real HTTP call from the backend.
"""

from __future__ import annotations

import os

INTERNAL = os.getenv("CAPTCHA_SOLVER_URL_INTERNAL", "http://127.0.0.1:8010").rstrip("/")


def captcha_base(value: str | None = None) -> str:
    v = str(value or "").strip().rstrip("/")
    if v.startswith(("http://", "https://")):
        # Stale separate-container hostname or the browser proxy path → internal.
        if "captcha-solver:" in v or "/api/captcha" in v or ":8010" in v:
            return INTERNAL
        return v
    # empty or relative ("/api/captcha") → internal
    return INTERNAL


def khoa_solver(cfg: dict | None = None) -> str:
    """Khoá Bearer cho lời gọi PHÍA MÁY CHỦ tới captcha-solver.

    Solver NỘI BỘ kiểm đúng biến ``CAPTCHA_SOLVER_API_KEY`` → dùng biến đó. Khoá chép trong cấu hình
    (``providers.*.captcha_solver_api_key``) chỉ tồn tại khi ai đó từng lưu trang Cài đặt — ``config.get()`` điền nó
    từ biến môi trường cho WEB nhưng không ghi vào ``config.data``. Đo 05/10/2026: máy mới cài chưa lưu Flow/Gemini
    → mọi nơi đọc ``config.data`` gửi khoá RỖNG → «401 Unauthorized … /v1/openai-native/onboard».
    Solver RIÊNG (URL lạ, ``captcha_base`` giữ nguyên) có khoá riêng → dùng khoá trong cấu hình (cùng luật
    ``branch_health.kiem_khoa_captcha``)."""
    c = cfg if isinstance(cfg, dict) else {}
    rieng = str(c.get("captcha_solver_api_key") or "").strip()
    if captcha_base(c.get("captcha_solver_url")) != INTERNAL:
        return rieng
    return os.getenv("CAPTCHA_SOLVER_API_KEY", "").strip() or rieng
