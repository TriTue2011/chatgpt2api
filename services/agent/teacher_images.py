"""Kho ẢNH cho việc giảng bài — CHỈ dùng cho phần giáo viên.

Vì sao chỉ giáo viên: giảng bài cần hiện đúng trang sách đang giảng, nên ảnh là
NỘI DUNG, không phải bản lưu tạm. Các đường RAG khác (wiki, ảnh chụp gửi chat,
MCP) chỉ cần chữ — lưu ảnh cho chúng là phình dung lượng mà không ai xem. Đừng
gọi module này từ ngoài `services/agent/teacher_*`.

MÃ HOÁ — chọn bằng ĐO THẬT trên hai trang sách 1094×1536 (2026-07-29):

    trang Hoá 11 (bảng + công thức chỉ số dưới)   PNG gốc 450 KB
    trang Tiếng Việt 1 (4 khung truyện tranh màu) PNG gốc 791 KB

      mã hoá        Hoá 11    TViệt 1    nhỏ hơn PNG
      JPEG q72       140 KB     128 KB      3–6×      ← mức dự án đang dùng
      WebP q60        70 KB      61 KB      7–13×
      AVIF q40        42 KB      40 KB     11–20×
      AVIF q30        32 KB      30 KB     14–27×     ← CHỌN

Chọn AVIF q30 vì đã kiểm CHẤT LƯỢNG, không chỉ dung lượng: nén q30 rồi giải nén
lại, vùng chữ nhỏ nhất của trang Hoá (bảng dãy đồng đẳng + trắc nghiệm) vẫn đọc
rõ nguyên văn — cả CₙH₂ₙ₊₂, C₃H₇OH, (n≥1) và đủ dấu tiếng Việt.

Quy mô: cả kho 70.698 trang × 32 KB ≈ 2,2 GB; chỉ SGK bộ chính (13.501 trang)
≈ 420 MB. Cùng số trang đó mà dùng JPEG q72 là ≈ 9,4 GB.

KHÔNG cần thêm phụ thuộc: Pillow có AVIF trong lõi từ 11.3, dự án ghim
`pillow>=12.2.0`. Vẫn có đường rơi về WebP nếu môi trường nào đó thiếu — im lặng
lưu thất bại thì lúc giảng mới phát hiện không có ảnh.
"""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR

logger = logging.getLogger(__name__)

ROOT = Path(DATA_DIR) / "agent" / "teacher" / "page_img"

# Xem bảng đo ở docstring module. MAX_EDGE 1536 = đúng cạnh dài ảnh gốc của kho,
# tức KHÔNG thu nhỏ — thu nhỏ chỉ tiết kiệm thêm ~10% mà làm chữ nhỏ khó đọc.
FMT = "AVIF"
QUALITY = 30
FMT_FALLBACK = "WEBP"
QUALITY_FALLBACK = 60
MAX_EDGE = 1536
_EXT = {"AVIF": "avif", "WEBP": "webp", "JPEG": "jpg"}


def _safe(name: str) -> str:
    """Tên an toàn để làm đường dẫn — chặn ../ và ký tự lạ."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(name or "")).strip("._-")[:120]


def encode(raw: bytes, *, max_edge: int = MAX_EDGE) -> tuple[bytes, str]:
    """Ảnh bất kỳ → (blob đã nén, phần mở rộng). Rỗng = không mã hoá được.

    Thứ tự thử: AVIF q30 → WebP q60. KHÔNG rơi về PNG: PNG của trang sách nặng
    gấp 14 lần mà chẳng nét hơn khi đọc.
    """
    try:
        from PIL import Image
    except Exception as exc:
        logger.warning("teacher_images.encode: thiếu Pillow: %s", exc)
        return b"", ""
    try:
        im = Image.open(io.BytesIO(raw))
        # RGB: AVIF/WebP không nhận palette hay CMYK; ảnh có alpha thì dán lên
        # nền trắng (trang sách không cần trong suốt).
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        if max_edge and max(im.size) > max_edge:
            k = max_edge / max(im.size)
            im = im.resize((round(im.width * k), round(im.height * k)),
                           Image.LANCZOS)
    except Exception as exc:
        logger.warning("teacher_images.encode: mở ảnh lỗi: %s", exc)
        return b"", ""

    for fmt, q in ((FMT, QUALITY), (FMT_FALLBACK, QUALITY_FALLBACK)):
        try:
            buf = io.BytesIO()
            im.save(buf, fmt, quality=q)
            return buf.getvalue(), _EXT[fmt]
        except Exception as exc:
            logger.warning("teacher_images.encode: %s lỗi (%s) — thử định dạng sau",
                           fmt, exc)
    return b"", ""


def save_page(slug: str, page: int, raw: bytes) -> str:
    """Lưu ảnh MỘT trang. Trả đường dẫn tương đối trong kho, rỗng = thất bại."""
    s = _safe(slug)
    if not s or int(page) < 1 or not raw:
        return ""
    blob, ext = encode(raw)
    if not blob:
        return ""
    rel = f"{s}/{int(page)}.{ext}"
    out = ROOT / rel
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_bytes(blob)
        tmp.replace(out)
        return rel
    except Exception as exc:
        logger.warning("teacher_images.save_page lỗi (%s): %s", rel, exc)
        return ""


def path_of(rel_or_slug: str, page: int = 0) -> Path | None:
    """Đường dẫn thật của ảnh đã lưu. None = không có.

    Nhận cả đường dẫn tương đối ("slug/80.avif") lẫn (slug, page).
    """
    if page and "/" not in str(rel_or_slug):
        s = _safe(rel_or_slug)
        for ext in _EXT.values():
            p = ROOT / s / f"{int(page)}.{ext}"
            if p.is_file():
                return p
        return None
    p = ROOT / str(rel_or_slug or "").lstrip("/")
    try:
        # Chặn thoát khỏi kho qua ../ dù _safe đã lọc ở đường ghi.
        p.resolve().relative_to(ROOT.resolve())
    except Exception:
        return None
    return p if p.is_file() else None


def store_report() -> dict[str, Any]:
    """Kho ảnh đang chiếm bao nhiêu — để quyết có dọn hay không."""
    n = total = 0
    books: dict[str, dict[str, int]] = {}
    if ROOT.is_dir():
        for p in ROOT.rglob("*"):
            if not p.is_file() or p.suffix == ".tmp":
                continue
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            n += 1
            total += sz
            b = books.setdefault(p.parent.name, {"files": 0, "bytes": 0})
            b["files"] += 1
            b["bytes"] += sz
    return {"ok": True, "root": str(ROOT), "files": n, "bytes": total,
            "books": len(books),
            "avg_bytes": (total // n) if n else 0,
            "per_book": books,
            "hint": (f"Mã hoá {FMT} q{QUALITY} — đo thật ~32 KB/trang trang sách. "
                     "Đây là NỘI DUNG để giảng bài (hiện ảnh đi cùng chữ), không "
                     "phải bản lưu tạm như PDF: xoá là mất phần trực quan.")}


def purge(slug: str = "") -> dict[str, Any]:
    """Xoá ảnh của một quyển, hoặc CẢ kho khi ``slug`` rỗng."""
    target = (ROOT / _safe(slug)) if slug else ROOT
    if not target.is_dir():
        return {"ok": True, "deleted": 0, "freed_bytes": 0}
    n = freed = 0
    for p in target.rglob("*"):
        if p.is_file():
            try:
                freed += p.stat().st_size
                n += 1
            except OSError:
                pass
    try:
        shutil.rmtree(target)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": True, "deleted": n, "freed_bytes": freed,
            "scope": slug or "toàn bộ kho ảnh giáo viên"}


def store_pdf_pages(pdf_path: str | Path, slug: str, *, max_pages: int = 0,
                    dpi: int = 150) -> list[str]:
    """Render từng trang PDF rồi lưu ảnh. Trả danh sách đường dẫn theo THỨ TỰ trang.

    Dùng cho PDF do giáo viên TẢI LÊN — đường đó không có ảnh trên CDN như kho
    taphuan, nên không render và lưu thì sau khi OCR xong là mất hẳn phần trực
    quan: chữ vào kho, còn muốn hiện trang sách lúc giảng thì không có gì để hiện.

    dpi=150 cho trang A4 ra ~1240×1750, thu về cạnh 1536 khi mã hoá. Đủ nét để
    đọc chữ nhỏ (đã kiểm ở mức 1094×1536) mà không render thừa.
    """
    try:
        import fitz
    except Exception as exc:
        logger.warning("teacher_images.store_pdf_pages: thiếu PyMuPDF: %s", exc)
        return []
    out: list[str] = []
    try:
        with fitz.open(str(pdf_path)) as doc:
            total = doc.page_count
            n = min(total, max_pages) if max_pages else total
            for i in range(n):
                try:
                    pix = doc.load_page(i).get_pixmap(dpi=dpi)
                    rel = save_page(slug, i + 1, pix.tobytes("png"))
                except Exception as exc:
                    logger.warning("teacher_images.store_pdf_pages: trang %s lỗi: %s",
                                   i + 1, exc)
                    rel = ""
                # Giữ CHỖ cho trang lỗi bằng chuỗi rỗng: cắt bớt sẽ làm mọi trang
                # sau lệch số, và số trang phải khớp mốc <<<TRANG n>>> của OCR.
                out.append(rel)
    except Exception as exc:
        logger.warning("teacher_images.store_pdf_pages: mở PDF lỗi: %s", exc)
        return out
    return out


# ── Bản đồ TRANG → ẢNH ──────────────────────────────────────────────────────
#
# Nằm ở đây (không ở sgk_taphuan) vì CẢ HAI đường nạp đều cần và chúng không
# import được nhau: sgk_taphuan → teacher_workspace, nên teacher_workspace không
# thể import sgk_taphuan. Module này không import module teacher_* nào nên cả hai
# gọi vào được.
MAP_DIR = Path(DATA_DIR) / "agent" / "teacher" / "pages"


def slug_of(reader_url: str) -> str:
    """Slug ổn định của một quyển, dùng làm tên file bản đồ + thư mục ảnh."""
    tail = str(reader_url or "").rstrip("/").rsplit("/", 1)[-1]
    return _safe(tail)


def save_manifest(source: str, *, grade: int, subject: str, kind: str = "sgk",
                  book_set: str = "", label: str = "",
                  urls: list[str] | None = None,
                  files: list[str] | None = None) -> str:
    """Ghi bản đồ trang. ``urls`` là ảnh trên CDN, ``files`` là ảnh đã lưu ở kho.

    Cho phép có cả hai: kho taphuan có URL sẵn (miễn phí), mà vẫn lưu bản địa
    được nếu muốn phòng CDN đổi đường. PDF tải lên thì chỉ có ``files``.

    Số trang đếm từ 1 theo THỨ TỰ ẢNH — trùng đúng mốc ``<<<TRANG n>>>`` của OCR.
    Lệch một là lúc giảng hiện sai trang.
    """
    s = slug_of(source)
    u = list(urls or [])
    f = list(files or [])
    if not s or not (u or f):
        return ""
    n = max(len(u), len(f))
    pages = []
    for i in range(n):
        row: dict[str, Any] = {"n": i + 1}
        if i < len(u) and u[i]:
            row["url"] = u[i]
        if i < len(f) and f[i]:
            row["file"] = f[i]
        pages.append(row)
    rec = {"slug": s, "source": source, "reader_url": source,
           "grade": int(grade), "subject": subject, "kind": kind or "sgk",
           "book_set": str(book_set or ""), "label": label,
           "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "pages": pages}
    try:
        MAP_DIR.mkdir(parents=True, exist_ok=True)
        out = MAP_DIR / f"{s}.json"
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        tmp.replace(out)
        return str(out)
    except Exception as exc:
        logger.warning("teacher_images.save_manifest lỗi (%s): %s", s, exc)
        return ""


def get_manifest(slug: str) -> dict[str, Any]:
    p = MAP_DIR / f"{slug_of(slug)}.json"
    try:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("teacher_images.get_manifest lỗi (%s): %s", slug, exc)
    return {}


def page_source(slug: str, page: int) -> dict[str, Any]:
    """Nguồn ảnh của MỘT trang: ``{file}`` nếu có bản địa, ``{url}`` nếu chỉ có CDN.

    Ưu tiên bản địa: nó là của mình, không phụ thuộc CDN của kho còn sống hay
    không.
    """
    for row in get_manifest(slug).get("pages") or ():
        if int(row.get("n") or 0) != int(page):
            continue
        out = {"n": int(page)}
        if row.get("file"):
            out["file"] = row["file"]
        if row.get("url"):
            out["url"] = row["url"]
        return out
    return {}


def list_manifests() -> list[dict[str, Any]]:
    """Quyển đã có bản đồ — chỉ metadata, KHÔNG kèm hàng trăm URL mỗi quyển."""
    out: list[dict[str, Any]] = []
    if not MAP_DIR.is_dir():
        return out
    for p in sorted(MAP_DIR.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        pages = rec.get("pages") or []
        row = {k: rec.get(k) for k in ("slug", "source", "grade", "subject",
                                       "kind", "book_set", "label", "saved_at")}
        row["pages"] = len(pages)
        row["local_pages"] = sum(1 for r in pages if r.get("file"))
        out.append(row)
    return out


# ── Không có ảnh thì TẠO ảnh ────────────────────────────────────────────────
#
# Dùng đúng đường tạo ảnh sẵn có của dự án (nhánh Agent "image_gen"), không dựng
# đường thứ hai. Model trả về URL nên PHẢI tải về lưu lại: URL của provider hết
# hạn, mà bài giảng thì cần hiện được ảnh nhiều tháng sau.
_ILLUS_DIR_PREFIX = "_ai"
_ILLUS_MAX_BYTES = 25 * 1024 * 1024


def illustrate(topic: str, *, grade: int = 0, subject: str = "",
               cache_key: str = "", model: str = "") -> dict[str, Any]:
    """Tạo ảnh minh hoạ khi bài giảng KHÔNG có ảnh trang sách.

    Trả ``{ok, file, ai_generated, prompt, error}``.

    ``ai_generated`` LUÔN True và phải được hiện lên giao diện: một ảnh do model
    vẽ mà bày ra cạnh nội dung SGK, học sinh sẽ tin đó là hình trong sách. Đó là
    nói sai với người học, không phải chi tiết kỹ thuật.
    """
    # Kiểm đầu vào TRƯỚC khi import: nạp branches/runtime là kéo theo cả chuỗi
    # config của dự án, không đáng cho một lời gọi chắc chắn bị từ chối.
    t = str(topic or "").strip()
    if not t:
        return {"ok": False, "error": "thiếu nội dung cần vẽ", "ai_generated": True}

    from services import net_guard
    from services.agent.branches import branch_model
    from services.agent.runtime import call_model, content_of, first_image_url

    key = _safe(cache_key or f"lop{grade}_{subject}_{t}")[:100]
    rel = f"{_ILLUS_DIR_PREFIX}/{key}"
    exist = path_of(rel + ".avif") or path_of(rel + ".webp")
    if exist:
        # Vẽ lại là tốn thêm một lượt gọi model cho cùng một hình.
        return {"ok": True, "file": str(exist.relative_to(ROOT)),
                "ai_generated": True, "cached": True, "prompt": ""}

    mon = f" môn {subject}" if subject else ""
    lop = f" lớp {grade}" if grade else ""
    prompt = (f"Hình minh hoạ cho bài học{lop}{mon}: {t}. "
              "Phong cách sách giáo khoa Việt Nam: nét rõ, màu tươi, nền sạch, "
              "KHÔNG chèn chữ vào hình, không watermark, không viền khung.")
    mid = model or branch_model("image_gen")
    resp = call_model(mid, [{"role": "user", "content": f"Vẽ: {prompt}"}],
                      timeout=320, max_tokens=600)
    if resp.get("error"):
        return {"ok": False, "error": f"{mid}: {str(resp['error'])[:200]}",
                "ai_generated": True, "prompt": prompt}
    url = first_image_url(content_of(resp) or "")
    if not url:
        return {"ok": False, "error": f"{mid} không trả về ảnh",
                "ai_generated": True, "prompt": prompt}
    try:
        # allow_hosts=None: host của provider không biết trước. net_guard vẫn
        # chặn IP nội bộ và DNS-rebinding, nên không mở đường SSRF.
        raw = net_guard.safe_fetch(url, timeout=90, max_bytes=_ILLUS_MAX_BYTES)
    except Exception as exc:
        return {"ok": False, "error": f"tải ảnh vừa vẽ lỗi: {str(exc)[:150]}",
                "ai_generated": True, "prompt": prompt}
    blob, ext = encode(raw)
    if not blob:
        return {"ok": False, "error": "không mã hoá được ảnh vừa vẽ",
                "ai_generated": True, "prompt": prompt}
    out = ROOT / f"{rel}.{ext}"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(blob)
    except Exception as exc:
        return {"ok": False, "error": f"lưu ảnh lỗi: {str(exc)[:150]}",
                "ai_generated": True, "prompt": prompt}
    # Ghi kèm nguồn gốc: sau này đọc lại kho còn biết hình nào do model vẽ.
    try:
        (out.parent / f"{key}.json").write_text(json.dumps(
            {"topic": t, "grade": grade, "subject": subject, "model": mid,
             "prompt": prompt, "source_url": url, "ai_generated": True,
             "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return {"ok": True, "file": f"{rel}.{ext}", "ai_generated": True,
            "prompt": prompt, "model": mid, "bytes": len(blob)}
