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
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("vn_currency")

VCB_RATES_URL = "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx"
SJC_URL = "https://sjc.com.vn/giavang/textContent.php"
DOJI_URL = "https://giavang.doji.vn/"
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


def _fetch_doji() -> list[dict[str, Any]]:
    """DOJI HTML scrape — gold prices by type."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
            r = client.get(DOJI_URL)
            r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as exc:
        logger.warning("DOJI fetch failed: %s", exc)
        return []
    
    tables = soup.find_all("table")
    if not tables:
        return []
    
    rows: list[dict[str, Any]] = []
    # Extract from the first table which contains the retail gold rates
    table = tables[0]
    for tr in table.find_all("tr"):
        cols = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if len(cols) < 3 or cols[0] in ("Giá vàng trong nước", "Loại"):
            continue
        rows.append({"type": cols[0], "buy": cols[1], "sell": cols[2]})
    return rows


def _fetch_btmc() -> list[dict[str, Any]]:
    """Read BTMC's current public gold table (the former API times out).

    Keep the site's displayed unit and product weight, including 0.1 coins;
    never relabel these figures as dong/tael or another dealer's quote.
    """
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get("https://btmc.vn/")
            response.raise_for_status()
        return _parse_btmc(response.text)
    except Exception as exc:
        logger.warning("BTMC fetch failed: %s", exc)
        return []


def _parse_btmc(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.bd_price_home")
    if table is None or "Loại vàng" not in table.get_text(" ", strip=True):
        return []
    # Timestamp following the GOLD table, not the independently updated silver table.
    # The timestamp is outside the immediate wrapper on the public page.
    tail = str(soup)[str(soup).find(str(table)) + len(str(table)):]
    tail = tail.split('<table', 1)[0]
    context = BeautifulSoup(tail, "html.parser").get_text(" ", strip=True)
    updated = re.search(r"Cập nhật lúc\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", context, re.I)
    unit = re.search(r"ĐVT\s*1\s*=\s*1[.,]000\s*VNĐ", context, re.I)
    if not updated or not unit:
        return []  # Unknown unit/date must not become a fabricated current quote.
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td", recursive=False)]
        if len(cells) not in (4, 5):
            continue
        name, purity, buy, sell = cells[-4:]
        if not name or not re.fullmatch(r"[\d.,]+", buy):
            continue
        if not re.fullmatch(r"[\d.,]+", sell) and not sell.startswith("Liên hệ"):
            continue
        rows.append({"type": f"{name} ({purity})", "buy": buy, "sell": sell,
                     "updated_at": updated.group(1), "unit": "1 = 1.000 VNĐ (theo sản phẩm niêm yết)"})
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
def get_gold_prices(brand: str = "all") -> str:
    """Giá vàng từ SJC, DOJI, BTMC, kèm nguồn và thời điểm khi nguồn cung cấp.

    brand: sjc | doji | btmc | all. Không suy giá PNJ từ bảng của hãng khác.
    """
    brand = brand.lower().strip()
    sources = {
        "sjc": (_fetch_sjc, SJC_URL, "nghìn đồng/lượng"),
        "doji": (_fetch_doji, DOJI_URL, "nghìn đồng/chỉ"),
        "btmc": (_fetch_btmc, "https://btmc.vn/", "theo sản phẩm niêm yết"),
    }
    if brand not in (*sources, "all"):
        return f"Không lấy được giá vàng {brand.upper()}: chưa có nguồn trực tiếp được hỗ trợ."
    lines, missing = [], []
    for name, (fetch, url, unit) in sources.items():
        if brand not in (name, "all"):
            continue
        rows = fetch()
        if not rows:
            missing.append(name.upper())
            continue
        date = rows[0].get("updated_at") or "nguồn chưa cung cấp thời điểm; cần kiểm tra độ mới"
        lines += [f"**Giá vàng {name.upper()}**", f"Cập nhật: {date}",
                  "| Loại vàng | Mua vào | Bán ra |", "|---|---:|---:|"]
        for row in rows:
            lines.append(f"| {row['type']} | {row['buy']} | {row['sell']} |")
        lines.append(f"Đơn vị: {rows[0].get('unit') or unit}. Nguồn: {url}")
    if not lines:
        return "Không lấy được thông tin giá vàng lúc này (nguồn: " + ", ".join(missing) + ")."
    if missing:
        lines.append("Chưa lấy được bảng trực tiếp từ: " + ", ".join(missing) + ".")
    return "\n".join(lines)
