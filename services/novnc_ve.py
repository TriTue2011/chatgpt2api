"""Vé mở noVNC, và phiên ngắn hạn đổi được từ vé.

**Vì sao cần.** noVNC mở bằng `window.open` sang tab mới. Tab đó là điều hướng
thường của trình duyệt, không có JavaScript nào gắn `Authorization` vào được —
nên proxy `/novnc/…` không thể đòi header như các endpoint khác, và bản đầu đòi
header đã làm mọi lần mở đều 401.

Đây đúng bài toán mà `services/sse_ticket.py` đã giải cho SSE, nên module này
bám theo nó: web UI xin vé bằng header (đường xác thực bình thường), rồi nhét
vé vào URL. Vé sống ngắn và dùng một lần, nên lộ qua access log, lịch sử trình
duyệt hay header `Referer` cũng gần như vô hại — khác hẳn nhét thẳng khoá admin
vào URL, vì khoá đó mở MỌI endpoint và xoay nó thì kéo theo Home Assistant,
Zalo và mọi script khác.

**Khác SSE ở đâu.** SSE mở đúng một kết nối nên vé dùng-một-lần là đủ. noVNC
tải hàng chục tệp (`vnc.html`, rồi `core/*.js`, `app/*.js`, ảnh…) nên vé sẽ
cháy ngay ở tệp đầu và mọi tệp sau đều 401 — trang trắng. Vì thế vé ở đây đổi
lấy một PHIÊN ngắn hạn, giao cho trình duyệt dưới dạng cookie giới hạn trong
đường `/novnc`. Mọi tệp con và kênh WebSocket dùng chung phiên đó.

Phiên sống lâu hơn vé vì nó phải trụ hết buổi làm việc trên màn hình từ xa —
đăng nhập một tài khoản Google, gõ captcha — chứ không phải chỉ đủ để tải trang.

Giữ trong RAM là đủ và đúng: khởi động lại thì người dùng bấm mở lại, còn ghi
ra đĩa chỉ tạo thêm một chỗ chứa bí mật mà chẳng được gì.
"""
from __future__ import annotations

import secrets
import threading
import time

# Vé chỉ sống đủ để trình duyệt mở tab và gửi request đầu tiên.
VE_TTL = 60.0
# Phiên phải trụ hết một buổi thao tác tay trên màn hình từ xa.
PHIEN_TTL = 8 * 60 * 60.0
# Trần để một client hỏng (vòng lặp xin vé) không ăn hết RAM.
GIOI_HAN = 512


class KhoVeNoVNC:
    def __init__(self) -> None:
        self._khoa = threading.Lock()
        self._ve: dict[str, float] = {}
        self._phien: dict[str, float] = {}
        # Cho phép proxy đọc mà không phải import thêm hằng.
        self.PHIEN_TTL = PHIEN_TTL

    @staticmethod
    def _don(kho: dict[str, float], bay_gio: float) -> None:
        for k in [k for k, han in kho.items() if han <= bay_gio]:
            kho.pop(k, None)

    def cap(self) -> tuple[str, float]:
        """Cấp vé mới. Trả (vé, số giây sống)."""
        bay_gio = time.time()
        ve = secrets.token_urlsafe(32)
        with self._khoa:
            self._don(self._ve, bay_gio)
            if len(self._ve) >= GIOI_HAN:
                # Bỏ vé sắp hết hạn nhất — nó gần vô dụng nhất.
                self._ve.pop(min(self._ve, key=self._ve.get), None)
            self._ve[ve] = bay_gio + VE_TTL
        return ve, VE_TTL

    def dung(self, ve: str) -> bool:
        """Tiêu vé. Vé BIẾN MẤT ngay, dùng lại không được.

        Xoá trước khi trả lời (chứ không sau) để hai request đến cùng lúc với
        cùng một vé thì chỉ một cái qua được.
        """
        if not ve:
            return False
        bay_gio = time.time()
        with self._khoa:
            self._don(self._ve, bay_gio)
            han = self._ve.pop(ve, None)
        return han is not None and han > bay_gio

    def mo_phien(self) -> str:
        """Mở phiên noVNC mới, trả mã để đặt vào cookie."""
        bay_gio = time.time()
        ma = secrets.token_urlsafe(32)
        with self._khoa:
            self._don(self._phien, bay_gio)
            if len(self._phien) >= GIOI_HAN:
                self._phien.pop(min(self._phien, key=self._phien.get), None)
            self._phien[ma] = bay_gio + PHIEN_TTL
        return ma

    def phien_con_han(self, ma: str) -> bool:
        if not ma:
            return False
        bay_gio = time.time()
        with self._khoa:
            self._don(self._phien, bay_gio)
            han = self._phien.get(ma)
        return han is not None and han > bay_gio


kho_ve_novnc = KhoVeNoVNC()

__all__ = ["GIOI_HAN", "KhoVeNoVNC", "PHIEN_TTL", "VE_TTL", "kho_ve_novnc"]
