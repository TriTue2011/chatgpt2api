"""Content-Security-Policy: báo cáo trước, siết sau.

CSP là loại header mà bật nhầm thì trang trắng và người dùng không có cách nào
biết vì sao — lỗi chỉ nằm trong console của trình duyệt. Vì vậy nó đi hai
bước, và bước một là bắt buộc:

  1. `Content-Security-Policy-Report-Only` — trình duyệt KHÔNG chặn gì, chỉ
     gửi báo cáo về `/api/csp-report`. Chạy vài ngày để biết cái gì sẽ vỡ.
  2. Sửa hết vi phạm rồi mới đổi `security.csp_enforce: true`.

**Chính sách report-only là chính sách ĐÍCH, không phải bản nới lỏng.** Nếu đã
cho sẵn `'unsafe-inline'` ở bước một thì báo cáo sẽ im lặng và ta không học
được gì — tới lúc siết mới biết là hỏng. Web ở đây là bản Next.js static
export, nhiều khả năng có script nội tuyến; đó chính là thứ cần báo cáo chỉ
ra, chứ không phải thứ cần giấu đi trước.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

DUONG_BAO_CAO = "/api/csp-report"

# Chính sách ĐÍCH. `frame-ancestors 'none'` chặn nhúng iframe (clickjacking);
# `base-uri 'self'` chặn thẻ <base> bị chèn để đổi hướng mọi URL tương đối.
_CHI_THI: tuple[str, ...] = (
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    # data:/blob: cần cho ảnh xem trước và audio phát tại chỗ — đây là dữ liệu
    # do chính trang tạo ra, không phải nguồn ngoài.
    "img-src 'self' data: blob:",
    "media-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    # style nội tuyến thì gần như không tránh được với CSS-in-JS, và rủi ro
    # của nó thấp hơn hẳn script nội tuyến. Script thì CỐ Ý siết để báo cáo
    # chỉ ra chỗ cần sửa.
    "style-src 'self' 'unsafe-inline'",
    "script-src 'self'",
)


def chuoi_chinh_sach(*, co_report_uri: bool) -> str:
    phan = list(_CHI_THI)
    if co_report_uri:
        phan.append(f"report-uri {DUONG_BAO_CAO}")
    return "; ".join(phan)


def dang_siet(config) -> bool:
    """Cờ `security.csp_enforce`. Mặc định TẮT (chỉ báo cáo)."""
    try:
        sec = config.get().get("security")
        return bool(sec.get("csp_enforce")) if isinstance(sec, dict) else False
    except Exception:
        return False


def bat_csp(config) -> bool:
    """Cờ `security.csp_enabled`. Mặc định TẮT.

    Kể cả report-only cũng sau cờ: nó thêm một header vào MỌI phản hồi và một
    endpoint nhận POST không cần auth. Bật khi chủ máy sẵn sàng nhìn báo cáo,
    không phải mặc định cho mọi bản triển khai.
    """
    try:
        sec = config.get().get("security")
        return bool(sec.get("csp_enabled")) if isinstance(sec, dict) else False
    except Exception:
        return False


class _BoDemBaoCao:
    """Gộp báo cáo trùng và chặn lụt log.

    Một trang vi phạm có thể bắn hàng trăm báo cáo mỗi lần tải. Ghi hết là log
    ngập và mất luôn mọi thứ khác — đúng lúc đang cần đọc log để sửa.
    """

    CUA_SO_GIAY = 300.0
    TRAN_MOI_CUA_SO = 60

    def __init__(self) -> None:
        self._khoa = threading.Lock()
        self._da_thay: dict[tuple[str, str], int] = {}
        self._moc = 0.0
        self._dem = 0

    def nen_ghi(self, chi_thi: str, nguon: str) -> tuple[bool, int]:
        """(có nên ghi log không, số lần đã thấy trong cửa sổ)."""
        bay_gio = time.time()
        khoa = (str(chi_thi or "")[:80], str(nguon or "")[:120])
        with self._khoa:
            if bay_gio - self._moc > self.CUA_SO_GIAY:
                self._moc = bay_gio
                self._da_thay.clear()
                self._dem = 0
            self._dem += 1
            lan = self._da_thay.get(khoa, 0) + 1
            self._da_thay[khoa] = lan
            if self._dem > self.TRAN_MOI_CUA_SO:
                return False, lan
            # Ghi lần đầu, rồi thưa dần: 1, 10, 100…
            return (lan == 1 or lan % 10 == 0), lan


bo_dem = _BoDemBaoCao()


def ghi_bao_cao(du_lieu: dict) -> None:
    """Ghi một vi phạm CSP, đã gộp trùng. KHÔNG ghi nguyên payload.

    Payload do trình duyệt gửi và chứa URL đầy đủ của trang — có thể mang theo
    tham số nhạy cảm. Chỉ giữ ba trường cần cho việc sửa.
    """
    r = du_lieu.get("csp-report") if isinstance(du_lieu.get("csp-report"), dict) else du_lieu
    if not isinstance(r, dict):
        return
    chi_thi = str(r.get("effective-directive") or r.get("violated-directive") or "")[:80]
    nguon = str(r.get("blocked-uri") or "")[:120]
    ghi, lan = bo_dem.nen_ghi(chi_thi, nguon)
    if ghi:
        logger.warning({"event": "csp_vi_pham", "directive": chi_thi,
                        "blocked": nguon, "lan": lan})


__all__ = ["DUONG_BAO_CAO", "bat_csp", "chuoi_chinh_sach", "dang_siet",
           "ghi_bao_cao"]
