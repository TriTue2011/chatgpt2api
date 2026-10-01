"""Gọi API C2A để đẩy tin cảnh báo chủ động ra Zalo.

Dùng kênh **Zalo Cá Nhân** (`POST /api/zalo-personal/test-send`), auth bằng
admin API key tĩnh (`Authorization: Bearer <C2A_AUTH_KEY>`) — KHÔNG cần đăng
nhập/JWT. KHÔNG dùng kênh Bot API chính thức (`/api/zalo-bot/send`): C2A chạy
song song 2 kênh Zalo tách biệt hoàn toàn, không chia sẻ token/trạng thái
(xem api/zalo_bot.py docstring trên C2A) — chủ máy chat hàng ngày với
chi-tieu-bot qua Zalo Cá Nhân, không phải bot chính thức, nên cảnh báo phải
đi đúng kênh đó mới tới người.
Xem CLAUDE.md mục "Ràng buộc kiến trúc" để biết vì sao chọn đường API tĩnh.
"""
from __future__ import annotations

import time

import httpx

from app.config import C2A_AUTH_KEY, C2A_BASE_URL, C2A_ZALO_PERSONAL_THREAD_ID

# Ghim "auto:text" thay vì bỏ trống `model` (phát hiện 23/09/2026): C2A coi
# request KHÔNG có model là câu trả lời cho loa Home Assistant
# (_wants_verbalize(None) == True) -> services/verbalize.py xoá | ** # →,
# đổi "%" thành "phần trăm" -- câu trả lời "Hỏi AI phân tích" trên /ui dính
# thành 1 khối. Hậu tố ":text" chỉ tắt bước đó; định tuyến vẫn là "auto" y
# như cũ (_strip_marker("auto:text") == "auto").
MODEL_HOI_AI = "auto:text"
# Kho ký ức riêng trên C2A (admin:chi-tieu-bot-ui) -- không gửi `user` thì mọi
# lượt hỏi của /ui rơi vào kho admin chung 'chatgpt2api' và có thể bị chèn lại
# vào cuộc chat admin khác (cùng họ lỗi "ký ức C2A tự bịa số liệu" 22/09).
USER_KHO_KY_UC = "chi-tieu-bot-ui"
# /ui đi qua Cloudflare Tunnel, Cloudflare cắt request sau ~100s (lỗi 524) --
# lần thử + retry chung 1 ngân sách. Retry chỉ khi còn đủ cho 1 lượt trả lời
# thường (đo thật 23/09/2026: 14-17s/lượt, lượt chậm ~40s).
TONG_THOI_GIAN_HOI_AI = 95.0
THOI_GIAN_TOI_THIEU_DE_RETRY = 30.0
_dong_ho = time.monotonic  # tách ra để test giả lập thời gian trôi


async def gui_canh_bao(text: str) -> dict:
    if not C2A_AUTH_KEY:
        raise RuntimeError(
            "C2A_AUTH_KEY chưa cấu hình trong .env — không gửi được cảnh báo. "
            "Lấy key ở C2A Settings -> Bảo mật -> API Key quản trị."
        )
    if not C2A_ZALO_PERSONAL_THREAD_ID:
        raise RuntimeError(
            "C2A_ZALO_PERSONAL_THREAD_ID chưa cấu hình trong .env — không biết "
            "gửi cảnh báo tới thread Zalo Cá Nhân nào. Xem README mục Deploy."
        )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{C2A_BASE_URL}/api/zalo-personal/test-send",
            json={"thread_id": C2A_ZALO_PERSONAL_THREAD_ID, "text": text, "type": 0},
            headers={"Authorization": f"Bearer {C2A_AUTH_KEY}"},
        )
        resp.raise_for_status()
        return resp.json()


async def hoi_ai_phan_tich(prompt: str) -> str:
    """POST /v1/chat/completions qua chính C2A, trả về nội dung text AI trả
    lời. Auth giống hệt gui_canh_bao (Bearer C2A_AUTH_KEY tĩnh, KHÔNG cần key
    riêng). Gửi model MODEL_HOI_AI + user USER_KHO_KY_UC (lý do: xem chú
    thích 2 hằng số) -- vẫn "auto" route như đường Zalo. Timeout dài hơn
    gui_canh_bao vì đây là LLM thật, có thể mất vài giây.

    Retry 1 lần nếu C2A trả 5xx (KHÔNG retry 4xx -- lỗi request thì gọi lại y
    hệt cũng lỗi y hệt). Phát hiện 22/09/2026: "auto" model routing của C2A
    thỉnh thoảng 502 chập chờn, gọi lại NGAY với cùng prompt thường thành
    công (đo thật: 502 sau 37s, gọi lại thành công sau 17s) -- không sửa được
    phía C2A nên tự retry ở đây thay vì bắt người dùng bấm "thử lại" trên /ui.
    """
    if not C2A_AUTH_KEY:
        raise RuntimeError(
            "C2A_AUTH_KEY chưa cấu hình trong .env — không hỏi AI được. "
            "Lấy key ở C2A Settings -> Bảo mật -> API Key quản trị."
        )
    han_chot = _dong_ho() + TONG_THOI_GIAN_HOI_AI
    async with httpx.AsyncClient() as client:
        so_lan_thu = 2  # 1 lần thử + 1 lần retry, xem docstring ở trên
        for lan in range(so_lan_thu):
            resp = await client.post(
                f"{C2A_BASE_URL}/v1/chat/completions",
                json={
                    "model": MODEL_HOI_AI,
                    "user": USER_KHO_KY_UC,
                    # "Lượt gọi TÁCH BIỆT" của C2A (_tach_biet/_thread_denies):
                    # không nhánh vẽ ảnh/video/nhạc/code, không chèn tài liệu
                    # tra cứu. Thiếu nó, "auto" từng đọc "trả về 1" (bỏ dấu:
                    # "tra ve 1") thành "vẽ 1" -> vẽ ảnh 83s (23/09/2026).
                    "x_allowed_groups": [],
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                headers={"Authorization": f"Bearer {C2A_AUTH_KEY}"},
                timeout=max(han_chot - _dong_ho(), 1.0),
            )
            if (resp.status_code < 500 or lan == so_lan_thu - 1
                    or han_chot - _dong_ho() < THOI_GIAN_TOI_THIEU_DE_RETRY):
                break
        resp.raise_for_status()
        data = resp.json()
        noi_dung = data["choices"][0]["message"]["content"]
        if not isinstance(noi_dung, str) or not noi_dung:
            # content null/missing (json None) hoặc chuỗi rỗng -- ép raise để
            # đi vào đúng nhánh lỗi 502 sẵn có ở app/web.py, tránh hiện chữ
            # "null" hoặc kết quả trống lặng lẽ trên /ui.
            raise RuntimeError("C2A trả về nội dung rỗng hoặc không hợp lệ")
        return noi_dung
