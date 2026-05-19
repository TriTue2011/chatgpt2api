"""vn_stock — giá cổ phiếu Việt Nam (HOSE/HNX) qua VNDirect public API.

VNDirect cung cấp endpoint công khai (không cần API key):
- finfo-api.vndirect.com.vn/v4/stocks → metadata
- finfo-api.vndirect.com.vn/v4/stock_prices → giá lịch sử

Tools:
- get_stock_price(symbol): giá hiện tại + thay đổi
- get_stock_info(symbol): thông tin công ty
- get_market_overview(): top tăng/giảm/khớp lệnh nhiều
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("vn_stock")

VND_PRICE_URL = "https://finfo-api.vndirect.com.vn/v4/stock_prices"
VND_INFO_URL = "https://finfo-api.vndirect.com.vn/v4/stocks"

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _fetch_latest_price(symbol: str) -> dict[str, Any] | None:
    today = date.today()
    week_ago = today - timedelta(days=7)
    params = {
        "sort": "date",
        "size": 5,
        "page": 1,
        "q": f"code:{symbol.upper()}~date:gte:{week_ago.isoformat()}~date:lte:{today.isoformat()}",
    }
    try:
        with httpx.Client(timeout=10.0, headers=HEADERS) as client:
            r = client.get(VND_PRICE_URL, params=params)
            r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning("VND price fetch failed for %s: %s", symbol, exc)
        return None
    items = data.get("data") or []
    if not items:
        return None
    return items[0]


def _fetch_info(symbol: str) -> dict[str, Any] | None:
    params = {"q": f"code:{symbol.upper()}"}
    try:
        with httpx.Client(timeout=10.0, headers=HEADERS) as client:
            r = client.get(VND_INFO_URL, params=params)
            r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning("VND info fetch failed for %s: %s", symbol, exc)
        return None
    items = data.get("data") or []
    return items[0] if items else None


@mcp.tool()
def get_stock_price(symbol: str) -> str:
    """Lấy giá cổ phiếu Việt Nam mới nhất từ VNDirect.

    Args:
        symbol: Mã cổ phiếu HOSE/HNX/UPCOM (vd: VNM, FPT, HPG, VIC).

    Returns:
        Giá đóng cửa, % thay đổi, khối lượng giao dịch.
    """
    sym = symbol.upper().strip()
    p = _fetch_latest_price(sym)
    if not p:
        return f"Không lấy được giá cổ phiếu '{sym}'. Mã không tồn tại hoặc API lỗi."
    change = p.get("change") or 0
    pct = p.get("pctChange") or 0
    arrow = "▲" if change > 0 else ("▼" if change < 0 else "—")
    return (
        f"**{sym}** (sàn {p.get('floor', 'N/A')}) — phiên {p.get('date')}\n"
        f"- Đóng cửa: {p.get('close', 0):,.0f} VND {arrow} {change:+,.0f} ({pct:+.2f}%)\n"
        f"- Mở cửa: {p.get('open', 0):,.0f} | Cao nhất: {p.get('high', 0):,.0f} | Thấp nhất: {p.get('low', 0):,.0f}\n"
        f"- Khối lượng: {p.get('nmVolume', 0):,} cp\n"
        f"- Giá trị: {p.get('nmValue', 0):,.0f} VND"
    )


@mcp.tool()
def get_stock_info(symbol: str) -> str:
    """Lấy thông tin công ty niêm yết Việt Nam.

    Args:
        symbol: Mã cổ phiếu (vd: VNM, FPT).

    Returns:
        Tên công ty, sàn niêm yết, ngành, vốn hóa nếu có.
    """
    sym = symbol.upper().strip()
    info = _fetch_info(sym)
    if not info:
        return f"Không lấy được thông tin '{sym}'."
    lines = [f"**{sym} — {info.get('companyName', 'N/A')}**"]
    if info.get("companyNameEng"):
        lines.append(f"- Tên Anh: {info['companyNameEng']}")
    lines.extend([
        f"- Sàn: {info.get('floor', 'N/A')}",
        f"- Ngành: {info.get('industryName', 'N/A')}",
        f"- Loại: {info.get('type', 'N/A')}",
        f"- Trạng thái: {info.get('status', 'N/A')}",
    ])
    return "\n".join(lines)
