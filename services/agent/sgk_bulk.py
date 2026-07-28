"""Nạp TOÀN BỘ SGK từ kho taphuan vào RAG — lần lượt theo lớp, nối lại được.

Vì sao phải có module riêng thay vì dùng `sgk_autofill`: cái đó đi bằng TÌM KIẾM
WEB (`sgk_fetch.find_sources`) nên phụ thuộc may mắn của kết quả search. Ở đây
nguồn là kho chính thức taphuan.nxbgd.vn, đi đúng đường danh mục → trang đọc →
ảnh từng trang → PDF tạm → OCR khối trang → RAG.

QUY MÔ, đo thật 2026-07-28: bộ chính 89 quyển / 12 lớp; riêng "Lịch sử và Địa lí
4" đã 127 trang. Cả hai bộ ước 8.000–10.000 trang ảnh, tức khoảng 400–500 lượt
gọi model vision (20 trang/lượt). Chạy tuần tự là NHIỀU NGÀY.

Vì vậy hai điều bắt buộc, không phải tuỳ chọn:

  1. NỐI LẠI ĐƯỢC theo từng quyển. Tiến độ ghi ra đĩa sau MỖI quyển; chạy lại là
     đi tiếp, không tải lại từ đầu. Không có cái này thì 8.000 trang là canh bạc —
     mất mạng ở quyển thứ 70 là mất cả công đoạn.
  2. KHÔNG giữ PDF (`keep_pdf=False`). PDF dựng từ ảnh trang của 89 quyển là hàng
     chục GB, mà nó chỉ để audit — tra cứu đi qua .md và RAG. Muốn giữ thì bật
     `keep_pdf=True` và tự chịu dung lượng.

VỀ VIỆC NẠP CẢ HAI BỘ SÁCH (`all_sets=True`, gồm `cac-bo-sach-khac?id_book=…`):
`sgk_taphuan.list_books` mặc định TẮT đường này, lý do ghi ngay trong hàm đó —
bộ khác là chương trình khác cho CÙNG môn, nạp chung vào một kho thì bot có thể
trả lời trộn hai bộ mà không biết đang dùng bộ nào. Người vận hành đã chọn nạp cả
hai, nên ĐÃ TÁCH COLLECTION theo bộ: bộ chính → `kb_giao_duc`, bộ khác →
`kb_giao_duc_bo{N}` (xem `sgk_taphuan.COLLECTION_FOR_SET`). Mỗi kho một chương
trình, muốn tra bộ nào thì hỏi kho đó. Bộ khác cũng KHÔNG ghi vào `.md` của SGK
gốc vì `search_sgk` đọc `.md` và không phân biệt được bộ. Ngoài ra mỗi chunk vẫn
mang tiêu đề có tên quyển + mã bộ (`_label_of`) để câu trả lời dẫn được nguồn.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from services.agent import sgk_taphuan as tp
from services.agent import teacher_workspace as tw
from services.config import DATA_DIR

logger = logging.getLogger(__name__)

STATE_PATH = Path(DATA_DIR) / "agent" / "teacher" / "sgk_bulk_state.json"

_lock = threading.RLock()
_thread: Optional[threading.Thread] = None
_stop = threading.Event()

# Nghỉ giữa hai quyển. Kho của trường học — đừng đấm.
_PAUSE_BOOK = 4.0


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_state() -> dict[str, Any]:
    try:
        if STATE_PATH.is_file():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("sgk_bulk: đọc state lỗi %s", exc)
    return {}


def _write_state(state: dict[str, Any]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        # Thay nguyên tử: mất điện giữa lúc ghi thì state cũ vẫn đọc được, chứ
        # không để lại file JSON nửa vời làm mất TOÀN BỘ tiến độ.
        tmp.replace(STATE_PATH)
    except Exception as exc:
        logger.warning("sgk_bulk: ghi state lỗi %s", exc)


def _label_of(book: dict[str, Any], subject: str, kind: str = "sgk", *,
              sample: bool = False) -> str:
    """Tiêu đề đi vào MỌI chunk RAG của quyển này.

    Phải có tên quyển + bộ sách: nạp cả hai bộ thì đây là thứ duy nhất giúp phân
    biệt hai chương trình khác nhau trong cùng lớp–môn.

    Phải có LOẠI tài liệu: nhãn cứng "SGK" cho mọi thứ khiến một chunk sách giáo
    viên vẫn tự giới thiệu là SGK, rồi bot trích lời hướng dẫn dạy như thể là nội
    dung học sinh phải học.

    ``sample=True`` (slug có "bai-mau") phải nói thẳng đây chỉ là vài trang mẫu:
    để bot tưởng nó có cả quyển vở bài tập thì nó sẽ khẳng định chắc nịch về
    những bài tập không hề nằm trong đó.
    """
    g = int(book.get("grade") or 0)
    mon = tw.SUBJECT_LABEL.get(subject, subject)
    slug = str(book.get("slug") or "")
    vol = str(book.get("volume") or "")
    bset = str(book.get("book_set") or "")
    parts = [f"{_KIND_SHORT.get(kind, 'Tài liệu')} lớp {g}", mon]
    if vol:
        parts.append(vol)
    parts.append(f"[{slug}]")
    parts.append(f"bộ {bset}" if bset else "bộ chính")
    if sample:
        parts.append("CHỈ BÀI MẪU, không phải cả quyển")
    return " · ".join(parts)


# Nhãn ngắn theo loại, dùng ở đầu mọi chunk RAG.
# Soi chiếu lại sgk_taphuan chứ KHÔNG giữ bảng thứ hai: hai bảng song song là lý
# do thêm loại ở một chỗ mà chỗ kia vẫn gắn nhãn cũ.
_KIND_SHORT = dict(tp.DOC_KIND_LABEL)

# Loại nạp mặc định. Chỉ SGK — thêm SGV/VBT là nhân số quyển lên khoảng ba lần,
# phải do người vận hành chọn chứ không bật sẵn.
DEFAULT_KINDS: tuple[str, ...] = ("sgk",)

# Thứ tự nạp trong MỘT quyển. SGK trước: dừng giữa đường thì thứ quan trọng nhất
# (sách học sinh) đã vào kho, chứ không phải mới có sách giáo viên.
# "slide" đứng ĐẦU vì nó gần như miễn phí: chữ thật từ Google Slides, 0 lượt gọi
# vision, cả kho vài trăm KB. Chạy trước thì dù có dừng ngay sau đó vẫn đã có
# phân bổ tuần–tiết của mọi quyển.
KIND_ORDER: tuple[str, ...] = ("slide", "sgk", "sgv", "vbt", "tap_huan")

# Loại KHÔNG đi qua trang /doc-sach/ nên không nằm trong `reader_urls()`.
NON_READER_KINDS: frozenset[str] = frozenset({"slide"})


def normalize_kinds(kinds: Iterable[str]) -> tuple[str, ...]:
    """Lọc loại lạ, xếp theo :data:`KIND_ORDER`. Rỗng thì về mặc định.

    Không im lặng nhận loại lạ: gõ sai "sgv " hay "SGV" vẫn nhận, nhưng "abc"
    thì bỏ — nếu để lọt xuống ``reader_urls`` thì nó khớp 0 tài liệu và cả lượt
    chạy báo "không thấy link đọc sách", rất khó lần ra là do gõ sai.
    """
    asked = {str(x).strip().lower() for x in (kinds or ()) if str(x).strip()}
    return tuple(k for k in KIND_ORDER if k in asked) or DEFAULT_KINDS


def plan(grades: Iterable[int] | None = None, *,
         all_sets: bool = True) -> list[dict[str, Any]]:
    """Danh sách QUYỂN sẽ nạp, theo thứ tự lớp tăng dần.

    Đơn vị công việc là MỘT QUYỂN (không phải một tổ hợp lớp–môn): một môn có thể
    có tập một + tập hai + chuyên đề, và nối lại được theo quyển thì mất mạng chỉ
    tốn lại đúng quyển đang chạy.
    """
    gs = [int(g) for g in (grades or tw.GRADES) if int(g) in tw.GRADES]
    out: list[dict[str, Any]] = []
    for g in sorted(gs):
        try:
            books = tp.list_books(g, all_sets=all_sets)
        except Exception as exc:
            logger.warning("sgk_bulk: danh mục lớp %s lỗi: %s", g, exc)
            continue
        for b in books:
            subs = b.get("subjects") or ()
            if not subs:
                # Sách không nhận ra môn (Âm nhạc, Mĩ thuật, Tiếng Hàn…) —
                # KHÔNG nạp, nhưng vẫn liệt kê để người vận hành thấy mà quyết.
                out.append({**b, "subject": "", "skip": "không nhận ra môn"})
                continue
            for sub in subs:
                out.append({**b, "subject": sub, "skip": ""})
    return out


def _key(item: dict[str, Any]) -> str:
    """Khoá nhận dạng một đơn vị công việc — dùng để bỏ qua thứ đã nạp."""
    return f"{item.get('grade')}|{item.get('subject')}|{item.get('slug')}|{item.get('book_set') or ''}"


def _doc_key(item: dict[str, Any], kind: str, reader_url: str) -> str:
    """Khoá cho MỘT TÀI LIỆU trong quyển, không phải cho cả quyển.

    Phải gồm cả slug trang đọc: một trang chi tiết có thể có hai tài liệu cùng
    loại (vd hai tập vở bài tập), dùng chung khoá thì cái sau bị coi là "đã nạp"
    và bị bỏ qua vĩnh viễn.
    """
    tail = str(reader_url or "").rstrip("/").rsplit("/", 1)[-1]
    return f"{_key(item)}|{kind}|{tail}"


def run(
    *,
    grades: Iterable[int] | None = None,
    all_sets: bool = True,
    kinds: Iterable[str] = DEFAULT_KINDS,
    keep_pdf: bool = False,
    max_pages: int = 0,
    skip_done: bool = True,
    dry_run: bool = False,
    pause: float = _PAUSE_BOOK,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Chạy đồng bộ (blocking). Muốn chạy nền thì dùng :func:`start`."""
    want_kinds = normalize_kinds(kinds)
    items = plan(grades, all_sets=all_sets)
    todo = [x for x in items if not x.get("skip")]
    prev = read_state()
    done_map: dict[str, Any] = dict(prev.get("books") or {}) if skip_done else {}

    state: dict[str, Any] = {
        "kinds": list(want_kinds),
        "started_at": _now(),
        "finished_at": "",
        "running": True,
        "dry_run": bool(dry_run),
        "all_sets": bool(all_sets),
        "keep_pdf": bool(keep_pdf),
        "total": len(todo),
        "index": 0,
        "current": "",
        "current_grade": 0,
        "counts": {"ok": 0, "failed": 0, "skipped": 0, "no_subject": 0},
        # Giữ theo KHOÁ chứ không phải danh sách: chạy lại nhiều lần vẫn tra được
        # quyển nào xong, và không phình vô hạn.
        "books": done_map,
        "pages_total": int(prev.get("pages_total") or 0),
        "chunks_total": int(prev.get("chunks_total") or 0),
        "skipped_no_subject": [x.get("slug") for x in items if x.get("skip")],
    }
    _write_state(state)

    for i, item in enumerate(todo, start=1):
        if _stop.is_set():
            state["stopped"] = True
            break
        k = _key(item)
        g, sub, slug = int(item["grade"]), str(item["subject"]), str(item["slug"])
        state["index"] = i
        state["current_grade"] = g
        state["current"] = f"lớp {g} · {tw.SUBJECT_LABEL.get(sub, sub)} · {slug}"

        # Không kiểm "đã nạp" ở mức quyển nữa — kiểm ở mức TÀI LIỆU bên dưới.
        # Chặn ở đây thì lần chạy sau xin thêm SGV/VBT của một quyển đã có SGK sẽ
        # bị bỏ qua toàn bộ, tức không bao giờ nạp thêm được loại mới.
        bset = str(item.get("book_set") or "")
        # Một trang chi tiết có NHIỀU tài liệu (SGK + SGV + VBT + tập huấn). Nạp
        # từng cái, mỗi cái một dòng state riêng → nối lại được ở mức TÀI LIỆU,
        # không phải mức quyển: mất mạng lúc đang nạp VBT thì SGK đã xong không
        # phải OCR lại.
        # Slide đi đường RIÊNG: không phải link /doc-sach/ nên reader_urls()
        # không thấy. Chữ thật từ Google Slides — 0 lượt gọi vision, ~6,5 KB mỗi
        # bộ, và 192/198 quyển có. Làm TRƯỚC vì gần như miễn phí: dừng ngay sau
        # đó thì vẫn đã có phân bổ tuần–tiết của mọi quyển.
        if "slide" in want_kinds:
            sk = _doc_key(item, "slide", str(item.get("url") or ""))
            if not (skip_done and done_map.get(sk, {}).get("status") == "ok"):
                srow = {"grade": g, "subject": sub, "slug": slug, "book_set": bset,
                        "kind": "slide", "status": "", "pages": 0, "chunks": 0,
                        "error": "", "ts": _now()}
                state["current"] = (f"lớp {g} · {tw.SUBJECT_LABEL.get(sub, sub)} · "
                                    f"slide · {slug}")
                if dry_run:
                    srow["status"] = "ok"
                    srow["error"] = "(dry_run — chưa nạp)"
                else:
                    try:
                        r = tp.import_slides(str(item.get("url") or ""), grade=g,
                                             subject=sub, book_set=bset)
                        if r.get("ok"):
                            srow["status"] = "ok"
                            srow["chunks"] = int(r.get("chunks_added") or 0)
                            srow["slides"] = int(r.get("slides") or 0)
                            srow["collection"] = r.get("collection") or ""
                            state["chunks_total"] += srow["chunks"]
                        else:
                            srow["status"] = "failed"
                            srow["error"] = str(r.get("error") or "")[:300]
                    except Exception as exc:
                        srow["status"] = "failed"
                        srow["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
                state["counts"][srow["status"]] = \
                    state["counts"].get(srow["status"], 0) + 1
                state["books"][sk] = srow
                done_map[sk] = srow
                _write_state(state)

        reader_kinds = tuple(k for k in want_kinds if k not in NON_READER_KINDS)
        docs: list[tuple[str, str]] = []   # (reader_url, kind)
        fetch_err = ""
        if not reader_kinds:
            # Chỉ xin slide — xong ở trên, không cần tải trang chi tiết lần nữa.
            continue
        if dry_run:
            docs = [("", kd) for kd in reader_kinds]
        else:
            try:
                for u in tp.reader_urls(str(item.get("url") or ""), reader_kinds):
                    docs.append((u, tp.doc_kind(u)))
            except Exception as exc:
                fetch_err = f"{type(exc).__name__}: {str(exc)[:200]}"

        if not docs:
            row = {"grade": g, "subject": sub, "slug": slug, "book_set": bset,
                   "kind": "", "status": "failed", "pages": 0, "chunks": 0,
                   "error": fetch_err or ("không thấy link đọc sách loại "
                                          + "/".join(reader_kinds)
                                          + " trong trang chi tiết"),
                   "ts": _now()}
            state["counts"]["failed"] += 1
            state["books"][k] = row
            done_map[k] = row
            _write_state(state)
            continue

        for reader_url, kind in docs:
            if _stop.is_set():
                state["stopped"] = True
                break
            dk = _doc_key(item, kind, reader_url)
            if skip_done and done_map.get(dk, {}).get("status") == "ok":
                state["counts"]["skipped"] += 1
                _write_state(state)
                continue
            sample = bool(reader_url) and tp.is_sample(reader_url)
            row = {"grade": g, "subject": sub, "slug": slug, "book_set": bset,
                   "kind": kind, "reader": reader_url, "sample": sample,
                   "status": "", "pages": 0, "chunks": 0, "error": "",
                   "ts": _now()}
            state["current"] = (f"lớp {g} · {tw.SUBJECT_LABEL.get(sub, sub)} · "
                                f"{_KIND_SHORT.get(kind, kind)} · {slug}")
            if dry_run:
                row["status"] = "ok"
                row["error"] = "(dry_run — chưa nạp)"
            else:
                try:
                    res = tp.import_reader(
                        reader_url, grade=g, subject=sub, mode="append",
                        max_pages=max_pages,
                        label=_label_of(item, sub, kind, sample=sample),
                        keep_pdf=keep_pdf, book_set=bset, kind=kind,
                    )
                    if res.get("ok"):
                        row["status"] = "ok"
                        row["pages"] = int(res.get("pages") or 0)
                        rag = res.get("rag") or {}
                        row["chunks"] = int(rag.get("chunks_added") or 0)
                        row["collection"] = tp.COLLECTION_FOR_SET(bset, kind)
                        state["pages_total"] += row["pages"]
                        state["chunks_total"] += row["chunks"]
                    else:
                        row["status"] = "failed"
                        row["error"] = str(res.get("error") or "")[:300]
                except Exception as exc:
                    row["status"] = "failed"
                    row["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"

            state["counts"][row["status"]] = state["counts"].get(row["status"], 0) + 1
            # Ghi state SAU MỖI TÀI LIỆU — đây là điểm nối lại. Ghi thưa hơn là
            # mất công của những thứ đã xong.
            state["books"][dk] = row
            done_map[dk] = row
            _write_state(state)
            logger.info({"event": "sgk_bulk_book", "grade": g, "subject": sub,
                         "slug": slug, "kind": kind, "status": row["status"],
                         "pages": row["pages"], "chunks": row["chunks"],
                         "i": i, "total": len(todo)})
        if on_progress:
            try:
                on_progress(dict(state))
            except Exception:
                pass
        if pause > 0 and i < len(todo) and not _stop.is_set():
            _stop.wait(pause)

    state["running"] = False
    state["finished_at"] = _now()
    _write_state(state)
    return state


def start(**kw: Any) -> dict[str, Any]:
    """Chạy NỀN. Trả ngay, xem tiến độ bằng :func:`read_state`."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return {"ok": False, "message": "đang chạy rồi — dừng trước khi chạy lại",
                    "state": read_state()}
        _stop.clear()

        def _worker() -> None:
            try:
                run(**kw)
            except Exception as exc:
                logger.exception("sgk_bulk: chạy nền lỗi")
                st = read_state()
                st["running"] = False
                st["finished_at"] = _now()
                st["error"] = str(exc)[:300]
                _write_state(st)

        _thread = threading.Thread(target=_worker, name="sgk-bulk", daemon=True)
        _thread.start()
    return {"ok": True, "message": "đã bắt đầu nạp nền — theo dõi ở trạng thái"}


def stop() -> dict[str, Any]:
    """Dừng sau khi xong QUYỂN đang chạy (không cắt giữa quyển làm mất công)."""
    _stop.set()
    return {"ok": True, "message": "sẽ dừng sau khi xong quyển đang nạp"}


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def summary(state: dict[str, Any] | None = None) -> str:
    st = state or read_state()
    if not st:
        return "Chưa chạy nạp SGK hàng loạt lần nào."
    c = st.get("counts") or {}
    lines = [
        f"{'Đang chạy' if st.get('running') else 'Đã xong'} · "
        f"{st.get('index', 0)}/{st.get('total', 0)} quyển",
        f"✅ {c.get('ok', 0)} nạp được · ↩︎ {c.get('skipped', 0)} bỏ qua (đã có) · "
        f"❌ {c.get('failed', 0)} lỗi",
        f"📄 {st.get('pages_total', 0)} trang · 🧩 {st.get('chunks_total', 0)} chunks",
    ]
    if st.get("current"):
        lines.append(f"Đang: {st['current']}")
    bad = [v for v in (st.get("books") or {}).values() if v.get("status") == "failed"]
    if bad:
        lines.append("Lỗi gần nhất:")
        for r in bad[-5:]:
            lines.append(f"  • lớp {r.get('grade')} {r.get('slug')}: {r.get('error')}")
    return "\n".join(lines)


# ── Dung lượng đang chiếm + dọn PDF ─────────────────────────────────────────

def storage_report() -> dict[str, Any]:
    """PDF/markdown đang chiếm bao nhiêu — để quyết có xoá PDF hay không."""
    root = Path(DATA_DIR) / "agent" / "teacher"
    out: dict[str, Any] = {"ok": True, "root": str(root)}

    def _walk(d: Path, pat: str) -> tuple[int, int]:
        n = total = 0
        if d.is_dir():
            for p in d.rglob(pat):
                try:
                    if p.is_file():
                        n += 1
                        total += p.stat().st_size
                except OSError:
                    continue
        return (n, total)

    # HAI thư mục PDF, cố ý tách nhau từ trước: `imports/` do
    # teacher_workspace.import_sgk_pdf ghi, `imports_extra/` do
    # sgk_fetch._archive_pdf ghi (đường URL / sách nâng cao). Đếm thiếu một chỗ
    # là báo dung lượng sai rồi tưởng đã dọn sạch.
    a_n, a_b = _walk(root / "imports", "*.pdf")
    e_n, e_b = _walk(root / "imports_extra", "*.pdf")
    pdf_n, pdf_b = a_n + e_n, a_b + e_b
    md_n, md_b = _walk(root / "sgk", "*.md")
    out["pdf_files"] = pdf_n
    out["pdf_bytes"] = pdf_b
    out["pdf_imports"] = {"files": a_n, "bytes": a_b}
    out["pdf_imports_extra"] = {"files": e_n, "bytes": e_b}
    out["md_files"] = md_n
    out["md_bytes"] = md_b
    out["hint"] = (
        "PDF chỉ để audit — tra cứu đi qua .md và RAG, nên xoá PDF KHÔNG mất "
        "kiến thức đã nạp. Nạp hàng loạt nên để keep_pdf=false ngay từ đầu."
    )
    # Chi tiết theo lớp để biết lớp nào phình.
    per: list[dict[str, Any]] = []
    imp = root / "imports"
    if imp.is_dir():
        for d in sorted(imp.iterdir()):
            if d.is_dir() and d.name.startswith("lop"):
                n, b = _walk(d, "*.pdf")
                if n:
                    per.append({"grade": d.name, "files": n, "bytes": b})
    out["per_grade"] = per
    return out


def purge_pdfs(*, grade: int | None = None) -> dict[str, Any]:
    """Xoá bản PDF đã lưu trong ``imports/``. KHÔNG đụng .md và RAG.

    An toàn vì PDF chỉ là bản lưu để audit: markdown theo chương/bài và chunks
    trong Chroma đã tách khỏi nó từ lúc nạp.
    """
    base = Path(DATA_DIR) / "agent" / "teacher"
    roots = [base / "imports", base / "imports_extra"]
    n = freed = 0
    for root in roots:
        if not root.is_dir():
            continue
        if grade:
            # imports/lop4/... còn imports_extra/{kind}/lop4/... nên phải quét
            # theo tên thư mục thay vì ghép đường dẫn cứng.
            targets = [d for d in root.rglob(f"lop{int(grade)}") if d.is_dir()]
        else:
            targets = [root]
        for t in targets:
            for p in list(t.rglob("*.pdf")):
                try:
                    sz = p.stat().st_size
                    p.unlink()
                    n += 1
                    freed += sz
                except OSError as exc:
                    logger.warning("sgk_bulk.purge_pdfs: %s: %s", p.name, exc)
    logger.info({"event": "sgk_pdf_purged", "files": n, "freed_bytes": freed,
                 "grade": grade or "all"})
    return {"ok": True, "deleted": n, "freed_bytes": freed,
            "scope": f"lop{grade}" if grade else "tất cả",
            "note": "Chỉ xoá PDF. Markdown SGK và RAG giữ nguyên."}


__all__ = ["plan", "run", "start", "stop", "is_running", "read_state",
           "summary", "storage_report", "purge_pdfs"]
