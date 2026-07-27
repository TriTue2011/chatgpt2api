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
CATALOG_URL = BASE + "/tap-huan?grade={grade}&subjects={subjects}"

# Mã môn theo lớp — do người vận hành chốt, KHÔNG tự suy. Kho có cả Âm nhạc,
# Mĩ thuật, Hoạt động trải nghiệm, Giáo dục thể chất…; lọc sẵn ở tầng URL để
# không tải rồi mới bỏ. Đo thật với danh sách này:
#   lớp 4  → Toán, Tiếng Việt, Tiếng Anh, Lịch sử và Địa lí
#   lớp 10 → Toán, Ngữ văn, Lịch sử, Địa lí, Vật lí (+ chuyên đề học tập)
_GRADE_SUBJECT_IDS: dict[int, str] = {
    1: "1,3,2",
    2: "1,3,2",
    3: "1,3,2",
    4: "1,3,22,2",
    5: "1,3,22,2",
    6: "21,3,22,5,2",
    7: "21,3,22,5,2",
    8: "21,3,22,5,6,7,2",
    9: "21,3,22,5,6,7,2",
    10: "21,3,8,9,5,6,7,2",
    11: "21,3,8,9,5,6,7,2",
    12: "21,3,8,9,5,6,7,2",
}
# Các bộ sách còn lại nằm ở trang riêng. Đo 2026-07-27 với lớp 4: id_book 2 và
# 3 mỗi bộ 12 quyển, id_book 1/4/5 rỗng — nhưng KHÔNG hardcode 2,3 vì bộ có
# thể thêm/bớt theo năm; cứ quét dải rồi bỏ trang rỗng.
BOOK_SET_URL = (
    BASE + "/tap-huan/cac-bo-sach-khac?grade={grade}&id_book={id_book}"
           "&subjects={subjects}"
)
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
    """Môn (có thể NHIỀU, vd Lịch sử và Địa lí) suy từ slug. Rỗng = không nhận.

    Xử lý được cả sách chuyên đề THPT (``chuyen-de-hoc-tap-toan-10``) — bóc
    tiền tố rồi khớp theo môn gốc, nếu không sẽ rơi hết vào "không nhận".
    """
    s = (slug or "").lower()
    if s.startswith("chuyen-de-hoc-tap-"):
        s = s[len("chuyen-de-hoc-tap-"):]
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


def list_books(grade: int, *, all_sets: bool = False) -> list[dict[str, Any]]:
    """Danh mục SGK của MỘT lớp. Mặc định CHỈ bộ chính (``?grade=N``).

    Trả list ``{slug, url, subjects, volume, book_set, grade}``. Sách không
    nhận ra môn (Âm nhạc, Mĩ thuật, Hoạt động trải nghiệm…) vẫn được trả về
    với ``subjects=()`` để người gọi tự quyết, KHÔNG im lặng vứt đi.

    ``all_sets=True`` lấy thêm các bộ sách khác (``cac-bo-sach-khac``). MẶC
    ĐỊNH TẮT vì đó là bộ sách KHÁC cho CÙNG môn: nạp chung vào một file
    ``lop{N}/{mon}.md`` thì trong cùng một môn có hai chương trình khác nhau,
    bài khác nhau — bot sẽ trả lời mâu thuẫn mà không biết bộ nào đang dùng.
    Muốn bật thì phải tách kho theo bộ sách trước.
    """
    g = int(grade)
    if g not in tw.GRADES:
        return []

    subs = _GRADE_SUBJECT_IDS.get(g, "")
    pages: list[tuple[str, str]] = [
        ("", CATALOG_URL.format(grade=g, subjects=subs)),
    ]
    if all_sets:
        # Bộ sách khác lọc CÙNG danh sách môn — không để bộ phụ kéo về những
        # môn mà bộ chính đã cố tình loại.
        pages += [
            (str(i), BOOK_SET_URL.format(grade=g, id_book=i, subjects=subs))
            for i in BOOK_SET_IDS
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


# Chất lượng JPEG khi nhúng. 72 đủ nét cho model đọc chữ mà giảm ~20 lần dung
# lượng so với nhúng thẳng PNG. Đằng nào bước sau cũng là OCR, không phải in.
_JPEG_QUALITY = 72
# Cạnh dài tối đa mỗi trang. Ảnh gốc ~2000px; Gemini hạ về 3072px là cùng nên
# giữ 2000 không mất gì, mà chặn được trang scan khổ lớn bất thường.
_MAX_EDGE = 2000


def _to_jpeg(png: bytes) -> bytes:
    """PNG → JPEG. Trả lại nguyên bản nếu vì lý do gì đó không đổi được."""
    try:
        import io

        from PIL import Image

        im = Image.open(io.BytesIO(png))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > _MAX_EDGE:
            scale = _MAX_EDGE / float(max(w, h))
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=_JPEG_QUALITY, optimize=True)
        return buf.getvalue()
    except Exception as exc:
        logger.warning("sgk_taphuan._to_jpeg: đổi ảnh lỗi, dùng bản gốc: %s", exc)
        return png


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
            # PHẢI đổi sang JPEG trước khi nhúng. Nhúng thẳng PNG thì PyMuPDF
            # giải nén rồi nén lại bằng Flate: đo thật 2026-07-28, 108 MB ảnh
            # PNG phình thành PDF 647 MB (gấp 6). Hệ quả không chỉ là tốn đĩa —
            # mỗi khối 20 trang thành ~97 MB, base64 lên ~130 MB, vượt xa trần
            # 50 MB mỗi PDF của Gemini nên treo luôn ở bước gửi.
            jpg = _to_jpeg(blob)
            img = fitz.open(stream=jpg, filetype="jpeg")
            rect = img[0].rect
            page = doc.new_page(width=rect.width, height=rect.height)
            page.insert_image(rect, stream=jpg)
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


_DOC_PROMPT = (
    "Chép TOÀN BỘ nội dung các trang sách giáo khoa này thành Markdown tiếng "
    "Việt. Giữ nguyên thứ tự trang, tiêu đề bài, số bài, bảng biểu. Với hình "
    "minh hoạ, mô tả ngắn trong ngoặc. KHÔNG tóm tắt, KHÔNG bình luận, KHÔNG "
    "bịa thêm nội dung không có trên trang."
)
# Số trang mỗi lượt gọi. Cả quyển một lượt thì đầu ra bị cắt cụt (134 trang ≈
# 60k token markdown, vượt trần output), nên cắt khối. 20 trang ≈ 12k token —
# an toàn, mà vẫn ít hơn 20 lần so với gửi từng trang một.
_PAGES_PER_CALL = 20
# Trần dung lượng mỗi khối gửi đi. Gemini chặn 50 MB/PDF, base64 phình 4/3
# (30 MB → ~40 MB trên dây), nên 30 MB là ngưỡng an toàn.
_MAX_CHUNK_BYTES = 30 * 1024 * 1024


def book_markdown(pdf_path: str | Path, *, pages_per_call: int = _PAGES_PER_CALL,
                  model: str = "") -> str:
    """PDF cả quyển → Markdown, gửi theo KHỐI TRANG thay vì từng trang.

    Rẻ hơn đường ``_scan_markdown_pages`` (1 ảnh = 1 lượt gọi) khoảng 20 lần.
    Dùng được vì provider Gemini nhận ``file_data`` với data URL mime bất kỳ —
    xem gemini_free._data_url_part.

    Khối nào lỗi thì bỏ qua và ghi nhận, KHÔNG để thông báo lỗi lọt vào kết
    quả (xem p2w.looks_like_ocr_failure).
    """
    import base64
    import fitz

    from services import pdf_to_word as p2w
    from services.agent.branches import branch_model
    from services.agent.runtime import call_model, content_of

    mid = model or branch_model("vision")
    src = fitz.open(str(pdf_path))
    total = src.page_count
    out: list[str] = []
    missing: list[tuple[int, int]] = []
    step = max(1, int(pages_per_call))
    try:
        start = 0
        while start < total:
            end = min(start + step, total) - 1
            # Thu nhỏ khối cho tới khi lọt trần. Gemini chặn 50 MB mỗi PDF, mà
            # base64 còn phình 4/3, nên lấy 30 MB làm ngưỡng an toàn. Không có
            # bước này thì một quyển ảnh nặng bất thường sẽ treo ở lúc gửi
            # thay vì báo lỗi (đã dính đúng như vậy 2026-07-28).
            while True:
                chunk = fitz.open()
                chunk.insert_pdf(src, from_page=start, to_page=end)
                blob = chunk.tobytes()
                chunk.close()
                if len(blob) <= _MAX_CHUNK_BYTES or end <= start:
                    break
                end = start + max(0, (end - start) // 2)
            if len(blob) > _MAX_CHUNK_BYTES:
                logger.warning("sgk_taphuan.book_markdown: trang %s nặng %s MB, bỏ qua",
                               start + 1, len(blob) // 1024 // 1024)
                start = end + 1
                continue
            uri = "data:application/pdf;base64," + base64.b64encode(blob).decode()
            try:
                resp = call_model(mid, [
                    {"role": "user", "content": [
                        {"type": "text", "text": _DOC_PROMPT},
                        {"type": "file_data", "file_data": {"file_uri": uri}},
                    ]},
                ], timeout=600, max_tokens=32000, no_smart_home=True)
                if resp.get("error"):
                    logger.warning("sgk_taphuan.book_markdown: khối %s-%s lỗi: %s",
                                   start + 1, end + 1, str(resp["error"])[:150])
                    missing.append((start + 1, end + 1))
                else:
                    md = content_of(resp).strip()
                    if p2w.looks_like_ocr_failure(md):
                        logger.warning(
                            "sgk_taphuan.book_markdown: khối %s-%s trả lỗi model",
                            start + 1, end + 1)
                        missing.append((start + 1, end + 1))
                    else:
                        out.append(md)
            finally:
                # Luôn tiến, kể cả khi khối lỗi — nếu không thì vòng while lặp
                # vô hạn trên đúng khối hỏng đó.
                start = end + 1
    finally:
        src.close()

    body = "\n\n---\n\n".join(out)
    if missing:
        # KHÔNG im lặng nuốt phần thiếu. Sách vào kho mà hụt 20 trang, bot dạy
        # sai mà không ai biết là kiểu hỏng tệ nhất — nên ghi thẳng vào nội
        # dung để người đọc file .md thấy, và nêu rõ ở log.
        note = "\n\n".join(
            f"> ⚠️ THIẾU trang {a}–{b}: model không trả được nội dung." for a, b in missing
        )
        body = f"{body}\n\n---\n\n{note}\n" if body else note
        lost = sum(b - a + 1 for a, b in missing)
        logger.warning(
            {"event": "sgk_taphuan_thieu_trang", "pdf": str(pdf_path),
             "so_trang_thieu": lost, "tong_trang": total, "khoi": missing})
        # Hụt quá nửa quyển thì coi như hỏng, để caller khỏi nạp bản què.
        if lost > total * 0.5:
            raise RuntimeError(
                f"thiếu {lost}/{total} trang — quá nửa quyển, không nạp")
    return body


def _ingest_pdf(pdf_path: str, *, grade: int, subject: str, title: str,
                source_name: str, mode: str = "append") -> dict[str, Any]:
    """Đẩy PDF vào đúng pipeline sẵn có — giống nhánh của sgk_fetch.

    3 môn gốc (toán/văn/anh) đi ``import_sgk_pdf`` để ghi cả file .md lẫn RAG;
    môn mới chỉ nạp RAG, KHÔNG đụng .md của SGK gốc.
    """
    from services import pdf_to_word as p2w

    # Trích bằng đường KHỐI TRANG (~20 lần rẻ hơn OCR từng trang). Hỏng thì
    # để None và rơi về đường cũ, chứ không nạp nửa vời.
    raw = book_markdown(pdf_path)
    if p2w.looks_like_ocr_failure(raw):
        raw = ""

    if subject in tw.SUBJECTS:
        return tw.import_sgk_pdf(
            pdf_path, grade=grade, subject=subject, mode=mode,
            title=title, source_name=source_name, text=raw,
        )
    if not raw:
        from services.pdf_intent import extract_markdown
        max_pages = int(getattr(p2w, "TEACHER_SGK_MAX_PAGES", 0) or 0)
        raw = extract_markdown(pdf_path, max_pages=max_pages)
    # Chặn nạp rác: gateway hay trả "Gemini error …" như content trang.
    # Helper dùng chung với cache OCR (services.pdf_to_word.looks_like_ocr_failure).
    if p2w.looks_like_ocr_failure(raw):
        return {"ok": False,
                "error": "OCR hỏng — kết quả là thông báo lỗi của model, "
                         "KHÔNG nạp để tránh nhồi rác vào kho SGK"}
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
    probed = False
    for item in plan:
        imgs = page_images(item["reader"])
        if not imgs:
            done.append({**item, "ok": False, "error": "không lấy được ảnh trang"})
            continue

        # Thử OCR ĐÚNG 1 TRANG trước khi tải cả quyển. Một quyển là ~134 lượt
        # gọi vision và ~110 MB tải về — hỏng ngay từ trang đầu thì dừng luôn,
        # đỡ đốt cả hai. Chỉ thử một lần cho cả lần chạy.
        if not probed:
            probed = True
            with tempfile.TemporaryDirectory() as ptd:
                probe_pdf = str(Path(ptd) / "probe.pdf")
                pb = build_pdf(imgs, probe_pdf, max_pages=1)
                if not pb.get("ok"):
                    return {"ok": False, "grade": g, "subject": sub,
                            "status": "failed",
                            "error": f"không dựng nổi trang thử: {pb.get('error')}"}
                from services import pdf_to_word as p2w
                from services.pdf_intent import extract_markdown
                probe_txt = extract_markdown(probe_pdf, max_pages=1)
            if p2w.looks_like_ocr_failure(probe_txt):
                return {"ok": False, "grade": g, "subject": sub,
                        "status": "failed",
                        "error": "OCR vision đang hỏng (trang thử không ra chữ) "
                                 "— dừng trước khi tải cả quyển",
                        "probe_sample": (probe_txt or "")[:200]}
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
