"""ssh_exec — SSH MCP tổng quát, chạy lệnh trên bất kỳ server nào đã khai báo.

Không gắn với Home Assistant. Cho phép AI Agent quản trị nhiều máy chủ (Linux
server, NAS, đầu ghi NVR, Raspberry Pi…) qua SSH: xem trạng thái, đọc log, chạy
lệnh, restart dịch vụ.

Bảo mật:
- Mật khẩu/khoá lưu trong /app/data/ssh_servers.json (server-side). Tool KHÔNG
  bao giờ trả mật khẩu về cho model — chỉ trả tên/host/user.
- Mỗi server có cờ `allow_dangerous` (mặc định False). Khi tắt, một số lệnh phá
  huỷ dữ liệu rõ ràng (rm -rf /, mkfs, dd of=/dev/…, fork bomb) bị chặn.

Tools:
- ssh_list_servers(): liệt kê server đã khai báo (không kèm mật khẩu)
- ssh_run(server, command, timeout): chạy lệnh, trả về exit code + stdout/stderr
- ssh_add_server(name, host, username, password, port, allow_dangerous): thêm server
- ssh_remove_server(name): xoá server
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

mcp = FastMCP("ssh_exec")

DATA_DIR = Path(os.getenv("VN_HUB_DATA_DIR", "/app/data"))
REGISTRY = DATA_DIR / "ssh_servers.json"
_LOCK = threading.Lock()

# Trần độ dài output trả về model để tránh phình context.
_MAX_OUTPUT = 8000

# Lệnh phá huỷ dữ liệu rõ ràng — chặn khi server chưa bật allow_dangerous.
_DANGEROUS = [
    re.compile(r"\brm\s+-[a-z]*r[a-z]*f?\s+(/|/\*|~\s|~/\s*$)"),
    re.compile(r"\brm\s+-[a-z]*f[a-z]*r?\s+(/|/\*)(\s|$)"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\b.*\bof=/dev/"),
    re.compile(r">\s*/dev/(sd|nvme|mmcblk|vd)"),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),  # fork bomb
    re.compile(r"\bmv\s+/\s+"),
]


# ── Registry ────────────────────────────────────────────────────────────────


def _read_registry() -> list[dict[str, Any]]:
    if not REGISTRY.exists():
        return []
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_registry(entries: list[dict[str, Any]]) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _find(name: str) -> dict[str, Any] | None:
    key = (name or "").strip().lower()
    for e in _read_registry():
        if str(e.get("name", "")).lower() == key:
            return e
    return None


def _norm_paths(paths: Any) -> list[str]:
    """Chuẩn hoá list thư mục (chấp nhận list hoặc chuỗi phân tách bằng dấu phẩy)."""
    if not paths:
        return []
    if isinstance(paths, str):
        paths = [p for p in paths.replace(",", "\n").splitlines()]
    out: list[str] = []
    for p in paths:
        p = str(p).strip().replace("\\", "/")
        if p:
            out.append(p)
    return out


def add_server(name: str, host: str, username: str, password: str = "",
               port: int = 22, key_path: str = "", allow_dangerous: bool = False,
               read_paths: Any = None, write_paths: Any = None) -> dict[str, Any]:
    """Thêm/cập nhật một server vào registry (dùng chung cho SSH + file MCP + REST).

    read_paths/write_paths: thư mục cho phép fs_remote ĐỌC/GHI. read rỗng = đọc
    mọi nơi (theo quyền OS của user); write rỗng = CẤM ghi (an toàn mặc định).
    """
    name = (name or "").strip()
    host = (host or "").strip()
    username = (username or "").strip()
    if not name or not host or not username:
        return {"ok": False, "error": "name, host, username là bắt buộc"}
    with _LOCK:
        prev = next((e for e in _read_registry() if str(e.get("name", "")).lower() == name.lower()), {})
        entries = [e for e in _read_registry() if str(e.get("name", "")).lower() != name.lower()]
        entries.append({
            "name": name, "host": host, "port": int(port or 22),
            "username": username, "password": password or prev.get("password", ""),
            "key_path": key_path or prev.get("key_path", ""),
            "allow_dangerous": bool(allow_dangerous),
            "read_paths": _norm_paths(read_paths) if read_paths is not None else prev.get("read_paths", []),
            "write_paths": _norm_paths(write_paths) if write_paths is not None else prev.get("write_paths", []),
        })
        _write_registry(entries)
    return {"ok": True, "name": name}


def set_paths(name: str, add_read: str = "", add_write: str = "",
              read_paths: Any = None, write_paths: Any = None) -> dict[str, Any]:
    """Cập nhật thư mục được phép đọc/ghi cho một server (dùng để cấp quyền qua chat).

    - add_read/add_write: THÊM một thư mục vào danh sách hiện có.
    - read_paths/write_paths: THAY THẾ toàn bộ danh sách.
    """
    with _LOCK:
        entries = _read_registry()
        entry = next((e for e in entries if str(e.get("name", "")).lower() == (name or "").strip().lower()), None)
        if entry is None:
            return {"ok": False, "error": f"Không tìm thấy server '{name}'"}
        if read_paths is not None:
            entry["read_paths"] = _norm_paths(read_paths)
        if write_paths is not None:
            entry["write_paths"] = _norm_paths(write_paths)
        if add_read:
            entry.setdefault("read_paths", [])
            for p in _norm_paths(add_read):
                if p not in entry["read_paths"]:
                    entry["read_paths"].append(p)
        if add_write:
            entry.setdefault("write_paths", [])
            for p in _norm_paths(add_write):
                if p not in entry["write_paths"]:
                    entry["write_paths"].append(p)
        _write_registry(entries)
        return {"ok": True, "name": entry["name"],
                "read_paths": entry.get("read_paths", []),
                "write_paths": entry.get("write_paths", [])}


def remove_server(name: str) -> dict[str, Any]:
    with _LOCK:
        entries = _read_registry()
        left = [e for e in entries if str(e.get("name", "")).lower() != (name or "").strip().lower()]
        if len(left) == len(entries):
            return {"ok": False, "error": f"Không tìm thấy server '{name}'"}
        _write_registry(left)
    return {"ok": True, "name": name}


def list_servers_safe() -> list[dict[str, Any]]:
    """Registry KHÔNG kèm mật khẩu — an toàn để hiển thị/trả cho model."""
    out = []
    for e in _read_registry():
        out.append({
            "name": e.get("name"), "host": e.get("host"),
            "port": e.get("port", 22), "username": e.get("username"),
            "has_password": bool(e.get("password")),
            "has_key": bool(e.get("key_path")),
            "allow_dangerous": bool(e.get("allow_dangerous")),
            "read_paths": e.get("read_paths", []),
            "write_paths": e.get("write_paths", []),
        })
    return out


def find_server(name: str) -> dict[str, Any] | None:
    """Public accessor cho registry entry đầy đủ (fs_remote dùng để lấy creds)."""
    return _find(name)


# ── SSH connect / exec ──────────────────────────────────────────────────────


def connect(entry: dict[str, Any]):
    """Mở một paramiko.SSHClient đã kết nối tới server (caller tự đóng)."""
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kw: dict[str, Any] = {
        "hostname": entry["host"],
        "port": int(entry.get("port", 22)),
        "username": entry["username"],
        "timeout": 12,
        "banner_timeout": 20,
        "auth_timeout": 20,
        "look_for_keys": False,
        "allow_agent": False,
    }
    key_path = entry.get("key_path")
    if key_path and os.path.exists(key_path):
        connect_kw["key_filename"] = key_path
    if entry.get("password"):
        connect_kw["password"] = entry["password"]
    client.connect(**connect_kw)
    return client


def _run_ssh(entry: dict[str, Any], command: str, timeout: int) -> tuple[int, str, str]:
    client = connect(entry)
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err
    finally:
        client.close()


def run_command(server: str, command: str, timeout: int = 30) -> str:
    entry = _find(server)
    if not entry:
        names = ", ".join(s["name"] for s in list_servers_safe()) or "(chưa có server nào)"
        return f"Lỗi: chưa khai báo server '{server}'. Server hiện có: {names}"
    cmd = (command or "").strip()
    if not cmd:
        return "Lỗi: command trống."
    if not entry.get("allow_dangerous") and any(p.search(cmd) for p in _DANGEROUS):
        return (f"❌ Từ chối: lệnh có dấu hiệu phá huỷ dữ liệu trên '{server}'. "
                f"Nếu chắc chắn, bật allow_dangerous cho server này rồi thử lại.")
    timeout = max(1, min(300, int(timeout or 30)))
    try:
        code, out, err = _run_ssh(entry, cmd, timeout)
    except Exception as exc:
        return f"❌ Lỗi SSH tới '{server}' ({entry.get('username')}@{entry.get('host')}): {exc}"
    body = out if out else ""
    if err.strip():
        body += ("\n" if body else "") + f"[stderr]\n{err}"
    if len(body) > _MAX_OUTPUT:
        body = body[:_MAX_OUTPUT] + f"\n… (đã cắt bớt, tổng {len(body)} ký tự)"
    status = "OK" if code == 0 else f"exit={code}"
    return f"[{server}] $ {cmd}\n({status})\n{body or '(không có output)'}"


# ── MCP tools ───────────────────────────────────────────────────────────────


@mcp.tool()
def ssh_list_servers() -> str:
    """Liệt kê các server đã khai báo để chạy lệnh SSH (không hiển thị mật khẩu)."""
    servers = list_servers_safe()
    if not servers:
        return "Chưa khai báo server SSH nào. Dùng ssh_add_server để thêm."
    lines = ["Các server SSH đã khai báo:"]
    for s in servers:
        auth = "password" if s["has_password"] else ("key" if s["has_key"] else "chưa có auth")
        danger = " ⚠️allow_dangerous" if s["allow_dangerous"] else ""
        lines.append(f"- {s['name']}: {s['username']}@{s['host']}:{s['port']} ({auth}){danger}")
    return "\n".join(lines)


@mcp.tool()
def ssh_run(server: str, command: str, timeout: int = 30) -> str:
    """Chạy một lệnh shell trên server đã khai báo qua SSH và trả về kết quả.

    Args:
        server: Tên server đã khai báo (xem ssh_list_servers). Vd: "ha", "nvr".
        command: Lệnh shell cần chạy (vd: "uptime", "df -h", "docker ps").
        timeout: Thời gian chờ tối đa (giây), tối đa 300.
    """
    return run_command(server, command, timeout)


_container_cache: dict[str, Any] = {"ts": 0.0, "map": {}}
_CONTAINER_TTL = 60.0


def _list_containers(entry: dict) -> list[str]:
    try:
        _code, out, _err = _run_ssh(entry, "docker ps --format '{{.Names}}'", 15)
        return [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    except Exception:
        return []


def _container_map(use_cache: bool = True) -> dict[str, list[str]]:
    """{server_name: [container names]} — quét SONG SONG mọi server, cache ~60s."""
    import time as _t
    from concurrent.futures import ThreadPoolExecutor, as_completed
    now = _t.time()
    if use_cache and _container_cache["map"] and (now - _container_cache["ts"]) < _CONTAINER_TTL:
        return _container_cache["map"]
    servers = _read_registry()
    result: dict[str, list[str]] = {}
    if servers:
        with ThreadPoolExecutor(max_workers=min(16, len(servers))) as pool:
            futs = {pool.submit(_list_containers, e): e for e in servers}
            try:
                for f in as_completed(futs, timeout=30):
                    e = futs[f]
                    try:
                        result[str(e.get("name", ""))] = f.result()
                    except Exception:
                        result[str(e.get("name", ""))] = []
            except Exception:
                pass
    _container_cache["ts"] = now
    _container_cache["map"] = result
    return result


@mcp.tool()
def ssh_locate(name: str = "") -> str:
    """Tìm NHANH một container/dịch vụ đang chạy trên MÁY nào — quét `docker ps`
    SONG SONG tất cả server đã khai báo trong MỘT lần gọi (cache ~60s). Dùng cái
    này THAY VÌ chạy docker ps tuần tự từng máy (nhanh kể cả khi có nhiều server).

    Args:
        name: Tên (hoặc một phần) container cần tìm, vd "frigate". Để trống để
              liệt kê toàn bộ container theo từng server.
    """
    servers = _read_registry()
    if not servers:
        return "Chưa khai báo server nào."
    cmap = _container_map()
    nl = (name or "").strip().lower()
    if not nl:
        lines = [f"- {sv}: {', '.join(conts) if conts else '(trống/không truy cập được)'}"
                 for sv, conts in cmap.items()]
        return "Container theo server:\n" + "\n".join(lines)
    hits = [(sv, c) for sv, conts in cmap.items() for c in conts if nl in c.lower()]
    if not hits:
        return (f"Không thấy container khớp '{name}' trên {len(servers)} máy đã khai báo. "
                "Thử ssh_locate('') để xem tất cả.")
    lines = [f"- '{c}' → server '{sv}'" for sv, c in hits]
    return ("Tìm thấy:\n" + "\n".join(lines) +
            "\nSau đó gọi ssh_run(server, \"docker ...\") hoặc fs_* trên ĐÚNG server đó.")


@mcp.tool()
def ssh_add_server(name: str, host: str, username: str, password: str = "",
                   port: int = 22, allow_dangerous: bool = False) -> str:
    """Khai báo một server mới để chạy lệnh SSH.

    Args:
        name: Tên gợi nhớ (vd: "ha", "nvr").
        host: IP hoặc hostname.
        username: Tên đăng nhập SSH.
        password: Mật khẩu (lưu server-side, không lộ ra ngoài).
        port: Cổng SSH (mặc định 22).
        allow_dangerous: Cho phép lệnh phá huỷ dữ liệu (mặc định False).
    """
    r = add_server(name, host, username, password, port, allow_dangerous=allow_dangerous)
    return f"✅ Đã thêm server '{r['name']}'." if r.get("ok") else f"Lỗi: {r.get('error')}"


@mcp.tool()
def ssh_remove_server(name: str) -> str:
    """Xoá một server khỏi danh sách SSH.

    Args:
        name: Tên server cần xoá.
    """
    r = remove_server(name)
    return f"✅ Đã xoá server '{name}'." if r.get("ok") else f"Lỗi: {r.get('error')}"
