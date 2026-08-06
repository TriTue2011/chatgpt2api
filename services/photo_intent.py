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
# Nhãn loại tài liệu — soi chiếu `sgk_taphuan.DOC_KIND_LABEL` chứ không giữ bảng
# thứ hai: hai bảng song song là lý do thêm loại một chỗ mà chỗ kia vẫn nhãn cũ.
try:  # pragma: no cover — import vòng thì rơi về bảng tối thiểu
    from services.agent.sgk_taphuan import DOC_KIND_LABEL as _KIND_LABEL
except Exception:  # noqa: BLE001
    _KIND_LABEL = {"sgk": "SGK", "sgv": "SGV", "vbt": "VBT/SBT",
                   "tap_huan": "Tài liệu tập huấn"}

ASK_TEACHER = (
    "📚 Nạp ảnh vào **RAG teacher / SGK**\n"
    "Cho em **lớp** (1–12) và **môn**.\n"
    "Môn: toán · tiếng việt · ngữ văn · tiếng anh · lịch sử và địa lí · "
    "lịch sử · địa lí · lí · hoá · sinh\n"
    "Ví dụ: `5 toán` · `lớp 2 tiếng việt` · `lớp 10 hoá`\n"
    "Thêm được **loại** và **tập** — không nói thì mặc định sách giáo khoa:\n"
    "`lớp 4 sgv toán` · `lớp 4 vở bài tập toán` · `lớp 2 tiếng việt tập hai`\n"
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


# ── Bot đang chờ NGƯỜI DÙNG gửi ảnh ────────────────────────────────────────
# Khác `_pending` (bot giữ ảnh, chờ người chọn làm gì): đây là chiều ngược lại —
# bot vừa nói "gửi ảnh đi" và đang đợi ảnh tới.
#
# Cần vì trong nhóm bot chỉ nghe khi được tag. Người dùng tag bot hỏi "phân tích
# ảnh", bot xin ảnh, rồi họ gửi ảnh KHÔNG tag — ảnh tới máy chủ nhưng bị cổng
# chặn-nếu-không-tag loại ngay, không có lời gọi vision nào. Đo thật trên máy chủ
# 06/08 lúc 07:07: log có `msgType: 'chat.photo'` kèm đường dẫn ảnh, rồi im bặt.
_CHO_ANH_TTL = 300.0      # 5 phút: xin ảnh xong mà 5 phút chưa gửi thì coi như thôi
_cho_anh: dict[str, float] = {}

#: Câu bot nói khi cần ảnh. Khớp thì bật cờ chờ. Viết KHÔNG DẤU vì so sau khi bỏ
#: dấu — mô hình có lúc trả lời thiếu dấu.
_XIN_ANH_RE = re.compile(
    r"(gui|dua|cho).{0,12}(anh|hinh|link anh)|anh.{0,10}(muon|can).{0,10}phan tich",
    re.IGNORECASE)


def _bo_dau_anh(s: str) -> str:
    import unicodedata
    s = str(s or "").replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(c))


def danh_dau_neu_xin_anh(key: str, reply: str) -> bool:
    """Bot vừa nói câu xin ảnh → ghi nhận đang chờ ảnh của ĐÚNG người đó."""
    if not key or not _XIN_ANH_RE.search(_bo_dau_anh(reply)):
        return False
    _cho_anh[str(key)] = time.time()
    return True


def dang_cho_anh(key: str) -> bool:
    t = _cho_anh.get(str(key))
    if not t:
        return False
    if time.time() - t > _CHO_ANH_TTL:
        _cho_anh.pop(str(key), None)
        return False
    return True


def het_cho_anh(key: str) -> None:
    _cho_anh.pop(str(key), None)


# ── Nhớ ảnh vừa gửi trong nhóm, kể cả khi cổng tag đã loại nó ────────────────
# Đo thật trên máy chủ 06/08 lúc 11:43–11:45 (nhóm Homeassistant): chủ máy tag
# bot, 17 giây sau gửi ảnh KHÔNG tag, rồi tag lại "mô tả ảnh". Ảnh tới nơi đầy
# đủ (`msgType: 'chat.photo'` + href) nhưng bị cổng "trong nhóm phải tag bot"
# loại — và loại IM LẶNG, vì dòng log báo điều đó nằm ở mức INFO trong khi logger
# của module đang ở mức WARNING. Ba câu tag sau đó chỉ nhận lời chào chung.
#
# Zalo không cho vừa tag vừa đính ảnh trong một tin, nên "tag rồi gửi ảnh" là
# cách người ta buộc phải làm. Vì vậy: NHỚ đường dẫn ảnh của thread (chỉ đường
# dẫn, không tải về — không tốn băng thông, không giữ ảnh của người lạ), để câu
# tag ngay sau đó còn dùng được.
_ANH_GAN_DAY_TTL = 600.0     # 10 phút
_anh_gan_day: dict[str, tuple[str, float]] = {}


def nho_anh_gan_day(khoa_thread: str, url: str) -> None:
    """Ghi nhận ảnh vừa xuất hiện trong thread. Gọi TRƯỚC cổng tag."""
    if khoa_thread and url:
        _anh_gan_day[str(khoa_thread)] = (str(url), time.time())


def lay_anh_gan_day(khoa_thread: str) -> str:
    """Đường dẫn ảnh gần nhất còn hạn của thread. '' nếu không có."""
    v = _anh_gan_day.get(str(khoa_thread))
    if not v:
        return ""
    url, t = v
    if time.time() - t > _ANH_GAN_DAY_TTL:
        _anh_gan_day.pop(str(khoa_thread), None)
        return ""
    return url


def quen_anh_gan_day(khoa_thread: str) -> None:
    _anh_gan_day.pop(str(khoa_thread), None)


#: Câu hỏi VỀ ẢNH mà không kèm ảnh — "mô tả ảnh", "ảnh này là gì", "xem ảnh"…
#: So sau khi bỏ dấu. Cố ý HẸP: chỉ nhận câu thật sự nói về ảnh, vì nhận rộng là
#: mọi câu có chữ "ảnh" đều lôi tấm ảnh cũ ra phân tích.
_HOI_VE_ANH_RE = re.compile(
    r"\b(mo ta|phan tich|xem|doc|dich|nhin|kiem tra|giai|nay la gi|la gi|co gi)\b"
    r"[^.!?]{0,20}\b(anh|hinh|tam anh|buc anh|tam hinh)\b"
    r"|\b(anh|hinh|tam anh|buc anh|tam hinh)\b[^.!?]{0,20}"
    r"\b(nay|tren|vua gui|do)\b",
    re.IGNORECASE)


def hoi_ve_anh(text: str) -> bool:
    """Câu này có phải đang hỏi về một tấm ảnh không?"""
    t = _bo_dau_anh(str(text or "")).lower().strip()
    if not t:
        return False
    return bool(_HOI_VE_ANH_RE.search(t))


#: Chuỗi tag người dùng gõ để gọi bot: '@BenBap', '@Botmitbap'…
_TAG_RE = re.compile(r"@[^\s@]{1,32}")


def bo_tag(text: str) -> str:
    """Bỏ phần tag bot khỏi lời kèm ảnh, trả phần chữ THẬT sự có nội dung.

    Trong nhóm phải tag bot mới gọi được nó, nên lời kèm ảnh gần như luôn mở đầu
    bằng '@TenBot'. Nếu không bóc ra thì lời kèm không bao giờ rỗng, và nhánh
    "chưa nói gì → hiện menu" không bao giờ chạy: tag bot rồi gửi ảnh suông là bị
    đoán bừa thành «phân tích ảnh» thay vì được hỏi muốn làm gì.

    Đo thật 05/08: chủ máy tag bot kèm ảnh, hệ thống gửi lên model đúng một chuỗi
    "@Botmitbap" làm yêu cầu phân tích.
    """
    return _TAG_RE.sub(" ", str(text or "")).strip()


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
            # "1." chứ không phải keycap "1️⃣" — xem chú thích ở `pdf_intent.ask_text`.
            lines.append(f"{n}. {catalog[code]}")
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


def prepare_incoming(image_bytes: bytes | None) -> tuple[bytes | None, str]:
    """Ảnh vừa tải từ bot → (bytes chuẩn hoá, "") hoặc (None, câu báo lỗi).

    Gọi NGAY sau khi tải ảnh về: ảnh iPhone (HEIC) được chuyển sang JPEG một lần
    tại đây, còn ảnh hỏng thì báo liền cho người dùng thay vì để họ chọn menu,
    chờ vision, rồi mới nhận lỗi.
    """
    from services.image_utils import UnsupportedImage, normalize
    try:
        data, _mime = normalize(image_bytes)
        return data, ""
    except UnsupportedImage as exc:
        logger.warning("prepare_incoming: %s", exc)
        return None, bad_image_reply(exc)
    except Exception as exc:  # Pillow lỗi lạ → cứ để bytes gốc đi tiếp
        logger.warning("prepare_incoming: lỗi không ngờ %s", str(exc)[:150])
        return image_bytes, ""


def bad_image_reply(exc: Exception) -> str:
    """Câu trả lời khi ảnh không đọc được — nói rõ định dạng, khỏi gọi model."""
    from services.image_utils import UnsupportedImage
    label = getattr(exc, "label", "") if isinstance(exc, UnsupportedImage) else ""
    return (
        f"📷 Ảnh này em chưa mở được: {label or 'không nhận dạng được định dạng'}.\n"
        "Anh/chị chụp lại hoặc gửi dạng JPG / PNG giúp em nhé "
        "(iPhone: Cài đặt → Camera → Định dạng → 'Tương thích nhất')."
    )


def analyze_photo(image_bytes: bytes, prompt: str, *, channel: str = "") -> str:
    """Vision analysis with explicit prompt."""
    from services.agent.branches import branch_model
    from services.agent.runtime import call_model, content_of
    from services.image_utils import UnsupportedImage, normalize

    q = (prompt or "").strip() or "Mô tả chi tiết ảnh này bằng tiếng Việt."
    # NEO NGÔN NGỮ: model vision hay rò tiếng Trung/Nhật khi prompt không chốt
    # ngôn ngữ (đo thật 31/07: "mô tả ảnh và tóm tắt" → trả lời TOÀN tiếng Trung).
    # Ép trả lời đúng ngôn ngữ người dùng — mặc định tiếng Việt trừ khi chính câu
    # hỏi dùng ngôn ngữ khác.
    q = ("[Trả lời HOÀN TOÀN bằng tiếng Việt, trừ khi câu hỏi bên dưới dùng ngôn "
         "ngữ khác thì theo ngôn ngữ đó. TUYỆT ĐỐI KHÔNG chèn chữ Trung/Nhật/Hàn "
         "nếu người dùng không dùng.]\n\n" + q)
    # Chuẩn hoá TRƯỚC khi gọi model: ảnh HEIC/JXL/tải hỏng mà lọt xuống provider
    # thì provider nào cũng chết y hệt → combo đốt sạch đường rồi báo "cạn provider".
    try:
        image_bytes, mime = normalize(image_bytes)
    except UnsupportedImage as exc:
        logger.warning("analyze_photo: %s", exc)
        return bad_image_reply(exc)
    data_url = f"data:{mime};base64," + base64.b64encode(image_bytes).decode()
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
    from services.image_utils import UnsupportedImage, normalize

    p = (prompt or "").strip()
    if not p:
        return {"text": "Anh/chị mô tả muốn chỉnh/tạo ảnh thế nào ạ? 🎨"}
    try:
        image_bytes, mime = normalize(image_bytes)
    except UnsupportedImage as exc:
        logger.warning("generate_from_photo: %s", exc)
        return {"text": bad_image_reply(exc)}
    data_url = f"data:{mime};base64," + base64.b64encode(image_bytes).decode()
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
        # Fallback 1: Tìm base64 data URL trong markdown image syntax
        m = re.search(r"!\[[^\]]*\]\((data:image/[^;]+;base64,[^)]+)\)", txt or "")
        if m:
            url = m.group(1)
    if not url and txt:
        # MỚI: Fallback 2 — Tìm plain HTTP(S) URL trong text (provider response)
        plain_url_m = re.search(r"(https?://[^\s\)\"',<>]+\.(png|jpg|jpeg|webp|gif))(?:[\"'<>\s,)]|$)", txt, re.IGNORECASE)
        if plain_url_m:
            url = plain_url_m.group(1)
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
    from services import ocr_rules

    # Đây là việc MÔ TẢ ảnh, không phải OCR chặt như ingest_teacher_from_photo —
    # nên không áp cả bộ quy tắc. Nhưng lá chắn injection thì phải có: nội dung
    # ảnh đi thẳng vào wiki.ingest, và một ảnh chụp dòng chữ "bỏ qua hướng dẫn
    # trên" không được phép điều khiển đường nạp.
    desc = analyze_photo(
        image_bytes,
        (prompt or "Mô tả chi tiết ảnh, nội dung chữ (OCR), đối tượng, ngữ cảnh "
                   "— tiếng Việt.")
        + "\n\n" + ocr_rules.INJECTION_GUARD,
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
    kind: str = "sgk",
    caption: str = "",
) -> dict[str, Any]:
    """Vision → markdown → nạp vào ĐÚNG kho theo loại + đẩy vào RAG.

    ``kind``: sgk (mặc định) | sgv | vbt | tap_huan. Ảnh chụp một trang sách
    giáo viên gửi vào mà không khai loại thì lời hướng dẫn dạy nằm trong kho nội
    dung học sinh, rồi ``ask_sgk`` đọc nó ra như thể học sinh phải học — đúng lỗi
    đã phải vá ở đường crawl và đường tải lên.

    ``caption``: lời kèm ảnh, dùng để suy TẬP ("tập hai"). Không suy được thì để
    trống, KHÔNG đoán: gắn "tập một" cho trang thuộc tập hai là lọc theo tập sẽ
    trả sai tập mà không có gì báo.
    """
    import tempfile
    from pathlib import Path

    from services import ocr_rules

    # Dùng CHUNG quy tắc OCR với pdf_to_word và sgk_taphuan (services/ocr_rules).
    # Trước đây đây là prompt OCR thứ BA của dự án, chỉ một dòng — thiếu ký hiệu
    # toán (ảnh trang Toán/Hoá chụp gửi vào sẽ mất số mũ, chỉ số dưới), thiếu dấu
    # [không đọc được] (ảnh chụp bằng điện thoại rất hay mờ một góc, model sẽ
    # đoán cho trôi chảy), và thiếu lá chắn prompt injection.
    #
    # math="unicode" chứ KHÔNG phải latex: `desc` còn được trả THẲNG vào tin nhắn
    # Zalo/Telegram cho người gửi đọc (xem giá trị "text" trả về), mà "$x^2$"
    # trong tin nhắn thì không ai đọc được.
    desc = analyze_photo(
        image_bytes,
        "Đây là ảnh chụp một trang sách giáo khoa / bài học. Chép TOÀN BỘ nội "
        "dung trang thành Markdown tiếng Việt.\n\n"
        + ocr_rules.rules(math=ocr_rules.MATH_UNICODE),
        channel=channel,
    )
    if ocr_rules.looks_degenerate(desc):
        # Lặp vòng: dài mà rỗng nghĩa. Ở đây nó sẽ vào thẳng file .md của SGK và
        # kho RAG, nên KHÔNG nhận — báo lại để người gửi chụp lại rõ hơn.
        return {"ok": False, "text": "",
                "error": "OCR ảnh bị lặp vòng — chụp lại rõ hơn giúp em nhé "
                         "(đủ sáng, thẳng trang, không loá)."}
    try:
        from services.agent import teacher_workspace as tw
        g = int(grade)
        sub = tw._normalize_subject(subject)
        if g not in tw.GRADES or not sub:
            return {"ok": False, "error": "lớp/môn không hợp lệ", "text": ""}
        k = str(kind or "sgk").strip().lower() or "sgk"
        tw._ensure_seeded()
        stamp = time.strftime("%Y-%m-%d %H:%M")
        nhan_loai = _KIND_LABEL.get(k, "Tài liệu")
        head = f"{nhan_loai} lớp {g} · {tw.SUBJECT_LABEL[sub]} · ảnh {name}"
        md = f"# {head}\n\n<!-- import photo {stamp} -->\n\n{desc}\n"

        # Ghi .md CHỈ cho sách học sinh: `search_sgk` đọc các file đó và không
        # phân biệt loại, nên nhét ảnh trang SGV vào đấy là trả lời trộn.
        dest = None
        if k == "sgk":
            dest = tw._SGK / f"lop{g}" / f"{sub}.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tw._lock:
                if dest.exists():
                    old = dest.read_text(encoding="utf-8")
                    dest.write_text(old.rstrip() + "\n\n" + md, encoding="utf-8")
                else:
                    dest.write_text(md, encoding="utf-8")

        # ĐẨY VÀO RAG — đây là phần trước đây KHÔNG hề có.
        #
        # Bản cũ chỉ ghi .md rồi báo "Đã nạp ảnh vào SGK teacher 🎓". Nhưng .md chỉ
        # được `search_sgk` (khớp từ khoá, đường offline) đọc; còn `ask_sgk` của
        # MCP hub — thứ mà bài giảng, bài tập ba mức và mọi câu hỏi qua bot dùng —
        # đọc kho vector. Nên ảnh trang sách gửi qua Zalo/Telegram vào rồi mà bot
        # KHÔNG BAO GIỜ tìm ra, trong khi tin nhắn đã báo thành công. Người gửi
        # không có cách nào biết.
        from services.agent import sgk_fetch as _sf
        rag = tw.push_sgk_to_rag(
            md, title=head, grade=g, subject=sub,
            source=f"photo/{name}",
            collection=_sf.KIND_COLLECTION.get(k, "kb_giao_duc"),
            volume=tw.detect_volume(caption or head),
            kind=k,
        )
        so_doan = int((rag or {}).get("chunks_added") or 0)
        dong = [f"Đã nạp ảnh vào kho {nhan_loai} 🎓",
                f"• Lớp **{g}** · **{tw.SUBJECT_LABEL[sub]}**"]
        if dest is not None:
            dong.append(f"• `{dest}`")
        dong.append(f"• {len(desc)} ký tự mô tả/OCR")
        # Nói rõ RAG có nhận hay không: đây là điều kiện để bot tra ra được, mà
        # trước đây tin nhắn không hề nhắc tới.
        dong.append(f"• RAG: **{so_doan} đoạn** vào `{(rag or {}).get('collection')}`"
                    if so_doan > 0 else
                    f"• ⚠️ RAG chưa nhận ({str((rag or {}).get('errors') or (rag or {}).get('error') or 'không rõ')[:100]}) "
                    f"— bot có thể chưa tra ra ảnh này")
        return {"ok": True, "text": "\n".join(dong), "rag": rag}
    except Exception as exc:
        logger.warning("ingest_teacher_from_photo: %s", exc)
        return {"ok": False, "error": str(exc), "text": ""}
