"""Tám việc tài liệu mà `officecli` chưa làm được — soi từ repo Quiz99/officeCliMCP.

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

Dựng thêm một tiến trình, một cổng, một bộ phụ thuộc là đắt; và mỗi tool MCP còn
tốn context MỖI LƯỢT chat (xem ghi chú `skills.py` trong CLAUDE.md). Nên bù đúng
những việc thiếu, viết thẳng vào đây:

    1. so_sanh            so hai tài liệu                    (diff_documents)
    2. thong_ke_bang      thống kê bảng tính                 (analyze_data)
    3. tim_thay_the       tìm & thay thế toàn tài liệu       (replace_all)
    4. tao_slide          dàn ý → .pptx                      (create_slides)
    5. cat_theo_tieu_de   cắt tài liệu theo tiêu đề          (split_document)
    6. noi_tep            nối nhiều tệp thành một            (merge_documents)
    7. doc_thong_tin      tác giả / số trang / số sheet…     (extract_metadata)
    8. tao_bao_cao        Excel + mẫu Markdown → .docx       (create_report)

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


# ── 5. Cắt tài liệu theo tiêu đề ────────────────────────────────────────────
# Repo cắt bằng `content.split("\n## ")` — CỨNG ở cấp 2. Tài liệu chỉ dùng `#`
# (rất thường gặp với văn bản tiếng Việt một cấp) thì không cắt được mảnh nào,
# trả về đúng một tệp bằng cả bản gốc mà vẫn báo ok.

_RE_TD = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _cap_tieu_de_nong_nhat(cac_dong: list[str]) -> int:
    """Cấp tiêu đề NÔNG nhất có trong tài liệu (1 = '#'). 0 = không có tiêu đề."""
    cap = 0
    for d in cac_dong:
        m = _RE_TD.match(d)
        if m:
            n = len(m.group(1))
            cap = n if cap == 0 else min(cap, n)
    return cap


def cat_theo_tieu_de(tep: str, *, cap: int = 0,
                     thu_muc: str = "") -> dict[str, Any]:
    """Cắt tài liệu thành nhiều tệp .md theo tiêu đề.

    `cap=0` → tự lấy cấp tiêu đề NÔNG nhất tài liệu đang dùng, nên tài liệu chỉ
    có `#` vẫn cắt được. Bảng trong .docx còn nguyên vì đọc qua
    `pdf_intent.extract_markdown`.
    """
    try:
        p = _duong_dan(tep)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    try:
        noi_dung = _doc_chu(p)
    except Exception as exc:
        return {"ok": False, "error": f"không đọc được: {str(exc)[:150]}"}
    dong = noi_dung.splitlines()
    muc_cap = int(cap) if cap else _cap_tieu_de_nong_nhat(dong)
    if not muc_cap:
        return {"ok": False,
                "error": "tài liệu không có tiêu đề Markdown nào để cắt theo"}

    try:
        from services import officecli
        ra_dir = (officecli.resolve_path(thu_muc) if str(thu_muc or "").strip()
                  else officecli.workspace() / f"{p.stem}-cat")
        ra_dir.mkdir(parents=True, exist_ok=True)
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}

    phan: list[tuple[str, list[str]]] = []
    for d in dong:
        m = _RE_TD.match(d)
        if m and len(m.group(1)) == muc_cap:
            phan.append((m.group(2).strip(), [d]))
        elif phan:
            phan[-1][1].append(d)
        elif d.strip():
            phan.append(("mo-dau", [d]))     # chữ trước tiêu đề đầu tiên
    if not phan:
        return {"ok": False, "error": "không tách được phần nào"}

    cac_tep: list[str] = []
    for i, (ten, than) in enumerate(phan, 1):
        an_toan = re.sub(r"[^\w \-]+", "", ten)[:50].strip().replace(" ", "-") or f"phan-{i}"
        q = ra_dir / f"{i:02d}-{an_toan}.md"
        q.write_text("\n".join(than).strip() + "\n", "utf-8")
        cac_tep.append(q.name)
    return {"ok": True, "so_phan": len(cac_tep), "cap": muc_cap,
            "thu_muc": str(ra_dir), "cac_tep": cac_tep}


# ── 6. Nối nhiều tệp thành một ─────────────────────────────────────────────
# KHÁC `office_merge` sẵn có: cái đó là trộn dữ liệu vào MẪU (mail-merge), còn
# đây là ghép nội dung nhiều tệp lại.
#
# Repo nối .docx bằng `new_para.text = para.text` — mất sạch đậm/nghiêng, và bỏ
# luôn mọi bảng. Nó còn `continue` im lặng khi tệp thiếu, nên nối 5 tệp mà ra 2
# thì người dùng không biết ba tệp nào đã rơi.

def noi_tep(cac_tep: list[str], ten_ra: str, *,
            dinh_dang: str = "docx") -> dict[str, Any]:
    """Nối nhiều tài liệu thành một. dinh_dang: docx | md."""
    ds = [str(x) for x in (cac_tep or []) if str(x or "").strip()]
    if len(ds) < 2:
        return {"ok": False, "error": "cần ít nhất hai tệp để nối"}
    try:
        from services import officecli
        ra = officecli.resolve_path(str(ten_ra or "").strip() or "noi.docx")
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}

    hop_le: list[Path] = []
    bo_qua: list[str] = []
    for x in ds:
        try:
            hop_le.append(_duong_dan(x))
        except (ValueError, FileNotFoundError, OSError) as exc:
            bo_qua.append(f"{x} ({str(exc)[:60]})")
    if len(hop_le) < 2:
        return {"ok": False, "error": "không đủ hai tệp đọc được",
                "bo_qua": bo_qua}

    try:
        if dinh_dang == "md":
            khoi = []
            for q in hop_le:
                khoi.append(f"# {q.stem}\n\n{_doc_chu(q)}\n")
            ra.write_text("\n---\n\n".join(khoi), "utf-8")
        elif dinh_dang == "docx":
            _noi_docx(hop_le, ra)
        else:
            return {"ok": False, "error": f"chỉ nối được docx hoặc md, không phải {dinh_dang}"}
    except Exception as exc:
        logger.warning("noi_tep lỗi: %s", str(exc)[:150])
        return {"ok": False, "error": f"không nối được: {str(exc)[:150]}"}
    kq: dict[str, Any] = {"ok": True, "duong_dan": str(ra), "ten": ra.name,
                          "so_tep": len(hop_le)}
    if bo_qua:
        # Nói RA tệp nào đã rơi. Bỏ qua im lặng là nối 5 tệp ra 2 mà không ai biết.
        kq["bo_qua"] = bo_qua
    return kq


def _noi_docx(cac_tep: list[Path], ra: Path) -> None:
    """Nối .docx GIỮ ĐỊNH DẠNG: bê nguyên thân XML của từng đoạn/bảng sang.

    Repo gán `new_para.text = ...` nên mất đậm/nghiêng và bỏ hết bảng. Ở đây
    dùng `copy.deepcopy` phần tử XML rồi chèn vào thân tài liệu đích — giữ được
    cả định dạng chữ lẫn bảng.
    """
    import copy
    import docx
    ra_doc = docx.Document()
    than = ra_doc.element.body
    for i, q in enumerate(cac_tep):
        ra_doc.add_heading(q.stem, level=1)
        if q.suffix.lower() == ".docx":
            nguon = docx.Document(str(q))
            for pt in nguon.element.body:
                if pt.tag.endswith("}sectPr"):     # thẻ khổ giấy — không bê sang
                    continue
                than.append(copy.deepcopy(pt))
        else:
            for d in _doc_chu(q).splitlines():
                ra_doc.add_paragraph(d)
        if i < len(cac_tep) - 1:
            ra_doc.add_page_break()
    ra_doc.save(str(ra))


# ── 7. Đọc thông tin tài liệu ──────────────────────────────────────────────

def doc_thong_tin(tep: str) -> dict[str, Any]:
    """Thông tin một tài liệu: cỡ, lần sửa, tác giả, số trang/sheet/slide/từ."""
    try:
        p = _duong_dan(tep)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    from datetime import datetime
    st = p.stat()
    tt: dict[str, Any] = {
        "ten": p.name, "loai": p.suffix.lower().lstrip("."),
        "co_byte": st.st_size,
        "sua_luc": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M"),
    }
    duoi = p.suffix.lower()
    try:
        if duoi == ".docx":
            import docx
            d = docx.Document(str(p))
            cp = d.core_properties
            tt.update({"tac_gia": cp.author or "", "tieu_de": cp.title or "",
                       "so_doan": len(d.paragraphs), "so_bang": len(d.tables),
                       "so_tu": sum(len(x.text.split()) for x in d.paragraphs)})
            if cp.created:
                tt["tao_luc"] = cp.created.strftime("%d/%m/%Y %H:%M")
        elif duoi in {".xlsx", ".xlsm"}:
            import openpyxl
            wb = openpyxl.load_workbook(str(p), read_only=True)
            tt.update({"so_sheet": len(wb.worksheets),
                       "cac_sheet": [w.title for w in wb.worksheets],
                       "so_dong": {w.title: (w.max_row or 0) for w in wb.worksheets}})
            wb.close()
        elif duoi == ".pptx":
            from pptx import Presentation
            pres = Presentation(str(p))
            tt["so_slide"] = len(pres.slides)
        elif duoi == ".pdf":
            import fitz
            with fitz.open(str(p)) as d:
                md = d.metadata or {}
                tt.update({"so_trang": d.page_count,
                           "tac_gia": md.get("author") or "",
                           "tieu_de": md.get("title") or ""})
    except Exception as exc:
        # Đọc được cỡ/ngày rồi thì vẫn trả về, chỉ ghi chú phần đọc sâu bị hỏng.
        tt["ghi_chu"] = f"không đọc được phần chi tiết: {str(exc)[:100]}"
    return {"ok": True, **tt}


# ── 8. Sinh báo cáo từ Excel + mẫu Markdown ────────────────────────────────
# Repo nhận tham số `template_md` rồi KHÔNG DÙNG ở đâu cả (soi hết
# report_creator.py: chỉ xuất hiện ở chữ ký hàm và một lời gọi chuyển tiếp), nên
# tiêu đề báo cáo luôn cứng là "Báo cáo: <tên tệp>". Ở đây mẫu là thật: mỗi dòng
# Markdown thành một đoạn, và chỗ nào ghi `{{bang:<tên sheet>}}` thì thay bằng
# bảng thật; `{{thong_ke:<tên sheet>}}` thì thay bằng bảng min/max/trung bình.

_RE_CHO_THAY = re.compile(r"\{\{\s*(bang|thong_ke)\s*:\s*([^}]+?)\s*\}\}")


def tao_bao_cao(tep_du_lieu: str, ten_ra: str, *,
                mau_md: str = "", max_dong_bang: int = 50) -> dict[str, Any]:
    """Excel → báo cáo .docx. `mau_md` là mẫu Markdown, để trống thì tự dựng."""
    try:
        p = _duong_dan(tep_du_lieu)
        from services import officecli
        ra = officecli.resolve_path(str(ten_ra or "").strip() or "bao-cao.docx")
    except (ValueError, FileNotFoundError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    if p.suffix.lower() not in {".xlsx", ".xls", ".xlsm", ".csv"}:
        return {"ok": False, "error": f"cần bảng tính, không phải {p.suffix}"}
    try:
        import pandas as pd
        if p.suffix.lower() == ".csv":
            bang = {"CSV": pd.read_csv(str(p))}
        else:
            bang = pd.read_excel(str(p), sheet_name=None)
    except Exception as exc:
        return {"ok": False, "error": f"không đọc được bảng: {str(exc)[:150]}"}
    if not bang:
        return {"ok": False, "error": "bảng tính không có sheet nào"}

    try:
        import docx
        d = docx.Document()
        if str(mau_md or "").strip():
            _theo_mau(d, mau_md, bang, max_dong_bang)
        else:
            _bao_cao_mac_dinh(d, p.stem, bang, max_dong_bang)
        d.save(str(ra))
    except Exception as exc:
        logger.warning("tao_bao_cao lỗi: %s", str(exc)[:150])
        return {"ok": False, "error": f"không tạo được báo cáo: {str(exc)[:150]}"}
    return {"ok": True, "duong_dan": str(ra), "ten": ra.name,
            "so_sheet": len(bang), "theo_mau": bool(str(mau_md or "").strip())}


def _bang_vao_docx(d: Any, df: Any, max_dong: int) -> None:
    cot = [str(c) for c in df.columns]
    b = d.add_table(rows=1, cols=len(cot))
    b.style = "Light Grid Accent 1"
    for i, c in enumerate(cot):
        b.rows[0].cells[i].text = c
    for _, hang in df.head(max_dong).iterrows():
        o = b.add_row().cells
        for i, c in enumerate(cot):
            v = hang[c]
            o[i].text = "" if v is None or (isinstance(v, float) and v != v) else str(v)
    if len(df) > max_dong:
        d.add_paragraph(f"(còn {len(df) - max_dong} dòng nữa, không đưa vào báo cáo)")


def _thong_ke_vao_docx(d: Any, df: Any) -> None:
    so = df.select_dtypes("number")
    if so.empty:
        d.add_paragraph("(sheet này không có cột số nào để thống kê)")
        return
    b = d.add_table(rows=1, cols=5)
    b.style = "Light Grid Accent 1"
    for i, t in enumerate(["Cột", "Nhỏ nhất", "Lớn nhất", "Trung bình", "Tổng"]):
        b.rows[0].cells[i].text = t
    for c in so.columns:
        v = so[c].dropna()
        if v.empty:
            continue
        o = b.add_row().cells
        for i, t in enumerate([str(c), f"{v.min():g}", f"{v.max():g}",
                               f"{v.mean():.2f}", f"{v.sum():g}"]):
            o[i].text = t


def _theo_mau(d: Any, mau: str, bang: dict, max_dong: int) -> None:
    for dong in str(mau).splitlines():
        m = _RE_CHO_THAY.search(dong)
        if m:
            loai, ten_sheet = m.group(1), m.group(2).strip()
            df = bang.get(ten_sheet)
            if df is None:
                d.add_paragraph(f"[không có sheet “{ten_sheet}” trong tệp]")
            elif loai == "bang":
                _bang_vao_docx(d, df, max_dong)
            else:
                _thong_ke_vao_docx(d, df)
            continue
        td = _RE_TD.match(dong.strip())
        if td:
            d.add_heading(td.group(2), level=min(len(td.group(1)), 4))
        elif dong.strip():
            g = _RE_GACH_DAU.match(dong)
            d.add_paragraph(g.group(1) if g else dong.strip(),
                            style="List Bullet" if g else None)


def _bao_cao_mac_dinh(d: Any, ten: str, bang: dict, max_dong: int) -> None:
    from datetime import datetime
    d.add_heading(f"Báo cáo {ten}", level=1)
    d.add_paragraph("Lập lúc " + datetime.now().strftime("%H:%M %d/%m/%Y"))
    for ten_sheet, df in bang.items():
        d.add_heading(str(ten_sheet), level=2)
        if df is None or df.empty:
            d.add_paragraph("(trống)")
            continue
        d.add_paragraph(f"{len(df)} dòng × {len(df.columns)} cột")
        d.add_heading("Thống kê", level=3)
        _thong_ke_vao_docx(d, df)
        d.add_heading("Dữ liệu", level=3)
        _bang_vao_docx(d, df, max_dong)
