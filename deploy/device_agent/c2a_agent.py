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

An toàn:
  * Chỉ dùng stdlib — không cài thêm gì, chạy được cả trên Termux.
  * Allowlist đường dẫn giữ NGAY TẠI ĐÂY: agent KHÔNG tin gateway. Gateway bị
    chiếm cũng không đọc/ghi ra ngoài thư mục anh cho phép.
  * Không có --allow-write thì mọi lệnh ghi/xoá bị từ chối tại máy.
  * Không có lệnh shell. Chỉ thao tác file.
  * Symlink được resolve TRƯỚC khi kiểm allowlist (chặn link trỏ ra ngoài).

Thoát: Ctrl-C. Chạy nền lâu dài thì dùng systemd (Linux) hoặc
`termux-wake-lock` + nohup (Android).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import ssl
import struct
import sys
import time
from pathlib import Path

VERSION = "1.0.0"

MAX_READ = 200_000       # trần đọc 1 file (khớp fs_remote)
MAX_WRITE = 500_000      # trần ghi 1 lần
MAX_LIST = 500           # trần số mục liệt kê
MAX_FIND = 200           # trần số kết quả tìm
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
    def __init__(self, paths: list[str], allow_write: bool) -> None:
        self.roots = [Path(p).expanduser().resolve() for p in paths]
        self.allow_write = allow_write

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


OPS = {"ls": op_ls, "read": op_read, "stat": op_stat, "find": op_find,
       "write": op_write, "append": op_append, "mkdir": op_mkdir, "delete": op_delete}


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
        print("[c2a-agent] cho phép: %s | ghi: %s"
              % (", ".join(str(r) for r in g.roots), "CÓ" if g.allow_write else "KHÔNG"),
              flush=True)
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
            res = handle(g, op, msg.get("args") or {})
            print("[c2a-agent] %s %s -> %s" % (
                op, str((msg.get("args") or {}).get("path") or "")[:60],
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
                    help="cho phép ghi/xoá; thiếu cờ này thì CHỈ ĐỌC")
    ap.add_argument("--label", default="", help="tên gợi nhớ hiển thị ở dự án")
    a = ap.parse_args()

    if not a.token:
        print("thiếu --token (hoặc biến C2A_TOKEN)", file=sys.stderr)
        return 2
    if not a.path:
        # Fail-closed: không khai thư mục nào thì KHÔNG mở gì cả. Cấu hình
        # thiếu sót không bao giờ được biến thành "mở toàn máy".
        print("thiếu --path: phải khai ít nhất một thư mục được phép", file=sys.stderr)
        return 2

    g = Guard(a.path, a.allow_write)
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
