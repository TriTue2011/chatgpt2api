"""Bài giảng hai khung: lời cô (SGV) một bên, trang SGK cho học sinh một bên.

Vì sao không dùng `ai_draft_lesson` sẵn có: nó trả MỘT khối body_text + tts —
không nói được "đoạn này ứng với trang nào của SGK", nên không làm được yêu cầu
"giảng đến đâu, trang sách lật theo đến đó". Ở đây bài giảng là DANH SÁCH ĐOẠN,
mỗi đoạn mang số trang in; UI đổi ảnh trang theo đoạn đang giảng.

Hai kho, hai vai — lấy lẫn là sai việc:
  · kb_giao_duc      (SGK) → thứ HIỆN CHO HỌC SINH và nội dung cần dạy
  · kb_giao_duc_sgv  (SGV) → CÁCH dạy, chỉ vào lời cô, KHÔNG đọc ra cho học sinh

Truy vấn qua MCP `kb_giao_vien` trên hub (127.0.0.1:8005) — không mở đường
Chroma thứ hai từ tiến trình app: hub đang giữ sqlite, và nạp thêm bộ embedding
~200MB vào app chỉ để hỏi là trả giá sai chỗ.

Ảnh trang: dùng lại manifest trang→ảnh của `teacher_images` (route
`/api/teacher/page-img/{slug}/{page}` đã có). Manifest chưa có thì dựng tại chỗ
từ taphuan — chỉ URL, không tải ảnh, không gọi model. LƯU Ý đánh số: tham số
`page` của route là THỨ TỰ ẢNH (bìa = 1); số IN trên trang giấy = thứ tự − 1
(đo thật 2026-07-28). Trả `offset` để UI cộng, không cộng ngầm ở nhiều nơi.
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

_ROOT = Path(DATA_DIR) / "agent" / "teacher" / "lectures"
_HUB_KB_URL = "http://127.0.0.1:8005/kb_giao_vien/mcp"
_kb_lock = threading.Lock()
_kb_session = None

# Trang in = thứ tự ảnh − 1 (bìa là ảnh 1). Đo trên kho taphuan 2026-07-28:
# ảnh "-page-80-" của Hoá 11 in số 79, "-page-94-" của Tiếng Việt 1 in số 93.
PAGE_OFFSET = 1


def _kb(tool: str, args: dict[str, Any]) -> str:
    """Gọi một tool của MCP kb_giao_vien. Hỏng thì trả "" — bài giảng vẫn soạn
    được nhưng PHẢI nói rõ trong prompt là không có căn cứ kho."""
    global _kb_session
    try:
        from services.mcp_client import MCPSession
        with _kb_lock:
            if _kb_session is None:
                _kb_session = MCPSession(_HUB_KB_URL, "")
            s = _kb_session
        return (s.call_tool(tool, args) or "").strip()
    except Exception as exc:  # noqa: BLE001 — kho hỏng không được chặn soạn bài
        logger.warning("teacher_lecture._kb %s lỗi: %s", tool, str(exc)[:120])
        return ""


# ── Sách + manifest trang cho khung học sinh ────────────────────────────────

def books_for(grade: int, subject: str) -> list[dict[str, Any]]:
    """SGK bộ chính của lớp–môn, kèm manifest trang→ảnh (dựng nếu chưa có).

    Trả [] khi không tìm thấy — caller hiện khung chữ không ảnh, KHÔNG lấy bừa
    sách của bộ khác (khác chương trình, lật trang sẽ sai bài).
    """
    from services.agent import sgk_taphuan as tp

    out: list[dict[str, Any]] = []
    try:
        books = tp.list_books(int(grade))
    except Exception as exc:  # noqa: BLE001
        logger.warning("teacher_lecture.books_for(%s,%s): %s", grade, subject,
                       str(exc)[:120])
        return out
    from services.agent import sgk_fetch as sf

    want = str(subject or "").strip()
    mon = sf.SUBJECT_LABEL.get(want, want)
    for b in books:
        # `list_books` trả {slug, url, subjects(tuple), volume, book_set, grade}
        # — KHÔNG có detail_url/subject/title. Sách gộp (Lịch sử và Địa lí) có
        # nhiều mã trong `subjects`, nên so bằng phép chứa.
        if want and want not in (b.get("subjects") or ()):
            continue
        for url in tp.reader_urls(b.get("url") or "", kinds=("sgk",)):
            if tp.is_sample(url):
                continue
            slug = tp.reader_slug(url)
            rec = tp.get_page_manifest(slug)
            if not rec.get("pages"):
                imgs = tp.page_images(url)
                if not imgs:
                    continue
                tp.save_page_manifest(url, imgs, grade=int(grade), subject=want)
                rec = tp.get_page_manifest(slug)
            vol = str(b.get("volume") or "").strip()
            out.append({
                "slug": slug,
                "title": " · ".join(x for x in (f"SGK lớp {grade}", mon, vol) if x),
                "volume": vol,
                # `pages` trong manifest là DANH SÁCH dòng {n, url} — đếm len,
                # int(list) là TypeError.
                "pages": len(rec.get("pages") or []),
                "offset": PAGE_OFFSET,
            })
    return out


# ── Mục lục có cấu trúc: chọn BÀI theo sách thay vì gõ tay ─────────────────
# Nguồn: chép từ mục lục SGK (đang nạp dần từng quyển). Để ở file JSON theo
# lớp–môn vì cả bài giảng LẪN bài tập cùng chọn từ đây — kho RAG chỉ trả văn
# xuôi, không đủ chắc để dựng dropdown.

_TOC_DIR = Path(DATA_DIR) / "agent" / "teacher" / "toc"


def toc(grade: int, subject: str) -> list[dict[str, Any]]:
    """Danh sách bài của lớp–môn: [{bai, ten, trang, tap}]. Rỗng = chưa nạp mục
    lục quyển đó — UI rơi về ô gõ tay, không chặn."""
    p = _TOC_DIR / f"lop{int(grade)}-{re.sub(r'[^a-z]', '', str(subject or ''))}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_toc(grade: int, subject: str, rows: list[dict[str, Any]]) -> int:
    """Ghi mục lục (đường nạp gọi khi chép xong một quyển). Ghi đè cả file —
    mục lục là ảnh chụp của quyển sách, không phải log để cộng dồn."""
    clean = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        ten = str(r.get("ten") or "").strip()
        if not ten:
            continue
        clean.append({"bai": str(r.get("bai") or "").strip()[:20], "ten": ten[:200],
                      "trang": int(r.get("trang") or 0) or None,
                      "tap": str(r.get("tap") or "").strip()[:20]})
    if not clean:
        return 0
    _TOC_DIR.mkdir(parents=True, exist_ok=True)
    p = _TOC_DIR / f"lop{int(grade)}-{re.sub(r'[^a-z]', '', str(subject or ''))}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return len(clean)


# ── Soạn bài giảng theo ĐOẠN gắn trang ──────────────────────────────────────

_SCHEMA_HINT = (
    '{"title":"...","muc_tieu":"1 câu","segments":[{"heading":"...",'
    '"text":"lời giảng hiện chữ","tts":"2-4 câu để loa đọc, không kí hiệu",'
    '"page":số trang in hoặc null}],"cau_hoi_kiem_tra":"1 câu CFU"}'
)


def _parse_lecture(raw: str) -> dict[str, Any] | None:
    """JSON của model → dict đã kiểm hình dạng. Sai hình dạng = None, KHÔNG vá
    im lặng — bài giảng thiếu segments mà vẫn lưu thì UI trắng khung không rõ lý do."""
    try:
        from services.agent.teacher_classroom import _parse_json_obj
        data = _parse_json_obj(raw)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return None
    segs = data.get("segments")
    if not isinstance(segs, list) or not segs:
        return None
    clean: list[dict[str, Any]] = []
    for s in segs:
        if not isinstance(s, dict):
            continue
        text = str(s.get("text") or "").strip()
        if not text:
            continue
        page = s.get("page")
        try:
            page = int(page) if page is not None else None
            if page is not None and not (0 < page < 1000):
                page = None
        except Exception:
            page = None
        clean.append({
            "heading": str(s.get("heading") or "").strip()[:120],
            "text": text,
            "tts": str(s.get("tts") or "").strip() or text[:280],
            "page": page,
        })
    if not clean:
        return None
    return {
        "title": str(data.get("title") or "").strip()[:200],
        "muc_tieu": str(data.get("muc_tieu") or "").strip()[:300],
        "segments": clean,
        "cau_hoi_kiem_tra": str(data.get("cau_hoi_kiem_tra") or "").strip()[:300],
    }


def _store_path(student_key: str) -> Path:
    sk = re.sub(r"[^\w.\-]+", "_", (student_key or "anon").strip())[:64]
    return _ROOT / f"{sk}.json"


def _load_store(student_key: str) -> dict[str, Any]:
    p = _store_path(student_key)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_store(student_key: str, data: dict[str, Any]) -> None:
    p = _store_path(student_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def generate(student_key: str, subject: str, *, bai: str = "",
             topic: str = "", notes: str = "") -> dict[str, Any]:
    """Soạn bài giảng cho MỘT học sinh: lớp lấy từ hồ sơ, không nhận từ ngoài.

    Lớp là dữ liệu của hồ sơ (suy từ năm sinh) — nhận lớp từ tham số là mở đường
    soạn bài lớp 5 cho học sinh lớp 2 chỉ vì UI truyền nhầm.
    """
    from services.agent import teacher_path as tpath
    from services.agent import teacher_workspace as tw

    stu = next((r for r in tpath.list_students()
                if r.get("student_key") == student_key), None)
    if not stu:
        return {"ok": False, "error": f"không có học sinh '{student_key}'"}
    g = int(stu.get("grade") or 0)
    if g not in tw.GRADES:
        return {"ok": False,
                "error": "hồ sơ chưa rõ lớp — bổ sung năm sinh ở tab Học sinh trước"}

    sub = tw._normalize_subject(subject) or "toan"
    mon = tw.SUBJECT_LABEL.get(sub, sub)
    hoi = (bai or topic or "").strip()
    if not hoi:
        return {"ok": False, "error": "cần tên bài hoặc chủ đề"}

    # Hai kho, hai câu hỏi khác nhau — đúng vai từng kho.
    kb_sgk = _kb("ask_sgk", {"question": f"lớp {g} {mon} {hoi}: nội dung bài, "
                                         f"số trang", "top_k": 4})
    kb_sgv = _kb("ask_sgv", {"question": f"lớp {g} {mon} dạy {hoi} thế nào: mục "
                                         f"tiêu, hoạt động, lỗi thường gặp",
                             "top_k": 4})
    kb_tuan = _kb("ask_phan_bo", {"question": f"lớp {g} {mon} {hoi} tuần mấy, "
                                              f"mấy tiết", "top_k": 2})

    sys_p = (
        "Bạn là giáo viên Việt Nam soạn BÀI GIẢNG TRỰC QUAN cho một học sinh "
        f"lớp {g}. Trả JSON thuần đúng schema:\n" + _SCHEMA_HINT + "\n"
        "Quy tắc:\n"
        "1. 4–8 segments, theo nhịp I do → We do → You do; mỗi segment một ý.\n"
        "2. `page`: CHỈ ghi số trang IN thấy trong TƯ LIỆU SGK (dạng «TRANG n» "
        "hoặc «trang n»); không thấy thì để null — TUYỆT ĐỐI không đoán trang.\n"
        "3. `text` là lời giảng hiện chữ cho học sinh; `tts` là lời cô nói, "
        "câu ngắn, không kí hiệu ×÷=%, đọc 'nhân/chia/bằng/phần trăm'.\n"
        "4. TƯ LIỆU SGV chỉ dùng để chọn cách dạy — không chép lời SGV vào text.\n"
        "5. Đúng phạm vi kiến thức đã học tới bài này của lớp đó, không dùng "
        "kiến thức lớp trên."
    )
    user_p = (
        f"Học sinh lớp {g} · môn {mon} · bài/chủ đề: {hoi}\n"
        f"Ghi chú của giáo viên: {(notes or '').strip() or '(không)'}\n\n"
        f"TƯ LIỆU SGK (nội dung + trang):\n{(kb_sgk or '(kho chưa có)')[:2600]}\n\n"
        f"TƯ LIỆU SGV (cách dạy):\n{(kb_sgv or '(kho chưa có)')[:2000]}\n\n"
        f"PHÂN BỔ TUẦN-TIẾT:\n{(kb_tuan or '(không rõ)')[:500]}"
    )

    from services.agent.runtime import call_model, content_of
    from services.agent.teacher_classroom import _teacher_model

    llm = _teacher_model("speak")
    resp = call_model(
        llm,
        [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
        timeout=150, max_tokens=2200, no_smart_home=True,
    )
    if resp.get("error"):
        return {"ok": False, "error": f"model lỗi: {str(resp.get('error'))[:160]}"}
    lecture = _parse_lecture(content_of(resp))
    if not lecture:
        return {"ok": False, "error": "model không trả đúng dạng bài giảng — thử lại"}

    # TTS đọc được: dùng chung verbalize với đường lesson cũ.
    try:
        from services.agent import teacher as teach
        for s in lecture["segments"]:
            s["tts"] = teach.verbalize_for_tts(s["tts"])[:600]
    except Exception:
        pass

    lecture.update({
        "student_key": student_key, "grade": g, "subject": sub,
        "bai": hoi, "notes": notes, "model_used": llm,
        "books": books_for(g, sub),
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "grounded": {"sgk": bool(kb_sgk), "sgv": bool(kb_sgv),
                     "phan_bo": bool(kb_tuan)},
    })

    store = _load_store(student_key)
    store[sub] = lecture
    _save_store(student_key, store)
    return {"ok": True, "lecture": lecture}


def last(student_key: str, subject: str = "") -> dict[str, Any]:
    store = _load_store(student_key)
    if subject:
        from services.agent import teacher_workspace as tw
        sub = tw._normalize_subject(subject) or subject
        lec = store.get(sub)
        return {"ok": True, "lecture": lec} if lec else {"ok": False,
                                                         "error": "chưa có bài giảng"}
    return {"ok": True, "subjects": sorted(store.keys())}


def ask(student_key: str, question: str, subject: str = "") -> dict[str, Any]:
    """Học sinh nói chỗ chưa hiểu SAU bài giảng → giải thích bám đúng bài đó.

    Neo vào bài giảng vừa dạy chứ không trả lời trôi nổi: cùng một câu "con chưa
    hiểu chỗ cộng" phải được giải thích theo đúng ví dụ của bài, không lôi ví dụ
    lớp khác vào.
    """
    q = (question or "").strip()
    if not q:
        return {"ok": False, "error": "câu hỏi rỗng"}
    store = _load_store(student_key)
    lec = None
    if subject:
        from services.agent import teacher_workspace as tw
        lec = store.get(tw._normalize_subject(subject) or subject)
    if lec is None and store:
        lec = max(store.values(), key=lambda x: str(x.get("created") or ""))
    if not lec:
        return {"ok": False, "error": "chưa có bài giảng nào để hỏi lại"}

    g = int(lec.get("grade") or 0)
    body = "\n\n".join(f"[{i+1}] {s.get('heading') or ''}\n{s.get('text')}"
                       for i, s in enumerate(lec.get("segments") or []))
    sys_p = (
        f"Bạn là cô giáo vừa giảng xong bài «{lec.get('title')}» cho học sinh "
        f"lớp {g}. Em nói chỗ chưa hiểu. Giải thích LẠI bằng cách KHÁC dựa đúng "
        "nội dung bài bên dưới: chậm hơn, ví dụ mới cùng dạng, 3–6 câu ngắn. "
        "Không sang kiến thức ngoài bài. Trả JSON thuần: "
        '{"answer":"lời giải thích hiện chữ","tts":"bản đọc loa, không kí hiệu"}'
    )
    user_p = f"BÀI GIẢNG:\n{body[:3000]}\n\nHỌC SINH NÓI: {q}"

    from services.agent.runtime import call_model, content_of
    from services.agent.teacher_classroom import _parse_json_obj, _teacher_model

    resp = call_model(
        _teacher_model("speak"),
        [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
        timeout=120, max_tokens=800, no_smart_home=True,
    )
    if resp.get("error"):
        return {"ok": False, "error": f"model lỗi: {str(resp.get('error'))[:160]}"}
    data = _parse_json_obj(content_of(resp)) or {}
    ans = str(data.get("answer") or content_of(resp) or "").strip()
    if not ans:
        return {"ok": False, "error": "model không trả lời được — thử lại"}
    tts = str(data.get("tts") or ans).strip()
    try:
        from services.agent import teacher as teach
        tts = teach.verbalize_for_tts(tts)[:600]
    except Exception:
        pass
    return {"ok": True, "answer": ans, "tts": tts}
