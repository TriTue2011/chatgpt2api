"""Ảnh nhận qua bot → menu ý định (giống pdf_intent).

Lựa chọn:
  1. RAG kiến thức  — nạp wiki (tự phát hiện chủ đề từ caption/OCR/vision)
  2. RAG teacher    — hỏi lớp + môn → nạp SGK
  3. Phân tích ảnh  — vision (hỏi prompt nếu chưa có)
  4. Tạo ảnh (img2img) — hỏi prompt bắt buộc; thuộc filter nhóm ``image``

Ảnh không caption → set_pending(stage=choose).
Sau khi chọn 3/4 mà chưa có prompt → stage=need_prompt.
Teacher → stage=teacher_meta (reuse pdf_intent.parse_teacher_meta).
"""
from __future__ import annotations

import base64
import logging
import os
import re
import tempfile
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_pending: dict[str, dict] = {}
_lock = threading.RLock()
_TTL = 600

# Intent codes
RAG_KNOWLEDGE = "rag_knowledge"
RAG_TEACHER = "rag_teacher"
ANALYZE = "analyze"
GENERATE = "generate"
INTENT_ORDER = (RAG_KNOWLEDGE, RAG_TEACHER, ANALYZE, GENERATE)
ALL_INTENTS = set(INTENT_ORDER)

ASK_PROMPT_ANALYZE = (
    "🔍 Phân tích ảnh — em cần **câu hỏi / yêu cầu** cụ thể.\n"
    "Ví dụ: `mô tả ảnh` · `đọc chữ trong ảnh` · `ảnh có mấy người?`\n"
    "→ Trả lời trong 10 phút."
)
ASK_PROMPT_GENERATE = (
    "🎨 Tạo ảnh từ ảnh này — em cần **mô tả chỉnh sửa / phong cách**.\n"
    "Ví dụ: `vẽ lại anime` · `đổi nền bãi biển` · `làm nét, tông ấm`\n"
    "→ Trả lời trong 10 phút."
)
ASK_TEACHER = (
    "📚 Nạp ảnh vào **RAG teacher / SGK**\n"
    "Cho em **lớp** (1–12) và **môn** (toán / văn / anh).\n"
    "Ví dụ: `5 toán` · `lớp 9 văn`\n"
    "→ Trả lời trong 10 phút."
)


def _gc() -> None:
    now = time.time()
    for k in [k for k, v in _pending.items() if now - v["ts"] > _TTL]:
        v = _pending.pop(k, None)
        if v:
            try:
                os.unlink(v["path"])
            except Exception:
                pass


def set_pending(key: str, image_bytes: bytes, **extra: Any) -> None:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    tmp.write(image_bytes)
    tmp.close()
    with _lock:
        old = _pending.pop(key, None)
        if old:
            try:
                os.unlink(old["path"])
            except Exception:
                pass
        item = {
            "path": tmp.name,
            "ts": time.time(),
            "stage": "choose",  # choose | need_prompt | teacher_meta
            "intent": None,
            "prompt": "",
        }
        item.update({k: v for k, v in extra.items() if v is not None})
        _pending[key] = item
        _gc()


def has_pending(key: str) -> bool:
    with _lock:
        _gc()
        return key in _pending


def get_pending(key: str) -> dict | None:
    with _lock:
        _gc()
        p = _pending.get(key)
        return dict(p) if p else None


def update_pending(key: str, **fields: Any) -> bool:
    with _lock:
        _gc()
        if key not in _pending:
            return False
        _pending[key].update(fields)
        _pending[key]["ts"] = time.time()
        return True


def pop_pending(key: str) -> bytes | None:
    """Lấy bytes ảnh + xóa pending. None nếu hết hạn."""
    with _lock:
        _gc()
        item = _pending.pop(key, None)
    if not item:
        return None
    try:
        with open(item["path"], "rb") as f:
            return f.read()
    except Exception:
        return None
    finally:
        try:
            os.unlink(item["path"])
        except Exception:
            pass


def pop_pending_full(key: str) -> dict | None:
    """Pop cả meta + bytes (bytes trong key 'data')."""
    with _lock:
        _gc()
        item = _pending.pop(key, None)
    if not item:
        return None
    try:
        with open(item["path"], "rb") as f:
            data = f.read()
    except Exception:
        data = None
    try:
        os.unlink(item["path"])
    except Exception:
        pass
    out = dict(item)
    out["data"] = data
    out.pop("path", None)
    return out


def allowed_intents(allow: set[str] | None) -> set[str]:
    """Quyền theo filter thread.

    - rag_knowledge: rag|summary|wiki
    - rag_teacher: teacher
    - analyze: luôn (vision) — hoặc vision nếu có nhóm riêng
    - generate: image
    """
    if allow is None:
        return set(ALL_INTENTS)
    out: set[str] = set()
    if "rag" in allow or "summary" in allow or "wiki" in allow:
        out.add(RAG_KNOWLEDGE)
    if "teacher" in allow:
        out.add(RAG_TEACHER)
    # Phân tích ảnh: luôn cho phép khi thread đã được cấp phép (có filter entry).
    # Không gắn nhóm riêng — vision là core.
    out.add(ANALYZE)
    if "image" in allow:
        out.add(GENERATE)
    return out


def ask_text(intents: set[str] | None = None) -> str:
    intents = intents if intents is not None else ALL_INTENTS
    catalog = {
        RAG_KNOWLEDGE: "📚 Nạp **RAG kiến thức** (tự phát hiện → wiki)",
        RAG_TEACHER: "🎓 Nạp **RAG teacher / SGK** (hỏi lớp + môn)",
        ANALYZE: "🔍 **Phân tích ảnh** (hỏi thêm yêu cầu)",
        GENERATE: "🎨 **Tạo ảnh** từ ảnh này (hỏi thêm mô tả)",
    }
    lines = ["📷 Đã nhận ảnh. Bạn muốn em làm gì?"]
    n = 1
    shown = 0
    for code in INTENT_ORDER:
        if code in intents:
            lines.append(f"{n}️⃣ {catalog[code]}")
            n += 1
            shown += 1
    if not shown:
        return "📷 Đã nhận ảnh nhưng nhóm này không được phép xử lý ảnh."
    lines.append("→ Trả lời số hoặc từ khóa (trong 10 phút).")
    return "\n".join(lines)


# backward compat
ASK = ask_text(ALL_INTENTS)


def parse_intent(text: str, allowed: set[str] | None = None) -> str | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    # keywords
    if any(w in t for w in (
        "kiến thức", "kien thuc", "wiki", "tri thức", "tri thuc", "nạp rag kiến",
        "knowledge",
    )):
        return RAG_KNOWLEDGE
    if any(w in t for w in (
        "teacher", "sgk", "giáo viên", "giao vien", "sách giáo khoa", "sach giao khoa",
    )):
        return RAG_TEACHER
    if any(w in t for w in (
        "phân tích", "phan tich", "mô tả", "mo ta", "ocr", "đọc chữ", "doc chu",
        "ảnh này", "anh nay", "analyze", "describe", "what is",
    )) and not _looks_generate(t):
        return ANALYZE
    if _looks_generate(t):
        return GENERATE

    num_map = {
        "1": 1, "1️⃣": 1, "1.": 1, "1)": 1,
        "2": 2, "2️⃣": 2, "2.": 2, "2)": 2,
        "3": 3, "3️⃣": 3, "3.": 3, "3)": 3,
        "4": 4, "4️⃣": 4, "4.": 4, "4)": 4,
    }
    if t in num_map:
        opts = [c for c in INTENT_ORDER if allowed is None or c in allowed]
        idx = num_map[t] - 1
        if 0 <= idx < len(opts):
            return opts[idx]
    return None


_GEN_KWS = (
    "vẽ", "ve lai", "ve theo", "ve thanh", "tạo ảnh", "tao anh", "tạo hình",
    "tao hinh", "sửa ảnh", "sua anh", "chỉnh ảnh", "chinh anh", "chỉnh sửa",
    "chinh sua", "thay nền", "thay nen", "đổi nền", "doi nen", "xóa nền",
    "xoa nen", "phong cách", "phong cach", "style", "anime", "hoạt hình",
    "hoat hinh", "ghibli", "chibi", "sticker", "logo", "biến thành",
    "bien thanh", "làm thành", "lam thanh", "ghép", "ghep ", "phục chế",
    "phuc che", "làm nét", "lam net", "tô màu", "to mau", "generate", "draw",
    "redraw", "remix", "edit", "img2img",
)


def _looks_generate(t: str) -> bool:
    return any(k in t for k in _GEN_KWS)


def classify(text: str) -> str:
    """Legacy: 'generate' | 'analyze' — dùng khi caption có sẵn (không qua menu)."""
    return GENERATE if _looks_generate((text or "").lower()) else ANALYZE


def needs_prompt(intent: str, text: str = "") -> bool:
    """analyze/generate cần prompt; số menu thuần (1-4) không đủ."""
    t = (text or "").strip()
    if intent == GENERATE:
        # pure number or pure keyword without description
        if not t or t.lower() in {
            "1", "2", "3", "4", "1️⃣", "2️⃣", "3️⃣", "4️⃣",
            "generate", "tạo ảnh", "tao anh", "vẽ", "edit", "img2img",
        }:
            return True
        # only keyword short
        if _looks_generate(t.lower()) and len(t) < 12:
            return True
        return len(t) < 4
    if intent == ANALYZE:
        if not t or t.lower() in {
            "1", "2", "3", "4", "1️⃣", "2️⃣", "3️⃣", "4️⃣",
            "phân tích", "phan tich", "analyze", "mô tả", "mo ta", "ocr",
        }:
            return True
        return False
    return False


def analyze_photo(image_bytes: bytes, prompt: str, *, channel: str = "") -> str:
    """Vision analysis with explicit prompt."""
    from services.agent.branches import branch_model
    from services.agent.runtime import call_model, content_of

    q = (prompt or "").strip() or "Mô tả chi tiết ảnh này bằng tiếng Việt."
    data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": q},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]}]
    _vm = branch_model("vision", channel)
    resp = call_model(_vm, msgs, timeout=180, max_tokens=900)
    if resp.get("error"):
        try:
            from services.notifier import notify_admin
            notify_admin(f"⚠️ Vision (photo) lỗi — model '{_vm}': {str(resp['error'])[:200]}")
        except Exception:
            pass
        # OCR fallback
        try:
            import io
            import pytesseract
            from PIL import Image
            ocr = pytesseract.image_to_string(
                Image.open(io.BytesIO(image_bytes)), lang="vie+eng",
            ).strip()
            if ocr:
                return f"📷 OCR (vision lỗi):\n{ocr[:2000]}"
        except Exception:
            pass
        return f"📷 Em chưa phân tích được ảnh ạ ({str(resp['error'])[:120]})."
    return content_of(resp).strip() or "📷 Em chưa phân tích được ạ."


def generate_from_photo(image_bytes: bytes, prompt: str, *, channel: str = "") -> dict:
    """Img2img qua nhánh image_gen + modalities=['image'] (ảnh nguồn).

    Providers:
      - ChatGPT/Codex pool: ConversationRequest.images ✅
      - gemini-image / custom adapters nhận body.images ✅ (sau fix adapter path)
      - flow thuần text-to-image: có ảnh nguồn → vẫn gửi kèm; solver có thể bỏ qua
    """
    from services.agent.branches import branch_model
    from services.agent.runtime import call_model, content_of, first_image_url

    p = (prompt or "").strip()
    if not p:
        return {"text": "Anh/chị mô tả muốn chỉnh/tạo ảnh thế nào ạ? 🎨"}
    data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()
    model = branch_model("image_gen", channel)
    resp = call_model(
        model,
        [{"role": "user", "content": [
            {"type": "text", "text": p},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
        timeout=320, max_tokens=600, modalities=["image"], channel=channel,
    )
    if resp.get("error"):
        logger.warning("generate_from_photo (%s) lỗi: %s", model, str(resp["error"])[:200])
        return {
            "text": f"Em tạo ảnh bị lỗi 😥 ({str(resp['error'])[:150]}). "
                    "Thử lại hoặc đổi nhánh image_gen (ChatGPT/Gemini image hỗ trợ ảnh nguồn tốt hơn Flow text-only).",
        }
    txt = content_of(resp)
    url = first_image_url(txt)
    out_bytes: bytes | None = None
    if not url:
        m = re.search(r"!\[[^\]]*\]\((data:image/[^;]+;base64,[^)]+)\)", txt or "")
        if m:
            url = m.group(1)
    if url and url.startswith("data:"):
        try:
            from services.protocol.conversation import save_image_bytes
            out_bytes = base64.b64decode(url.split(",", 1)[1])
            url = save_image_bytes(out_bytes)
        except Exception as exc:
            logger.warning("save generated image failed: %s", exc)
            url = None
    if url and not url.startswith(("http://", "https://")):
        from services.config import config as _cfg
        c = _cfg.get()
        base = (str(c.get("base_url") or "").strip()
                or str(c.get("telegram_webhook_url") or "").strip()).rstrip("/") \
            or "http://127.0.0.1:80"
        url = base + (url if url.startswith("/") else "/" + url)
    if url:
        r: dict[str, Any] = {"text": "Đây ạ 🎨", "image_url": url}
        if out_bytes:
            r["image_bytes"] = out_bytes
        return r
    return {
        "text": (txt[:500] if txt and not str(txt).startswith("![") else "")
        or "Em chưa tạo được ảnh, anh/chị mô tả rõ hơn giúp em nhé.",
    }


def ingest_knowledge_from_photo(
    image_bytes: bytes,
    *,
    prompt: str = "",
    who: str = "",
    platform: str = "",
    chat_id: str = "",
    channel: str = "",
) -> dict[str, Any]:
    """Vision mô tả → wiki.ingest (RAG kiến thức)."""
    desc = analyze_photo(
        image_bytes,
        prompt or "Mô tả chi tiết ảnh, nội dung chữ (OCR), đối tượng, ngữ cảnh — tiếng Việt.",
        channel=channel,
    )
    content = f"Nguồn: ảnh gửi chat\n\n## Mô tả ảnh\n\n{desc}"
    try:
        from services.agent import wiki
        r = wiki.ingest(
            content, title="", who=who, source="photo:chat",
            platform=platform, chat_id=chat_id,
        )
        return {
            "ok": bool(r.get("ok")),
            "text": (desc + "\n\n" + (r.get("text") or "")).strip(),
            "error": "" if r.get("ok") else (r.get("text") or "ingest failed"),
        }
    except Exception as exc:
        return {"ok": False, "text": desc, "error": str(exc)}


def ingest_teacher_from_photo(
    image_bytes: bytes,
    *,
    grade: int,
    subject: str,
    name: str = "photo.jpg",
    channel: str = "",
) -> dict[str, Any]:
    """Vision → markdown → teacher SGK import (từ ảnh chụp trang SGK)."""
    import tempfile
    from pathlib import Path

    desc = analyze_photo(
        image_bytes,
        "Đây là trang SGK/bài học. Chép TOÀN BỘ chữ đọc được (OCR) + mô tả hình, "
        "giữ cấu trúc đề mục. Tiếng Việt.",
        channel=channel,
    )
    # Write temp md-like content as fake pdf path won't work for import_sgk_pdf
    # import_sgk_pdf needs PDF path — use import via markdown path if available
    try:
        from services.agent import teacher_workspace as tw
        # Prefer import_sgk_bytes if we make a simple text file — check import_sgk_pdf only accepts pdf
        # Create a minimal PDF wrapper is heavy — write md directly into SGK via internal API
        g = int(grade)
        sub = tw._normalize_subject(subject)
        if g not in tw.GRADES or not sub:
            return {"ok": False, "error": "lớp/môn không hợp lệ", "text": ""}
        tw._ensure_seeded()
        stamp = time.strftime("%Y-%m-%d %H:%M")
        head = f"SGK lớp {g} · {tw.SUBJECT_LABEL[sub]} · ảnh {name}"
        md = f"# {head}\n\n<!-- import photo {stamp} -->\n\n{desc}\n"
        dest = tw._SGK / f"lop{g}" / f"{sub}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tw._lock:
            if dest.exists():
                old = dest.read_text(encoding="utf-8")
                dest.write_text(old.rstrip() + "\n\n" + md, encoding="utf-8")
            else:
                dest.write_text(md, encoding="utf-8")
        return {
            "ok": True,
            "text": (
                f"Đã nạp ảnh vào SGK teacher 🎓\n"
                f"• Lớp **{g}** · **{tw.SUBJECT_LABEL[sub]}**\n"
                f"• `{dest}`\n"
                f"• {len(desc)} ký tự mô tả/OCR"
            ),
        }
    except Exception as exc:
        logger.warning("ingest_teacher_from_photo: %s", exc)
        return {"ok": False, "error": str(exc), "text": ""}
