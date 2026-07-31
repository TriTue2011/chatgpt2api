"""Nhóm chức năng THÊM SAU không được coi là "người dùng đã tắt".

Bộ lọc thread (`thread_filters`) là ảnh chụp các ô đã tick VÀO LÚC LƯU. Không có
mốc "lúc đó hệ thống biết những nhóm nào" thì một nhóm mới thêm vào code không
phân biệt được với nhóm người dùng CỐ Ý tắt, và `allowed_groups_for()` buộc phải
chọn một trong hai cách sai:

  * chặn oan nhóm mới  → tool bị ẩn, và với thread có lọc thì bot IM LẶNG hoàn
    toàn, nhìn từ ngoài không phân biệt được với hỏng;
  * bật lại mọi nhóm  → bật lại đúng nhóm người dùng vừa tắt.

Đo thật trên máy chủ 01/08: cả 4 thread có lọc đều thiếu `device`, `office`,
`tts_reply` — 9 tool Office chết trên chính những kênh đang dùng thật, và một
lượt "Tắt laptop của tôi" trên Zalo cá nhân bị chặn, trả về câu RỖNG.

Cách chữa: `thread_filter_meta[key]["known"]` đóng dấu danh sách nhóm đã tồn tại
lúc lưu. Vắng khỏi `known` = chưa từng được hỏi ý → cho phép. Có trong `known`
mà không được tick = cố ý tắt → giữ tắt.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import config as config_mod
from services.agent import capabilities as caps

# Danh sách nhóm giả, cố định — test không được đổi kết quả khi ai đó thêm
# capability mới vào dự án.
NHOM = ["device", "image", "office", "tts_reply", "video", "web"]


def _allow(filters: dict, meta: dict) -> set[str] | None:
    cfg = {"thread_filters": filters, "thread_filter_meta": meta}
    with patch("services.config.config.get", return_value=cfg), \
         patch.object(caps, "all_groups", return_value=list(NHOM)):
        return caps.allowed_groups_for("t1")


class TestNhomMoiKhongBiChanOan(unittest.TestCase):
    def test_ban_ghi_cu_khong_co_known(self):
        """Bản ghi lưu trước khi có cơ chế này: mọi nhóm chưa tick đều là nhóm
        chưa từng được hỏi ý, nên phải cho phép hết."""
        self.assertEqual(
            _allow({"t1": ["image", "video", "web"]}, {"t1": {"kind": "user"}}),
            {"image", "video", "web", "device", "office", "tts_reply"})

    def test_known_thieu_nhom_sinh_sau(self):
        """`known` chỉ có 3 nhóm cũ → 3 nhóm sinh sau được cộng thêm, còn
        'video' bị bỏ tick TRONG SỐ nhóm đã biết thì vẫn tắt."""
        self.assertEqual(
            _allow({"t1": ["image", "web"]},
                   {"t1": {"known": ["image", "video", "web"]}}),
            {"image", "web", "device", "office", "tts_reply"})

    def test_khong_co_ban_ghi_thi_khong_loc(self):
        self.assertIsNone(_allow({}, {}))


class TestGiuNguyenYNguoiDung(unittest.TestCase):
    def test_co_y_tat_thi_giu_tat(self):
        """`known` đủ mọi nhóm = người dùng đã thấy và đã chọn. Bỏ tick 'video'
        là cố ý, không được tự bật lại."""
        ra = _allow({"t1": ["image", "web", "device", "office", "tts_reply"]},
                    {"t1": {"known": list(NHOM)}})
        self.assertNotIn("video", ra or set())
        self.assertEqual(ra, {"image", "web", "device", "office", "tts_reply"})

    def test_tick_rong_co_chu_dich_thi_chan_het(self):
        """Danh sách rỗng + `known` đủ = "chỉ chat, không tool". Phải giữ đúng
        nghĩa đó, không được biến thành "cho phép tất cả"."""
        self.assertEqual(_allow({"t1": []}, {"t1": {"known": list(NHOM)}}), set())


class TestDongDauKhiLuu(unittest.TestCase):
    """Đường LƯU phải đóng dấu `known`, không thì lần sau người dùng bỏ tick
    nhóm nào cũng bị tự bật lại — lỗi ngược lại, và khó thấy hơn."""

    def test_luu_thi_dong_dau_moi_thread(self):
        data = {"thread_filters": {"a": ["image"], "b": []},
                "thread_filter_meta": {"a": {"kind": "user", "name": "Ai đó"}}}
        with patch.object(caps, "all_groups", return_value=list(NHOM)):
            config_mod._dong_dau_nhom_da_biet(data)
        meta = data["thread_filter_meta"]
        self.assertEqual(meta["a"]["known"], sorted(NHOM))
        self.assertEqual(meta["b"]["known"], sorted(NHOM))
        # Không được xoá thông tin hiển thị đang có
        self.assertEqual(meta["a"]["name"], "Ai đó")

    def test_khong_biet_danh_sach_nhom_thi_khong_dong_dau(self):
        """Import lỗi / danh sách rỗng thì thà không đóng dấu, chứ đóng dấu một
        danh sách thiếu là biến nhóm thật thành "đã bị tắt" vĩnh viễn."""
        data = {"thread_filters": {"a": ["image"]}, "thread_filter_meta": {}}
        with patch.object(caps, "all_groups", return_value=[]):
            config_mod._dong_dau_nhom_da_biet(data)
        self.assertEqual(data["thread_filter_meta"], {})


if __name__ == "__main__":
    unittest.main()
