"""Theo dõi chủ đề tin tức, có trạng thái và báo tin tự nguyện.

Mỗi chủ đề là một bản ghi bền vững theo ``user_id``. Nó có thể chỉ được lưu để
người dùng tự hỏi lại, hoặc được bật báo định kỳ sau khi người dùng đồng ý rõ
ràng. Các kết quả đã thấy được ghi fingerprint để một lần quét không gửi lặp
cùng bản tin.

Sổ cũ ``{user_id: [{chu_de, ts}]}`` vẫn đọc được và tự chuẩn hoá khi ghi lần
tiếp theo. Việc ghi dùng file tạm + ``os.replace``; khoá file là lớp bổ sung
cho ``RLock`` khi ứng dụng chạy nhiều worker trên cùng DATA_DIR.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

_TOI_DA = 30
_SEEN_CAP = 80
_MAX_DUE_PER_TICK = 10
_MIN_INTERVAL_MIN = 5
_MAX_INTERVAL_MIN = 7 * 24 * 60
_lock = threading.RLock()
_started = False
_stop = threading.Event()
_URL_RE = re.compile(r"https?://[^\s<>\]\[\)\}\",]+", re.I)


def _fold(s: str) -> str:
    b = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    k = "aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyyd"
    return " ".join((s or "").lower().translate(str.maketrans(b, k)).split())


def _duong() -> Path:
    from services.config import DATA_DIR

    return Path(DATA_DIR) / "agent" / "tracked_topic.json"


@contextmanager
def _khoa_ghi() -> Iterator[None]:
    """Khoá cả trong một process lẫn giữa các worker POSIX (best effort)."""
    with _lock:
        p = _duong()
        p.parent.mkdir(parents=True, exist_ok=True)
        fh = (p.parent / f".{p.name}.lock").open("a+", encoding="utf-8")
        try:
            try:
                import fcntl  # POSIX; Windows vẫn còn RLock ở trên.
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            fh.close()


def _doc() -> dict[str, Any]:
    try:
        p = _duong()
        if p.is_file():
            d = json.loads(p.read_text("utf-8") or "{}")
            return d if isinstance(d, dict) else {}
    except Exception as exc:
        logger.warning("tracked_topic: đọc sổ lỗi: %s", exc)
    return {}


def _ghi_file(d: dict[str, Any]) -> bool:
    """Ghi nguyên tử, trả kết quả THẬT để caller không báo thành công giả."""
    p = _duong()
    tmp: Path | None = None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
        return True
    except Exception as exc:
        logger.warning("tracked_topic: ghi sổ lỗi: %s", exc)
        try:
            if tmp is not None and tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def _legacy_id(uid: str, item: dict[str, Any]) -> str:
    raw = f"{uid}\0{item.get('chu_de') or ''}\0{item.get('ts') or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _so_thuc(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _interval(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return max(_MIN_INTERVAL_MIN, min(_MAX_INTERVAL_MIN, n))


def _delivery(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    channel = str(value.get("channel") or "").strip()
    chat_id = str(value.get("chat_id") or "").strip()
    if channel not in {"tg", "zalo", "zalop"} or not chat_id:
        return None
    meta = value.get("meta") if isinstance(value.get("meta"), dict) else {}
    clean_meta = {
        str(k)[:40]: str(v)[:200]
        for k, v in meta.items()
        if isinstance(k, str) and isinstance(v, (str, int, float, bool))
    }
    return {"channel": channel, "chat_id": chat_id[:200], "meta": clean_meta}


def _muc(uid: str, raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    chu_de = str(raw.get("chu_de") or raw.get("query") or "").strip()[:200]
    if not chu_de:
        return None
    ts = _so_thuc(raw.get("created_at", raw.get("ts")), time.time()) or time.time()
    iid = str(raw.get("id") or "").strip()[:64] or _legacy_id(uid, raw)
    interval = _interval(raw.get("alert_interval_min"))
    seen: list[dict[str, Any]] = []
    for item in raw.get("seen_items") or []:
        if not isinstance(item, dict):
            continue
        fp = str(item.get("fingerprint") or "").strip()[:128]
        if not fp:
            continue
        seen.append({
            "fingerprint": fp,
            "url": str(item.get("url") or "").strip()[:1000],
            "seen_at": _so_thuc(item.get("seen_at"), ts) or ts,
        })
    mode = "interval" if interval else "manual"
    return {
        "id": iid,
        "chu_de": chu_de,
        "query": str(raw.get("query") or chu_de).strip()[:300] or chu_de,
        "created_at": ts,
        "ts": ts,  # tương thích caller cũ
        "enabled": bool(raw.get("enabled", True)),
        "delivery_mode": mode,
        "alert_interval_min": interval,
        "next_check_at": _so_thuc(raw.get("next_check_at")),
        "last_checked_at": _so_thuc(raw.get("last_checked_at")),
        "last_seen_url": str(raw.get("last_seen_url") or "").strip()[:1000],
        "last_seen_at": _so_thuc(raw.get("last_seen_at")),
        "seen_items": seen[-_SEEN_CAP:],
        "delivery": _delivery(raw.get("delivery")),
    }


def _users(d: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Đọc cả schema v1 và v2, chỉ trả mục hợp lệ đã chuẩn hoá."""
    raw_users = d.get("users") if isinstance(d.get("users"), dict) else d
    out: dict[str, list[dict[str, Any]]] = {}
    for uid, raw_ds in raw_users.items():
        if uid in {"version", "users"} or not isinstance(raw_ds, list):
            continue
        key = str(uid).strip()
        if not key:
            continue
        ds = [m for m in (_muc(key, x) for x in raw_ds) if m is not None]
        if ds:
            out[key] = ds[:_TOI_DA]
    return out


def _dong_goi(users: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {"version": 2, "users": users}


def _new_record(chu_de: str, now: float) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:12],
        "chu_de": chu_de[:200],
        "query": chu_de[:300],
        "created_at": now,
        "ts": now,
        "enabled": True,
        "delivery_mode": "manual",
        "alert_interval_min": None,
        "next_check_at": None,
        "last_checked_at": None,
        "last_seen_url": "",
        "last_seen_at": None,
        "seen_items": [],
        "delivery": None,
    }


def _find(ds: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    key = str(key or "").strip()
    if not key:
        return None
    for item in ds:
        if key == item.get("id") or _fold(key) == _fold(str(item.get("chu_de") or "")):
            return item
    return None


def them(user_id: str, chu_de: str) -> bool:
    """Thêm/nâng-lên-đầu một chủ đề. False nếu dữ liệu không ghi được."""
    uid = str(user_id or "").strip()
    cd = str(chu_de or "").strip()
    if not uid or not cd:
        return False
    with _khoa_ghi():
        users = _users(_doc())
        f = _fold(cd)
        cu = users.get(uid) or []
        old = next((m for m in cu if _fold(str(m.get("chu_de") or "")) == f), None)
        if old is None:
            old = _new_record(cd, time.time())
        else:
            old["chu_de"] = cd[:200]
            old["query"] = cd[:300]
        users[uid] = [old] + [m for m in cu if m is not old and m.get("id") != old.get("id")]
        users[uid] = users[uid][:_TOI_DA]
        return _ghi_file(_dong_goi(users))


def liet_ke(user_id: str) -> list[dict[str, Any]]:
    uid = str(user_id or "").strip()
    if not uid:
        return []
    return [dict(m) for m in (_users(_doc()).get(uid) or [])]


def tim_muc(user_id: str, tu_khoa: str) -> list[dict[str, Any]]:
    """Tìm để HIỆN lựa chọn; hàm này tuyệt đối không xoá gì."""
    f = _fold(tu_khoa)
    if not f:
        return []
    return [m for m in liet_ke(user_id) if f in _fold(str(m.get("chu_de") or ""))]


def xoa(user_id: str, chu_de_hoac_id: str) -> bool:
    """Bỏ đúng MỘT mục theo id hoặc tên đầy đủ; không xoá bằng chuỗi mơ hồ."""
    uid = str(user_id or "").strip()
    key = str(chu_de_hoac_id or "").strip()
    if not uid or not key:
        return False
    with _khoa_ghi():
        users = _users(_doc())
        cu = users.get(uid) or []
        found = _find(cu, key)
        if found is None:
            return False
        users[uid] = [m for m in cu if m.get("id") != found.get("id")]
        return _ghi_file(_dong_goi(users))


def gan_nhat(user_id: str) -> str:
    ds = liet_ke(user_id)
    return str(ds[0].get("chu_de")) if ds else ""


def lay_muc(user_id: str, chu_de_hoac_id: str) -> dict[str, Any] | None:
    return _find(liet_ke(user_id), chu_de_hoac_id)


def bat_bao(user_id: str, chu_de_hoac_id: str, interval_min: int,
            *, delivery: dict[str, Any] | None, now: float | None = None) -> bool:
    """Bật báo có lịch. Caller chỉ gọi sau lựa chọn/đồng ý rõ ràng của người dùng."""
    uid = str(user_id or "").strip()
    interval = _interval(interval_min)
    where = _delivery(delivery)
    if not uid or not interval or where is None:
        return False
    now = float(now if now is not None else time.time())
    with _khoa_ghi():
        users = _users(_doc())
        item = _find(users.get(uid) or [], chu_de_hoac_id)
        if item is None:
            return False
        item.update({"enabled": True, "delivery_mode": "interval",
                     "alert_interval_min": interval, "next_check_at": now,
                     "delivery": where})
        return _ghi_file(_dong_goi(users))


def tam_dung_bao(user_id: str, chu_de_hoac_id: str) -> bool:
    uid = str(user_id or "").strip()
    if not uid:
        return False
    with _khoa_ghi():
        users = _users(_doc())
        item = _find(users.get(uid) or [], chu_de_hoac_id)
        if item is None:
            return False
        item.update({"delivery_mode": "manual", "alert_interval_min": None,
                     "next_check_at": None})
        return _ghi_file(_dong_goi(users))


def dat_lan_kiem_tra(user_id: str, chu_de_hoac_id: str, at: float) -> bool:
    """Dùng cho kiểm thử/điều phối để đặt lần quét kế tiếp của đúng một mục."""
    uid = str(user_id or "").strip()
    when = _so_thuc(at)
    if not uid or when is None:
        return False
    with _khoa_ghi():
        users = _users(_doc())
        item = _find(users.get(uid) or [], chu_de_hoac_id)
        if item is None or not item.get("alert_interval_min"):
            return False
        item["next_check_at"] = when
        return _ghi_file(_dong_goi(users))


def _claim_due(now: float) -> list[tuple[str, dict[str, Any]]]:
    """Nhận quyền quét trước khi gọi web để hai worker không gửi trùng."""
    claimed: list[tuple[str, dict[str, Any]]] = []
    with _khoa_ghi():
        users = _users(_doc())
        for uid, ds in users.items():
            for item in ds:
                interval = _interval(item.get("alert_interval_min"))
                due = _so_thuc(item.get("next_check_at"))
                if (len(claimed) >= _MAX_DUE_PER_TICK or not item.get("enabled")
                        or not interval or due is None or due > now
                        or not _delivery(item.get("delivery"))):
                    continue
                item["last_checked_at"] = now
                item["next_check_at"] = now + interval * 60
                claimed.append((uid, dict(item)))
        if not claimed:
            return []
        if not _ghi_file(_dong_goi(users)):
            return []
    return claimed


def _fingerprint(value: str) -> str:
    return hashlib.sha256(_fold(value).encode("utf-8")).hexdigest()


def ghi_ket_qua(user_id: str, chu_de_hoac_id: str, text: str,
                *, now: float | None = None) -> bool:
    """Ghi kết quả quét và trả True chỉ khi có bản tin/chùm tin chưa từng thấy."""
    uid = str(user_id or "").strip()
    body = str(text or "").strip()
    if not uid or not body:
        return False
    now = float(now if now is not None else time.time())
    result_fp = _fingerprint(body)
    urls = list(dict.fromkeys(_URL_RE.findall(body)))[:12]
    with _khoa_ghi():
        users = _users(_doc())
        item = _find(users.get(uid) or [], chu_de_hoac_id)
        if item is None:
            return False
        seen = list(item.get("seen_items") or [])
        known = {str(x.get("fingerprint") or "") for x in seen if isinstance(x, dict)}
        url_fps = [_fingerprint(url) for url in urls]
        is_new = (any(fp not in known for fp in url_fps) if url_fps
                  else result_fp not in known)
        additions = [{"fingerprint": result_fp, "url": urls[0] if urls else "", "seen_at": now}]
        additions += [{"fingerprint": fp, "url": url, "seen_at": now}
                      for fp, url in zip(url_fps, urls)]
        merged = seen + [x for x in additions if x["fingerprint"] not in known]
        item["seen_items"] = merged[-_SEEN_CAP:]
        item["last_checked_at"] = now
        if urls:
            item["last_seen_url"] = urls[0]
        if is_new:
            item["last_seen_at"] = now
        if not _ghi_file(_dong_goi(users)):
            return False
    return is_new


def _fetch_default(query: str, uid: str) -> str:
    from services.agent.capabilities import _h_web_search

    out = _h_web_search({"query": query}, {"user_id": uid})
    return str((out or {}).get("text") or "").strip()


def _deliver_default(item: dict[str, Any], text: str) -> None:
    delivery = _delivery(item.get("delivery"))
    if delivery is None:
        return
    from services.agent.reminders import _send

    _send(delivery["channel"], delivery["chat_id"], text, delivery.get("meta") or {})


def tick_once(*, fetcher: Callable[[str, str], str] | None = None,
              deliver: Callable[[dict[str, Any], str], None] | None = None,
              now: float | None = None) -> int:
    """Quét các mục đến hạn, chỉ gửi khi kết quả có fingerprint nguồn mới."""
    now = float(now if now is not None else time.time())
    fetcher = fetcher or _fetch_default
    deliver = deliver or _deliver_default
    sent = 0
    for uid, item in _claim_due(now):
        try:
            query = str(item.get("query") or item.get("chu_de") or "")
            body = str(fetcher(query, uid) or "").strip()
            if not body or not ghi_ket_qua(uid, str(item.get("id") or ""), body, now=now):
                continue
            deliver(item, f"📌 Có tin mới về «{item.get('chu_de')}»:\n{body}")
            sent += 1
            logger.info({"event": "tracked_topic_notified", "topic_id": item.get("id"),
                         "user_id": uid[:40]})
        except Exception as exc:
            logger.warning("tracked_topic: quét %s lỗi: %s", item.get("id"), str(exc)[:160])
    return sent


def _cfg() -> dict[str, Any]:
    try:
        from services.config import config
        raw = config.get().get("tracked_topic")
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _tick_seconds() -> float:
    try:
        return max(30.0, float(_cfg().get("tick_seconds") or 60.0))
    except (TypeError, ValueError):
        return 60.0


def is_scheduler_enabled() -> bool:
    return bool(_cfg().get("scheduler_enabled", True))


def _loop() -> None:
    while not _stop.is_set():
        try:
            tick_once()
        except Exception as exc:
            logger.warning("tracked_topic: tick lỗi: %s", str(exc)[:160])
        _stop.wait(_tick_seconds())


def start() -> None:
    """Bật worker nền; không có alert nào thì không gọi web."""
    global _started
    if _started or not is_scheduler_enabled():
        return
    _started = True
    _stop.clear()
    threading.Thread(target=_loop, name="tracked-topic", daemon=True).start()
    logger.info("tracked_topic: scheduler started")


def stop() -> None:
    global _started
    _stop.set()
    _started = False
