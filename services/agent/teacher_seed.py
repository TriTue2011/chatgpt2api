"""Tự nạp kho slide giáo dục ngay khi container chạy — deploy là dùng được.

Nạp gì: chữ trong bộ slide "giới thiệu sách" và "tập huấn giáo viên" của mọi
quyển trên taphuan.nxbgd.vn. Đo thật 2026-07-29: 192/198 quyển có slide, 101 bộ
khác nhau tải được, ~2,1 MB CHỮ THẬT. Nội dung là phân bổ tuần–tiết và phương
pháp dạy — thứ mà muốn lấy từ sách giáo viên thì phải OCR hàng trăm trang::

    "Tuần 0: HS làm quen · Tuần 1–6: 1–2 âm chữ · Bài 1: A a"
    "Học vần: chủ yếu 3 vần/bài, không 'tăng tải'"
    "Phần cứng: 10 tiết, 2 tiết linh hoạt"

Vì sao TỰ TẢI mà không đóng gói sẵn nội dung vào image:

  Repo của dự án là repo CÔNG KHAI. Nội dung slide là tài liệu của Nhà xuất bản
  Giáo dục Việt Nam — commit vào repo công khai là phát hành lại tài liệu của
  họ, khác hẳn việc người vận hành tự tải về dùng cho hệ thống của mình. Ở đây
  chỉ commit ĐƯỜNG LẤY (danh mục URL, đã có trong docs/sgk/), còn nội dung do
  chính container tải từ nguồn công khai lúc chạy.

Vì sao KHÔNG cần OCR và không tốn lượt gọi model: bản `/export/txt` của Google
Slides là chữ sẵn. Chỉ ~1% bộ là slide ảnh (nội dung nằm trong ảnh chèn vào) —
những bộ đó bỏ qua ở đây, để đường nạp hàng loạt xử lý bằng OCR.

An toàn khi chạy lại: ghi state theo từng bộ slide, chạy lần hai chỉ làm phần
còn thiếu. Chroma upsert theo id nên nạp trùng cũng không nhân bản chunk.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from services.config import DATA_DIR

logger = logging.getLogger(__name__)

# Danh mục ĐÃ ĐO, commit kèm repo — chỉ URL và metadata, không có nội dung sách.
CATALOG = Path(__file__).resolve().parents[2] / "docs" / "sgk" / \
    "taphuan_catalog_2026-07-28.json"
STATE_PATH = Path(DATA_DIR) / "agent" / "teacher" / "slide_seed_state.json"

COLLECTION = "kb_giao_duc_slide"
_GSLIDE_RE = re.compile(
    r"https://docs\.google\.com/presentation/d/([A-Za-z0-9_-]{20,})")
# PHẢI có googleusercontent.com: `/export/txt` trả 302 sang
# doc-XX-YY-slides.googleusercontent.com (tên máy đổi theo lượt), mà
# `net_guard.safe_fetch` kiểm lại allowlist ở TỪNG bước chuyển hướng. Thiếu host
# này thì mọi lượt tải đều bị chặn — đo thật, đã dính. check_url khớp cả hậu tố
# nên khai tên miền gốc là đủ cho mọi tên máy con.
_GSLIDE_HOSTS = {"docs.google.com", "googleusercontent.com"}
_TXT_MAX_BYTES = 4 * 1024 * 1024
# Dưới mức này coi như slide ẢNH (chữ nằm trong ảnh chèn vào) — bỏ qua ở đây,
# để đường nạp hàng loạt lấy bằng OCR. Đo thật: bộ mỏng nhất có chữ là 656 ký
# tự / 15 slide; các bộ bình thường có trung vị 14.031 ký tự.
#
# HAI mức, không phải một:
#   < _KEEP_MIN   : gần như không có chữ → bỏ hẳn, chờ OCR
#   < _RICH_MIN   : có chữ nhưng mỏng (tiêu đề, tên tác giả) → VẪN nạp phần đó,
#                   nhưng ghi status "thin_ok" để biết bộ này CÒN THIẾU phần
#                   trong ảnh; ghi thẳng "ok" là tự nói dối rằng đã xong.
# Đo thật: bộ Toán 1 có 656 ký tự cho 15 slide (43 ký tự/slide) — chữ đó là tên
# tác giả + một đoạn quan điểm, phần dạy nằm hết trong ảnh. Trên 97 bộ tải được
# chỉ 1 bộ dưới 1.000 ký tự, nên ngưỡng này gần như không loại oan ai.
_KEEP_MIN = 200
_RICH_MIN = 1000
# Nghỉ giữa hai lượt tải — kho của trường học và Google, đừng đấm.
_GAP = 0.35

_lock = threading.RLock()
_thread: threading.Thread | None = None


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_state() -> dict[str, Any]:
    try:
        if STATE_PATH.is_file():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("teacher_seed: đọc state lỗi %s", exc)
    return {}


def _write_state(st: dict[str, Any]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(STATE_PATH)
    except Exception as exc:
        logger.warning("teacher_seed: ghi state lỗi %s", exc)


def _books(grades: list[int] | None = None, *, all_sets: bool = True
           ) -> list[dict[str, Any]]:
    """Quyển cần nạp slide — CHỈ môn có trong danh mục của dự án.

    Tự CÀO danh mục lúc chạy, không đọc file đóng gói sẵn. Hai lý do:

      1. `docs/` KHÔNG nằm trong danh sách COPY của Dockerfile, nên file danh mục
         đo sẵn không hề tồn tại trong container — đọc nó là chắc chắn rỗng.
      2. Người vận hành không muốn dữ liệu của kho nằm trong image build. Cào lúc
         chạy thì image chỉ có CODE, còn nội dung ở volume /app/data.

    Bản danh mục trong docs/ chỉ để tra tay, và dùng làm đường nhanh khi có.
    """
    if CATALOG.is_file():
        try:
            man = json.loads(CATALOG.read_text(encoding="utf-8"))
            rows = [b for b in man.get("books") or [] if b.get("subject")]
            if rows:
                logger.info("teacher_seed: dùng danh mục sẵn có (%s quyển)", len(rows))
                return rows
        except Exception as exc:
            logger.warning("teacher_seed: danh mục sẵn có lỗi, cào lại: %s", exc)

    from services.agent import sgk_taphuan as tp
    from services.agent import teacher_workspace as tw

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for g in sorted(grades or tw.GRADES):
        try:
            books = tp.list_books(int(g), all_sets=all_sets)
        except Exception as exc:
            logger.warning("teacher_seed: danh mục lớp %s lỗi: %s", g, exc)
            continue
        for b in books:
            subs = b.get("subjects") or ()
            slug = str(b.get("slug") or "")
            if not subs or slug in seen:
                continue
            seen.add(slug)
            out.append({"detail_url": b.get("url"), "slug": slug,
                        "grade": int(g), "subject": subs[0],
                        "book_set": str(b.get("book_set") or "")})
        time.sleep(_GAP)
    logger.info("teacher_seed: cào được %s quyển từ kho", len(out))
    return out


def _slide_ids(detail_url: str) -> list[str]:
    from services import net_guard
    from services.agent import sgk_taphuan as tp
    try:
        raw = net_guard.safe_fetch(detail_url, allow_hosts=tp.ALLOW_HOSTS,
                                   timeout=45, max_bytes=8 * 1024 * 1024)
    except Exception as exc:
        logger.warning("teacher_seed: tải trang chi tiết lỗi (%s): %s",
                       detail_url[-50:], exc)
        return []
    html = raw.decode("utf-8", errors="ignore")
    return list(dict.fromkeys(_GSLIDE_RE.findall(html)))


def _slide_text(gid: str) -> str | None:
    """Chữ của một bộ slide. ``None`` = TẢI LỖI, ``""``/ngắn = slide ảnh.

    Phân biệt hai thứ đó là bắt buộc, không phải cho đẹp: gộp lại thì một sự cố
    mạng bị ghi thành "slide ảnh", cả 101 bộ đều "thin" và lượt nạp báo THÀNH
    CÔNG trong khi kho rỗng. Đã dính đúng như vậy khi chạy thử thật.
    """
    from services import net_guard
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", gid or ""):
        return None
    url = f"https://docs.google.com/presentation/d/{gid}/export/txt"
    try:
        raw = net_guard.safe_fetch(url, allow_hosts=_GSLIDE_HOSTS, timeout=60,
                                   max_bytes=_TXT_MAX_BYTES)
    except Exception as exc:
        logger.warning("teacher_seed: tải slide lỗi (%s): %s", gid[:12], exc)
        return None
    return raw.decode("utf-8", errors="ignore").strip()


def run(*, limit: int = 0, force: bool = False, grades: list[int] | None = None,
        all_sets: bool = True) -> dict[str, Any]:
    """Nạp (hoặc nạp tiếp) kho slide. Chạy đồng bộ — gọi trong threadpool/thread.

    ``limit`` > 0 để thử vài quyển trước. ``force`` bỏ qua state, nạp lại hết.
    """
    from services.agent import teacher_workspace as tw

    books = _books(grades, all_sets=all_sets)
    if not books:
        return {"ok": False, "error": "danh mục rỗng — thiếu docs/sgk/*.json?"}

    st = {} if force else read_state()
    done: dict[str, Any] = dict(st.get("slides") or {})
    out = {"started_at": _now(), "collection": COLLECTION,
           "total_books": len(books), "ok": 0, "thin_ok": 0, "skipped": 0,
           "thin": 0,
           "failed": 0, "chars": int(st.get("chars") or 0),
           "chunks": int(st.get("chunks") or 0)}
    seen_gid: set[str] = set()
    n = 0

    for b in books:
        if limit and n >= limit:
            break
        detail = str(b.get("detail_url") or "")
        if not detail:
            continue
        ids = _slide_ids(detail)
        time.sleep(_GAP)
        for gid in ids:
            # Nhiều quyển dùng CHUNG một bộ slide (tập một + tập hai). Nạp một
            # lần là đủ; nạp lại chỉ tốn thời gian và làm chunk trùng nội dung.
            if gid in seen_gid:
                continue
            seen_gid.add(gid)
            if not force and done.get(gid, {}).get("status") == "ok":
                out["skipped"] += 1
                continue
            txt = _slide_text(gid)
            time.sleep(_GAP)
            if txt is None:
                # TẢI LỖI — khác hẳn "slide ảnh". Ghi failed để lượt chạy sau thử
                # lại; ghi thin thì bỏ qua vĩnh viễn một bộ vốn có chữ.
                done[gid] = {"status": "failed", "error": "tải slide lỗi",
                             "ts": _now()}
                out["failed"] += 1
                continue
            if len(txt) < _KEEP_MIN:
                # Gần như không có chữ: nội dung nằm hết trong ảnh chèn vào.
                # Ghi nhận để đường nạp hàng loạt lấy bằng OCR.
                done[gid] = {"status": "thin", "chars": len(txt), "ts": _now()}
                out["thin"] += 1
                continue
            thin = len(txt) < _RICH_MIN
            g = int(b.get("grade") or 0)
            sub = str(b.get("subject") or "")
            mon = tw.SUBJECT_LABEL.get(sub, sub)
            title = (f"Slide giới thiệu · tập huấn — lớp {g} · {mon}"
                     + (f" · bộ {b['book_set']}" if b.get("book_set") else " · bộ chính"))
            if thin:
                # Nói thẳng trong CHÍNH nội dung chunk: bot đọc được cảnh báo này
                # nên không khẳng định chắc nịch dựa trên vài dòng tiêu đề.
                title += " · CHỈ phần chữ, nội dung chính nằm trong ảnh (chưa OCR)"
            res = tw.push_sgk_to_rag(
                f"## {title}\n\n{txt}\n", title=title, grade=g, subject=sub,
                source=f"slide/{gid[:16]}", collection=COLLECTION)
            if res.get("ok"):
                done[gid] = {"status": "thin_ok" if thin else "ok",
                             "chars": len(txt),
                             "chunks": int(res.get("chunks_added") or 0),
                             "grade": g, "subject": sub, "ts": _now()}
                out["thin_ok" if thin else "ok"] += 1
                out["chars"] += len(txt)
                out["chunks"] += int(res.get("chunks_added") or 0)
            else:
                done[gid] = {"status": "failed",
                             "error": str(res.get("errors") or res.get("error"))[:200],
                             "ts": _now()}
                out["failed"] += 1
            # Ghi state sau MỖI bộ — mất mạng giữa đường vẫn giữ phần đã nạp.
            _write_state({"slides": done, "chars": out["chars"],
                          "chunks": out["chunks"], "updated_at": _now()})
        n += 1

    out["finished_at"] = _now()
    _write_state({"slides": done, "chars": out["chars"], "chunks": out["chunks"],
                  "updated_at": _now(), "last_run": out})
    logger.info({"event": "teacher_seed_done", **out})
    return {"ok": True, **out}


def wait_for_hub(timeout_s: float = 300.0, gap_s: float = 5.0) -> bool:
    """Chờ vn-mcp-hub sẵn sàng. False = hết giờ mà chưa lên.

    Bắt buộc khi tự chạy lúc khởi động: hub là TIẾN TRÌNH RIÊNG dưới supervisord,
    app chính lên trước nó. Đẩy vào lúc hub chưa lên thì 101 bộ slide đều lỗi
    "connection refused" rồi bị ghi state là failed — nạp đúng một lần rồi bỏ.
    """
    import urllib.request

    from services.agent import teacher_workspace as tw

    base = str(tw.config_hub_url() or "").rstrip("/")
    if not base:
        return False
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{base}/api/rag/models", method="GET")
            with urllib.request.urlopen(req, timeout=8) as r:
                if r.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(gap_s)
    logger.warning("teacher_seed: hub chưa lên sau %ss — bỏ lượt nạp tự động",
                   int(timeout_s))
    return False


def is_running() -> bool:
    with _lock:
        return bool(_thread and _thread.is_alive())


def start(*, wait_hub: bool = False, **kw: Any) -> dict[str, Any]:
    """Chạy NỀN. Trả ngay; theo dõi bằng :func:`read_state`.

    ``wait_hub=True`` để chờ hub lên trước — dùng khi gọi lúc khởi động.
    """
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return {"ok": False, "error": "đang chạy rồi", "running": True}

        def _go() -> None:
            try:
                if wait_hub and not wait_for_hub():
                    return
                run(**kw)
            except Exception as exc:
                logger.warning("teacher_seed: chạy nền lỗi %s", exc)

        _thread = threading.Thread(target=_go, name="teacher-slide-seed",
                                   daemon=True)
        _thread.start()
    return {"ok": True, "running": True}


def autostart_if_empty() -> dict[str, Any]:
    """Gọi lúc khởi động: chưa nạp gì thì nạp NỀN, đã có rồi thì không làm gì.

    Chạy trong THREAD RIÊNG, không chặn khởi động: nạp 101 bộ slide mất vài phút,
    mà chặn vòng lặp sự kiện lúc boot là cả gateway đứng hình — bot câm, web treo.
    Đã có sự cố đúng kiểu đó, nên đây là điều kiện bắt buộc, không phải tối ưu.

    Chỉ tự chạy LẦN ĐẦU. Đã có state nghĩa là người vận hành đã nạp (hoặc đã cố
    ý dừng) — tự chạy lại là đi ngược quyết định của họ.
    """
    st = read_state()
    if st.get("slides"):
        return {"ok": True, "skipped": "đã nạp trước đó", "running": False}
    logger.info("teacher_seed: chưa có kho slide — nạp nền lần đầu")
    return start(wait_hub=True)
