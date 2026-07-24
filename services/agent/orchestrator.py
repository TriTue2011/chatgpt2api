"""Agent orchestrator — the supervised, capability-aware conversation loop.

Flow per user message:
  1. Resolve a pending approval first (the user is confirming/denying a change
     the agent proposed last turn).
  2. Build the tiered system prompt (persona + memory + user profile + granted
     permissions) — this is what makes the bot "know who it is, what it can do,
     what it's allowed, and what it remembers".
  3. Run the agentic loop: call the main model with the native capability tools.
     - READ capability  → execute, feed the result back, keep going.
     - CHANGE capability → if pre-approved ("always") execute; otherwise PROPOSE
       it and stop, waiting for the user to approve.
     - plain text       → that's the reply.
  4. Errors are reported to the user, never silently retried in a loop.

Returns ``{"text": str, "image_url": Optional[str]}``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from services.config import config
from services.agent import state
from services.agent import session as sess
from services.agent import compaction as compact
from services.agent import ask_choices
from services.agent import skills as agent_skills
from services.agent import workflows as agent_workflows
from services.agent import capabilities as caps
from services.agent import tool_compress
from services.agent import approval_gate
from services.agent import super_context
from services.agent import goals as agent_goals
from services.agent import model_hints
from services.agent import run_journal
from services.agent.runtime import call_model, content_of

logger = logging.getLogger(__name__)

_MAX_STEPS = 4
# In-process cache; durable source of truth is session SQLite when enabled.
# Kept so a failed DB still allows the current process to converse.
_history: dict[str, list[dict[str, Any]]] = {}

_APPROVE_ALWAYS = ("luôn luôn", "luôn khỏi hỏi", "khỏi hỏi", "lúc nào cũng", "từ giờ khỏi hỏi", "always")
_APPROVE_ONCE = ("ok", "oke", "được", "duoc", "đồng ý", "dong y", "làm đi", "lam di", "ừ", "uh", "yes", "có", "co", "đi")
_DENY = ("thôi", "thoi", "không", "khong", "hủy", "huy", "đừng", "dung", "no", "khỏi")


def _main_model(hint: str = "chat") -> str:
    """Resolve agent model via hint routing (chat/burst/reason/code)."""
    try:
        return model_hints.resolve(hint or "chat")
    except Exception:
        return str(config.get().get("telegram_ai_model") or "").strip() or "cx/auto"


_PROVIDER_FRIENDLY = {
    "cx": "Codex", "claude": "Claude (viết code)", "flow": "Flow (vẽ ảnh miễn phí)",
    "gma": "Gemini", "gemini_free": "Gemini", "gemini_web": "Gemini web",
    "gemini_web_api": "Gemini web", "chatgpt_web": "ChatGPT web",
    "cgf": "ChatGPT free", "chatgpt": "ChatGPT",
}


def _provider_summary() -> str:
    """List the AI backends actually available, so the persona only claims tools
    that really exist. Codex (the main brain) is configured outside `providers`,
    so seed it from the main model."""
    names = []
    try:
        main = _main_model().split("/")[0]
        names.append(_PROVIDER_FRIENDLY.get(main, main) + " (agent chính)")
    except Exception:
        pass
    try:
        providers = config.get().get("providers") or {}
        if isinstance(providers, dict):
            for key in providers.keys():
                names.append(_PROVIDER_FRIENDLY.get(str(key), str(key)))
    except Exception:
        pass
    return ", ".join(dict.fromkeys(names)) if names else ""


_WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def _now_line() -> str:
    """Current VIETNAM datetime in Vietnamese, so the model answers date/time
    questions ("mai thứ mấy") naturally and correctly by itself. The container
    runs UTC, so pin Asia/Ho_Chi_Minh explicitly."""
    import datetime
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    except Exception:
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    return (f"Bây giờ là {now.strftime('%H:%M')}, {_WEEKDAYS_VI[now.weekday()]}, "
            f"ngày {now.day} tháng {now.month} năm {now.year} (giờ Việt Nam).")


def _build_system_prompt(user_id: str, allow: set[str] | None = None) -> str:
    name = config.agent_name
    soul = state.load_soul().replace("{agent_name}", name)
    parts = [soul, _now_line()]
    # Capability list — auto-generated from the registry (single source of truth).
    # Lọc theo `allow` để persona KHÔNG khoe chức năng thread này bị cấm.
    parts.append("## Em làm được gì (năng lực THẬT lúc này)\n" + caps.persona_list(allow))
    if allow is not None:
        parts.append(
            "## Giới hạn khung chat này (QUAN TRỌNG)\n"
            "Khung chat này CHỈ được cấp các chức năng liệt kê ở trên. Mọi chức "
            "năng khác (vd: xem/điều khiển nhà thông minh, xem máy chủ, viết code, "
            "xử lý tài liệu…) đã bị TẮT theo cấu hình. Nếu người dùng yêu cầu việc "
            "thuộc chức năng bị tắt: KHÔNG giải thích, KHÔNG xin lỗi, KHÔNG bịa/"
            "đoán dữ liệu (trạng thái đèn/thiết bị, nhiệt độ, máy chủ…) — chỉ trả "
            "lời DUY NHẤT chuỗi [BLOCKED] (đúng nguyên văn), hệ thống sẽ tự bỏ "
            "qua tin nhắn đó. Trò chuyện thông thường vẫn trả lời bình thường.")
    prov = _provider_summary()
    if prov:
        parts.append("## Công cụ / nhà cung cấp AI đang có\n" + prov)
    env = state.load_environment()
    if env.strip():
        parts.append("## Môi trường em đang sống (bản đồ hệ thống)\n" + env.strip())
    mem = state.load_memory()
    if mem.strip():
        parts.append("## Trí nhớ (chuyện đã ghi nhớ)\n" + mem.strip())
    # Compacted earlier turns (durable across restarts)
    try:
        summary = sess.load_summary(user_id)
        if summary.strip():
            parts.append(
                "## Tóm tắt hội thoại trước với người này\n" + summary.strip()
            )
    except Exception:
        pass
    prof = state.load_user_profile(user_id)
    if prof.strip():
        parts.append("## Hồ sơ người đang nói chuyện\n" + prof.strip())
    # Skill / playbook index (description only — body loaded via use_skill)
    try:
        sk_block = agent_skills.router_block()
        if sk_block.strip():
            parts.append(sk_block)
    except Exception:
        pass
    try:
        wf_block = agent_workflows.router_block()
        if wf_block.strip():
            parts.append(wf_block)
    except Exception:
        pass
    try:
        goals_block = agent_goals.prompt_block(user_id)
        if goals_block.strip():
            parts.append(goals_block)
    except Exception:
        pass
    parts.append(
        "## Bảo mật secret / placeholder (BẮT BUỘC)\n"
        "Trong hội thoại và tool/RAG có thể xuất hiện placeholder dạng "
        "⟦secret:…⟧ / ⟦password:…⟧ / ⟦tc:…⟧. "
        "Em phải CHÉP NGUYÊN VĂN placeholder khi cần dùng lại — "
        "TUYỆT ĐỐI KHÔNG đoán, khôi phục, hay viết lại mật khẩu/token thật. "
        "Không đưa secret thô vào câu trả lời cho người dùng.")
    parts.append(
        "## Cách dùng công cụ\n"
        "Khi cần làm việc cụ thể, GỌI đúng tool. Với việc THAY ĐỔI chưa được "
        "phép, cứ gọi tool bình thường — hệ thống sẽ tự hỏi xin phép người dùng. "
        "Nếu chỉ trò chuyện/giải thích thì trả lời thẳng, không gọi tool.")
    parts.append(
        "## HỎI-ĐỦ-RỒI-MỚI-LÀM (nguyên tắc BẮT BUỘC cho MỌI yêu cầu hành động)\n"
        "Trước khi gọi tool THỰC THI (gửi tin, nhắc/hẹn giờ, phát nhạc/loa, tạo "
        "ảnh/video/nhạc, điều khiển nhà, xoá/sửa, lưu bộ nhớ, tra RAG/tài liệu…), "
        "TỰ HỎI: 'việc này cần những thông tin gì để làm ĐÚNG?'. Nếu một thông tin "
        "BẮT BUỘC bị THIẾU hoặc MẬP MỜ (nhiều khả năng, trùng tên, đoán sai sẽ làm "
        "nhầm) → HỎI LẠI để lấy ĐỦ và ĐÚNG, rồi mới làm. TUYỆT ĐỐI KHÔNG đoán dữ "
        "liệu đích. Tuỳ tình huống, các mảnh hay cần làm rõ: gửi/báo QUA KÊNH nào · "
        "CHO AI (người/nhóm nào; nếu trùng tên hoặc có ở nhiều kênh phải hỏi rõ) · "
        "LÚC NÀO / bao lâu một lần · Ở ĐÂU / THIẾT BỊ nào (loa, phòng) · SỐ LƯỢNG "
        "bao nhiêu · NGUỒN hay ĐÍCH dữ liệu nào (bộ nhớ, wiki/RAG, tệp, ảnh nào) · "
        "nội dung / tham số quan trọng.\n"
        "PHÂN BIỆT rõ: những gì ĐÃ CÓ mặc định (công cụ, model, chất lượng, tỉ lệ "
        "ảnh mặc định…) thì KHÔNG hỏi — cứ dùng mặc định và làm ngay. CHỈ hỏi khi "
        "thiếu DỮ LIỆU ĐÍCH mà đoán sai sẽ gửi nhầm người / sai giờ / nhầm thiết bị "
        "/ nhầm nguồn. Hỏi NGẮN GỌN, gộp mọi mục còn thiếu vào MỘT câu; nếu là chọn "
        "lựa hữu hạn thì dùng khối <<<ASK>>> bên dưới.")
    parts.append(
        "## Hỏi lại có lựa chọn (khi cần user chọn)\n"
        "Khi phải hỏi chọn (công cụ vẽ, phương án…), cuối câu trả lời thêm khối:\n"
        "<<<ASK>>>\n"
        "Nhãn hiện cho user | giá trị gửi lại khi chọn\n"
        "Flow miễn phí | flow\n"
        "ChatGPT\n"
        "<<<END>>>\n"
        "Hệ thống tự vẽ nút (Telegram) hoặc danh sách số (Zalo). "
        "Chỉ dùng khi THẬT SỰ cần chọn; đừng lạm dụng mỗi câu.")
    parts.append(
        "## Bảng chỉ đường (định tuyến việc — LÀM ĐÚNG NHÁNH, KHÔNG HỎI LẠI)\n"
        "- Vẽ/tạo ảnh → generate_image. Tạo nhạc/bài hát → generate_music. "
        "Tạo video → generate_video. Viết/sửa code → write_code. "
        "Tra cứu tin tức/giá cả → web_search. Khi tổng hợp TIN TỨC / BẢN TIN, BẮT BUỘC chia theo ĐẦY ĐỦ các đầu mục (🇻🇳 Thời sự Việt Nam, 🌎 Thế giới, 💼 Kinh doanh & Kinh tế, 📱 Công nghệ & Khoa học, ⚽ Thể thao, 🎨 Giải trí & Văn hóa, 🏥 Sức khỏe & Đời sống, ⚖️ Pháp luật & Xã hội), và MỖI ĐẦU MỤC lấy đúng 3 tiêu đề tin mới nhất kèm tóm tắt ngắn gọn.\n"
        "- Nhắc hẹn / việc định kỳ ('nhắc em sau 30 phút', 'mỗi sáng 7h báo "
        "thời tiết') → schedule (mode=notify|task). Tìm chuyện cũ → search_history.\n"
        "- Quy trình / playbook khớp skill → use_skill(slug=…) rồi làm theo.\n"
        "- Chuỗi nhiều bước (thu thập→xử lý→kiểm chứng) → run_workflow(slug, input).\n"
        "- Lưu ghi chú dài vào wiki → ingest; tìm/đọc wiki → wiki_search / wiki_read; "
        "tóm tắt ngày → wiki_digest.\n"
        "- Mục tiêu dài hơi trong chat ('nhớ làm…', 'đang làm…', 'xong…') → goals.\n"
        "- Tool output bị nén (có marker ⟦tc:…⟧) mà cần chi tiết → expand_tool_result.\n"
        "- Admin: 'ai vừa nhắn' / danh bạ / đặt tên → contacts; gửi tin cho alias "
        "(chọn bot) → send_to_contact (duyệt).\n"
        "- Hỏi về media ĐÃ TẠO ('gửi ảnh/video/nhạc mới nhất', 'ảnh vừa tạo', "
        "'trong thư viện có gì') → BẮT BUỘC gọi tool library_media (kind=image/video/music). "
        "LƯU Ý CỰC KỲ QUAN TRỌNG: Khi user nhắc đến 'thư viện', 'ảnh mới nhất', họ ĐANG NÓI TỚI thư viện ảnh do AI tạo ra trên máy chủ, KHÔNG PHẢI thư viện iCloud hay Google Photos trên điện thoại của họ! TUYỆT ĐỐI KHÔNG được trả lời là 'em không truy cập được thư viện ảnh của anh' — hãy gọi ngay tool library_media để lấy ảnh ra!\n"
        "- Mỗi việc đã có công cụ + model mặc định cấu hình sẵn — cứ gọi tool "
        "ngay, KHÔNG hỏi người dùng chọn công cụ/model.\n"
        "- Chỉ làm khác mặc định khi người dùng NÊU RÕ (vd 'vẽ bằng chatgpt', "
        "'video chất lượng đẹp').\n"
        "- Một yêu cầu = một nhánh chính; đừng gọi nhiều tool tạo media cho "
        "cùng một yêu cầu.")
    return "\n\n".join(parts)


def _finalize(user_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Attach ask-choices metadata; strip control blocks; P0#5 filter media URLs."""
    try:
        result = ask_choices.apply_to_result(result, user_id)
    except Exception:
        pass
    # LLM/tool output = untrusted — chặn SSRF trước khi bot channel fetch/gửi.
    try:
        from services import net_guard
        if isinstance(result, dict):
            result = net_guard.filter_agent_output(result)
    except Exception as exc:
        logger.warning("agent: filter_agent_output failed: %s", exc)
    return result if isinstance(result, dict) else {"text": str(result or "")}


def _get_history(user_id: str) -> list[dict[str, Any]]:
    """Load durable session history (fallback to in-process cache)."""
    if sess.is_enabled():
        try:
            loaded = sess.load_history(user_id)
            if loaded:
                _history[user_id] = loaded
                return _history[user_id]
        except Exception as exc:
            logger.warning("agent: load session failed: %s", exc)
    return _history.setdefault(user_id, [])


def _persist_history(user_id: str, hist: list[dict[str, Any]]) -> None:
    """Write history + searchable turns; compact when long."""
    _history[user_id] = list(hist)
    if not sess.is_enabled():
        return
    try:
        # Log the latest exchange into FTS (user then assistant when available)
        if len(hist) >= 2 and hist[-1].get("role") == "assistant" and hist[-2].get("role") == "user":
            sess.append_turn(user_id, "user", str(hist[-2].get("content") or ""))
            sess.append_turn(user_id, "assistant", str(hist[-1].get("content") or ""))
        elif hist:
            last = hist[-1]
            sess.append_turn(user_id, str(last.get("role") or ""), str(last.get("content") or ""))
        new_hist = compact.maybe_compact(user_id, hist)
        if new_hist is not None:
            hist[:] = new_hist
            _history[user_id] = list(hist)
        else:
            sess.save_history(user_id, hist)
    except Exception as exc:
        logger.warning("agent: persist session failed: %s", exc)


def _classify_reply(text: str) -> Optional[str]:
    """Return 'always' | 'once' | 'deny' | None for a short confirmation reply."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if any(k in t for k in _APPROVE_ALWAYS):
        return "always"
    if any(t == k or t.startswith(k + " ") or t.startswith(k + ",") for k in _DENY):
        return "deny"
    if any(t == k or t.startswith(k + " ") or t.startswith(k + ",") or t.endswith(" " + k) for k in _APPROVE_ONCE):
        return "once"
    return None


def _execute(cap: "caps.Capability", args: dict, user_id: str) -> dict:
    ctx = {"user_id": user_id}
    risk = str(getattr(cap, "risk", "") or "").lower()
    try:
        raw = cap.handler(args, ctx)
    except Exception as exc:  # report, never crash the turn
        logger.exception("agent: capability %s failed", cap.name)
        try:
            if risk == "change":
                approval_gate.log_event(
                    "execute_error", user_id, cap.name,
                    summary=str(exc)[:200],
                )
        except Exception:
            pass
        return {"text": f"Em gặp lỗi khi {cap.name} 😥: {str(exc)[:150]}. Anh/chị muốn em thử lại không?"}
    # P2#12: audit append-only mọi hành động CHANGE (kể cả auto-approve)
    try:
        if risk == "change":
            summary = approval_gate.summarize_action(
                cap.name, args if isinstance(args, dict) else {},
                getattr(cap, "description", "") or "",
            )
            approval_gate.log_event(
                "execute_change", user_id, cap.name, summary=summary,
            )
    except Exception as exc:
        logger.warning("agent: audit log failed: %s", exc)
    # TokenJuice-style: compact large tool text before it hits the model context.
    # expand_tool_result itself is never compressed (would hide the full payload).
    if cap.name == "expand_tool_result":
        out = raw if isinstance(raw, dict) else {"text": str(raw)}
    else:
        try:
            out = tool_compress.maybe_compress_result(
                raw if isinstance(raw, dict) else {"text": str(raw)},
                tool_name=cap.name,
            )
        except Exception as exc:
            logger.warning("agent: tool_compress failed: %s", exc)
            out = raw if isinstance(raw, dict) else {"text": str(raw)}
    # P1#7: redact secret/PII trong tool result trước khi vào context
    try:
        from services.privacy_gate import redact_text
        if isinstance(out, dict) and isinstance(out.get("text"), str) and out["text"]:
            out = dict(out)
            out["text"] = redact_text(out["text"], session_id=f"agent:{user_id}")
    except Exception:
        pass
    return out


def orchestrate(user_text: str, user_id: str,
                allow: set[str] | None = None,
                ha_fastpath: bool = True,
                model: str | None = None,
                auto_approve: bool = False) -> dict[str, Any]:
    """`allow` = tập nhóm chức năng threadID này được phép (None = tất cả). Lọc
    tool schema + chặn dispatch theo nhóm để giới hạn chức năng cho từng người.

    `ha_fastpath` = cài đặt RIÊNG từng bot/tài khoản (Telegram/Zalo): lệnh nhà
    thông minh rõ ràng được thực thi cục bộ ngay — không vòng qua provider.

    `model` = override model (vd. per-admin ai_model); trống → model_hints/default.
    """
    import time as _time
    t0 = _time.time()
    tools_used: list[str] = []
    steps_done = 0
    run_status = "ok"
    run_error = ""
    _override = str(model or "").strip()
    main_model = _override or _main_model("reason")

    def _journal(reply: str, *, status: str | None = None, error: str = "") -> None:
        try:
            uid = str(user_id or "")
            # Infer channel + source account from user_id prefixes used by bots
            source_kind = ""
            source_account = ""
            source_peer = ""
            if uid.startswith("zalop_"):
                source_kind = "zalop"
                rest = uid[6:]
                # zalop_{account}_{thread} or similar
                parts = rest.split("_", 1)
                source_account = parts[0] if parts else rest
                source_peer = parts[1] if len(parts) > 1 else ""
            elif uid.startswith("zalo_"):
                source_kind = "zalo"
                source_peer = uid[5:]
            elif uid.startswith("email_"):
                source_kind = "email"
                source_peer = uid[6:]
            elif uid.startswith("tg_") or uid.isdigit():
                source_kind = "tg"
                source_peer = uid[3:] if uid.startswith("tg_") else uid
            else:
                source_kind = "tg" if uid else "agent"
                source_peer = uid
            # Infer display kind + permission groups (🏠 Ảnh / Video / …) for UI
            run_kind = "agent"
            tools_set = set(tools_used or [])
            if tools_set & {"generate_image", "library_media"} and not (
                tools_set - {"generate_image", "library_media", "expand_tool_result"}
            ):
                run_kind = "image_gen"
            elif tools_set & {"generate_video"} and not (
                tools_set - {"generate_video", "expand_tool_result"}
            ):
                run_kind = "video_gen"
            groups: list[str] = []
            try:
                from services.agent.capabilities import group_of
                for t in tools_used or []:
                    g = group_of(t)
                    if g and g != "_ungrouped" and g not in groups:
                        groups.append(g)
            except Exception:
                groups = []
            run_journal.log_run(
                user_id=user_id,
                user_text=user_text,
                reply_text=reply,
                model=main_model,
                hint=run_kind,
                tools=tools_used,
                steps=steps_done,
                duration_ms=int((_time.time() - t0) * 1000),
                status=status or run_status,
                error=error or run_error,
                meta={
                    "kind": run_kind,
                    "kind_label": {
                        "image_gen": "Tạo ảnh",
                        "video_gen": "Tạo video",
                        "agent": "Agent",
                    }.get(run_kind, "Agent"),
                    "groups": groups,
                },
                source_kind=source_kind,
                source_account=source_account,
                source_peer=source_peer,
                # dest_* filled from request_context by log_run when providers set it
            )
        except Exception as exc:
            logger.debug("agent: run_journal failed: %s", exc)

    user_text = (user_text or "").strip()
    if not user_text:
        return {"text": "Dạ anh/chị cần em giúp gì ạ? 😊"}

    # 0) Resolve a pending ask-choice (user tapped button or replied 1/2/…)
    try:
        picked = ask_choices.resolve_reply(user_id, user_text)
        if picked:
            user_text = picked
    except Exception:
        pass

    # 0) Speech Persona wizard — deterministic, ngoài vòng LLM (0 token model).
    # Chỉ can thiệp khi user gõ trigger ('persona'…) hoặc wizard đang mở.
    try:
        from services.agent import persona as _persona
        _p_out = _persona.handle(user_id, user_text)
        if _p_out is not None:
            return _finalize(user_id, _p_out)
    except Exception as _p_exc:
        logger.warning("persona wizard: %s", _p_exc)

    # 1) Resolve a pending approval (confirming a proposed change).
    pending = approval_gate.get_pending(user_id)
    if pending is not None:
        verdict = _classify_reply(user_text)
        if verdict in ("once", "always"):
            cap = caps.get(pending["capability"])
            if verdict == "always" and cap:
                approval_gate.resolve(user_id, "always", capability=cap.name)
            else:
                approval_gate.resolve(user_id, "once", capability=(cap.name if cap else ""))
            if cap:
                tools_used.append(cap.name)
                out = _execute(cap, pending.get("args") or {}, user_id)
                if verdict == "always":
                    out["text"] = "Dạ, từ giờ việc này em tự làm khỏi hỏi ạ. " + out.get("text", "")
                fin = _finalize(user_id, out)
                _journal(str(fin.get("text") or ""), status="approved")
                return fin
        elif verdict == "deny":
            approval_gate.resolve(
                user_id, "deny",
                capability=str(pending.get("capability") or ""),
            )
            _journal("thôi", status="denied")
            return {"text": "Dạ thôi em không làm ạ 🙆"}
        # Not a clear yes/no → fall through and treat as a new request.
        approval_gate.clear_pending(user_id)

    hist = _get_history(user_id)
    # Snapshot for SuperContext (before this turn becomes "history").
    hist_before = list(hist)
    hist.append({"role": "user", "content": user_text})
    # Soft cap in-process; durable store keeps more until compaction.
    max_h = sess.max_history() if sess.is_enabled() else 16
    if len(hist) > max_h * 2:
        del hist[: len(hist) - max_h * 2]

    # 1.5) HA fast-path (bật/tắt RIÊNG từng bot/tài khoản qua `ha_fastpath`):
    # lệnh điều khiển / câu hỏi nhà RÕ RÀNG → xử lý CỤC BỘ ngay, KHÔNG vòng qua
    # provider — thiết bị phản ứng tức thì và chạy được cả khi không có provider
    # nào. Phần trả lời: thử nhờ model diễn đạt tự nhiên; không có provider /
    # lỗi → dùng luôn văn mẫu của fast-path.
    if ha_fastpath and (allow is None or "homeassistant" in allow):
        fp_text, fp_control = None, False
        try:
            from services.protocol.openai_v1_chat_complete import ha_local_fastpath_answer
            fp_text, fp_control = ha_local_fastpath_answer(user_text)
        except Exception as exc:
            logger.warning("agent: ha fastpath error: %s", exc)
        # Optional: gate HA control through approval (default off — instant lights).
        if (
            fp_text and fp_control
            and approval_gate.gate_ha_fastpath()
            and approval_gate.needs_approval(user_id, "control_home", risk="change")
        ):
            approval_gate.set_pending(
                user_id, "control_home", {"command": user_text}, user_text,
            )
            q = approval_gate.format_proposal(
                "control_home", {"command": user_text},
                description="Điều khiển nhà thông minh",
                label="điều khiển nhà",
            )
            out_q = _finalize(user_id, {"text": q})
            hist.append({"role": "assistant", "content": out_q.get("text") or q})
            _persist_history(user_id, hist)
            return out_q
        if fp_text and fp_control and approval_gate.is_blocked("control_home", risk="change"):
            return {"text": "Chế độ chỉ-đọc: em không được điều khiển nhà ạ."}
        if fp_text:
            logger.info("agent: ha fastpath %s -> %.120s",
                        "control" if fp_control else "answer", fp_text)
            reply = fp_text
            try:
                # Dùng model chat (thường "AI text") — giữ °C/%; burst có thể là
                # model rẻ không :text và verbalize lại.
                _phrase_model = _main_model("chat") or _main_model("burst")
                resp = call_model(_phrase_model, [
                    {"role": "system", "content": (
                        "Hệ thống nhà thông minh ĐÃ xử lý xong tin nhắn của người dùng. "
                        "Diễn đạt lại kết quả bên dưới thành MỘT câu trả lời tiếng Việt "
                        "tự nhiên, ấm áp (xưng 'em') — đúng CHÍNH XÁC nội dung kết quả, "
                        "không bịa thêm thiết bị hay số liệu, không hỏi thêm.\n"
                        "QUAN TRỌNG — GIỮ NGUYÊN ĐƠN VỊ KÝ HIỆU trong kết quả: "
                        "viết đúng °C (không viết 'độ'/'độ C'), viết % (không 'phần trăm'), "
                        "giữ km/h, kWh nếu có. Ví dụ đúng: 'khoảng 30°C, độ ẩm 79%'."
                    )},
                    {"role": "user", "content": (
                        f"Tin nhắn: {user_text}\nKết quả từ hệ thống nhà: {fp_text}")},
                    # no_smart_home: chỉ nhờ diễn đạt LẠI văn bản — tắt tích hợp HA
                    # kẻo pipeline thấy từ khóa lệnh nhà rồi THỰC THI LẦN 2.
                ], timeout=30, no_smart_home=True)
                if not resp.get("error"):
                    phrased = content_of(resp).strip()
                    if phrased:
                        reply = phrased
            except Exception as exc:  # call_model không raise, nhưng phòng hờ
                logger.info("agent: ha fastpath phrasing skipped: %s", exc)
            out = _finalize(user_id, {"text": reply})
            hist.append({"role": "assistant", "content": out.get("text") or reply})
            _persist_history(user_id, hist)
            tools_used.append("ha_fastpath")
            _journal(str(out.get("text") or reply), status="ha_fastpath")
            return out

    # Only feed the recent tail to the model (summary lives in system prompt).
    model_hist = hist[-max_h:]
    sys_prompt = _build_system_prompt(user_id, allow)
    # Speech Persona của phiên (nếu cài) — khối nén ~100 token, lưu sẵn.
    try:
        from services.agent import persona as _persona2
        _pb = _persona2.prompt_for(user_id)
        if _pb:
            sys_prompt += "\n\n" + _pb
    except Exception:
        pass
    sys_prompt = super_context.maybe_attach(
        sys_prompt, user_id, user_text, hist_before, allow=allow,
    )
    messages = [{"role": "system", "content": sys_prompt}] + list(model_hist)

    # 2) Agentic loop.
    seen_workflows: set[str] = set()  # tier-2: inject each workflow note once/turn
    for _step in range(_MAX_STEPS):
        steps_done = _step + 1
        resp = call_model(main_model, messages, tools=caps.tools_schema(allow),
                          no_smart_home=(allow is not None and "homeassistant" not in allow),
                          allowed_groups=allow, channel=caps._channel_of({"user_id": user_id}))
        if resp.get("error"):
            run_status = "error"
            run_error = str(resp.get("error") or "")[:200]
            msg_err = f"Hệ thống đang trục trặc 😥 ({resp['error']}). Anh/chị thử lại giúp em nhé."
            _journal(msg_err, status="error", error=run_error)
            return {"text": msg_err}
        msg = ((resp.get("choices") or [{}])[0].get("message")) or {}
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            reply = content_of(resp).strip() or "Dạ em chưa rõ ý, anh/chị nói lại giúp em nhé 😊"
            if allow is not None and "[BLOCKED]" in reply:
                # Thread lọc hỏi chức năng bị tắt → BỎ QUA, không phản hồi gì
                # (yêu cầu 2026-07-15). Bot thấy silent=True sẽ không gửi tin.
                if hist and hist[-1].get("role") == "user":
                    hist.pop()
                _journal("", status="blocked")
                return {"text": "", "silent": True}
            out = _finalize(user_id, {"text": reply})
            hist.append({"role": "assistant", "content": out.get("text") or reply})
            _persist_history(user_id, hist)
            _journal(str(out.get("text") or reply))
            return out

        # Append the assistant tool-call message so results can reference it.
        messages.append({"role": "assistant", "content": msg.get("content"),
                         "tool_calls": tool_calls})
        produced_media: Optional[dict] = None  # {"image_url"|"video_path"|"video_url"|"doc_path": ...}
        produced_caption = "Đây ạ 🎨"

        for tc in tool_calls:
            fn = (tc.get("function") or {})
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            # P2: tool runtime resolves vault refs (AI never had plaintext)
            try:
                from services.privacy_gate import resolve_secret_ref
                if isinstance(args, dict):
                    resolved = {}
                    for k, v in args.items():
                        if isinstance(v, str) and ("⟦" in v or k.lower() in {
                            "password", "passwd", "pwd", "secret", "token",
                            "api_key", "session_key", "mk", "mat_khau",
                        }):
                            resolved[k] = resolve_secret_ref(v, session_id=f"agent:{user_id}")
                        elif isinstance(v, str) and "⟦" in v:
                            resolved[k] = resolve_secret_ref(v, session_id=f"agent:{user_id}")
                        else:
                            resolved[k] = v
                    args = resolved
            except Exception:
                pass
            if name:
                tools_used.append(str(name))
            cap = caps.get(name)
            if not cap:
                result = {"text": f"(không có công cụ {name})"}
            elif (allow is not None and name not in caps._CORE_TOOLS
                    and caps.group_of(name) not in allow):
                # Chốt chặn tầng 2 — model KHÔNG nên gọi (đã lọc schema) nhưng nếu
                # cố gọi thì BỎ QUA im lặng theo bộ lọc chức năng của threadID.
                if hist and hist[-1].get("role") == "user":
                    hist.pop()
                return {"text": "", "silent": True}
            elif not auto_approve and approval_gate.is_blocked(name, risk=cap.risk):
                result = {
                    "text": (
                        f"Chế độ chỉ-đọc: em không được chạy `{name}` "
                        f"(thay đổi hệ thống). Anh/chị bật lại autonomy supervised/full nhé."
                    ),
                }
            elif not auto_approve and approval_gate.needs_approval(user_id, name, risk=cap.risk):
                # Propose + wait for approval (ASK chips + ok/luôn luôn/thôi).
                # Never put resolved secrets into approval UI — re-redact display
                display_args = dict(args)
                try:
                    from services.privacy_gate import redact_text
                    for k, v in list(display_args.items()):
                        if isinstance(v, str) and k.lower() in {
                            "password", "passwd", "pwd", "secret", "token", "api_key",
                        }:
                            display_args[k] = "⟦HIDDEN⟧"
                except Exception:
                    pass
                summary = approval_gate.summarize_action(
                    name, display_args, cap.description or "",
                )
                approval_gate.set_pending(user_id, name, args, summary)
                q = approval_gate.format_proposal(
                    name, display_args,
                    description=cap.description or "",
                    label=cap.label or cap.name,
                )
                out_q = _finalize(user_id, {"text": q})
                hist.append({"role": "assistant", "content": out_q.get("text") or q})
                _persist_history(user_id, hist)
                _journal(str(out_q.get("text") or q), status="awaiting_approval")
                return out_q
            else:
                result = _execute(cap, args, user_id)

            for media_key in ("image_url", "video_path", "video_url", "audio_url", "audio_path", "doc_path"):
                if not result.get(media_key):
                    continue
                # P0#5: tool/model media — chỉ giữ URL/path được phép egress.
                try:
                    from services import net_guard as _ng
                    val = result[media_key]
                    if media_key.endswith("_url"):
                        if not _ng.is_allowed_egress_url(str(val)):
                            logger.warning("orchestrator drop unsafe %s=%s",
                                           media_key, str(val)[:120])
                            continue
                    elif media_key.endswith("_path"):
                        if not _ng.is_allowed_media_path(str(val)):
                            logger.warning("orchestrator drop unsafe %s=%s",
                                           media_key, str(val)[:120])
                            continue
                except Exception as exc:
                    logger.warning("orchestrator media guard: %s", exc)
                    continue
                produced_media = {media_key: result[media_key]}
                produced_caption = result.get("text") or "Đây ạ 🎨"
                break
            content = result.get("text", "")
            # Redact secret/PII trong tool result trước khi đưa lại context LLM
            # (OWASP LLM02/LLM07 — tool output có thể chứa token/cookie).
            try:
                from services.privacy_gate import redact_text
                if isinstance(content, str) and content:
                    content = redact_text(content, session_id=f"agent:{user_id}")
            except Exception:
                pass
            # Tier-2 workflow note: procedural guidance costs tokens only when
            # the capability is actually used (first use per turn).
            if cap and cap.workflow and cap.name not in seen_workflows:
                seen_workflows.add(cap.name)
                content += f"\n\n[Quy trình {cap.name}]: {cap.workflow}"
            messages.append({"role": "tool", "tool_call_id": tc.get("id"),
                             "content": content})

        # If a capability produced media, deliver it now (the media is the answer).
        if produced_media:
            text = produced_caption
            out_m = _finalize(user_id, {"text": text, **produced_media})
            hist.append({"role": "assistant", "content": out_m.get("text") or text})
            _persist_history(user_id, hist)
            _journal(str(out_m.get("text") or text), status="media")
            return out_m
        # else loop: let the model integrate the tool results into a natural reply.

    # Ran out of steps.
    msg_slow = "Em xử lý hơi lâu, anh/chị thử hỏi lại gọn hơn giúp em nhé 😊"
    _journal(msg_slow, status="max_steps")
    return {"text": msg_slow}
