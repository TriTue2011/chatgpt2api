"""Subconscious-lite heartbeat — background skip / act / escalate loop.

Periodic tick (default 5 min) evaluates system + user tasks:

- **skip** — nothing to do
- **act** — run a deterministic handler (e.g. write wiki daily digest)
- **escalate** — notify configured admin user_ids (or log only)

User tasks live in ``DATA_DIR/agent/HEARTBEAT.md`` (one per line)::

    # comments ignored
    [read] Kiểm tra thiết bị offline
    [write] Gửi tóm tắt nếu có tin lạ
    wiki_daily_digest          # bare id = system task name override

Config (``agent_heartbeat``)::

    enabled: bool (default True)
    tick_seconds: int (default 300, min 60)
    admin_user_ids: list[str]  — orchestrator user_ids to notify on escalate
    max_acts_per_tick: int (default 3)
    activity_log: bool (default True)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_AGENT_DIR = Path(DATA_DIR) / "agent"
_HEARTBEAT_MD = _AGENT_DIR / "HEARTBEAT.md"
_STATE_FILE = _AGENT_DIR / "heartbeat_state.json"
_ACTIVITY_FILE = _AGENT_DIR / "heartbeat_activity.jsonl"
_DEFAULT_HEARTBEAT = """# Heartbeat — một dòng / task (Phase B)
# [read] = chỉ quan sát; [write] = có thể gửi tin / side-effect khi escalate
# Hệ thống luôn chạy: wiki_daily_digest

[read] Rà pending approvals nếu có
"""

_lock = threading.RLock()
_started = False
_stop = threading.Event()
# last run bookkeeping: task_id -> ts
_state: dict[str, Any] = {}


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_heartbeat")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def tick_seconds() -> float:
    try:
        return max(60.0, float(_cfg().get("tick_seconds") or 300))
    except (TypeError, ValueError):
        return 300.0


def max_acts_per_tick() -> int:
    try:
        return max(1, int(_cfg().get("max_acts_per_tick") or 3))
    except (TypeError, ValueError):
        return 3


def admin_user_ids() -> list[str]:
    raw = _cfg().get("admin_user_ids")
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def activity_log_enabled() -> bool:
    return bool(_cfg().get("activity_log", True))


def _load_state() -> dict[str, Any]:
    global _state
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _state = data
                return _state
    except Exception as exc:
        logger.warning("heartbeat: load state failed: %s", exc)
    _state = {}
    return _state


def _save_state() -> None:
    try:
        _AGENT_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(_state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("heartbeat: save state failed: %s", exc)


def _log_activity(kind: str, task_id: str, detail: str = "") -> None:
    if not activity_log_enabled():
        return
    row = {
        "ts": time.time(),
        "kind": kind,
        "task": task_id,
        "detail": (detail or "")[:500],
    }
    try:
        _AGENT_DIR.mkdir(parents=True, exist_ok=True)
        with _ACTIVITY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _ensure_heartbeat_md() -> None:
    try:
        _AGENT_DIR.mkdir(parents=True, exist_ok=True)
        if not _HEARTBEAT_MD.exists():
            _HEARTBEAT_MD.write_text(_DEFAULT_HEARTBEAT, encoding="utf-8")
    except OSError as exc:
        logger.warning("heartbeat: seed HEARTBEAT.md failed: %s", exc)


def _parse_tasks() -> list[dict[str, Any]]:
    """Return task dicts: id, intent (read|write), text, system?."""
    tasks: list[dict[str, Any]] = []
    # Always include system digest task first
    tasks.append({
        "id": "wiki_daily_digest",
        "intent": "read",
        "text": "Viết wiki daily digest nếu đến giờ và chưa có file hôm nay",
        "system": True,
    })
    tasks.append({
        "id": "open_goals_nudge",
        "intent": "read",
        "text": "Nhắc admin nếu có goal doing quá 24h (khi có admin_user_ids)",
        "system": True,
    })
    tasks.append({
        "id": "chatlog_nhac_scan",
        "intent": "write",
        "text": "Quét nhật ký nhóm: ai nhắc tới + có hẹn → đặt nhắc trước 1 ngày/1 giờ",
        "system": True,
    })
    tasks.append({
        "id": "user_profile_distill",
        "intent": "read",
        "text": "Chưng cất hồ sơ người dùng + fact từ hội thoại (mỗi ngày, sau giờ cấu hình)",
        "system": True,
    })
    # khoa_cua_nha KHÔNG còn ở đây: nó có vòng riêng nhịp 15 giây
    # (`khoa_cua_nha.start`, gọi từ api/app.py). Để cả hai là gọi API Tuya đôi
    # mà chẳng nhanh thêm — nhịp chung tối thiểu 60 giây vẫn chậm hơn 4 lần.
    tasks.append({
        "id": "tinh_huong_nha",
        "intent": "read",
        "text": "Học tình huống trong nhà (giờ ăn, buổi sáng…) rồi xin duyệt tên",
        "system": True,
    })
    tasks.append({
        "id": "canh_bao_nha",
        "intent": "read",
        "text": "Báo thiết bị nhà hỏng/đơ (5p → 30p → 60p → 6h → mỗi ngày)",
        "system": True,
    })
    tasks.append({
        "id": "cap_quyen",
        "intent": "write",
        "text": "Gỡ quyền dùng bot đã hết hạn (anh duyệt theo gói + thời hạn trong kênh) rồi báo anh",
        "system": True,
    })
    # Ba việc dưới đây từng chỉ có hàm xử lý trong `_HANDLERS` mà KHÔNG có ở danh sách này → không bao giờ chạy (phát
    # hiện 05/10/2026: tự đánh giá luật duyệt và tự bật bình nóng lạnh theo nếp chưa chạy lần nào). Có test canh.
    tasks.append({
        "id": "luat_duyet",
        "intent": "read",
        "text": "Tự đánh giá luật đã duyệt mỗi ngày: luật chết / bật rồi tắt ngay → chấm sai, giải lại, hỏi anh",
        "system": True,
    })
    tasks.append({
        "id": "tu_bat_theo_nep",
        "intent": "write",
        "text": "Thiết bị anh bật «tự bật theo nếp» (bình nóng lạnh): tới giờ nếp thì bật, đủ thời lượng thì tắt",
        "system": True,
    })
    tasks.append({
        "id": "loi_khuyen_nha",
        "intent": "read",
        "text": "Chu kỳ học (5, 5, 7×4 ngày rồi mỗi tháng): lời khuyên thời gian ở lại / vắng từ nhật ký, hỏi anh",
        "system": True,
    })
    tasks.append({
        "id": "loa_cho",
        "intent": "read",
        "text": "Thông báo loa giữ lại lúc nhà vắng — có người về thì phát",
        "system": True,
    })
    tasks.append({
        "id": "lech_nep",
        "intent": "read",
        "text": "Thiết bị không hoạt động đúng giờ quen thì hỏi nhẹ kèm nguyên nhân — chỉ khi đã tích",
        "system": True,
    })
    tasks.append({
        "id": "tam_hon",
        "intent": "read",
        "text": "Bot cảm và viết/vẽ từ chuyện thật trong nhà — chỉ khi chủ máy đã tích kích hoạt",
        "system": True,
    })
    tasks.append({
        "id": "du_doan_nha",
        "intent": "read",
        "text": "Học thói quen theo bối cảnh (lux, nhiệt độ, hiện diện) rồi gợi ý",
        "system": True,
    })
    tasks.append({
        "id": "bai_hoc",
        "intent": "read",
        "text": "Bản tin «em học được gì» — mặc định TẮT (mqtt.bai_hoc.bao)",
        "system": True,
    })
    tasks.append({
        "id": "hieu_thiet_bi_nha",
        "intent": "read",
        "text": "Bot học hỏi tự hiểu thiết bị nhà (mã nào là một, cái nào nên học) rồi báo nhóm học hỏi",
        "system": True,
    })
    tasks.append({
        "id": "thoi_quen_nha",
        "intent": "read",
        "text": "Bot học hỏi chọn ngoại vi theo khu vực cho từng thiết bị được học rồi báo nhóm học hỏi",
        "system": True,
    })

    _ensure_heartbeat_md()
    try:
        text = _HEARTBEAT_MD.read_text(encoding="utf-8")
    except OSError:
        return tasks

    seen = {t["id"] for t in tasks}
    for i, line in enumerate(text.splitlines()):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        intent = "read"
        body = raw
        if raw.lower().startswith("[write]"):
            intent = "write"
            body = raw[7:].strip()
        elif raw.lower().startswith("[read]"):
            intent = "read"
            body = raw[6:].strip()
        if not body:
            continue
        # bare known system id
        tid = body.split()[0].lower() if body.split()[0].isidentifier() and " " not in body else f"user_{i}"
        if body in ("wiki_daily_digest", "open_goals_nudge"):
            continue  # already seeded
        if tid in seen and body in seen:
            continue
        uid = f"user_{i}_{abs(hash(body)) % 10000}"
        if body.isidentifier():
            uid = body
        if uid in seen:
            continue
        seen.add(uid)
        tasks.append({
            "id": uid,
            "intent": intent,
            "text": body,
            "system": False,
        })
    return tasks


# ── Task handlers ────────────────────────────────────────────────────────────


def _eval_wiki_digest() -> tuple[str, str]:
    """Return (decision, detail) for wiki_daily_digest."""
    try:
        from services.agent import wiki as w
        if not w.digest_due_now():
            return "skip", "chưa đến giờ hoặc đã có digest"
        out = w.build_daily_digest(force=False)
        if not out.get("ok"):
            return "skip", str(out.get("text") or "digest fail")
        if out.get("skipped"):
            return "skip", f"đã có digest {out.get('day')}"
        detail = f"digest {out.get('day')}: {out.get('note_count', 0)} notes"
        # escalate = notify admins of digest summary
        admins = admin_user_ids()
        if admins and out.get("text"):
            snippet = str(out["text"])[:800]
            for uid in admins:
                _notify_user(uid, f"📰 Wiki digest hôm nay:\n{snippet}")
            return "act", detail + f" · gửi {len(admins)} admin"
        return "act", detail
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_open_goals() -> tuple[str, str]:
    admins = admin_user_ids()
    if not admins:
        return "skip", "không cấu hình admin_user_ids"
    try:
        from services.agent import goals as g
        if not g.is_enabled():
            return "skip", "goals tắt"
        now = time.time()
        stale: list[str] = []
        for uid in admins:
            for row in g.list_for(uid, status="doing", limit=20):
                age = now - float(row.get("updated_at") or 0)
                if age >= 86400:
                    stale.append(f"{uid}: {row.get('title')} (`{row.get('id')}`)")
        if not stale:
            return "skip", "không có goal doing >24h"
        msg = "🎯 Goal đang `doing` quá 24h:\n" + "\n".join(f"• {s}" for s in stale[:8])
        for uid in admins:
            _notify_user(uid, msg)
        return "escalate", f"{len(stale)} goal stale"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_user_task(task: dict[str, Any]) -> tuple[str, str]:
    """User HEARTBEAT lines: escalate write intents to admin; skip read unless interval."""
    tid = task["id"]
    st = _load_state()
    last = float((st.get("tasks") or {}).get(tid) or 0)
    # User tasks at most once per 6 hours
    if last and time.time() - last < 6 * 3600:
        return "skip", "chưa đủ 6h từ lần trước"
    intent = task.get("intent") or "read"
    text = task.get("text") or tid
    admins = admin_user_ids()
    if not admins:
        return "skip", "không có admin để escalate"
    if intent == "write":
        for uid in admins:
            _notify_user(
                uid,
                f"💓 Heartbeat gợi ý việc (write):\n{text}\n"
                f"Anh/chị muốn em làm thì nhắn lại (hoặc đặt schedule).",
            )
        return "escalate", text[:120]
    # read: gentle nudge less often
    for uid in admins:
        _notify_user(
            uid,
            f"💓 Heartbeat nhắc kiểm tra (read):\n{text}",
        )
    return "escalate", text[:120]


def _notify_user(user_id: str, text: str) -> None:
    """Best-effort send via reminders channel mapping."""
    try:
        from services.agent import reminders as rem
        channel, chat_id = rem.channel_of(user_id)
        rem._send(channel, chat_id, text, {})
    except Exception as exc:
        logger.info("heartbeat: notify %s failed: %s", user_id, exc)


# ── Tự nhắc theo nhật ký nhóm (luật «ai nhắc tôi + có hẹn → báo trước») ────────

def _trich_hen_llm(msgs: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    """Nhờ MODEL đọc các tin nhắc-tới, trả mốc hẹn TƯƠNG LAI nếu có (giờ VN).

    Vào: [{id, ts, sender, text}]. Ra: {msg_id: {"iso": 'YYYY-MM-DDTHH:MM',
    "label": '...'}}. Chỉ giữ id có hẹn RÕ RÀNG — model bỏ qua id không có hẹn.
    Lỗi/không parse được → {} (không tạo nhắc còn hơn tạo nhầm)."""
    if not msgs:
        return {}
    try:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Ho_Chi_Minh")
    except Exception:
        from datetime import datetime as _dt, timezone as _tzc, timedelta as _td
        tz = _tzc(_td(hours=7))
    try:
        from services.agent.runtime import call_model, content_of
        model = str(config.get().get("telegram_ai_model") or "").strip() or "cx/auto"
        hom_nay = _dt.now(tz).strftime("%Y-%m-%d (thứ %w)")
        dong = "\n".join(f'{m["id"]}\t{str(m.get("text") or "")[:200]}' for m in msgs)
        sys_p = (
            "Bạn trích LỊCH HẸN từ tin nhắn nhóm tiếng Việt. Hôm nay là "
            f"{hom_nay}, múi giờ Việt Nam. Mỗi dòng có dạng «id<TAB>nội dung». "
            "Với dòng nào nêu MỐC THỜI GIAN HẸN CỤ THỂ trong TƯƠNG LAI (vd 'mai "
            "8h', 'chiều thứ 6', '20/8 14:00', 'thứ Ba tuần sau 9h30'), tính ra "
            "thời điểm tuyệt đối rồi trả về. Bỏ qua dòng KHÔNG có hẹn rõ (chỉ hỏi "
            "han, cảm thán, con số vu vơ đều BỎ). CHỈ trả JSON đúng dạng: "
            '{"hen":[{"id":<số>,"iso":"YYYY-MM-DDTHH:MM","nhan":"<nhãn ngắn>"}]}'
        )
        resp = call_model(
            model,
            [{"role": "system", "content": sys_p},
             {"role": "user", "content": dong[:4000]}],
            timeout=60, max_tokens=500, no_smart_home=True,
            response_format={"type": "json_object"},
        )
        if resp.get("error"):
            return {}
        data = json.loads(content_of(resp) or "{}")
        out: dict[int, dict[str, str]] = {}
        for h in (data.get("hen") or []):
            try:
                out[int(h["id"])] = {"iso": str(h.get("iso") or ""),
                                     "label": str(h.get("nhan") or "")}
            except (KeyError, TypeError, ValueError):
                continue
        return out
    except Exception as exc:
        logger.info("heartbeat: trich_hen_llm error: %s", exc)
        return {}


def _tao_nhac_reminder(deliver_to: str, text: str, when_ts: float,
                       meta: dict[str, Any]) -> None:
    """Đặt một reminder 'once' vào `when_ts`, gửi tới `deliver_to`. Dùng
    `meta` (bot_id/account…) đã chốt lúc đặt luật để nền gửi đúng chỗ."""
    from services.agent import reminders as rem
    sched = {"kind": "once", "due_at": when_ts, "next_run_at": when_ts}
    rem.create(deliver_to, text, sched, mode="notify",
               meta_extra=meta if isinstance(meta, dict) else None)


def _eval_chatlog_nhac() -> tuple[str, str]:
    """Quét luật «tự nhắc»: tin nhắc-tới + có hẹn → đặt nhắc trước các mốc."""
    try:
        from services.agent import chatlog
    except Exception as exc:
        return "skip", f"chatlog import error: {exc}"
    try:
        if not chatlog.luat_tat_ca():
            return "skip", "chưa có luật tự nhắc"
        from services.agent import reminders as rem
        if not rem.is_enabled():
            return "skip", "nhắc hẹn đang tắt (agent_reminders)"
        n = chatlog.quet_nhac_hen(trich_hen=_trich_hen_llm,
                                  tao_nhac=_tao_nhac_reminder)
        return ("act", f"đặt {n} nhắc") if n else ("skip", "không có hẹn mới")
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_distill() -> tuple[str, str]:
    """Chưng cất hồ sơ người dùng (L3) + fact (L1) — services.agent.distill."""
    try:
        from services.agent import distill
        if not distill.is_enabled():
            return "skip", "distill tắt (agent_distill)"
        if not distill.due_now():
            return "skip", "chưa đến giờ hoặc hôm nay đã chạy"
        # Chạy NỀN: lô này gọi model tối đa ~12 phút — không được ghim thread
        # heartbeat (chatlog_nhac_scan + task người dùng còn chờ sau nó).
        # run_once tự NHẬN ngày ngay khi bắt đầu nên tick sau không chạy đúp.
        threading.Thread(target=distill.run_once, name="agent-distill",
                         daemon=True).start()
        return "act", "chưng cất hồ sơ chạy nền (kết quả xem log distill)"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_canh_bao_nha() -> tuple[str, str]:
    """Cảnh báo thiết bị nhà hỏng — services.canh_bao_nha.

    Tick 5 phút của heartbeat CHÍNH LÀ mốc báo lại đầu tiên (5p → 30p → 60p →
    6h → mỗi ngày), nên không cần hẹn giờ riêng.
    """
    try:
        from services import canh_bao_nha
        if not canh_bao_nha.is_enabled():
            return "skip", "cảnh báo nhà tắt (mqtt.canh_bao)"
        try:
            from services import su_co_thiet_bi
            su_co_thiet_bi.quet()            # thiết bị bot đang tự điều khiển mà mất kết nối — báo nhanh, kèm nguyên nhân
        except Exception as exc:  # noqa: BLE001
            logger.warning({"event": "su_co_thiet_bi_quet_loi", "error": str(exc)[:160]})
        try:
            from services import mang_nha
            mang_nha.quet()                  # máy lạ vào mạng nhà, internet rớt / có lại (router MikroTik)
        except Exception as exc:  # noqa: BLE001
            logger.warning({"event": "mang_nha_quet_loi", "error": str(exc)[:160]})
        kq = canh_bao_nha.chay_mot_lan()
        if kq.get("gui"):
            return "act", f"báo {kq['so_loi']} lỗi tới {kq['gui']} người"
        return "skip", kq.get("ly_do") or f"{kq.get('tong_hong', 0)} lỗi, chưa tới hạn báo"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_tinh_huong() -> tuple[str, str]:
    """Học tình huống trong nhà — services.tinh_huong_nha.

    Chạy nền vì có gọi model đặt tên (tối đa 3 lần/ngày), không được ghim
    luồng heartbeat như _eval_distill đã lường.
    """
    try:
        from services import tinh_huong_nha as th
        if not th.is_enabled():
            return "skip", "học tình huống tắt (mqtt.tinh_huong)"
        # Một ngày một lần là đủ: nếp sinh hoạt không đổi theo giờ. Ghi mốc
        # TRƯỚC khi chạy nền, nếu không tick sau (5 phút) lại chạy đúp.
        import time as _t
        hom_nay = _t.strftime("%Y-%m-%d")
        if _state.get("tinh_huong_ngay") == hom_nay:
            return "skip", "hôm nay đã học rồi"
        _state["tinh_huong_ngay"] = hom_nay
        _save_state()
        threading.Thread(target=th.chay_mot_lan, name="tinh-huong-nha",
                         daemon=True).start()
        return "act", "học tình huống chạy nền"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_khoa_cua() -> tuple[str, str]:
    """Báo ai mở cửa + hỏi tên người lạ — services.khoa_cua_nha.

    Tick 5 phút: đủ nhanh để báo người lạ, và bản tóm tắt tự canh giờ theo
    nếp ngủ của nhà nên không cần hẹn giờ riêng.
    """
    try:
        from services import khoa_cua_nha as kc
        if not kc.is_enabled():
            return "skip", "khoá cửa tắt (mqtt.khoa_cua)"
        kq = kc.chay_mot_lan()
        if kq.get("gui"):
            return "act", f"gửi {kq['gui']} tin về khoá cửa"
        return "skip", kq.get("ly_do") or "không có gì mới"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_bai_hoc() -> tuple[str, str]:
    """Bản tin «em học được gì» — services.bai_hoc.

    Mặc định TẮT (`mqtt.bai_hoc.bao`), và bật thì cũng chỉ gửi mỗi 7 ngày, nên
    hiếm khi tranh suất `max_acts_per_tick`. Chưa học được gì thì im, không
    nhắn bản tin rỗng.
    """
    try:
        from services import bai_hoc
        kq = bai_hoc.chay_mot_lan()
        if kq.get("gui"):
            return "act", f"báo học tập tới {kq['gui']} người"
        return "skip", kq.get("ly_do") or "chưa có gì để kể"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_du_doan_nha() -> tuple[str, str]:
    """Học thói quen theo bối cảnh rồi gợi ý — services.du_doan_nha.

    CHỈ TRẢ VỀ danh sách gợi ý, không tự bật gì ở đây: bật thiết bị là tác
    dụng phụ, phải đi qua cổng riêng.

    Chạy nền vì `hoc()` quét lịch sử nhiều ngày và dựng bối cảnh cho từng ô 30
    phút — vài giây. Khuôn theo `_eval_tinh_huong`: ghi mốc TRƯỚC khi chạy nền
    để tick 5 phút sau không chạy đúp.
    """
    try:
        from services import du_doan_nha as dn
        if not dn.is_enabled():
            return "skip", "đang tắt (mqtt.du_doan.bat)"
        import time as _t
        moc = _t.strftime("%Y-%m-%d %H")
        if _state.get("du_doan_gio") == moc:
            return "skip", "giờ này đã xem rồi"
        _state["du_doan_gio"] = moc
        _save_state()
        threading.Thread(target=dn.chay_mot_lan, name="du-doan-nha",
                         daemon=True).start()
        return "act", "học thói quen theo bối cảnh (chạy nền)"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_hieu_thiet_bi_nha() -> tuple[str, str]:
    """Bot học hỏi tự hiểu thiết bị nhà — services.hieu_thiet_bi_nha.

    Mỗi NGÀY một lần: thiết bị nhà không đổi từng giờ, còn mỗi lượt là một lời
    gọi model. Chạy nền vì phải đo hồ sơ cả tháng rồi chờ model trả lời. Khuôn
    theo `_eval_du_doan_nha`: ghi mốc TRƯỚC khi chạy nền để tick sau không
    chạy đúp.
    """
    try:
        from services import hieu_thiet_bi_nha as ht
        if not ht.is_enabled():
            return "skip", "đang tắt (mqtt.hieu_thiet_bi.bat)"
        import time as _t
        moc = _t.strftime("%Y-%m-%d")
        # Chủ máy vừa dạy dữ kiện mới thì xem lại NGAY tick này, đừng bắt chờ tới
        # mai mới thấy bot hiểu ra sao ("tôi vừa đưa 2 dữ kiện xem bot học sao").
        if _state.get("hieu_thiet_bi_ngay") == moc and not ht.co_du_kien_moi():
            return "skip", "hôm nay đã xem rồi, chưa có dữ kiện mới"
        _state["hieu_thiet_bi_ngay"] = moc
        _save_state()
        threading.Thread(target=ht.chay_mot_lan, name="hieu-thiet-bi-nha",
                         daemon=True).start()
        return "act", "bot học hỏi tự hiểu thiết bị nhà (chạy nền)"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_thoi_quen_nha() -> tuple[str, str]:
    """Bot học hỏi chọn ngoại vi theo khu vực, rồi đọc thói quen bật/tắt —
    services.thoi_quen_nha.

    Mỗi ngày một lần, và CHỈ SAU khi lượt hiểu thiết bị hôm nay đã xong: tầng
    này đọc "thiết bị nào được học" từ kết luận của lượt đó. Dữ kiện mới của
    chủ máy thì chạy lại ngay, cùng lẽ `_eval_hieu_thiet_bi_nha`.
    """
    try:
        from services import hieu_thiet_bi_nha as ht, thoi_quen_nha as tq
        if not ht.is_enabled():
            return "skip", "đang tắt (mqtt.hieu_thiet_bi.bat)"
        import time as _t
        moc = _t.strftime("%Y-%m-%d")
        if _state.get("hieu_thiet_bi_ngay") != moc or ht._dang_giai.locked():
            return "skip", "chờ lượt hiểu thiết bị hôm nay xong"
        if _state.get("thoi_quen_ngay") == moc and not ht.co_du_kien_moi("ngoai_vi"):
            return "skip", "hôm nay đã chọn rồi, chưa có dữ kiện mới"
        _state["thoi_quen_ngay"] = moc
        _save_state()
        threading.Thread(target=tq.chay_mot_lan, name="thoi-quen-nha",
                         daemon=True).start()
        return "act", "bot học hỏi chọn ngoại vi theo khu vực (chạy nền)"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_luat_duyet() -> tuple[str, str]:
    """ĐỊNH KỲ TỰ ĐÁNH GIÁ luật đã duyệt: luật nào khớp nguồn mà bị điều kiện chặn mãi, không lần nào làm được (CHẾT)
    thì tự chấm SAI (gỡ khỏi sổ chạy — nó vốn không làm gì) rồi cho bot GIẢI LẠI với đề đã có độ tin cảm biến + cặp
    trùng. Chủ máy 04/10/2026: "bot giải lúc đầu, sau chạy tự động; bót định kỳ học lại, đánh giá để tối ưu".

    Mỗi ngày một lần, mỗi tick chỉ lo MỘT thiết bị (mỗi lần giải là một lời gọi model). Luật giải lại là ĐỀ XUẤT,
    chờ chấm — không tự áp."""
    try:
        from services import luat_duyet, nhat_ky_kich_hoat as nk
        import time as _t
        moc = _t.strftime("%Y-%m-%d")
        if _state.get("luat_duyet_ngay") == moc:
            return "skip", "hôm nay đã xét rồi"
        chet = nk.luat_chet()
        dao = nk.luat_dao_dong()
        # Gom luật KÉM còn đang ÁP cho MỘT thiết bị: chết (chặn mãi) + dao động (bật rồi tắt ngay = bật quá sớm).
        viec: tuple[str, dict[int, str]] | None = None
        for tb in sorted(set(chet) | set(dao)):
            dang = {l["so"] for l in luat_duyet.ap(tb)}
            ly: dict[int, str] = {}
            for s in chet.get(tb) or []:
                if s in dang:
                    ly[s] = "khớp nguồn nhưng điều kiện chặn mãi, không lần nào chạy — giải lại tránh cảm biến nhiễu / mâu thuẫn"
            for s, n in (dao.get(tb) or {}).items():
                if s in dang:
                    ly[s] = (f"bật rồi phải tắt ngay {n} lần (≤5 phút, không ai ở lại) — bật QUÁ SỚM; đổi sang người "
                             "Ở LẠI đủ lâu, hoặc chéo camera trước khi bật")
            if ly:
                viec = (tb, ly)
                break
        if viec is None:
            _state["luat_duyet_ngay"] = moc
            _save_state()
            return "skip", "không có luật chết / dao động đang áp"
        tb, ly = viec
        _state["luat_duyet_ngay"] = moc
        _save_state()

        def _chay() -> None:
            for s, ghi in ly.items():
                luat_duyet.cham(tb, s, False, cham_boi="claude", ghi_chu=f"tự đánh giá: {ghi}")
            luat_duyet.giai_va_bao(tb)
        threading.Thread(target=_chay, name="luat-duyet-tu-danh-gia", daemon=True).start()
        return "act", f"luật kém của {tb} (#{', #'.join(map(str, sorted(ly)))}) → chấm sai + giải lại (chạy nền)"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_loi_khuyen_nha() -> tuple[str, str]:
    """CHU KỲ HỌC giãn dần (2 lần × 5 ngày, 4 lần × 7 ngày, rồi mỗi tháng): rút lời khuyên thời gian ở lại / vắng từ
    nhật ký kích hoạt, xếp vào hàng hỏi chủ nhà (`services.loi_khuyen_nha`). Chưa tới kỳ thì chỉ đọc một file.
    Mỗi tick cũng nhắc lại câu hỏi đang chờ quá hạn (tin có thể trôi)."""
    try:
        from services import loi_khuyen_nha as lk, luat_duyet
        luat_duyet.hoi_tiep()
        ra = lk.chay()
        if not ra:
            ck = lk.chu_ky()
            return "skip", f"chu kỳ {ck['lan']} — kỳ tới {time.strftime('%d/%m', time.localtime(ck['toi']))}"
        return "act", f"{len(ra)} lời khuyên thời gian ở lại / vắng → hỏi chủ nhà"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_tu_bat_theo_nep() -> tuple[str, str]:
    """Thiết bị chủ nhà bật «tự bật theo nếp» (services.tu_bat_theo_nep): tới giờ nếp thì bật, hết thời lượng thì tắt.
    Mỗi tick — rẻ (một thiết bị đọc lịch sử 60 ngày) và giờ tắt phải được xét lại sau mỗi lần khởi động lại."""
    try:
        from services import tu_bat_theo_nep as tb
        if not any(x.get("bat") for x in tb.cai_dat().values()):
            return "skip", "chưa thiết bị nào bật chế độ"
        ra = tb.chay_mot_lan()
        lam = [r for r in ra if "đã bật" in r or "tới giờ tắt" in r]
        return ("act", "; ".join(lam)) if lam else ("skip", "; ".join(ra)[:200])
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_cap_quyen() -> tuple[str, str]:
    """Quyền cấp theo thời hạn (services.cap_quyen): quá hạn thì gỡ — chỉ khi bản ghi lọc còn đúng như bot ghi."""
    try:
        from services import cap_quyen
        if not any(v.get("het_han") for v in cap_quyen.ds().values()):
            return "skip", "không có quyền nào có hạn"
        n = cap_quyen.chay_mot_lan()
        return ("act", f"gỡ {n} quyền hết hạn") if n else ("skip", "chưa có quyền nào hết hạn")
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_loa_cho() -> tuple[str, str]:
    """Tin loa giữ lúc nhà vắng (services.voice.announce): có người thì phát. Chạy nền — TTS + Cast mất vài giây."""
    try:
        from services.voice import announce
        if not announce.dang_cho():
            return "skip", "không có tin chờ"
        threading.Thread(target=announce.phat_cho, name="loa-cho", daemon=True).start()
        return "act", "xét phát tin loa đang chờ (chạy nền)"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_lech_nep() -> tuple[str, str]:
    """Nhắc lệch nếp — services.lech_nep. Mặc định TẮT (mqtt.lech_nep.bat). Chạy nền: lần đầu
    mỗi ngày phải học lại nếp từ 21 ngày lịch sử."""
    try:
        from services import lech_nep
        if not lech_nep.is_enabled():
            return "skip", "nhắc lệch nếp tắt (mqtt.lech_nep)"
        threading.Thread(target=lech_nep.chay_mot_lan, name="lech-nep", daemon=True).start()
        return "act", "soát lệch nếp (chạy nền)"
    except Exception as exc:
        return "skip", f"error: {exc}"


def _eval_tam_hon() -> tuple[str, str]:
    """Tâm hồn của bot — services.agent.tam_hon. Mặc định TẮT: chủ máy tích mới chạy."""
    try:
        from services.agent import tam_hon
        nen, ly_do = tam_hon.nen_chay()
        if not nen:
            return "skip", ly_do
        threading.Thread(target=tam_hon.chay_mot_lan, name="tam-hon", daemon=True).start()
        return "act", "bot cảm (chạy nền)"
    except Exception as exc:
        return "skip", f"error: {exc}"


_HANDLERS: dict[str, Callable[[], tuple[str, str]]] = {
    "hieu_thiet_bi_nha": _eval_hieu_thiet_bi_nha,
    "thoi_quen_nha": _eval_thoi_quen_nha,
    "wiki_daily_digest": _eval_wiki_digest,
    "open_goals_nudge": _eval_open_goals,
    "chatlog_nhac_scan": _eval_chatlog_nhac,
    "user_profile_distill": _eval_distill,
    "canh_bao_nha": _eval_canh_bao_nha,
    "tinh_huong_nha": _eval_tinh_huong,
    "khoa_cua_nha": _eval_khoa_cua,
    "bai_hoc": _eval_bai_hoc,
    "du_doan_nha": _eval_du_doan_nha,
    "tam_hon": _eval_tam_hon,
    "lech_nep": _eval_lech_nep,
    "loa_cho": _eval_loa_cho,
    "luat_duyet": _eval_luat_duyet,
    "tu_bat_theo_nep": _eval_tu_bat_theo_nep,
    "loi_khuyen_nha": _eval_loi_khuyen_nha,
    "cap_quyen": _eval_cap_quyen,
}


def evaluate_task(task: dict[str, Any]) -> dict[str, Any]:
    tid = str(task.get("id") or "")
    if tid in _HANDLERS:
        decision, detail = _HANDLERS[tid]()
    elif task.get("system"):
        decision, detail = "skip", "no handler"
    else:
        decision, detail = _eval_user_task(task)
    return {
        "id": tid,
        "decision": decision,
        "detail": detail,
        "intent": task.get("intent"),
        "text": task.get("text"),
    }


def tick_once() -> list[dict[str, Any]]:
    """Run one heartbeat evaluation. Returns list of outcomes."""
    if not is_enabled():
        return []
    _load_state()
    tasks = _parse_tasks()
    results: list[dict[str, Any]] = []
    acts = 0
    for task in tasks:
        try:
            out = evaluate_task(task)
        except Exception as exc:
            out = {
                "id": task.get("id"),
                "decision": "skip",
                "detail": f"error: {exc}",
            }
        results.append(out)
        dec = out.get("decision") or "skip"
        _log_activity(dec, str(out.get("id")), str(out.get("detail") or ""))
        if dec in ("act", "escalate"):
            acts += 1
            # mark last run
            _state.setdefault("tasks", {})[str(out.get("id"))] = time.time()
            if acts >= max_acts_per_tick():
                # still mark remaining as skipped this tick
                break
    _state["last_tick"] = time.time()
    _save_state()
    logger.info(
        "heartbeat: tick done acts=%s results=%s",
        acts,
        [(r.get("id"), r.get("decision")) for r in results],
    )
    return results


def _loop() -> None:
    # slight delay so app finishes startup
    _stop.wait(15)
    while not _stop.is_set():
        try:
            tick_once()
        except Exception as exc:
            logger.warning("heartbeat: tick error: %s", exc)
        _stop.wait(tick_seconds())


def start() -> None:
    global _started
    if _started or not is_enabled():
        return
    _started = True
    _stop.clear()
    _ensure_heartbeat_md()
    _load_state()
    t = threading.Thread(target=_loop, name="agent-heartbeat", daemon=True)
    t.start()
    logger.info("heartbeat: started (tick=%ss)", tick_seconds())


def stop() -> None:
    global _started
    _stop.set()
    _started = False


def _reset_for_tests(
    agent_dir: Path | None = None,
    *,
    clear_state: bool = True,
) -> None:
    global _AGENT_DIR, _HEARTBEAT_MD, _STATE_FILE, _ACTIVITY_FILE, _state, _started
    stop()
    with _lock:
        if agent_dir is not None:
            _AGENT_DIR = Path(agent_dir)
            _HEARTBEAT_MD = _AGENT_DIR / "HEARTBEAT.md"
            _STATE_FILE = _AGENT_DIR / "heartbeat_state.json"
            _ACTIVITY_FILE = _AGENT_DIR / "heartbeat_activity.jsonl"
        if clear_state:
            _state = {}
            try:
                if _STATE_FILE.exists():
                    _STATE_FILE.unlink()
            except OSError:
                pass
    _started = False
