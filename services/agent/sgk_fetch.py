"""Tự tìm & tự nạp SGK / sách nâng cao vào RAG (Giáo viên).

Bổ sung "bước tìm nguồn" còn thiếu của pipeline SGK đã có sẵn
(``teacher_workspace.import_sgk_pdf`` / ``push_sgk_to_rag`` / ``search_sgk``):

  1. ``find_sources`` — dựng câu tìm kiếm tiếng Việt (lớp, môn, bộ sách,
     năm học) rồi chạy qua ``search_service`` (KHÔNG dựng stack search mới),
     lọc kết quả "trông giống PDF" và xếp hạng theo số từ khoá khớp tiêu đề.
     CHỈ tìm — không tự tải.
  2. ``fetch_and_ingest`` — tải 1 URL (lấy từ ``find_sources`` hoặc do người
     dùng tự cung cấp — KHÔNG BAO GIỜ tự bịa URL khác) qua
     ``services.net_guard.safe_fetch`` (chặn SSRF), xác minh đúng là PDF, rồi
     nạp vào SGK/RAG. Ghi lại provenance (url, năm, bộ sách, loại, thời điểm)
     để trích dẫn và để lần chạy sau không tải trùng.

Tách 2 kho RAG rõ ràng:
  - SGK chính thức  → collection ``kb_giao_duc`` (dùng nguyên
    ``import_sgk_pdf`` — ghi cả file ``lop{N}/{mon}.md`` để tra cứu offline
    lẫn RAG).
  - Sách nâng cao / mở rộng kiến thức → collection ``kb_nangcao`` — KHÔNG bao
    giờ ghi đè vào file ``.md`` của SGK gốc, để tra cứu offline
    (``search_sgk``) không bị lẫn nội dung ngoài chương trình.
  - Môn nào có trong ``teacher_workspace.SUBJECTS`` thì đi đúng pipeline gốc
    (ghi cả ``lop{N}/{mon}.md`` lẫn RAG); môn không nhận ra thì nạp thẳng RAG
    như sách nâng cao, KHÔNG đụng file .md của SGK.

An toàn — nói thật, không đoán bừa:
  - Đây là PDF ĐĂNG CÔNG KHAI tìm được trên mạng — KHÔNG đảm bảo đúng bản/năm
    xuất bản cụ thể. Không tìm được nguồn tốt → báo thật, KHÔNG nạp đại một
    quyển có thể sai.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from services import net_guard
from services.agent import teacher_workspace as tw
from services.config import DATA_DIR

logger = logging.getLogger(__name__)

# ── Danh mục môn ────────────────────────────────────────────────────────────
# CHỈ soi chiếu lại teacher_workspace, KHÔNG giữ danh sách thứ hai. Trước đây có
# hai bảng song song và đó chính là lý do thêm môn ở một chỗ mà chỗ kia vẫn
# không nhận.
SUBJECT_LABEL: dict[str, str] = dict(tw.SUBJECT_LABEL)
SUBJECTS: tuple[str, ...] = tuple(tw.SUBJECTS)

# Từ khoá tiếng Việt dùng để dựng câu tìm kiếm — chữ thường không dấu hoa, đọc
# tự nhiên trong câu query (SUBJECT_LABEL là nhãn hiển thị, viết hoa đầu).
_SUBJECT_QUERY: dict[str, str] = {
    "toan": "toán", "tviet": "tiếng việt", "van": "ngữ văn", "anh": "tiếng anh",
    "sudia": "lịch sử và địa lí",
    "su": "lịch sử", "dia": "địa lí",
    "ly": "vật lí", "hoa": "hoá học", "sinh": "sinh học",
}

# Lưới đỡ cho bí danh chỉ dùng ở tầng này (tên tiếng Anh, biến thể dấu). Bảng
# chính là teacher_workspace.SUBJECT_ALIASES. Mọi giá trị ở đây PHẢI là mã có
# trong SUBJECTS — normalize_subject bên dưới lọc lại lần nữa cho chắc.
_EXTRA_ALIASES: dict[str, str] = {
    "ly": "ly", "lý": "ly", "vat_ly": "ly", "vat ly": "ly", "vật lý": "ly",
    "physics": "ly",
    "hoa": "hoa", "hóa": "hoa", "hoa_hoc": "hoa", "hoa hoc": "hoa",
    "hóa học": "hoa", "chemistry": "hoa",
    "sinh": "sinh", "sinh_hoc": "sinh", "sinh hoc": "sinh", "sinh học": "sinh",
    "biology": "sinh",
    "su": "su", "sử": "su", "lich_su": "su", "lich su": "su", "lịch sử": "su",
    "history": "su",
    "dia": "dia", "địa": "dia", "dia_ly": "dia", "dia ly": "dia",
    "địa lý": "dia", "dia li": "dia", "địa lí": "dia", "geography": "dia",
}

# 3 bộ SGK hiện hành (chương trình GDPT 2018) — dùng để dựng query + đoán bộ
# sách từ tiêu đề kết quả tìm kiếm.
_CURRICULA: tuple[str, ...] = (
    "kết nối tri thức", "chân trời sáng tạo", "cánh diều",
)

# Site THẬT SỰ đăng SGK **và máy tải được**. Thứ tự = kết quả đo thật từ máy
# chủ (2026-07-27), không phải theo trang nào "chính thức" hơn:
#
#   hanhtrangso.nxbgd.vn  200  ← kho NXBGDVN, còn sống, tải được
#   vndoc / taimienphi / download.vn  200
#   taphuan.nxbgd.vn      403  ← LOẠI: xem chú thích bên dưới
#   sachmem.vn            000  ← LOẠI: không kết nối được
#
# taphuan.nxbgd.vn nay là kho chính thức của NXBGDVN (hanhtrangso đã được
# thông báo sẽ ngừng) và với NGƯỜI DÙNG thì miễn phí, không cần đăng nhập —
# nhưng nó nấp sau Cloudflare, trả 403 kèm trang captcha cho mọi client không
# phải trình duyệt. Đưa nó vào đây chỉ tạo ra ứng viên chắc chắn 403 lúc tải,
# lại chiếm suất trong hạn mức 3 ứng viên/tổ hợp nên đẩy tổ hợp thành
# "failed" thay vì để nó thử nguồn khác. Muốn lấy sách từ taphuan thì phải
# đi bằng trình duyệt thật (stack captcha-solver/chromium sẵn có trong image)
# — việc đó tách riêng, KHÔNG nhét vào đường tìm kiếm này.
#
# Vì sao cần whitelist: trước đây find_sources bắn câu hỏi tiếng Việt vào
# CrossRef/OpenAlex/PubMed/Wikipedia/Internet Archive — kho DOI học thuật và
# bách khoa, KHÔNG bao giờ chứa SGK Việt Nam. Kết quả là 0 ứng viên thật, kèm
# 429 hàng loạt vì bắn quá dày.
_SGK_SITES: tuple[str, ...] = (
    "hanhtrangso.nxbgd.vn",
    "vndoc.com",
    "taimienphi.vn",
    "download.vn",
)

# Nghỉ giữa hai truy vấn của CÙNG một tổ hợp. DDG cắt TLS (SSL EOF) khi bị bắn
# dồn từ một IP nên nhịp thưa là điều kiện sống còn, không phải tối ưu vặt.
_QUERY_GAP = 1.2
# Có đủ số ứng viên này thì dừng hỏi tiếp — tổ hợp dễ chỉ tốn 1 truy vấn.
_ENOUGH_CANDIDATES = 3

# collection RAG theo loại tài liệu — sách nâng cao TÁCH RIÊNG khỏi SGK để bot
# không dạy vượt chương trình như thể đó là nội dung SGK chính thức.
KIND_COLLECTION: dict[str, str] = {"sgk": "kb_giao_duc", "nangcao": "kb_nangcao"}

_ROOT = Path(DATA_DIR) / "agent" / "teacher"
_INDEX_PATH = _ROOT / "sgk_fetch_index.json"
_MAX_BYTES = 120 * 1024 * 1024  # trần tải PDF SGK/nâng cao (sách scan có thể nặng)
_idx_lock = threading.RLock()

_PDF_URL_RE = re.compile(r"https?://[^\s<>\"'\)]+", re.I)
_YEAR_RE = re.compile(r"\b(20[0-2]\d)\b")


def normalize_subject(subject: str) -> str | None:
    """Chuẩn hoá tên môn. ``None`` = không nhận diện.

    Bảng bí danh đã dồn về `teacher_workspace.SUBJECT_ALIASES` (đủ 10 môn), nên
    ở đây chỉ gọi lại. `_EXTRA_ALIASES` bên dưới giữ làm lưới đỡ cho bí danh nào
    còn sót riêng ở tầng này.
    """
    s = str(subject or "").strip().lower()
    if not s:
        return None
    got = tw._normalize_subject(s)
    if got:
        return got
    # Lọc lại theo SUBJECTS: bảng lưới đỡ từng còn bí danh trỏ vào mã đã bỏ
    # khỏi danh mục (gdcd, tin) và hàm này trả về mã không tồn tại — chỗ gọi
    # tưởng nhận diện thành công rồi ghi ra file lop{N}/gdcd.md không ai đọc.
    cand = _EXTRA_ALIASES.get(s) or s
    return cand if cand in SUBJECTS else None


def _fold(text: str) -> str:
    """Hạ thường + bỏ dấu tiếng Việt (để so khớp từ khoá không phân biệt dấu)."""
    import unicodedata
    s = (text or "").lower().replace("đ", "d").replace("Đ", "d")
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _looks_like_pdf(url: str, title: str = "") -> bool:
    u = (url or "").lower()
    if ".pdf" in u:
        return True
    return "pdf" in (title or "").lower()


def _detect_curriculum(text: str) -> str:
    folded = _fold(text or "")
    for cur in _CURRICULA:
        if _fold(cur) in folded:
            return cur
    return ""


def _detect_year(text: str) -> str:
    m = _YEAR_RE.search(text or "")
    return m.group(1) if m else ""


_MCP_LINE_RE = re.compile(r"^\s*\d+\.\s+\*\*(?P<title>.+?)\*\*\s*$")


def _parse_mcp_search_text(text: str) -> list[dict[str, str]]:
    """Bóc {title, url, snippet} từ khối markdown mà tool ``search_web`` trả về.

    vn_search trả VĂN BẢN đã format (``1. **Tiêu đề**`` / snippet / link) chứ
    không phải JSON, nên phải bóc tay. Dòng nào không khớp thì bỏ, không đoán.
    """
    out: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        m = _MCP_LINE_RE.match(raw_line)
        if m:
            if cur.get("url"):
                out.append(cur)
            cur = {"title": m.group("title").strip(), "url": "", "snippet": ""}
            continue
        if not cur:
            continue
        if line.startswith("http://") or line.startswith("https://"):
            cur["url"] = line
        elif line:
            cur["snippet"] = (cur.get("snippet", "") + " " + line).strip()
    if cur.get("url"):
        out.append(cur)
    return out


def _web_search(query: str, limit: int = 8) -> list[dict[str, str]]:
    """Tìm web cho ĐÚNG mục đích lấy PDF sách — chỉ gọi vn_search (DuckDuckGo).

    KHÔNG dùng ``search_service.search_all``: hàm đó fan-out song song sang
    CrossRef/OpenAlex/PubMed/Wikipedia/Internet Archive — toàn kho học thuật,
    không hề chứa SGK Việt Nam, mà vẫn tính vào hạn mức và làm cạn tài nguyên.
    """
    from services import mcp_client

    try:
        text = mcp_client.call_mcp_tool(
            "search_web", {"query": query, "limit": limit}, server_id="vn_search",
        )
    except Exception as exc:
        logger.warning("sgk_fetch._web_search: gọi vn_search lỗi: %s", exc)
        text = None
    if text:
        parsed = _parse_mcp_search_text(text)
        if parsed:
            return parsed

    # vn_search chưa cài/đang chết → hạ xuống combo backend (TUẦN TỰ, có
    # fallback sẵn), vẫn không đụng tới fan-out học thuật.
    try:
        from services.search_service import search_service
        return [dict(r) for r in (search_service.search(query) or [])]
    except Exception as exc:
        logger.warning("sgk_fetch._web_search: backend dự phòng lỗi: %s", exc)
        return []


def _score_candidate(
    url: str, title: str, grade: int, subject_word: str,
    curriculum_hint: str, year_hint: str,
) -> dict[str, Any]:
    folded_title = _fold(title)
    cur_guess = _detect_curriculum(title) or curriculum_hint
    year_guess = _detect_year(title) or _detect_year(url) or year_hint
    terms = [str(grade), _fold(subject_word), "pdf"]
    if cur_guess:
        terms.append(_fold(cur_guess))
    if year_guess:
        terms.append(year_guess)
    hits = sum(1 for t in terms if t and t in folded_title)
    confidence = round(hits / max(1, len(terms)), 2)
    try:
        domain = urlparse(url).hostname or ""
    except Exception:
        domain = ""
    # Cộng điểm cho site thật sự đăng SGK — tiêu đề trên các site này thường
    # gọn ("Toán 8 - Kết nối tri thức") nên chấm theo từ khoá dễ bị thiệt so
    # với một blog nhồi đủ chữ lớp/môn/pdf vào tiêu đề.
    dom_folded = domain.lower()
    if any(dom_folded == s or dom_folded.endswith("." + s) for s in _SGK_SITES):
        confidence = round(min(1.0, confidence + 0.25), 2)
    return {
        "title": title[:200],
        "url": url,
        "source": domain,
        "year_guess": year_guess,
        "curriculum_guess": cur_guess,
        "confidence": confidence,
    }


def find_sources(
    grade: int, subject: str, year: str = "", kind: str = "sgk",
) -> list[dict[str, Any]]:
    """Tìm nguồn PDF công khai (SGK hoặc sách nâng cao) qua search_service.

    KHÔNG tự tải — chỉ tìm và trả ứng viên đã lọc "trông giống PDF", xếp hạng
    theo số từ khoá khớp tiêu đề (lớp, môn, bộ sách, "pdf"). Trả ``[]`` nếu
    grade/subject không hợp lệ hoặc không tìm thấy gì đủ tin cậy — KHÔNG bịa
    kết quả.
    """
    try:
        g = int(grade)
    except (TypeError, ValueError):
        return []
    if g not in tw.GRADES:
        return []
    sub = normalize_subject(subject)
    if not sub:
        return []
    kind = kind if kind in KIND_COLLECTION else "sgk"
    word = _SUBJECT_QUERY.get(sub, SUBJECT_LABEL.get(sub, sub))
    year_s = str(year or "").strip()

    # Thứ tự truy vấn = thứ tự khả năng trúng, chạy TUẦN TỰ và dừng sớm khi đã
    # đủ ứng viên. Tổ hợp dễ chỉ tốn 1 lượt tìm; tổ hợp khó mới đi hết danh
    # sách. Trước đây bắn cả 4 câu SONG SONG cho mọi tổ hợp, nhân với 120 tổ
    # hợp là vài nghìn request — đủ để tự ăn 429 và cạn file descriptor.
    queries: list[tuple[str, str]] = []
    if kind == "nangcao":
        for phrase in ("sách bài tập nâng cao", "bồi dưỡng học sinh giỏi"):
            q = f"{phrase} {word} lớp {g} pdf"
            if year_s:
                q = f"{q} {year_s}"
            queries.append((q, ""))
    else:
        base = f"sách giáo khoa {word} lớp {g}"
        # 1) Kho chính thức + các site có sách trước — hỏi thẳng bằng site:
        for site in _SGK_SITES:
            queries.append((f"site:{site} {base}", ""))
        # 2) Rồi mới tới câu mở, có/không kèm bộ sách
        q = f"{base} pdf"
        if year_s:
            q = f"{q} {year_s}"
        queries.append((q, ""))
        for cur in _CURRICULA:
            q = f"{base} {cur} pdf"
            if year_s:
                q = f"{q} {year_s}"
            queries.append((q, cur))

    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for i, (q, cur_hint) in enumerate(queries):
        if i:
            time.sleep(_QUERY_GAP)
        try:
            results = _web_search(q)
        except Exception as exc:
            logger.warning("sgk_fetch.find_sources: search lỗi (%s…): %s", q[:50], exc)
            continue
        for r in results:
            title = str(r.get("title") or "").strip()
            url = str(r.get("url") or "").strip()
            snippet = str(r.get("snippet") or "")
            urls = ([url] if url else []) + _PDF_URL_RE.findall(snippet)
            for u in urls:
                u = u.rstrip(").,;]>\"'")
                if not u or u in seen or not _looks_like_pdf(u, title):
                    continue
                seen.add(u)
                candidates.append(
                    _score_candidate(u, title or u, g, word, cur_hint, year_s)
                )
        if len(candidates) >= _ENOUGH_CANDIDATES:
            break

    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates[:8]


# ── Provenance index (theo dõi đã nạp gì, tránh tải trùng) ─────────────────


def _load_index() -> dict[str, Any]:
    with _idx_lock:
        if not _INDEX_PATH.is_file():
            return {}
        try:
            data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def _save_index(data: dict[str, Any]) -> None:
    with _idx_lock:
        _INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        _INDEX_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _filename_from_url(url: str) -> str:
    try:
        name = os.path.basename(urlparse(url).path) or "sgk.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        return name[:120]
    except Exception:
        return "sgk.pdf"


def _archive_pdf(tmp_path: str, grade: int, subject: str, kind: str, fname: str) -> None:
    """Lưu bản PDF gốc để audit — dùng thư mục RIÊNG với teacher_workspace's
    imports/ (đường dẫn đó gắn với 3 môn gốc do import_sgk_pdf quản lý)."""
    try:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^\w.\-]+", "_", fname)[:80]
        dest_dir = _ROOT / "imports_extra" / kind / f"lop{grade}" / subject
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_path, dest_dir / f"{stamp}_{safe}")
    except Exception as exc:
        logger.warning("sgk_fetch: lưu bản PDF gốc lỗi (bỏ qua): %s", exc)


def fetch_and_ingest(
    grade: int,
    subject: str,
    url: str,
    *,
    year: str = "",
    kind: str = "sgk",
    curriculum: str = "",
    dry_run: bool = False,
    force: bool = False,
    keep_pdf: bool = True,
    drop_pdf_on_rag_ok: bool = False,
) -> dict[str, Any]:
    """Tải 1 URL (từ ``find_sources`` hoặc do người dùng tự cung cấp) rồi nạp
    vào SGK/RAG. KHÔNG BAO GIỜ tự đoán/bịa URL khác — ``url`` phải do caller
    đưa vào tường minh. Luôn tải qua ``net_guard.safe_fetch`` (chặn SSRF).

    - kind='sgk' + môn gốc (toan/van/anh) → dùng nguyên
      ``teacher_workspace.import_sgk_pdf`` (ghi file ``lop{g}/{sub}.md`` +
      RAG ``kb_giao_duc``) — giống hệt import thủ công qua Settings.
    - kind='nangcao' HOẶC môn mới (lý/hoá/sinh/sử/địa/gdcd/tin) → CHỈ nạp RAG
      (``kb_nangcao`` cho nâng cao; ``kb_giao_duc`` cho SGK môn mới) — KHÔNG
      ghi đè file ``.md`` gốc, tránh lẫn nội dung mở rộng vào tra cứu offline.
    - ``dry_run=True``: chỉ tải + trích thử để xem trước, KHÔNG ghi SGK/RAG.
    - ``force=True``: bỏ qua kiểm tra "đã nạp trước đó", tải lại.
    """
    try:
        g = int(grade)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"grade phải 1–12, nhận {grade!r}"}
    if g not in tw.GRADES:
        return {"ok": False, "error": f"grade phải 1–12, nhận {grade}"}
    sub = normalize_subject(subject)
    if not sub:
        return {"ok": False, "error": f"Môn không nhận diện được: {subject!r}"}
    kind = kind if kind in KIND_COLLECTION else "sgk"
    collection = KIND_COLLECTION[kind]
    url_s = str(url or "").strip()
    if not url_s:
        return {"ok": False, "error": "Thiếu url (lấy từ find_sources hoặc URL người dùng cung cấp)"}

    idx = _load_index()
    prev = idx.get(url_s)
    if prev and prev.get("ok") and not force and not dry_run:
        out = {"ok": True, "skipped": True, "reason": (
            "URL này đã được nạp trước đó — bỏ qua để tránh trùng lặp "
            "(force=true nếu muốn nạp lại)."
        )}
        out.update({k: v for k, v in prev.items() if k != "ok"})
        return out

    try:
        data = net_guard.safe_fetch(url_s, timeout=90, max_bytes=_MAX_BYTES)
    except net_guard.BlockedURL as exc:
        return {"ok": False, "error": f"URL bị chặn (an toàn SSRF): {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"Tải file lỗi: {exc}"}

    if not data or data[:4] != b"%PDF":
        return {"ok": False, "error": (
            "Nội dung tải về không phải PDF hợp lệ (thiếu header %PDF) — "
            "có thể trang đã chặn tải hoặc trả về trang HTML lỗi. Thử URL khác."
        )}

    fname = _filename_from_url(url_s)
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    result: dict[str, Any] = {}
    rag_info: dict[str, Any] = {}
    try:
        os.write(fd, data)
        os.close(fd)

        mon_label = SUBJECT_LABEL.get(sub, sub)
        head = (
            f"SGK lớp {g} · {mon_label}" if kind == "sgk"
            else f"Nâng cao lớp {g} · {mon_label}"
        )
        if curriculum:
            head = f"{head} · {curriculum}"

        if dry_run:
            try:
                from services.pdf_intent import extract_markdown
                raw = extract_markdown(tmp_path, max_pages=20)
            except Exception as exc:
                return {"ok": False, "error": f"Trích thử PDF lỗi: {exc}"}
            return {
                "ok": True, "dry_run": True, "bytes": len(data),
                "preview_chars": len(raw or ""),
                "preview": (raw or "")[:600],
                "note": "Chưa ghi SGK/RAG (dry_run=True). Gọi lại dry_run=False để nạp thật.",
            }

        if kind == "sgk" and sub in tw.SUBJECTS:
            # 3 môn gốc → tái dùng NGUYÊN pipeline sẵn có (ghi .md + RAG).
            result = tw.import_sgk_pdf(
                tmp_path, grade=g, subject=sub, mode="append",
                title=head, source_name=fname, keep_pdf=keep_pdf,
                drop_pdf_on_rag_ok=drop_pdf_on_rag_ok,
            )
            rag_info = result.get("rag") or {}
        else:
            # Môn mới hoặc sách nâng cao → chỉ nạp RAG, không đụng .md SGK gốc.
            try:
                from services.pdf_intent import extract_markdown
                from services import pdf_to_word as p2w
                max_pages = int(getattr(p2w, "TEACHER_SGK_MAX_PAGES", 0) or 0)
                raw = extract_markdown(tmp_path, max_pages=max_pages)
            except Exception as exc:
                return {"ok": False, "error": f"Trích PDF lỗi: {exc}"}
            if not (raw or "").strip():
                return {"ok": False, "error": "PDF không trích được chữ (scan cần OCR)"}
            md = tw._md_from_pdf_text(raw, title=head)
            # PDF chỉ để audit; RAG đã tách khỏi nó từ lúc trích. Sách dựng từ
            # ảnh trang rất nặng nên keep_pdf=False là bỏ hẳn bước lưu.
            # Nhánh này tự đẩy RAG bên dưới nên chỉ lưu PDF khi được yêu cầu
            # giữ HẲN; drop_pdf_on_rag_ok thì khỏi lưu rồi xoá cho tốn I/O.
            if keep_pdf and not drop_pdf_on_rag_ok:
                _archive_pdf(tmp_path, g, sub, kind, fname)
            rag_info = tw.push_sgk_to_rag(
                md, title=head, grade=g, subject=sub, source=fname,
                collection=collection,
            )
            result = {
                "ok": bool(rag_info.get("ok")), "grade": g, "subject": sub,
                "workspace": f"lop{g}-{sub}", "source": fname,
                "chars": len(md), "chapters": len(re.findall(r"^##\s+", md, re.M)),
                "note": "Chỉ nạp RAG (không ghi file .md SGK gốc).",
            }
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    record = {
        "url": url_s, "grade": g, "subject": sub, "kind": kind,
        "collection": collection, "curriculum": curriculum or "",
        "year": str(year or ""), "source_name": fname,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ok": bool(result.get("ok")),
        "chunks_added": (rag_info or {}).get("chunks_added"),
        "workspace": result.get("workspace") or f"lop{g}-{sub}",
    }
    idx[url_s] = record
    _save_index(idx)

    out = dict(result)
    out["provenance"] = record
    out["source"] = fname
    return out


def status(*, grade: int | None = None, subject: str | None = None) -> dict[str, Any]:
    """Đã nạp gì qua tính năng tự tìm/tự nạp — lọc theo lớp/môn (tuỳ chọn)."""
    idx = _load_index()
    g_filter = None
    if grade not in (None, ""):
        try:
            gi = int(grade)
            if gi in tw.GRADES:
                g_filter = gi
        except (TypeError, ValueError):
            pass
    sub_filter = normalize_subject(subject) if subject else None
    rows = []
    for rec in idx.values():
        if g_filter is not None and rec.get("grade") != g_filter:
            continue
        if sub_filter and rec.get("subject") != sub_filter:
            continue
        rows.append(rec)
    rows.sort(key=lambda r: str(r.get("fetched_at") or ""), reverse=True)
    return {"ok": True, "total": len(rows), "items": rows[:100]}


def nangcao_hits(
    query: str, *, grade: int | None = None, subject: str | None = None,
    top_k: int = 3,
) -> str:
    """Best-effort tra kb_nangcao qua MCP hub (``ask_nangcao``) — dùng để bổ
    sung cho ``search_sgk`` một đoạn "kiến thức mở rộng" TÁCH RÕ khỏi SGK.

    Trả "" nếu không có gì / lỗi (kb_nangcao có thể chưa từng được nạp, hoặc
    vn-mcp-hub chưa có tool ask_nangcao cho collection mới — không có gì để
    xác minh từ trong repo này, nên luôn tự làm hỏng-êm, không ném lỗi)."""
    q = (query or "").strip()
    if not q:
        return ""
    try:
        from services.mcp_client import call_mcp_tool
    except Exception:
        return ""
    try:
        text = str(
            call_mcp_tool("ask_nangcao", {"question": q}, server_id="kb_nangcao") or ""
        ).strip()
    except Exception as exc:
        logger.debug("sgk_fetch.nangcao_hits: %s", exc)
        return ""
    low = text.lower()
    if not text or len(text) < 20 or "chưa có dữ liệu" in low or "chưa sẵn sàng" in low:
        return ""
    if len(text) > 1500:
        text = text[:1500] + "…"
    return (
        "\n\n---\n"
        "**📘 Kiến thức mở rộng (KHÔNG có trong SGK — kb_nangcao):**\n"
        f"{text}\n\n"
        "_Lưu ý: đây là nội dung nâng cao/mở rộng, không phải sách giáo khoa "
        "chính thức — khi trả lời cần nói rõ với học sinh đây là phần mở rộng, "
        "không có trong SGK, để tránh nhầm là nội dung bắt buộc._"
    )
