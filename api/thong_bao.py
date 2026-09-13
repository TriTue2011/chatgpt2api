"""API cho trang Cài đặt → Thông báo: một nơi bật/tắt và chọn kênh cho TỪNG tin.

Chủ máy chốt 13/09/2026: gom mọi cài đặt thông báo về một chỗ, mỗi thông báo cài
riêng, *"toàn bộ các thông báo theo cài đặt webui, không mặc định"*, và *"cài
đặt thông báo ở tab cũ xóa đi tránh xung đột"*.

Bám khuôn ``api/hoc_hoi.py``: mỗi endpoint ``require_admin``, và mọi thao tác
GHI đi qua endpoint HẸP. Đây không phải chi tiết phong cách — thẻ Cài đặt cũ
POST NGUYÊN cả khối config (``store.saveConfig`` → ``POST /api/settings``), nên
thẻ nào nạp dữ liệu cũ sẽ ghi đè phần của thẻ khác. Chuyện đó ĐÃ xảy ra và được
ghi lại thành bẫy #9 (mất ``du_doan.kenh_nhan``). Trang Thông báo vì thế chỉ ghi
đúng mục ``thong_bao`` qua đường này, không đụng khoá nào khác.

Danh sách kênh chọn được thì KHÔNG trả ở đây: giao diện đã có sẵn
``thread_filters`` + ``thread_filter_meta`` trong config đang nạp (đúng cách
``email-calendar-card.tsx`` đang làm), nên trả lại lần nữa chỉ là một nguồn sự
thật thứ hai để lệch nhau.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Header

from api.support import require_admin
# Bộ ghi log của nhà: `logging.getLogger(__name__)` propagate lên root, mà root
# của ứng dụng này không có handler và đang ở mức WARNING — log biến mất. Đo
# 13/09/2026 trên máy chủ thật.
from utils.log import logger


def _loi(exc: Exception, viec: str) -> dict:
    # MỘT tham số: `utils.log.Logger.warning(message)` không nhận kiểu %-format
    # nhiều đối số như `logging`. Giữ nguyên lời gọi cũ là mỗi lần có lỗi lại
    # ném thêm TypeError ngay trong chính chỗ xử lý lỗi.
    logger.warning({"event": "thong_bao_api_loi", "viec": viec,
                    "loi": str(exc)[:200]})
    return {"ok": False, "error": str(exc)[:200]}


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/thong-bao")
    async def danh_sach(authorization: str | None = Header(default=None)):
        """Sổ đăng ký + cài đặt hiện tại của từng thông báo."""
        require_admin(authorization)
        try:
            from services import thong_bao

            return {"ok": True, "su_kien": thong_bao.dang_ky()}
        except Exception as exc:
            return _loi(exc, "đọc danh sách")

    @router.post("/api/thong-bao/luu")
    async def luu(body: dict, authorization: str | None = Header(default=None)):
        """Ghi cài đặt. body: ``{muc: {<khoa>: {bat: bool, kenh: [...]}}}``.

        Chỉ ghi mục ``thong_bao``; khoá lạ bị bỏ ngay trong ``thong_bao.luu``.
        """
        require_admin(authorization)
        try:
            from services import thong_bao

            muc = body.get("muc")
            if not isinstance(muc, dict):
                return {"ok": False, "error": "thiếu 'muc'"}
            return thong_bao.luu(muc)
        except Exception as exc:
            return _loi(exc, "lưu")

    @router.post("/api/thong-bao/thu")
    async def gui_thu(body: dict, authorization: str | None = Header(default=None)):
        """Gửi thử một thông báo tới đúng kênh đã chọn. body: ``{khoa}``.

        Chạy qua ``asyncio.to_thread``: gửi tin là việc mạng, không được chặn
        vòng lặp sự kiện.
        """
        require_admin(authorization)
        try:
            from services import thong_bao

            khoa = str(body.get("khoa") or "").strip()
            if not khoa:
                return {"ok": False, "error": "thiếu 'khoa'"}
            tin = str(body.get("tin") or "").strip() or (
                "🔔 Tin thử từ Cài đặt → Thông báo. Nhận được tức là kênh này "
                "đã chọn đúng.")
            n = await asyncio.to_thread(thong_bao.gui, khoa, tin)
            if n:
                return {"ok": True, "gui": n}
            # Nói RÕ vì sao không gửi: tắt, chưa chọn kênh, hay kênh từ chối.
            c = thong_bao.cai_dat(khoa)
            if not c["bat"]:
                ly_do = "thông báo này đang tắt"
            elif not c["kenh"]:
                ly_do = "chưa chọn kênh nhận"
            else:
                ly_do = "đã chọn kênh nhưng không kênh nào nhận được"
            return {"ok": False, "gui": 0, "error": ly_do}
        except Exception as exc:
            return _loi(exc, "gửi thử")

    return router
