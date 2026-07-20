"""Hẹn giờ phát thông báo TTS ra loa — bộ hẹn giờ NHẸ trong tiến trình.

Vd: "phát 'kiểm tra loa' sau 1 phút ra loa phòng khách âm lượng 20%".
Mỗi job: tới giờ thì đọc `text` bằng TTS rồi phát ra loa (tra theo TÊN/id),
có thể đặt âm lượng trước khi phát.

Dùng threading.Timer nên KHÔNG sống qua restart — đủ cho hẹn ngắn ("sau N phút").
Cần bền vững qua restart thì dùng agent_reminders (SQLite) thay cho module này.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_jobs: dict[str, dict[str, Any]] = {}
_MAX_KEEP = 50   # giữ tối đa 50 job gần nhất cho UI xem


def _resolve_one(speaker_query: str) -> dict[str, Any]:
    """Tra đúng MỘT loa theo tên/id. Nhiều kết quả = chưa rõ → bắt hỏi lại."""
    from services.voice import speakers as vspk

    hits = vspk.resolve(speaker_query)
    if not hits:
        raise RuntimeError(f"Không tìm thấy loa nào tên '{speaker_query}'.")
    if len(hits) > 1:
        names = ", ".join(str(h.get("name")) for h in hits[:6])
        raise RuntimeError(f"Nhiều loa khớp '{speaker_query}': {names} — nói rõ tên hơn.")
    return hits[0]


def _run(jid: str) -> None:
    from services import voice
    from services.voice import speakers as vspk

    with _lock:
        job = _jobs.get(jid)
    if not job or job.get("status") == "cancelled":
        return
    rec = job["rec"]
    try:
        vol = job.get("volume")
        if vol is not None:
            try:
                vspk.set_volume(rec, float(vol))
            except Exception as exc:   # loa không chỉnh được vol thì vẫn đọc
                logger.info("announce: bỏ qua đặt âm lượng (%s)", str(exc)[:80])
        voice.play_text_on(job["text"], rec)
        with _lock:
            job["status"] = "done"
    except Exception as exc:
        with _lock:
            job["status"] = f"error: {str(exc)[:160]}"
        logger.warning("announce: phát lỗi ra %s: %s", rec.get("name"), exc)


def schedule(speaker_query: str, text: str, *, delay_seconds: float,
             volume: Optional[float] = None) -> dict[str, Any]:
    """Hẹn đọc `text` ra loa `speaker_query` sau `delay_seconds`.

    volume: 0..1 (tỉ lệ) hoặc — với R1 — chỉ số tuyệt đối (>1). Tuỳ chọn.
    Ném RuntimeError nếu loa không rõ (0 hoặc >1 kết quả)."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("Thiếu nội dung thông báo.")
    rec = _resolve_one(speaker_query)     # ném lỗi sớm nếu loa chưa rõ
    delay = max(0.0, float(delay_seconds))
    jid = uuid.uuid4().hex[:10]
    timer = threading.Timer(delay, _run, args=(jid,))
    timer.daemon = True
    with _lock:
        _jobs[jid] = {
            "id": jid,
            "rec": rec,
            "speaker_name": rec.get("name"),
            "text": text,
            "volume": None if volume is None else float(volume),
            "fire_at": int(time.time() + delay),
            "status": "scheduled",
            "timer": timer,
        }
        _prune()
    timer.start()
    return public(jid) or {}


def cancel(jid: str) -> bool:
    with _lock:
        job = _jobs.get(str(jid or ""))
        if not job:
            return False
        job["status"] = "cancelled"
        t = job.get("timer")
    if t:
        try:
            t.cancel()
        except Exception:
            pass
    return True


def public(jid: str) -> Optional[dict[str, Any]]:
    with _lock:
        job = _jobs.get(str(jid or ""))
        if not job:
            return None
        return {k: job[k] for k in ("id", "speaker_name", "text", "volume", "fire_at", "status")}


def list_jobs() -> list[dict[str, Any]]:
    with _lock:
        rows = [{k: j[k] for k in ("id", "speaker_name", "text", "volume", "fire_at", "status")}
                for j in _jobs.values()]
    rows.sort(key=lambda r: r.get("fire_at") or 0, reverse=True)
    return rows


def _prune() -> None:
    """Bỏ bớt job cũ đã xong/huỷ khi vượt trần (giữ job đang chờ)."""
    if len(_jobs) <= _MAX_KEEP:
        return
    done = [(j["fire_at"], j["id"]) for j in _jobs.values()
            if j.get("status") in ("done", "cancelled") or str(j.get("status", "")).startswith("error")]
    done.sort()
    for _, jid in done[: len(_jobs) - _MAX_KEEP]:
        _jobs.pop(jid, None)
