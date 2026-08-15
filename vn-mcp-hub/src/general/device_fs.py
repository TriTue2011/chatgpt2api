"""device_fs — MCP đọc/sửa file trên MỌI thiết bị đã cài c2a-agent.

Khác `fs_remote` (SFTP gọi VÀO server, cần SSH mở + IP tới được): ở đây agent
trên thiết bị **tự quay ra** kết nối tới gateway, nên máy tính, điện thoại
Android, VPS sau NAT/wifi/4G đều dùng được — chỉ cần thiết bị có Internet.

Đường đi: tool này → gateway (127.0.0.1:80 /api/devices/*) → WebSocket xuống
đúng thiết bị → agent thực thi → trả ngược lại.

Ba lớp chặn, cố ý trùng nhau:
  1. Gateway: token → thiết bị + allowlist đường dẫn (config `device_agents`).
  2. Gateway: chặn thao tác ghi/chạy lệnh/tắt máy nếu thiếu quyền tương ứng.
  3. Agent:   tự giữ allowlist + cờ quyền của chính nó, KHÔNG tin gateway.

Bốn nhóm quyền, mỗi nhóm phải bật ở CẢ HAI phía (dự án + cờ khi chạy agent):
  đọc          — luôn có
  can_write    — ghi/xoá file trong allowlist
  can_exec     — chạy lệnh PowerShell/cmd/sh tuỳ ý, tắt tiến trình
  can_power    — khoá màn hình, ngủ, đăng xuất, tắt máy, khởi động lại

Nhóm TRA CỨU hệ thống (sysinfo/resources/processes/services/screen) không cần
quyền gì thêm: agent chỉ chạy các lệnh CỐ ĐỊNH do chính nó chọn và tất cả đều
chỉ đọc — nếu đòi `can_exec` thì muốn xem RAM cũng phải mở quyền chạy lệnh tuỳ ý.
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

GATEWAY = (os.getenv("C2A_GATEWAY_URL", "").strip().rstrip("/")
           or f"http://127.0.0.1:{os.getenv('APP_PORT', '80')}")
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
        quyen = ", ".join(filter(None, [
            "ghi file" if x.get("can_write") else "",
            "chạy lệnh" if x.get("can_exec") else "",
            "tắt/khoá máy" if x.get("can_power") else "",
        ])) or "chỉ đọc"
        lines.append(
            f"• **{x.get('label') or x.get('name')}** (`{x.get('name')}`) — {mark}{extra}\n"
            f"  thư mục: {', '.join(x.get('paths') or []) or '(chưa khai báo)'}\n"
            f"  quyền: {quyen}")
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


# ── Tra cứu hệ thống (chỉ đọc, không cần quyền thêm) ────────────────────────

def _gb(n: Any) -> str:
    try:
        return f"{float(n) / 1024 ** 3:.1f} GB"
    except (TypeError, ValueError):
        return "?"


def _dur(sec: Any) -> str:
    try:
        s = int(sec)
    except (TypeError, ValueError):
        return "?"
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    return (f"{d} ngày {h} giờ {m} phút" if d else
            f"{h} giờ {m} phút" if h else f"{m} phút")


@mcp.tool()
def device_sysinfo(device: str) -> str:
    """Thông tin máy: hệ điều hành, tên máy, CPU, người đang đăng nhập, uptime.

    Chỉ đọc — dùng được cả khi thiết bị chỉ có quyền đọc. Trả kèm thiết bị đang
    được cấp những quyền nào, hữu ích khi cần biết vì sao một lệnh bị chặn.
    """
    r = _op(device, "sysinfo", {})
    if not r.get("ok"):
        return f"❌ {r.get('error')}"
    quyen = ", ".join(filter(None, [
        "ghi file" if r.get("allow_write") else "",
        "chạy lệnh" if r.get("allow_exec") else "",
        "tắt/khoá máy" if r.get("allow_power") else "",
    ])) or "chỉ đọc"
    return "\n".join([
        f"🖥 **{r.get('hostname')}**",
        f"• Hệ điều hành: {r.get('platform')}",
        f"• Kiến trúc: {r.get('machine')} · {r.get('cpu_count')} lõi CPU",
        f"• Đang đăng nhập: {r.get('user') or '?'}",
        f"• Bật máy được: {_dur(r.get('uptime_seconds'))}",
        f"• Python {r.get('python')} · agent v{r.get('agent_version')}",
        f"• Quyền agent tự khai: {quyen}",
    ])


@mcp.tool()
def device_resources(device: str) -> str:
    """Tài nguyên đang dùng: CPU %, RAM, dung lượng ổ đĩa, load average.

    Chỉ đọc. Dùng khi cần biết máy có đang nặng không, còn bao nhiêu chỗ trống.
    """
    r = _op(device, "resources", {})
    if not r.get("ok"):
        return f"❌ {r.get('error')}"
    out = []
    cpu = r.get("cpu_percent")
    out.append(f"⚙️ CPU: {cpu}% / {r.get('cpu_count')} lõi"
               if cpu is not None else f"⚙️ CPU: {r.get('cpu_count')} lõi (không đo được %)")
    la = r.get("load_avg") or []
    if la:
        out.append("• Load 1/5/15 phút: " + " · ".join(f"{x:.2f}" for x in la))
    if r.get("mem_total"):
        out.append(f"🧠 RAM: {_gb(r.get('mem_used'))} / {_gb(r.get('mem_total'))}"
                   f" ({r.get('mem_percent')}%)")
    for d in r.get("disks") or []:
        out.append(f"💾 {d.get('mount')}: {_gb(d.get('used'))} / {_gb(d.get('total'))}"
                   f" ({d.get('percent')}%) · trống {_gb(d.get('free'))}")
    return "\n".join(out)


@mcp.tool()
def device_processes(device: str, limit: int = 15, name: str = "") -> str:
    """Các tiến trình đang chạy, sắp theo RAM giảm dần.

    `name` để lọc theo tên (vd "chrome"). Chỉ đọc — muốn TẮT thì dùng
    device_kill (cần quyền chạy lệnh).
    """
    r = _op(device, "processes", {"limit": limit, "name": name})
    if not r.get("ok"):
        return f"❌ {r.get('error')}"
    rows = r.get("processes") or []
    if not rows:
        return (f"Không có tiến trình nào khớp `{name}`" if name
                else "Không đọc được danh sách tiến trình")
    head = f"{r.get('count')} tiến trình" + (f" (lọc `{name}`)" if name else "")
    lines = [f"{head}, {len(rows)} dòng đầu theo RAM:"]
    for p in rows:
        mb = (p.get("mem_kb") or 0) / 1024
        cpu = f" · CPU {p.get('cpu')}%" if p.get("cpu") is not None else ""
        lines.append(f"• `{p.get('pid')}` {p.get('name')} — {mb:.0f} MB{cpu}")
    return "\n".join(lines)


@mcp.tool()
def device_services(device: str, name: str = "") -> str:
    """Danh sách service/daemon trên thiết bị, hoặc trạng thái MỘT service.

    Windows dùng `sc query`, Linux `systemctl`, macOS `launchctl` — agent tự
    chọn, chỉ đọc.
    """
    r = _op(device, "services", {"name": name})
    if not r.get("ok"):
        return f"❌ {r.get('error')}"
    body = str(r.get("output") or "").strip()
    if not body:
        return "Không có dữ liệu service."
    if len(body) > 6000:
        body = body[:6000] + "\n…(đã cắt bớt)"
    tag = f" — `{name}`" if name else ""
    return f"Service{tag}:\n```\n{body}\n```"


@mcp.tool()
def device_screen(device: str) -> str:
    """Màn hình đang sáng/tắt, máy có đang khoá không, bao lâu không ai chạm.

    Nói thẳng về giới hạn: không hệ điều hành nào cho biết đủ cả ba thứ này một
    cách chắc chắn, nên trường nào không đo được sẽ ghi rõ là "không rõ" kèm lý
    do, thay vì đoán bừa.
    """
    r = _op(device, "screen", {})
    if not r.get("ok"):
        return f"❌ {r.get('error')}"
    v = lambda b: "có" if b is True else ("không" if b is False else "không rõ")  # noqa: E731
    out = [f"🔒 Đang khoá màn hình: {v(r.get('locked'))}",
           f"💡 Màn hình sáng: {v(r.get('display_on'))}"]
    if r.get("idle_seconds") is not None:
        out.append(f"🕐 Không ai chạm máy: {_dur(r.get('idle_seconds'))}")
    if r.get("note"):
        out.append(f"_Lưu ý: {r.get('note')}_")
    return "\n".join(out)


# ── Can thiệp (cần quyền riêng, mặc định TẮT) ───────────────────────────────

@mcp.tool()
def device_exec(device: str, command: str, shell: str = "",
                timeout: int = 30, cwd: str = "") -> str:
    """Chạy MỘT lệnh trên thiết bị (PowerShell / cmd / sh) và trả kết quả.

    Dùng để tra cứu sâu, cài đặt phần mềm (winget, apt, brew), xem cấu hình
    mạng, quản lý service… — bất cứ gì làm được ở dòng lệnh.

    `shell`: để trống = mặc định của máy (Windows → PowerShell, còn lại → sh).
    Đặt "cmd" để dùng cmd.exe trên Windows.
    `timeout`: giây, tối đa 300. `cwd`: thư mục chạy lệnh.

    CẦN quyền "chạy lệnh" bật ở CẢ dự án lẫn agent (--allow-exec). Thiếu một
    phía là bị chặn — đó là chủ ý, không phải lỗi.

    LƯU Ý cho người gọi: lệnh chạy với quyền của tài khoản đang chạy agent và
    KHÔNG bị giới hạn trong allowlist thư mục. Không chạy lệnh phá hoại; việc
    xoá/định dạng/tắt dịch vụ quan trọng phải để chủ máy tự quyết.
    """
    args: dict[str, Any] = {"command": command, "timeout": timeout}
    if shell:
        args["shell"] = shell
    if cwd:
        args["cwd"] = cwd
    r = _op(device, "exec", args)
    if r.get("error") and not r.get("stdout") and not r.get("stderr"):
        return f"❌ {r.get('error')}"
    parts = [f"`{r.get('command')}` qua **{r.get('shell')}** → rc={r.get('rc')}"]
    if r.get("stdout"):
        parts.append("stdout:\n```\n" + str(r["stdout"]).rstrip() + "\n```")
    if r.get("stderr"):
        parts.append("stderr:\n```\n" + str(r["stderr"]).rstrip() + "\n```")
    if not r.get("stdout") and not r.get("stderr"):
        parts.append("_(không có kết quả in ra)_")
    if r.get("truncated"):
        parts.append("_(kết quả đã bị cắt bớt)_")
    return "\n".join(parts)


@mcp.tool()
def device_kill(device: str, pid: str = "", name: str = "",
                force: bool = False) -> str:
    """Tắt một ứng dụng / tiến trình theo `pid` hoặc `name`.

    Dùng device_processes để lấy pid trước. `force=True` là tắt cưỡng bức (mất
    dữ liệu chưa lưu). CẦN quyền "chạy lệnh".
    """
    r = _op(device, "kill", {"pid": pid, "name": name, "force": force})
    if not r.get("ok"):
        detail = str(r.get("stderr") or r.get("error") or "").strip()
        return f"❌ Không tắt được `{pid or name}`: {detail[:300]}"
    return f"✅ Đã gửi lệnh tắt `{r.get('target')}`" + (
        " (cưỡng bức)" if force else "")


@mcp.tool()
def device_unlock(device: str, password: str = "") -> str:
    """Mở khoá màn hình đang bị khoá của MÁY người dùng.

    CẦN quyền "tắt/khoá máy". Trên Windows thường KHÔNG chạy được: màn hình khoá
    do LogonUI vẽ trên desktop riêng, phần mềm chạy quyền người dùng thường
    không chạm vào được — đó là thiết kế an ninh của Windows.

    ĐỪNG hỏi mật khẩu trước rồi mới gọi: mật khẩu KHÔNG phải thứ mở được khoá ở
    đây, quyền SYSTEM mới là. Gọi thẳng, rồi báo đúng những gì máy trả về. Nếu
    thất bại vì thiếu quyền thì nói rõ là cần cài lại agent kèm tác vụ SYSTEM,
    chứ không phải xin mật khẩu.
    """
    r = _op(device, "unlock", {"password": password} if password else {})
    if r.get("ok"):
        return f"✅ Đã mở khoá màn hình `{device}`"
    detail = str(r.get("error") or r.get("stderr") or "").strip()
    msg = f"❌ Chưa mở khoá được `{device}`: {detail[:300]}"
    if r.get("mat_khau_khong_giup"):
        msg += ("\n_Mật khẩu không giúp được ở bước này — Windows chặn phần mềm "
                "gõ mật khẩu vào màn hình khoá._")
    return msg


@mcp.tool()
def device_power(device: str, action: str) -> str:
    """Khoá màn hình / ngủ / đăng xuất / TẮT MÁY / khởi động lại.

    `action`: lock | sleep | logoff | shutdown | restart

    CẦN quyền "tắt/khoá máy" (--allow-power). Đây là thao tác ẢNH HƯỞNG NGƯỜI
    ĐANG DÙNG MÁY: chỉ gọi khi người dùng nói rõ muốn làm việc đó, và nêu rõ máy
    nào trước khi gọi. `shutdown`/`restart` làm agent mất kết nối — đó là bình
    thường, không phải lỗi.
    """
    r = _op(device, "power", {"action": action})
    if not r.get("ok"):
        detail = str(r.get("stderr") or r.get("error") or "").strip()
        return f"❌ Không thực hiện được `{action}`: {detail[:300]}"
    msg = f"✅ Đã gửi lệnh **{action}** tới `{device}`"
    if r.get("note"):
        msg += f"\n_{r.get('note')}_"
    return msg
