"""Per-request context: source (who called) + dest provider account (who served).

Works across the FastAPI threadpool by storing state under a ``request_id``
(thread-local + global map). Providers call ``note_provider_account`` from
worker threads; LoggedCall / journal read via ``get_dest(request_id)``.
"""

from __future__ import annotations

import threading
import time
import uuid
from contextvars import ContextVar
from typing import Any

_lock = threading.RLock()
# request_id -> {source, dest, trail, ts}
_STORE: dict[str, dict[str, Any]] = {}
_local = threading.local()

# Best-effort ContextVar (same-thread paths: orchestrator tools, etc.)
_source_cv: ContextVar[dict[str, Any]] = ContextVar("req_source", default={})
_dest_cv: ContextVar[dict[str, Any]] = ContextVar("req_dest", default={})
_dest_trail_cv: ContextVar[list[dict[str, Any]]] = ContextVar("req_dest_trail", default=[])
_rid_cv: ContextVar[str] = ContextVar("req_id", default="")

_TTL_SEC = 600  # drop finished request bags after 10 min


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def _prune() -> None:
    now = time.time()
    dead = [k for k, v in _STORE.items() if now - float(v.get("ts") or 0) > _TTL_SEC]
    for k in dead:
        _STORE.pop(k, None)


def begin(request_id: str = "") -> str:
    """Start (or re-bind) a request bag. Call at API entry and at handler start."""
    rid = str(request_id or "").strip() or new_request_id()
    _local.rid = rid
    _rid_cv.set(rid)
    with _lock:
        _prune()
        if rid not in _STORE:
            _STORE[rid] = {
                "source": {},
                "dest": {},
                "trail": [],
                "ts": time.time(),
            }
        else:
            _STORE[rid]["ts"] = time.time()
    return rid


def current_request_id() -> str:
    rid = str(getattr(_local, "rid", "") or "").strip()
    if rid:
        return rid
    return str(_rid_cv.get() or "").strip()


def end(request_id: str = "") -> None:
    rid = str(request_id or current_request_id() or "").strip()
    if not rid:
        return
    with _lock:
        _STORE.pop(rid, None)
    if getattr(_local, "rid", None) == rid:
        try:
            del _local.rid
        except Exception:
            _local.rid = ""


def reset_all() -> None:
    """Clear thread-local + ContextVar (does not wipe other requests' bags)."""
    rid = current_request_id()
    _source_cv.set({})
    _dest_cv.set({})
    _dest_trail_cv.set([])
    _rid_cv.set("")
    if rid:
        end(rid)
    try:
        del _local.rid
    except Exception:
        pass


def set_source(request_id: str = "", **kwargs: Any) -> None:
    rid = begin(request_id) if request_id else (current_request_id() or begin())
    cur = {k: v for k, v in kwargs.items() if v is not None and v != ""}
    _source_cv.set({**(_source_cv.get() or {}), **cur})
    with _lock:
        bag = _STORE.setdefault(rid, {"source": {}, "dest": {}, "trail": [], "ts": time.time()})
        bag["source"] = {**(bag.get("source") or {}), **cur}
        bag["ts"] = time.time()


def get_source(request_id: str = "") -> dict[str, Any]:
    rid = str(request_id or current_request_id() or "").strip()
    if rid:
        with _lock:
            bag = _STORE.get(rid)
            if bag and bag.get("source"):
                return dict(bag["source"])
    return dict(_source_cv.get() or {})


def set_dest(
    *,
    provider: str = "",
    account: str = "",
    model: str = "",
    account_id: str = "",
    request_id: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    row: dict[str, Any] = {
        "provider": str(provider or "")[:80],
        "account": str(account or "")[:120],
        "model": str(model or "")[:120],
        "account_id": str(account_id or "")[:80],
    }
    if extra:
        for k, v in extra.items():
            if v is None or v == "":
                continue
            row[str(k)[:40]] = str(v)[:200]
    _dest_cv.set(row)
    rid = str(request_id or current_request_id() or "").strip()
    if not rid:
        rid = begin()
    with _lock:
        bag = _STORE.setdefault(rid, {"source": {}, "dest": {}, "trail": [], "ts": time.time()})
        bag["dest"] = row
        trail = list(bag.get("trail") or [])
        if not trail or trail[-1] != row:
            trail.append(row)
            bag["trail"] = trail[-12:]
        bag["ts"] = time.time()
    trail_cv = list(_dest_trail_cv.get() or [])
    if not trail_cv or trail_cv[-1] != row:
        trail_cv.append(row)
        _dest_trail_cv.set(trail_cv[-12:])


def get_dest(request_id: str = "") -> dict[str, Any]:
    rid = str(request_id or current_request_id() or "").strip()
    if rid:
        with _lock:
            bag = _STORE.get(rid)
            if bag and bag.get("dest"):
                return dict(bag["dest"])
    return dict(_dest_cv.get() or {})


def get_dest_trail(request_id: str = "") -> list[dict[str, Any]]:
    rid = str(request_id or current_request_id() or "").strip()
    if rid:
        with _lock:
            bag = _STORE.get(rid)
            if bag and bag.get("trail"):
                return list(bag["trail"])
    return list(_dest_trail_cv.get() or [])


def note_provider_account(
    provider: str,
    account: str = "",
    *,
    model: str = "",
    account_id: str = "",
    request_id: str = "",
    **extra: Any,
) -> None:
    try:
        set_dest(
            provider=provider,
            account=account,
            model=model,
            account_id=account_id,
            request_id=request_id,
            extra=extra or None,
        )
    except Exception:
        pass
