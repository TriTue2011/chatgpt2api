"""Chưng cất trí nhớ — job nền viết hồ sơ người dùng (L3) + chiết fact (L1).

Bài học từ TencentDB-Agent-Memory (L0 Conversation → L1 Atom → L2 Scenario →
L3 Persona): dự án đã có L0 (session/chatlog), L1 (MEMORY.md qua tool
``remember``), L2 (compaction summary) — nhưng L3 (``users/<uid>.md``) chỉ có
đường ĐỌC, không ai ghi; và L1 chỉ nhận điều người dùng DẶN RÕ trong lượt
chat. Job này (heartbeat gọi mỗi ngày một lần) bù hai chỗ hổng đó:

1. Với mỗi user có đủ turn mới: đưa tóm tắt phiên + đuôi hội thoại + hồ sơ
   hiện có cho model → HỒ SƠ cập nhật → ``state.save_user_profile`` (chỉ thay
   phần dưới marker; ghi chú soạn tay phía trên giữ nguyên).
2. Cùng lượt gọi đó, chiết các FACT đáng nhớ lộ ra tự nhiên trong hội thoại
   (không ai "dặn") → ``state.nho_hoac_cap_nhat`` (tự chặn trùng / thay bản cũ).

Hồ sơ ghi xong tự chảy vào mọi lượt chat qua orchestrator + super_context
(hai chỗ đó đã đọc ``load_user_profile`` sẵn — không phải đấu nối gì thêm).
Mọi lỗi nuốt (fail-open): chưng cất hỏng thì chat vẫn chạy y nguyên.

HỒ SƠ LÀ CỦA TỪNG NGƯỜI, KHÔNG TRỘN: khoá phiên 1-1 chính là người đó; nhóm
mặc định tách mỗi người một phiên (':u<uid>', chốt 06/08) nên mỗi người một
hồ sơ riêng. Phiên nhóm DÙNG CHUNG (tắt group_user_isolation) bị run_once bỏ
qua — không tồn tại "hồ sơ của cả nhóm". Fact chiết ra thì vẫn theo luật chia
sẻ sẵn có của bộ nhớ (khoa_du_lieu — nhóm chưa lọc user thì kho chung nhóm),
đúng ranh giới chủ máy đã chốt: chỉ hội thoại live tách người, bộ nhớ giữ nguyên.

Config (``agent_distill``, đều optional)::

    enabled: bool (default True)
    hour: int 0-23 giờ VN (default 3) — chạy sau giờ này, mỗi ngày một lần
    min_new_turns: int (default 10) — user ít turn mới hơn thì bỏ qua
    max_users_per_run: int (default 8) — trần chi phí LLM mỗi ngày
    profile_max_chars: int (default 1200)
    facts_max: int (default 5)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.agent import runtime
from services.agent import session as sess
from services.agent import state
from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_STATE_FILE = Path(DATA_DIR) / "agent" / "distill_state.json"
_lock = threading.RLock()
# Ngày đã chạy, giữ THÊM trong RAM: nếu ghi _STATE_FILE hỏng (đĩa đầy/read-only)
# mà chỉ dựa vào file thì due_now() lại True ở tick sau → job một-ngày-một-lần
# biến thành gọi model mỗi 5 phút suốt cả tối.
_ran_day_mem = ""

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    _TZ = timezone(timedelta(hours=7))

# Ứng viên = user có turn trong cửa sổ này (không quét cả lịch sử đời đời).
_CUA_SO_UNG_VIEN = 14 * 86400

_PROMPT_KHUON = (
    "Em là bộ phận chưng cất trí nhớ của một trợ lý gia đình tiếng Việt. "
    "Từ chất liệu bên dưới, làm HAI việc và trả lời ĐÚNG khuôn sau, không "
    "thêm lời dẫn:\n"
    "## HỒ SƠ\n"
    "- (gạch đầu dòng: cách xưng hô/cách gọi, sở thích, thói quen, mối quan "
    "tâm, việc đang theo đuổi — chỉ điều ỔN ĐỊNH lâu dài về NGƯỜI này, không "
    "chép lại diễn biến một lần; gộp hồ sơ hiện có: giữ điều còn đúng, sửa "
    "điều đã đổi; mốc thời gian ghi TUYỆT ĐỐI dạng 11-08-2026, không ghi "
    "'hôm qua/tuần trước'; tối đa 12 dòng)\n"
    "## FACT MỚI\n"
    "- (mỗi dòng MỘT sự việc cụ thể đáng nhớ lâu dài lộ ra trong hội thoại "
    "mà chưa có trong hồ sơ/trí nhớ — lịch hẹn đã chốt, quyết định, hoàn "
    "cảnh mới; nếu không có gì đáng lưu, ghi đúng một dòng: KHÔNG CÓ)"
)


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_distill")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def _hour() -> int:
    # KHÔNG dùng `or 3`: 0 (chạy ngay sau nửa đêm) là giá trị hợp lệ mà `or`
    # sẽ nuốt mất thành mặc định.
    raw = _cfg().get("hour")
    if raw is None:
        return 3
    try:
        return max(0, min(23, int(raw)))
    except (TypeError, ValueError):
        return 3


def _min_new_turns() -> int:
    try:
        return max(2, int(_cfg().get("min_new_turns") or 10))
    except (TypeError, ValueError):
        return 10


def _max_users_per_run() -> int:
    try:
        return max(1, min(50, int(_cfg().get("max_users_per_run") or 8)))
    except (TypeError, ValueError):
        return 8


def _profile_max_chars() -> int:
    try:
        return max(200, int(_cfg().get("profile_max_chars") or 1200))
    except (TypeError, ValueError):
        return 1200


def _facts_max() -> int:
    # 0 = tắt hẳn phần chiết fact (chỉ viết hồ sơ) — hợp lệ, đừng `or` mất.
    raw = _cfg().get("facts_max")
    if raw is None:
        return 5
    try:
        return max(0, min(12, int(raw)))
    except (TypeError, ValueError):
        return 5


def _now_vn() -> datetime:
    return datetime.now(_TZ)


def _main_model() -> str:
    # Cùng cách chọn model với compaction (một chỗ sửa, hai đường theo).
    from services.agent.compaction import _main_model as _chon
    return _chon()


# ── Sổ trạng thái (ngày đã chạy + mốc turn từng user) ────────────────────────

def _load_state() -> dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.warning("distill: đọc state lỗi: %s", exc)
    return {}


def _save_state(data: dict[str, Any]) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("distill: ghi state lỗi: %s", exc)


def due_now() -> bool:
    """True khi đã qua giờ cấu hình (VN) và hôm nay chưa chạy."""
    if not is_enabled():
        return False
    now = _now_vn()
    if now.hour < _hour():
        return False
    today = now.strftime("%Y-%m-%d")
    if _ran_day_mem == today:
        return False
    with _lock:
        return _load_state().get("last_day") != today


# ── Chưng cất một user ───────────────────────────────────────────────────────

def _chat_lieu(user_id: str) -> str:
    """Gom chất liệu: tóm tắt phiên (L2) + đuôi hội thoại (L0) + hồ sơ (L3)."""
    parts: list[str] = []
    prof = (state.load_user_profile(user_id) or "").strip()
    if prof:
        parts.append("Hồ sơ hiện tại:\n" + prof[:2000])
    summary = (sess.load_summary(user_id) or "").strip()
    if summary:
        parts.append("Tóm tắt các phiên trước:\n" + summary[:2000])
    try:
        from services.agent.compaction import _format_turns
        body = _format_turns(sess.load_history(user_id))
    except Exception:
        body = ""
    if body.strip():
        parts.append("Hội thoại gần đây:\n" + body[:6000])
    return "\n\n".join(parts)


def _tach_ket_qua(text: str) -> tuple[str, list[str]]:
    """Tách (hồ sơ, [fact]) từ trả lời theo khuôn; khuôn vỡ → ("", [])."""
    text = (text or "").strip()
    if "## HỒ SƠ" not in text:
        return "", []
    sau_ho_so = text.split("## HỒ SƠ", 1)[1]
    if "## FACT MỚI" in sau_ho_so:
        ho_so, phan_fact = sau_ho_so.split("## FACT MỚI", 1)
    else:
        ho_so, phan_fact = sau_ho_so, ""
    facts: list[str] = []
    for ln in phan_fact.splitlines():
        s = ln.strip()
        if not s.startswith("-"):
            continue
        s = s.lstrip("-").strip()
        # Sentinel so CẢ DÒNG, không substring: "không có" là phủ định cực
        # phổ biến ("Bé không có dị ứng penicillin") — match substring sẽ
        # nuốt đúng nhóm fact phủ định đáng lưu nhất.
        if not s or s.upper().rstrip(".") == "KHÔNG CÓ":
            continue
        facts.append(s[:250])
    return ho_so.strip(), facts


def _chung_cat_user(user_id: str) -> tuple[bool, int] | None:
    """Chưng cất một user. Trả (đã ghi hồ sơ?, số fact đã lưu).

    Trả ``None`` khi model LỖI (mạng/provider sập) — caller phải GIỮ NGUYÊN
    mốc watermark để chất liệu được xét lại lần sau, khác với "đã xử lý mà
    không có gì đáng ghi" (trả (False, 0), mốc được đẩy lên).
    """
    chat_lieu = _chat_lieu(user_id)
    if not chat_lieu.strip():
        return False, 0
    resp = runtime.call_model(
        _main_model(),
        [{"role": "user", "content": _PROMPT_KHUON + "\n\n" + chat_lieu}],
        timeout=90,
        max_tokens=700,
        no_smart_home=True,
    )
    if resp.get("error"):
        logger.info("distill: user=%s model lỗi: %s", user_id, resp["error"])
        return None
    ho_so, facts = _tach_ket_qua(runtime.content_of(resp))
    ghi_ho_so = False
    if ho_so:
        ghi_ho_so = state.save_user_profile(
            user_id, ho_so, max_chars=_profile_max_chars())
    so_fact = 0
    if facts:
        # Fact chưng từ chat riêng PHẢI vào đúng kho phạm vi của user đó —
        # không fallback về kho chung ("" = cả nhà đọc được): khoa_du_lieu là
        # module nội bộ, nó hỏng thì để exception nổi lên cho vòng ngoài giữ
        # watermark, còn hơn lặng lẽ rò fact riêng tư sang phạm vi khác.
        from services.agent.scope import khoa_du_lieu
        pv = khoa_du_lieu(user_id)
        for fact in facts[:_facts_max()]:
            try:
                if state.nho_hoac_cap_nhat(fact, who="chưng cất",
                                           pham_vi=pv) != "trung":
                    so_fact += 1
            except Exception as exc:
                logger.warning("distill: lưu fact lỗi: %s", exc)
    return ghi_ho_so, so_fact


def run_once(force: bool = False) -> dict[str, Any]:
    """Chạy một lượt chưng cất cho các user đủ chất liệu mới.

    ``force=True`` bỏ qua ngưỡng ``min_new_turns`` (dùng khi thử tay);
    lịch mỗi-ngày-một-lần do heartbeat + ``due_now()`` giữ.

    Khoá chỉ ôm hai đoạn đọc/ghi state file, KHÔNG ôm vòng gọi model (tối đa
    max_users_per_run × 90s) — due_now() và caller khác không phải xếp hàng
    sau I/O mạng. Ngày được NHẬN ngay từ đầu (file + RAM) để tick heartbeat
    sau không chạy đúp khi lô này còn dở; đổi lại ngày provider sập cả lô thì
    hôm đó bỏ, nhưng watermark từng user vẫn giữ nên hôm sau bù đủ chất liệu.
    """
    global _ran_day_mem
    if not is_enabled():
        return {"ok": False, "detail": "distill tắt (agent_distill)"}
    now = time.time()
    today = _now_vn().strftime("%Y-%m-%d")
    with _lock:
        so = _load_state()
        users_state: dict[str, Any] = (
            so.get("users") if isinstance(so.get("users"), dict) else {})
        so["users"] = users_state
        so["last_day"] = today
        _ran_day_mem = today
        _save_state(so)

    xet = 0
    ho_so = 0
    fact = 0
    da_xong: dict[str, float] = {}
    for user_id, _n in sess.users_active_since(now - _CUA_SO_UNG_VIEN):
        if xet >= _max_users_per_run():
            break
        # Hồ sơ là chuyện của MỘT người. Phiên nhóm dùng chung (nhóm mà khoá
        # không mang ':u<uid>' — xảy ra khi tắt group_user_isolation) không có
        # "một người" nào để chưng: chưng bừa là trộn nhiều người vào một file
        # rồi tiêm nhầm vào lượt chat của tất cả thành viên. Bỏ qua.
        try:
            from services.agent.scope import tach_khoa_phien
            sc = tach_khoa_phien(user_id)
            if sc.la_nhom and not sc.actor:
                continue
        except Exception:
            continue
        try:
            moc = float((users_state.get(user_id) or {}).get("ts") or 0.0)
        except (TypeError, ValueError):
            moc = 0.0
        if not force and sess.count_turns_since(user_id, moc) < _min_new_turns():
            continue
        xet += 1
        try:
            ket = _chung_cat_user(user_id)
        except Exception as exc:
            logger.warning("distill: user=%s lỗi: %s", user_id, exc)
            continue  # watermark giữ nguyên — xét lại lần sau
        if ket is None:
            continue  # model lỗi — watermark giữ nguyên, chất liệu không mất
        da_ghi, so_fact = ket
        if da_ghi:
            ho_so += 1
        fact += so_fact
        da_xong[user_id] = now

    if da_xong:
        with _lock:
            so = _load_state()
            users_state = (
                so.get("users") if isinstance(so.get("users"), dict) else {})
            for uid, ts in da_xong.items():
                users_state[uid] = {"ts": ts}
            so["users"] = users_state
            so["last_day"] = today
            _save_state(so)
    logger.info("distill: xét %d user → %d hồ sơ, %d fact", xet, ho_so, fact)
    return {"ok": True, "users": xet, "profiles": ho_so, "facts": fact}


def _reset_for_tests(state_file: Path | None = None) -> None:
    global _STATE_FILE, _ran_day_mem
    with _lock:
        _ran_day_mem = ""
        if state_file is not None:
            _STATE_FILE = state_file
