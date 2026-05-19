"""vn_currency — tỷ giá ngoại tệ và giá vàng Việt Nam.

Sources:
- Vietcombank: portal.vietcombank.com.vn (XML rate feed)
- SJC: sjc.com.vn (HTML scrape gold prices)
- ExchangeRate-API: open.er-api.com (cross-currency fallback)

Tools:
- get_exchange_rate(base, quote): tỷ giá 2 đồng tiền
- get_vcb_rates(): toàn bộ tỷ giá Vietcombank
- get_gold_prices(): giá vàng SJC theo loại
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("vn_currency")

VCB_RATES_URL = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"
SJC_URL = "https://sjc.com.vn/giavang/textContent.php"
EXR_URL = "https://open.er-api.com/v6/latest/{base}"


def _fetch_vcb() -> list[dict[str, Any]]:
    """Vietcombank XML feed — list of {currency, name, buy, sell, transfer}."""
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            r = client.get(VCB_RATES_URL)
            r.raise_for_status()
        soup = BeautifulSoup(r.text, "xml")
    except Exception as exc:
        logger.warning("VCB fetch failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for ex in soup.find_all("Exrate"):
        out.append({
            "currency": (ex.get("CurrencyCode") or "").strip(),
            "name": (ex.get("CurrencyName") or "").strip(),
            "buy": (ex.get("Buy") or "").strip(),
            "transfer": (ex.get("Transfer") or "").strip(),
            "sell": (ex.get("Sell") or "").strip(),
        })
    return out


def _fetch_sjc() -> list[dict[str, Any]]:
    """SJC HTML scrape — gold prices by type."""
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            r = client.get(SJC_URL)
            r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as exc:
        logger.warning("SJC fetch failed: %s", exc)
        return []
    rows: list[dict[str, Any]] = []
    for tr in soup.find_all("tr"):
        cols = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if len(cols) < 3:
            continue
        rows.append({"type": cols[0], "buy": cols[1], "sell": cols[2]})
    return rows


def _fetch_er(base: str = "USD") -> dict[str, float]:
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(EXR_URL.format(base=base.upper()))
            r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.warning("ExchangeRate API failed: %s", exc)
        return {}
    if data.get("result") != "success":
        return {}
    return {k: float(v) for k, v in (data.get("rates") or {}).items()}


@mcp.tool()
def get_vcb_rates() -> str:
    """Lấy toàn bộ tỷ giá hối đoái Vietcombank (VND) cho các ngoại tệ.

    Returns:
        Bảng tỷ giá USD, EUR, JPY, CNY, GBP, AUD, KRW, etc. với giá mua tiền mặt,
        chuyển khoản, và bán.
    """
    rates = _fetch_vcb()
    if not rates:
        return "Không lấy được tỷ giá Vietcombank lúc này."
    lines = ["**Tỷ giá Vietcombank (VND):**", "", "| Mã | Tên | Mua TM | Mua CK | Bán |", "|---|---|---:|---:|---:|"]
    for r in rates:
        lines.append(f"| {r['currency']} | {r['name']} | {r['buy']} | {r['transfer']} | {r['sell']} |")
    return "\n".join(lines)


@mcp.tool()
def get_exchange_rate(base: str = "USD", quote: str = "VND") -> str:
    """Lấy tỷ giá giữa 2 loại tiền tệ.

    Args:
        base: Mã tiền nguồn (vd: USD, EUR). Mặc định USD.
        quote: Mã tiền đích (vd: VND, JPY). Mặc định VND.

    Returns:
        Tỷ giá hiện tại từ ExchangeRate-API. Cho cặp X-VND, ưu tiên Vietcombank.
    """
    base = base.upper().strip()
    quote = quote.upper().strip()
    if quote == "VND":
        rates = _fetch_vcb()
        for r in rates:
            if r["currency"] == base:
                return (
                    f"**1 {base} = ? VND (Vietcombank)**\n"
                    f"- Mua tiền mặt: {r['buy']}\n"
                    f"- Mua chuyển khoản: {r['transfer']}\n"
                    f"- Bán: {r['sell']}"
                )
    rates_map = _fetch_er(base)
    if quote in rates_map:
        return f"1 {base} = {rates_map[quote]:,.4f} {quote} (ExchangeRate-API)"
    return f"Không lấy được tỷ giá {base}/{quote}."


@mcp.tool()
def get_gold_prices() -> str:
    """Lấy giá vàng SJC hôm nay tại Việt Nam.

    Returns:
        Bảng giá vàng SJC theo loại (vàng miếng, vàng nhẫn, etc.) với giá mua/bán
        đơn vị nghìn đồng/lượng.
    """
    rows = _fetch_sjc()
    if not rows:
        return "Không lấy được giá vàng SJC lúc này."
    lines = ["**Giá vàng SJC hôm nay:**", "", "| Loại vàng | Mua | Bán |", "|---|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['type']} | {r['buy']} | {r['sell']} |")
    lines.append("\n_Đơn vị: nghìn đồng/lượng. Nguồn: sjc.com.vn_")
    return "\n".join(lines)
