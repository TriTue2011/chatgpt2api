"""device_fs — MCP đọc/sửa file trên MỌI thiết bị đã cài c2a-agent.

Khác `fs_remote` (SFTP gọi VÀO server, cần SSH mở + IP tới được): ở đây agent
trên thiết bị **tự quay ra** kết nối tới gateway, nên máy tính, điện thoại
Android, VPS sau NAT/wifi/4G đều dùng được — chỉ cần thiết bị có Internet.

Đường đi: tool này → gateway (127.0.0.1:80 /api/devices/*) → WebSocket xuống
đúng thiết bị → agent thực thi → trả ngược lại.

Ba lớp chặn, cố ý trùng nhau:
  1. Gateway: token → thiết bị + allowlist đường dẫn (config `device_agents`).
  2. Gateway: chặn thao tác ghi nếu thiết bị không bật `can_write`.
  3. Agent:   tự giữ allowlist của chính nó, KHÔNG tin gateway.
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastmcp import FastMCP

mcp = FastMCP("device_fs")

GATEWAY = os.getenv("C2A_GATEWAY_URL", "http://127.0.0.1:80").rstrip("/")
AUTH_KEY = os.getenv("CHATGPT2API_AUTH_KEY", "")
_TIMEOUT = 90


def _call(path: str, payload: dict | None = None, method: str = "POST") -> dict[str, Any]:
    url = GATEWAY + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {AUTH_KEY}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode()[:200]
        except Exception:
            pass
        return {"ok": False, "error": f"gateway HTTP {exc.code}: {body}"}
    except Exception as exc:
        return {"ok": False, "error": f"không gọi được gateway: {str(exc)[:120]}"}


def _op(device: str, op: str, args: dict[str, Any]) -> dict[str, Any]:
    dev = str(device or "").strip()
    if not dev:
        return {"ok": False, "error": "thiếu tên thiết bị — gọi device_list trước"}
    return _call(f"/api/devices/{urllib.parse.quote(dev)}/op",
                 {"op": op, "args": args})


@mcp.tool()
def device_list() -> str:
    """Liệt kê các thiết bị đã khai báo (máy tính, điện thoại, VPS, server).

    Hiện rõ thiết bị nào đang ONLINE, thư mục nào được phép, có quyền ghi không.
    Gọi tool này TRƯỚC khi đọc/sửa file để biết tên thiết bị và phạm vi.
    """
    d = _call("/api/devices", method="GET")
    if d.get("ok") is False:
        return f"❌ {d.get('error')}"
    devices = d.get("devices") or []
    if not devices:
        return ("Chưa khai báo thiết bị nào. Thêm ở Cài đặt → Thiết bị "
                "(mỗi thiết bị một token), rồi chạy c2a_agent.py trên máy đó.")
    lines = []
    for x in devices:
        mark = "🟢 online" if x.get("connected") else "⚪ offline"
        extra = ""
        if x.get("connected"):
            extra = f" · {x.get('platform', '')} · {x.get('hostname', '')}"
        lines.append(
            f"• **{x.get('label') or x.get('name')}** (`{x.get('name')}`) — {mark}{extra}\n"
            f"  thư mục: {', '.join(x.get('paths') or []) or '(chưa khai báo)'}\n"
            f"  ghi file: {'CÓ' if x.get('can_write') else 'KHÔNG (chỉ đọc)'}")
    return "Thiết bị:\n" + "\n".join(lines)


@mcp.tool()
def device_ls(device: str, path: str) -> str:
    """Liệt kê thư mục trên thiết bị. `device` lấy từ device_list."""
    r = _op(device, "ls", {"path": path})
    if not r.get("ok"):
        return f"❌ {r.get('error')}"
    items = r.get("items") or []
    if not items:
        return f"`{r.get('path')}` — thư mục rỗng"
    lines = []
    for it in items:
        if it.get("dir"):
            lines.append(f"📁 {it.get('name')}/")
        else:
            kb = (it.get("size") or 0) / 1024
            lines.append(f"📄 {it.get('name')} ({kb:.1f} KB)")
    out = f"`{r.get('path')}` ({len(items)} mục):\n" + "\n".join(lines)
    if r.get("truncated"):
        out += "\n…(đã cắt bớt)"
    return out


@mcp.tool()
def device_read(device: str, path: str) -> str:
    """Đọc nội dung một file trên thiết bị (trần 200KB)."""
    r = _op(device, "read", {"path": path})
    if not r.get("ok"):
        return f"❌ {r.get('error')}"
    if r.get("binary"):
        return (f"`{r.get('path')}` là file NHỊ PHÂN ({r.get('size')} byte) — "
                "không hiển thị dạng chữ được.")
    head = f"`{r.get('path')}` ({r.get('size')} byte"
    head += ", đã cắt bớt)" if r.get("truncated") else ")"
    return head + ":\n```\n" + str(r.get("content") or "") + "\n```"


@mcp.tool()
def device_write(device: str, path: str, content: str) -> str:
    """Ghi (đè) nội dung vào file trên thiết bị.

    Thiết bị phải được bật quyền ghi. File cũ luôn được sao lưu thành
    `<tên>.c2a.bak` trước khi đè, và việc thay file là nguyên tử.
    """
    r = _op(device, "write", {"path": path, "content": content})
    if not r.get("ok"):
        return f"❌ {r.get('error')}"
    msg = f"✅ Đã ghi {r.get('written')} byte vào `{r.get('path')}`"
    if r.get("backup"):
        msg += f"\n(bản cũ giữ ở `{r.get('backup')}`)"
    return msg


@mcp.tool()
def device_append(device: str, path: str, content: str) -> str:
    """Ghi THÊM vào cuối file trên thiết bị (không đè nội dung cũ)."""
    r = _op(device, "append", {"path": path, "content": content})
    return (f"✅ Đã thêm {r.get('appended')} byte vào `{r.get('path')}`"
            if r.get("ok") else f"❌ {r.get('error')}")


@mcp.tool()
def device_find(device: str, path: str, pattern: str = "*") -> str:
    """Tìm file theo mẫu tên trong thư mục trên thiết bị (vd `*.log`, `*.py`)."""
    r = _op(device, "find", {"path": path, "pattern": pattern})
    if not r.get("ok"):
        return f"❌ {r.get('error')}"
    hits = r.get("matches") or []
    if not hits:
        return f"Không tìm thấy `{pattern}` trong `{r.get('root')}`"
    out = f"Tìm thấy {len(hits)} kết quả cho `{pattern}`:\n" + "\n".join(
        f"• {h}" for h in hits)
    if r.get("truncated"):
        out += "\n…(đã cắt bớt)"
    return out


@mcp.tool()
def device_stat(device: str, path: str) -> str:
    """Xem thông tin một đường dẫn: file hay thư mục, dung lượng, lần sửa cuối."""
    r = _op(device, "stat", {"path": path})
    if not r.get("ok"):
        return f"❌ {r.get('error')}"
    mt = datetime.datetime.fromtimestamp(r.get("mtime") or 0)
    kind = "thư mục" if r.get("dir") else "file"
    return (f"`{r.get('path')}` — {kind}, {r.get('size')} byte, "
            f"quyền {r.get('mode')}, sửa lần cuối {mt:%Y-%m-%d %H:%M}")


@mcp.tool()
def device_mkdir(device: str, path: str) -> str:
    """Tạo thư mục trên thiết bị (tạo cả cấp cha nếu thiếu)."""
    r = _op(device, "mkdir", {"path": path})
    return (f"✅ Đã tạo `{r.get('path')}`" if r.get("ok")
            else f"❌ {r.get('error')}")
