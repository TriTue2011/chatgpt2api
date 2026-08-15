"""Cloudflare Tunnel manager — auto-start/stop cloudflared subprocess.

Paste your Cloudflare Tunnel token in Settings UI → tunnel auto-starts.
Auto-restarts on crash (monitored every 30s).
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

from services.config import config

logger = logging.getLogger(__name__)

_tunnel_process: subprocess.Popen | None = None
_lock = threading.Lock()
_monitor_started = False


def _token() -> str:
    return str(config.get().get("cloudflare_tunnel_token", "")).strip()


def _co_tien_trinh_he_thong() -> bool:
    """Có cloudflared nào ĐANG chạy trên máy không (kể cả của tiến trình app cũ).

    Vì sao cần: `_tunnel_process` chỉ là tay cầm TRONG tiến trình. App khởi động
    lại (deploy, health-restart, Portainer update) là mất tay cầm, nên
    `start_tunnel()` tưởng chưa có và đẻ THÊM một cloudflared, còn cái cũ mồ côi
    vẫn chạy. Đo thật 31/07: sau vài lượt restart có 2 cloudflared cùng token
    cùng sống — mỗi lần restart lại rò thêm một tiến trình.
    """
    try:
        import subprocess as _sp
        r = _sp.run(["pgrep", "-x", "cloudflared"], capture_output=True, text=True, timeout=5)
        return bool((r.stdout or "").strip())
    except Exception:
        return False


def is_running() -> bool:
    with _lock:
        if _tunnel_process is not None and _tunnel_process.poll() is None:
            return True
    # Tay cầm mất (app vừa restart) nhưng tiến trình cũ có thể vẫn sống.
    return _co_tien_trinh_he_thong()


def start_tunnel() -> bool:
    global _tunnel_process
    token = _token()
    if not token:
        return False

    with _lock:
        if _tunnel_process is not None and _tunnel_process.poll() is None:
            return True
        # Sau restart app, tay cầm Python mất nhưng cloudflared cũ có thể vẫn
        # chạy. Không spawn thêm tunnel cùng token; process đó vẫn phục vụ được
        # và operator có thể restart có chủ đích nếu cần lấy lại ownership.
        if _co_tien_trinh_he_thong():
            logger.warning("Cloudflare Tunnel is already running without a local handle")
            return True
        try:
            _tunnel_process = subprocess.Popen(
                ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token", token],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            time.sleep(2)
            if _tunnel_process.poll() is not None:
                stderr = _tunnel_process.stderr.read() if _tunnel_process.stderr else ""
                logger.error("Cloudflare Tunnel failed: %s", stderr[:300])
                _tunnel_process = None
                return False
            logger.info("Cloudflare Tunnel started (PID %d)", _tunnel_process.pid)
            return True
        except FileNotFoundError:
            logger.warning("cloudflared not installed")
            return False
        except Exception as exc:
            logger.error("Tunnel start error: %s", exc)
            return False


def stop_tunnel() -> bool:
    global _tunnel_process
    with _lock:
        if _tunnel_process is None:
            return True
        try:
            _tunnel_process.terminate()
            _tunnel_process.wait(timeout=10)
            _tunnel_process = None
            return True
        except Exception:
            try:
                _tunnel_process.kill()
                _tunnel_process.wait(timeout=5)
            except Exception:
                pass
            _tunnel_process = None
            return True


def restart_tunnel() -> bool:
    stop_tunnel()
    return start_tunnel()


def _monitor_loop() -> None:
    global _tunnel_process
    while True:
        time.sleep(30)
        try:
            token = _token()
            if not token:
                continue
            with _lock:
                if _tunnel_process is not None and _tunnel_process.poll() is not None:
                    logger.warning("Tunnel crashed (exit %d), restarting", _tunnel_process.returncode)
                    _tunnel_process = None
            if not is_running() and token:
                start_tunnel()
        except Exception:
            pass


def start_monitor() -> None:
    global _monitor_started
    if _monitor_started:
        return
    _monitor_started = True
    t = threading.Thread(target=_monitor_loop, daemon=True, name="cf-monitor")
    t.start()


def get_status() -> dict:
    return {"running": is_running(), "token_configured": bool(_token())}
