"""Quét định kỳ phiên Claude / ChatGPT free / Gemini web, giữ phiên sống giống
`flow_session_scheduler.py` — nhưng RẺ HƠN Flow.

VÌ SAO RẺ HƠN: kiểm phiên Flow bắt buộc mở một trang trình duyệt
(`check-project`), nên phải giới hạn nghiêm số tài khoản mỗi vòng. Ba provider
ở đây nói chuyện thẳng bằng HTTP (cookie/JWT đã có), không cần trình duyệt cho
BƯỚC KIỂM — xem `services/account_recovery.py::_claude_session_trang_thai` /
`_cgf_session_trang_thai` / `_gma_session_trang_thai`. Chỉ khi kiểm ra 'mat'
(cần đăng nhập lại Google) mới chạm tới `_freshen_google` (trình duyệt, hàng
đợi toàn cục dùng chung với Flow).

TẮT MẶC ĐỊNH (chủ máy chốt khi thiết kế): thêm traffic nền đều đặn tới
claude.ai/chatgpt.com/gemini.google.com là rủi ro bị để ý, nên để chủ máy tự
bật qua cấu hình `web_session_scan.enabled` khi sẵn sàng — giống đúng quyết
định 05/09 với Flow.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Any

from utils.log import logger

_BOOT_DELAY_S = 150.0
_SCAN_INTERVAL_S = 3 * 3600
_SCAN_JITTER_S = 20 * 60
# Kiểm không mở trình duyệt nên rẻ hơn Flow nhiều, nhưng vẫn giới hạn để một
# vòng quét không dựng hàng loạt request cùng lúc.
_MAX_PER_CYCLE = 3
_PER_ACCOUNT_MIN_GAP_S = 2 * 3600

_started = False
_last_check: dict[str, float] = {}
_lock = threading.Lock()


def _cfg() -> dict[str, Any]:
    try:
        from services.config import config

        raw = (config.data or {}).get("web_session_scan")
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", False))


def _max_per_cycle() -> int:
    try:
        return max(1, min(10, int(_cfg().get("max_per_cycle") or _MAX_PER_CYCLE)))
    except (TypeError, ValueError):
        return _MAX_PER_CYCLE


def _interval_s() -> float:
    try:
        h = float(_cfg().get("interval_hours") or (_SCAN_INTERVAL_S / 3600))
        return max(30 * 60, h * 3600)
    except (TypeError, ValueError):
        return float(_SCAN_INTERVAL_S)


def _lan_cuoi(khoa: str) -> float:
    with _lock:
        return float(_last_check.get(khoa, 0.0))


def _danh_dau(khoa: str, now: float) -> None:
    with _lock:
        _last_check[khoa] = now


def _claude_profiles() -> list[str]:
    try:
        from api.claude import claude_profiles, _claude_cfg
        return claude_profiles(_claude_cfg())
    except Exception as exc:
        logger.warning({"event": "web_session_scan_claude_cfg_error", "error": str(exc)[:120]})
        return []


def _gma_profiles() -> list[str]:
    try:
        from api.gemini_web import _profiles
        return _profiles()
    except Exception as exc:
        logger.warning({"event": "web_session_scan_gma_cfg_error", "error": str(exc)[:120]})
        return []


def _free_accounts() -> list[dict[str, Any]]:
    """Tài khoản ChatGPT free ĐÃ CÓ trong kho (chỉ quét cái đã thêm tay, không
    tự thêm — cùng luật với `_cgf_ghi_pool`)."""
    try:
        from services.account_service import account_service, account_group
        with account_service._lock:
            ra, seen = [], set()
            for a in account_service._accounts.values():
                if not isinstance(a, dict) or account_group(a) != "free":
                    continue
                em = str(a.get("email") or "").lower()
                if em and em not in seen:
                    seen.add(em)
                    ra.append(dict(a))
            return ra
    except Exception as exc:
        logger.warning({"event": "web_session_scan_free_cfg_error", "error": str(exc)[:120]})
        return []


def _quet_mot_tang(provider: str, ids: list[str], cap: int, now: float,
                   trang_thai_fn, mat_fn) -> tuple[int, int, int]:
    """Vòng quét chung cho một tầng: trả (đã_kiểm, chết, bận). Mỗi ``ids[i]``
    là khoá xoay vòng (profile hoặc email); ``trang_thai_fn(id_)`` trả
    ok/ban/mat/chua_ro; ``mat_fn(id_)`` chỉ gọi khi 'mat'."""
    da_kiem = chet = ban = 0
    for id_ in sorted(ids, key=lambda x: _lan_cuoi(f"{provider}:{x}")):
        if da_kiem >= cap:
            break
        khoa = f"{provider}:{id_}"
        if now - _lan_cuoi(khoa) < _PER_ACCOUNT_MIN_GAP_S:
            continue
        _danh_dau(khoa, now)
        da_kiem += 1
        try:
            tt = trang_thai_fn(id_)
        except Exception as exc:
            logger.warning({"event": "web_session_scan_check_error", "provider": provider,
                            "id": id_[:60], "error": str(exc)[:160]})
            continue
        if tt == "ok":
            continue
        if tt in ("ban", "chua_ro"):
            ban += 1
            continue
        chet += 1
        logger.info({"event": "web_session_scan_dead", "provider": provider, "id": id_[:60]})
        try:
            mat_fn(id_)
        except Exception as exc:
            logger.warning({"event": "web_session_scan_recover_error", "provider": provider,
                            "id": id_[:60], "error": str(exc)[:160]})
    return da_kiem, chet, ban


def _scan_once() -> None:
    if not is_enabled():
        return
    from services.account_recovery import (
        _claude_session_trang_thai, claude_recover_and_notify,
        _gma_session_trang_thai, gma_recover_and_notify,
        _cgf_session_trang_thai, recover_provider_account,
    )

    cap = _max_per_cycle()
    now = time.time()
    tong: dict[str, tuple[int, int, int]] = {}

    tong["claude"] = _quet_mot_tang(
        "claude", _claude_profiles(), cap, now,
        _claude_session_trang_thai,
        lambda p: claude_recover_and_notify(p, reason="quét định kỳ: mất phiên claude.ai"))

    tong["gemini_web_api"] = _quet_mot_tang(
        "gma", _gma_profiles(), cap, now,
        _gma_session_trang_thai,
        lambda p: gma_recover_and_notify(p, reason="quét định kỳ: mất phiên"))

    free_accs = {str(a.get("email") or "").lower(): a for a in _free_accounts()}
    tong["free"] = _quet_mot_tang(
        "free", list(free_accs.keys()), cap, now,
        _cgf_session_trang_thai,
        lambda em: recover_provider_account(
            free_accs[em], "free", "quét định kỳ: mất phiên ChatGPT"))

    logger.info({"event": "web_session_scan", "max_per_cycle": cap,
                 **{f"{k}_{n}": v for k, vals in tong.items()
                    for n, v in zip(("checked", "dead", "busy"), vals)}})


def _loop() -> None:
    time.sleep(_BOOT_DELAY_S)
    while True:
        try:
            _scan_once()
        except Exception as exc:
            logger.warning({"event": "web_session_scan_loop_error", "error": str(exc)[:160]})
        base = _interval_s()
        time.sleep(max(60.0, base + random.uniform(-_SCAN_JITTER_S, _SCAN_JITTER_S)))


def start() -> None:
    """Khởi động bộ quét giữ phiên Claude/ChatGPT-free/Gemini-web (gọi nhiều
    lần cũng chỉ chạy 1). Tắt mặc định — bật qua `web_session_scan.enabled`."""
    global _started
    if _started:
        return
    if not is_enabled():
        logger.info({"event": "web_session_scheduler_disabled"})
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="web-session-scan").start()
    logger.info({
        "event": "web_session_scheduler_started",
        "interval_h": _interval_s() / 3600,
        "max_per_cycle": _max_per_cycle(),
        "boot_delay_s": _BOOT_DELAY_S,
    })


def _reset_for_tests() -> None:
    global _started
    _started = False
    with _lock:
        _last_check.clear()
