"""Bảng ô tích «Lọc thread» phải đủ MỌI nhóm chức năng của máy chủ.

VÌ SAO CÓ BÀI NÀY — sự cố thật 06/08/2026. Chủ máy hỏi "nhóm office bật chỗ nào,
trên webui tôi không thấy ô tích nhỉ". Đúng là không có: `FUNCTION_GROUPS` trong
`telegram-cloudflare-card.tsx` thiếu `office` và `device`.

Thiếu ô tích KHÔNG phải là "nhóm đó mặc kệ, cứ chạy". Mỗi lần bộ lọc được lưu,
`config._dong_dau_nhom_da_biet` đóng dấu `thread_filter_meta[key]["known"]` =
TOÀN BỘ nhóm phía máy chủ. `capabilities.allowed_groups_for` đọc dấu đó theo
luật: có trong `known` mà không có trong danh sách tick = chủ máy CỐ Ý tắt →
giữ tắt. Nhóm vắng ô tích thì không bao giờ tick được, nên bị khoá VĨNH VIỄN mà
không có đường nào bật lại từ giao diện.

Đo trên máy chủ 06/08: cả 5 thread (2 Zalo cá nhân, Telegram nhóm, Telegram
topic, Zalo Bot) đều chặn `office` → 18 công cụ tài liệu chết ở mọi kênh, kể cả
8 công cụ vừa viết hôm trước.

Đây là kiểu hỏng "một hàm đúng, cắm sai chỗ": phía máy chủ đủ nhóm, phía giao
diện thiếu, và không tầng nào báo lỗi.
"""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

_THE = GOC / "web" / "src" / "app" / "settings" / "components" / "telegram-cloudflare-card.tsx"


def _nhom_trong_giao_dien() -> set[str]:
    """Các khoá nhóm khai trong bảng `FUNCTION_GROUPS` của thẻ Lọc thread."""
    src = _THE.read_text(encoding="utf-8")
    m = re.search(r"const FUNCTION_GROUPS:[^=]*=\s*\[(.*?)\n\];", src, re.S)
    if not m:
        raise AssertionError("không tìm thấy bảng FUNCTION_GROUPS — đổi tên rồi?")
    return set(re.findall(r'\[\s*"([a-z_]+)"\s*,', m.group(1)))


class OTichDuMoiNhomTests(unittest.TestCase):
    def test_giao_dien_khong_thieu_nhom_nao(self) -> None:
        from services.agent.capabilities import all_groups
        may_chu = set(all_groups())
        giao_dien = _nhom_trong_giao_dien()
        thieu = sorted(may_chu - giao_dien)
        self.assertEqual(thieu, [], (
            f"Nhóm {thieu} có ở máy chủ nhưng KHÔNG có ô tích trong «Lọc thread». "
            f"Thêm vào FUNCTION_GROUPS ({_THE.name}) kèm nhãn tiếng Việt — nếu "
            f"không, nhóm này bị khoá vĩnh viễn và không bật lại được từ giao diện."
        ))

    def test_giao_dien_khong_bia_nhom_khong_ton_tai(self) -> None:
        """Ô tích trỏ vào nhóm không có thật thì tick xong chẳng đổi gì —
        im lặng và không cách nào biết, nên chốt luôn chiều ngược lại."""
        from services.agent.capabilities import all_groups
        thua = sorted(_nhom_trong_giao_dien() - set(all_groups()))
        self.assertEqual(thua, [], f"ô tích trỏ vào nhóm không tồn tại: {thua}")


if __name__ == "__main__":
    unittest.main()
