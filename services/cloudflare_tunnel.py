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


def _giet_tien_trinh_he_thong() -> bool:
    """Giết cloudflared mồ côi. True nếu sau đó máy không còn cloudflared nào.

    Chỉ dùng cho hành động CÓ CHỦ ĐÍCH của người vận hành (đổi token, bấm
    Restart). Đường tự động thì thấy tiến trình cũ là nhường, vì giết nó lúc
    khởi động app nghĩa là mỗi lần deploy lại cắt tunnel đang phục vụ.
    """
    try:
        subprocess.run(["pkill", "-x", "cloudflared"], capture_output=True, timeout=5)
    except Exception as exc:
        logger.warning("không gọi được pkill cloudflared: %s", exc)
        return False
    for _ in range(10):
        if not _co_tien_trinh_he_thong():
            return True
        time.sleep(0.5)
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


def stop_tunnel(*, ke_ca_mo_coi: bool = False) -> bool:
    global _tunnel_process
    with _lock:
        if _tunnel_process is not None:
            try:
                _tunnel_process.terminate()
                _tunnel_process.wait(timeout=10)
            except Exception:
                try:
                    _tunnel_process.kill()
                    _tunnel_process.wait(timeout=5)
                except Exception:
                    pass
            _tunnel_process = None
        # Tay cầm mất sau khi app restart nhưng cloudflared cũ vẫn chạy bằng
        # token CŨ. Không giết nó thì `start_tunnel` thấy nó rồi nhường, và
        # token mới không bao giờ được áp — trong khi giao diện báo thành công.
        if ke_ca_mo_coi and _co_tien_trinh_he_thong():
            _giet_tien_trinh_he_thong()
        return True


def restart_tunnel() -> bool:
    """Chạy lại tunnel bằng token HIỆN TẠI — dùng cho người vận hành.

    Khác đường tự động đúng một chỗ: nó giành lại quyền sở hữu, kể cả khi
    cloudflared đang chạy là tiến trình mồ côi của một lần chạy app trước.
    """
    stop_tunnel(ke_ca_mo_coi=True)
    if _co_tien_trinh_he_thong():
        logger.error("còn cloudflared cũ không giết được — token mới CHƯA áp dụng")
        return False
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
