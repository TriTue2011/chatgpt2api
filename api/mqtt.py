"""API cho MQTT nhà — tab Cài đặt → Home Assistant.

Cấu hình máy chủ nằm trong ``config`` (khoá ``mqtt``) nên web lưu nó qua đúng
đường lưu cấu hình chung như mọi card khác. Ở đây chỉ có những việc web KHÔNG tự
làm được vì phải mở kết nối MQTT thật:

``POST /api/mqtt/test``         thử nối tới một máy chủ (chưa cần lưu)
``POST /api/mqtt/quet``         quét lại, tìm thiết bị
``GET  /api/mqtt/thiet-bi``     danh sách thiết bị đã tìm thấy
``POST /api/mqtt/dieu-khien``   gửi một lệnh tới thiết bị
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Header

from api.support import require_admin

logger = logging.getLogger(__name__)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/mqtt/test")
    async def test(body: dict, authorization: str | None = Header(default=None)):
        """Thử nối tới một máy chủ MQTT. Nghe 5 giây để đếm nhánh.

        Nhận tham số rời chứ không đọc config, để người dùng thử được TRƯỚC khi
        lưu — khai sai địa chỉ mà phải lưu mới biết thì mất luôn cấu hình cũ.
        """
        require_admin(authorization)

        from services import mqtt_nha

        try:
            return await asyncio.to_thread(
                mqtt_nha.thu_ket_noi,
                str(body.get("host") or "").strip(),
                int(body.get("port") or 1883),
                str(body.get("username") or ""),
                str(body.get("password") or ""),
            )
        except (TypeError, ValueError):
            return {"ok": False, "error": "Cổng phải là một con số."}
        except Exception as exc:
            logger.warning("mqtt test lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    @router.post("/api/mqtt/quet")
    async def quet(body: dict, authorization: str | None = Header(default=None)):
        """Quét máy chủ đã lưu để tìm thiết bị."""
        require_admin(authorization)

        from services import mqtt_nha

        try:
            kq = await asyncio.to_thread(mqtt_nha.lam_moi, float(body.get("giay") or 20))
            return {"ok": True, **kq}
        except mqtt_nha.LoiMqtt as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("mqtt quét lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    @router.get("/api/mqtt/thiet-bi")
    async def thiet_bi(authorization: str | None = Header(default=None)):
        """Thiết bị đã tìm thấy. Đọc từ bộ nhớ, không mở kết nối mới."""
        require_admin(authorization)

        from services import mqtt_nha

        try:
            return {"ok": True, "thiet_bi": mqtt_nha.danh_sach_thiet_bi(),
                    "trang_thai": mqtt_nha.stats()}
        except Exception as exc:
            logger.warning("mqtt danh sách lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    @router.post("/api/mqtt/dieu-khien")
    async def dieu_khien(body: dict, authorization: str | None = Header(default=None)):
        """Gửi một lệnh tới thiết bị."""
        require_admin(authorization)

        from services import mqtt_nha

        ten = str(body.get("ten") or "").strip()
        thuc_the = str(body.get("thuc_the") or "").strip()
        if not ten:
            return {"ok": False, "error": "Chưa chọn thiết bị nào."}
        try:
            await asyncio.to_thread(mqtt_nha.dieu_khien, ten, thuc_the,
                                    body.get("gia_tri"))
            return {"ok": True}
        except mqtt_nha.LoiMqtt as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("mqtt điều khiển lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    @router.get("/api/mqtt/lich-su")
    async def lich_su(authorization: str | None = Header(default=None)):
        """Thống kê tầng ghi lịch sử — số bản ghi, dung lượng thật trên đĩa."""
        require_admin(authorization)

        from services import lich_su_nha

        try:
            return {"ok": True, "thong_ke": lich_su_nha.thong_ke()}
        except Exception as exc:
            logger.warning("mqtt lịch sử lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    @router.post("/api/mqtt/nap-ha")
    async def nap_ha(body: dict, authorization: str | None = Header(default=None)):
        """Nạp lịch sử Home Assistant sẵn có (HA chỉ giữ ~10 ngày rồi trôi mất).

        Chạy lại nhiều lần được: UNIQUE(thiet_bi, truong, ts) chặn ghi trùng.
        """
        require_admin(authorization)

        from services import lich_su_nha

        try:
            so_ngay = int(body.get("so_ngay") or 10)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Số ngày phải là một con số."}
        try:
            kq = await asyncio.to_thread(lich_su_nha.nap_tu_ha, so_ngay)
            return {"ok": True, **kq}
        except Exception as exc:
            logger.warning("mqtt nạp HA lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    @router.get("/api/mqtt/soi-hong")
    async def soi_hong(so_ngay: int = 7,
                       authorization: str | None = Header(default=None)):
        """Cảm biến chết / đơ / chập chờn.

        Đo trên HA thật 09/09/2026: 24 chết hẳn, 63 đơ, 69 chập chờn trên 500
        cảm biến. Cảm biến đơ nguy hiểm hơn chết hẳn vì nhìn vào tưởng còn chạy.
        """
        require_admin(authorization)

        from services import lich_su_nha

        try:
            ds = await asyncio.to_thread(lich_su_nha.soi_hong, so_ngay)
            return {"ok": True, "hong": ds, "so_luong": len(ds)}
        except Exception as exc:
            logger.warning("mqtt soi hỏng lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    return router
