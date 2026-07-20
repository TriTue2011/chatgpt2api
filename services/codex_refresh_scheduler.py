"""Codex OAuth proactive refresh scheduler.

Codex OAuth access_tokens expire after ~8h (28,800s per expires_in).
Accounts with a stored refresh_token can be proactively refreshed so
live requests never hit a 401. This is the proactive complement to the
reactive `_try_refresh_token` path in openai_oauth.py.

Mirrors the pattern in jwt_refresh_scheduler.py but uses the OAuth
refresh_token exchange (codex_token_refresh.py) instead of captcha-solver.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Any

from services.codex_token_refresh import refresh_codex_token
from services.config import config
from utils.log import logger

# Refresh when token has <= 6h remaining (access_tokens live ~8h).
# This gives a ~2h window where refresh is a noop; running every 4h
# means each token gets at most one refresh per cycle, not a cascade.
REFRESH_THRESHOLD_SECONDS = 6 * 3600

# Scan every 4h: frequent enough to catch 8h tokens before they expire,
# rare enough not to hammer auth.openai.com with hundreds of accounts.
SCAN_INTERVAL_SECONDS = 4 * 3600

# Per-scan wall-clock jitter: ±30 min to avoid lockstep timing.
SCAN_INTERVAL_JITTER_SECONDS = 30 * 60

# Per-account jitter inside one scan: spread refreshes across the scan
# window so N accounts don't hit auth.openai.com in the same second.
PER_ACCOUNT_JITTER_SECONDS = 60

REFRESH_TIMEOUT = 30

_started = False


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    """Decode the JWT payload (middle segment, base64url) without verifying."""
    import base64
    import json

    try:
        _, payload_b64, _ = token.split(".", 2)
    except ValueError:
        return None
    pad = "=" * (-len(payload_b64) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload_b64 + pad)
        return json.loads(raw)
    except Exception:
        return None


def _needs_refresh(account: dict[str, Any]) -> bool:
    """Check if a codex account with refresh_token needs proactive refresh."""
    refresh_token = str(account.get("refresh_token") or "").strip()
    if not refresh_token:
        return False

    # Check stored expires_at first (set by prior refresh)
    expires_raw = account.get("expires_at")
    if expires_raw:
        try:
            expires_at = float(expires_raw)
            if expires_at - time.time() > REFRESH_THRESHOLD_SECONDS:
                return False
            return True
        except (ValueError, TypeError):
            pass

    # Fall back to JWT exp claim
    access_token = str(account.get("access_token") or "")
    if not access_token:
        return False
    payload = _decode_jwt_payload(access_token)
    if not payload:
        return False
    exp = int(payload.get("exp") or 0)
    if exp == 0:
        return False
    return (exp - time.time()) <= REFRESH_THRESHOLD_SECONDS


def _refresh_one(account: dict[str, Any]) -> dict[str, Any] | None:
    """Refresh a single codex account's OAuth token.

    Returns updated account dict (with new access_token + refresh_token +
    expires_at) or None if refresh was skipped or failed.
    """
    refresh_token = str(account.get("refresh_token") or "").strip()
    if not refresh_token:
        return None

    device_id = str(account.get("device_id") or "").strip() or None

    try:
        result = refresh_codex_token(refresh_token, device_id)
    except Exception as exc:
        logger.warning({
            "event": "codex_refresh_scheduler_error",
            "token_preview": refresh_token[:16],
            "error": str(exc)[:120],
        })
        return None

    if result is None:
        return None  # transient error

    if result.get("error") == "unrecoverable":
        code = result.get("code", "unknown")
        logger.warning({
            "event": "codex_refresh_unrecoverable_scheduled",
            "code": code,
            "hint": "account refresh_token expired or revoked",
        })
        # Don't mark disabled here — let the reactive 401 path handle that.
        # The refresh_token may still be usable by the reactive path with
        # different timing.
        return None

    new_access = str(result.get("access_token") or "")
    new_refresh = str(result.get("refresh_token") or refresh_token)
    new_expires_at = result.get("expires_at", 0.0)

    if not new_access or new_access == account.get("access_token"):
        return None

    email = str(account.get("email") or "")[:40]
    logger.info({
        "event": "codex_oauth_refreshed",
        "email": email,
        "expires_in_h": round((new_expires_at - time.time()) / 3600, 1) if new_expires_at else 0,
    })

    return {
        **account,
        "access_token": new_access,
        "refresh_token": new_refresh,
        "expires_at": new_expires_at,
        "codex_refreshed_at": int(time.time()),
    }


def _scan_and_refresh() -> None:
    """Scan all codex accounts and refresh any near-expiry OAuth tokens."""
    try:
        from services.account_service import account_service
    except Exception as exc:
        logger.warning({"event": "codex_refresh_no_account_service", "error": str(exc)[:120]})
        return

    try:
        accounts = account_service.list_accounts()
    except Exception as exc:
        logger.warning({"event": "codex_refresh_list_failed", "error": str(exc)[:120]})
        return

    refreshed = 0
    skipped = 0
    for acc in list(accounts):
        try:
            # Per-account jitter: spread bursts across the scan window.
            time.sleep(random.uniform(0, PER_ACCOUNT_JITTER_SECONDS))

            if not _needs_refresh(acc):
                skipped += 1
                continue

            updated = _refresh_one(acc)
            if updated:
                try:
                    account_service.update_account(acc.get("access_token"), updated)
                    refreshed += 1
                except Exception as exc:
                    logger.warning({
                        "event": "codex_refresh_save_failed",
                        "error": str(exc)[:120],
                    })
        except Exception as exc:
            logger.warning({"event": "codex_refresh_one_crashed", "error": str(exc)[:120]})

    if refreshed or skipped > 0:
        logger.info({
            "event": "codex_refresh_cycle_done",
            "refreshed": refreshed,
            "scanned": refreshed + skipped,
        })


def _scheduler_loop() -> None:
    """Background loop: scan + refresh codex OAuth tokens on a jittered interval."""
    time.sleep(30)  # wait for server to fully start
    while True:
        try:
            _scan_and_refresh()
        except Exception as exc:
            logger.warning({"event": "codex_refresh_loop_error", "error": str(exc)[:120]})
        jitter = random.uniform(-SCAN_INTERVAL_JITTER_SECONDS, SCAN_INTERVAL_JITTER_SECONDS)
        time.sleep(max(60, SCAN_INTERVAL_SECONDS + jitter))


def start() -> None:
    """Start the background scheduler (idempotent)."""
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="codex-refresh-scheduler")
    t.start()
    logger.info({
        "event": "codex_refresh_scheduler_started",
        "interval_h": SCAN_INTERVAL_SECONDS / 3600,
        "threshold_h": REFRESH_THRESHOLD_SECONDS / 3600,
    })
