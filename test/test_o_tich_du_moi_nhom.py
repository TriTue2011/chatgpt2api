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

# Image triển khai KHÔNG chứa mã nguồn web (chỉ có bản đã build), nên trong
# container các bài soi .tsx báo lỗi và trông y như hồi quy thật. Đo 07/08:
# 7 bài lỗi kiểu này làm tổng lỗi nhảy 52 → 59, mất một lúc mới truy ra.
# Bỏ qua khi thiếu nguồn; trên CI có đủ mã nên chúng vẫn chạy như thường.
_CO_NGUON_WEB = _THE.exists()


def _nhom_trong_giao_dien() -> set[str]:
    """Các khoá nhóm khai trong bảng `FUNCTION_GROUPS` của thẻ Lọc thread."""
    src = _THE.read_text(encoding="utf-8")
    m = re.search(r"const FUNCTION_GROUPS:[^=]*=\s*\[(.*?)\n\];", src, re.S)
    if not m:
        raise AssertionError("không tìm thấy bảng FUNCTION_GROUPS — đổi tên rồi?")
    return set(re.findall(r'\[\s*"([a-z_]+)"\s*,', m.group(1)))


@unittest.skipUnless(_CO_NGUON_WEB, "image không có mã nguồn web")
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


@unittest.skipUnless(_CO_NGUON_WEB, "image không có mã nguồn web")
class MoiCongCuDeuCoNhomTests(unittest.TestCase):
    """Tầng dưới ô tích: mọi công cụ của bot phải được gắn vào một nhóm.

    Công cụ vắng trong `_CAP_GROUP` thì `group_of()` trả '_ungrouped', và chốt
    chặn ở orchestrator coi là KHÔNG được phép rồi bỏ qua IM LẶNG. Người dùng
    hỏi mà bot không trả lời, cũng không báo lỗi, dù thread đã bật đúng nhóm —
    đã xảy ra thật 15/07/2026 với các tool Home Assistant.

    Hỏng kiểu này TỆ HƠN thiếu ô tích: thiếu ô tích thì ít ra nhìn màn hình còn
    thấy vắng, còn thiếu nhóm thì không dấu hiệu nào cả.

    Đo 07/08: 70 công cụ, 0 công cụ mồ côi.
    """

    def test_khong_cong_cu_nao_mo_coi(self) -> None:
        from services.agent.capabilities import CAPABILITIES, _CORE_TOOLS, group_of
        mo_coi = sorted(n for n in CAPABILITIES
                        if group_of(n) == "_ungrouped" and n not in _CORE_TOOLS)
        self.assertEqual(mo_coi, [], (
            f"Công cụ {mo_coi} chưa gắn nhóm trong `_CAP_GROUP` → thread có bật "
            f"lọc sẽ bỏ qua chúng IM LẶNG. Thêm nhóm cho từng cái."
        ))

    def test_nhom_cua_cong_cu_deu_co_o_tich(self) -> None:
        """Gắn công cụ vào một nhóm không có ô tích cũng là mồ côi trá hình:
        nhóm đó không bao giờ tick được nên công cụ vĩnh viễn bị chặn."""
        from services.agent.capabilities import CAPABILITIES, _CORE_TOOLS, group_of
        giao_dien = _nhom_trong_giao_dien()
        xau = sorted({group_of(n) for n in CAPABILITIES if n not in _CORE_TOOLS}
                     - giao_dien - {"_ungrouped"})
        self.assertEqual(xau, [], f"nhóm có công cụ nhưng không có ô tích: {xau}")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(_CO_NGUON_WEB, "image không có mã nguồn web")
class BangNhomTrongLocNhatKyTests(unittest.TestCase):
    """«Lọc nhật ký» có bảng 21 nhóm RIÊNG — phải khớp bảng của «Lọc thread».

    Hai bảng lệch nhau thì có nhóm bật được ở «Lọc thread» mà không lọc được ở
    nhật ký (hoặc ngược lại: tick một nhóm không tồn tại, bấm xong chẳng đổi
    gì). Cùng loại hỏng với `office` thiếu ô tích — không tầng nào báo.

    Không gộp làm một bảng vì hai thẻ nằm ở hai tệp khác nhau và không import
    lẫn nhau; bài này là thứ giữ chúng đồng bộ.
    """

    def _bang(self, ten: str, bien: str) -> set:
        src = (_THE.parent / ten).read_text(encoding="utf-8") \
            if _THE.is_file() else (_THE / ten).read_text(encoding="utf-8")
        m = re.search(bien + r"[^=]*=\s*\[(.*?)\n\];", src, re.S)
        self.assertIsNotNone(m, f"{ten}: không tìm thấy {bien}")
        return set(re.findall(r'\[\s*"([a-z_]+)"\s*,', m.group(1)))

    def test_hai_bang_khop_nhau(self):
        loc = self._bang("telegram-cloudflare-card.tsx", "const FUNCTION_GROUPS")
        nk = self._bang("chatlog-settings-card.tsx", "const NHOM_CHUC_NANG")
        self.assertEqual(sorted(loc - nk), [], "nhóm có ở «Lọc thread» mà thiếu ở «Lọc nhật ký»")
        self.assertEqual(sorted(nk - loc), [], "nhóm bịa ở «Lọc nhật ký»")

    def test_khop_luon_may_chu(self):
        from services.agent.capabilities import all_groups
        nk = self._bang("chatlog-settings-card.tsx", "const NHOM_CHUC_NANG")
        self.assertEqual(sorted(set(all_groups()) - nk), [])
