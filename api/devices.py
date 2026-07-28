"""Endpoint cho device agent: WebSocket để agent quay ra, REST để MCP gọi vào.

Agent (máy/điện thoại/VPS) mở WS tới `/api/devices/agent` — chiều ĐẢO nên
thiết bị sau NAT vẫn tới được. MCP `device_fs` trên hub gọi các route REST
`/api/devices/*` qua localhost để đọc/sửa file trên đúng thiết bị đó.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect

from api.support import require_admin
from services import device_agents as da
from services.config import config
from utils.log import logger

_READ_OPS = {"ls", "read", "stat", "find"}
_WRITE_OPS = {"write", "mkdir", "delete", "append"}


def create_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/api/devices/agent")
    async def device_agent_ws(ws: WebSocket):
        """Agent kết nối vào đây. Frame đầu PHẢI là hello kèm token."""
        await ws.accept()
        session = None
        try:
            hello = await ws.receive_json()
            if not isinstance(hello, dict) or hello.get("type") != "hello":
                await ws.close(code=4400)
                return
            match = da.resolve_token(str(hello.get("token") or ""))
            if match is None:
                # Không nói rõ vì sao — token sai thì đừng giúp bên kia dò.
                logger.warning({"event": "device_agent_auth_failed"})
                await ws.send_json({"type": "error", "error": "token không hợp lệ"})
                await ws.close(code=4401)
                return
            name, cfg = match
            session = da.AgentSession(name, cfg, ws)
            session.info = hello.get("info") if isinstance(hello.get("info"), dict) else {}
            await da.register(session)
            await ws.send_json({"type": "ready", "device": name,
                                "paths": session.allowed_paths,
                                "can_write": session.can_write})
            # Vòng đọc: mọi frame sau đó là kết quả của một lệnh đã gửi.
            while True:
                msg = await ws.receive_json()
                if isinstance(msg, dict):
                    if msg.get("type") == "pong":
                        continue
                    session.deliver(msg)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning({"event": "device_agent_ws_error", "error": str(exc)[:120]})
        finally:
            if session is not None:
                await da.unregister(session)

    def _agent_ws_url() -> str:
        """URL agent phải trỏ vào — suy từ base_url công khai của dự án.

        UI KHÔNG được tự lấy window.location.origin: trang admin hay được mở
        bằng IP LAN (172.16.10.38:3030), còn agent trên điện thoại/VPS phải đi
        qua domain công khai. Dựng lệnh cài từ origin sẽ ra lệnh chạy được ở
        LAN nhưng chết ngoài Internet.
        """
        c = config.get()
        base = (str(c.get("base_url") or "").strip()
                or str(c.get("telegram_webhook_url") or "").strip()).rstrip("/")
        if not base:
            return ""
        ws = base.replace("https://", "wss://").replace("http://", "ws://")
        return f"{ws}/api/devices/agent"

    @router.get("/api/devices")
    async def devices_list(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"devices": da.list_devices(), "ws_url": _agent_ws_url()}

    @router.post("/api/devices/{name}/rotate")
    async def devices_rotate(name: str,
                             authorization: str | None = Header(default=None)):
        """Sinh token MỚI cho thiết bị đã có, trả về một lần.

        Token cũ chỉ hiện đúng lúc khai báo, nên khi cần lại lệnh cài (đổi máy,
        mất token) thì cách an toàn là XOAY token chứ không phải đọc lại cái cũ
        — cấu hình không nên là nơi tra cứu bí mật. Phiên đang chạy bằng token
        cũ bị ngắt ngay để không còn hai bên cùng dùng.
        """
        require_admin(authorization)
        import secrets

        devs = dict(config.data.get("device_agents") or {})
        cfg = devs.get(name)
        if not isinstance(cfg, dict):
            raise HTTPException(404, f"không có thiết bị '{name}'")
        cfg = dict(cfg)
        cfg["token"] = secrets.token_urlsafe(32)
        devs[name] = cfg
        config.data["device_agents"] = devs
        config._save()
        session = da.get(name)
        if session is not None:
            session.fail_all("token đã được xoay — chạy lại agent với token mới")
            try:
                await session.ws.close(code=4403)
            except Exception:
                pass
        logger.info({"event": "device_token_rotated", "device": name})
        return {"ok": True, "name": name, "token": cfg["token"],
                "paths": cfg.get("paths") or [],
                "can_write": bool(cfg.get("can_write")),
                "ws_url": _agent_ws_url()}

    @router.post("/api/devices")
    async def devices_register(payload: dict,
                               authorization: str | None = Header(default=None)):
        """Khai báo MỘT thiết bị mới, tự sinh token và trả về.

        Có endpoint này để người dùng tự thêm thiết bị bằng một lệnh curl —
        không phải sửa tay cả khối `device_agents` trong config (dễ ghi đè mất
        thiết bị khác) và không cần chờ ai làm hộ.

        Body: {name, label?, paths[], can_write?}
        """
        require_admin(authorization)
        import re
        import secrets

        name = str((payload or {}).get("name") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,30}", name):
            raise HTTPException(400, "name chỉ gồm a-z 0-9 _ - (2–31 ký tự), "
                                     "vd 'laptop-win'")
        paths = [str(p).strip() for p in ((payload or {}).get("paths") or [])
                 if str(p).strip()]
        if not paths:
            # Fail-closed: thiết bị không có thư mục nào thì vô nghĩa, và để
            # rỗng dễ bị hiểu nhầm là "mở tất cả".
            raise HTTPException(400, "phải khai ít nhất một thư mục trong 'paths'")

        devs = dict(config.data.get("device_agents") or {})
        if name in devs:
            raise HTTPException(409, f"thiết bị '{name}' đã tồn tại — "
                                     f"xoá trước (DELETE /api/devices/{name}) rồi thêm lại")
        token = secrets.token_urlsafe(32)
        devs[name] = {
            "label": str((payload or {}).get("label") or name),
            "token": token,
            "paths": paths,
            "can_write": bool((payload or {}).get("can_write", False)),
            "enabled": True,
        }
        config.data["device_agents"] = devs
        config._save()
        logger.info({"event": "device_registered", "device": name,
                     "paths": len(paths), "can_write": devs[name]["can_write"]})
        return {"ok": True, "name": name, "token": token,
                "paths": paths, "can_write": devs[name]["can_write"],
                "ws_url": _agent_ws_url(),
                "note": "Giữ token này — nó không hiện lại ở đâu khác."}

    @router.delete("/api/devices/{name}")
    async def devices_remove(name: str,
                             authorization: str | None = Header(default=None)):
        """Xoá thiết bị (token hết hiệu lực ngay, ngắt cả phiên đang kết nối)."""
        require_admin(authorization)
        devs = dict(config.data.get("device_agents") or {})
        if name not in devs:
            raise HTTPException(404, f"không có thiết bị '{name}'")
        devs.pop(name, None)
        config.data["device_agents"] = devs
        config._save()
        # Phiên đang mở phải bị ngắt — nếu không, token đã xoá vẫn dùng được
        # tới khi thiết bị tự rớt mạng.
        session = da.get(name)
        if session is not None:
            session.fail_all("thiết bị đã bị xoá khỏi cấu hình")
            try:
                await session.ws.close(code=4403)
            except Exception:
                pass
        logger.info({"event": "device_removed", "device": name})
        return {"ok": True, "name": name}

    @router.post("/api/devices/{name}/op")
    async def devices_op(name: str, payload: dict,
                         authorization: str | None = Header(default=None)):
        """Chạy MỘT thao tác file trên thiết bị. MCP hub gọi route này."""
        require_admin(authorization)
        op = str((payload or {}).get("op") or "").strip()
        args = (payload or {}).get("args") or {}
        if not isinstance(args, dict):
            args = {}
        if op not in (_READ_OPS | _WRITE_OPS):
            raise HTTPException(400, f"thao tác không hỗ trợ: {op}")

        session = da.get(name)
        if session is None:
            return {"ok": False, "error": f"thiết bị '{name}' chưa kết nối"}
        if op in _WRITE_OPS and not session.can_write:
            return {"ok": False,
                    "error": f"thiết bị '{name}' chỉ được cấp quyền ĐỌC (can_write=false)"}

        # Kiểm allowlist NGAY Ở GATEWAY, trước khi gửi xuống thiết bị. Agent
        # cũng tự kiểm lại — hai lớp cố ý trùng nhau.
        for key in ("path", "src", "dst"):
            p = args.get(key)
            if p and not da.path_allowed(session, str(p)):
                return {"ok": False,
                        "error": (f"'{p}' ngoài phạm vi cho phép của thiết bị. "
                                  f"Được phép: {', '.join(session.allowed_paths) or '(chưa khai báo)'}")}
        res = await session.call(op, args)
        if not res.get("ok"):
            logger.info({"event": "device_op_failed", "device": name, "op": op,
                         "error": str(res.get("error"))[:120]})
        return res

    return router
