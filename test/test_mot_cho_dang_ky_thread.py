"""Thread lạ chỉ đăng ký MỘT chỗ («Lọc nhật ký»), ba tab kia đọc lại.

Chủ máy chốt 07/08: thread bot đang ở trong nhưng chưa khai ở «Lọc thread» kênh
nào thì khai một lần bên «Lọc nhật ký», rồi nó phải tự hiện ra ở:

    🧠 Kết nối bộ nhớ        (memory-links-card → LinksCard)
    ☁️ Kết nối kho đám mây   (cùng thẻ trên, khác `configKey`)
    📦 Lưu trữ online        (luu-tru-online-card)

Vì sao chốt bằng test: đây đúng kiểu hỏng "một hàm đúng, cắm sai chỗ" — thêm ô
đăng ký ở «Lọc nhật ký» mà quên nối vào một tab nào đó thì mọi thứ vẫn build,
vẫn chạy, chỉ là thread khai xong KHÔNG hiện ra để chọn, và người dùng không có
cách nào biết vì sao.

Bài này soi mã nguồn TSX (không có runner JS trong bộ test) nên chỉ khẳng định
được ĐƯỜNG DÂY có tồn tại, không khẳng định được hiển thị đúng.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

_THE = GOC / "web" / "src" / "app" / "settings" / "components"

#: Thẻ nào phải đọc `chatlog_settings` để dựng danh sách chọn.
_TIEU_THU = ["memory-links-card.tsx", "luu-tru-online-card.tsx"]


class MotChoDangKyTests(unittest.TestCase):
    def test_cac_tab_deu_doc_thread_tu_them(self) -> None:
        thieu = []
        for ten in _TIEU_THU:
            src = (_THE / ten).read_text(encoding="utf-8")
            if "chatlog_settings" not in src:
                thieu.append(ten)
        self.assertEqual(thieu, [], (
            f"{thieu} không đọc `chatlog_settings` → thread tự thêm bên «Lọc nhật "
            f"ký» sẽ KHÔNG hiện ra để chọn ở tab đó."
        ))

    def test_loc_nhat_ky_co_o_tu_them_kem_chon_kenh(self) -> None:
        """Bắt buộc chọn kênh: id thô không nói được nó thuộc kênh nào, mà khoá
        phạm vi luôn mở đầu bằng kênh — thiếu là bản ghi trỏ vào hư không."""
        src = (_THE / "chatlog-settings-card.tsx").read_text(encoding="utf-8")
        self.assertIn("setTKenh", src, "thiếu ô chọn kênh khi tự thêm thread")
        self.assertIn("setTChat", src, "thiếu ô nhập chat id khi tự thêm thread")

    def test_loc_nhat_ky_co_o_tag_bot(self) -> None:
        src = (_THE / "chatlog-settings-card.tsx").read_text(encoding="utf-8")
        self.assertIn("tag_only", src, "thiếu ô «chỉ ghi tin có tag bot»")

    def test_khoa_ba_phan_tro_len_moi_tach_NGUOI(self) -> None:
        """Khoá chatlog là 'kenh:chat[#topic][:user]', KHÔNG kèm bot — khác khoá
        «Lọc thread». Tách nhầm là chat bị đọc thành người, mối nối trỏ vào một
        phạm vi không ai ghi vào và im lặng không báo gì."""
        for ten in _TIEU_THU:
            src = (_THE / ten).read_text(encoding="utf-8")
            self.assertIn('split(":").length >= 3', src,
                          f"{ten}: thiếu luật tách khoá chatlog theo số phần")


if __name__ == "__main__":
    unittest.main()
