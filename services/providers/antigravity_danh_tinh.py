"""Danh tính DUY NHẤT c2a khai với Google ở mọi bước Antigravity (lấy mã dự án, hỏi danh sách model, gọi model).

Chủ máy 06/10/2026: "làm cho User-Agent khớp giữa lúc lấy token và lúc gọi API giống như lấy retoken flow". Trước
đó cùng một tài khoản khai BA danh tính: loadCodeAssist tự xưng `google-api-nodejs-client` + `vscode_cloudshelleditor`,
gọi model lại xưng `antigravity/…` — đúng kiểu lệch 9router ghi nhận làm Google gắn cờ tài khoản (decolua/9router
#1226). Ở đây chỉ làm c2a TỰ NHẤT QUÁN; không sao chép dấu vân tay ẩn của ứng dụng chính thức (enum, TLS).
"""
from __future__ import annotations

import json

USER_AGENT = "antigravity/1.107.0 Windows/x64"
METADATA = {"ideType": "IDE_UNSPECIFIED", "platform": "PLATFORM_UNSPECIFIED", "pluginType": "GEMINI"}


def tieu_de(access_token: str, **them: str) -> dict[str, str]:
    """Tiêu đề chung cho mọi lời gọi cloudcode-pa của một tài khoản."""
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json",
            "User-Agent": USER_AGENT, "Client-Metadata": json.dumps(METADATA), "x-request-source": "local", **them}
