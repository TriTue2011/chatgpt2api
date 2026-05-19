"""vn_phat_nguoi — tra cứu phạt nguội Việt Nam qua csgt.vn.

csgt.vn cung cấp form tra cứu công khai theo biển số xe. Form yêu cầu:
- Biển số (vd: 30A-12345)
- Loại xe (1=ôtô, 2=xe máy, 3=xe điện)
- Captcha — đây là điểm tắc nghẽn (csgt.vn dùng captcha số)

Tools chỉ best-effort: hiển thị URL form + cảnh báo captcha. Không tự bypass
captcha vì thường vi phạm ToS. User được hướng dẫn click link để tra cứu thủ công.

Khi csgt.vn ra OCR-friendly captcha hoặc API token, có thể bypass; hiện tại
cách an toàn nhất là trả URL form + tooling guide.
"""

from __future__ import annotations

import logging
import re

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("vn_phat_nguoi")

CSGT_URL = "https://www.csgt.vn/?mod=contact&task=tracuu_post&ajax"
CSGT_FORM = "https://www.csgt.vn/tra-cuu-phuong-tien-vi-pham.html"

VEHICLE_TYPES = {
    "oto": ("1", "Ô tô"),
    "ô tô": ("1", "Ô tô"),
    "car": ("1", "Ô tô"),
    "xemay": ("2", "Xe máy"),
    "xe máy": ("2", "Xe máy"),
    "motor": ("2", "Xe máy"),
    "xedien": ("3", "Xe đạp điện"),
    "xe đạp điện": ("3", "Xe đạp điện"),
}

PLATE_PATTERN = re.compile(r"^\d{2}[A-Z]{1,2}-?\d{4,5}(\.\d{2})?$", re.IGNORECASE)


def _normalise_plate(plate: str) -> str:
    p = plate.strip().upper().replace(" ", "")
    if "-" not in p and len(p) >= 7:
        p = f"{p[:3]}-{p[3:]}"
    return p


def _is_valid_plate(plate: str) -> bool:
    return bool(PLATE_PATTERN.match(plate))


@mcp.tool()
def check_traffic_violation(plate: str, vehicle_type: str = "oto") -> str:
    """Hướng dẫn tra cứu phạt nguội xe tại Việt Nam qua csgt.vn.

    csgt.vn yêu cầu nhập captcha thủ công nên không thể tra cứu tự động.
    Tool này trả về URL form + biển số đã chuẩn hóa để user tra cứu.

    Args:
        plate: Biển số xe (vd: "30A-12345", "29-K3-1234.56").
        vehicle_type: Loại xe ('oto', 'xe máy', 'xe đạp điện'). Mặc định oto.

    Returns:
        Hướng dẫn tra cứu kèm URL form, biển số đã chuẩn hóa, mã loại xe.
    """
    norm_plate = _normalise_plate(plate)
    if not _is_valid_plate(norm_plate):
        return (
            f"Biển số '{plate}' không đúng định dạng VN.\n"
            "Định dạng đúng: XX(A-Z)-12345 hoặc 29-K3-1234.56"
        )

    vt_key = vehicle_type.lower().strip()
    vt = VEHICLE_TYPES.get(vt_key)
    if not vt:
        return (
            f"Loại xe '{vehicle_type}' không hợp lệ. "
            f"Chọn: ô tô, xe máy, xe đạp điện."
        )
    code, vt_label = vt

    return (
        f"**Tra cứu phạt nguội cho {vt_label} biển số {norm_plate}:**\n\n"
        f"1. Mở trang: {CSGT_FORM}\n"
        f"2. Nhập biển số: `{norm_plate}`\n"
        f"3. Chọn loại xe: `{vt_label}` (mã {code})\n"
        f"4. Nhập captcha hiển thị trên trang\n"
        f"5. Bấm 'Tra cứu'\n\n"
        f"_Lưu ý: csgt.vn yêu cầu captcha thủ công nên không thể tra cứu tự động._"
    )


@mcp.tool()
def list_vehicle_types() -> str:
    """Liệt kê các loại xe được hỗ trợ tra cứu phạt nguội.

    Returns:
        Danh sách loại xe + mã code dùng cho check_traffic_violation.
    """
    seen = set()
    out = ["**Loại xe hỗ trợ tra cứu phạt nguội:**", ""]
    for key, (code, label) in VEHICLE_TYPES.items():
        if code in seen:
            continue
        seen.add(code)
        out.append(f"- {label} (mã {code})")
    return "\n".join(out)
