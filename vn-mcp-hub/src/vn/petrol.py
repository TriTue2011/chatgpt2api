"""vn_petrol — giá xăng dầu bán lẻ Petrolimex.

Nguồn CHÍNH: trang chủ petrolimex.com.vn mở bằng Chrome không giao diện (bảng giá dựng bằng JS, đọc đúng thứ người
xem thấy — không gọi API mã hoá của họ). Nguồn PHỤ: webgia.com (bản chép HTML tĩnh).

Chủ máy 06/10/2026 (ảnh trang Petrolimex 15:00 1/10: «E10 RON 95 Mức 5 28.180…»): bot báo «RON 95 chưa có dữ
liệu», E5 26.390 — webgia đứng ở 14:02 1/10, không theo kịp lần Petrolimex đổi tên sản phẩm (E10 RON 95 Mức 5/3,
E5 RON 92 Mức 2, DO Mức 5/2) nên hiện «-» và giá cũ. Nguồn phụ thì phải ghi rõ là nguồn phụ.

Tools:
- get_petrol_prices(region="all"): bảng giá hiện tại theo Vùng 1 / Vùng 2
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx
from bs4 import BeautifulSoup
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("vn_petrol")

PETROL_URL = "https://webgia.com/gia-xang-dau/petrolimex/"
PETROLIMEX_URL = "https://www.petrolimex.com.vn/"
#: Mở trang mất ~12 s — đệm kết quả; Petrolimex đổi giá theo kỳ điều hành (vài ngày một lần).
DEM_GIAY = 30 * 60
_dem: dict[str, Any] = {"luc": 0.0, "data": None}
_GIA_RE = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _fetch_petrol() -> dict[str, Any]:
    """Scrape the Petrolimex retail price table from webgia.com.

    Returns dict with `updated_at` and `rows` = list of
    {product, vung_1, vung_2} entries.
    """
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            r = client.get(PETROL_URL, headers={"User-Agent": UA})
            r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as exc:
        logger.warning("Petrol fetch failed: %s", exc)
        return {"updated_at": "", "rows": []}

    # The first .table with thead "Sản phẩm | Vùng 1 | Vùng 2" is the retail
    # table. Other tables on the page are historical-change rows we don't want.
    rows: list[dict[str, str]] = []
    for table in soup.find_all("table"):
        thead = table.find("thead")
        if not thead or "Sản phẩm" not in thead.get_text():
            continue
        body = table.find("tbody")
        if not body:
            continue
        for tr in body.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) < 3:
                continue
            product = cells[0].get_text(strip=True)
            v1 = cells[1].get_text(strip=True)
            v2 = cells[2].get_text(strip=True)
            if product and v1:
                rows.append({"product": product, "vung_1": v1, "vung_2": v2})
        if rows:
            break  # first matching table is the current retail board

    # Updated-at is in the <h1><small> tag.
    updated_at = ""
    h1 = soup.find("h1")
    if h1:
        small = h1.find("small")
        if small:
            updated_at = small.get_text(strip=True).lstrip("- ").strip()

    return {"updated_at": updated_at, "rows": rows}


def doc_bang_petrolimex(chu: str) -> dict[str, Any]:
    """Chữ hiển thị của khối «Giá bán lẻ xăng dầu» → {updated_at, rows}. Mỗi sản phẩm là một dòng chữ theo sau bởi
    hai dòng số (Vùng 1, Vùng 2); dừng ở «đơn vị». Không nhận ra được thì rows rỗng."""
    dong = [d.strip() for d in str(chu or "").splitlines() if d.strip()]
    rows: list[dict[str, str]] = []
    try:
        dau = next(i for i, d in enumerate(dong) if d.startswith("Vùng 2")) + 1
    except StopIteration:
        return {"updated_at": "", "rows": []}
    i = dau
    while i + 2 < len(dong) and "đơn vị" not in dong[i].lower():
        if not _GIA_RE.match(dong[i]) and _GIA_RE.match(dong[i + 1]) and _GIA_RE.match(dong[i + 2]):
            rows.append({"product": dong[i], "vung_1": dong[i + 1], "vung_2": dong[i + 2]})
            i += 3
        else:
            i += 1
    m = re.search(r"cập nhật lúc\s*([0-9]{1,2}:[0-9]{2}\s*-\s*[0-9/]+)", " ".join(dong), re.IGNORECASE)
    return {"updated_at": m.group(1) if m else "", "rows": rows}


def _fetch_petrolimex() -> dict[str, Any]:
    """Mở trang chủ Petrolimex bằng Chrome không giao diện, đọc chữ của khối bảng giá. Hỏng thì rows rỗng."""
    try:
        import asyncio

        from playwright.async_api import async_playwright

        async def _doc() -> str:
            async with async_playwright() as p:
                b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
                try:
                    pg = await b.new_page(locale="vi-VN")
                    await pg.goto(PETROLIMEX_URL, wait_until="networkidle", timeout=45000)
                    # Bảng nằm trong ô thả xuống đang ĐÓNG: innerText rỗng (đo 06/10/2026) — đọc textContent từng
                    # ô của từng dòng, mỗi ô một dòng chữ; mốc «cập nhật lúc …» lấy từ khối bao ngoài.
                    return await pg.evaluate(
                        """() => { const all = Array.from(document.querySelectorAll('div,section,table'));
                        const hop = all.filter(e => e.textContent.includes('Vùng 1')
                            && e.textContent.toLowerCase().includes('đơn vị'));
                        hop.sort((a, b) => a.textContent.length - b.textContent.length);
                        if (!hop.length) return '';
                        const o = (c) => c.children.length ? Array.from(c.children).map(o).flat()
                                                           : [c.textContent.replace(/\\s+/g, ' ').trim()];
                        const dong = o(hop[0]).filter(Boolean);
                        let bao = hop[0];
                        while (bao && !/cập nhật lúc/i.test(bao.textContent)) bao = bao.parentElement;
                        const moc = bao ? (bao.textContent.match(/cập nhật lúc[^0-9]*[0-9]{1,2}:[0-9]{2}\\s*-\\s*[0-9/]+/i) || [''])[0] : '';
                        return dong.join('\\n') + '\\n' + moc; }""")
                finally:
                    await b.close()

        return doc_bang_petrolimex(asyncio.run(_doc()))
    except Exception as exc:  # noqa: BLE001 — nguồn chính hỏng thì lùi nguồn phụ
        logger.warning("Petrolimex render failed: %s", exc)
        return {"updated_at": "", "rows": []}


def _lay_bang() -> dict[str, Any]:
    """Bảng giá: Petrolimex (đệm DEM_GIAY), hỏng thì webgia — đánh dấu ``nguon`` để câu trả lời nói rõ."""
    if _dem["data"] and time.time() - _dem["luc"] < DEM_GIAY:
        return _dem["data"]
    data = _fetch_petrolimex()
    if data.get("rows"):
        data["nguon"] = "petrolimex"
        _dem.update(luc=time.time(), data=data)
        return data
    data = _fetch_petrol()
    data["nguon"] = "webgia"
    return data


@mcp.tool()
def get_petrol_prices(region: str = "all") -> str:
    """Lấy giá bán lẻ xăng dầu Petrolimex hôm nay (Vùng 1 và Vùng 2).

    Args:
        region: "vung1" / "vung2" / "all" (mặc định). Vùng 1 áp dụng cho
            các đô thị lớn (Hà Nội, TP.HCM, Đà Nẵng, Cần Thơ...); Vùng 2
            cao hơn ~500-600đ/lít cho các tỉnh vùng sâu vùng xa.

    Returns:
        Bảng giá Markdown đúng tên sản phẩm Petrolimex đang niêm yết (vd Xăng E10 RON 95 Mức 5/3, E5 RON 92
        Mức 2, DO 0,001S Mức 5, DO 0,05S Mức 2, Dầu hỏa 2-K) kèm mốc cập nhật. Đơn vị đồng/lít. Nguồn
        petrolimex.com.vn; lùi webgia.com thì ghi rõ «Nguồn PHỤ».
    """
    region = region.lower().strip()
    data = _lay_bang()
    rows = data.get("rows") or []
    if not rows:
        return "Không lấy được bảng giá xăng dầu Petrolimex lúc này."

    lines = [f"**Giá bán lẻ xăng dầu Petrolimex — cập nhật {data.get('updated_at') or 'mới nhất'}:**", ""]
    if region in ("vung1", "vung_1", "1"):
        lines.append("| Sản phẩm | Vùng 1 (đồng) |")
        lines.append("|---|---:|")
        for r in rows:
            lines.append(f"| {r['product']} | {r['vung_1']} |")
    elif region in ("vung2", "vung_2", "2"):
        lines.append("| Sản phẩm | Vùng 2 (đồng) |")
        lines.append("|---|---:|")
        for r in rows:
            lines.append(f"| {r['product']} | {r['vung_2']} |")
    else:
        lines.append("| Sản phẩm | Vùng 1 | Vùng 2 |")
        lines.append("|---|---:|---:|")
        for r in rows:
            lines.append(f"| {r['product']} | {r['vung_1']} | {r['vung_2']} |")

    lines.append("")
    lines.append("_Vùng 1 = đô thị lớn; Vùng 2 = vùng sâu vùng xa (cao hơn ~500-600đ/lít)._")
    if data.get("nguon") == "petrolimex":
        lines.append("_Nguồn: petrolimex.com.vn (bảng giá bán lẻ trên trang chủ)._")
    else:
        lines.append("_Nguồn PHỤ: webgia.com (bản chép) — trang Petrolimex không đọc được lúc này; bảng có thể CŨ, "
                     "nói rõ mốc cập nhật với người hỏi._")
    return "\n".join(lines)
