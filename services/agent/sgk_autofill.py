"""Quét TOÀN BỘ lớp × môn, tự tìm và tự nạp SGK vào RAG.

Chạy trên nền `sgk_fetch`: mỗi tổ hợp (lớp, môn) → ``find_sources`` lấy ứng viên
PDF công khai → thử nạp lần lượt tới khi được một cái. Tổ hợp không có sách
(vd Hoá lớp 1, GDCD lớp 2) chỉ ghi ``no_source`` rồi đi tiếp — KHÔNG coi là lỗi,
vì chương trình vốn không có môn đó ở lớp đó.

Đặc tính cần cho việc chạy dài (120 tổ hợp, mỗi PDF tới cả trăm MB):
- **Chạy lại được**: tổ hợp đã nạp thành công (có trong ``sgk_fetch_index.json``)
  được bỏ qua, nên đứt giữa chừng thì chạy lại là đi tiếp chứ không làm lại.
- **Xem được tiến độ**: ghi ``sgk_autofill_state.json`` sau MỖI tổ hợp.
- **Dừng được**: ``stop()`` — vòng lặp kiểm tra cờ giữa các tổ hợp.
- **Không đập search service**: nghỉ ``pause`` giây giữa các tổ hợp.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Iterable, Optional

from services.agent import sgk_fetch as sf
from services.agent import teacher_workspace as tw

logger = logging.getLogger(__name__)

STATE_PATH = sf._ROOT / "sgk_autofill_state.json"

_lock = threading.RLock()
_thread: Optional[threading.Thread] = None
_stop = threading.Event()

# Nghỉ giữa 2 tổ hợp (giây) — tìm kiếm web liên tục dễ bị chặn.
_DEFAULT_PAUSE = 3.0
# Số ứng viên thử tối đa cho mỗi tổ hợp trước khi bỏ cuộc.
_DEFAULT_CANDIDATES = 3


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def combos(grades: Iterable[int] | None = None,
           subjects: Iterable[str] | None = None) -> list[tuple[int, str]]:
    """Danh sách (lớp, môn) sẽ quét — mặc định 12 lớp × toàn bộ môn."""
    gs = [int(g) for g in (grades or tw.GRADES) if int(g) in tw.GRADES]
    subs: list[str] = []
    for s in (subjects or sf.SUBJECTS):
        n = sf.normalize_subject(s)
        if n and n not in subs:
            subs.append(n)
    return [(g, s) for g in gs for s in subs]


def _done_keys(kind: str) -> set[tuple[int, str]]:
    """Tổ hợp đã nạp thành công trước đó (đọc từ index của sgk_fetch)."""
    out: set[tuple[int, str]] = set()
    for rec in sf._load_index().values():
        if not rec.get("ok"):
            continue
        if kind and rec.get("kind") != kind:
            continue
        try:
            out.add((int(rec.get("grade")), str(rec.get("subject"))))
        except (TypeError, ValueError):
            continue
    return out


def read_state() -> dict[str, Any]:
    """Tiến độ lần chạy gần nhất (rỗng nếu chưa chạy bao giờ)."""
    try:
        if STATE_PATH.is_file():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("sgk_autofill: đọc state lỗi %s", exc)
    return {}


def _write_state(state: dict[str, Any]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("sgk_autofill: ghi state lỗi %s", exc)


def run(
    *,
    grades: Iterable[int] | None = None,
    subjects: Iterable[str] | None = None,
    kind: str = "sgk",
    candidates_per_combo: int = _DEFAULT_CANDIDATES,
    skip_done: bool = True,
    dry_run: bool = False,
    pause: float = _DEFAULT_PAUSE,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Quét đồng bộ (blocking) — trả tổng kết khi xong.

    Muốn chạy nền thì dùng :func:`start`.
    """
    plan = combos(grades, subjects)
    already = _done_keys(kind) if skip_done else set()
    state: dict[str, Any] = {
        "started_at": _now(),
        "finished_at": "",
        "running": True,
        "kind": kind,
        "dry_run": bool(dry_run),
        "total": len(plan),
        "index": 0,
        "current": "",
        "counts": {"ok": 0, "no_source": 0, "failed": 0, "skipped": 0},
        "done": [],
    }
    _write_state(state)

    for i, (g, sub) in enumerate(plan, start=1):
        if _stop.is_set():
            state["stopped"] = True
            break
        state["index"] = i
        state["current"] = f"lớp {g} · {sf.SUBJECT_LABEL.get(sub, sub)}"
        row: dict[str, Any] = {"grade": g, "subject": sub, "status": "", "url": "", "error": ""}

        if (g, sub) in already:
            row["status"] = "skipped"
            row["error"] = "đã nạp trước đó"
        else:
            try:
                cands = sf.find_sources(g, sub, kind=kind)
            except Exception as exc:
                cands = []
                row["error"] = f"tìm nguồn lỗi: {str(exc)[:150]}"
            if not cands:
                # Không có sách cho tổ hợp này là chuyện BÌNH THƯỜNG
                # (Hoá lớp 1, GDCD lớp 2…) — ghi nhận rồi đi tiếp.
                row["status"] = "no_source"
            else:
                for cand in cands[:max(1, int(candidates_per_combo))]:
                    if _stop.is_set():
                        break
                    url = str(cand.get("url") or "")
                    if not url:
                        continue
                    try:
                        res = sf.fetch_and_ingest(
                            g, sub, url, kind=kind, dry_run=dry_run,
                            curriculum=str(cand.get("curriculum") or ""),
                            year=str(cand.get("year") or ""),
                        )
                    except Exception as exc:
                        row["error"] = str(exc)[:200]
                        continue
                    if res.get("ok"):
                        row["status"] = "ok"
                        row["url"] = url
                        row["chunks"] = res.get("chunks_added")
                        row["error"] = ""
                        break
                    row["error"] = str(res.get("error") or res.get("message") or "")[:200]
                if row["status"] != "ok":
                    row["status"] = "failed"

        state["counts"][row["status"]] = state["counts"].get(row["status"], 0) + 1
        state["done"].append(row)
        _write_state(state)
        logger.info({"event": "sgk_autofill_combo", "grade": g, "subject": sub,
                     "status": row["status"], "i": i, "total": len(plan)})
        if on_progress:
            try:
                on_progress(dict(row, index=i, total=len(plan)))
            except Exception:
                pass
        if pause > 0 and i < len(plan) and not _stop.is_set():
            _stop.wait(pause)

    state["running"] = False
    state["current"] = ""
    state["finished_at"] = _now()
    _write_state(state)
    return state


def start(**kw: Any) -> dict[str, Any]:
    """Chạy nền. Gọi lại khi đang chạy → báo bận, KHÔNG chạy chồng."""
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            st = read_state()
            return {"ok": False, "message": "đang chạy rồi",
                    "index": st.get("index"), "total": st.get("total")}
        _stop.clear()
        _thread = threading.Thread(
            target=lambda: run(**kw), name="sgk-autofill", daemon=True,
        )
        _thread.start()
    return {"ok": True, "message": "đã bắt đầu quét nền"}


def stop() -> dict[str, Any]:
    """Dừng sau khi xong tổ hợp hiện tại (không cắt ngang lần tải đang chạy)."""
    _stop.set()
    return {"ok": True, "message": "sẽ dừng sau tổ hợp đang chạy"}


def is_running() -> bool:
    return bool(_thread and _thread.is_alive())


def summary(state: dict[str, Any] | None = None) -> str:
    """Bản tóm tắt tiếng Việt cho bot/CLI."""
    st = state if state is not None else read_state()
    if not st:
        return "Chưa chạy tự nạp SGK lần nào."
    c = st.get("counts") or {}
    running = " (ĐANG CHẠY: " + str(st.get("current") or "") + ")" if st.get("running") else ""
    head = (
        f"📚 Tự nạp SGK — {st.get('index', 0)}/{st.get('total', 0)} tổ hợp{running}\n"
        f"✅ nạp được {c.get('ok', 0)} · ⬜ không có sách {c.get('no_source', 0)} · "
        f"❌ hỏng {c.get('failed', 0)} · ↩︎ bỏ qua {c.get('skipped', 0)}"
    )
    oks = [r for r in (st.get("done") or []) if r.get("status") == "ok"]
    if oks:
        lines = [f"  • Lớp {r['grade']} {sf.SUBJECT_LABEL.get(r['subject'], r['subject'])}"
                 for r in oks[:30]]
        head += "\n\nĐã nạp:\n" + "\n".join(lines)
        if len(oks) > 30:
            head += f"\n  … và {len(oks) - 30} mục nữa"
    fails = [r for r in (st.get("done") or []) if r.get("status") == "failed"]
    if fails:
        head += f"\n\n❌ Hỏng ({len(fails)}): " + ", ".join(
            f"L{r['grade']}-{r['subject']}" for r in fails[:15]
        )
    return head
