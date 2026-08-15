"""Phục vụ `/images` có kiểm soát, thay cho `StaticFiles` mở toang.

Trước đây `/images` là một mount `StaticFiles` thuần: ai đoán hoặc dò được tên
file là tải được mọi ảnh, video, PDF từng đi qua hệ thống — kể cả ảnh camera,
ảnh chụp màn hình và tài liệu người dùng tải lên. Tên file thì nằm sẵn trong
log, trong lịch sử chat và trong mọi URL đã chia sẻ.

**Vì sao kiểm ở MỘT CỬA chứ không ký ở từng nơi phát.** Có 76 chỗ trong mã
dựng URL `/images/…`. Sửa từng chỗ là một diff khổng lồ, và chỉ cần sót một
chỗ là có một đường vòng — mà chỗ bị sót thì không ai biết cho tới khi có
người tìm ra. Kiểm ở cửa vào thì không sót được.

**Hai đường vào hợp lệ**, vì hai loại người dùng khác hẳn nhau:

  1. **Chữ ký** — cho nơi KHÔNG gửi được header: Zalo, Telegram, loa Cast kéo
     file bằng cách đưa URL cho một tiến trình khác.
  2. **Phiên đã xác thực** — cho trình duyệt admin. Thẻ `<img>` không gửi được
     `Authorization`, nhưng cookie phiên thì trình duyệt tự gửi. Đây chính là
     lý do việc bắt buộc chữ ký phải bật SAU khi phiên cookie đã chạy.

Cờ `security.signed_media_required` mặc định TẮT → giữ nguyên hành vi cũ.
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from services.config import config

logger = logging.getLogger(__name__)

PHAM_VI = "images"


def bat_buoc_ky() -> bool:
    try:
        sec = config.get().get("security")
        return bool(sec.get("signed_media_required")) if isinstance(sec, dict) else False
    except Exception:
        return False


def _duong_that(rel: str) -> Path | None:
    """Đường dẫn tuyệt đối nằm trong images_dir, hoặc None.

    Luật an toàn nằm ở `services/media_path.duong_an_toan` — tách ra để test
    được mà không phải kéo theo cả FastAPI.
    """
    from services.media_path import duong_an_toan
    return duong_an_toan(config.images_dir, rel)


def require_image_access(rel: str, exp: str = "", sig: str = "") -> None:
    """Áp chính sách ảnh đã ký cho mọi biến thể của cùng một ảnh.

    Thumbnail là một biểu diễn của ``/images/<rel>``, không phải một tài sản
    độc lập. Vì vậy dùng chính chữ ký của ảnh gốc: URL ảnh đã ký khi đổi sang
    thumbnail vẫn hợp lệ, còn một chữ ký cho ảnh A không mở được ảnh B.
    """
    if not bat_buoc_ky():
        return

    from services.signed_url import kiem_chu_ky

    duong = f"/images/{rel}"
    hop_le = kiem_chu_ky(duong, exp, sig, pham_vi=PHAM_VI)
    if not hop_le:
        # Trình duyệt admin: `<img>` không gửi được Authorization, nhưng cookie
        # phiên được trình duyệt gửi tự động.
        try:
            from services.browser_session_middleware import danh_tinh_cookie
            hop_le = danh_tinh_cookie.get() is not None
        except Exception:
            hop_le = False
    if not hop_le:
        logger.warning({"event": "anh_tu_choi_thieu_chu_ky", "path": duong[:120]})
        raise HTTPException(403, "chữ ký không hợp lệ hoặc đã hết hạn")


def create_router() -> APIRouter:
    router = APIRouter(tags=["media"])

    @router.get("/images/{rel:path}")
    async def phuc_vu_anh(rel: str, exp: str = "", sig: str = ""):
        that = _duong_that(rel)
        if that is None:
            raise HTTPException(404, "not found")

        require_image_access(rel, exp, sig)

        kieu, _ = mimetypes.guess_type(that.name)
        return FileResponse(str(that), media_type=kieu or "application/octet-stream")

    return router


__all__ = ["PHAM_VI", "bat_buoc_ky", "create_router", "require_image_access"]
