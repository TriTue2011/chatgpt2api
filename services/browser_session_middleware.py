"""Nhận diện phiên trình duyệt qua cookie, và chặn CSRF cho phiên đó.

**Vì sao là middleware + ContextVar chứ không sửa chữ ký hàm.** 289 điểm gọi
``require_admin(authorization)`` nằm rải trên 18 file, tất cả chỉ nhận đúng
chuỗi header. Thêm tham số ``Request`` vào từng chỗ là một diff khổng lồ chạm
vào mọi endpoint — rủi ro lớn hơn nhiều so với thứ nó sửa. Middleware giải
được danh tính một lần rồi đặt vào ContextVar; ``require_identity`` chỉ cần
biết "không có Bearer thì nhìn sang đây".

**Thứ tự ưu tiên: Bearer TRƯỚC, cookie SAU.** Request mang Bearer đi nguyên
đường cũ — không đọc cookie, không đòi CSRF. Home Assistant, Zalo, script và
API ngoài vì thế không đổi hành vi một chút nào.

**CSRF.** Cookie tự động được trình duyệt gửi kèm, kể cả khi request do trang
khác kích hoạt — đó chính là CSRF. Nên với phiên cookie, mọi phương thức làm
đổi trạng thái phải kèm ``X-CSRF-Token`` khớp bí mật của phiên, và ``Origin``
phải hợp lệ. Bearer không cần: nó không tự động được gửi kèm.

Tắt cờ ``security.browser_sessions_enabled`` thì middleware trả request đi
tiếp ngay ở dòng đầu — không đọc cookie, không đụng gì.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from services.browser_session import COOKIE_NAME, CSRF_HEADER, kho_phien
from services.config import config

logger = logging.getLogger(__name__)

# Danh tính giải được từ cookie cho request đang chạy. `require_identity` đọc
# biến này khi request không mang Bearer.
danh_tinh_cookie: ContextVar[dict[str, Any] | None] = ContextVar(
    "danh_tinh_cookie", default=None)

PHUONG_THUC_DOI_TRANG_THAI = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Đăng nhập chưa có phiên thì chưa có CSRF token để mà gửi — miễn cho đúng
# đường vào, phần còn lại vẫn bị soi.
DUONG_MIEN_CSRF = ("/auth/browser-login",)


def bat_phien_trinh_duyet() -> bool:
    """Cờ ``security.browser_sessions_enabled``. Mặc định TẮT.

    Mặc định tắt vì bật lên là đổi cách cả web admin xác thực; phải có
    frontend đi kèm rồi mới bật, không thì trang trắng mà không ai biết vì sao.
    """
    try:
        sec = config.get().get("security")
        if isinstance(sec, dict):
            return bool(sec.get("browser_sessions_enabled"))
    except Exception:
        pass
    return False


def origin_hop_le(origin: str, host: str) -> bool:
    """Origin có phải chỗ ta chấp nhận không.

    Không có ``Origin`` (điều hướng thường, curl) → hợp lệ: trình duyệt LUÔN
    gửi Origin cho request cross-site làm đổi trạng thái, nên vắng nó không
    phải dấu hiệu tấn công. Có mà sai mới là.
    """
    if not origin:
        return True
    o = urlsplit(origin)
    if not o.netloc:
        return False
    cho_phep = config.cors_allow_origins
    if cho_phep and cho_phep != ["*"]:
        return any(origin.rstrip("/") == c.rstrip("/") for c in cho_phep)
    # Chưa khai allowlist → chấp nhận đúng host đang phục vụ (same-origin).
    return bool(host) and o.netloc.lower() == host.lower()


class PhienTrinhDuyetMiddleware:
    """ASGI thuần, không phải BaseHTTPMiddleware.

    BaseHTTPMiddleware chạy phần dưới trong một task khác; ContextVar đặt
    trong đó thì endpoint không nhìn thấy. ASGI thuần chạy cùng task nên
    ContextVar truyền xuống bình thường.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not bat_phien_trinh_duyet():
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers") or []}

        # Có Bearer THẬT → đường cũ, không đụng cookie, không đòi CSRF.
        #
        # Phải kiểm cả phần token chứ không chỉ tiền tố: một header rỗng kiểu
        # `Authorization: Bearer ` (client dựng chuỗi từ biến rỗng — chuyện rất
        # dễ xảy ra ở frontend) sẽ khớp tiền tố, làm middleware bỏ qua cookie,
        # rồi `require_identity` cũng không có token nào để dùng → 401 dù người
        # dùng đang có phiên hợp lệ.
        auth = headers.get("authorization", "")
        if auth[:7].lower() == "bearer " and auth[7:].strip():
            await self.app(scope, receive, send)
            return

        sid = _doc_cookie(headers.get("cookie", ""), COOKIE_NAME)
        ban_ghi = kho_phien.tra_cuu(sid) if sid else None
        if not ban_ghi:
            await self.app(scope, receive, send)
            return

        duong = str(scope.get("path") or "")
        phuong_thuc = str(scope.get("method") or "").upper()
        if phuong_thuc in PHUONG_THUC_DOI_TRANG_THAI and duong not in DUONG_MIEN_CSRF:
            if not origin_hop_le(headers.get("origin", ""), headers.get("host", "")):
                await _tu_choi(scope, receive, send,
                               "Origin không hợp lệ cho phiên trình duyệt",
                               "origin_khong_hop_le")
                return
            if not kho_phien.kiem_csrf(sid, headers.get(CSRF_HEADER.lower(), "")):
                await _tu_choi(scope, receive, send,
                               f"Thiếu hoặc sai {CSRF_HEADER}", "csrf_khong_khop")
                return

        moc = danh_tinh_cookie.set({
            "id": ban_ghi.get("chu_the") or "",
            "name": ban_ghi.get("ten") or "",
            "role": ban_ghi.get("vai_tro") or "",
            "nguon": "cookie",
        })
        try:
            await self.app(scope, receive, send)
        finally:
            danh_tinh_cookie.reset(moc)


def _doc_cookie(header: str, ten: str) -> str:
    for phan in header.split(";"):
        k, _, v = phan.strip().partition("=")
        if k == ten:
            return v.strip()
    return ""


async def _tu_choi(scope: Scope, receive: Receive, send: Send,
                   thong_bao: str, ma: str) -> None:
    logger.warning({"event": "phien_trinh_duyet_tu_choi", "code": ma})
    resp = JSONResponse({"detail": {"error": thong_bao, "code": ma}}, status_code=403)
    await resp(scope, receive, send)


__all__ = ["PhienTrinhDuyetMiddleware", "bat_phien_trinh_duyet",
           "danh_tinh_cookie", "origin_hop_le"]
