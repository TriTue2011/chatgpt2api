"""Gọi API RouterOS (MikroTik) qua cổng API-SSL 8729 — giao thức câu-từ của MikroTik, không thêm thư viện.

Tài khoản đọc từ ``mang_nha.router`` (host, port, ssl, username, password). Chủ máy tạo 03/10/2026 tài khoản riêng
``c2a`` nhóm ``read,write,api``, chỉ đăng nhập được từ 172.16.10.38. Router dùng chứng chỉ tự ký nên không kiểm tên
— đường đi nằm trong LAN, cổng chỉ mở cho .38 (luật input «c2a API SSL»).

Hợp đồng: ``with ket_noi() as r: r.goi("/ip/dhcp-server/lease/print", truy_van=["?dynamic=true"])`` trả list
dict (bỏ dấu «=» đầu khoá); lệnh add trả ``[{"ret": "*1A"}]``. Router từ chối → ``Loi`` mang NGUYÊN lời router
(chủ máy: bị chặn hay từ chối phải nói lý do). Chưa cấu hình → ``Loi`` nói thiếu gì.
"""
from __future__ import annotations

import socket
import ssl
from typing import Any

HET_GIO = 8.0


class Loi(Exception):
    pass


def _ma_do_dai(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n < 0x4000:
        return (n | 0x8000).to_bytes(2, "big")
    if n < 0x200000:
        return (n | 0xC00000).to_bytes(3, "big")
    if n < 0x10000000:
        return (n | 0xE0000000).to_bytes(4, "big")
    return b"\xf0" + n.to_bytes(4, "big")


class Phien:
    def __init__(self, sock: Any):
        self._s = sock

    def _doc(self, n: int) -> bytes:
        b = b""
        while len(b) < n:
            c = self._s.recv(n - len(b))
            if not c:
                raise Loi("router đóng kết nối giữa chừng")
            b += c
        return b

    def _do_dai(self) -> int:
        c = self._doc(1)[0]
        if c < 0x80:
            return c
        if c < 0xC0:
            return ((c & 0x3F) << 8) | self._doc(1)[0]
        if c < 0xE0:
            return ((c & 0x1F) << 16) | int.from_bytes(self._doc(2), "big")
        if c < 0xF0:
            return ((c & 0x0F) << 24) | int.from_bytes(self._doc(3), "big")
        return int.from_bytes(self._doc(4), "big")

    def _cau(self) -> list[str]:
        tu: list[str] = []
        while (n := self._do_dai()) != 0:
            tu.append(self._doc(n).decode("utf-8", errors="replace"))
        return tu

    def goi(self, lenh: str, truy_van: list[str] | None = None, **thuoc_tinh: Any) -> list[dict[str, str]]:
        """``thuoc_tinh`` viết gạch dưới thay gạch nối (``mac_address`` → ``mac-address``); ``id`` → ``.id``."""
        tu = [lenh]
        for k, v in thuoc_tinh.items():
            k = ".id" if k == "id" else k.replace("_", "-")
            tu.append(f"={k}={'yes' if v is True else 'no' if v is False else v}")
        tu += list(truy_van or [])
        for w in tu:
            b = w.encode("utf-8")
            self._s.sendall(_ma_do_dai(len(b)) + b)
        self._s.sendall(b"\x00")
        ra: list[dict[str, str]] = []
        while True:
            cau = self._cau()
            if not cau:
                continue
            d = {}
            for w in cau[1:]:
                k, _, v = w[1:].partition("=")
                d[k] = v
            if cau[0] == "!re":
                ra.append(d)
            elif cau[0] == "!done":
                if "ret" in d:
                    ra.append({"ret": d["ret"]})
                return ra
            elif cau[0] in ("!trap", "!fatal"):
                # Sau !trap router vẫn gửi !done — đọc hết để phiên dùng tiếp được.
                if cau[0] == "!trap":
                    while (c := self._cau()) and c[0] != "!done":
                        pass
                raise Loi(f"router từ chối «{lenh}»: {d.get('message') or cau}")

    def dong(self) -> None:
        try:
            self._s.close()
        except OSError:
            pass

    def __enter__(self) -> "Phien":
        return self

    def __exit__(self, *a: Any) -> None:
        self.dong()


def cau_hinh() -> dict[str, Any]:
    from services.config import config
    r = (config.data.get("mang_nha") or {}).get("router")
    return r if isinstance(r, dict) else {}


def ket_noi(cfg: dict[str, Any] | None = None) -> Phien:
    c = cfg if cfg is not None else cau_hinh()
    thieu = [k for k in ("host", "username", "password") if not c.get(k)]
    if thieu:
        raise Loi(f"chưa cấu hình router MikroTik (thiếu {', '.join(thieu)}) — điền ở Cài đặt › Home Assistant › Mạng nhà")
    dung_ssl = c.get("ssl", True) is not False
    cong = int(c.get("port") or (8729 if dung_ssl else 8728))
    try:
        s: Any = socket.create_connection((str(c["host"]), cong), timeout=HET_GIO)
        if dung_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            s = ctx.wrap_socket(s)
    except OSError as exc:
        raise Loi(f"không vào được router {c['host']}:{cong} ({exc}) — kiểm luật tường lửa «c2a API SSL» "
                  f"và /ip service api-ssl address") from exc
    p = Phien(s)
    try:
        p.goi("/login", name=c["username"], password=c["password"])
    except Loi as exc:
        p.dong()
        raise Loi(f"đăng nhập router bằng «{c['username']}» không được: {exc}") from exc
    except OSError as exc:
        p.dong()
        raise Loi(f"router ngắt khi đăng nhập ({exc})") from exc
    return p
