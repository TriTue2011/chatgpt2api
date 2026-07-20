"""fs_remote — MCP file an toàn trên server từ xa qua SFTP.

Khác với ssh_exec (chạy lệnh shell tùy ý), fs_remote chỉ phơi bày các thao tác
FILE cụ thể, có kiểm soát phạm vi thư mục cho từng server:

- ĐỌC: nếu server chưa khai báo read_paths → đọc mọi nơi (theo quyền OS của
  user SSH). Nếu có khai báo → chỉ đọc trong các thư mục đó.
- GHI/XOÁ/TẠO THƯ MỤC: BẮT BUỘC nằm trong write_paths. write_paths rỗng → CẤM
  hoàn toàn (an toàn mặc định). Cấp quyền bằng fs_grant_write (qua chat).

Dùng chung registry server với ssh_exec — thêm server 1 lần (ssh_add_server)
là dùng được cho cả chạy lệnh lẫn thao tác file.

Tools:
- fs_list(server, path): liệt kê thư mục
- fs_read(server, path): đọc nội dung file (text)
- fs_write(server, path, content): tạo/ghi đè file (trong write_paths)
- fs_append(server, path, content): ghi thêm cuối file
- fs_mkdir(server, path): tạo thư mục
- fs_delete(server, path, confirm): xoá file
- fs_stat(server, path): thông tin file
- fs_find(server, path, name_contains): tìm file theo tên (đệ quy, có giới hạn)
- fs_permissions(server): xem thư mục được phép đọc/ghi
- fs_grant_write(server, path) / fs_grant_read(server, path): cấp quyền qua chat
"""

from __future__ import annotations

import posixpath
import stat as _stat
from typing import Any

from fastmcp import FastMCP

from src.general.ssh_exec import connect, find_server, list_servers_safe, set_paths

mcp = FastMCP("fs_remote")

_MAX_READ = 200_000       # trần đọc 1 file trả về model (~200KB)
_MAX_WRITE = 500_000      # trần ghi 1 lần
_MAX_LIST = 500           # trần số mục liệt kê
_MAX_FIND = 200           # trần số kết quả tìm
_FIND_MAX_DIRS = 2000     # trần số thư mục duyệt khi tìm


# ── Helpers ──────────────────────────────────────────────────────────────────


def _norm(path: str) -> str:
    """Chuẩn hoá path POSIX tuyệt đối. Trả '' nếu không hợp lệ (không tuyệt đối)."""
    if not path:
        return ""
    p = str(path).replace("\\", "/").strip()
    if not p.startswith("/"):
        return ""
    return posixpath.normpath(p)


def _within(path: str, prefixes: list[str]) -> bool:
    np = _norm(path)
    if not np:
        return False
    for pref in prefixes or []:
        pn = posixpath.normpath(str(pref).replace("\\", "/"))
        if np == pn or np.startswith(pn.rstrip("/") + "/"):
            return True
    return False


def _entry(server: str) -> dict[str, Any] | None:
    return find_server(server)


def _unknown(server: str) -> str:
    names = ", ".join(s["name"] for s in list_servers_safe()) or "(chưa có server nào)"
    return f"Lỗi: chưa khai báo server '{server}'. Server hiện có: {names}"


def _check_read(entry: dict[str, Any], path: str) -> str | None:
    np = _norm(path)
    if not np:
        return "Lỗi: đường dẫn phải là tuyệt đối (bắt đầu bằng /)."
    rp = entry.get("read_paths") or []
    if rp and not _within(path, rp):
        return (f"❌ Từ chối đọc '{path}': ngoài phạm vi cho phép. "
                f"Chỉ đọc trong: {', '.join(rp)}")
    return None


def _check_write(entry: dict[str, Any], path: str) -> str | None:
    np = _norm(path)
    if not np:
        return "Lỗi: đường dẫn phải là tuyệt đối (bắt đầu bằng /)."
    wp = entry.get("write_paths") or []
    if not wp:
        return (f"❌ Từ chối ghi trên '{entry.get('name')}': chưa cấp thư mục ghi nào. "
                f"Cấp quyền bằng fs_grant_write(server, '<thư_mục>').")
    if not _within(path, wp):
        return (f"❌ Từ chối ghi '{path}': ngoài phạm vi cho phép. "
                f"Chỉ ghi trong: {', '.join(wp)}")
    return None


class _Conn:
    """Context manager: mở SSH + SFTP, tự đóng."""

    def __init__(self, entry: dict[str, Any]):
        self.entry = entry
        self.client = None
        self.sftp = None

    def __enter__(self):
        self.client = connect(self.entry)
        self.sftp = self.client.open_sftp()
        return self.sftp

    def __exit__(self, *exc):
        try:
            if self.sftp:
                self.sftp.close()
        finally:
            if self.client:
                self.client.close()


# ── MCP tools ────────────────────────────────────────────────────────────────


@mcp.tool()
def fs_list(server: str, path: str = "/") -> str:
    """Liệt kê nội dung một thư mục trên server từ xa.

    Args:
        server: Tên server đã khai báo (xem ssh_list_servers).
        path: Đường dẫn thư mục tuyệt đối (vd: "/config", "/home/user").
    """
    entry = _entry(server)
    if not entry:
        return _unknown(server)
    if (err := _check_read(entry, path)):
        return err
    try:
        with _Conn(entry) as sftp:
            items = sftp.listdir_attr(_norm(path))
    except Exception as exc:
        return f"❌ Lỗi liệt kê '{path}' trên '{server}': {exc}"
    items.sort(key=lambda a: (not _stat.S_ISDIR(a.st_mode or 0), a.filename))
    lines = [f"[{server}] {path}  ({len(items)} mục)"]
    for a in items[:_MAX_LIST]:
        is_dir = _stat.S_ISDIR(a.st_mode or 0)
        size = "" if is_dir else f"  {a.st_size} B"
        lines.append(f"{'d' if is_dir else '-'} {a.filename}{'/' if is_dir else ''}{size}")
    if len(items) > _MAX_LIST:
        lines.append(f"… (còn {len(items) - _MAX_LIST} mục, đã cắt)")
    return "\n".join(lines)


@mcp.tool()
def fs_read(server: str, path: str) -> str:
    """Đọc nội dung một file text trên server từ xa.

    Args:
        server: Tên server đã khai báo.
        path: Đường dẫn file tuyệt đối.
    """
    entry = _entry(server)
    if not entry:
        return _unknown(server)
    if (err := _check_read(entry, path)):
        return err
    try:
        with _Conn(entry) as sftp:
            with sftp.open(_norm(path), "r") as f:
                data = f.read(_MAX_READ + 1)
    except Exception as exc:
        return f"❌ Lỗi đọc '{path}' trên '{server}': {exc}"
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
    truncated = len(text) > _MAX_READ
    if truncated:
        text = text[:_MAX_READ]
    header = f"[{server}] {path}" + ("  (đã cắt bớt)" if truncated else "")
    return f"{header}\n{text}"


@mcp.tool()
def fs_write(server: str, path: str, content: str, overwrite: bool = True) -> str:
    """Tạo mới hoặc ghi đè một file text (chỉ trong thư mục được cấp quyền ghi).

    Args:
        server: Tên server đã khai báo.
        path: Đường dẫn file tuyệt đối, phải nằm trong write_paths.
        content: Nội dung file.
        overwrite: True = ghi đè nếu file đã tồn tại; False = báo lỗi nếu đã có.
    """
    entry = _entry(server)
    if not entry:
        return _unknown(server)
    if (err := _check_write(entry, path)):
        return err
    if len(content or "") > _MAX_WRITE:
        return f"❌ Nội dung quá lớn (>{_MAX_WRITE} ký tự)."
    np = _norm(path)
    try:
        with _Conn(entry) as sftp:
            if not overwrite:
                try:
                    sftp.stat(np)
                    return f"❌ File '{path}' đã tồn tại (overwrite=False)."
                except IOError:
                    pass
            with sftp.open(np, "w") as f:
                f.write(content or "")
    except Exception as exc:
        return f"❌ Lỗi ghi '{path}' trên '{server}': {exc}"
    return f"✅ Đã ghi {len(content or '')} ký tự vào '{path}' trên '{server}'."


@mcp.tool()
def fs_append(server: str, path: str, content: str) -> str:
    """Ghi thêm nội dung vào cuối file (chỉ trong thư mục được cấp quyền ghi).

    Args:
        server: Tên server đã khai báo.
        path: Đường dẫn file tuyệt đối, phải nằm trong write_paths.
        content: Nội dung cần nối thêm.
    """
    entry = _entry(server)
    if not entry:
        return _unknown(server)
    if (err := _check_write(entry, path)):
        return err
    try:
        with _Conn(entry) as sftp:
            with sftp.open(_norm(path), "a") as f:
                f.write(content or "")
    except Exception as exc:
        return f"❌ Lỗi ghi thêm '{path}' trên '{server}': {exc}"
    return f"✅ Đã nối {len(content or '')} ký tự vào '{path}' trên '{server}'."


@mcp.tool()
def fs_mkdir(server: str, path: str) -> str:
    """Tạo một thư mục mới (chỉ trong thư mục được cấp quyền ghi).

    Args:
        server: Tên server đã khai báo.
        path: Đường dẫn thư mục tuyệt đối, phải nằm trong write_paths.
    """
    entry = _entry(server)
    if not entry:
        return _unknown(server)
    if (err := _check_write(entry, path)):
        return err
    try:
        with _Conn(entry) as sftp:
            sftp.mkdir(_norm(path))
    except Exception as exc:
        return f"❌ Lỗi tạo thư mục '{path}' trên '{server}': {exc}"
    return f"✅ Đã tạo thư mục '{path}' trên '{server}'."


@mcp.tool()
def fs_delete(server: str, path: str, confirm: bool = False) -> str:
    """Xoá một file (chỉ trong thư mục được cấp quyền ghi). Cần confirm=True.

    Args:
        server: Tên server đã khai báo.
        path: Đường dẫn file tuyệt đối, phải nằm trong write_paths.
        confirm: Phải đặt True để thực sự xoá (tránh xoá nhầm).
    """
    entry = _entry(server)
    if not entry:
        return _unknown(server)
    if (err := _check_write(entry, path)):
        return err
    if not confirm:
        return f"⚠️ Xác nhận xoá: gọi lại fs_delete('{server}', '{path}', confirm=True) để xoá thật."
    try:
        with _Conn(entry) as sftp:
            sftp.remove(_norm(path))
    except Exception as exc:
        return f"❌ Lỗi xoá '{path}' trên '{server}': {exc}"
    return f"✅ Đã xoá '{path}' trên '{server}'."


@mcp.tool()
def fs_stat(server: str, path: str) -> str:
    """Xem thông tin (loại, kích thước, thời gian sửa) của một file/thư mục.

    Args:
        server: Tên server đã khai báo.
        path: Đường dẫn tuyệt đối.
    """
    entry = _entry(server)
    if not entry:
        return _unknown(server)
    if (err := _check_read(entry, path)):
        return err
    try:
        with _Conn(entry) as sftp:
            st = sftp.stat(_norm(path))
    except Exception as exc:
        return f"❌ Lỗi stat '{path}' trên '{server}': {exc}"
    import datetime
    kind = "thư mục" if _stat.S_ISDIR(st.st_mode or 0) else "file"
    mtime = datetime.datetime.fromtimestamp(st.st_mtime or 0).strftime("%Y-%m-%d %H:%M")
    return f"[{server}] {path}\n- Loại: {kind}\n- Kích thước: {st.st_size} B\n- Sửa lần cuối: {mtime}\n- Quyền: {oct(st.st_mode or 0)[-3:]}"


@mcp.tool()
def fs_find(server: str, path: str, name_contains: str = "") -> str:
    """Tìm file theo tên (đệ quy, có giới hạn) trong một thư mục.

    Args:
        server: Tên server đã khai báo.
        path: Thư mục gốc để tìm (tuyệt đối).
        name_contains: Chuỗi con cần có trong tên file (rỗng = liệt kê mọi file).
    """
    entry = _entry(server)
    if not entry:
        return _unknown(server)
    if (err := _check_read(entry, path)):
        return err
    needle = (name_contains or "").lower()
    results: list[str] = []
    dirs_seen = 0
    try:
        with _Conn(entry) as sftp:
            stack = [_norm(path)]
            while stack and len(results) < _MAX_FIND and dirs_seen < _FIND_MAX_DIRS:
                cur = stack.pop()
                dirs_seen += 1
                try:
                    for a in sftp.listdir_attr(cur):
                        full = posixpath.join(cur, a.filename)
                        if _stat.S_ISDIR(a.st_mode or 0):
                            stack.append(full)
                        elif not needle or needle in a.filename.lower():
                            results.append(full)
                            if len(results) >= _MAX_FIND:
                                break
                except Exception:
                    continue
    except Exception as exc:
        return f"❌ Lỗi tìm trong '{path}' trên '{server}': {exc}"
    if not results:
        return f"[{server}] Không tìm thấy file khớp '{name_contains}' trong {path}."
    head = f"[{server}] {len(results)} kết quả trong {path}:"
    return head + "\n" + "\n".join(results)


@mcp.tool()
def fs_permissions(server: str) -> str:
    """Xem các thư mục được phép ĐỌC/GHI của một server.

    Args:
        server: Tên server đã khai báo.
    """
    s = next((x for x in list_servers_safe() if x["name"].lower() == (server or "").lower()), None)
    if not s:
        return _unknown(server)
    rp = s.get("read_paths") or []
    wp = s.get("write_paths") or []
    return (f"[{server}] Quyền file:\n"
            f"- Đọc: {', '.join(rp) if rp else 'mọi nơi (theo quyền OS)'}\n"
            f"- Ghi: {', '.join(wp) if wp else 'CẤM (chưa cấp thư mục ghi nào)'}")


@mcp.tool()
def fs_grant_write(server: str, path: str) -> str:
    """Cấp quyền GHI cho một thư mục trên server (để bot tự cấu hình qua chat).

    Args:
        server: Tên server đã khai báo.
        path: Thư mục cho phép ghi (tuyệt đối, vd "/config", "/tmp").
    """
    r = set_paths(server, add_write=path)
    if not r.get("ok"):
        return f"Lỗi: {r.get('error')}"
    return f"✅ Đã cấp quyền ghi '{path}' cho '{server}'. Thư mục ghi hiện tại: {', '.join(r['write_paths'])}"


@mcp.tool()
def fs_grant_read(server: str, path: str) -> str:
    """Giới hạn quyền ĐỌC vào một thư mục (thêm vào danh sách read_paths).

    Lưu ý: khi read_paths rỗng, server đọc được mọi nơi. Thêm thư mục vào đây sẽ
    GIỚI HẠN chỉ đọc trong các thư mục đã liệt kê.

    Args:
        server: Tên server đã khai báo.
        path: Thư mục cho phép đọc (tuyệt đối).
    """
    r = set_paths(server, add_read=path)
    if not r.get("ok"):
        return f"Lỗi: {r.get('error')}"
    return f"✅ Đã giới hạn đọc trong '{path}' cho '{server}'. Thư mục đọc hiện tại: {', '.join(r['read_paths'])}"
