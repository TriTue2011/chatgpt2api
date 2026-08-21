"""Dọn thư viện media: chọn ảnh/video/nhạc cần xoá theo luật giữ lại.

Chủ máy nêu 19/08, năm cách nói mà thực chất là ba luật:

    "xoá ảnh vừa tạo" · "xoá video vừa tạo"            → VUA_TAO
    "xoá hết ảnh trong thư viện"                        → TAT_CA
    "xoá ảnh từ 7 ngày trở về trước"                    ┐
    "giữ lại ảnh 7 ngày gần nhất"                       ├ CU_HON
    "giữ lại 7 ngày kể từ ảnh tạo lần cuối"             ┘

Hai câu giữa nói ngược nhau mà cùng một phép: bỏ thứ cũ hơn N ngày. Khác nhau ở
MỐC đếm ngược — câu cuối đếm từ tệp mới nhất chứ không từ bây giờ, nên thư viện
để yên ba tháng vẫn giữ đủ 7 ngày cuối cùng có hoạt động, thay vì bị xoá sạch.

Module này chỉ CHỌN và gọi ``image_service.delete_images`` — hàm đó vốn đã chặn
path traversal, dọn kèm thumbnail, gỡ tag và dọn thư mục rỗng. Viết lại phần xoá
ở đây là dựng đường thứ hai vào cùng một kho, kiểu gì cũng có ngày lệch nhau.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Đuôi tệp theo từng loại. Nhạc do Lyria tạo là .mp4 (tiếng + bìa động) nằm
#: chung thư viện video, phân biệt bằng tiền tố tên ``nhac_`` — xem
#: ``capabilities._h_library_media``, đây giữ đúng quy ước đó.
DUOI = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"},
    "video": {".mp4", ".mov", ".webm", ".avi", ".mkv"},
    "music": {".mp4", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"},
}
TIEN_TO_NHAC = "nhac_"

#: Ba luật chọn.
VUA_TAO, TAT_CA, CU_HON = "vua-tao", "tat-ca", "cu-hon"
CHE_DO = (VUA_TAO, TAT_CA, CU_HON)

#: Mốc đếm ngược của luật CU_HON.
HOM_NAY, LAN_CUOI = "hom-nay", "lan-cuoi"
MOC = (HOM_NAY, LAN_CUOI)

_XAC_NHAN_TTL_S = 600.0
_xac_nhan_lock = threading.Lock()


@dataclass(frozen=True)
class YeuCauDon:
    """Các tham số phải khớp nguyên vẹn giữa preview và xác nhận."""

    kind: str
    che_do: str
    so_ngay: int
    moc: str


_xac_nhan_dang_cho: dict[
    str, tuple[float, YeuCauDon, tuple[dict[str, Any], ...]]
] = {}


class LoiDonMedia(ValueError):
    """Tham số không hợp lệ — người gọi báo lại nguyên văn cho người dùng."""


def luu_xem_truoc(khoa: str, yeu_cau: YeuCauDon,
                  muc: list[dict[str, Any]]) -> None:
    """Giữ đúng snapshot người dùng vừa xem, tối đa 10 phút và dùng một lần."""
    khoa = str(khoa or "").strip()
    if not khoa:
        raise LoiDonMedia("không xác định được người đang duyệt danh sách xoá")
    bay_gio = time.monotonic()
    snapshot = tuple(dict(x) for x in muc)
    with _xac_nhan_lock:
        het_han = [k for k, (han, _, _) in _xac_nhan_dang_cho.items()
                   if han <= bay_gio]
        for k in het_han:
            _xac_nhan_dang_cho.pop(k, None)
        _xac_nhan_dang_cho[khoa] = (bay_gio + _XAC_NHAN_TTL_S,
                                    yeu_cau, snapshot)


def lay_da_duyet(khoa: str, yeu_cau: YeuCauDon) -> list[dict[str, Any]] | None:
    """Lấy snapshot khớp yêu cầu rồi huỷ ngay, tránh xác nhận lại hai lần."""
    khoa = str(khoa or "").strip()
    if not khoa:
        return None
    bay_gio = time.monotonic()
    with _xac_nhan_lock:
        dang_cho = _xac_nhan_dang_cho.get(khoa)
        if not dang_cho:
            return None
        han, da_xem, snapshot = dang_cho
        if han <= bay_gio:
            _xac_nhan_dang_cho.pop(khoa, None)
            return None
        if da_xem != yeu_cau:
            return None
        _xac_nhan_dang_cho.pop(khoa, None)
    return [dict(x) for x in snapshot]


def _khop_loai(p: Path, kind: str) -> bool:
    ten = p.name.lower()
    duoi = p.suffix.lower()
    if kind == "music":
        return ten.startswith(TIEN_TO_NHAC) or duoi in (DUOI["music"] - DUOI["video"])
    if kind == "video":
        return duoi in DUOI["video"] and not ten.startswith(TIEN_TO_NHAC)
    return duoi in DUOI["image"]


def liet_ke(kind: str, thu_muc: Path | str | None = None) -> list[dict[str, Any]]:
    """Mọi tệp thuộc loại này trong thư viện, MỚI NHẤT ĐỨNG TRƯỚC.

    Bỏ qua tệp/thư mục ẩn (marker TTL, tệp tạm) và thumbnail — chúng là dữ liệu
    nội bộ, không phải thứ người dùng gọi là "ảnh trong thư viện".
    """
    if kind not in DUOI:
        raise LoiDonMedia(f"loại phải là {sorted(DUOI)}, nhận {kind!r}")
    if thu_muc is None:
        from services.config import config
        thu_muc = config.images_dir
    goc = Path(thu_muc)
    ra: list[dict[str, Any]] = []
    if not goc.is_dir():
        return ra
    for p in goc.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(goc)
        if any(x.startswith(".") for x in rel.parts) or "_thumb" in p.name:
            continue
        if not _khop_loai(p, kind):
            continue
        st = p.stat()
        ra.append({"rel": rel.as_posix(), "bytes": st.st_size, "mtime": st.st_mtime})
    ra.sort(key=lambda x: x["mtime"], reverse=True)
    return ra


def chon(kind: str, che_do: str, *, so_ngay: int = 0, moc: str = HOM_NAY,
         bay_gio: float | None = None,
         thu_muc: Path | str | None = None) -> list[dict[str, Any]]:
    """Danh sách tệp SẼ bị xoá theo luật đã chọn. Không xoá gì cả.

    Tách hẳn khỏi ``xoa`` để tầng gọi xem trước rồi mới hỏi người dùng duyệt —
    xoá cả thư viện mà không nói trước sẽ xoá bao nhiêu tệp là chuyện không sửa
    lại được.
    """
    if che_do not in CHE_DO:
        raise LoiDonMedia(f"chế độ phải là {list(CHE_DO)}, nhận {che_do!r}")
    if moc not in MOC:
        raise LoiDonMedia(f"mốc phải là {list(MOC)}, nhận {moc!r}")
    tat = liet_ke(kind, thu_muc)
    if not tat:
        return []
    if che_do == VUA_TAO:
        return tat[:1]
    if che_do == TAT_CA:
        return tat
    if so_ngay <= 0:
        raise LoiDonMedia("giữ lại bao nhiêu ngày thì phải nói rõ số ngày")
    goc_thoi_gian = tat[0]["mtime"] if moc == LAN_CUOI else (bay_gio or time.time())
    nguong = goc_thoi_gian - so_ngay * 86400
    return [x for x in tat if x["mtime"] < nguong]


def tom_tat(muc: list[dict[str, Any]]) -> str:
    """Câu mô tả những gì sắp xoá — để hỏi người dùng trước khi làm thật."""
    if not muc:
        return "không có tệp nào khớp"
    mb = sum(x["bytes"] for x in muc) / 1048576
    cu = time.strftime("%d/%m/%Y", time.localtime(muc[-1]["mtime"]))
    moi = time.strftime("%d/%m/%Y", time.localtime(muc[0]["mtime"]))
    khoang = cu if cu == moi else f"{cu} → {moi}"
    return f"{len(muc)} tệp · {mb:.1f} MB · {khoang}"


def xoa(muc: list[dict[str, Any]], thu_muc: Path | str | None = None) -> int:
    """Xoá thật danh sách đã chọn, trả số tệp đã xoá.

    Giao cho ``image_service.delete_images``: nó đã chặn path traversal, xoá kèm
    thumbnail, gỡ tag và dọn thư mục rỗng.
    """
    if not muc:
        return 0
    if thu_muc is None:
        from services.config import config
        thu_muc = config.images_dir
    goc = Path(thu_muc)

    # Một tên tệp có thể bị ghi đè sau preview. Chỉ đường dẫn thôi chưa đủ để
    # chứng minh đây vẫn là nội dung người dùng đã duyệt, nên đối chiếu cả size
    # và mtime của snapshot ngay trước khi giao xuống tầng xoá.
    khong_doi: list[dict[str, Any]] = []
    for item in muc:
        try:
            st = (goc / str(item["rel"])).stat()
            if (st.st_size == int(item["bytes"])
                    and math.isclose(st.st_mtime, float(item["mtime"]), abs_tol=1e-6)):
                khong_doi.append(item)
        except (KeyError, OSError, TypeError, ValueError):
            continue
    if not khong_doi:
        return 0

    from services.image_service import delete_images

    kq = delete_images(paths=[str(x["rel"]) for x in khong_doi])
    so = int(kq.get("removed") or 0)
    logger.info({"event": "don_thu_vien_media", "da_xoa": so, "chon": len(muc),
                 "bo_qua_da_doi": len(muc) - len(khong_doi)})
    return so
