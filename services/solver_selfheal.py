"""Shared self-heal for captcha-solver web providers.

When a provider loses its session/token because the underlying Google session in
its browser profile expired, trigger the solver's per-service
`relogin-via-google` for that profile. The solver resolves the saved Google
credentials internally and does an SSO reuse (session still valid) or a full
email/password/2FA login (session gone) — no manual noVNC unless Google throws
an anti-bot challenge it can't pass headlessly.

Bounded by a per-(service, profile) 5-minute cooldown so a profile that genuinely
can't onboard doesn't relaunch Chrome on every request. Best-effort: the caller
re-fetches the token/cookie on the next attempt (relogin runs a few seconds in
the background on the solver).
"""

from __future__ import annotations

import threading
import time

_COOLDOWN = 300.0
_cooldown: dict[str, float] = {}
_lock = threading.Lock()

# service segment used in the solver URL /v1/<service>/<profile>/relogin-via-google
CLAUDE = "claude-web"
CHATGPT = "chatgpt"
GEMINI = "gemini-web"


def try_relogin(base: str, api_key: str, service: str, profile: str) -> bool:
    """Fire relogin-via-google for `profile` on `service`. Returns True if a
    relogin was actually triggered this call (i.e. not within cooldown)."""
    if not base or not profile:
        return False
    key = f"{service}:{profile}"
    now = time.time()
    with _lock:
        if now - _cooldown.get(key, 0) < _COOLDOWN:
            return False
        _cooldown[key] = now
    try:
        from curl_cffi import requests
        from utils.log import logger
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        requests.post(
            f"{base.rstrip('/')}/v1/{service}/{profile}/relogin-via-google",
            headers=headers, timeout=30, impersonate="chrome110",
        )
        logger.info({"event": "solver_selfheal_relogin", "service": service, "profile": profile})
        return True
    except Exception as exc:
        try:
            from utils.log import logger
            logger.warning({"event": "solver_selfheal_failed", "service": service,
                            "profile": profile, "error": str(exc)[:120]})
        except Exception:
            pass
        return False
