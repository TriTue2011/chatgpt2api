"""Endpoint cho device agent: WebSocket để agent quay ra, REST để MCP gọi vào.

Agent (máy/điện thoại/VPS) mở WS tới `/api/devices/agent` — chiều ĐẢO nên
thiết bị sau NAT vẫn tới được. MCP `device_fs` trên hub gọi các route REST
`/api/devices/*` qua localhost để đọc/sửa file trên đúng thiết bị đó.
"""
from __future__ import annotations

from typing import Any

from fastapi import (APIRouter, Header, HTTPException, Query, WebSocket,
                     WebSocketDisconnect)

from api.support import require_admin
from services import device_agents as da
from services.config import config
from utils.log import logger

_READ_OPS = {"ls", "read", "stat", "find"}
_WRITE_OPS = {"write", "mkdir", "delete", "append"}
# Tra cứu hệ thống: agent chỉ chạy các lệnh CỐ ĐỊNH do chính nó chọn (tasklist,
# ps, systemctl list-units…), mô hình không chèn được chữ nào vào đó và tất cả
# đều chỉ đọc. Vì vậy không đòi quyền riêng — nếu đòi thì muốn xem RAM cũng phải
# mở luôn quyền chạy lệnh tuỳ ý, tức đánh đổi ngược.
_INFO_OPS = {"sysinfo", "resources", "processes", "services", "screen"}
# Chạy lệnh tuỳ ý + tắt tiến trình.
_EXEC_OPS = {"exec", "kill"}
# Khoá / ngủ / đăng xuất / tắt / khởi động lại + mở khoá màn hình.
# `unlock` xếp cùng nhóm `power` vì cùng một loại quyền: đổi trạng thái phiên
# đăng nhập của người đang dùng máy. Ai mở được quyền khoá máy thì cũng là người
# quyết định được việc mở khoá.
_POWER_OPS = {"power", "unlock"}
# Chụp webcam + ảnh màn hình. Nhóm RIÊNG, không gộp vào _INFO_OPS dù cũng "chỉ
# đọc": đây là nhóm duy nhất nhìn thấy NGƯỜI (mặt ai đang ngồi trước máy) và
# NỘI DUNG ĐANG LÀM (mật khẩu hiện trên màn, tin nhắn riêng). Đọc file còn bị
# allowlist thư mục chặn; ảnh màn hình thì không allowlist nào che được. Nên
# phải là quyền bật tường minh, ngang cấp can_power.
_CAPTURE_OPS = {"webcam", "screenshot"}
# Agent tự gỡ mình khỏi máy. KHÔNG nằm trong _ALL_OPS: đây không phải thao tác
# người dùng gọi được qua /op hay qua bot, mà chỉ đường xoá thiết bị dùng — cho
# vào _ALL_OPS là mở cho mô hình một cách "xoá agent của người ta" bằng lời.
# Cũng KHÔNG đòi can_exec: thiết bị chỉ-đọc phải gỡ được, đúng lúc muốn dứt
# điểm nhất; và mọi thứ nó xoá đều là của chính agent.
_SELF_OPS = {"uninstall"}
_ALL_OPS = _READ_OPS | _WRITE_OPS | _INFO_OPS | _EXEC_OPS | _POWER_OPS | _CAPTURE_OPS


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
            tok_offered = str(hello.get("token") or "")
            match = da.resolve_token(tok_offered)
            if match is None:
                # Không nói rõ vì sao TRONG PHẢN HỒI — token sai thì đừng giúp bên
                # kia dò. Nhưng LOG phải đủ để phân biệt ba ca khác hẳn nhau mà
                # bản cũ gộp thành một dòng trống rỗng: token CŨ (đã xoay), token
                # RỖNG/quá ngắn, và thiết bị bị tắt. Không có gì để so thì chỉ
                # còn cách đoán.
                #
                # Ghi DẤU VÂN (sha256 rút gọn), không ghi token: đủ để đối chiếu
                # với dấu vân đang lưu, không đủ để dùng lại.
                import hashlib
                logger.warning({
                    "event": "device_agent_auth_failed",
                    "do_dai": len(tok_offered),
                    "dau_van": (hashlib.sha256(tok_offered.encode()).hexdigest()[:12]
                                if tok_offered else ""),
                    "ly_do": ("rỗng" if not tok_offered
                              else "quá ngắn" if len(tok_offered) < 16
                              else "không khớp thiết bị nào"),
                })
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
                "can_exec": bool(cfg.get("can_exec")),
                "can_power": bool(cfg.get("can_power")),
                "can_capture": bool(cfg.get("can_capture")),
                "ws_url": _agent_ws_url()}

    @router.post("/api/devices")
    async def devices_register(payload: dict,
                               authorization: str | None = Header(default=None)):
        """Khai báo MỘT thiết bị mới, tự sinh token và trả về.

        Có endpoint này để người dùng tự thêm thiết bị bằng một lệnh curl —
        không phải sửa tay cả khối `device_agents` trong config (dễ ghi đè mất
        thiết bị khác) và không cần chờ ai làm hộ.

        Body: {name, label?, paths[], can_write?, can_exec?, can_power?, can_capture?}
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
            "can_exec": bool((payload or {}).get("can_exec", False)),
            "can_power": bool((payload or {}).get("can_power", False)),
            "can_capture": bool((payload or {}).get("can_capture", False)),
            "enabled": True,
        }
        config.data["device_agents"] = devs
        config._save()
        logger.info({"event": "device_registered", "device": name,
                     "paths": len(paths), "can_write": devs[name]["can_write"],
                     "can_exec": devs[name]["can_exec"],
                     "can_power": devs[name]["can_power"],
                     "can_capture": devs[name]["can_capture"]})
        return {"ok": True, "name": name, "token": token,
                "paths": paths, "can_write": devs[name]["can_write"],
                "can_exec": devs[name]["can_exec"],
                "can_power": devs[name]["can_power"],
                "can_capture": devs[name]["can_capture"],
                "ws_url": _agent_ws_url(),
                "note": "Giữ token này — nó không hiện lại ở đâu khác."}

    @router.patch("/api/devices/{name}")
    async def devices_update(name: str, payload: dict,
                             authorization: str | None = Header(default=None)):
        """Sửa quyền / nhãn / thư mục của thiết bị ĐÃ CÓ, giữ nguyên token.

        Không dùng đường xoá-rồi-thêm-lại cho việc này: xoá là mất token, phải
        chạy lại agent trên máy đó — quá đắt chỉ để tích thêm một ô quyền.

        Body: {label?, paths?, can_write?, can_exec?, can_power?, can_capture?}
        """
        require_admin(authorization)
        devs = dict(config.data.get("device_agents") or {})
        cfg = devs.get(name)
        if not isinstance(cfg, dict):
            raise HTTPException(404, f"không có thiết bị '{name}'")
        cfg = dict(cfg)
        body = payload or {}

        if "label" in body:
            cfg["label"] = str(body.get("label") or name)
        if "paths" in body:
            paths = [str(p).strip() for p in (body.get("paths") or []) if str(p).strip()]
            if not paths:
                raise HTTPException(400, "phải khai ít nhất một thư mục trong 'paths'")
            cfg["paths"] = paths
        for key in ("can_write", "can_exec", "can_power", "can_capture"):
            if key in body:
                cfg[key] = bool(body.get(key))

        devs[name] = cfg
        config.data["device_agents"] = devs
        config._save()
        # Phiên đang mở đọc quyền từ cfg cũ — trỏ lại để đổi có hiệu lực ngay,
        # không phải chờ thiết bị nối lại.
        session = da.get(name)
        if session is not None:
            session.cfg = cfg
        logger.info({"event": "device_updated", "device": name,
                     "can_write": bool(cfg.get("can_write")),
                     "can_exec": bool(cfg.get("can_exec")),
                     "can_power": bool(cfg.get("can_power")),
                     "can_capture": bool(cfg.get("can_capture"))})
        return {"ok": True, "name": name, "paths": cfg.get("paths") or [],
                "can_write": bool(cfg.get("can_write")),
                "can_exec": bool(cfg.get("can_exec")),
                "can_power": bool(cfg.get("can_power")),
                "can_capture": bool(cfg.get("can_capture")),
                "note": ("Đổi quyền ở dự án là chưa đủ — agent trên máy đó cũng "
                         "phải chạy kèm cờ tương ứng (--allow-exec / --allow-power "
                         "/ --allow-capture). Thiếu một trong hai phía là vẫn bị chặn.")}

    @router.delete("/api/devices/{name}")
    async def devices_remove(name: str,
                             uninstall: bool = Query(default=True),
                             authorization: str | None = Header(default=None)):
        """Xoá thiết bị: GỠ TRÊN MÁY TRƯỚC, rồi mới xoá ở dự án.

        Thứ tự này là bắt buộc, không phải cho gọn. Xoá ở dự án trước thì token
        chết ngay, phiên bị đóng — lúc đó không còn đường nào ra lệnh gỡ nữa, mà
        trên máy người dùng vẫn còn lịch tự chạy: agent cứ bật lại mỗi lần mở
        máy, gõ cửa gateway bằng token đã chết, mãi mãi. Người dùng "đã xoá
        thiết bị" nhưng phải tự đi tìm Task Scheduler mà tắt.

        `uninstall=false` để chỉ xoá ở dự án (máy kia đã hỏng, đã bán, đã cài
        lại Windows — không có gì để gỡ).
        """
        require_admin(authorization)
        devs = dict(config.data.get("device_agents") or {})
        if name not in devs:
            raise HTTPException(404, f"không có thiết bị '{name}'")

        # Bước 1 — nhờ chính agent tự gỡ, KHI NÓ CÒN ONLINE.
        go_may: dict[str, Any] = {"da_thu": False}
        session = da.get(name)
        if uninstall and session is not None:
            go_may["da_thu"] = True
            try:
                res = await session.call("uninstall", {})
                go_may.update({"ok": bool((res or {}).get("ok")),
                               "steps": (res or {}).get("steps") or [],
                               "errors": (res or {}).get("errors") or []})
                logger.info({"event": "device_uninstalled", "device": name,
                             "ok": go_may.get("ok")})
            except Exception as exc:
                # Gỡ hỏng thì VẪN xoá ở dự án — token phải chết cho bằng được,
                # đó là lớp bảo vệ thật. Nhưng nói rõ máy kia còn sót gì.
                go_may.update({"ok": False, "errors": [str(exc)[:160]]})
                logger.warning({"event": "device_uninstall_failed", "device": name,
                                "error": str(exc)[:160]})
        elif uninstall:
            go_may["ghi_chu"] = (
                "thiết bị đang offline nên không gỡ được từ xa — nếu máy đó còn "
                "dùng, chạy trên máy:  & \"$env:TEMP\\c2a-install.ps1\" -Uninstall")

        # Bước 2 — xoá ở dự án.
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
        # Trả kèm kết quả gỡ để UI nói được sự thật: "đã gỡ sạch" khác hẳn "đã
        # xoá ở dự án nhưng máy kia còn lịch tự chạy, tự đi tắt hộ".
        return {"ok": True, "name": name, "go_tren_may": go_may}

    @router.post("/api/devices/{name}/op")
    async def devices_op(name: str, payload: dict,
                         authorization: str | None = Header(default=None)):
        """Chạy MỘT thao tác file trên thiết bị. MCP hub gọi route này."""
        require_admin(authorization)
        op = str((payload or {}).get("op") or "").strip()
        args = (payload or {}).get("args") or {}
        if not isinstance(args, dict):
            args = {}
        if op not in _ALL_OPS:
            raise HTTPException(400, f"thao tác không hỗ trợ: {op}")

        session = da.get(name)
        if session is None:
            return {"ok": False, "error": f"thiết bị '{name}' chưa kết nối"}
        if op in _WRITE_OPS and not session.can_write:
            return {"ok": False,
                    "error": f"thiết bị '{name}' chỉ được cấp quyền ĐỌC (can_write=false)"}
        if op in _EXEC_OPS and not session.can_exec:
            return {"ok": False,
                    "error": (f"thiết bị '{name}' KHÔNG được cấp quyền chạy lệnh "
                              f"(can_exec=false). Bật ở MCP → Thiết bị của tôi, "
                              f"rồi chạy lại agent kèm --allow-exec.")}
        if op in _POWER_OPS and not session.can_power:
            return {"ok": False,
                    "error": (f"thiết bị '{name}' KHÔNG được cấp quyền tắt/khoá máy "
                              f"(can_power=false). Bật ở MCP → Thiết bị của tôi, "
                              f"rồi chạy lại agent kèm --allow-power.")}
        if op in _CAPTURE_OPS and not session.can_capture:
            return {"ok": False,
                    "error": (f"thiết bị '{name}' KHÔNG được cấp quyền chụp webcam/"
                              f"màn hình (can_capture=false). Bật ở MCP → Thiết bị "
                              f"của tôi, rồi chạy lại agent kèm --allow-capture.")}

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
