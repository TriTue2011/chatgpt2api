"""Ảnh nhận qua bot → có caption thì LÀM LUÔN, không caption thì HỎI yêu cầu.

Hai ý định (dùng chung Telegram + Zalo):
- 'analyze'  — mô tả/phân tích/OCR ảnh (nhánh vision, không thuộc nhóm lọc nào).
- 'generate' — tạo/chỉnh ảnh MỚI dựa trên ảnh đính kèm (img2img — gateway đã
  hỗ trợ ảnh nguồn qua content part image_url trong image_chat). Thuộc nhóm
  lọc 'image': thread bị lọc thiếu nhóm này → bot BỎ QUA im lặng.

Ảnh không caption được xếp hàng chờ theo (bot, chat) — tin nhắn text kế tiếp
của thread đó được coi là yêu cầu cho ảnh (TTL 10 phút), giống pdf_intent.
"""
from __future__ import annotations

import base64
import logging
import os
import tempfile
import threading
import time

logger = logging.getLogger(__name__)

_pending: dict[str, dict] = {}
_lock = threading.Lock()
_TTL = 600  # ảnh chờ tối đa 10 phút


def _gc() -> None:
    now = time.time()
    for k in [k for k, v in _pending.items() if now - v["ts"] > _TTL]:
        v = _pending.pop(k, None)
        if v:
            try:
                os.unlink(v["path"])
            except Exception:
                pass


def set_pending(key: str, image_bytes: bytes) -> None:
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
        _pending[key] = {"path": tmp.name, "ts": time.time()}
        _gc()


def has_pending(key: str) -> bool:
    with _lock:
        _gc()
        return key in _pending


def pop_pending(key: str) -> bytes | None:
    """Lấy ảnh chờ (bytes) và xóa file tạm. None nếu hết hạn/không có."""
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


ASK = ("📷 Đã nhận ảnh. Bạn muốn em làm gì với ảnh này?\n"
       "• Phân tích / mô tả / đọc chữ trong ảnh — vd: 'mô tả', 'ảnh này là gì'\n"
       "• Tạo ảnh mới từ ảnh này — vd: 'vẽ lại phong cách hoạt hình', 'đổi nền bãi biển'\n"
       "→ Trả lời trong 10 phút nhé.")


# Từ khóa nhận diện yêu cầu TẠO/CHỈNH ảnh (đối chiếu bản đã hạ dấu lẫn bản gốc).
_GEN_KWS = (
    "vẽ", "ve lai", "ve theo", "ve thanh", "tạo ảnh", "tao anh", "tạo hình",
    "tao hinh", "sửa ảnh", "sua anh", "chỉnh ảnh", "chinh anh", "chỉnh sửa",
    "chinh sua", "thay nền", "thay nen", "đổi nền", "doi nen", "xóa nền",
    "xoa nen", "phong cách", "phong cach", "style", "anime", "hoạt hình",
    "hoat hinh", "ghibli", "chibi", "sticker", "logo", "biến thành",
    "bien thanh", "làm thành", "lam thanh", "ghép", "ghep ", "phục chế",
    "phuc che", "làm nét", "lam net", "tô màu", "to mau", "generate", "draw",
    "redraw", "remix", "edit",
)


def classify(text: str) -> str:
    """Phân loại yêu cầu đi kèm ảnh: 'generate' (tạo/chỉnh ảnh) | 'analyze'.
    Mặc định 'analyze' — hỏi han/mô tả/OCR là trường hợp phổ biến nhất."""
    t = (text or "").strip().lower()
    return "generate" if any(k in t for k in _GEN_KWS) else "analyze"


def generate_from_photo(image_bytes: bytes, prompt: str) -> dict:
    """Tạo ảnh mới từ ảnh đính kèm + mô tả (img2img qua nhánh image_gen).

    BẮT BUỘC gửi modalities=['image'] để gateway đi pipeline image_chat
    (hỗ trợ ảnh NGUỒN) — dispatch thường coi message kèm ảnh là vision chat
    và model chỉ trả lời bằng chữ ("chưa có công cụ tạo ảnh").
    Trả {'text', 'image_url'?} như capability generate_image."""
    import re as _re
    from services.agent.branches import branch_model
    from services.agent.runtime import call_model, content_of, first_image_url
    data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()
    model = branch_model("image_gen")
    resp = call_model(model, [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]}], timeout=320, max_tokens=600, modalities=["image"])
    if resp.get("error"):
        logger.warning("generate_from_photo (%s) lỗi: %s", model, str(resp["error"])[:200])
        return {"text": f"Em tạo ảnh bị lỗi 😥 ({str(resp['error'])[:150]}). "
                        "Anh/chị thử lại hoặc mô tả khác giúp em nhé."}
    txt = content_of(resp)
    url = first_image_url(txt)
    out_bytes: bytes | None = None
    if not url:
        # Pipeline ảnh có thể trả data-URI base64 inline thay vì link http.
        m = _re.search(r"!\[[^\]]*\]\((data:image/[^;]+;base64,[^)]+)\)", txt)
        if m:
            url = m.group(1)
    if url and url.startswith("data:"):
        # Zalo sendPhoto cần URL http công khai (server Zalo tự tải) → lưu
        # data-URI thành file trong kho /images/ rồi dùng link đó. Giữ bytes
        # để Telegram upload multipart trực tiếp (chắc chắn ra ẢNH).
        try:
            from services.protocol.conversation import save_image_bytes
            out_bytes = base64.b64decode(url.split(",", 1)[1])
            url = save_image_bytes(out_bytes)
        except Exception as exc:
            logger.warning("save generated image failed: %s", exc)
            url = None
    if url and not url.startswith(("http://", "https://")):
        # base_url có thể rỗng → save_image_bytes trả đường dẫn tương đối.
        # Zalo cần domain công khai (Cloudflare của webhook Telegram); không
        # có thì dùng localhost để ít nhất Telegram tự tải bytes gửi đi được.
        from services.config import config as _cfg
        c = _cfg.get()
        base = (str(c.get("base_url") or "").strip()
                or str(c.get("telegram_webhook_url") or "").strip()).rstrip("/") \
            or "http://127.0.0.1:80"
        url = base + (url if url.startswith("/") else "/" + url)
    if url:
        r = {"text": "Đây ạ 🎨", "image_url": url}
        if out_bytes:
            r["image_bytes"] = out_bytes
        return r
    return {"text": (txt[:500] if txt and not txt.startswith("![") else "")
            or "Em chưa tạo được ảnh, anh/chị mô tả rõ hơn giúp em nhé."}
