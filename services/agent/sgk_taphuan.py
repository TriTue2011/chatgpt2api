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

# Mã môn của kho, đo thật 2026-07-28 bằng cách hỏi riêng từng mã ở lớp 10:
#   1=Tiếng Việt  2=Tiếng Anh  3=Toán  5=Vật lí  6=Hoá học  7=Sinh học
#   8=Lịch sử  9=Địa lí  21=Ngữ văn  22=Lịch sử và Địa lí
# Lọc sẵn ở tầng URL để không tải rồi mới bỏ (kho còn Âm nhạc, Mĩ thuật, Hoạt
# động trải nghiệm, Giáo dục thể chất…).
_SUBJECT_IDS_BY_GRADE: dict[int, tuple[int, ...]] = {
    1:  (1, 3, 2),
    2:  (1, 3, 2),
    3:  (1, 3, 2),
    4:  (1, 3, 22, 2),
    5:  (1, 3, 22, 2),
    6:  (21, 3, 22, 2),
    7:  (21, 3, 22, 2),
    8:  (21, 3, 22, 2),
    9:  (21, 3, 22, 2),
    10: (21, 3, 8, 9, 5, 6, 7, 2),
    11: (21, 3, 8, 9, 5, 6, 7, 2),
    12: (21, 3, 8, 9, 5, 6, 7, 2),
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
# Bắt MỌI link đọc rồi mới lọc theo loại bằng `doc_kind()`. Trước đây regex tự
# ép tiền tố `sgk-`, nên "shs-" (sách học sinh) và slug trần không lọt qua —
# tức mất luôn sách chính của một số môn thay vì chỉ mất SGV/VBT.
_READER_RE = re.compile(r"/tap-huan/doc-sach/([a-z0-9-]+\.[0-9]+)")
_PAGE_IMG_RE = re.compile(
    r"https?://cdn\d*\.olm\.vn/upload/taphuan/[^\s\"'<>]*?-page-(\d+)-\d+\.png",
    re.I,
)
# Đọc ảnh trang qua THẺ img thay vì bắt URL: số trang nằm ở `data-page`, dùng
# được cho cả hai kiểu tên ảnh của kho. Xem :func:`parse_page_images`.
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
_CDN_IMG_RE = re.compile(r"https?://cdn\d*\.olm\.vn/upload/taphuan/", re.I)


def _tag_attr(tag: str, name: str) -> str:
    """Giá trị một thuộc tính trong thẻ HTML. Nhận cả nháy đơn và nháy kép."""
    m = re.search(rf"""\b{re.escape(name)}\s*=\s*("[^"]*"|'[^']*')""", tag, re.I)
    return m.group(1)[1:-1] if m else ""

# slug → mã môn của sgk_fetch. Thứ tự QUAN TRỌNG: "lich-su-va-dia-li" phải
# đứng trước "lich-su" và "dia-li", nếu không sách gộp bị nhận nhầm.
_SLUG_SUBJECT: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Giữ NGUYÊN tên sách, không gộp và không đổi:
    #   lớp 4–9 là MỘT quyển "Lịch sử và Địa lí" → mã `sudia` (trước tách thành
    #   ("su","dia") tức tự đổi một quyển thành hai môn);
    #   "Tiếng Việt" (1–5) khác "Ngữ văn" (6–12) → hai mã khác nhau.
    #
    # Chỉ khai môn CÓ trong teacher_workspace.SUBJECTS. Khoa học tự nhiên, GDCD,
    # KT&PL, Tin học đã bỏ khỏi danh mục (không cần) — cố ý KHÔNG khai ở đây:
    # trỏ vào mã môn không tồn tại thì `_normalize_subject` trả None và import
    # chết với lỗi khó hiểu. Không khai thì `list_books` trả `subjects=()`, tức
    # "không nhận ra môn" — người gọi thấy rõ và tự quyết.
    ("lich-su-va-dia-li", ("sudia",)),
    ("tieng-viet", ("tviet",)),
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

    # Hỏi RIÊNG TỪNG mã môn, không gộp tất cả vào một URL.
    #
    # Trang danh mục CẮT BỚT kết quả khi lọc nhiều mã một lượt: đo 2026-07-28,
    # lớp 10 hỏi gộp `subjects=21,3,8,9,5,6,7,2` chỉ trả 12 quyển, hỏi riêng
    # từng mã ra 17 — mất hẳn Tiếng Anh, Hoá học, Sinh học. Bản cũ hỏi gộp nên
    # âm thầm bỏ sót sách, và ai đọc kết quả sẽ kết luận sai là kho không có.
    sids = _SUBJECT_IDS_BY_GRADE.get(g, ())
    pages: list[tuple[str, str]] = [
        ("", CATALOG_URL.format(grade=g, subjects=sid)) for sid in sids
    ]
    if all_sets:
        # Bộ sách khác lọc CÙNG danh sách môn — không để bộ phụ kéo về những
        # môn mà bộ chính đã cố tình loại. Cũng hỏi từng mã một, cùng lý do.
        pages += [
            (str(i), BOOK_SET_URL.format(grade=g, id_book=i, subjects=sid))
            for i in BOOK_SET_IDS
            for sid in sids
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


def reader_urls(detail_url: str, kinds: Iterable[str] = ("sgk",)) -> list[str]:
    """Link trang đọc trong 1 trang chi tiết, lọc theo LOẠI tài liệu.

    Mặc định chỉ SGK — nạp sách giáo viên hay vở bài tập vào kho SGK là sai nội
    dung. Muốn lấy thêm thì nói rõ, vd ``kinds=("sgk", "sgv", "vbt")``; mỗi loại
    đi về collection riêng qua :func:`COLLECTION_FOR_SET`.

    ``kinds=()`` nghĩa là KHÔNG lọc — trả về tất cả.
    """
    try:
        html = _get(detail_url)
    except Exception as exc:
        logger.warning("sgk_taphuan.reader_urls lỗi (%s): %s", detail_url[:80], exc)
        return []
    want = {str(k).strip().lower() for k in kinds if str(k).strip()}
    out: list[str] = []
    for ident in dict.fromkeys(_READER_RE.findall(html)):
        url = f"{BASE}/tap-huan/doc-sach/{ident}"
        if want and doc_kind(url) not in want:
            continue
        out.append(url)
    return out


def parse_page_images(html: str) -> list[str]:
    """Ảnh từng trang, đọc từ THẺ ``<img>`` — thuần chuỗi, tách ra để test được.

    Vì sao không dùng regex bắt URL nữa (đo thật 2026-07-28): kho có HAI kiểu
    tên ảnh, và regex cũ ``-page-N-<id>.png`` chỉ khớp kiểu thứ nhất::

        kiểu A  .../4714093295-page-1-<id>.png          ← số trang trong URL
        kiểu B  .../<uuid>-<yyyymmddhhmm...>-<ms>.jpg   ← KHÔNG có số trang

    Kiểu B khiến hàm này trả về rỗng, tức "sách không có trang nào" — im lặng.
    Đo trên bản quét dở: 41 mục bị báo 0 trang, trong đó
    ``shs-tieng-viet-2-tap-mot`` thật ra có 156 trang và
    ``sgv-tieng-viet-2-tap-mot`` có 212 trang.

    Số trang thật nằm ở thuộc tính ``data-page`` của chính thẻ ``<img>``, dùng
    được cho CẢ HAI kiểu::

        <img src="/training/images/default/blank_book_page.png"
             data-src="https://cdn3.olm.vn/upload/taphuan/....jpg"
             data-page="1" alt="page-1" class="js-lazy-page">

    Phải lấy ``data-src`` chứ không phải ``src``: trang nạp chậm nên ``src`` là
    ảnh trắng dùng chung — lấy ``src`` thì được đủ số trang nhưng trang nào
    cũng trắng, OCR ra rỗng mà không có lỗi nào.

    Bìa (``alt="cover-first"``/``cover-last"``) không có ``data-page`` nên bị bỏ,
    cố ý: prompt OCR đánh số trang theo số THẬT, chèn bìa vào sẽ lệch hết.
    """
    by_url: dict[int, str] = {}
    by_attr: dict[int, str] = {}
    unnumbered: list[str] = []
    for m in _IMG_TAG_RE.finditer(html or ""):
        tag = m.group(0)
        url = _tag_attr(tag, "data-src") or _tag_attr(tag, "src")
        if not url or not _CDN_IMG_RE.match(url):
            continue
        mm = re.search(r"-page-(\d+)-\d+\.", url)
        dp = _tag_attr(tag, "data-page").strip()
        if mm:
            by_url.setdefault(int(mm.group(1)), url)
        elif dp.isdigit() and int(dp) > 0:
            by_attr.setdefault(int(dp), url)
        else:
            unnumbered.append(url)
    # KHÔNG trộn hai hệ đánh số — chúng đo hai thứ KHÁC NHAU (đo thật, đối chiếu
    # với số in trên chính trang ảnh, 2026-07-28):
    #
    #   số trong URL  = THỨ TỰ ẢNH trong quyển, bìa là ảnh 1 → luôn có, liền mạch
    #   data-page     = SỐ TRANG IN trên trang giấy         → lệch 1 vì có bìa,
    #                                                         và bìa/trang trắng
    #                                                         thì không có
    #
    # Kiểm chứng: ảnh "-page-80-" của Hoá học 11 in số 79; ảnh "-page-94-" của
    # Tiếng Việt 1 in số 93.
    #
    # Chọn hệ URL vì nó LUÔN có và liền mạch — thiếu số thì không đối chiếu được
    # độ phủ. Trộn hai hệ thì `setdefault` cho trang này chiếm chỗ trang kia và
    # mất trang thật (đã mất đúng 1 trang khi thử trộn).
    #
    # Hệ quả phải xử lý ở prompt: model NHÌN THẤY số in nên phải nói rõ đánh số
    # theo số tôi nêu, không theo số in — xem `_DOC_PROMPT` quy tắc 1.
    if by_url:
        return [by_url[k] for k in sorted(by_url)]
    if by_attr:
        return [by_attr[k] for k in sorted(by_attr)]
    # Không thẻ nào có số: đành theo thứ tự xuất hiện. Kèm cảnh báo vì thứ tự
    # tài liệu chỉ ĐÚNG TÌNH CỜ — đừng để nó thành đường mặc định không ai biết.
    if unnumbered:
        logger.warning(
            "sgk_taphuan.parse_page_images: %s ảnh KHÔNG có data-page, phải xếp "
            "theo thứ tự xuất hiện — kiểm lại nếu nội dung lộn trang", len(unnumbered))
    return unnumbered


def page_images(reader_url: str) -> list[str]:
    """URL ảnh từng trang, sắp theo SỐ TRANG chứ không theo thứ tự xuất hiện."""
    try:
        html = _get(reader_url, timeout=45)
    except Exception as exc:
        logger.warning("sgk_taphuan.page_images lỗi (%s): %s", reader_url[:80], exc)
        return []
    urls = parse_page_images(html)
    if not urls:
        logger.warning("sgk_taphuan.page_images: không thấy ảnh trang nào ở %s",
                       reader_url[:100])
    return urls


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


# Mốc trang. Có mốc thì đếm được model TRẢ THẬT bao nhiêu trang, không có thì
# khối 20 trang trả về 8 trang vẫn được nhận như đủ — kiểu hỏng tệ nhất vì im
# lặng. Đây là điểm khác biệt chính so với bản trước.
_PAGE_MARK_RE = re.compile(r"<<<\s*TRANG\s+(\d+)\s*>>>")

# Prompt theo kỷ luật của các bộ OCR tài liệu được đánh giá cao nhất trên GitHub
# (olmOCR — Apache-2.0, và MinerU/marker/docling): nêu rõ thứ tự đọc, công thức
# ra LaTeX, bảng ra Markdown, hình KHÔNG được bịa, chỗ không đọc được thì ghi
# dấu chứ không đoán. Ba quy tắc cuối là chỗ trước đây sai nhiều nhất:
#   · không mốc trang ⇒ mất trang mà không đo được
#   · công thức chép phẳng ⇒ "x²" thành "x2", đề toán sai nghĩa
#   · gặp trang khó thì model đoán tiếp cho trôi chảy ⇒ bịa nội dung SGK
_DOC_PROMPT = (
    "Bạn là bộ OCR tài liệu. Chép TOÀN BỘ nội dung các trang sách này thành "
    "Markdown tiếng Việt.\n\n"
    "BẮT BUỘC:\n"
    "1. Trước mỗi trang, ghi đúng một dòng mốc: <<<TRANG n>>> với n là số tôi "
    "nêu ở cuối prompt — ĐẾM THEO THỨ TỰ TRANG TRONG TỆP, KHÔNG dùng số trang in "
    "trên giấy (hai số này lệch nhau vì tệp tính cả bìa). Nếu trên trang có in số "
    "trang thì ghi thêm ngay sau mốc, dạng: <<<TRANG 80>>> (số in: 79). Phải có "
    "mốc cho MỌI trang, kể cả trang trắng, bìa, hay trang chỉ có hình.\n"
    "2. Đọc theo thứ tự đọc của người: cột trái xong mới sang cột phải; khung/"
    "hộp thoại đọc theo vị trí trên trang.\n"
    "3. Công thức, phân số, số mũ, chỉ số dưới, ký hiệu toán: viết LaTeX — $...$ "
    "trong dòng, $$...$$ tách dòng. KHÔNG chép phẳng (x² không được thành x2).\n"
    "4. Bảng: dựng bảng Markdown. Ô gộp thì lặp lại giá trị cho từng ô.\n"
    "5. Hình minh hoạ: ghi ![](hình: mô tả ngắn những gì THẤY trên hình). Chỉ mô "
    "tả điều nhìn thấy, không suy diễn, không đặt tên nhân vật nếu trang không "
    "ghi tên.\n"
    "6. Giữ nguyên số bài, tên bài, số thứ tự câu hỏi, số bài tập đúng như trên "
    "trang.\n\n"
    "TUYỆT ĐỐI KHÔNG:\n"
    "· Không tóm tắt, không diễn giải, không thêm lời dẫn hay nhận xét.\n"
    "· Không bịa nội dung. Chữ nào mờ/bị che/không đọc được thì ghi [không đọc "
    "được] tại đúng chỗ đó — thà thiếu một chữ còn hơn đoán sai một câu.\n"
    "· Không bỏ trang. Trang trắng thì ghi mốc rồi để trống.\n"
    "· Không lặp lại một đoạn nhiều lần.\n"
    "· Không thêm lời mở đầu kiểu \"Dưới đây là nội dung\" — bắt đầu ngay bằng "
    "mốc <<<TRANG n>>>."
)


def _pages_seen(md: str) -> set[int]:
    """Số trang mà model THẬT SỰ trả về, đọc từ mốc <<<TRANG n>>>."""
    return {int(m.group(1)) for m in _PAGE_MARK_RE.finditer(md or "")}


# Ngưỡng nhận một dòng là "lặp bệnh lý". VLM đọc ảnh đôi khi rơi vào vòng lặp
# và nhả cùng một dòng hàng trăm lần — đầu ra dài, trông như có nội dung, nên
# mọi phép kiểm theo độ dài đều lọt.
_DEGEN_MIN_LEN = 12
_DEGEN_REPEAT = 8
# Dòng chỉ gồm mấy ký tự này là KẺ SẴN, không phải nội dung: chỗ trống điền
# đáp án, đường kẻ ngang, viền bảng Markdown. Vở bài tập có hàng chục dòng như
# nhau là chuyện thường — tính chúng vào phép đo lặp thì chính những quyển vở
# bài tập cần nạp lại bị loại vì "lặp vòng".
_DEGEN_FILLER = set(".…_-—–=|*+ \t·•’'\"")


def _is_filler(line: str) -> bool:
    return bool(line) and set(line) <= _DEGEN_FILLER


def _looks_degenerate(md: str) -> bool:
    """True khi đầu ra bị lặp vòng — nhận nó vào kho là nhồi rác vào RAG.

    Bỏ qua dòng kẻ sẵn (xem ``_DEGEN_FILLER``) rồi mới đo, theo hai hướng:
      · lặp LIỀN KỀ từ 8 dòng giống nhau — dấu hiệu model rơi vào vòng lặp;
      · một dòng chiếm QUÁ NỬA đầu ra — lặp xen kẽ, dài mà rỗng nghĩa.
    """
    lines = [ln.strip() for ln in (md or "").splitlines()
             if len(ln.strip()) >= _DEGEN_MIN_LEN and not _is_filler(ln.strip())]
    if len(lines) < _DEGEN_REPEAT:
        return False
    run = 1
    for a, b in zip(lines, lines[1:]):
        run = run + 1 if a == b else 1
        if run >= _DEGEN_REPEAT:
            return True
    from collections import Counter
    _top, n = Counter(lines).most_common(1)[0]
    return n >= _DEGEN_REPEAT and n >= len(lines) * 0.5
# Số trang mỗi lượt gọi. Cả quyển một lượt thì đầu ra bị cắt cụt (134 trang ≈
# 60k token markdown, vượt trần output), nên cắt khối. 20 trang ≈ 12k token —
# an toàn, mà vẫn ít hơn 20 lần so với gửi từng trang một.
_PAGES_PER_CALL = 20
# Trần dung lượng mỗi khối gửi đi. Gemini chặn 50 MB/PDF, base64 phình 4/3
# (30 MB → ~40 MB trên dây), nên 30 MB là ngưỡng an toàn.
_MAX_CHUNK_BYTES = 30 * 1024 * 1024
# Thử lại mỗi khối khi model lỗi. Nghỉ 4s → 8s → 16s, đủ để qua đợt nghẽn nhịp
# mà không kéo dài vô tận.
_CHUNK_RETRIES = 4
_RETRY_BASE = 4.0
# Chẻ đôi khối khi model trả THIẾU trang. Sâu 4 tầng: 20→10→5→3→1 trang, tức
# xấu nhất vẫn về được từng trang một.
_SPLIT_DEPTH = 4
# Trần số lượt gọi model cho MỘT quyển. Chẻ đôi làm số lượt tăng, không có trần
# thì một quyển hỏng nặng có thể ngốn hết hạn mức của cả buổi nạp.
_MAX_CALLS_PER_BOOK = 120


def _chunk_prompt(a1: int, b1: int) -> str:
    """Prompt cho một khối, có nêu SỐ TRANG THẬT để đối chiếu lại được."""
    n = b1 - a1 + 1
    if n == 1:
        which = f"Tệp PDF kèm theo có đúng 1 trang: trang số {a1} của quyển sách."
    else:
        which = (f"Tệp PDF kèm theo có {n} trang: các trang số {a1} đến {b1} của "
                 f"quyển sách (trang đầu của tệp là trang {a1}).")
    return (f"{_DOC_PROMPT}\n\n{which}\n"
            f"Đầu ra phải có đủ {n} mốc <<<TRANG n>>>, với n chạy từ {a1} đến {b1} "
            f"theo đúng thứ tự trang trong tệp. Số in trên giấy có thể khác — "
            f"vẫn dùng {a1}..{b1} cho mốc.")


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
    calls = [0]          # đếm lượt gọi model cho cả quyển
    unverified: list[tuple[int, int]] = []   # khối model phớt lờ mốc trang

    def _ask(blob: bytes, a1: int, b1: int) -> tuple[str, str]:
        """Gửi một khối, trả (markdown, lý do hỏng). Đã gồm thử lại giãn cách."""
        uri = "data:application/pdf;base64," + base64.b64encode(blob).decode()
        last = ""
        for attempt in range(_CHUNK_RETRIES):
            if calls[0] >= _MAX_CALLS_PER_BOOK:
                return "", f"vượt trần {_MAX_CALLS_PER_BOOK} lượt gọi cho một quyển"
            if attempt:
                time.sleep(_RETRY_BASE * (2 ** (attempt - 1)))
            calls[0] += 1
            resp = call_model(mid, [
                {"role": "user", "content": [
                    {"type": "text", "text": _chunk_prompt(a1, b1)},
                    {"type": "file_data", "file_data": {"file_uri": uri}},
                ]},
            ], timeout=600, max_tokens=32000, no_smart_home=True)
            if resp.get("error"):
                last = str(resp["error"])[:150]
                continue
            cand = content_of(resp).strip()
            if p2w.looks_like_ocr_failure(cand):
                last = "model trả lỗi thay vì nội dung"
                continue
            if _looks_degenerate(cand):
                # Lặp vòng: đầu ra dài nên mọi phép kiểm theo độ dài đều lọt,
                # mà nội dung là rác. Thử lại thay vì nhồi vào RAG.
                last = "đầu ra lặp vòng"
                continue
            return cand, ""
        return "", last

    def _range(a: int, b: int, depth: int, blob: bytes | None = None) -> None:
        """OCR trang a..b (0-index) và ghi kết quả vào ``out``/``missing``.

        Điểm khác bản trước: ĐỐI CHIẾU mốc trang. Khối 20 trang mà model chỉ
        trả 8 trang thì trước đây được nhận như đủ — mất 12 trang không ai
        biết. Giờ thiếu thì chẻ đôi khối rồi hỏi lại từng nửa.
        """
        if blob is None:
            chunk = fitz.open()
            chunk.insert_pdf(src, from_page=a, to_page=b)
            blob = chunk.tobytes()
            chunk.close()
        a1, b1 = a + 1, b + 1
        md, why = _ask(blob, a1, b1)
        if not md:
            logger.warning("sgk_taphuan.book_markdown: khối %s-%s hỏng: %s",
                           a1, b1, why)
            missing.append((a1, b1))
            return
        seen = _pages_seen(md)
        want = set(range(a1, b1 + 1))
        lost = sorted(want - seen)
        if not lost:
            out.append(md)
            return
        if not seen:
            # Model phớt lờ hẳn yêu cầu mốc trang. Chẻ đôi cũng vô ích vì lần
            # nào nó cũng phớt lờ — nhận nội dung nhưng ghi rõ là KHÔNG kiểm
            # chứng được, thà biết mình không biết.
            logger.warning("sgk_taphuan.book_markdown: khối %s-%s không có mốc "
                           "trang nào — nhận nội dung nhưng không kiểm chứng được",
                           a1, b1)
            unverified.append((a1, b1))
            out.append(md)
            return
        if b > a and depth < _SPLIT_DEPTH:
            # Mốc trang CÓ hoạt động (thấy một phần) nên phần thiếu là thiếu
            # thật. Chẻ đôi: khối nhỏ hơn thì model đọc hết.
            mid_pt = a + (b - a) // 2
            logger.info("sgk_taphuan.book_markdown: khối %s-%s thiếu trang %s → chẻ đôi",
                        a1, b1, lost)
            _range(a, mid_pt, depth + 1)
            _range(mid_pt + 1, b, depth + 1)
            return
        # Hết đường chẻ: nhận phần đọc được, ghi nhận phần mất.
        out.append(md)
        for p in lost:
            missing.append((p, p))

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
                missing.append((start + 1, end + 1))
                start = end + 1
                continue
            try:
                _range(start, end, 0, blob)
            finally:
                # Luôn tiến, kể cả khi khối lỗi — nếu không thì vòng while lặp
                # vô hạn trên đúng khối hỏng đó.
                start = end + 1
    finally:
        src.close()

    body = "\n\n---\n\n".join(out)
    if unverified:
        # Không phải "mất trang", mà là "không biết có mất hay không". Ghi vào
        # nội dung để người đọc file .md biết phần này chưa được đối chiếu.
        n = sum(b - a + 1 for a, b in unverified)
        body += ("\n\n---\n\n> ℹ️ KHÔNG KIỂM CHỨNG ĐƯỢC số trang ở "
                 + ", ".join(f"{a}–{b}" for a, b in unverified)
                 + f" ({n} trang): model không đặt mốc trang nào, nên không đối "
                   "chiếu được đủ/thiếu.\n")
        logger.warning({"event": "sgk_taphuan_khong_kiem_chung",
                        "pdf": str(pdf_path), "so_trang": n, "khoi": unverified})
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


# Mỗi trang chi tiết taphuan có 4 loại tài liệu, phân biệt bằng TIỀN TỐ slug của
# link đọc: sgk- (sách học sinh) · sgv- (sách giáo viên) · vbt- (vở bài tập) ·
# tai-lieu-tap-huan- (tài liệu bồi dưỡng GV). Nội dung khác nhau hoàn toàn.
_DOC_KIND: tuple[tuple[str, str], ...] = (
    ("sgk-", "sgk"),
    ("sgv-", "sgv"),
    ("vbt-", "vbt"),
    ("tai-lieu-tap-huan", "tap_huan"),
)

# Tiền tố ĐO THẬT trên kho 2026-07-28, xếp từ cụ thể tới chung. Bốn khe hở của
# bảng ``_DOC_KIND`` phía trên, phát hiện khi quét cả 12 lớp:
#   · "shs-"      = Sách Học Sinh, tức CHÍNH LÀ SGK. Trước rơi vào "other" nên
#                   sách học sinh lớp 2 bị đẩy sang kho tài liệu.
#   · "sgvtieng…" NXB gõ thiếu gạch nối ("sgvtieng-viet-1-tap-hai", 210 trang) —
#                 dùng tiền tố "sgv" không gạch để hứng cả hai cách viết.
#   · "tap-viet-" Tập viết: vở luyện viết, gần vở bài tập nhất.
#   · "tai-lieu"  phải xét TRƯỚC "sgk" vì có slug
#                 "tai-lieu-tap-huan-day-hoc-theo-sgk-moi-mon-…".
#   · "sbt-"      = Sách Bài Tập (40 quyển trên kho) — cùng mục đích với vở bài
#                   tập nên về CÙNG kho `vbt`, không mở thêm một chiều phân loại
#   · "khbd-"     = Kế hoạch bài dạy — tài liệu cho giáo viên, trả lời đúng câu
#                   "dạy bài này thế nào", nên về cùng kho với sách giáo viên
_DOC_KIND_PREFIX: tuple[tuple[str, str], ...] = (
    ("tai-lieu", "tap_huan"),
    ("tap-huan", "tap_huan"),
    ("sgv", "sgv"),
    ("khbd", "sgv"),
    ("shs", "sgk"),
    ("sgk", "sgk"),
    ("vbt", "vbt"),
    ("sbt", "vbt"),
    ("tap-viet", "vbt"),
)

DOC_KIND_LABEL = {
    "sgk": "SGK",
    # Nhãn nói cả hai vì kho gộp cả hai tiền tố: sgv- và khbd- (kế hoạch bài
    # dạy), sbt- (sách bài tập) và vbt- (vở bài tập). Ghi mỗi "SGV" thì một quyển
    # kế hoạch bài dạy vào kho lại tự nhận là sách giáo viên.
    "sgv": "SGV/KHBD (sách giáo viên · kế hoạch bài dạy)",
    "vbt": "VBT/SBT (vở & sách bài tập)",
    "tap_huan": "Tài liệu tập huấn",
    "other": "Tài liệu",
}


def doc_kind(reader_url: str) -> str:
    """Loại tài liệu suy từ tiền tố slug trong link đọc. 'other' = không rõ.

    Vì sao cần: `reader_urls()` cố ý CHỈ lấy `sgk-` để không nhồi sách giáo viên
    và vở bài tập vào kho SGK. Nhưng người dùng dán THẲNG link `/doc-sach/` thì
    đường `import-url` nhận nguyên link đó, bỏ qua bộ lọc — và một quyển SGV sẽ
    vào kho SGK mang nhãn "SGK", rồi bot trích sách giáo viên như thể là sách của
    học sinh. Nhận diện ở đây để cho vào ĐÚNG kho với ĐÚNG nhãn.
    """
    slug = str(reader_url or "").rstrip("/").rsplit("/", 1)[-1].lower()
    for pre, kind in _DOC_KIND_PREFIX:
        if slug.startswith(pre):
            return kind
    # Không tiền tố nào khớp: slug TRẦN bắt đầu bằng tên môn thì là sách học
    # sinh ("tieng-anh-2-global-success", 78 trang — đúng cỡ một quyển SGK, và
    # trang chi tiết của nó không có quyển "sgk-" nào khác). Trả "other" ở đây
    # thì SGK bị đẩy sang kho tài liệu và bot không tra được sách chính.
    for pre, _codes in _SLUG_SUBJECT:
        if slug.startswith(pre):
            return "sgk"
    return "other"


def is_sample(reader_url: str) -> bool:
    """True khi chỉ là BÀI MẪU, không phải cả quyển.

    Kho có nhiều vở bài tập dạng "vbt-toan-1-tap-1-bai-mau" chỉ 8–14 trang.
    Vẫn đáng nạp (thấy được kiểu ra bài tập) nhưng PHẢI gắn nhãn: để bot tưởng
    nó có cả quyển vở bài tập thì nó sẽ khẳng định chắc nịch về những bài tập
    không hề nằm trong đó.

    Đo cả kho 2026-07-28: 135/145 vở & sách bài tập là bài mẫu, 10 quyển còn lại
    cũng chỉ 4–19 trang. Tức mảng bài tập gần như CHỈ có mẫu — biết điều đó mới
    đặt đúng kỳ vọng thay vì tưởng đã có cả kho bài tập.

    NXB viết cả hai cách: "bai-mau" và "ban-mau"
    (sbt-ngu-van-8-tap-hai-ban-mau). Bắt thiếu một cách là quyển đó vào kho mà
    không có nhãn cảnh báo.
    """
    s = str(reader_url or "").lower()
    return "bai-mau" in s or "ban-mau" in s


def COLLECTION_FOR_SET(book_set: str = "", kind: str = "sgk") -> str:
    """Collection RAG theo BỘ SÁCH và LOẠI tài liệu.

    Tách hẳn collection chứ không chỉ ghi vào tiêu đề chunk: cùng một lớp–môn mà
    hai bộ là hai chương trình khác nhau, để chung kho thì truy vấn "bài 5 Toán
    4" kéo về cả hai và bot trả lời trộn. Sách giáo viên / vở bài tập càng phải
    tách — chúng không phải nội dung học sinh học.

        sgk  + bộ chính → kb_giao_duc
        sgk  + bộ N     → kb_giao_duc_bo{N}
        sgv            → kb_giao_duc_sgv
        vbt            → kb_giao_duc_vbt
        tap_huan/other → kb_giao_duc_tailieu
    """
    k = str(kind or "sgk").strip() or "sgk"
    # Loại KHÔNG phải sgk: soi chiếu lại bảng duy nhất ở sgk_fetch.KIND_COLLECTION
    # (chiều phụ thuộc là module này → sgk_fetch, nên bảng nằm ở đó). Giữ bảng
    # thứ hai ở đây là mở đường cho việc thêm loại một chỗ mà chỗ kia vẫn cho vào
    # kho cũ — và cái sai đó im lặng.
    if k != "sgk":
        return sf.KIND_COLLECTION.get(k, "kb_giao_duc_tailieu")
    bs = str(book_set or "").strip()
    return f"kb_giao_duc_bo{bs}" if bs else "kb_giao_duc"


def _ingest_pdf(pdf_path: str, *, grade: int, subject: str, title: str,
                source_name: str, mode: str = "append",
                keep_pdf: bool = True, drop_pdf_on_rag_ok: bool = False,
                book_set: str = "", kind: str = "sgk") -> dict[str, Any]:
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
            keep_pdf=keep_pdf, drop_pdf_on_rag_ok=drop_pdf_on_rag_ok,
            collection=COLLECTION_FOR_SET(book_set, kind),
            # CHỈ sách học sinh của bộ chính được ghi vào .md của SGK gốc.
            # `search_sgk` đọc .md và không phân biệt bộ hay loại tài liệu, nên
            # ghi SGV/VBT/bộ khác vào đó là trả lời trộn ở đường offline.
            write_md=(kind == "sgk" and not str(book_set or "").strip()),
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


def import_reader(reader_url: str, *, grade: int, subject: str,
                  max_pages: int = 0, mode: str = "append",
                  label: str = "", keep_pdf: bool = True,
                  drop_pdf_on_rag_ok: bool = False,
                  book_set: str = "", kind: str = "") -> dict[str, Any]:
    """Nạp ĐÚNG MỘT trang đọc sách đã biết link — dùng cho ô 'dán URL' trên web.

    Khác :func:`import_book` ở chỗ không tra danh mục: người dùng đã chỉ đúng
    quyển nào, lớp nào, môn nào, nên không đoán lại.
    """
    sub = sf.normalize_subject(subject)
    g = int(grade)
    if g not in tw.GRADES:
        return {"ok": False, "error": f"grade phải 1–12, nhận {grade}"}
    if not sub:
        return {"ok": False, "error": f"không nhận ra môn: {subject}"}

    imgs = page_images(reader_url)
    if not imgs:
        return {"ok": False, "error": "không lấy được ảnh trang từ link này"}

    # `label` đi vào tiêu đề mọi chunk RAG. Nạp cả hai bộ sách thì PHẢI truyền
    # tên quyển + bộ vào đây, không thì trong cùng lớp–môn có hai chương trình mà
    # chunk không phân biệt được, bot trả lời trộn hai bộ mà không biết.
    # Loại tài liệu suy từ chính link nếu người gọi không nói rõ.
    k = (kind or "").strip() or doc_kind(reader_url)
    label = label.strip() or (
        f"{DOC_KIND_LABEL.get(k, 'Tài liệu')} lớp {g} · {sf.SUBJECT_LABEL.get(sub, sub)}")
    with tempfile.TemporaryDirectory() as td:
        pdf_path = str(Path(td) / "sach.pdf")
        built = build_pdf(imgs, pdf_path, max_pages=max_pages)
        if not built.get("ok"):
            return {"ok": False, "error": f"ghép PDF lỗi: {built.get('error')}"}
        res = _ingest_pdf(pdf_path, grade=g, subject=sub, title=label,
                          source_name=reader_url, mode=mode, keep_pdf=keep_pdf,
                          drop_pdf_on_rag_ok=drop_pdf_on_rag_ok,
                          book_set=book_set, kind=k)
    return {**res, "pages": built.get("pages"), "source": reader_url,
            "doc_kind": k, "doc_kind_label": DOC_KIND_LABEL.get(k, "Tài liệu")}


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


__all__ = ["list_books", "reader_urls", "page_images", "build_pdf", "import_reader",
           "import_book", "subjects_of_slug"]
