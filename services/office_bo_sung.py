"""Bốn việc tài liệu mà `officecli` chưa làm được — soi từ repo Quiz99/officeCliMCP.

Vì sao KHÔNG cắm repo đó vào làm một máy chủ MCP riêng
------------------------------------------------------
`officeCliMCP` là một máy chủ MCP độc lập, viết sẵn để chạy cạnh dự án này (mã của
nó có đoạn ánh xạ `/app/data/images/docs/` sang `/app/data/c2a-docs`). Nhưng 19
trong 23 tool của nó trùng việc với thứ đã có ở đây:

    read_document/read_sheet/read_slides  ≈ officecli view/get + extract_markdown
    extract_images                        ≈ pdf_images.extract_office_images
    insert_content/delete_content         ≈ officecli add / remove
    edit_sheet                            ≈ officecli set
    create_document                       ≈ officecli create
    convert_document                      ≈ pdf_to_word / pdf_to_excel / markitdown
    summarize_document                    ≈ pdf_intent.summarize_pdf
    list_files                            ≈ officecli list_files

Dựng thêm một tiến trình, một cổng, một bộ phụ thuộc để lấy 4 việc còn lại là đắt;
và mỗi tool MCP còn tốn context MỖI LƯỢT chat (xem ghi chú `skills.py` trong
CLAUDE.md). Nên chỉ bù đúng 4 việc thiếu, viết thẳng vào đây.

Chỗ bản này LÀM KHÁC repo, có lý do
------------------------------------
1. **Khoá trong thư mục làm việc.** `_resolve_path` của repo chỉ ghép tiền tố rồi
   ánh xạ vài đường dẫn, KHÔNG kiểm gì — `diff_documents("/etc/passwd", …)` là đọc
   được tệp đó. Ở đây dùng `officecli.resolve_path`, nó `resolve()` rồi đòi đường
   dẫn phải nằm trong workspace, nên `..` và symlink đều không lách được. Bot đọc
   tài liệu người lạ gửi tới, mà tài liệu có thể chứa câu ra lệnh.
2. **Đọc tài liệu bằng đường sẵn có.** Repo đọc .docx bằng cách nối `p.text` của
   từng paragraph — MẤT HẾT bảng. Ở đây gọi `pdf_intent.extract_markdown`
   (pdf-inspector → PyMuPDF → markitdown) nên bảng còn nguyên, và PDF scan còn
   được OCR. So sánh hai bản hợp đồng mà rơi mất bảng thì so sánh để làm gì.
3. **Không raise ra ngoài.** Mọi hàm trả `{ok, ...}`; đây là việc phụ của luồng
   chat, hỏng thì báo lại chứ không được làm gãy lượt trả lời.
"""
from __future__ import annotations

import difflib
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Trần độ dài báo cáo trả về bot. Vượt trần thì cắt và NÓI LÀ ĐÃ CẮT — cắt âm
#: thầm là thứ đã làm mất cả buổi để lần ra ở `ask_choices`.
MAX_KY_TU = 12000


def _duong_dan(p: str) -> Path:
    from services import officecli
    return officecli.resolve_path(p, must_exist=True)


def _doc_chu(p: Path) -> str:
    """Tài liệu → chữ, giữ bảng. Dùng đúng đường trích xuất của dự án."""
    duoi = p.suffix.lower()
    if duoi in {".md", ".txt", ".csv", ".json"}:
        return p.read_text("utf-8", errors="ignore")
    from services import pdf_intent
    return pdf_intent.extract_markdown(str(p)) or ""


def _cat(s: str) -> tuple[str, bool]:
    return (s[:MAX_KY_TU], True) if len(s) > MAX_KY_TU else (s, False)


# ── 1. So sánh hai tài liệu ─────────────────────────────────────────────────

def so_sanh(tep_a: str, tep_b: str, *, dinh_dang: str = "markdown") -> dict[str, Any]:
    """So hai tài liệu, trả báo cáo khác biệt. dinh_dang: markdown | unified."""
    try:
        a, b = _duong_dan(tep_a), _duong_dan(tep_b)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    try:
        ta, tb = _doc_chu(a), _doc_chu(b)
    except Exception as exc:
        return {"ok": False, "error": f"không đọc được nội dung: {str(exc)[:150]}"}

    da, db = ta.splitlines(), tb.splitlines()
    if da == db:
        return {"ok": True, "giong_nhau": True,
                "bao_cao": f"✅ {a.name} và {b.name} giống nhau.",
                "them": 0, "bo": 0, "sua": 0}

    if dinh_dang == "unified":
        bc = "\n".join(difflib.unified_diff(da, db, fromfile=a.name, tofile=b.name,
                                            lineterm=""))
        them = sum(1 for d in bc.splitlines() if d.startswith("+") and not d.startswith("+++"))
        bo = sum(1 for d in bc.splitlines() if d.startswith("-") and not d.startswith("---"))
        bc, bi_cat = _cat(bc)
        return {"ok": True, "giong_nhau": False, "bao_cao": bc,
                "them": them, "bo": bo, "sua": 0, "bi_cat": bi_cat}

    them = bo = sua = 0
    khoi: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, da, db).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            sua += 1
            khoi.append(f"\n**🔄 Sửa (dòng {i1 + 1})**\n")
            khoi += [f"- {x}" for x in da[i1:i2]]
            khoi += [f"+ {x}" for x in db[j1:j2]]
        elif tag == "delete":
            bo += i2 - i1
            khoi.append(f"\n**❌ Bỏ (dòng {i1 + 1})**\n")
            khoi += [f"- {x}" for x in da[i1:i2]]
        elif tag == "insert":
            them += j2 - j1
            khoi.append(f"\n**✅ Thêm (dòng {j1 + 1})**\n")
            khoi += [f"+ {x}" for x in db[j1:j2]]
    dau = (f"# So sánh {a.name} ↔ {b.name}\n\n"
           f"- Thêm: {them} dòng\n- Bỏ: {bo} dòng\n- Sửa: {sua} khối\n")
    bc, bi_cat = _cat(dau + "\n".join(khoi))
    return {"ok": True, "giong_nhau": False, "bao_cao": bc,
            "them": them, "bo": bo, "sua": sua, "bi_cat": bi_cat}


# ── 2. Thống kê bảng Excel ──────────────────────────────────────────────────

def thong_ke_bang(tep: str, *, sheet: str = "") -> dict[str, Any]:
    """Thống kê nhanh một bảng tính: số dòng/cột, thiếu dữ liệu, min/max/trung bình."""
    try:
        p = _duong_dan(tep)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    if p.suffix.lower() not in {".xlsx", ".xls", ".xlsm", ".csv"}:
        return {"ok": False, "error": f"chỉ thống kê được bảng tính, không phải {p.suffix}"}
    try:
        import pandas as pd
        if p.suffix.lower() == ".csv":
            bang = {"CSV": pd.read_csv(str(p))}
        else:
            bang = pd.read_excel(str(p), sheet_name=(sheet or None))
            if not isinstance(bang, dict):
                bang = {sheet or "Sheet1": bang}
    except Exception as exc:
        return {"ok": False, "error": f"không đọc được bảng: {str(exc)[:150]}"}

    dong: list[str] = [f"# Thống kê {p.name}"]
    tong_dong = 0
    for ten, df in bang.items():
        if df is None or df.empty:
            dong.append(f"\n## {ten}\n(trống)")
            continue
        tong_dong += len(df)
        dong.append(f"\n## {ten}\n\n{len(df)} dòng × {len(df.columns)} cột")
        thieu = {c: int(df[c].isna().sum()) for c in df.columns if df[c].isna().any()}
        if thieu:
            dong.append("\n**Thiếu dữ liệu:** "
                        + ", ".join(f"{c} ({n})" for c, n in thieu.items()))
        so = df.select_dtypes("number")
        if not so.empty:
            dong.append("\n| Cột | Nhỏ nhất | Lớn nhất | Trung bình | Tổng |")
            dong.append("|---|---|---|---|---|")
            for c in so.columns:
                v = so[c].dropna()
                if v.empty:
                    continue
                dong.append(f"| {c} | {v.min():g} | {v.max():g} | "
                            f"{v.mean():.2f} | {v.sum():g} |")
        chu = [c for c in df.columns if c not in so.columns]
        for c in chu[:3]:      # ba cột chữ đầu, đủ để nhận ra dữ liệu là gì
            top = df[c].astype(str).value_counts().head(3)
            if len(top):
                dong.append(f"\n**{c}** hay gặp: "
                            + ", ".join(f"{k} ({v})" for k, v in top.items()))
    bc, bi_cat = _cat("\n".join(dong))
    return {"ok": True, "bao_cao": bc, "so_sheet": len(bang),
            "tong_dong": tong_dong, "bi_cat": bi_cat}


# ── 3. Tìm & thay thế toàn tài liệu ────────────────────────────────────────
# `officecli set` chỉ sửa được ĐÚNG một phần tử đã biết đường dẫn. Muốn đổi một
# cụm từ nằm rải khắp tài liệu thì phải tra từng chỗ — việc thường gặp nhất
# (đổi tên, đổi năm học) lại là việc khó nhất.

def tim_thay_the(tep: str, tim: str, thay: str, *,
                 tat_ca: bool = True) -> dict[str, Any]:
    """Đổi `tim` thành `thay` trong .docx / .xlsx. Ghi thẳng vào tệp đó."""
    if not str(tim or ""):
        return {"ok": False, "error": "chưa cho biết cần tìm cụm gì"}
    try:
        p = _duong_dan(tep)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    duoi = p.suffix.lower()
    try:
        if duoi == ".docx":
            n = _thay_docx(p, tim, thay, tat_ca)
        elif duoi in {".xlsx", ".xlsm"}:
            n = _thay_xlsx(p, tim, thay, tat_ca)
        else:
            return {"ok": False, "error": f"chỉ đổi được .docx và .xlsx, không phải {duoi}"}
    except Exception as exc:
        logger.warning("tim_thay_the %s lỗi: %s", p.name, str(exc)[:150])
        return {"ok": False, "error": f"không sửa được: {str(exc)[:150]}"}
    if not n:
        return {"ok": True, "so_lan": 0,
                "text": f"Không thấy “{tim}” trong {p.name} ạ."}
    return {"ok": True, "so_lan": n,
            "text": f"Đã đổi {n} chỗ trong {p.name} ạ."}


def _thay_trong_doan(doan: Any, tim: str, thay: str, con_lai: list[int]) -> int:
    """Đổi trong một paragraph, GIỮ ĐỊNH DẠNG của run đầu tiên khớp.

    Vì sao không gán thẳng `doan.text = ...`: làm thế là xoá sạch mọi run, tức
    mất hết đậm/nghiêng/màu của cả đoạn. Ở đây chỉ sửa text của từng run.
    """
    if tim not in doan.text:
        return 0
    dem = 0
    for run in doan.runs:
        if tim not in run.text or con_lai[0] == 0:
            continue
        if con_lai[0] < 0:                       # -1 = đổi tất cả
            so = run.text.count(tim)
            run.text = run.text.replace(tim, thay)
        else:
            so = min(run.text.count(tim), con_lai[0])
            run.text = run.text.replace(tim, thay, so)
            con_lai[0] -= so
        dem += so
    # Cụm bị cắt ngang giữa hai run thì vòng trên không thấy. Gộp cả đoạn vào
    # run đầu — mất định dạng riêng của các run sau, nhưng đúng nội dung; thà
    # vậy còn hơn im lặng không đổi gì.
    if dem == 0 and doan.runs:
        doan.runs[0].text = doan.text.replace(tim, thay)
        for r in doan.runs[1:]:
            r.text = ""
        dem = doan.text.count(tim) or 1
    return dem


def _thay_docx(p: Path, tim: str, thay: str, tat_ca: bool) -> int:
    import docx
    d = docx.Document(str(p))
    con_lai = [-1 if tat_ca else 1]
    dem = 0
    for doan in d.paragraphs:
        dem += _thay_trong_doan(doan, tim, thay, con_lai)
        if con_lai[0] == 0:
            break
    if con_lai[0] != 0:
        for bang in d.tables:          # bảng: repo bỏ qua hoàn toàn
            for hang in bang.rows:
                for o in hang.cells:
                    for doan in o.paragraphs:
                        dem += _thay_trong_doan(doan, tim, thay, con_lai)
    if dem:
        d.save(str(p))
    return dem


def _thay_xlsx(p: Path, tim: str, thay: str, tat_ca: bool) -> int:
    import openpyxl
    wb = openpyxl.load_workbook(str(p))
    dem = 0
    for ws in wb.worksheets:
        for hang in ws.iter_rows():
            for o in hang:
                if isinstance(o.value, str) and tim in o.value:
                    so = o.value.count(tim)
                    o.value = o.value.replace(tim, thay) if tat_ca \
                        else o.value.replace(tim, thay, 1)
                    dem += so if tat_ca else 1
                    if not tat_ca:
                        wb.save(str(p))
                        return dem
    if dem:
        wb.save(str(p))
    return dem


# ── 4. Tạo slide PowerPoint từ dàn ý ───────────────────────────────────────
# Dự án chưa tạo được .pptx ở bất kỳ đâu (soi cả `services/`: không nơi nào
# import pptx để GHI). Với đường dạy học thì đây là việc đáng có nhất trong repo.

_RE_TIEU_DE = re.compile(r"^(#{1,3})\s+(.*)$")
_RE_GACH_DAU = re.compile(r"^\s*[-*•]\s+(.*)$")


def tao_slide(dan_y: str, ten_tep: str) -> dict[str, Any]:
    """Dàn ý Markdown → .pptx. Mỗi tiêu đề `#`/`##` là một slide, gạch đầu dòng
    là các ý trong slide đó."""
    noi_dung = str(dan_y or "").strip()
    if not noi_dung:
        return {"ok": False, "error": "chưa có dàn ý"}
    ten = re.sub(r"[^\w.() \-]+", "_", Path(str(ten_tep or "")).name).strip()
    if not ten:
        ten = "slide.pptx"
    if not ten.lower().endswith(".pptx"):
        ten += ".pptx"
    try:
        from services import officecli
        p = officecli.resolve_path(ten)
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}

    cac_slide: list[tuple[str, list[str]]] = []
    for dong in noi_dung.splitlines():
        m = _RE_TIEU_DE.match(dong.strip())
        if m:
            cac_slide.append((m.group(2).strip(), []))
            continue
        g = _RE_GACH_DAU.match(dong)
        y = (g.group(1) if g else dong).strip()
        if not y:
            continue
        if not cac_slide:                 # chữ trước tiêu đề đầu → slide mở đầu
            cac_slide.append(("", []))
        cac_slide[-1][1].append(y)
    if not cac_slide:
        return {"ok": False, "error": "dàn ý không có tiêu đề hay ý nào"}

    try:
        from pptx import Presentation
        from pptx.util import Pt
        pres = Presentation()
        for tieu_de, cac_y in cac_slide:
            bo_cuc = pres.slide_layouts[1 if cac_y else 5]
            s = pres.slides.add_slide(bo_cuc)
            s.shapes.title.text = tieu_de or " "
            if not cac_y:
                continue
            khung = None
            for ph in s.placeholders:
                if ph.placeholder_format.idx != 0:
                    khung = ph.text_frame
                    break
            if khung is None:
                continue
            khung.text = cac_y[0]
            for y in cac_y[1:]:
                khung.add_paragraph().text = y
            for doan in khung.paragraphs:
                for r in doan.runs:
                    r.font.size = Pt(20)
        p.parent.mkdir(parents=True, exist_ok=True)
        pres.save(str(p))
    except Exception as exc:
        logger.warning("tao_slide %s lỗi: %s", ten, str(exc)[:150])
        return {"ok": False, "error": f"không tạo được slide: {str(exc)[:150]}"}
    return {"ok": True, "duong_dan": str(p), "ten": p.name,
            "so_slide": len(cac_slide)}
