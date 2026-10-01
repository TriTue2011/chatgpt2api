"""Đối chiếu HÓA ĐƠN ĐIỆN TỬ Việt Nam với bảng DANH MỤC Excel.

Chủ máy 01/10/2026: "để sau này có việc cho check thông tin với bản excel xem có đúng không. Ví dụ pdf hóa
đơn với excel danh mục". Soát GitHub cùng ngày: các repo Việt Nam đọc hóa đơn (dieutx/hddt-downloader-windows,
TaiHoaDonDienTu, KE-TOAN, vatengine) đều mới 0–3 sao và đa số không có giấy phép — không dùng lại được;
invoice2data (MIT) đọc PDF theo mẫu từng nhà phát hành, mà hóa đơn Việt Nam có hàng chục mẫu (Viettel, VNPT,
MISA, BKAV…). Nên viết thẳng ở đây:

- XML là BẢN GỐC pháp lý (Nghị định 123/2020, Thông tư 78/2021) và cùng một khuôn cho MỌI nhà cung cấp:
  ``HDon/DLHDon/TTChung`` (KHMSHDon, KHHDon, SHDon, NLap), ``NDHDon/NBan|NMua`` (Ten, MST),
  ``DSHHDVu/HHDVu`` (STT, TChat, THHDVu, DVTinh, SLuong, DGia, TLCKhau, STCKhau, ThTien, TSuat),
  ``TToan`` (TgTCThue, TgTThue, TTCKTMai, TgTTTBSo). Tìm thẻ theo TÊN ở mọi tầng, không theo đường lồng:
  tài liệu các nhà cung cấp đặt ``TToan`` không thống nhất.
- PDF chỉ là bản in → đọc qua đường trích xuất sẵn có (`pdf_intent.extract_markdown`), tìm bảng có cột tên
  hàng / số lượng / đơn giá / thành tiền. Kém chắc hơn XML; báo cáo NÓI RÕ là đọc từ PDF.

Tên cột (`_COT`) là TÊN TRƯỜNG mẫu hóa đơn bắt buộc in và cách kế toán hay đặt tên cột danh mục — từ điển
tên trường của một loại giấy tờ, không phải đoán ý người dùng.
"""

from __future__ import annotations

import difflib
import re
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

#: Lệch tiền dưới ngần này đồng là làm tròn, không phải sai.
LECH_TIEN = 1.0
#: Tên hàng gần giống ngần này trở lên (0–1) thì coi là cùng mặt hàng khi không khớp đúng.
GIONG_TEN = 0.85
#: Các mức thuế GTGT Việt Nam — danh mục lệch hóa đơn ĐÚNG một trong các tỉ lệ (1 + mức) ở mọi dòng thì danh mục
#: ghi giá đã gồm thuế, không phải nhiều lỗi rời.
THUE_GTGT = (0.05, 0.08, 0.10)
#: Hồ sơ đang chờ đủ hai tệp (hóa đơn + danh mục) sống ngần này giây.
CHO_GIAY = 1800
_DUOI_BANG = (".xlsx", ".xls", ".xlsm", ".csv")


def _gap(s: Any) -> str:
    """Chữ thường, bỏ dấu, gộp khoảng trắng — để so tên cột và tên hàng."""
    s = unicodedata.normalize("NFD", str(s or "")).replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9%]+", " ", s).strip()


def _so(x: Any) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    from services.office_bo_sung import _so as so_viet
    return so_viet(str(x))


# ── Đọc XML ─────────────────────────────────────────────────────────────────
def _ten(e: ET.Element) -> str:
    return e.tag.rsplit("}", 1)[-1]


def _mot(goc: ET.Element | None, ten: str) -> ET.Element | None:
    if goc is None:
        return None
    return next((e for e in goc.iter() if _ten(e) == ten), None)


def _chu(goc: ET.Element | None, ten: str) -> str:
    e = _mot(goc, ten)
    return (e.text or "").strip() if e is not None and e.text else ""


def doc_xml(duong: str | Path) -> dict[str, Any]:
    try:
        goc = ET.parse(str(duong)).getroot()
    except (ET.ParseError, OSError) as exc:
        return {"loi": f"không đọc được XML: {str(exc)[:120]}"}
    hh = [e for e in goc.iter() if _ten(e) == "HHDVu"]
    if not hh:
        return {"loi": "XML không có danh sách hàng hóa (DSHHDVu/HHDVu) — có phải hóa đơn theo Thông tư 78?"}
    dong = []
    for e in hh:
        dong.append({"stt": _chu(e, "STT"), "ten": _chu(e, "THHDVu"), "ma": _chu(e, "MHHDVu"),
                     "dvt": _chu(e, "DVTinh"), "sl": _so(_chu(e, "SLuong") or None),
                     "dg": _so(_chu(e, "DGia") or None), "ck": _so(_chu(e, "STCKhau") or None),
                     "tt": _so(_chu(e, "ThTien") or None), "thue_suat": _chu(e, "TSuat"),
                     "tinh_chat": _chu(e, "TChat")})
    tt = _mot(goc, "TToan")
    return {"nguon": "xml", "mau": _chu(goc, "KHMSHDon"), "ky_hieu": _chu(goc, "KHHDon"),
            "so": _chu(goc, "SHDon"), "ngay": _chu(goc, "NLap"),
            "ban": {"ten": _chu(_mot(goc, "NBan"), "Ten"), "mst": _chu(_mot(goc, "NBan"), "MST")},
            "mua": {"ten": _chu(_mot(goc, "NMua"), "Ten"), "mst": _chu(_mot(goc, "NMua"), "MST")},
            "dong": dong,
            "tong": {"chua_thue": _so(_chu(tt, "TgTCThue") or None), "thue": _so(_chu(tt, "TgTThue") or None),
                     "ck": _so(_chu(tt, "TTCKTMai") or None), "thanh_toan": _so(_chu(tt, "TgTTTBSo") or None)}}


# ── Nhận cột của bảng (PDF đã thành Markdown, hoặc Excel) ──────────────────
def _cot(tieu_de: Any) -> str | None:
    t = _gap(tieu_de)
    if not t:
        return None
    if t in ("stt", "tt") or t.startswith("so tt") or t.startswith("stt "):
        return "stt"
    if "thanh tien" in t or t.startswith("gia tri") or "thanh toan" in t:
        return "tt"
    if "don gia" in t or t in ("gia", "gia ban", "gia nhap"):
        return "dg"
    if "so luong" in t or t in ("sl", "kl", "khoi luong"):
        return "sl"
    if "don vi" in t or t == "dvt":
        return "dvt"
    if "thue suat" in t or t in ("% thue", "vat", "thue %"):
        return "thue_suat"
    if t.startswith("ma ") or t in ("ma", "ma hang", "ma vt", "ma sp"):
        return "ma"
    if ("ten" in t.split() or "hang hoa" in t or "mat hang" in t or "dien giai" in t or "san pham" in t
            or "vat tu" in t or "dich vu" in t):
        return "ten"
    return None


def _anh_xa(hang: list[Any]) -> dict[str, int]:
    """Một dòng tiêu đề → {khoá: chỉ số cột}. Cột đầu tiên khớp thắng (``tt`` = thành tiền, hay đứng sau)."""
    ra: dict[str, int] = {}
    for i, o in enumerate(hang):
        k = _cot(o)
        if k and k not in ra:
            ra[k] = i
    return ra


def _du_cot(m: dict[str, int]) -> bool:
    return "ten" in m and len({"sl", "dg", "tt"} & set(m)) >= 2


def _dong_tu_hang(m: dict[str, int], hang: list[Any]) -> dict[str, Any] | None:
    def o(k: str) -> Any:
        i = m.get(k)
        return hang[i] if i is not None and i < len(hang) else None
    ten = str(o("ten") or "").strip()
    # Tên hàng phải có chữ: dòng đánh số cột của mẫu in («1 | 2 | 3 | 4 | 5 | 6 = 4 x 5») không phải hàng.
    if not re.search(r"[^\W\d_]", ten) or ten.lower() == "nan" or _gap(ten).startswith(("cong", "tong")):
        return None
    sl, dg, tt = _so(o("sl")), _so(o("dg")), _so(o("tt"))
    if sl is None and dg is None and tt is None:
        return None
    return {"stt": str(o("stt") or "").strip(), "ten": ten, "ma": str(o("ma") or "").strip(),
            "dvt": str(o("dvt") or "").strip(), "sl": sl, "dg": dg, "tt": tt,
            "thue_suat": str(o("thue_suat") or "").strip()}


def bang_tu_markdown(md: str) -> list[dict[str, Any]]:
    """Dòng hàng từ bảng Markdown đầu tiên có đủ cột tên hàng + hai trong ba cột số lượng / đơn giá / thành
    tiền. Mẫu in hóa đơn hay có dòng đánh số cột (1, 2, 3, 4=2x3…) ngay dưới tiêu đề — bỏ qua tự nhiên vì
    không có tên hàng."""
    m: dict[str, int] | None = None
    ra: list[dict[str, Any]] = []
    for dong in md.splitlines():
        s = dong.strip()
        if not (s.startswith("|") and s.endswith("|")):
            if m is not None and ra:
                break
            continue
        o = [x.strip() for x in s.strip("|").split("|")]
        if re.fullmatch(r"[\s:|+-]*", s.replace("|", "")):
            continue
        if m is None:
            mm = _anh_xa(o)
            if _du_cot(mm):
                m = mm
            continue
        d = _dong_tu_hang(m, o)
        if d:
            ra.append(d)
    return ra


def _tu(md: str) -> list[tuple[str, str]]:
    """Chữ hóa đơn → dãy (từ gốc, từ đã gập). Bỏ dấu bảng / định dạng Markdown; một từ gốc như «AA-Energizer» hay
    «1,5» gập ra nhiều từ con, mỗi từ con mang theo từ gốc để còn đọc số đúng kiểu Việt."""
    # Thẻ định dạng bỏ KHÔNG chèn cách: bản in hay gạch chân giữa chữ («T<u>iền thuế») — chèn cách là «Tiền» thành
    # hai từ và nhãn tổng không còn khớp. Dấu cột bảng thì là ranh giới thật.
    sach = re.sub(r"\|", " ", re.sub(r"</?u>|\*+", "", md))
    ra = []
    for goc in sach.split():
        for con in _gap(goc).split():
            ra.append((goc, con))
    return ra


def _sau_nhan(tu: list[tuple[str, str]], nhan: list[str]) -> float | None:
    """Số ĐẦU TIÊN sau nhãn (vd «cộng tiền hàng») trong dãy từ."""
    con = [c for _, c in tu]
    for i in range(len(con) - len(nhan) + 1):
        if con[i:i + len(nhan)] == nhan:
            for goc, _ in tu[i + len(nhan):i + len(nhan) + 12]:
                v = _so(goc.strip(":();"))
                if v is not None:
                    return v
    return None


def _neo_theo_ten(tu: list[tuple[str, str]], ten: list[str]) -> list[dict[str, Any]]:
    """Tìm từng TÊN HÀNG (của danh mục) trong chữ hóa đơn rồi đọc đơn vị + ba số đi sau (số lượng, đơn giá, thành
    tiền). Không cần bảng trích đúng — bản in PDF hay bị dính cột, sang trang thì thành một dòng chữ liền."""
    con = [c for _, c in tu]
    da_dung: set[int] = set()
    ra = []
    for t in ten:
        mau = _gap(t).split()
        if not mau:
            continue
        i = next((i for i in range(len(con) - len(mau) + 1)
                  if i not in da_dung and con[i:i + len(mau)] == mau), None)
        if i is None:
            continue
        da_dung.add(i)
        j, goc_cuoi = i + len(mau), tu[i + len(mau) - 1][0]
        while j < len(tu) and tu[j][0] == goc_cuoi:          # từ gốc cuối của tên còn từ con chưa khớp
            j += 1
        dvt, so = "", []
        seen = None
        for goc, _ in tu[j:j + 12]:
            if goc is seen:
                continue
            seen = goc
            v = _so(goc)
            if v is None:
                if so:
                    break
                dvt = dvt or goc
                continue
            so.append(v)
            if len(so) == 3:
                break
        if len(so) == 3:
            ra.append({"stt": "", "ten": t, "ma": "", "dvt": dvt, "sl": so[0], "dg": so[1], "tt": so[2],
                       "thue_suat": ""})
    return ra


def doc_pdf(duong: str | Path, ten_goi_y: list[str] | None = None) -> dict[str, Any]:
    """PDF (bản in): bảng Markdown nếu trích được đúng; không thì — khi đang đối chiếu — neo theo tên hàng của danh
    mục. Tổng «cộng tiền hàng / thuế / thanh toán» đọc theo nhãn in bắt buộc trên hóa đơn GTGT."""
    from services import pdf_intent
    md = pdf_intent.extract_markdown(str(duong)) or ""
    tu = _tu(md)
    dong = bang_tu_markdown(md)
    cach = "bang"
    if not dong and ten_goi_y:
        dong, cach = _neo_theo_ten(tu, ten_goi_y), "neo"
    if not dong:
        return {"loi": "không tìm thấy bảng hàng hóa trong PDF (cột tên hàng, số lượng, đơn giá, thành tiền) — "
                       "gửi file XML gốc của hóa đơn sẽ chắc hơn"}
    ky = re.search(r"(?:Ký hiệu|Serial)\W+(?:\(Serial\)\W*)?:?\s*([0-9A-Z]{6,8})\b", re.sub(r"[*_]", "", md))
    return {"nguon": "pdf", "cach_doc": cach, "so": "", "ky_hieu": ky.group(1) if ky else "", "mau": "",
            "ngay": "", "ban": {}, "mua": {}, "dong": dong,
            "tong": {"chua_thue": _sau_nhan(tu, ["cong", "tien", "hang"]),
                     "thue": _sau_nhan(tu, ["tien", "thue", "gtgt"]),
                     "thanh_toan": _sau_nhan(tu, ["tong", "cong", "tien", "thanh", "toan"])}}


def doc_bang(duong: str | Path, sheet: str = "") -> dict[str, Any]:
    """Bảng danh mục Excel/CSV: tự tìm dòng tiêu đề trong 30 dòng đầu của từng sheet."""
    import pandas as pd
    p = Path(duong)
    try:
        if p.suffix.lower() == ".csv":
            bang = {"CSV": pd.read_csv(str(p), header=None, dtype=object)}
        else:
            bang = pd.read_excel(str(p), sheet_name=(sheet or None), header=None, dtype=object)
            if not isinstance(bang, dict):
                bang = {sheet or "Sheet1": bang}
    except Exception as exc:  # noqa: BLE001 — tệp người dùng gửi, hỏng kiểu gì cũng chỉ báo lại
        return {"loi": f"không đọc được bảng: {str(exc)[:150]}"}
    for ten, df in bang.items():
        hang = df.where(df.notna(), None).values.tolist()
        for i, h in enumerate(hang[:30]):
            m = _anh_xa(h)
            if _du_cot(m):
                dong = [d for d in (_dong_tu_hang(m, x) for x in hang[i + 1:]) if d]
                if dong:
                    return {"nguon": "bang", "sheet": ten, "dong": dong}
    return {"loi": "không tìm thấy dòng tiêu đề có cột tên hàng và hai trong ba cột số lượng / đơn giá / "
                   "thành tiền"}


def doc_hoa_don(duong: str | Path, ten_goi_y: list[str] | None = None) -> dict[str, Any]:
    p = Path(duong)
    if p.suffix.lower() == ".xml":
        return doc_xml(p)
    if p.suffix.lower() == ".pdf":
        return doc_pdf(p, ten_goi_y)
    return {"loi": f"hóa đơn phải là .xml (bản gốc) hoặc .pdf, không phải {p.suffix}"}


# ── Đối chiếu ───────────────────────────────────────────────────────────────
def _bang_nhau(a: float | None, b: float | None, tien: bool) -> bool:
    if a is None or b is None:
        return True                     # một bên không ghi thì không có gì để so
    return abs(a - b) <= (LECH_TIEN if tien else 1e-6 * max(1.0, abs(a)))


def _ghep(hd: list[dict[str, Any]], dm: list[dict[str, Any]]) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Cặp (dòng hóa đơn, dòng danh mục): theo MÃ nếu cả hai có, rồi tên khớp đúng, rồi tên gần giống nhất
    (≥ GIONG_TEN, mỗi dòng danh mục ghép một lần)."""
    con = set(range(len(dm)))
    cap: list[tuple[int, int]] = []
    chua: list[int] = []
    for i, d in enumerate(hd):
        j = next((j for j in con if d.get("ma") and dm[j].get("ma") and _gap(d["ma"]) == _gap(dm[j]["ma"])), None)
        if j is None:
            j = next((j for j in con if _gap(d["ten"]) == _gap(dm[j]["ten"])), None)
        if j is None:
            diem = sorted(((difflib.SequenceMatcher(None, _gap(d["ten"]), _gap(dm[j]["ten"])).ratio(), j)
                           for j in con), reverse=True)
            if diem and diem[0][0] >= GIONG_TEN:
                j = diem[0][1]
        if j is None:
            chua.append(i)
        else:
            con.discard(j)
            cap.append((i, j))
    return cap, chua, sorted(con)


def _tien(x: float | None) -> str:
    if x is None:
        return "—"
    s = f"{x:,.2f}".rstrip("0").rstrip(".")
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def kiem_phep_tinh(hd: dict[str, Any]) -> list[str]:
    """Tự kiểm hóa đơn: số lượng × đơn giá − chiết khấu = thành tiền; tổng dòng = tổng chưa thuế; chưa thuế +
    thuế = thanh toán."""
    loi = []
    for d in hd["dong"]:
        if d.get("sl") is not None and d.get("dg") is not None and d.get("tt") is not None:
            tinh = d["sl"] * d["dg"] - (d.get("ck") or 0)
            if not _bang_nhau(tinh, d["tt"], True):
                loi.append(f"«{d['ten']}»: {_tien(d['sl'])} × {_tien(d['dg'])}"
                           + (f" − {_tien(d['ck'])}" if d.get("ck") else "")
                           + f" = {_tien(tinh)}, hóa đơn ghi {_tien(d['tt'])}")
    t = hd.get("tong") or {}
    hang = [d["tt"] for d in hd["dong"] if d.get("tt") is not None and d.get("tinh_chat") not in ("3", "4")]
    if t.get("chua_thue") is not None and hang:
        # Dòng chiết khấu thương mại (TChat 3) và ghi chú (4) không cộng như hàng — so với tổng đã trừ chiết khấu.
        if not _bang_nhau(sum(hang) - (t.get("ck") or 0), t["chua_thue"], True) and \
                not _bang_nhau(sum(hang), t["chua_thue"], True):
            loi.append(f"tổng các dòng {_tien(sum(hang))} ≠ tổng chưa thuế {_tien(t['chua_thue'])}")
    if None not in (t.get("chua_thue"), t.get("thue"), t.get("thanh_toan")):
        if not _bang_nhau(t["chua_thue"] + t["thue"], t["thanh_toan"], True):
            loi.append(f"chưa thuế {_tien(t['chua_thue'])} + thuế {_tien(t['thue'])} ≠ thanh toán "
                       f"{_tien(t['thanh_toan'])}")
    return loi


def doi_chieu(hd: dict[str, Any], dm: dict[str, Any], *, ten_hd: str = "", ten_dm: str = "") -> str:
    """Báo cáo Markdown: phép tính trên hóa đơn, dòng khớp, dòng lệch (trường nào, hai bên ghi gì), dòng chỉ
    có một bên."""
    cap, chi_hd, chi_dm = _ghep(hd["dong"], dm["dong"])
    lech: list[tuple[str, str, str, str]] = []
    for i, j in cap:
        a, b = hd["dong"][i], dm["dong"][j]
        for k, nhan, tien in (("sl", "số lượng", False), ("dg", "đơn giá", True), ("tt", "thành tiền", True)):
            if not _bang_nhau(a.get(k), b.get(k), tien):
                lech.append((a["ten"], nhan, _tien(a.get(k)), _tien(b.get(k))))
        if a.get("dvt") and b.get("dvt") and _gap(a["dvt"]) != _gap(b["dvt"]):
            lech.append((a["ten"], "đơn vị", a["dvt"], b["dvt"]))
        if _gap(a["ten"]) != _gap(b["ten"]):
            lech.append((a["ten"], "tên (ghép gần đúng)", a["ten"], b["ten"]))
    ti_le = [dm["dong"][j]["dg"] / hd["dong"][i]["dg"] for i, j in cap
             if hd["dong"][i].get("dg") and dm["dong"][j].get("dg")
             and not _bang_nhau(hd["dong"][i]["dg"], dm["dong"][j]["dg"], True)]
    gom_thue = None
    if len(ti_le) >= 3 and len(ti_le) == len(cap):
        r = sorted(ti_le)[len(ti_le) // 2]
        gom_thue = next((t for t in THUE_GTGT if abs(r - 1 - t) < 0.002 and all(abs(x - r) < 0.002 for x in ti_le)),
                        None)
    so = "-".join(x for x in (hd.get("ky_hieu"), hd.get("so")) if x) or ten_hd
    ra = [f"# Đối chiếu hóa đơn {so} với {ten_dm or 'danh mục'}"]
    if hd.get("nguon") == "pdf":
        ra.append("\n⚠️ Đọc từ **PDF** (bản in) — kém chắc hơn file XML gốc; nghi ngờ thì gửi XML."
                  + (" PDF trích bảng lệch cột nên em tìm từng tên hàng của danh mục trong hóa đơn; mặt hàng "
                     "hóa đơn có mà danh mục không có thì chỉ lộ ra qua tổng tiền." if hd.get("cach_doc") == "neo"
                     else ""))
    t = hd.get("tong") or {}
    if hd.get("ban", {}).get("ten") or hd.get("ngay"):
        ra.append(f"\nNgười bán: {hd['ban'].get('ten') or '—'} (MST {hd['ban'].get('mst') or '—'}); ngày lập "
                  f"{hd.get('ngay') or '—'}.")
    if any(t.get(k) is not None for k in ("chua_thue", "thue", "thanh_toan")):
        ra.append(f"\nTiền hàng {_tien(t.get('chua_thue'))} + thuế {_tien(t.get('thue'))} = thanh toán "
                  f"{_tien(t.get('thanh_toan'))}; danh mục cộng {_tien(sum(d['tt'] for d in dm['dong'] if d.get('tt')))}.")
    pt = kiem_phep_tinh(hd)
    ra.append("\n## Phép tính trên hóa đơn\n" + ("\n".join(f"- ❌ {x}" for x in pt) if pt else "- ✅ đúng"))
    ra.append(f"\n## Kết quả\n- Hóa đơn {len(hd['dong'])} dòng, danh mục {len(dm['dong'])} dòng; ghép được "
              f"{len(cap)} cặp, {len({x[0] for x in lech})} mặt hàng có lệch.")
    if gom_thue is not None:
        ra.append(f"\n💡 Mọi đơn giá trong danh mục đều bằng giá hóa đơn × {_tien(1 + gom_thue)} — danh mục ghi giá ĐÃ GỒM "
                  f"thuế GTGT {round(gom_thue * 100)}%, hóa đơn ghi giá CHƯA thuế. Nếu đúng ý đó thì không có lệch "
                  "nào khác về giá; bảng dưới chỉ để đối chiếu từng dòng.")
    if lech:
        ra.append("\n| Mặt hàng | Trường | Hóa đơn | Danh mục |\n|---|---|---|---|")
        ra += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in lech]
    if chi_hd:
        ra.append("\n**Chỉ có trên hóa đơn:** " + "; ".join(hd["dong"][i]["ten"] for i in chi_hd))
    if chi_dm:
        ra.append("\n**Chỉ có trong danh mục:** " + "; ".join(dm["dong"][j]["ten"] for j in chi_dm))
    if not (pt or lech or chi_hd or chi_dm):
        ra.append("\n✅ Hóa đơn khớp danh mục.")
    return "\n".join(ra)


def doi_chieu_tep(tep_hoa_don: str | Path, tep_danh_muc: str | Path, sheet: str = "") -> dict[str, Any]:
    dm = doc_bang(tep_danh_muc, sheet)
    if dm.get("loi"):
        return {"ok": False, "error": f"danh mục: {dm['loi']}"}
    hd = doc_hoa_don(tep_hoa_don, [d["ten"] for d in dm["dong"]])
    if hd.get("loi"):
        return {"ok": False, "error": f"hóa đơn: {hd['loi']}"}
    return {"ok": True, "bao_cao": doi_chieu(hd, dm, ten_hd=Path(tep_hoa_don).name, ten_dm=Path(tep_danh_muc).name)}


# ── Nhận tệp qua chat: gom đủ hóa đơn + danh mục rồi tự đối chiếu ─────────
_ho_so: dict[str, dict[str, Any]] = {}
_khoa = threading.Lock()


def la_bang(ten: str) -> bool:
    return str(ten or "").lower().endswith(_DUOI_BANG)


def _vai(ten: str) -> str:
    return "danh_muc" if la_bang(ten) else "hoa_don"


def dang_cho(khoa: str, ten: str) -> bool:
    """Người này đã chọn «Đối chiếu hóa đơn» cho MỘT tệp (còn hạn) và ``ten`` đúng là tệp còn thiếu → kênh chuyển
    thẳng vào đây, không hiện menu lần nữa (chủ máy 01/10/2026: "gửi 1 file trước … rồi gửi file 2 là xong")."""
    if not (la_bang(ten) or str(ten or "").lower().endswith((".pdf", ".xml"))):
        return False
    with _khoa:
        hs = _ho_so.get(str(khoa))
        return bool(hs) and time.time() - hs["luc"] <= CHO_GIAY and _vai(ten) not in hs


def nhan_tep(khoa: str, duong: str, ten: str) -> str:
    return nhan_du_lieu(khoa, Path(duong).read_bytes(), ten)


def nhan_du_lieu(khoa: str, du_lieu: bytes, ten: str) -> str:
    """Người dùng chọn «Đối chiếu hóa đơn» cho một tệp: lưu vào thư mục làm việc (công cụ
    `office_doi_chieu_hoa_don` đọc lại được), ghi vào hồ sơ của người đó; đủ hai tệp thì đối chiếu luôn."""
    from services.agent import luu_tru_day
    tep = luu_tru_day.luu_vao_thu_muc_lam_viec(ten, du_lieu)
    vai = _vai(ten)
    with _khoa:
        for k in [k for k, v in _ho_so.items() if time.time() - v["luc"] > CHO_GIAY]:
            _ho_so.pop(k, None)
        hs = _ho_so.setdefault(str(khoa), {"luc": time.time()})
        hs[vai], hs["luc"] = tep, time.time()
        du = "hoa_don" in hs and "danh_muc" in hs
        if du:
            _ho_so.pop(str(khoa), None)
    if not du:
        con = "file Excel danh mục" if vai == "hoa_don" else "hóa đơn (file XML gốc, hoặc PDF)"
        return (f"🧾 Đã nhận {'hóa đơn' if vai == 'hoa_don' else 'danh mục'}: {Path(tep).name}.\n"
                f"Gửi tiếp {con} trong {CHO_GIAY // 60} phút — em đối chiếu luôn, không hỏi lại.")
    kq = doi_chieu_tep(hs["hoa_don"], hs["danh_muc"])
    return kq["bao_cao"] if kq["ok"] else f"Không đối chiếu được — {kq['error']}."


def _reset_for_tests() -> None:
    with _khoa:
        _ho_so.clear()
