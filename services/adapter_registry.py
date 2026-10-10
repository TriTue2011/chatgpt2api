"""Sổ đăng ký adapter — "phiên dịch viên" của web2api.

Mỗi provider (hoặc, về sau, mỗi module chạy ở nơi khác) đăng ký MỘT hàm ``chat`` biết nhận
yêu cầu chuẩn OpenAI của web2api và nói chuyện với phía bên kia theo cách của nó. Cửa điều
phối (``_dispatch_provider``) chỉ tra sổ rồi gọi; nó không còn biết provider nào tồn tại.

Hợp đồng của ``chat``::

    chat(route, messages, tools, tool_choice, body) -> dict | Iterator[dict]

* ``route``  — ``BackendRoute``: ``route.provider`` là mã adapter, ``route.model`` đã bỏ tiền tố.
* trả về — một lời đáp chat-completion (``dict``) hoặc bộ phát từng khúc khi ``body["stream"]``.
* adapter KHÔNG nhận ``tools`` thì cứ bỏ qua đối số đó; chuyển tiếp hay không là việc của nó.

``tai_tep`` — provider tải thẳng tệp lớn lên máy chủ phía bên kia (chatgpt.com): cửa điều
phối luôn chạy bước nén RTK kiểu tải-tệp cho nó, bất kể công tắc ``rtk_enabled``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class Adapter:
    ma: str
    chat: Callable[[Any, list, Any, Any, dict], Any]
    tai_tep: bool = False


_BANG: dict[str, Adapter] = {}


def dang_ky(ma: str, chat: Callable[..., Any], *, tai_tep: bool = False,
            bi_danh: tuple[str, ...] = ()) -> None:
    """Đăng ký adapter cho ``ma`` và các tên gọi khác của nó (``bi_danh``)."""
    adapter = Adapter(ma=ma, chat=chat, tai_tep=tai_tep)
    for ten in (ma, *bi_danh):
        _BANG[ten] = adapter


def tim(ma: str) -> Optional[Adapter]:
    """Adapter của provider ``ma``; ``None`` nếu chưa ai đăng ký.

    Provider khai động có dạng ``loai:ten`` (``custom:lv``) — tra theo phần ``loai``.
    """
    adapter = _BANG.get(ma)
    if adapter is None and ":" in ma:
        adapter = _BANG.get(ma.split(":", 1)[0])
    return adapter


def danh_sach() -> list[str]:
    """Mọi tên đã đăng ký (kể cả bí danh), để test và trang quản trị soi."""
    return sorted(_BANG)
