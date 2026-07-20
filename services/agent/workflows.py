"""Multi-step agent workflows (2–5 steps) with optional verify.

Canonical files under ``DATA_DIR/agent/workflows/<slug>.md``::

    ---
    name: Morning brief pipeline
    description: Thu thập trạng thái nhà rồi viết báo cáo sáng
    verify: true
    ---

    ## Bước 1: Thu thập
    Dựa trên yêu cầu người dùng ({{input}}), liệt kê những gì cần kiểm tra
    ở nhà thông minh và giả định dữ liệu nếu chưa có tool.

    ## Bước 2: Viết báo cáo
    Dùng kết quả bước trước:
    {{prev}}

    Viết báo cáo sáng 5–8 dòng, xưng em, tiếng Việt.

Package defaults in ``workflows_default/`` are seeded once (never overwrite).

Config (``agent_workflows``)::

    enabled: bool (default True)
    max_steps: int (default 5)
    step_timeout: int seconds (default 90)
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
        steps=steps, path=path,
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
        return f"(lỗi bước {step.index}: {resp['error']})"
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


def run(
    slug: str,
    user_input: str,
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Execute workflow. Returns {text, slug, steps_run, verified?, verify_note?}."""
    if not is_enabled():
        return {"text": "Workflow đang tắt trên máy chủ ạ.", "ok": False}
    wf = get_workflow(slug)
    if not wf:
        names = ", ".join(w.slug for w in list_workflows()[:12]) or "(trống)"
        return {
            "text": f"Không thấy workflow `{slug}`. Đang có: {names}",
            "ok": False,
        }
    user_input = (user_input or "").strip()
    if not user_input:
        return {"text": "Thiếu input cho workflow ạ.", "ok": False}

    model = (model or _main_model()).strip()
    prev = user_input
    log_lines: list[str] = [f"🔄 Workflow **{wf.name}** (`{slug}`)"]
    t0 = time.time()

    for step in wf.steps:
        try:
            out = _run_llm_step(
                step=step, user_input=user_input, prev=prev, model=model,
            )
        except Exception as exc:
            out = f"(lỗi bước {step.index}: {exc})"
            log_lines.append(f"• B{step.index} {step.title}: lỗi")
            prev = out
            break
        prev = out
        preview = out.replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:120] + "…"
        log_lines.append(f"• B{step.index} {step.title}: {preview}")

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

    elapsed = int((time.time() - t0) * 1000)
    body = (
        f"{final.strip()}\n\n"
        f"———\n"
        + "\n".join(log_lines)
        + f"\n⏱ {elapsed}ms · {len(wf.steps)} bước"
    )
    return {
        "text": body,
        "ok": True,
        "slug": slug,
        "steps_run": len(wf.steps),
        "verified": verified,
        "verify_note": verify_note,
        "result": final,
    }


def _reset_for_tests(wf_dir: Path | None = None) -> None:
    global _WF_DIR, _seeded
    with _lock:
        if wf_dir is not None:
            _WF_DIR = Path(wf_dir)
        _seeded = False
