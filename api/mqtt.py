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

    @router.get("/api/mqtt/canh-bao")
    async def canh_bao(authorization: str | None = Header(default=None)):
        """Trạng thái cảnh báo + danh sách lỗi đang theo dõi."""
        require_admin(authorization)

        from services import canh_bao_nha

        try:
            return {"ok": True, "trang_thai": canh_bao_nha.trang_thai(),
                    "danh_sach": canh_bao_nha.danh_sach()}
        except Exception as exc:
            logger.warning("mqtt cảnh báo lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    @router.post("/api/mqtt/canh-bao/im")
    async def canh_bao_im(body: dict, authorization: str | None = Header(default=None)):
        """Tắt / bật lại nhắc cho một thiết bị (hoặc tất cả nếu bỏ trống tên)."""
        require_admin(authorization)

        from services import canh_bao_nha

        ten = str(body.get("thiet_bi") or "").strip()
        try:
            if body.get("bat_lai"):
                return {"ok": True, **canh_bao_nha.bo_im(ten)}
            if not ten:
                return {"ok": False, "error": "Chưa chọn thiết bị nào."}
            return {"ok": True, **canh_bao_nha.im_di(
                ten, str(body.get("truong") or ""), str(body.get("loai") or ""))}
        except Exception as exc:
            logger.warning("mqtt im cảnh báo lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    @router.post("/api/tuya/test")
    async def tuya_test(body: dict, authorization: str | None = Header(default=None)):
        """Thử Access ID/Secret. KHÔNG ghi bí mật ra log."""
        require_admin(authorization)

        from services import tuya_nha
        from services.config import config

        cu = config.data.get("tuya")
        try:
            # Thử với thông tin người dùng vừa nhập mà CHƯA lưu — nhập sai thì
            # không làm hỏng cấu hình đang chạy.
            tam = dict(cu or {})
            for k in ("access_id", "access_secret", "endpoint"):
                v = str(body.get(k) or "").strip()
                if v and v != "***":
                    tam[k] = v
            config.data["tuya"] = tam
            tuya_nha._reset_for_tests()
            return await asyncio.to_thread(tuya_nha.thu_ket_noi)
        except Exception as exc:
            logger.warning("tuya test lỗi: %s", str(exc)[:120])
            return {"ok": False, "error": str(exc)[:200]}
        finally:
            if cu is None:
                config.data.pop("tuya", None)
            else:
                config.data["tuya"] = cu
            tuya_nha._reset_for_tests()

    @router.get("/api/tuya/thiet-bi")
    async def tuya_thiet_bi(authorization: str | None = Header(default=None)):
        """Thiết bị Tuya kèm trạng thái."""
        require_admin(authorization)

        from services import tuya_nha

        try:
            ds = await asyncio.to_thread(tuya_nha.danh_sach_thiet_bi)
            return {"ok": True, "thiet_bi": ds, "trang_thai": tuya_nha.stats()}
        except tuya_nha.LoiTuya as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("tuya danh sách lỗi: %s", str(exc)[:120])
            return {"ok": False, "error": str(exc)[:200]}

    @router.get("/api/mqtt/tinh-huong")
    async def tinh_huong(authorization: str | None = Header(default=None)):
        """Tình huống bot học được, kèm trạng thái duyệt."""
        require_admin(authorization)

        from services import tinh_huong_nha as th

        try:
            return {"ok": True, "danh_sach": th.danh_sach(),
                    "thong_ke": th.thong_ke()}
        except Exception as exc:
            logger.warning("mqtt tình huống lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    @router.get("/api/mqtt/du-doan")
    async def du_doan(authorization: str | None = Header(default=None)):
        """Bot đang nghĩ gì, và nó đã đoán đúng bao nhiêu lần.

        Trả cả `dang_nghi` (gợi ý lúc này) lẫn `thong_ke` (thành tích từng
        thiết bị, còn thiếu bao nhiêu lượt nữa mới được tự làm).
        """
        require_admin(authorization)

        from services import du_doan_nha as dn

        try:
            return {"ok": True, "dang_nghi": dn.quet(),
                    "thong_ke": dn.thong_ke()}
        except Exception as exc:
            logger.warning("mqtt dự đoán lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    @router.post("/api/mqtt/du-doan/cham")
    async def du_doan_cham(body: dict,
                           authorization: str | None = Header(default=None)):
        """Chấm một lần đoán: đúng hay sai.

        Đây là đường bot lên cấp: đủ 50 lượt được chấm mà đúng ≥95% thì thiết
        bị đó tự làm được, không cần ai bật tay.
        """
        require_admin(authorization)

        from services import du_doan_nha as dn

        try:
            i = int(body.get("id") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Thiếu id."}
        if not i:
            return {"ok": False, "error": "Thiếu id."}
        try:
            ok = (dn.ghi_dung(i) if body.get("dung") else dn.ghi_sai(i))
            if not ok:
                return {"ok": False, "error": "Lần đoán này đã chấm rồi."}
            return {"ok": True, "giai_thich": dn.giai_thich(i)}
        except Exception as exc:
            logger.warning("mqtt chấm dự đoán lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    @router.post("/api/mqtt/tinh-huong/duyet")
    async def tinh_huong_duyet(body: dict,
                               authorization: str | None = Header(default=None)):
        """Duyệt / đổi tên / bỏ một tình huống."""
        require_admin(authorization)

        from services import tinh_huong_nha as th

        try:
            i = int(body.get("id") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Thiếu id."}
        if not i:
            return {"ok": False, "error": "Thiếu id."}
        try:
            if body.get("bo"):
                return {"ok": th.bo(i)}
            return {"ok": th.duyet(i, str(body.get("ten") or ""))}
        except Exception as exc:
            logger.warning("mqtt duyệt tình huống lỗi: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    return router
