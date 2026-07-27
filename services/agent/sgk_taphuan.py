"""Nạp SGK thẳng từ kho chính thức taphuan.nxbgd.vn — KHÔNG qua máy tìm kiếm.

Vì sao có file này: đường cũ (``sgk_fetch.find_sources``) đi tìm PDF bằng
DuckDuckGo, mà DDG đã chặn kiểu quét HTML — trả 202 kèm trang "anomaly", đo
từ hai IP ở hai châu lục đều vậy. Không có máy tìm kiếm thì mọi cách xếp hạng
nguồn đều vô nghĩa. Kho của NXB Giáo dục thì mở sẵn và có cấu trúc rõ ràng,
nên đi thẳng vừa chắc vừa đúng bản chính chủ.

Cấu trúc kho (đo thật 2026-07-27):

  1. Danh mục theo lớp
     https://taphuan.nxbgd.vn/tap-huan?grade=4   → 12 quyển đủ các môn lớp 4
     (trang /tap-huan không tham số chỉ giới thiệu 12 quyển lẻ — PHẢI có ?grade=N)

  2. Trang chi tiết mỗi quyển
     .../tap-huan/chi-tiet-sach/toan-4-tap-mot-939781966.939781966
     slug đã chứa môn + lớp + tập, khỏi đoán từ tiêu đề.

  3. Trang đọc sách (lọc tiền tố sgk-, bỏ sgv-/vbt-/tai-lieu-tap-huan-)
     .../tap-huan/doc-sach/sgk-toan-4-tap-mot.4714093295

  4. ⚠️ KHÔNG có file PDF. Mỗi trang sách là MỘT ẢNH PNG trên CDN:
     https://cdn3.olm.vn/upload/taphuan/2026/0413/4714093295-page-1-...png
     "Toán 4 tập một" = 134 ảnh, mỗi ảnh ~1,3 MB.

Nên module này gom ảnh → ghép thành PDF → đẩy vào ĐÚNG pipeline nạp sẵn có
(``teacher_workspace.import_sgk_pdf``). PDF ảnh sẽ được nhận là bản scan và
đi nhánh OCR vision — chỗ này TỐN, xem chú thích ở :func:`import_book`.

Trang này KHÔNG cần đăng nhập, nhưng nấp sau Cloudflare: có mạng bị trả 403
kèm trang captcha. Gặp 403 thì báo thẳng, KHÔNG lặng lẽ bịa nguồn khác.
"""
from __future__ import annotations

import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from services import net_guard
from services.agent import sgk_fetch as sf
from services.agent import teacher_workspace as tw

logger = logging.getLogger(__name__)

BASE = "https://taphuan.nxbgd.vn"
CATALOG_URL = BASE + "/tap-huan?grade={grade}"
# Các bộ sách còn lại nằm ở trang riêng. Đo 2026-07-27 với lớp 4: id_book 2 và
# 3 mỗi bộ 12 quyển, id_book 1/4/5 rỗng — nhưng KHÔNG hardcode 2,3 vì bộ có
# thể thêm/bớt theo năm; cứ quét dải rồi bỏ trang rỗng.
BOOK_SET_URL = BASE + "/tap-huan/cac-bo-sach-khac?grade={grade}&id_book={id_book}"
BOOK_SET_IDS: tuple[int, ...] = (1, 2, 3, 4, 5)
ALLOW_HOSTS = {"taphuan.nxbgd.vn", "cdn3.olm.vn", "cdn.olm.vn", "cdn2.olm.vn"}

# Trần cho MỘT ảnh trang và cho cả quyển sau khi ghép.
_MAX_IMG_BYTES = 12 * 1024 * 1024
_MAX_BOOK_BYTES = 400 * 1024 * 1024
# Nghỉ giữa hai lượt tải ảnh — kho của trường học, đừng đấm.
_IMG_GAP = 0.15

_DETAIL_RE = re.compile(r"/tap-huan/chi-tiet-sach/([a-z0-9-]+\.[0-9]+)")
_READER_RE = re.compile(r"/tap-huan/doc-sach/(sgk-[a-z0-9-]+\.[0-9]+)")
_PAGE_IMG_RE = re.compile(
    r"https?://cdn\d*\.olm\.vn/upload/taphuan/[^\s\"'<>]*?-page-(\d+)-\d+\.png",
    re.I,
)

# slug → mã môn của sgk_fetch. Thứ tự QUAN TRỌNG: "lich-su-va-dia-li" phải
# đứng trước "lich-su" và "dia-li", nếu không sách gộp bị nhận nhầm.
_SLUG_SUBJECT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lich-su-va-dia-li", ("su", "dia")),
    ("giao-duc-kinh-te-va-phap-luat", ("gdcd",)),
    ("giao-duc-cong-dan", ("gdcd",)),
    ("khoa-hoc-tu-nhien", ("ly", "hoa", "sinh")),
    ("tieng-viet", ("van",)),
    ("ngu-van", ("van",)),
    ("tieng-anh", ("anh",)),
    ("toan", ("toan",)),
    ("vat-li", ("ly",)),
    ("vat-ly", ("ly",)),
    ("hoa-hoc", ("hoa",)),
    ("sinh-hoc", ("sinh",)),
    ("lich-su", ("su",)),
    ("dia-li", ("dia",)),
    ("dia-ly", ("dia",)),
    ("tin-hoc", ("tin",)),
)


def _get(url: str, *, timeout: float = 30) -> str:
    raw = net_guard.safe_fetch(
        url, allow_hosts=ALLOW_HOSTS, timeout=timeout, max_bytes=8 * 1024 * 1024,
    )
    return raw.decode("utf-8", errors="ignore")


def subjects_of_slug(slug: str) -> tuple[str, ...]:
    """Môn (có thể NHIỀU, vd Lịch sử và Địa lí) suy từ slug. Rỗng = không nhận."""
    s = (slug or "").lower()
    for prefix, subs in _SLUG_SUBJECT:
        if s.startswith(prefix):
            return subs
    return ()


def _volume_of_slug(slug: str) -> str:
    if "tap-mot" in slug:
        return "tập một"
    if "tap-hai" in slug:
        return "tập hai"
    return ""


def list_books(grade: int, *, all_sets: bool = True) -> list[dict[str, Any]]:
    """Danh mục SGK của MỘT lớp: bộ chính (``?grade=N``) + các bộ sách khác.

    Trả list ``{slug, url, subjects, volume, book_set, grade}``. Sách không
    nhận ra môn (Âm nhạc, Mĩ thuật, Hoạt động trải nghiệm…) vẫn được trả về
    với ``subjects=()`` để người gọi tự quyết, KHÔNG im lặng vứt đi.

    ``all_sets=False`` chỉ lấy bộ chính — nhanh hơn 5 lượt tải khi chỉ cần
    liệt kê nhanh.
    """
    g = int(grade)
    if g not in tw.GRADES:
        return []

    pages: list[tuple[str, str]] = [("", CATALOG_URL.format(grade=g))]
    if all_sets:
        pages += [
            (str(i), BOOK_SET_URL.format(grade=g, id_book=i)) for i in BOOK_SET_IDS
        ]

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for set_id, url in pages:
        try:
            html = _get(url)
        except Exception as exc:
            logger.warning("sgk_taphuan.list_books lớp %s (bộ %r) lỗi: %s",
                           g, set_id or "chính", exc)
            continue
        for m in _DETAIL_RE.finditer(html):
            ident = m.group(1)
            if ident in seen:  # cùng quyển xuất hiện ở nhiều bộ → giữ 1
                continue
            seen.add(ident)
            slug = ident.split(".")[0]
            out.append({
                "slug": slug,
                "url": f"{BASE}/tap-huan/chi-tiet-sach/{ident}",
                "subjects": subjects_of_slug(slug),
                "volume": _volume_of_slug(slug),
                "book_set": set_id,
                "grade": g,
            })
    return out


def reader_urls(detail_url: str) -> list[str]:
    """Link trang đọc của SGK trong 1 trang chi tiết (chỉ lấy tiền tố ``sgk-``).

    Trang chi tiết còn có sách giáo viên (sgv-), vở bài tập (vbt-) và tài liệu
    tập huấn — nạp nhầm mấy thứ đó vào kho SGK là sai nội dung, nên lọc chặt.
    """
    try:
        html = _get(detail_url)
    except Exception as exc:
        logger.warning("sgk_taphuan.reader_urls lỗi (%s): %s", detail_url[:80], exc)
        return []
    out: list[str] = []
    for ident in dict.fromkeys(_READER_RE.findall(html)):
        out.append(f"{BASE}/tap-huan/doc-sach/{ident}")
    return out


def page_images(reader_url: str) -> list[str]:
    """URL ảnh từng trang, sắp theo SỐ TRANG chứ không theo thứ tự xuất hiện."""
    try:
        html = _get(reader_url, timeout=45)
    except Exception as exc:
        logger.warning("sgk_taphuan.page_images lỗi (%s): %s", reader_url[:80], exc)
        return []
    found: dict[int, str] = {}
    for m in _PAGE_IMG_RE.finditer(html):
        num = int(m.group(1))
        found.setdefault(num, m.group(0))
    return [found[k] for k in sorted(found)]


def build_pdf(image_urls: Iterable[str], out_path: str | Path,
              *, max_pages: int = 0) -> dict[str, Any]:
    """Tải ảnh từng trang rồi ghép thành 1 PDF.

    ``max_pages=0`` là lấy hết. Ảnh nhúng nguyên xi (không giải mã lại) nên
    nhanh và không mất nét — đằng nào bước sau cũng OCR.
    """
    import fitz  # PyMuPDF, có sẵn trong venv app

    urls = list(image_urls)
    if max_pages and max_pages > 0:
        urls = urls[:max_pages]
    if not urls:
        return {"ok": False, "error": "không có ảnh trang nào"}

    doc = fitz.open()
    total = 0
    failed = 0
    for i, u in enumerate(urls):
        if i:
            time.sleep(_IMG_GAP)
        try:
            blob = net_guard.safe_fetch(
                u, allow_hosts=ALLOW_HOSTS, timeout=60, max_bytes=_MAX_IMG_BYTES,
            )
        except Exception as exc:
            failed += 1
            logger.warning("sgk_taphuan: tải trang %s lỗi: %s", i + 1, exc)
            continue
        total += len(blob)
        if total > _MAX_BOOK_BYTES:
            doc.close()
            return {"ok": False,
                    "error": f"sách vượt trần {_MAX_BOOK_BYTES // 1024 // 1024}MB"}
        try:
            img = fitz.open(stream=blob, filetype="png")
            rect = img[0].rect
            page = doc.new_page(width=rect.width, height=rect.height)
            page.insert_image(rect, stream=blob)
            img.close()
        except Exception as exc:
            failed += 1
            logger.warning("sgk_taphuan: nhúng trang %s lỗi: %s", i + 1, exc)

    if doc.page_count == 0:
        doc.close()
        return {"ok": False, "error": "không nhúng được trang nào"}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    pages = doc.page_count
    doc.close()
    return {"ok": True, "path": str(out), "pages": pages,
            "failed_pages": failed, "bytes": total}


def _ingest_pdf(pdf_path: str, *, grade: int, subject: str, title: str,
                source_name: str, mode: str = "append") -> dict[str, Any]:
    """Đẩy PDF vào đúng pipeline sẵn có — giống nhánh của sgk_fetch.

    3 môn gốc (toán/văn/anh) đi ``import_sgk_pdf`` để ghi cả file .md lẫn RAG;
    môn mới chỉ nạp RAG, KHÔNG đụng .md của SGK gốc.
    """
    if subject in tw.SUBJECTS:
        return tw.import_sgk_pdf(
            pdf_path, grade=grade, subject=subject, mode=mode,
            title=title, source_name=source_name,
        )
    from services import pdf_to_word as p2w
    from services.pdf_intent import extract_markdown

    max_pages = int(getattr(p2w, "TEACHER_SGK_MAX_PAGES", 0) or 0)
    raw = extract_markdown(pdf_path, max_pages=max_pages)
    if not (raw or "").strip():
        return {"ok": False, "error": "OCR không ra chữ (ảnh mờ hoặc thiếu vision)"}
    md = tw._md_from_pdf_text(raw, title=title)
    rag = tw.push_sgk_to_rag(
        md, title=title, grade=grade, subject=subject, source=source_name,
        collection=sf.KIND_COLLECTION["sgk"],
    )
    return {"ok": bool(rag.get("ok")), "grade": grade, "subject": subject,
            "chars": len(md), "rag": rag,
            "note": "Chỉ nạp RAG (không ghi .md SGK gốc)."}


def import_book(grade: int, subject: str, *, max_pages: int = 0,
                mode: str = "append", dry_run: bool = False) -> dict[str, Any]:
    """Nạp SGK 1 lớp–môn từ taphuan: danh mục → trang đọc → ảnh → PDF → RAG.

    Gộp mọi tập (tập một + tập hai) của môn đó.

    ⚠️ CHI PHÍ: PDF ghép từ ảnh luôn bị coi là bản scan nên phải OCR bằng AI
    vision. Một quyển ~134 trang là ~134 lượt gọi vision. Nạp cả 12 lớp × mọi
    môn là con số rất lớn — hãy nạp có chọn lọc, hoặc đặt ``max_pages`` để thử
    trước. ``dry_run=True`` chỉ liệt kê sẽ nạp gì, không tải, không OCR.
    """
    g = int(grade)
    sub = sf.normalize_subject(subject)
    if g not in tw.GRADES:
        return {"ok": False, "error": f"grade phải 1–12, nhận {grade}"}
    if not sub:
        return {"ok": False, "error": f"không nhận ra môn: {subject}"}

    books = [b for b in list_books(g) if sub in b["subjects"]]
    if not books:
        return {"ok": False, "grade": g, "subject": sub, "status": "no_source",
                "error": f"taphuan không có sách lớp {g} môn {sub}"}

    plan: list[dict[str, Any]] = []
    for b in books:
        for r in reader_urls(b["url"]):
            plan.append({"slug": b["slug"], "volume": b["volume"], "reader": r})
    if not plan:
        return {"ok": False, "grade": g, "subject": sub, "status": "no_source",
                "error": "thấy sách nhưng không có trang đọc dạng sgk-"}
    if dry_run:
        return {"ok": True, "grade": g, "subject": sub, "dry_run": True,
                "books": plan}

    done: list[dict[str, Any]] = []
    for item in plan:
        imgs = page_images(item["reader"])
        if not imgs:
            done.append({**item, "ok": False, "error": "không lấy được ảnh trang"})
            continue
        label = f"SGK lớp {g} · {sf.SUBJECT_LABEL.get(sub, sub)} · {item['volume']}".strip(" ·")
        with tempfile.TemporaryDirectory() as td:
            pdf_path = str(Path(td) / f"{item['slug']}.pdf")
            built = build_pdf(imgs, pdf_path, max_pages=max_pages)
            if not built.get("ok"):
                done.append({**item, "ok": False, "error": built.get("error")})
                continue
            res = _ingest_pdf(
                pdf_path, grade=g, subject=sub, title=label,
                source_name=f"taphuan.nxbgd.vn/{item['slug']}", mode=mode,
            )
        done.append({**item, "ok": bool(res.get("ok")),
                     "pages": built.get("pages"), "chars": res.get("chars"),
                     "error": res.get("error") or ""})
        mode = "append"  # tập sau luôn nối, đừng ghi đè tập trước

    ok_count = sum(1 for d in done if d["ok"])
    return {"ok": ok_count > 0, "grade": g, "subject": sub,
            "books": done, "ok_count": ok_count, "total": len(done)}


__all__ = ["list_books", "reader_urls", "page_images", "build_pdf",
           "import_book", "subjects_of_slug"]
