"""Bootstrap các pyscript file mà gateway phụ thuộc trên Home Assistant.

Nếu HA THIẾU service pyscript cần thiết (ai_file_ops để ghi/đọc file config,
create_automation_by_ai để tạo automation) → gateway KHÔNG tự ý cài; nó trả câu
xin phép user. User đồng ý ("đồng ý cài pyscript") → model gọi tool
ha_pyscript_setup(consent=true) → hàm install() SFTP asset lên HA qua SSH
(config home_assistant.ssh_*, chỉ lưu cục bộ, KHÔNG commit) rồi reload pyscript
qua REST và verify service đã xuất hiện.

Nguồn pyscript = file asset trong repo (services/ha_assets/*.py) → version-control
chuẩn, không nhét chuỗi khổng lồ vào code.
"""
from __future__ import annotations

import os
import time
from urllib.parse import urlparse

from services.config import config
from utils.log import logger

_ASSET_DIR = os.path.join(os.path.dirname(__file__), "ha_assets")

# name → service pyscript nó cung cấp + file asset + mô tả cho user.
DEPS: dict[str, dict[str, str]] = {
    "ai_file_ops": {
        "service": "ai_file_ops",
        "asset": "ai_file_ops.py",
        "desc": "ghi/đọc file cấu hình HA (helper, blueprint, configuration.yaml)",
    },
    "create_automation_by_ai": {
        "service": "create_automation_by_ai",
        "asset": "create_automation_by_ai.py",
        "desc": "tạo automation",
    },
}

_present_cache: dict[str, tuple[float, bool]] = {}
_PRESENT_TTL = 300.0


def _ssh_conf() -> dict | None:
    """SSH tới máy HA để ghi file pyscript. Lấy từ config home_assistant:
    ssh_host (mặc định = host trong url), ssh_port, ssh_user, ssh_pass,
    config_dir (thư mục config HA trên máy đó, mặc định /config)."""
    ha = config.data.get("home_assistant") or {}
    host = str(ha.get("ssh_host") or "").strip()
    if not host and ha.get("url"):
        try:
            host = urlparse(str(ha["url"])).hostname or ""
        except Exception:
            host = ""
    user = str(ha.get("ssh_user") or "").strip()
    pw = str(ha.get("ssh_pass") or "")
    if not (host and user and pw):
        return None
    return {
        "host": host,
        "port": int(ha.get("ssh_port") or 22),
        "user": user,
        "pw": pw,
        "config_dir": str(ha.get("config_dir") or "/config").rstrip("/"),
    }


def _service_present(service: str, use_cache: bool = True) -> bool:
    """HA có service pyscript.<service> không? Qua REST /api/services."""
    now = time.time()
    if use_cache:
        c = _present_cache.get(service)
        if c and now - c[0] < _PRESENT_TTL:
            return c[1]
    present = False
    try:
        from services.ha_client import _api_request
        code, body = _api_request("GET", "/api/services", timeout=12)
        if code == 200 and body:
            import json
            for dom in json.loads(body):
                if dom.get("domain") == "pyscript" and service in (dom.get("services") or {}):
                    present = True
                    break
    except Exception as exc:
        logger.warning({"event": "pyscript_probe_failed", "service": service, "error": str(exc)[:120]})
        return True  # đừng chặn oan khi không probe được
    _present_cache[service] = (now, present)
    return present


def missing(names: list[str]) -> list[str]:
    return [n for n in names if n in DEPS and not _service_present(DEPS[n]["service"])]


def consent_message(names: list[str]) -> str:
    items = "; ".join(f"{n} ({DEPS[n]['desc']})" for n in names if n in DEPS)
    return (f"⚠️ Home Assistant chưa có công cụ cần thiết: {items}. "
            "Bạn có ĐỒNG Ý cho tôi tự cài lên HA không? "
            "Nhắn 'đồng ý cài pyscript' để tôi cài, rồi thử lại yêu cầu.")


def install(names: list[str] | None = None) -> tuple[bool, str]:
    """Cài các pyscript còn thiếu (hoặc `names`) lên HA qua SSH + reload."""
    targets = names or list(DEPS.keys())
    todo = missing(targets)
    if not todo:
        return True, "✅ HA đã có đủ công cụ pyscript, không cần cài thêm."
    ssh = _ssh_conf()
    if not ssh:
        return False, ("❌ Chưa cấu hình SSH tới HA (home_assistant.ssh_host/ssh_user/"
                       "ssh_pass trong config gateway) nên không thể tự cài. "
                       "Cần thêm cấu hình đó rồi thử lại.")
    try:
        import paramiko
    except Exception:
        return False, "❌ Gateway thiếu paramiko để SSH cài pyscript."
    installed = []
    try:
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507 — SSH noi bo HA .200, creds tu config
        cli.connect(ssh["host"], port=ssh["port"], username=ssh["user"],
                    password=ssh["pw"], timeout=20)
        sftp = cli.open_sftp()
        remote_dir = ssh["config_dir"] + "/pyscript"
        try:
            sftp.stat(remote_dir)
        except IOError:
            cli.exec_command(f"mkdir -p {remote_dir}")[1].channel.recv_exit_status()
        for n in todo:
            asset = os.path.join(_ASSET_DIR, DEPS[n]["asset"])
            with open(asset, "rb") as f:
                data = f.read()
            rf = sftp.open(f"{remote_dir}/{DEPS[n]['asset']}", "wb")
            rf.write(data)
            rf.close()
            installed.append(n)
        sftp.close()
        cli.close()
    except Exception as exc:
        return False, f"❌ Lỗi SSH cài pyscript: {str(exc)[:200]}"

    # Reload pyscript (2 lần cho chắc — module/file mới đôi khi cần) + xoá cache.
    try:
        from services.ha_client import _api_request
        _api_request("POST", "/api/services/pyscript/reload", {}, timeout=30)
        time.sleep(2)
        _api_request("POST", "/api/services/pyscript/reload", {}, timeout=30)
        time.sleep(2)
    except Exception:
        pass
    _present_cache.clear()
    still = missing(installed)
    if still:
        return False, (f"⚠️ Đã ghi file {', '.join(installed)} nhưng HA chưa thấy "
                       f"service {', '.join(still)} sau reload — thử lại sau vài giây.")
    return True, f"✅ Đã tự cài + kích hoạt pyscript trên HA: {', '.join(installed)}."


def ensure(names: list[str], consent: bool = False) -> tuple[bool, str]:
    """(ready, message). ready=True nếu đủ. Thiếu + chưa consent → câu xin phép;
    thiếu + consent → cài rồi báo kết quả."""
    todo = missing(names)
    if not todo:
        return True, ""
    if consent:
        ok, msg = install(todo)
        return ok, msg
    return False, consent_message(todo)
