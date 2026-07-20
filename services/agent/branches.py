"""Branch registry — bảng định tuyến nhánh của agent.

Mỗi LOẠI VIỆC (vẽ ảnh, phân tích ảnh, tạo nhạc, tạo video, viết code…) có một
nhánh; mỗi nhánh trỏ tới MỘT model id — có thể là model đơn, combo, hay
pipeline Combo Code. Nhờ đó tái dùng nguyên hạ tầng sẵn có: combo tự chạy
model đầu tiên và tự fallback khi lỗi ("mặc định model đầu, lỗi xoay tiếp").

Quy tắc định tuyến (chống loạn):
  1. Việc thuộc nhánh nào → dùng model của nhánh đó. KHÔNG hỏi lại người dùng.
  2. Chỉ đổi model khi người dùng NÊU RÕ ("vẽ bằng chatgpt", "video đẹp").
  3. Đổi model nhánh = sửa config `agent_branches` (Settings → Telegram/Agent),
     không sửa code.
"""

from __future__ import annotations

from services.config import config

# name -> (label tiếng Việt cho UI/persona, model mặc định khi chưa cấu hình)
BRANCHES: dict[str, tuple[str, str]] = {
    "image_gen":  ("Vẽ / tạo ảnh",        "gma/image"),
    "vision":     ("Phân tích ảnh",        "gma/3.1-pro"),
    "music_gen":  ("Tạo nhạc",             "gma/auto"),
    "video_gen":  ("Tạo video",            "flow/veo-3.1-fast"),
    "code":       ("Viết / sửa code",      "claude/sonnet-5"),
    "code_reviewer": ("Kiểm duyệt code",   ""),  # trống = tắt tầng review
}


def branch_model(name: str, channel: str = "") -> str:
    """Model id của nhánh — ưu tiên cài đặt RIÊNG từng kênh rồi mới tới chung:
    `agent_branches_by_channel.<channel>.<name>` → `agent_branches.<name>` →
    default đăng ký. `channel`: 'tg' | 'zalo' | 'zalop' ('' = client thường:
    tab chat, HA, API ngoài — chỉ dùng cài đặt chung)."""
    c = config.get()
    ch = str(channel or "").strip()
    if ch:
        by = c.get("agent_branches_by_channel")
        entry = by.get(ch) if isinstance(by, dict) else None
        val = str((entry or {}).get(name) or "").strip() if isinstance(entry, dict) else ""
        if val:
            return val
    cfg = c.get("agent_branches") or {}
    val = str(cfg.get(name) or "").strip()
    if val:
        return val
    return BRANCHES.get(name, ("", ""))[1]
