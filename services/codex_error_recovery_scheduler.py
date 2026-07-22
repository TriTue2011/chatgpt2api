"""Periodic multi-tier recovery for dead Codex / ChatGPT-free accounts.

Accounts with status ``error`` / ``disabled`` are skipped by the request pool
and never hit the 401 path that spawns T0–T3 recovery. This scheduler:

1. Scans the pool for dead codex/free accounts.
2. Tries **T0** (OAuth refresh_token) via ``recover_and_notify``.
3. On T0 failure, runs **T1–T3** via ``recover_provider_account``
   (Google ride → Google re-login → bulk onboard).

Also exposes ``schedule_dead_account_recovery`` for immediate spawn when an
account is marked error/disabled mid-request.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Any

from utils.log import logger

# First scan after boot (let captcha-solver / browser stack warm up).
_BOOT_DELAY_S = 90.0
# Full pool scan interval (~2h ± 20min).
_SCAN_INTERVAL_S = 2 * 3600
_SCAN_JITTER_S = 20 * 60
# Cap browser-heavy recoveries per cycle (T1–T3 cost captcha + time).
_MAX_PER_CYCLE = 2
# Skip account if we already attempted recovery this recently (extra safety;
# account_recovery has its own debounce too).
_PER_ACCOUNT_MIN_GAP_S = 45 * 60

_started = False
_last_try: dict[str, float] = {}
_try_lock = threading.Lock()


def _cfg() -> dict[str, Any]:
    try:
        from services.config import config

        raw = (config.data or {}).get("codex_error_recovery")
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def is_enabled() -> bool:
    cfg = _cfg()
    if "enabled" in cfg:
        return bool(cfg.get("enabled"))
    return True  # on by default


def _max_per_cycle() -> int:
    try:
        return max(1, min(5, int(_cfg().get("max_per_cycle") or _MAX_PER_CYCLE)))
    except (TypeError, ValueError):
        return _MAX_PER_CYCLE


def _interval_s() -> float:
    try:
        h = float(_cfg().get("interval_hours") or (_SCAN_INTERVAL_S / 3600))
        return max(30 * 60, h * 3600)
    except (TypeError, ValueError):
        return float(_SCAN_INTERVAL_S)


def _account_key(acc: dict[str, Any]) -> str:
    em = str(acc.get("email") or "").strip().lower()
    if em:
        return em
    return str(acc.get("access_token") or "")[:40]


def _should_skip(acc: dict[str, Any]) -> bool:
    key = _account_key(acc)
    with _try_lock:
        last = _last_try.get(key, 0.0)
        return (time.time() - last) < _PER_ACCOUNT_MIN_GAP_S


def _mark_tried(acc: dict[str, Any]) -> None:
    key = _account_key(acc)
    with _try_lock:
        _last_try[key] = time.time()


def _is_recoverable_group(acc: dict[str, Any]) -> str:
    """Return provider key for recovery, or '' if not handled."""
    try:
        from services.account_service import account_group

        g = account_group(acc) or ""
    except Exception:
        g = ""
    t = str(acc.get("type") or "") + "," + str(acc.get("provider") or "")
    if g == "codex" or "codex" in t.lower():
        return "codex"
    if g in {"free", "chatgpt_free"} or "free" in t.lower():
        return "free"
    # JWT-looking + refresh_token often Codex
    tok = str(acc.get("access_token") or "")
    if tok.startswith("eyJ") and acc.get("refresh_token"):
        return "codex"
    return ""


def _list_dead_accounts() -> list[dict[str, Any]]:
    from services.account_service import account_service

    out: list[dict[str, Any]] = []
    with account_service._lock:
        for tok, acc in list(account_service._accounts.items()):
            if not isinstance(acc, dict):
                continue
            st = str(acc.get("status") or "").lower()
            if st not in {"error", "disabled"}:
                continue
            snap = dict(acc)
            if "access_token" not in snap:
                snap["access_token"] = tok
            if not _is_recoverable_group(snap):
                continue
            out.append(snap)
    # Prefer accounts that still have refresh_token (cheaper T0)
    out.sort(key=lambda a: (0 if a.get("refresh_token") else 1, str(a.get("email") or "")))
    return out


def recover_dead_account(account: dict[str, Any], reason: str = "dead_status") -> bool:
    """Run T0 then T1–T3 for one dead account. Returns True if revived to active."""
    if not isinstance(account, dict):
        return False
    if not is_enabled():
        return False
    if _should_skip(account):
        logger.info({
            "event": "dead_recovery_skip_gap",
            "email": str(account.get("email") or "")[:60],
        })
        return False
    _mark_tried(account)

    provider = _is_recoverable_group(account)
    if not provider:
        return False

    email = str(account.get("email") or "")[:80]
    logger.info({
        "event": "dead_recovery_start",
        "email": email,
        "provider": provider,
        "status": account.get("status"),
        "reason": str(reason)[:120],
        "has_refresh": bool(account.get("refresh_token")),
    })

    # ── T0: OAuth refresh ──────────────────────────────────────────────
    try:
        from services.account_recovery import recover_and_notify

        new_tok = recover_and_notify(account, reason=f"dead:{reason}")
        if new_tok:
            _force_active_if_needed(new_tok, email)
            logger.info({"event": "dead_recovery_ok", "tier": "T0", "email": email})
            return True
    except Exception as exc:
        logger.warning({
            "event": "dead_recovery_t0_error",
            "email": email,
            "error": str(exc)[:160],
        })

    # ── T1–T3: browser multi-tier ─────────────────────────────────────
    try:
        from services.account_recovery import recover_provider_account

        recover_provider_account(account, provider, reason=f"dead:{reason}")
    except Exception as exc:
        logger.warning({
            "event": "dead_recovery_t13_error",
            "email": email,
            "error": str(exc)[:160],
        })
        return False

    # Check if any active account for this email appeared
    if _email_has_active(email):
        logger.info({"event": "dead_recovery_ok", "tier": "T1-T3", "email": email})
        return True

    logger.warning({"event": "dead_recovery_failed", "email": email, "reason": reason[:80]})
    return False


def _force_active_if_needed(access_token: str, email: str) -> None:
    try:
        from services.account_service import account_service

        acc = account_service.get_account(access_token)
        if acc and str(acc.get("status") or "") != "active":
            account_service.update_account(access_token, {"status": "active", "quota": 0})
    except Exception:
        pass


def _email_has_active(email: str) -> bool:
    if not email:
        return False
    try:
        from services.account_service import account_service

        em = email.lower()
        with account_service._lock:
            for acc in account_service._accounts.values():
                if not isinstance(acc, dict):
                    continue
                if str(acc.get("email") or "").lower() != em:
                    continue
                if str(acc.get("status") or "") == "active":
                    return True
    except Exception:
        pass
    return False


def schedule_dead_account_recovery(
    account: dict[str, Any] | None,
    reason: str = "marked_error",
) -> None:
    """Fire-and-forget recovery when an account is marked error/disabled."""
    if not account or not is_enabled():
        return
    if not _is_recoverable_group(account):
        return
    snap = dict(account)

    def _run() -> None:
        try:
            recover_dead_account(snap, reason=reason)
        except Exception as exc:
            logger.warning({
                "event": "dead_recovery_spawn_error",
                "error": str(exc)[:160],
            })

    threading.Thread(
        target=_run,
        name=f"dead-recover-{(snap.get('email') or 'x')[:20]}",
        daemon=True,
    ).start()


def _scan_and_recover() -> None:
    if not is_enabled():
        return
    dead = _list_dead_accounts()
    if not dead:
        logger.info({"event": "dead_recovery_scan", "dead": 0, "tried": 0})
        return

    cap = _max_per_cycle()
    tried = 0
    ok = 0
    for acc in dead:
        if tried >= cap:
            break
        if _should_skip(acc):
            continue
        tried += 1
        try:
            if recover_dead_account(acc, reason="periodic_scan"):
                ok += 1
        except Exception as exc:
            logger.warning({
                "event": "dead_recovery_one_error",
                "email": str(acc.get("email") or "")[:60],
                "error": str(exc)[:120],
            })

    logger.info({
        "event": "dead_recovery_scan",
        "dead": len(dead),
        "tried": tried,
        "ok": ok,
        "max_per_cycle": cap,
    })


def _loop() -> None:
    time.sleep(_BOOT_DELAY_S)
    while True:
        try:
            _scan_and_recover()
        except Exception as exc:
            logger.warning({
                "event": "dead_recovery_loop_error",
                "error": str(exc)[:160],
            })
        base = _interval_s()
        jitter = random.uniform(-_SCAN_JITTER_S, _SCAN_JITTER_S)
        time.sleep(max(60.0, base + jitter))


def start() -> None:
    """Start background dead-account recovery (idempotent)."""
    global _started
    if _started:
        return
    if not is_enabled():
        logger.info({"event": "dead_recovery_scheduler_disabled"})
        return
    _started = True
    t = threading.Thread(target=_loop, daemon=True, name="codex-error-recovery")
    t.start()
    logger.info({
        "event": "dead_recovery_scheduler_started",
        "interval_h": _interval_s() / 3600,
        "max_per_cycle": _max_per_cycle(),
        "boot_delay_s": _BOOT_DELAY_S,
    })
