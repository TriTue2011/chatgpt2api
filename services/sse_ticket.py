"""Vé dùng-một-lần cho SSE, thay cho việc nhét khoá admin vào URL.

`EventSource` của trình duyệt không gửi được header tuỳ ý, nên đường SSE hiện
nay nhận xác thực qua query string: `/api/register/events?token=<KHOÁ ADMIN>`.
Đó là chính `CHATGPT2API_AUTH_KEY` — khoá mở MỌI endpoint — và query string thì
đi vào access log của reverse proxy, lịch sử trình duyệt, header `Referer` khi
trang mở link ra ngoài, và cả log của Cloudflare. Xoay khoá sau khi lộ thì kéo
theo Home Assistant, Zalo và mọi script khác.

Vé ở đây khác khoá ở ba điểm khiến việc lộ không còn nghiêm trọng:

  - **Sống 60 giây.** Log lưu lại cũng chỉ là một chuỗi đã hết hạn.
  - **Dùng đúng một lần.** Mở lại bằng vé cũ là hỏng, kể cả trong 60 giây đó.
  - **Chỉ mở được một đường.** Vé không thay được khoá ở bất kỳ endpoint nào
    khác.

Giữ trong RAM là đủ và đúng: vé sống 60 giây, khởi động lại thì client xin vé
mới — ghi ra đĩa chỉ tạo thêm một chỗ chứa bí mật mà chẳng được gì.
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any

TTL_GIAY = 60.0
# Trần để một client hỏng (vòng lặp xin vé) không ăn hết RAM. 512 vé × 60 giây
# là thừa cho mọi lượng dùng thật.
GIOI_HAN = 512


class KhoVe:
    def __init__(self) -> None:
        self._khoa = threading.Lock()
        self._ve: dict[str, tuple[float, dict[str, Any]]] = {}

    def _don(self, bay_gio: float) -> None:
        het = [k for k, (han, _) in self._ve.items() if han <= bay_gio]
        for k in het:
            self._ve.pop(k, None)

    def cap(self, identity: dict[str, Any]) -> tuple[str, float]:
        """Cấp vé mới cho danh tính đã xác thực. Trả (vé, số giây còn sống)."""
        bay_gio = time.time()
        ve = secrets.token_urlsafe(32)
        with self._khoa:
            self._don(bay_gio)
            if len(self._ve) >= GIOI_HAN:
                # Bỏ vé sắp hết hạn nhất — nó gần vô dụng nhất.
                cu = min(self._ve, key=lambda k: self._ve[k][0])
                self._ve.pop(cu, None)
            self._ve[ve] = (bay_gio + TTL_GIAY, dict(identity))
        return ve, TTL_GIAY

    def dung(self, ve: str) -> dict[str, Any] | None:
        """Đổi vé lấy danh tính. Vé BIẾN MẤT ngay, dùng lại không được.

        Xoá trước khi trả về (chứ không sau khi stream đóng) để hai request
        đến cùng lúc với cùng một vé thì chỉ một cái qua được.
        """
        if not ve:
            return None
        bay_gio = time.time()
        with self._khoa:
            self._don(bay_gio)
            muc = self._ve.pop(ve, None)
        if not muc:
            return None
        han, identity = muc
        return identity if han > bay_gio else None

    def so_ve(self) -> int:
        with self._khoa:
            self._don(time.time())
            return len(self._ve)


kho_ve = KhoVe()

__all__ = ["GIOI_HAN", "KhoVe", "TTL_GIAY", "kho_ve"]
