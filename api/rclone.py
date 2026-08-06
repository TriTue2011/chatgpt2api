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

    @router.post("/drive/start")
    def drive_start(payload: dict[str, Any],
                    authorization: str | None = Header(None)) -> dict[str, Any]:
        """Dựng đường dẫn cấp quyền Google Drive để người dùng bấm vào."""
        require_admin(authorization)
        kq = rc.drive_duong_dan_dang_nhap(str(payload.get("client_id") or ""),
                                          str(payload.get("scope") or "drive"))
        if not kq.get("ok"):
            raise HTTPException(status_code=400, detail={"error": kq.get("error")})
        return kq

    @router.post("/drive/exchange")
    def drive_exchange(payload: dict[str, Any],
                       authorization: str | None = Header(None)) -> dict[str, Any]:
        """Đổi mã cấp quyền lấy token rồi khai luôn kho Drive."""
        require_admin(authorization)
        kq = rc.drive_doi_ma_lay_token(
            str(payload.get("ten") or ""),
            str(payload.get("client_id") or ""),
            str(payload.get("client_secret") or ""),
            str(payload.get("redirect_url") or ""),
            scope=str(payload.get("scope") or "drive"),
            root_folder_id=str(payload.get("root_folder_id") or ""),
        )
        if not kq.get("ok"):
            raise HTTPException(status_code=400, detail={"error": kq.get("error")})
        return kq

    @router.post("/khoa-json")
    def luu_khoa_json(payload: dict[str, Any],
                      authorization: str | None = Header(None)) -> dict[str, Any]:
        """Nhận tệp khoá JSON tài khoản dịch vụ từ giao diện, trả đường dẫn đã lưu."""
        require_admin(authorization)
        kq = rc.luu_khoa_json(str(payload.get("ten") or ""),
                              str(payload.get("noi_dung") or ""))
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

    @router.get("/kho-doc-duoc")
    def kho_doc_duoc(authorization: str | None = Header(None)) -> dict[str, Any]:
        """Mỗi phạm vi đã bật «Lưu trữ online» đọc được những kho nào.

        Tính ở phía máy chủ chứ không để giao diện tự suy từ `memory_links`: hai
        nơi cùng quyết định quyền đọc là hai nơi sẽ lệch nhau, và lệch về quyền
        đọc thì hiển thị nói một đằng, bot làm một nẻo.
        """
        require_admin(authorization)
        from services.agent import luu_tru_online as lt
        return {"ok": True, "ban_do": lt.ban_do_doc_duoc()}

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
