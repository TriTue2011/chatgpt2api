"""API «mắt của nhà» — Cài đặt → Home Assistant → tab 🧑 Khuôn mặt.

Cấu hình (`nhin_nha`) lưu qua đường lưu config chung như mọi thẻ khác. Ở đây
chỉ có những việc web không tự làm được: đọc trạng thái model/luồng canh, và
quản sổ khuôn mặt (người, ảnh mặt, mặt lạ, sự kiện).

Ảnh mặt là dữ liệu sinh trắc — mọi đường đều ``require_admin``, ảnh trả về dưới
dạng data URL thu nhỏ chứ không mở một đường tĩnh công khai nào cho kho mặt.

``GET  /api/nhin-nha/trang-thai``            model đã tải + số liệu luồng canh
``GET  /api/nhin-nha/nguoi``                 người đã dạy (kèm ảnh nhỏ)
``POST /api/nhin-nha/day``                   dạy mặt: form ``ten`` + ``anh`` (+ ``ep``)
``POST /api/nhin-nha/nguoi/{id}/doi-ten``    ``{"ten": "..."}``
``DELETE /api/nhin-nha/nguoi/{id}``
``GET  /api/nhin-nha/mat-la``                mặt lạ đang theo dõi
``POST /api/nhin-nha/mat-la/{id}/dat-ten``   ``{"ten": "..."}``
``POST /api/nhin-nha/mat-la/{id}/thoi-hoi``
``GET  /api/nhin-nha/su-kien?so_gio=24``
"""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from api.support import require_admin

logger = logging.getLogger(__name__)

#: Ảnh tải lên để dạy mặt — ảnh điện thoại nguyên gốc hiếm khi quá 12 MB.
_TOI_DA_BYTE = 15_000_000
_CANH_NHO = 160


def _anh_nho(rel: str) -> str:
    """Ảnh mặt đã lưu → data URL JPEG cạnh dài ≤ 160 px. Mất ảnh thì chuỗi rỗng."""
    import cv2
    import numpy as np

    from services import so_mat_nha

    p = so_mat_nha.duong_anh(rel)
    if p is None:
        return ""
    anh = cv2.imdecode(np.frombuffer(p.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if anh is None:
        return ""
    cao, rong = anh.shape[:2]
    ti_le = _CANH_NHO / max(cao, rong)
    if ti_le < 1:
        anh = cv2.resize(anh, (max(1, int(rong * ti_le)), max(1, int(cao * ti_le))),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", anh, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/nhin-nha/trang-thai")
    async def trang_thai(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import canh_camera_nha, nhin_nha, so_mat_nha

        from services import yolo_nha

        tt = canh_camera_nha.trang_thai()
        # Danh sách nhãn để web dựng ô tích. Lấy từ bảng tên tiếng Việt chứ
        # không bắt web tự chép: chép là sớm muộn lệch nhau.
        nhan = [{"ma": ma, "ten": ten} for ma, ten in yolo_nha.TEN_VIET.items()]
        return {"ok": True, "model": {**nhin_nha.trang_thai(), "nhan": nhan},
                "canh": {k: v for k, v in tt.items() if k != "cau_hinh"},
                "so_nguoi": len(so_mat_nha.danh_sach_nguoi()),
                "so_mat_la": len(so_mat_nha.danh_sach_mat_la())}

    @router.get("/api/nhin-nha/nguoi")
    async def nguoi(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        def _doc():
            ds = so_mat_nha.danh_sach_nguoi()
            for n in ds:
                n["anh"] = _anh_nho(n["anh"])
            return ds
        return {"ok": True, "nguoi": await run_in_threadpool(_doc)}

    @router.post("/api/nhin-nha/day")
    async def day(ten: str = Form(...), anh: UploadFile = File(...), ep: bool = Form(False),
                  authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import nhin_nha, so_mat_nha

        du_lieu = await anh.read(_TOI_DA_BYTE + 1)
        if len(du_lieu) > _TOI_DA_BYTE:
            raise HTTPException(413, "Ảnh lớn quá (tối đa 15 MB).")
        try:
            from services import photo_intent
            du_lieu, loi = photo_intent.prepare_incoming(du_lieu)   # HEIC/AVIF → JPEG
            if not du_lieu:
                return {"ok": False, "error": loi}
            kq = await run_in_threadpool(so_mat_nha.day, ten, du_lieu, nguon="web", ep=ep)
        except (so_mat_nha.LoiSoMat, nhin_nha.ChuaCoModel) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **kq}

    @router.post("/api/nhin-nha/nguoi/{nguoi_id}/doi-ten")
    async def doi_ten(nguoi_id: str, body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        try:
            ok = so_mat_nha.doi_ten(nguoi_id, str(body.get("ten") or ""))
        except so_mat_nha.LoiSoMat as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": ok}

    @router.delete("/api/nhin-nha/nguoi/{nguoi_id}")
    async def xoa_nguoi(nguoi_id: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        return {"ok": await run_in_threadpool(so_mat_nha.xoa_nguoi, nguoi_id)}

    @router.get("/api/nhin-nha/mat-la")
    async def mat_la(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        def _doc():
            ds = so_mat_nha.danh_sach_mat_la()
            for x in ds:
                x["anh"] = _anh_nho(x["anh"])
            return ds
        return {"ok": True, "mat_la": await run_in_threadpool(_doc)}

    @router.post("/api/nhin-nha/mat-la/{ma}/dat-ten")
    async def dat_ten_mat_la(ma: str, body: dict, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import nhin_nha, so_mat_nha

        try:
            kq = await run_in_threadpool(so_mat_nha.dat_ten_mat_la, ma, str(body.get("ten") or ""))
        except (so_mat_nha.LoiSoMat, nhin_nha.ChuaCoModel) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **kq}

    @router.post("/api/nhin-nha/mat-la/{ma}/thoi-hoi")
    async def thoi_hoi(ma: str, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        return {"ok": so_mat_nha.thoi_hoi_mat_la(ma)}

    @router.get("/api/nhin-nha/su-kien")
    async def su_kien(so_gio: float = 24, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        from services import so_mat_nha

        so_gio = max(0.5, min(24 * 30, float(so_gio)))
        return {"ok": True, "su_kien": so_mat_nha.su_kien_gan(so_gio, gioi_han=100)}

    return router
