"""Endpoint quản trị cho rclone — trang Cài đặt gọi vào đây.

MỌI route ở đây đòi quyền quản trị: file cấu hình rclone chứa token thật của
Google Drive / OneDrive / S3, ai gọi được là đọc ghi được toàn bộ kho lưu trữ
của chủ máy. Bot KHÔNG đi qua đường này — bot dùng các capability trong
`services/agent/capabilities.py`, vốn bị khoá trong thư mục làm việc.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException

from api.support import require_admin
from services import rclone_service as rc


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/rclone", tags=["rclone"])

    @router.get("/status")
    def trang_thai(authorization: str | None = Header(None)) -> dict[str, Any]:
        require_admin(authorization)
        kq = rc.san_sang()
        kq["thu_muc_lam_viec"] = str(rc.workspace_dir())
        return kq

    @router.get("/config")
    def doc_config(authorization: str | None = Header(None)) -> dict[str, Any]:
        """Cấu hình ĐÃ CHE — token thật không bao giờ rời máy chủ."""
        require_admin(authorization)
        return {"ok": True, "noi_dung": rc.config_da_che()}

    @router.put("/config")
    def ghi_config(payload: dict[str, Any],
                   authorization: str | None = Header(None)) -> dict[str, Any]:
        require_admin(authorization)
        kq = rc.dat_config(str(payload.get("noi_dung") or ""))
        if not kq.get("ok"):
            raise HTTPException(status_code=400, detail={"error": kq.get("error")})
        return kq

    @router.post("/remotes")
    def them_remote(payload: dict[str, Any],
                    authorization: str | None = Header(None)) -> dict[str, Any]:
        require_admin(authorization)
        kq = rc.tao_remote(str(payload.get("ten") or ""),
                           str(payload.get("loai") or ""),
                           dict(payload.get("tham_so") or {}))
        if not kq.get("ok"):
            raise HTTPException(status_code=400, detail={"error": kq.get("error")})
        return kq

    @router.delete("/remotes/{ten}")
    def bo_remote(ten: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        require_admin(authorization)
        kq = rc.xoa_remote(ten)
        if not kq.get("ok"):
            raise HTTPException(status_code=400, detail={"error": kq.get("error")})
        return kq

    @router.post("/remotes/{ten}/test")
    def thu_remote(ten: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        require_admin(authorization)
        return rc.kiem_tra(ten)

    @router.get("/ls")
    def liet_ke(duong_dan: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        require_admin(authorization)
        kq = rc.liet_ke(duong_dan)
        if not kq.get("ok"):
            raise HTTPException(status_code=400, detail={"error": kq.get("error")})
        return kq

    @router.post("/tai-ve")
    def tai_ve(payload: dict[str, Any],
               authorization: str | None = Header(None)) -> dict[str, Any]:
        require_admin(authorization)
        kq = rc.tai_ve(str(payload.get("duong_dan") or ""),
                       ten_luu=str(payload.get("ten_luu") or ""))
        if not kq.get("ok"):
            raise HTTPException(status_code=400, detail={"error": kq.get("error")})
        return kq

    @router.post("/gui-len")
    def gui_len(payload: dict[str, Any],
                authorization: str | None = Header(None)) -> dict[str, Any]:
        require_admin(authorization)
        kq = rc.gui_len(str(payload.get("tep") or ""),
                        str(payload.get("thu_muc") or ""))
        if not kq.get("ok"):
            raise HTTPException(status_code=400, detail={"error": kq.get("error")})
        return kq

    return router
