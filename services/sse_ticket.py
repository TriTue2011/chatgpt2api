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

import hmac
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

    def cap(self, identity: dict[str, Any],
            phien_bam: str = "") -> tuple[str, float]:
        """Cấp vé mới cho danh tính đã xác thực. Trả (vé, số giây còn sống).

        `phien_bam` = hash session-id của phiên ĐÃ xin vé. Vé chỉ dùng được từ
        chính phiên đó — không có ràng buộc này thì ai đọc được vé trong 60
        giây (log proxy, lịch sử trình duyệt, người ngồi cạnh) đều mở được
        stream từ máy khác.
        """
        bay_gio = time.time()
        ve = secrets.token_urlsafe(32)
        with self._khoa:
            self._don(bay_gio)
            if len(self._ve) >= GIOI_HAN:
                # Bỏ vé sắp hết hạn nhất — nó gần vô dụng nhất.
                cu = min(self._ve, key=lambda k: self._ve[k][0])
                self._ve.pop(cu, None)
            muc = dict(identity)
            muc["_phien_bam"] = str(phien_bam or "")
            self._ve[ve] = (bay_gio + TTL_GIAY, muc)
        return ve, TTL_GIAY

    def dung(self, ve: str, phien_bam: str = "") -> dict[str, Any] | None:
        """Đổi vé lấy danh tính. Vé BIẾN MẤT ngay, dùng lại không được.

        Xoá trước khi trả về (chứ không sau khi stream đóng) để hai request
        đến cùng lúc với cùng một vé thì chỉ một cái qua được.

        Vé cấp cho một phiên thì CHỈ phiên đó dùng được. Vé cấp không kèm phiên
        (xin bằng Bearer) thì không ràng buộc — lúc đó nó vẫn còn hai lớp bảo
        vệ: dùng một lần và sống 60 giây.
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
        if han <= bay_gio:
            return None
        can = str(identity.get("_phien_bam") or "")
        if can and not hmac.compare_digest(can.encode(),
                                           str(phien_bam or "").encode()):
            return None
        return identity

    def so_ve(self) -> int:
        with self._khoa:
            self._don(time.time())
            return len(self._ve)


kho_ve = KhoVe()

__all__ = ["GIOI_HAN", "KhoVe", "TTL_GIAY", "kho_ve"]
