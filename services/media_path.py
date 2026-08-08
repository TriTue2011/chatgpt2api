"""Giải đường dẫn file media sao cho KHÔNG ra khỏi thư mục gốc.

Tách khỏi `api/media.py` vì hai lý do: đây là luật an toàn chứ không phải luật
định tuyến, và tách ra thì test được mà không phải kéo theo cả FastAPI.

`StaticFiles` tự chặn `..`; một route thường thì phải tự làm — và đó chính là
cái giá phải trả khi bỏ `StaticFiles` để cắm được phép kiểm.
"""
from __future__ import annotations

from pathlib import Path


def duong_an_toan(goc: Path | str, rel: str) -> Path | None:
    """Đường dẫn tuyệt đối NẰM TRONG `goc`, hoặc None.

    `resolve()` TRƯỚC rồi mới so quan hệ cha–con: nhờ vậy chặn được cả chuỗi
    `../` lẫn symlink trỏ ra ngoài. So bằng tiền tố chuỗi thì `/data/images-cu`
    sẽ lọt, vì nó cũng bắt đầu bằng `/data/images`.
    """
    try:
        thu_muc = Path(goc).resolve()
        that = (thu_muc / str(rel or "")).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        that.relative_to(thu_muc)
    except ValueError:
        return None
    return that if that.is_file() else None


__all__ = ["duong_an_toan"]
