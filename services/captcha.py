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
