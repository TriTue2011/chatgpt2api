"""Quét định kỳ phiên Flow (labs.google) và đăng nhập lại tài khoản mất phiên.

VÌ SAO CẦN: tài khoản Flow mất phiên chỉ được sửa qua đúng MỘT đường — nhánh
xử lý lỗi của adapter tạo ảnh (``services/image_providers/flow_google.py``) bắn
``flow_recover_and_notify`` khi tài khoản đó lỗi giữa lúc dùng. Đường đó có một
vòng khép kín:

  1. Tài khoản lỗi → ``_reorder_flow_account(to_front=False)`` đẩy nó xuống CUỐI
     danh sách.
  2. ``_next_account()`` chọn theo ưu tiên CỨNG theo thứ tự: index 0 trước, chỉ
     nhảy tiếp khi index 0 đang cooldown.
  3. Nên tài khoản đã bị đẩy xuống cuối KHÔNG BAO GIỜ được chọn nữa → không bao
     giờ lỗi thêm → không bao giờ có ai gọi khôi phục cho nó.

Đo thật 02/08: tài khoản nhãn "Main" (``google-benbap115``) bị đăng xuất Google,
nằm ở vị trí CUỐI (thứ tự thật: Backup, Spare 1, Spare 2, Main), và suốt 24 giờ
log chỉ có ``flow_account_chosen: Backup``. Mật khẩu + TOTP của nó vẫn nằm trong
solver, tức khôi phục được ngay — chỉ là chẳng có gì gọi. Đường tạo VIDEO
(``api/veo_video.py``) thì không có móc khôi phục nào cả.

Bộ quét này cắt vòng đó: định kỳ tự kiểm phiên từng tài khoản Flow, cái nào chết
thì gọi đúng ``flow_recover_and_notify`` (T1 kiểm/tái lập phiên → T2 đăng nhập
lại Google). Không phụ thuộc việc tài khoản có được traffic chạm tới hay không.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Any

from utils.log import logger

# Lần quét đầu sau khi khởi động (chờ browser/captcha-solver ấm máy).
_BOOT_DELAY_S = 150.0
# Chu kỳ quét (~3h ± 20 phút).
_SCAN_INTERVAL_S = 3 * 3600
_SCAN_JITTER_S = 20 * 60
# Kiểm phiên phải MỞ TRÌNH DUYỆT (get-or-create-project, tới 150s) nên chặn số
# tài khoản mỗi vòng, kẻo một lượt quét giành browser_pool với traffic thật và
# request của người dùng nhận "Account Busy".
_MAX_PER_CYCLE = 2
# Vừa kiểm tài khoản này rồi thì đừng kiểm lại quá sớm.
_PER_ACCOUNT_MIN_GAP_S = 2 * 3600

_started = False
_last_check: dict[str, float] = {}
_lock = threading.Lock()


def _cfg() -> dict[str, Any]:
    try:
        from services.config import config

        raw = (config.data or {}).get("flow_session_scan")
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def is_enabled() -> bool:
    cfg = _cfg()
    if "enabled" in cfg:
        return bool(cfg.get("enabled"))
    return True  # bật mặc định


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


def _profiles() -> list[str]:
    """Profile Google của các tài khoản Flow, theo thứ tự trong cấu hình.

    Chỉ nhận ``google-*``: đăng nhập lại cần profile Google có mật khẩu/TOTP
    trong solver, profile kiểu khác không có đường nào để mà đăng nhập.
    """
    try:
        from services.image_providers.flow_google import _pool_config

        accounts = (_pool_config() or {}).get("accounts") or []
    except Exception as exc:
        logger.warning({"event": "flow_scan_cfg_error", "error": str(exc)[:120]})
        return []
    out: list[str] = []
    for acc in accounts:
        if not isinstance(acc, dict) or acc.get("disabled"):
            continue
        p = str(acc.get("profile") or "").strip()
        if p.startswith("google-") and p not in out:
            out.append(p)
    return out


def _scan_once() -> None:
    if not is_enabled():
        return
    from services.account_recovery import _flow_session_trang_thai, flow_recover_and_notify

    profiles = _profiles()
    if not profiles:
        logger.info({"event": "flow_session_scan", "profiles": 0})
        return

    # Xoay vòng công bằng: cái lâu chưa kiểm nhất đi trước, nên tài khoản nằm
    # cuối danh sách (đúng những cái bị mắc kẹt) vẫn tới lượt.
    def _lan_cuoi(p: str) -> float:
        with _lock:
            return float(_last_check.get(p, 0.0))

    profiles.sort(key=_lan_cuoi)

    cap = _max_per_cycle()
    da_kiem = 0
    chet = 0
    ban = 0
    now = time.time()
    for profile in profiles:
        if da_kiem >= cap:
            break
        if now - _lan_cuoi(profile) < _PER_ACCOUNT_MIN_GAP_S:
            continue
        with _lock:
            _last_check[profile] = now
        da_kiem += 1
        try:
            tt = _flow_session_trang_thai(profile)
            if tt == "ok":
                continue
            if tt == "ban":
                # Hồ sơ đang tạo ảnh/video → `pool.page()` fast-failover 429.
                # Đó là tài khoản KHOẺ nhất có thể, không phải mất phiên. Bỏ
                # qua lượt này, vòng sau kiểm lại.
                ban += 1
                logger.info({"event": "flow_session_busy", "profile": profile})
                continue
            chet += 1
            logger.warning({"event": "flow_session_dead", "profile": profile})
            # Hàm này tự debounce 30 phút/profile và tự báo Telegram từng bước.
            flow_recover_and_notify(profile, reason="quét định kỳ: mất phiên labs.google")
        except Exception as exc:
            logger.warning({
                "event": "flow_session_check_error",
                "profile": profile,
                "error": str(exc)[:160],
            })

    logger.info({
        "event": "flow_session_scan",
        "profiles": len(profiles),
        "checked": da_kiem,
        "dead": chet,
        "busy": ban,
        "max_per_cycle": cap,
    })


def _loop() -> None:
    time.sleep(_BOOT_DELAY_S)
    while True:
        try:
            _scan_once()
        except Exception as exc:
            logger.warning({"event": "flow_session_loop_error", "error": str(exc)[:160]})
        base = _interval_s()
        time.sleep(max(60.0, base + random.uniform(-_SCAN_JITTER_S, _SCAN_JITTER_S)))


def start() -> None:
    """Khởi động bộ quét phiên Flow chạy nền (gọi nhiều lần cũng chỉ chạy 1)."""
    global _started
    if _started:
        return
    if not is_enabled():
        logger.info({"event": "flow_session_scheduler_disabled"})
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="flow-session-scan").start()
    logger.info({
        "event": "flow_session_scheduler_started",
        "interval_h": _interval_s() / 3600,
        "max_per_cycle": _max_per_cycle(),
        "boot_delay_s": _BOOT_DELAY_S,
    })
