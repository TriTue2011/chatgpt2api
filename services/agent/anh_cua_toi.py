"""Sổ ảnh THEO TỪNG NGƯỜI — "3 ảnh gần nhất TÔI tạo" phải là ảnh của chính họ.

Vì sao phải có sổ riêng: `save_image_bytes` đặt tên `<epoch>_<md5>.png` và KHÔNG
ghi ai tạo. Cả kho `data/images` là một rổ chung, trong đó có ảnh của người dùng
khác, ảnh snapshot camera do Home Assistant đẩy lên, và ảnh test. Đọc "N tệp mới
nhất" là gửi ảnh của người khác cho người này — hỏng cả về đúng đắn lẫn riêng tư,
mà nhìn từ ngoài thì y như hoạt động bình thường.

Không sửa `save_image_bytes` để nhận user_id vì nó được gọi từ nhiều tầng không
biết người dùng (protocol OpenAI, HA snapshot, test). Nơi BIẾT người dùng là
orchestrator — nên ghi sổ ở đó.

Sổ là JSON phẳng `{user_id: [url mới nhất trước, …]}`, chặn `_MOI_NGUOI` mục mỗi
người. Mất sổ chỉ mất khả năng lọc theo người (rơi về báo "chưa có ảnh nào của
anh/chị"), không mất ảnh — nên không cần bền bằng DB.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

#: Giữ nhiều hơn trần 50 ảnh/lượt để còn chỗ cho các lượt trước.
_MOI_NGUOI = 120
_lock = threading.Lock()


def _duong() -> Path:
    from services.config import DATA_DIR
    return Path(DATA_DIR) / "agent" / "anh_cua_toi.json"


def _doc() -> dict:
    try:
        p = _duong()
        if p.is_file():
            d = json.loads(p.read_text("utf-8") or "{}")
            return d if isinstance(d, dict) else {}
    except Exception as exc:
        logger.warning("anh_cua_toi: đọc sổ lỗi: %s", exc)
    return {}


def ghi(user_id: str, urls: list[str]) -> None:
    """Ghi nhận NGƯỜI NÀY vừa tạo những ảnh này (mới nhất lên đầu)."""
    uid = str(user_id or "").strip()
    if not uid or not urls:
        return
    with _lock:
        d = _doc()
        cu = [u for u in (d.get(uid) or []) if isinstance(u, str)]
        moi = [str(u) for u in urls if u]
        # Ảnh mới lên đầu, bỏ trùng nhưng GIỮ thứ tự — dùng dict.fromkeys thay vì
        # set, vì set làm mất thứ tự và "3 ảnh gần nhất" thành 3 ảnh bất kỳ.
        d[uid] = list(dict.fromkeys(moi + cu))[:_MOI_NGUOI]
        try:
            p = _duong()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
        except Exception as exc:
            logger.warning("anh_cua_toi: ghi sổ lỗi: %s", exc)


def gan_nhat(user_id: str, so: int) -> list[str]:
    """`so` ảnh gần nhất của CHÍNH người này. Rỗng nếu chưa tạo ảnh nào."""
    uid = str(user_id or "").strip()
    if not uid or so < 1:
        return []
    return [u for u in _doc().get(uid) or [] if isinstance(u, str)][:so]
