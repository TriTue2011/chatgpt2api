"""Approval gate policy — human-in-the-loop for side-effect tools.

Builds on ``state`` pending/always-allow storage. Adds:

- Autonomy tiers: ``supervised`` (default) | ``full`` | ``readonly``
- Clearer proposals with ASK chips (ok / luôn luôn / thôi)
- Optional durable pending (survives short restarts within TTL)
- Decision audit log (append-only JSONL)

Config (``agent_approval``)::

    enabled: bool (default True)
    level: supervised | full | readonly  (default supervised)
    ttl_seconds: int (default 600)
    persist_pending: bool (default True)
    auto_approve: list[str] — tool names always allowed for everyone
    gate_ha_fastpath: bool (default False) — if True, HA local control
        also pauses for approval (usually leave False for instant lights)
    hien_noi_dung_gui_tin: bool (default False) — câu duyệt GỬI TIN có kèm
        người nhận + nội dung không. Người dùng đổi bằng lời qua capability
        ``cai_dat_cau_duyet``; xem `format_proposal`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from services.config import DATA_DIR, config
from services.agent import state

logger = logging.getLogger(__name__)

_PENDING_FILE = Path(DATA_DIR) / "agent" / "approval_pending.json"
_AUDIT_FILE = Path(DATA_DIR) / "agent" / "approval_audit.jsonl"
_lock = threading.RLock()

# Tools that are CHANGE but low-stakes enough for full autonomy by default
# when level=full. Still gated under supervised.
_DEFAULT_AUTO_APPROVE: tuple[str, ...] = (
    # pure reads never hit this gate; keep empty for fail-closed write path
)

# Destructive / high-impact tools — ALWAYS need human confirm even when
# agent_approval.level=full (unless user previously said "luôn luôn" for that tool).
_ALWAYS_CONFIRM: tuple[str, ...] = (
    "create_automation",
    "send_to_contact",
)


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_approval")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def level() -> str:
    lv = str(_cfg().get("level") or "supervised").strip().lower()
    if lv in ("supervised", "full", "readonly", "read-only", "read_only"):
        if lv in ("read-only", "read_only"):
            return "readonly"
        return lv
    return "supervised"


def ttl_seconds() -> float:
    try:
        return float(_cfg().get("ttl_seconds") or 600)
    except (TypeError, ValueError):
        return 600.0


def persist_pending() -> bool:
    return bool(_cfg().get("persist_pending", True))


def auto_approve_names() -> set[str]:
    names = set(_DEFAULT_AUTO_APPROVE)
    raw = _cfg().get("auto_approve")
    if isinstance(raw, list):
        for x in raw:
            s = str(x or "").strip()
            if s:
                names.add(s)
    return names


def gate_ha_fastpath() -> bool:
    return bool(_cfg().get("gate_ha_fastpath", False))


def hien_noi_dung_gui_tin() -> bool:
    """Câu duyệt GỬI TIN có kèm người nhận + nội dung không? Mặc định KHÔNG."""
    return bool(_cfg().get("hien_noi_dung_gui_tin", False))


def dat_hien_noi_dung_gui_tin(bat: bool) -> bool:
    """Ghi cài đặt vào config rồi trả về giá trị mới.

    `config.update` chỉ trộn sâu cho providers, khoá khác bị THAY nguyên cụm —
    nên phải chép `agent_approval` cũ ra rồi mới ghi, kẻo mất level/ttl/auto_approve.
    """
    cur = dict(_cfg())
    cur["hien_noi_dung_gui_tin"] = bool(bat)
    config.update({"agent_approval": cur})
    return bool(bat)


def always_confirm_names() -> set[str]:
    names = set(_ALWAYS_CONFIRM)
    raw = _cfg().get("always_confirm")
    if isinstance(raw, list):
        for x in raw:
            s = str(x or "").strip()
            if s:
                names.add(s)
    return names


def needs_approval(user_id: str, capability: str, *, risk: str = "change") -> bool:
    """Whether this tool call must pause for human approval."""
    if not is_enabled():
        return False
    if (risk or "").lower() != "change":
        return False
    name = (capability or "").strip()
    if not name:
        return False
    if name in auto_approve_names():
        return False
    lv = level()
    if lv == "readonly":
        # block path is separate; still "needs approval" is false — we block
        return False
    # User previously chose "luôn luôn" for this tool → skip even always-confirm.
    if state.is_approved(user_id, name):
        return False
    # High-impact tools always ask (even level=full).
    if name in always_confirm_names():
        return True
    if lv == "full":
        return False
    # supervised
    return True


def is_blocked(capability: str, *, risk: str = "change") -> bool:
    """Readonly tier blocks all CHANGE tools (no approve path)."""
    if not is_enabled():
        return False
    if level() != "readonly":
        return False
    return (risk or "").lower() == "change"


def summarize_action(capability: str, args: dict[str, Any], description: str = "") -> str:
    """One-line human summary of the proposed side effect."""
    args = args or {}
    # send_to_contact / similar: show recipient + body together
    msg = str(args.get("message") or "").strip()
    to = str(args.get("to") or args.get("name") or "").strip()
    if msg and to:
        s = f"→ {to}: {msg}"
        return s[:280] + ("…" if len(s) > 280 else "")
    # Loa: PHẢI hiện loa nào + âm lượng + thời điểm, không chỉ nội dung.
    #
    # Đo thật 02/08 21:25 — chủ máy nói "loa phòng khách" mà câu duyệt chỉ có
    # nội dung: duyệt một việc không thấy tham số quan trọng nhất thì lời duyệt
    # đó chẳng nói lên điều gì, và bản ghi audit cũng không tra lại được.
    spk = str(args.get("speaker") or "").strip()
    txt = str(args.get("text") or "").strip()
    if spk and txt:
        phan = [f"→ {spk}"]
        vol = args.get("volume")
        if vol not in (None, ""):
            phan.append(f"âm lượng {vol}%")
        elif args.get("giu_am_luong"):
            phan.append("giữ nguyên âm lượng")
        khi = str(args.get("when") or "").strip()
        if khi:
            phan.append(f"lịch: {khi}")
        else:
            try:
                _p = float(args.get("delay_minutes") or 0)
                phan.append(f"sau {_p:g} phút" if _p > 0 else "đọc ngay")
            except (TypeError, ValueError):
                phan.append("đọc ngay")
        s = f"{' · '.join(phan)}\n{txt}"
        return s[:280] + ("…" if len(s) > 280 else "")
    for key in (
        "command", "request", "fact", "message", "content", "task", "query",
        "text", "to", "name",
    ):
        val = args.get(key)
        if val is not None and str(val).strip():
            s = str(val).strip()
            if len(s) > 280:
                s = s[:280] + "…"
            return s
    try:
        raw = json.dumps(args, ensure_ascii=False)
    except Exception:
        raw = str(args)
    if len(raw) > 280:
        raw = raw[:280] + "…"
    if description:
        return f"{description.split('.')[0]} — {raw}"
    return raw or capability

_KHOI_ASK = (
    "<<<ASK>>>\n"
    "Ok, làm đi | ok\n"
    "Luôn luôn (khỏi hỏi lại) | luôn luôn\n"
    "Thôi | thôi\n"
    "<<<END>>>"
)

# Tool GỬI TIN: câu duyệt CHỈ CÒN ba lựa chọn — không mở lời, không nhắc người
# nhận, không chép lại nội dung tin.
#
# Đo thật 04/08 22:15–22:19 — chủ máy gõ "gửi vào nhóm homeassistant bằng zalo cá
# nhân với nội dung 'mai đi họp'" rồi phải nhắc BỐN lần "chỉ đưa ra lựa chọn,
# không nhắc lại nội dung". Bot còn lưu đúng câu dặn đó vào bộ nhớ mà câu duyệt
# vẫn y nguyên: câu duyệt do CODE ở đây dựng, còn bộ nhớ chỉ đi vào prompt của
# model, nên dặn kiểu gì cũng không đổi được chữ này.
#
# Người dùng vừa gõ yêu cầu ngay câu trên, nên nhắc lại là tiếng ồn. Chỉ gọn ở
# phần HIỆN RA — `set_pending` và audit log vẫn giữ tóm tắt đầy đủ, tra lại vẫn
# biết đã duyệt gửi gì cho ai.
_TOOL_CHI_LUA_CHON: tuple[str, ...] = ("send_to_contact",)


def format_proposal(
    capability: str,
    args: dict[str, Any],
    *,
    description: str = "",
    label: str = "",
) -> str:
    """User-facing approval prompt with ASK chips."""
    if capability in _TOOL_CHI_LUA_CHON and not hien_noi_dung_gui_tin():
        # GỬI FILE thì hiện TÊN FILE, dù đang ở chế độ chỉ-ba-lựa-chọn.
        #
        # Tên file không phải "nội dung tin nhắn" — nó là thứ DUY NHẤT phân biệt
        # gửi đúng với gửi nhầm, nhất là khi người dùng nói "gửi file vừa tạo"
        # và bot tự lấy file mới nhất. Duyệt gửi tài liệu vào nhóm mà không thấy
        # tên thì là duyệt mù, và gửi nhầm tài liệu thì không rút lại được.
        _tep = str((args or {}).get("file") or (args or {}).get("file_name")
                   or (args or {}).get("document") or "").strip()
        if _tep:
            from pathlib import Path as _P
            return f"📎 {_P(_tep).name}\n\n{_KHOI_ASK}"
        return _KHOI_ASK
    summary = summarize_action(capability, args, description)
    verb = (label or description or capability).split(".")[0]
    # Nói ĐÚNG việc sắp làm, đừng liệt kê các chế độ có thể. Yêu cầu 02/08:
    # "khi không thời gian thì đâu cần phải «Đọc thông báo ra loa (ngay, hoặc hẹn
    # giờ)» mà nó phải là «đọc thông báo ra loa ngay»".
    if capability in ("announce_on_speaker", "speak_to_speaker") and isinstance(args, dict):
        _khi = str(args.get("when") or "").strip()
        try:
            _phut = float(args.get("delay_minutes") or 0)
        except (TypeError, ValueError):
            _phut = 0.0
        if _khi:
            verb = f"đặt lịch đọc thông báo ra loa ({_khi})"
        elif _phut > 0:
            verb = f"hẹn đọc thông báo ra loa sau {_phut:g} phút"
        else:
            verb = "đọc thông báo ra loa NGAY"
    dau_de = f"Em định **{verb}**:\n{summary}" if summary else f"Em định **{verb}**."
    return (
        f"{dau_de}\n\n"
        f"Anh/chị duyệt không ạ?\n"
        f"<<<ASK>>>\n"
        f"Ok, làm đi | ok\n"
        f"Luôn luôn (khỏi hỏi lại) | luôn luôn\n"
        f"Thôi | thôi\n"
        f"<<<END>>>"
    )


def set_pending(
    user_id: str,
    capability: str,
    args: dict[str, Any],
    summary: str = "",
) -> None:
    summary = summary or summarize_action(capability, args)
    state.set_pending(user_id, capability, args, summary)
    if persist_pending():
        _write_pending_disk(user_id, {
            "capability": capability,
            "args": args,
            "summary": summary,
            "ts": time.time(),
        })
    log_event("pending", user_id, capability, summary=summary)


def get_pending(user_id: str) -> Optional[dict[str, Any]]:
    """In-memory first; fall back to disk (within TTL)."""
    p = state.get_pending(user_id)
    if p is not None:
        return p
    if not persist_pending():
        return None
    disk = _read_pending_disk(user_id)
    if not disk:
        return None
    age = time.time() - float(disk.get("ts") or 0)
    if age > ttl_seconds():
        clear_pending(user_id)
        return None
    # restore into memory so classify path works
    state.set_pending(
        user_id,
        str(disk.get("capability") or ""),
        disk.get("args") or {},
        str(disk.get("summary") or ""),
    )
    return state.get_pending(user_id)


def clear_pending(user_id: str) -> None:
    state.clear_pending(user_id)
    if persist_pending():
        _drop_pending_disk(user_id)


def resolve(
    user_id: str,
    verdict: str,
    *,
    capability: str = "",
) -> None:
    """Record decision; caller still executes the tool."""
    log_event(
        f"decision_{verdict}",
        user_id,
        capability or "",
        summary=verdict,
    )
    if verdict == "always" and capability:
        state.grant_always(user_id, capability)
    clear_pending(user_id)


def log_event(
    kind: str,
    user_id: str,
    capability: str,
    *,
    summary: str = "",
) -> None:
    """Append-only audit JSONL (P2#12). Có prev_hash để phát hiện cắt/sửa file."""
    import hashlib

    row = {
        "ts": time.time(),
        "kind": kind,
        "user_id": str(user_id),
        "capability": capability,
        "summary": (summary or "")[:400],
    }
    try:
        _AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            prev = "genesis"
            if _AUDIT_FILE.exists() and _AUDIT_FILE.stat().st_size > 0:
                try:
                    # đọc dòng cuối (hash chain)
                    with _AUDIT_FILE.open("rb") as rf:
                        rf.seek(0, 2)
                        size = rf.tell()
                        step = min(size, 4096)
                        rf.seek(-step, 2)
                        tail = rf.read().decode("utf-8", errors="replace")
                    last = [ln for ln in tail.splitlines() if ln.strip()][-1]
                    prev_obj = json.loads(last)
                    prev = str(prev_obj.get("hash") or prev_obj.get("prev") or "genesis")
                except Exception:
                    prev = "unknown"
            row["prev"] = prev
            body = json.dumps(
                {k: row[k] for k in ("ts", "kind", "user_id", "capability", "summary", "prev")},
                ensure_ascii=False, sort_keys=True,
            )
            row["hash"] = hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]
            with _AUDIT_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("approval_gate: audit write failed: %s", exc)


def _load_all_pending() -> dict[str, Any]:
    try:
        if _PENDING_FILE.exists():
            data = json.loads(_PENDING_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.warning("approval_gate: read pending failed: %s", exc)
    return {}


def _write_pending_disk(user_id: str, payload: dict[str, Any]) -> None:
    with _lock:
        data = _load_all_pending()
        data[str(user_id)] = payload
        try:
            _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
            _PENDING_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("approval_gate: write pending failed: %s", exc)


def _read_pending_disk(user_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        data = _load_all_pending()
        p = data.get(str(user_id))
        return p if isinstance(p, dict) else None


def _drop_pending_disk(user_id: str) -> None:
    with _lock:
        data = _load_all_pending()
        if str(user_id) not in data:
            return
        data.pop(str(user_id), None)
        try:
            _PENDING_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass


def _reset_for_tests(agent_dir: Path | None = None) -> None:
    global _PENDING_FILE, _AUDIT_FILE
    with _lock:
        if agent_dir is not None:
            _PENDING_FILE = Path(agent_dir) / "approval_pending.json"
            _AUDIT_FILE = Path(agent_dir) / "approval_audit.jsonl"
        try:
            if _PENDING_FILE.exists():
                _PENDING_FILE.unlink()
        except OSError:
            pass
