"""Sổ đăng ký + bộ điều phối các device agent kết nối NGƯỢC về gateway.

Mô hình: agent nhỏ trên máy/điện thoại/VPS **tự quay ra** mở WebSocket tới
gateway (đường công khai qua Cloudflare tunnel) và ở đó chờ lệnh. Nhờ chiều
kết nối đảo, thiết bị nằm sau NAT/wifi/4G vẫn dùng được — thứ mà fs_remote
(SFTP gọi vào) và ssh_exec không làm được.

Mô hình tin cậy — hai lớp allowlist, cố ý trùng nhau:
  * Gateway: token → tên thiết bị + tiền tố đường dẫn cho phép (config).
  * Agent:   tự giữ allowlist của chính nó, KHÔNG tin lệnh từ gateway.
Gateway bị chiếm cũng không mở rộng được quyền trên thiết bị.

Ghi/xoá là hành vi KHÔNG hoàn tác được nên mặc định tắt: mỗi thiết bị phải
bật `can_write` tường minh trong config.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

from services.config import config
from utils.log import logger

# device_name → phiên đang kết nối
_sessions: dict[str, "AgentSession"] = {}
_lock = asyncio.Lock()

_OP_TIMEOUT = 60.0          # trần mỗi lệnh gửi xuống thiết bị
_MAX_PENDING = 32           # trần lệnh chờ song song mỗi thiết bị


def _registry() -> dict[str, dict[str, Any]]:
    """`device_agents` trong config: {name: {token, paths[], can_write, label}}."""
    d = config.data.get("device_agents") or {}
    return d if isinstance(d, dict) else {}


def resolve_token(token: str) -> tuple[str, dict[str, Any]] | None:
    """token → (device_name, cfg). None nếu không khớp thiết bị nào."""
    tok = str(token or "").strip()
    if len(tok) < 16:       # token ngắn = đoán được; chặn ngay từ cửa
        return None
    for name, cfg in _registry().items():
        if not isinstance(cfg, dict) or not cfg.get("enabled", True):
            continue
        if str(cfg.get("token") or "").strip() == tok:
            return str(name), cfg
    return None


class AgentSession:
    """Một thiết bị đang kết nối. Ghép request↔response bằng id."""

    def __init__(self, name: str, cfg: dict[str, Any], ws: Any) -> None:
        self.name = name
        self.cfg = cfg
        self.ws = ws
        self.connected_at = time.time()
        self.info: dict[str, Any] = {}
        self.ops = 0
        self._pending: dict[str, asyncio.Future] = {}

    @property
    def allowed_paths(self) -> list[str]:
        p = self.cfg.get("paths")
        return [str(x) for x in p if str(x).strip()] if isinstance(p, list) else []

    @property
    def can_write(self) -> bool:
        return bool(self.cfg.get("can_write", False))

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": str(self.cfg.get("label") or self.name),
            "connected": True,
            "connected_at": self.connected_at,
            "platform": self.info.get("platform", ""),
            "hostname": self.info.get("hostname", ""),
            "agent_version": self.info.get("version", ""),
            "paths": self.allowed_paths,
            "can_write": self.can_write,
            "ops": self.ops,
        }

    async def call(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        """Gửi một lệnh xuống thiết bị và chờ kết quả."""
        if len(self._pending) >= _MAX_PENDING:
            return {"ok": False, "error": "thiết bị đang quá tải lệnh chờ"}
        rid = uuid.uuid4().hex[:12]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self.ws.send_json({"id": rid, "op": op, "args": args})
        except Exception as exc:
            self._pending.pop(rid, None)
            return {"ok": False, "error": f"mất kết nối tới thiết bị: {str(exc)[:80]}"}
        try:
            res = await asyncio.wait_for(fut, timeout=_OP_TIMEOUT)
        except asyncio.TimeoutError:
            return {"ok": False, "error": f"thiết bị không trả lời trong {int(_OP_TIMEOUT)}s"}
        finally:
            self._pending.pop(rid, None)
        self.ops += 1
        return res if isinstance(res, dict) else {"ok": False, "error": "phản hồi không hợp lệ"}

    def deliver(self, msg: dict[str, Any]) -> None:
        """Agent trả kết quả → đánh thức future tương ứng."""
        fut = self._pending.get(str(msg.get("id") or ""))
        if fut is not None and not fut.done():
            fut.set_result(msg.get("result") if isinstance(msg.get("result"), dict)
                           else {"ok": False, "error": str(msg.get("error") or "lỗi không rõ")[:200]})

    def fail_all(self, reason: str) -> None:
        """Đứt kết nối → mọi lệnh đang chờ phải trả lỗi ngay, không treo caller."""
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_result({"ok": False, "error": reason})
        self._pending.clear()


async def register(session: AgentSession) -> None:
    async with _lock:
        old = _sessions.get(session.name)
        _sessions[session.name] = session
    if old is not None:
        # Cùng thiết bị nối lại (mạng đổi) — phiên cũ thành zombie, dọn ngay.
        old.fail_all("thiết bị đã nối lại bằng phiên mới")
        try:
            await old.ws.close()
        except Exception:
            pass
    logger.info({"event": "device_agent_connected", "device": session.name,
                 "platform": session.info.get("platform", "")})


async def unregister(session: AgentSession, reason: str = "đóng kết nối") -> None:
    async with _lock:
        if _sessions.get(session.name) is session:
            _sessions.pop(session.name, None)
    session.fail_all(reason)
    logger.info({"event": "device_agent_disconnected", "device": session.name,
                 "reason": reason[:80], "ops": session.ops})


def get(name: str) -> Optional[AgentSession]:
    return _sessions.get(str(name or "").strip())


def list_devices() -> list[dict[str, Any]]:
    """Mọi thiết bị đã KHAI BÁO — kèm cái đang offline, để biết mà chờ."""
    out: list[dict[str, Any]] = []
    for name, cfg in _registry().items():
        if not isinstance(cfg, dict):
            continue
        s = _sessions.get(name)
        if s is not None:
            out.append(s.public())
        else:
            out.append({
                "name": name,
                "label": str(cfg.get("label") or name),
                "connected": False,
                "paths": [str(x) for x in (cfg.get("paths") or [])],
                "can_write": bool(cfg.get("can_write", False)),
            })
    return out


def path_allowed(session: AgentSession, path: str) -> bool:
    """Đường dẫn có nằm trong allowlist của thiết bị không.

    Allowlist rỗng = KHÔNG cho gì cả (fail-closed). Cấu hình thiếu sót không
    bao giờ được biến thành "mở toàn máy" — đó là cách rò quyền kinh điển.
    """
    p = str(path or "")
    prefixes = session.allowed_paths
    if not p or not prefixes:
        return False
    if ".." in p.replace("\\", "/").split("/"):
        return False        # chặn leo thư mục trước khi tới agent
    norm = p.replace("\\", "/").rstrip("/") or "/"
    for pref in prefixes:
        pr = str(pref).replace("\\", "/").rstrip("/") or "/"
        if norm == pr or norm.startswith(pr + "/"):
            return True
    return False
