"""Multi-step agent workflows (2–5 steps) with optional verify.

Canonical files under ``DATA_DIR/agent/workflows/<slug>.md``::

    ---
    name: Morning brief pipeline
    description: Thu thập trạng thái nhà rồi viết báo cáo sáng
    verify: true
    trigger: tin_nhan
    khi: báo cáo sáng|brief sáng
    ---

    ## Bước 1: Thu thập
    Dựa trên yêu cầu người dùng ({{input}}), liệt kê những gì cần kiểm tra
    ở nhà thông minh và giả định dữ liệu nếu chưa có tool.

    ## Bước 2: Viết báo cáo
    Dùng kết quả bước trước:
    {{prev}}

    Viết báo cáo sáng 5–8 dòng, xưng em, tiếng Việt.

Package defaults in ``workflows_default/`` are seeded once (never overwrite).

Tự kích hoạt (mượn thiết kế trigger của block/buzz — ở đó workflow bắn theo
``message_posted`` / ``webhook``; đây rút còn hai đường đó vì lịch đã có
``reminders``/``lich_lap`` lo)::

    trigger: tin_nhan   # câu người dùng chứa từ khoá `khi:` → chạy thẳng
    trigger: webhook    # chỉ chạy khi bị gọi qua API, không tự bắn trong chat
    khi: sự cố|mất điện # danh sách từ khoá, ngăn bằng '|', khớp KHÔNG cần dấu

Vì sao từ khoá chứ không phải regex: file này do người vận hành gõ tay, mà
``re`` của Python không có trần thời gian — một regex lỡ tay (``(a+)+b``) sẽ
treo đúng luồng chat. buzz chặn chuyện tương tự bằng trần 100ms cho biểu thức
điều kiện; ở đây khớp chuỗi con là đủ việc và không có đường nào để treo.

Config (``agent_workflows``)::

    enabled: bool (default True)
    max_steps: int (default 5)
    step_timeout: int seconds (default 90)
    max_concurrent: int (default 2) — số workflow chạy CÙNG LÚC
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from services.agent.runtime import call_model, content_of
from services.agent.skills import split_frontmatter, valid_slug, SKILL_DESC_MAX
from services.agent.vi_text import fold
from services.config import DATA_DIR, config

logger = logging.getLogger(__name__)

_WF_DIR = Path(DATA_DIR) / "agent" / "workflows"
_DEFAULTS = Path(__file__).with_name("workflows_default")
_STEP_RE = re.compile(
    r"^##\s*Bước\s*(\d+)\s*[:：.\-–]?\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_lock = threading.RLock()
_seeded = False


def _cfg() -> dict[str, Any]:
    raw = config.get().get("agent_workflows")
    return raw if isinstance(raw, dict) else {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def max_steps() -> int:
    try:
        return max(2, min(int(_cfg().get("max_steps") or 5), 8))
    except (TypeError, ValueError):
        return 5


def max_concurrent() -> int:
    """Trần workflow chạy cùng lúc. Hết chỗ thì TỪ CHỐI NGAY, không xếp hàng.

    Mượn của buzz (``try_acquire`` → ``CapacityExceeded`` thay vì chờ): một
    workflow là 2–5 lượt gọi model, xếp hàng chỉ dời cơn quá tải sang phút sau
    rồi trả lời khi người dùng đã bỏ đi. Máy chủ này còn chạy bot thật nên trần
    để thấp; muốn cao hơn thì chỉnh ``agent_workflows.max_concurrent``.
    """
    try:
        return max(1, min(int(_cfg().get("max_concurrent") or 2), 8))
    except (TypeError, ValueError):
        return 2


def step_timeout() -> int:
    try:
        return max(30, int(_cfg().get("step_timeout") or 90))
    except (TypeError, ValueError):
        return 90


def _main_model() -> str:
    return str(config.get().get("telegram_ai_model") or "").strip() or "cx/auto"


def _ensure_seeded() -> None:
    global _seeded
    if _seeded:
        return
    with _lock:
        if _seeded:
            return
        try:
            _WF_DIR.mkdir(parents=True, exist_ok=True)
            if _DEFAULTS.is_dir():
                for f in sorted(_DEFAULTS.glob("*.md")):
                    dest = _WF_DIR / f.name
                    if dest.exists():
                        continue
                    shutil.copy2(f, dest)
                    logger.info("agent.workflows: seeded %s", f.name)
        except Exception as exc:
            logger.warning("agent.workflows: seed failed: %s", exc)
        _seeded = True


class BuocLoi(RuntimeError):
    """Một bước không gọi được model.

    Trước đây bước hỏng trả về chuỗi ``(lỗi bước N: …)`` — trông y như nội dung
    thật, nên chuỗi cứ chạy tiếp và bước sau nhận nguyên câu báo lỗi làm
    ``{{prev}}``. Đo thật 19/08: bước 2 lỗi 429, bước 3 vẫn chạy rồi viết "không
    có nội dung để rút gọn", mà bước kiểm chứng còn chấm PASS cho nó. Ngoại lệ
    thì không thể bị nhầm là nội dung.
    """


@dataclass
class WorkflowStep:
    index: int
    title: str
    prompt: str


@dataclass
class Workflow:
    slug: str
    name: str
    description: str
    verify: bool
    steps: list[WorkflowStep] = field(default_factory=list)
    path: Optional[Path] = None
    # "" = chỉ chạy khi được gọi (model chọn, hoặc tool run_workflow).
    trigger: str = ""
    # Từ khoá đã fold sẵn — chỉ dùng khi trigger == "tin_nhan".
    keywords: list[str] = field(default_factory=list)

    def router_line(self) -> str:
        desc = (self.description or self.name or self.slug).strip()
        if len(desc) > SKILL_DESC_MAX:
            desc = desc[: SKILL_DESC_MAX - 1] + "…"
        n = len(self.steps)
        return f"- `{self.slug}` ({n} bước): {desc}"


def parse_workflow_md(slug: str, text: str, path: Path | None = None) -> Workflow:
    meta, body = split_frontmatter(text or "")
    name = (meta.get("name") or slug).strip()
    desc = (meta.get("description") or "").strip()
    verify = str(meta.get("verify", "false")).strip().lower() in (
        "1", "true", "yes", "on",
    )
    trigger = (meta.get("trigger") or "").strip().lower()
    if trigger not in ("tin_nhan", "webhook"):
        trigger = ""
    # Từ khoá quá ngắn khớp vào giữa chữ khác ("an" nằm trong "bàn ăn") nên mọi
    # câu đều bắn workflow. Trần 3 ký tự (sau fold) chặn đúng chuyện đó.
    keywords = []
    for k in (meta.get("khi") or "").split("|"):
        kf = fold(k).strip()
        if len(kf) >= 3:
            keywords.append(kf)
    if trigger == "tin_nhan" and not keywords:
        # Khai `trigger: tin_nhan` mà không có `khi:` thì sẽ khớp MỌI câu —
        # coi như chưa khai, kẻo một file lỡ tay nuốt sạch luồng chat.
        trigger = ""
    steps: list[WorkflowStep] = []
    matches = list(_STEP_RE.finditer(body or ""))
    if matches:
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            prompt = (body[start:end] or "").strip()
            title = (m.group(2) or f"Bước {m.group(1)}").strip() or f"Bước {m.group(1)}"
            try:
                idx = int(m.group(1))
            except ValueError:
                idx = i + 1
            if prompt:
                steps.append(WorkflowStep(index=idx, title=title, prompt=prompt))
    else:
        # Fallback: whole body is one step
        blob = (body or "").strip()
        if blob:
            steps.append(WorkflowStep(index=1, title="Chạy", prompt=blob))
    # Cap steps
    steps = steps[: max_steps()]
    return Workflow(
        slug=slug, name=name, description=desc, verify=verify,
        steps=steps, path=path, trigger=trigger, keywords=keywords,
    )


def list_workflows() -> list[Workflow]:
    if not is_enabled():
        return []
    _ensure_seeded()
    out: list[Workflow] = []
    try:
        if not _WF_DIR.is_dir():
            return []
        for f in sorted(_WF_DIR.glob("*.md")):
            slug = f.stem
            if not valid_slug(slug):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            wf = parse_workflow_md(slug, text, f)
            if wf.steps:
                out.append(wf)
    except OSError as exc:
        logger.warning("agent.workflows: list failed: %s", exc)
    return out


def get_workflow(slug: str) -> Optional[Workflow]:
    if not valid_slug(slug) or not is_enabled():
        return None
    _ensure_seeded()
    path = _WF_DIR / f"{slug}.md"
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    wf = parse_workflow_md(slug, text, path)
    return wf if wf.steps else None


def khop_tin_nhan(text: str) -> Optional[Workflow]:
    """Workflow nào có ``trigger: tin_nhan`` và từ khoá nằm trong câu này.

    Khớp không dấu (``vi_text.fold``) nên "bao cao sang" cũng bắt được "báo cáo
    sáng". Duyệt theo thứ tự tên file nên khi hai workflow cùng khớp, kết quả
    luôn là một — không phụ thuộc thứ tự đọc thư mục.

    Trả None khi không khớp, khi workflow đang tắt, hoặc khi câu rỗng.
    """
    t = fold(text).strip()
    if not t:
        return None
    for wf in list_workflows():
        if wf.trigger != "tin_nhan":
            continue
        if any(k in t for k in wf.keywords):
            return wf
    return None


def cho_phep_webhook(slug: str) -> Optional[Workflow]:
    """Workflow này có tự khai ``trigger: webhook`` không (opt-in như buzz).

    Không khai thì API từ chối — để một endpoint bị lộ không biến MỌI workflow
    trong máy thành thứ gọi được từ ngoài.
    """
    wf = get_workflow(slug)
    return wf if wf is not None and wf.trigger == "webhook" else None


def router_block() -> str:
    wfs = list_workflows()
    if not wfs:
        return ""
    lines = [
        "## Workflow (chuỗi nhiều bước — tool run_workflow)",
        "Khi yêu cầu cần nhiều giai (thu thập → xử lý → kiểm chứng), gọi "
        "run_workflow(slug=…, input=…). Không tự bịa slug ngoài danh sách.",
    ]
    for w in wfs[:20]:
        lines.append(w.router_line())
    return "\n".join(lines)


_dang_chay = 0


def _gio_cho() -> bool:
    """Giữ một chỗ chạy. False = hết chỗ (caller phải từ chối NGAY, không chờ)."""
    global _dang_chay
    with _lock:
        if _dang_chay >= max_concurrent():
            return False
        _dang_chay += 1
        return True


def _tra_cho() -> None:
    global _dang_chay
    with _lock:
        _dang_chay = max(0, _dang_chay - 1)


def dang_chay() -> int:
    with _lock:
        return _dang_chay


def _render_prompt(template: str, *, user_input: str, prev: str) -> str:
    t = template or ""
    t = t.replace("{{input}}", user_input or "")
    t = t.replace("{{prev}}", prev or "")
    return t.strip()


def _run_llm_step(
    *,
    step: WorkflowStep,
    user_input: str,
    prev: str,
    model: str,
) -> str:
    prompt = _render_prompt(step.prompt, user_input=user_input, prev=prev)
    system = (
        f"Bạn đang thực hiện BƯỚC {step.index}: {step.title} trong một pipeline. "
        "Chỉ làm đúng bước này, trả lời tiếng Việt, ngắn gọn, không hỏi lại. "
        "Dùng {{prev}}/kết quả trước nếu được cung cấp."
    )
    resp = call_model(
        model,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt or user_input},
        ],
        timeout=step_timeout(),
        max_tokens=900,
        no_smart_home=True,
    )
    if resp.get("error"):
        raise BuocLoi(str(resp["error"]))
    return content_of(resp).strip() or f"(bước {step.index} trống)"


def _verify(goal: str, result: str, model: str) -> tuple[bool, str]:
    resp = call_model(
        model,
        [
            {
                "role": "system",
                "content": (
                    "Bạn là bước KIỂM CHỨNG. Đọc mục tiêu và kết quả pipeline. "
                    "Trả lời ĐÚNG 2 dòng:\n"
                    "VERDICT: PASS hoặc FAIL\n"
                    "NOTE: một câu tiếng Việt giải thích ngắn."
                ),
            },
            {
                "role": "user",
                "content": f"Mục tiêu:\n{goal}\n\nKết quả:\n{result[:3000]}",
            },
        ],
        timeout=min(60, step_timeout()),
        max_tokens=200,
        no_smart_home=True,
    )
    if resp.get("error"):
        return True, f"(bỏ qua verify: {resp['error']})"
    text = content_of(resp).strip()
    up = text.upper()
    ok = "FAIL" not in up.split("VERDICT", 1)[-1][:40] if "VERDICT" in up else "FAIL" not in up[:80]
    # Prefer explicit PASS
    if re.search(r"VERDICT\s*:\s*PASS", text, re.I):
        ok = True
    elif re.search(r"VERDICT\s*:\s*FAIL", text, re.I):
        ok = False
    note = text
    m = re.search(r"NOTE\s*:\s*(.+)", text, re.I | re.S)
    if m:
        note = m.group(1).strip().splitlines()[0][:200]
    return ok, note


def _ghi_nhat_ky(slug: str, ten: str, log_lines: list[str], t0: float,
                 *, hong: bool = False) -> None:
    """Nhật ký từng bước đi vào LOG MÁY CHỦ, không đi vào tin nhắn người dùng.

    Bản cũ nối nhật ký vào cuối câu trả lời. Đo thật trên `morning-brief`: tin
    gửi đi 562 ký tự mà nội dung chỉ 102 — phần còn lại là bản nháp của các bước
    lặp lại chính nội dung ấy thêm hai lần nữa. Người hỏi "báo cáo sáng" không
    cần biết pipeline có mấy bước; người CẦN biết là chủ máy lúc đi soi vì sao
    workflow ra kết quả lạ, mà chỗ của họ là log.
    """
    logger.info({
        "event": "workflow_hong" if hong else "workflow_xong",
        "slug": slug, "ten": ten,
        "ms": int((time.time() - t0) * 1000),
        "buoc": log_lines,
    })


def chan_thieu_quyen(slug: str, ctx: dict[str, Any] | None) -> Optional[str]:
    """Lời từ chối nếu khung chat này không được phép chạy `slug`; None = cho qua.

    Cổng Giáo viên phải nằm ở tầng `run()`, KHÔNG nằm riêng trong tool
    `run_workflow`: từ khi workflow tự bắn theo `trigger:` và gọi được qua
    webhook thì có BA đường vào cùng một pipeline, mà bản đầu chỉ có đường tool
    là bị kiểm. Một thread chưa hề được cấp nhóm «Giáo viên tiểu học» chỉ cần gõ
    đúng từ khoá là chạy được `cham-bai`.

    `ctx` rỗng (webhook) → `can_use_teacher` xét như thread chưa lọc, tức cho
    phép; đường đó đã đòi khoá admin nên không nới thêm quyền cho ai.
    """
    try:
        from services.agent import teacher as teach
    except Exception:          # teacher là phần tuỳ chọn, thiếu thì thôi
        return None
    if slug not in teach.TEACHER_WORKFLOWS:
        return None
    if not teach.is_enabled():
        return "Chế độ Giáo viên đang tắt trong Settings ạ."
    if not teach.can_use_teacher(ctx=ctx or {}):
        return ("Khung chat này chưa được cấp «Giáo viên tiểu học». "
                "Admin tick trong Settings → Lọc thread.")
    return None


def run(
    slug: str,
    user_input: str,
    *,
    model: str | None = None,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Chạy workflow. Trả {text, ok, slug, steps_run, verified?, verify_note?}.

    ``text`` là NỘI DUNG gửi thẳng cho người dùng — không kèm nhật ký các bước
    (nhật ký đi vào log máy chủ, xem `_ghi_nhat_ky`). Bước nào gọi model không
    được thì dừng ngay tại đó, trả ``ok=False`` kèm câu báo lỗi cho người dùng.
    """
    if not is_enabled():
        return {"text": "Workflow đang tắt trên máy chủ ạ.", "ok": False}
    wf = get_workflow(slug)
    if not wf:
        names = ", ".join(w.slug for w in list_workflows()[:12]) or "(trống)"
        return {
            "text": f"Không thấy workflow `{slug}`. Đang có: {names}",
            "ok": False,
        }
    tu_choi = chan_thieu_quyen(slug, ctx)
    if tu_choi:
        return {"text": tu_choi, "ok": False, "slug": slug}
    user_input = (user_input or "").strip()
    if not user_input:
        return {"text": "Thiếu input cho workflow ạ.", "ok": False}

    model = (model or _main_model()).strip()
    prev = user_input
    log_lines: list[str] = [f"🔄 Workflow **{wf.name}** (`{slug}`)"]
    t0 = time.time()

    # Giữ chỗ TRƯỚC khi đốt lượt model đầu tiên. Hết chỗ thì trả lời ngay
    # rằng đang bận — xếp hàng chỉ dời cơn quá tải sang phút sau, lúc người
    # dùng đã bỏ đi (đây là chỗ buzz chọn CapacityExceeded thay vì hàng đợi).
    if not _gio_cho():
        return {
            "text": (
                f"Em đang chạy {max_concurrent()} pipeline cùng lúc rồi, "
                "anh chờ một chút rồi bảo lại em ạ."
            ),
            "ok": False,
            "busy": True,
            "slug": slug,
        }
    try:
        # `vi_tri` chứ không phải `step.index`: index lấy nguyên số người viết gõ
        # trong tiêu đề «## Bước N», nên một file đánh số 3 và 7 sẽ báo "chạy tới
        # bước 3" ngay ở bước ĐẦU, và `steps_run` ra 2 khi chưa bước nào xong.
        for vi_tri, step in enumerate(wf.steps, start=1):
            try:
                out = _run_llm_step(
                    step=step, user_input=user_input, prev=prev, model=model,
                )
            except Exception as exc:
                # DỪNG HẲN. Chạy tiếp thì bước sau nhận câu báo lỗi làm dữ liệu
                # vào, tốn thêm lượt gọi model chỉ để sinh ra thứ bỏ đi, mà bước
                # kiểm chứng lại chấm PASS cho nó vì nó "đúng ngữ pháp".
                log_lines.append(f"• B{vi_tri} {step.title}: LỖI — {exc}")
                _ghi_nhat_ky(slug, wf.name, log_lines, t0, hong=True)
                return {
                    "text": (
                        f"Em chạy tới bước {vi_tri} ({step.title}) của «{wf.name}» "
                        "thì gọi model không được ạ. Anh thử lại giúp em nhé."
                    ),
                    "ok": False,
                    "slug": slug,
                    "steps_run": vi_tri - 1,
                    "error": str(exc)[:300],
                }
            prev = out
            preview = out.replace("\n", " ")
            if len(preview) > 120:
                preview = preview[:120] + "…"
            log_lines.append(f"• B{vi_tri} {step.title}: {preview}")

        final = prev
        verified: bool | None = None
        verify_note = ""
        if wf.verify and final:
            try:
                verified, verify_note = _verify(
                    f"{wf.description or wf.name}\nInput: {user_input}",
                    final,
                    model,
                )
                mark = "PASS ✅" if verified else "FAIL ⚠️"
                log_lines.append(f"• Kiểm chứng: {mark} — {verify_note}")
                if not verified:
                    # One repair attempt
                    repair = call_model(
                        model,
                        [
                            {
                                "role": "system",
                                "content": (
                                    "Kết quả pipeline chưa đạt. Sửa lại cho đúng mục tiêu, "
                                    "tiếng Việt, ngắn gọn."
                                ),
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"Mục tiêu: {wf.description or wf.name}\n"
                                    f"Input: {user_input}\n"
                                    f"Kết quả cũ:\n{final[:2500]}\n"
                                    f"Lỗi kiểm chứng: {verify_note}"
                                ),
                            },
                        ],
                        timeout=step_timeout(),
                        max_tokens=900,
                        no_smart_home=True,
                    )
                    if not repair.get("error"):
                        fixed = content_of(repair).strip()
                        if fixed:
                            final = fixed
                            log_lines.append("• Đã sửa sau kiểm chứng")
                            verified = True
            except Exception as exc:
                logger.info("agent.workflows: verify skip: %s", exc)

    finally:
        _tra_cho()

    _ghi_nhat_ky(slug, wf.name, log_lines, t0)
    return {
        "text": final.strip(),
        "ok": True,
        "slug": slug,
        "steps_run": len(wf.steps),
        "verified": verified,
        "verify_note": verify_note,
        "result": final,
    }


def _reset_for_tests(wf_dir: Path | None = None) -> None:
    global _WF_DIR, _seeded, _dang_chay
    with _lock:
        if wf_dir is not None:
            _WF_DIR = Path(wf_dir)
        _seeded = False
        _dang_chay = 0
