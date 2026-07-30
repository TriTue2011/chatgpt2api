#!/usr/bin/env python3
"""c2a-agent — cho dự án đọc/sửa file trên MÁY NÀY qua Internet.

Cài một lệnh trên máy tính / điện thoại Android (Termux) / VPS / server, agent
tự quay ra kết nối tới gateway rồi chờ lệnh. Vì agent GỌI RA nên máy nằm sau
NAT, wifi nhà hay 4G đều dùng được — không cần mở cổng, không cần IP tĩnh.

    python3 c2a_agent.py \
        --url wss://gpt.vhtatn.io.vn/api/devices/agent \
        --token <TOKEN> \
        --path /home/me/project --path /var/log \
        --allow-write

Bốn nhóm quyền, mỗi nhóm một cờ, MẶC ĐỊNH TẮT HẾT (trừ đọc):

    --allow-write   ghi / xoá file trong allowlist
    --allow-exec    chạy lệnh tuỳ ý (PowerShell / cmd / sh) + tắt tiến trình
    --allow-power   khoá màn hình, ngủ, đăng xuất, tắt máy, khởi động lại

An toàn:
  * Chỉ dùng stdlib — không cài thêm gì, chạy được cả trên Termux.
  * Allowlist đường dẫn giữ NGAY TẠI ĐÂY: agent KHÔNG tin gateway. Gateway bị
    chiếm cũng không đọc/ghi ra ngoài thư mục anh cho phép.
  * Không có --allow-write thì mọi lệnh ghi/xoá bị từ chối tại máy.
  * Symlink được resolve TRƯỚC khi kiểm allowlist (chặn link trỏ ra ngoài).

  * NÓI THẲNG VỀ --allow-exec: bật cờ này là allowlist thư mục hết ý nghĩa.
    Một lệnh shell đọc/ghi/xoá được MỌI thứ mà tài khoản đang chạy agent với
    tới, kể cả ngoài --path. Đừng bật kèm quyền admin/root nếu không cần.
    Muốn hẹp lại thì dùng --exec-allow: chỉ cho phép những lệnh bắt đầu bằng
    tiền tố đã khai (vd --exec-allow winget --exec-allow systemctl).
  * Nhóm tra cứu thông tin (sysinfo/resources/processes/services/screen) KHÔNG
    cần --allow-exec: chúng chỉ chạy các lệnh CỐ ĐỊNH do chính agent chọn, mô
    hình không chèn được chữ nào vào đó, và tất cả đều chỉ đọc.

Thoát: Ctrl-C. Chạy nền lâu dài thì dùng systemd (Linux) hoặc
`termux-wake-lock` + nohup (Android).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import time
from pathlib import Path

VERSION = "1.1.0"

MAX_READ = 200_000       # trần đọc 1 file (khớp fs_remote)
MAX_WRITE = 500_000      # trần ghi 1 lần
MAX_LIST = 500           # trần số mục liệt kê
MAX_FIND = 200           # trần số kết quả tìm
MAX_OUT = 100_000        # trần stdout+stderr của 1 lệnh
EXEC_TIMEOUT = 30.0      # mặc định; tối đa EXEC_TIMEOUT_MAX
EXEC_TIMEOUT_MAX = 300.0
MAX_PROCS = 40           # trần số tiến trình trả về

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
PING_EVERY = 25.0
IDLE_TIMEOUT = 70.0
BACKOFF_START = 5.0
BACKOFF_CAP = 120.0


# ── WebSocket client tối thiểu (RFC6455) ────────────────────────────────────
class WS:
    def __init__(self, url: str, timeout: float = 15.0) -> None:
        secure = url.startswith("wss://")
        rest = url.split("://", 1)[1]
        netloc, _, path = rest.partition("/")
        self.path = "/" + path
        host, _, port_s = netloc.partition(":")
        port = int(port_s) if port_s else (443 if secure else 80)
        self.host = host
        raw = socket.create_connection((host, port), timeout=timeout)
        if secure:
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=host)
        self.sock = raw
        self.sock.settimeout(IDLE_TIMEOUT)
        self.buf = bytearray()
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET {self.path} HTTP/1.1\r\nHost: {netloc}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            c = self.sock.recv(4096)
            if not c:
                raise RuntimeError("handshake bị đóng")
            resp += c
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            raise RuntimeError("gateway từ chối handshake: %r" % resp[:100])

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def _need(self, n: int) -> None:
        while len(self.buf) < n:
            c = self.sock.recv(16384)
            if not c:
                raise RuntimeError("kết nối đóng")
            self.buf.extend(c)

    def _send_raw(self, opcode: int, payload: bytes) -> None:
        m = os.urandom(4)
        h = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            h.append(0x80 | n)
        elif n < 65536:
            h.append(0x80 | 126); h += struct.pack(">H", n)
        else:
            h.append(0x80 | 127); h += struct.pack(">Q", n)
        h += m
        self.sock.sendall(bytes(h) + bytes(b ^ m[i % 4] for i, b in enumerate(payload)))

    def send_json(self, obj: dict) -> None:
        self._send_raw(0x1, json.dumps(obj, ensure_ascii=False).encode())

    def ping(self) -> None:
        self._send_raw(0x9, b"ka")

    def recv_json(self) -> dict:
        parts: list[bytes] = []
        while True:
            self._need(2)
            b0 = self.buf[0]
            fin, opcode = b0 & 0x80, b0 & 0x0F
            ln = self.buf[1] & 0x7F
            idx = 2
            if ln == 126:
                self._need(4); ln = struct.unpack(">H", bytes(self.buf[2:4]))[0]; idx = 4
            elif ln == 127:
                self._need(10); ln = struct.unpack(">Q", bytes(self.buf[2:10]))[0]; idx = 10
            self._need(idx + ln)
            payload = bytes(self.buf[idx:idx + ln])
            del self.buf[:idx + ln]
            if opcode == 0x9:
                self._send_raw(0xA, payload); continue
            if opcode == 0xA:
                continue
            if opcode == 0x8:
                raise RuntimeError("gateway đóng kết nối")
            if opcode in (0x1, 0x0):
                parts.append(payload)
                if fin:
                    return json.loads(b"".join(parts).decode("utf-8", "replace"))
                continue


# ── Allowlist ───────────────────────────────────────────────────────────────
class Guard:
    def __init__(self, paths: list[str], allow_write: bool,
                 allow_exec: bool = False, allow_power: bool = False,
                 exec_allow: list[str] | None = None) -> None:
        self.roots = [Path(p).expanduser().resolve() for p in paths]
        self.allow_write = allow_write
        self.allow_exec = allow_exec
        self.allow_power = allow_power
        # Tiền tố lệnh được phép. Rỗng = không giới hạn (miễn là có allow_exec).
        self.exec_allow = [s.strip().lower() for s in (exec_allow or []) if s.strip()]

    def resolve(self, raw: str) -> Path:
        """Chuẩn hoá + resolve symlink RỒI mới kiểm — link trỏ ra ngoài bị chặn.

        Với đường dẫn chưa tồn tại (ghi file mới) thì resolve thư mục cha, vì
        strict=True sẽ ném lỗi và ta vẫn cần chặn cha nằm ngoài allowlist.
        """
        p = Path(raw).expanduser()
        if not p.is_absolute():
            raise PermissionError("đường dẫn phải là tuyệt đối")
        try:
            real = p.resolve(strict=True)
        except FileNotFoundError:
            real = p.parent.resolve(strict=False) / p.name
        for root in self.roots:
            if real == root or root in real.parents:
                return real
        raise PermissionError(
            "ngoài phạm vi cho phép của thiết bị này (%s)"
            % ", ".join(str(r) for r in self.roots))

    def need_write(self) -> None:
        if not self.allow_write:
            raise PermissionError("thiết bị này chạy ở chế độ CHỈ ĐỌC (thiếu --allow-write)")

    def need_exec(self, cmd: str = "") -> None:
        if not self.allow_exec:
            raise PermissionError(
                "thiết bị này KHÔNG cho chạy lệnh (thiếu --allow-exec)")
        if not self.exec_allow:
            return
        # So khớp trên chuỗi đã hạ thường, bỏ khoảng trắng đầu. Cố ý chỉ xét
        # TIỀN TỐ: đủ để hạn chế vào vài công cụ, và nói rõ trong tài liệu là
        # KHÔNG phải hàng rào chống người dùng cố tình vượt (shell còn `;`, `&&`,
        # backtick…). Ai cần chặt hơn thì đừng bật --allow-exec.
        low = cmd.strip().lower()
        if not any(low.startswith(p) for p in self.exec_allow):
            raise PermissionError(
                "lệnh không nằm trong --exec-allow (%s)" % ", ".join(self.exec_allow))

    def need_power(self) -> None:
        if not self.allow_power:
            raise PermissionError(
                "thiết bị này KHÔNG cho khoá/tắt/khởi động lại (thiếu --allow-power)")


# ── Thao tác ────────────────────────────────────────────────────────────────
def op_ls(g: Guard, args: dict) -> dict:
    d = g.resolve(str(args.get("path") or ""))
    if not d.is_dir():
        return {"ok": False, "error": "không phải thư mục"}
    items = []
    for i, entry in enumerate(sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name))):
        if i >= MAX_LIST:
            break
        try:
            st = entry.stat()
            items.append({"name": entry.name, "dir": entry.is_dir(),
                          "size": st.st_size, "mtime": int(st.st_mtime)})
        except OSError:
            items.append({"name": entry.name, "dir": False, "error": "không đọc được"})
    return {"ok": True, "path": str(d), "items": items, "truncated": len(items) >= MAX_LIST}


def op_read(g: Guard, args: dict) -> dict:
    f = g.resolve(str(args.get("path") or ""))
    if not f.is_file():
        return {"ok": False, "error": "không phải file"}
    size = f.stat().st_size
    data = f.read_bytes()[:MAX_READ]
    try:
        text, binary = data.decode("utf-8"), False
    except UnicodeDecodeError:
        text, binary = base64.b64encode(data).decode(), True
    return {"ok": True, "path": str(f), "size": size, "binary": binary,
            "content": text, "truncated": size > MAX_READ}


def op_stat(g: Guard, args: dict) -> dict:
    p = g.resolve(str(args.get("path") or ""))
    if not p.exists():
        return {"ok": False, "error": "không tồn tại"}
    st = p.stat()
    return {"ok": True, "path": str(p), "dir": p.is_dir(), "size": st.st_size,
            "mtime": int(st.st_mtime), "mode": oct(st.st_mode & 0o777)}


def op_find(g: Guard, args: dict) -> dict:
    root = g.resolve(str(args.get("path") or ""))
    pattern = str(args.get("pattern") or "*")
    hits = []
    for i, m in enumerate(root.rglob(pattern)):
        if i >= MAX_FIND:
            break
        hits.append(str(m))
    return {"ok": True, "root": str(root), "matches": hits,
            "truncated": len(hits) >= MAX_FIND}


def op_write(g: Guard, args: dict) -> dict:
    g.need_write()
    f = g.resolve(str(args.get("path") or ""))
    content = args.get("content")
    if not isinstance(content, str):
        return {"ok": False, "error": "thiếu 'content' dạng chuỗi"}
    raw = (base64.b64decode(content) if args.get("base64")
           else content.encode("utf-8"))
    if len(raw) > MAX_WRITE:
        return {"ok": False, "error": f"vượt trần ghi {MAX_WRITE} byte"}
    f.parent.mkdir(parents=True, exist_ok=True)
    backup = ""
    if f.exists() and args.get("backup", True):
        # Ghi đè là KHÔNG hoàn tác được → giữ một bản .bak trước khi sửa.
        b = f.with_suffix(f.suffix + ".c2a.bak")
        shutil.copy2(f, b)
        backup = str(b)
    tmp = f.with_suffix(f.suffix + ".c2a.tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, f)          # thay nguyên tử — không để lại file nửa vời
    return {"ok": True, "path": str(f), "written": len(raw), "backup": backup}


def op_append(g: Guard, args: dict) -> dict:
    g.need_write()
    f = g.resolve(str(args.get("path") or ""))
    raw = str(args.get("content") or "").encode("utf-8")
    if len(raw) > MAX_WRITE:
        return {"ok": False, "error": f"vượt trần ghi {MAX_WRITE} byte"}
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "ab") as fh:
        fh.write(raw)
    return {"ok": True, "path": str(f), "appended": len(raw)}


def op_mkdir(g: Guard, args: dict) -> dict:
    g.need_write()
    d = g.resolve(str(args.get("path") or ""))
    d.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(d)}


def op_delete(g: Guard, args: dict) -> dict:
    g.need_write()
    p = g.resolve(str(args.get("path") or ""))
    if not p.exists():
        return {"ok": False, "error": "không tồn tại"}
    if p.is_dir():
        # Xoá cây thư mục quá dễ gây thảm hoạ → chỉ cho xoá thư mục RỖNG.
        try:
            p.rmdir()
        except OSError:
            return {"ok": False, "error": "thư mục không rỗng — agent chỉ xoá thư mục rỗng"}
    else:
        p.unlink()
    return {"ok": True, "path": str(p)}


# ── Chạy lệnh (dùng chung cho cả nhóm tra cứu và nhóm exec) ─────────────────
def _run(cmd: list[str] | str, *, shell: bool = False, timeout: float = 20.0,
         cwd: str | None = None) -> tuple[int, str, str]:
    """Chạy một lệnh, trả (rc, stdout, stderr) đã cắt theo MAX_OUT.

    Không dùng check=True: lệnh trả rc≠0 vẫn là thông tin hữu ích (vd
    `systemctl status` trả 3 khi service dừng), ném lỗi ở đây là mất dữ liệu.
    """
    try:
        p = subprocess.run(
            cmd, shell=shell, cwd=cwd or None, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except subprocess.TimeoutExpired:
        return (-1, "", "hết thời gian chờ (%.0fs)" % timeout)
    except FileNotFoundError as exc:
        return (-1, "", "không có lệnh: %s" % exc)
    dec = lambda b: (b or b"").decode("utf-8", "replace")[:MAX_OUT]  # noqa: E731
    return (p.returncode, dec(p.stdout), dec(p.stderr))


def _first_line(cmd: list[str] | str, *, shell: bool = False) -> str:
    rc, out, _ = _run(cmd, shell=shell, timeout=10.0)
    return out.strip().splitlines()[0].strip() if (rc == 0 and out.strip()) else ""


def _uptime_seconds() -> float | None:
    """Số giây từ lúc khởi động. None = không đọc được trên nền tảng này."""
    try:
        if IS_WIN:
            import ctypes
            return ctypes.windll.kernel32.GetTickCount64() / 1000.0
        if IS_MAC:
            # kern.boottime: { sec = 1690000000, usec = 0 } ...
            out = _first_line(["sysctl", "-n", "kern.boottime"])
            for tok in out.replace(",", " ").split():
                if tok.isdigit() and len(tok) >= 9:
                    return max(0.0, time.time() - int(tok))
            return None
        with open("/proc/uptime", encoding="utf-8") as fh:
            return float(fh.read().split()[0])
    except Exception:
        return None


def _mem_bytes() -> tuple[int, int]:
    """(đã dùng, tổng) byte. (0, 0) = không đọc được."""
    try:
        if IS_WIN:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = _MS()
            st.dwLength = ctypes.sizeof(_MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return (st.ullTotalPhys - st.ullAvailPhys, st.ullTotalPhys)
        if IS_MAC:
            total = int(_first_line(["sysctl", "-n", "hw.memsize"]) or 0)
            rc, out, _ = _run(["vm_stat"], timeout=8.0)
            if rc != 0 or not total:
                return (0, total)
            page = 4096
            free = inactive = spec = 0
            for ln in out.splitlines():
                if "page size of" in ln:
                    for tok in ln.split():
                        if tok.isdigit():
                            page = int(tok)
                            break
                k, _, v = ln.partition(":")
                n = v.strip().rstrip(".")
                if not n.isdigit():
                    continue
                if k.startswith("Pages free"):
                    free = int(n)
                elif k.startswith("Pages inactive"):
                    inactive = int(n)
                elif k.startswith("Pages speculative"):
                    spec = int(n)
            avail = (free + inactive + spec) * page
            return (max(0, total - avail), total)
        total = avail = 0
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for ln in fh:
                k, _, v = ln.partition(":")
                kb = v.strip().split()[0] if v.strip() else "0"
                if k == "MemTotal":
                    total = int(kb) * 1024
                elif k == "MemAvailable":
                    avail = int(kb) * 1024
        return (max(0, total - avail), total)
    except Exception:
        return (0, 0)


def _cpu_percent() -> float | None:
    """% CPU đo bằng HAI lần lấy mẫu cách nhau 0,25s (không có psutil)."""
    try:
        if IS_WIN:
            import ctypes

            def snap() -> tuple[int, int]:
                idle, kern, user = (ctypes.c_ulonglong(), ctypes.c_ulonglong(),
                                    ctypes.c_ulonglong())
                ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
                return (idle.value, kern.value + user.value)
            i0, t0 = snap()
            time.sleep(0.25)
            i1, t1 = snap()
            dt, di = t1 - t0, i1 - i0
            return round(100.0 * (dt - di) / dt, 1) if dt > 0 else None
        if IS_MAC:
            rc, out, _ = _run(["ps", "-A", "-o", "%cpu"], timeout=8.0)
            if rc != 0:
                return None
            tot = sum(float(x) for x in out.split()[1:] if _isnum(x))
            return round(min(100.0, tot / max(1, os.cpu_count() or 1)), 1)

        def snap_linux() -> tuple[int, int]:
            with open("/proc/stat", encoding="utf-8") as fh:
                f = [int(x) for x in fh.readline().split()[1:]]
            return (f[3] + f[4], sum(f))
        i0, t0 = snap_linux()
        time.sleep(0.25)
        i1, t1 = snap_linux()
        dt, di = t1 - t0, i1 - i0
        return round(100.0 * (dt - di) / dt, 1) if dt > 0 else None
    except Exception:
        return None


def _isnum(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _disks() -> list[dict]:
    """Dung lượng các ổ/điểm mount chính."""
    mounts: list[str] = []
    if IS_WIN:
        for c in "CDEFGH":
            p = f"{c}:\\"
            if os.path.exists(p):
                mounts.append(p)
    else:
        mounts = ["/"]
        for extra in ("/home", "/data", "/var", "/srv", "/System/Volumes/Data"):
            if os.path.ismount(extra):
                mounts.append(extra)
    out = []
    for m in mounts:
        try:
            u = shutil.disk_usage(m)
            out.append({"mount": m, "total": u.total, "used": u.used,
                        "free": u.free,
                        "percent": round(100.0 * u.used / u.total, 1) if u.total else 0})
        except Exception:
            continue
    return out


def op_sysinfo(g: Guard, args: dict) -> dict:
    """Thông tin máy — chỉ đọc, không cần quyền gì thêm."""
    up = _uptime_seconds()
    info = {
        "ok": True,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor() or "",
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "user": _current_user(),
        "cwd": os.getcwd(),
        "uptime_seconds": int(up) if up is not None else None,
        "boot_time": (time.time() - up) if up is not None else None,
        "agent_version": VERSION,
        "allow_write": g.allow_write,
        "allow_exec": g.allow_exec,
        "allow_power": g.allow_power,
    }
    return info


def _current_user() -> str:
    for key in ("USER", "USERNAME", "LOGNAME"):
        v = os.environ.get(key)
        if v:
            return v
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return ""


def op_resources(g: Guard, args: dict) -> dict:
    """CPU / RAM / ổ đĩa / load — chỉ đọc."""
    used, total = _mem_bytes()
    try:
        load = list(os.getloadavg())
    except (OSError, AttributeError):
        load = []          # Windows không có
    return {"ok": True,
            "cpu_percent": _cpu_percent(),
            "cpu_count": os.cpu_count(),
            "load_avg": load,
            "mem_used": used, "mem_total": total,
            "mem_percent": round(100.0 * used / total, 1) if total else None,
            "disks": _disks()}


def op_processes(g: Guard, args: dict) -> dict:
    """Top tiến trình theo RAM. Lệnh CỐ ĐỊNH nên không cần --allow-exec."""
    limit = max(1, min(int(args.get("limit") or 20), MAX_PROCS))
    name_filter = str(args.get("name") or "").strip().lower()
    rows: list[dict] = []
    if IS_WIN:
        rc, out, err = _run(["tasklist", "/fo", "csv", "/nh"], timeout=25.0)
        if rc != 0:
            return {"ok": False, "error": err or "tasklist lỗi"}
        import csv
        import io
        for r in csv.reader(io.StringIO(out)):
            if len(r) < 5:
                continue
            kb = "".join(ch for ch in r[4] if ch.isdigit())
            rows.append({"pid": r[1], "name": r[0],
                         "mem_kb": int(kb or 0), "cpu": None})
    else:
        rc, out, err = _run(["ps", "-eo", "pid,pcpu,rss,comm"], timeout=25.0)
        if rc != 0:
            return {"ok": False, "error": err or "ps lỗi"}
        for ln in out.splitlines()[1:]:
            f = ln.split(None, 3)
            if len(f) < 4:
                continue
            rows.append({"pid": f[0], "cpu": float(f[1]) if _isnum(f[1]) else None,
                         "mem_kb": int(f[2]) if f[2].isdigit() else 0,
                         "name": f[3].strip()})
    if name_filter:
        rows = [r for r in rows if name_filter in str(r["name"]).lower()]
    rows.sort(key=lambda r: r.get("mem_kb") or 0, reverse=True)
    return {"ok": True, "count": len(rows), "processes": rows[:limit]}


def op_services(g: Guard, args: dict) -> dict:
    """Danh sách service/daemon. Lệnh CỐ ĐỊNH, chỉ đọc."""
    name = str(args.get("name") or "").strip()
    if IS_WIN:
        # sc query có sẵn ở mọi bản Windows, không cần PowerShell.
        cmd = ["sc", "query", name] if name else ["sc", "query", "state=", "all"]
    elif IS_MAC:
        cmd = ["launchctl", "list"]
    else:
        cmd = ["systemctl", "list-units", "--type=service", "--all",
               "--no-pager", "--plain"]
        if name:
            cmd = ["systemctl", "status", name, "--no-pager"]
    rc, out, err = _run(cmd, timeout=30.0)
    if rc != 0 and not out.strip():
        return {"ok": False, "error": err or "không lấy được danh sách service"}
    if name and not IS_WIN and not IS_MAC:
        pass
    elif name and IS_MAC:
        out = "\n".join(ln for ln in out.splitlines() if name.lower() in ln.lower())
    return {"ok": True, "rc": rc, "output": out[:MAX_OUT], "target": name}


def op_screen(g: Guard, args: dict) -> dict:
    """Trạng thái màn hình / phiên đăng nhập — chỉ đọc.

    Nói thật về giới hạn: "màn hình đang sáng hay tắt" KHÔNG phải thứ mọi hệ
    điều hành cho biết chắc chắn. Trả về đúng những gì đo được và ghi rõ cái
    nào là suy đoán, thay vì đoán bừa một câu trả lời gọn gàng.
    """
    res: dict = {"ok": True, "locked": None, "display_on": None,
                 "idle_seconds": None, "note": ""}
    try:
        if IS_WIN:
            import ctypes

            class _LII(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]
            lii = _LII()
            lii.cbSize = ctypes.sizeof(_LII)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                tick = ctypes.windll.kernel32.GetTickCount64()
                res["idle_seconds"] = max(0, int((tick - lii.dwTime) / 1000))
            # Khoá máy → LogonUI.exe chạy. Đây là cách nhận biết thực dụng và
            # đáng tin trên Windows mà không cần thư viện ngoài.
            rc, out, _ = _run(["tasklist", "/fi", "IMAGENAME eq LogonUI.exe",
                               "/fo", "csv", "/nh"], timeout=15.0)
            res["locked"] = bool(rc == 0 and "logonui" in out.lower())
            res["note"] = ("locked suy từ tiến trình LogonUI.exe; display_on "
                           "không đọc được nếu không có thư viện ngoài — dùng "
                           "idle_seconds để suy đoán.")
        elif IS_MAC:
            rc, out, _ = _run(["ioreg", "-n", "IODisplayWrangler", "-r", "-d", "1"],
                              timeout=15.0)
            if rc == 0 and "IOPowerManagement" in out:
                # CurrentPowerState 4 = sáng, 1..3 = mờ/tắt
                for ln in out.splitlines():
                    if "CurrentPowerState" in ln:
                        digits = "".join(c for c in ln.split("=")[-1] if c.isdigit())
                        if digits:
                            res["display_on"] = int(digits) >= 4
                        break
            rc2, out2, _ = _run(
                "python3 -c \"import Quartz,sys;d=Quartz.CGSessionCopyCurrentDictionary();"
                "print(1 if d and d.get('CGSSessionScreenIsLocked') else 0)\"",
                shell=True, timeout=10.0)
            if rc2 == 0 and out2.strip() in ("0", "1"):
                res["locked"] = out2.strip() == "1"
            else:
                res["note"] = "locked cần PyObjC (Quartz) — không có nên bỏ trống."
        else:
            rc, out, _ = _run(["loginctl", "show-session", "self", "-p", "LockedHint"],
                              timeout=10.0)
            if rc == 0 and "=" in out:
                res["locked"] = out.strip().split("=")[-1].strip().lower() == "yes"
            rc2, out2, _ = _run(["xset", "-q"], timeout=10.0)
            if rc2 == 0 and "Monitor is" in out2:
                res["display_on"] = "Monitor is On" in out2
            if res["display_on"] is None:
                res["note"] = "display_on cần xset (X11); Wayland/headless không có."
    except Exception as exc:
        res["note"] = (res["note"] + " | lỗi: " + str(exc)[:80]).strip(" |")
    return res


def op_exec(g: Guard, args: dict) -> dict:
    """Chạy MỘT lệnh tuỳ ý. Cần --allow-exec."""
    cmd = str(args.get("command") or "").strip()
    if not cmd:
        return {"ok": False, "error": "thiếu command"}
    g.need_exec(cmd)
    want = str(args.get("shell") or "").strip().lower()
    timeout = float(args.get("timeout") or EXEC_TIMEOUT)
    timeout = max(1.0, min(timeout, EXEC_TIMEOUT_MAX))
    cwd = str(args.get("cwd") or "").strip() or None

    if IS_WIN:
        if want == "cmd":
            argv: list[str] | str = ["cmd", "/d", "/c", cmd]
        else:
            # PowerShell mặc định trên Windows: cú pháp mạnh hơn và là thứ người
            # dùng mong đợi. -NoProfile để profile của máy không đổi hành vi.
            exe = shutil.which("pwsh") or "powershell"
            argv = [exe, "-NoProfile", "-NonInteractive", "-Command", cmd]
        rc, out, err = _run(argv, timeout=timeout, cwd=cwd)
        used = "cmd" if want == "cmd" else "powershell"
    else:
        if want in ("powershell", "pwsh") and shutil.which("pwsh"):
            rc, out, err = _run(["pwsh", "-NoProfile", "-Command", cmd],
                                timeout=timeout, cwd=cwd)
            used = "pwsh"
        else:
            rc, out, err = _run(cmd, shell=True, timeout=timeout, cwd=cwd)
            used = "sh"
    return {"ok": rc == 0, "rc": rc, "shell": used, "command": cmd,
            "stdout": out, "stderr": err,
            "truncated": len(out) >= MAX_OUT or len(err) >= MAX_OUT}


def op_kill(g: Guard, args: dict) -> dict:
    """Tắt tiến trình theo pid hoặc tên. Cần --allow-exec."""
    pid = str(args.get("pid") or "").strip()
    name = str(args.get("name") or "").strip()
    if not pid and not name:
        return {"ok": False, "error": "cần pid hoặc name"}
    # Đi qua need_exec để cùng chịu --exec-allow: tắt tiến trình cũng là can
    # thiệp vào máy, không nên rẻ hơn chạy lệnh.
    g.need_exec("kill")
    force = bool(args.get("force"))
    if IS_WIN:
        argv = ["taskkill"] + (["/pid", pid] if pid else ["/im", name])
        if force:
            argv.append("/f")
    else:
        if pid:
            argv = ["kill", "-9" if force else "-15", pid]
        else:
            argv = ["pkill"] + (["-9"] if force else []) + ["-f", name]
    rc, out, err = _run(argv, timeout=20.0)
    return {"ok": rc == 0, "rc": rc, "target": pid or name,
            "stdout": out, "stderr": err}


_POWER_WIN = {
    "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
    "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
    "logoff": ["shutdown", "/l"],
    "shutdown": ["shutdown", "/s", "/t", "0"],
    "restart": ["shutdown", "/r", "/t", "0"],
}
_POWER_MAC = {
    "lock": ["pmset", "displaysleepnow"],
    "sleep": ["pmset", "sleepnow"],
    "logoff": ["osascript", "-e", 'tell application "System Events" to log out'],
    "shutdown": ["osascript", "-e", 'tell application "System Events" to shut down'],
    "restart": ["osascript", "-e", 'tell application "System Events" to restart'],
}
_POWER_LINUX = {
    "lock": ["loginctl", "lock-session"],
    "sleep": ["systemctl", "suspend"],
    "logoff": ["loginctl", "terminate-session", "self"],
    "shutdown": ["systemctl", "poweroff"],
    "restart": ["systemctl", "reboot"],
}


def op_power(g: Guard, args: dict) -> dict:
    """Khoá / ngủ / đăng xuất / tắt / khởi động lại. Cần --allow-power."""
    action = str(args.get("action") or "").strip().lower()
    table = _POWER_WIN if IS_WIN else (_POWER_MAC if IS_MAC else _POWER_LINUX)
    if action not in table:
        return {"ok": False,
                "error": "action phải là một trong %s" % "|".join(sorted(table))}
    g.need_power()
    argv = table[action]
    # shutdown/restart cắt kết nối ngay nên đừng chờ hết timeout dài.
    rc, out, err = _run(argv, timeout=20.0)
    return {"ok": rc == 0, "rc": rc, "action": action,
            "stdout": out, "stderr": err,
            "note": "máy sẽ tắt/khởi động lại — agent mất kết nối là bình thường"
                    if action in ("shutdown", "restart") else ""}


OPS = {"ls": op_ls, "read": op_read, "stat": op_stat, "find": op_find,
       "write": op_write, "append": op_append, "mkdir": op_mkdir, "delete": op_delete,
       # tra cứu — chỉ đọc, lệnh cố định
       "sysinfo": op_sysinfo, "resources": op_resources, "processes": op_processes,
       "services": op_services, "screen": op_screen,
       # can thiệp — cần cờ riêng
       "exec": op_exec, "kill": op_kill, "power": op_power}


def handle(g: Guard, op: str, args: dict) -> dict:
    fn = OPS.get(op)
    if fn is None:
        return {"ok": False, "error": f"thao tác không hỗ trợ: {op}"}
    try:
        return fn(g, args if isinstance(args, dict) else {})
    except PermissionError as exc:
        return {"ok": False, "error": str(exc)}
    except OSError as exc:
        return {"ok": False, "error": f"lỗi hệ thống tệp: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


# ── Vòng kết nối ────────────────────────────────────────────────────────────
def session(url: str, token: str, g: Guard, label: str) -> None:
    ws = WS(url)
    try:
        ws.send_json({"type": "hello", "token": token, "info": {
            "version": VERSION,
            "platform": f"{sys.platform}/{os.name}",
            "hostname": socket.gethostname(),
            "label": label,
            "python": sys.version.split()[0],
        }})
        ready = ws.recv_json()
        if ready.get("type") != "ready":
            raise RuntimeError("gateway không chấp nhận: %s"
                               % str(ready.get("error") or ready)[:120])
        print("[c2a-agent] đã kết nối — thiết bị '%s'" % ready.get("device"), flush=True)
        print("[c2a-agent] thư mục: %s" % ", ".join(str(r) for r in g.roots), flush=True)
        lim = (" (chỉ: %s)" % ", ".join(g.exec_allow)) if g.exec_allow else ""
        print("[c2a-agent] quyền — ghi: %s | chạy lệnh: %s%s | tắt/khoá máy: %s"
              % ("CÓ" if g.allow_write else "không",
                 "CÓ" if g.allow_exec else "không", lim if g.allow_exec else "",
                 "CÓ" if g.allow_power else "không"), flush=True)
        last_ping = time.time()
        while True:
            if time.time() - last_ping > PING_EVERY:
                ws.ping()
                last_ping = time.time()
            try:
                msg = ws.recv_json()
            except socket.timeout:
                raise RuntimeError("không nhận được gì quá lâu")
            rid, op = str(msg.get("id") or ""), str(msg.get("op") or "")
            if not rid:
                continue
            a_in = msg.get("args") or {}
            res = handle(g, op, a_in)
            # In cả `command`/`action`/tên tiến trình, không chỉ `path`: chủ máy
            # phải thấy được LỆNH nào vừa chạy trên máy mình, không thì bật
            # --allow-exec thành hộp đen.
            subject = str(a_in.get("command") or a_in.get("action")
                          or a_in.get("path") or a_in.get("name")
                          or a_in.get("pid") or "")
            print("[c2a-agent] %s %s -> %s" % (
                op, subject[:100],
                "OK" if res.get("ok") else "LỖI: " + str(res.get("error"))[:60]), flush=True)
            ws.send_json({"id": rid, "result": res})
    finally:
        ws.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="c2a device agent")
    ap.add_argument("--url", required=True, help="wss://<domain>/api/devices/agent")
    ap.add_argument("--token", default=os.environ.get("C2A_TOKEN", ""),
                    help="token thiết bị (hoặc biến môi trường C2A_TOKEN)")
    ap.add_argument("--path", action="append", default=[],
                    help="thư mục được phép (lặp lại nhiều lần)")
    ap.add_argument("--allow-write", action="store_true",
                    help="cho phép ghi/xoá file trong --path; thiếu cờ này thì CHỈ ĐỌC")
    ap.add_argument("--allow-exec", action="store_true",
                    help="cho phép CHẠY LỆNH tuỳ ý (PowerShell/cmd/sh) + tắt tiến "
                         "trình. Bật cờ này là allowlist thư mục hết ý nghĩa.")
    ap.add_argument("--exec-allow", action="append", default=[], metavar="TIỀN_TỐ",
                    help="chỉ cho phép lệnh bắt đầu bằng tiền tố này (lặp nhiều "
                         "lần). Bỏ trống = mọi lệnh. Chỉ có tác dụng khi có "
                         "--allow-exec.")
    ap.add_argument("--allow-power", action="store_true",
                    help="cho phép khoá màn hình, ngủ, đăng xuất, TẮT MÁY, "
                         "khởi động lại")
    ap.add_argument("--label", default="", help="tên gợi nhớ hiển thị ở dự án")
    ap.add_argument("--log-file", default="",
                    help="ghi log vào file thay vì màn hình — BẮT BUỘC khi chạy "
                         "ẩn bằng pythonw/Task Scheduler")
    a = ap.parse_args()

    # Chạy ẨN (pythonw / Task Scheduler / .vbs): tiến trình KHÔNG có console,
    # sys.stdout/err là None và ngay lệnh print đầu tiên sẽ ném AttributeError
    # — agent chết trước cả khi kết nối, không dấu vết. Nên: có --log-file thì
    # trút hết ra đó; không có mà cũng không có console thì nuốt vào devnull
    # để agent SỐNG là trên hết.
    if a.log_file:
        try:
            _lf = open(a.log_file, "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = _lf
        except OSError as exc:
            if sys.stderr is not None:
                print("[c2a-agent] không mở được log %r: %s" % (a.log_file, exc),
                      file=sys.stderr)
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    if not a.token:
        print("thiếu --token (hoặc biến C2A_TOKEN)", file=sys.stderr)
        return 2
    if not a.path:
        # Fail-closed: không khai thư mục nào thì KHÔNG mở gì cả. Cấu hình
        # thiếu sót không bao giờ được biến thành "mở toàn máy".
        print("thiếu --path: phải khai ít nhất một thư mục được phép", file=sys.stderr)
        return 2

    if a.exec_allow and not a.allow_exec:
        # Nói ra thay vì âm thầm bỏ qua: người dùng tưởng đã giới hạn được lệnh
        # trong khi thực ra chưa mở quyền chạy lệnh nào cả.
        print("[c2a-agent] --exec-allow không có tác dụng khi thiếu --allow-exec",
              file=sys.stderr)

    g = Guard(a.path, a.allow_write, a.allow_exec, a.allow_power, a.exec_allow)
    print("[c2a-agent] v%s — gateway %s" % (VERSION, a.url), flush=True)
    backoff = BACKOFF_START
    while True:
        try:
            session(a.url, a.token, g, a.label)
            backoff = BACKOFF_START
        except KeyboardInterrupt:
            print("\n[c2a-agent] dừng.", flush=True)
            return 0
        except Exception as exc:
            print("[c2a-agent] mất kết nối: %s — thử lại sau %ds"
                  % (str(exc)[:120], int(backoff)), flush=True)
        try:
            time.sleep(backoff)
        except KeyboardInterrupt:
            return 0
        backoff = min(backoff * 2, BACKOFF_CAP)


if __name__ == "__main__":
    sys.exit(main())
