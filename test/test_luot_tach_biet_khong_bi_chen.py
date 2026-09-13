"""Lượt gọi TÁCH BIỆT không được bị gateway chèn kho tri thức hay cắt suy luận.

Đo 13/09/2026 trên máy chủ: bot học hỏi giải đề bằng
`call_model(..., no_smart_home=True, allowed_groups=set())` — "system prompt chỉ
có hướng dẫn, không tool, không ngữ cảnh". Vậy mà 40 lượt giải thì 41 lần log có
`kb_prefetched` (~3,3 KB tài liệu điện nước), kèm lời dặn "trả lời NGẮN GỌN, tự
nhiên, dễ nghe" và `_force_effort = "none"`. Đề đầy chữ "đèn", "bật", "bình nóng
lạnh" nên bộ dò từ khoá của gateway tưởng là câu hỏi điện nước / lệnh nhà.

Test chạy thật `_handle_main` tới ngay trước bước chọn pipeline model.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

DE = ("BƯỚC 2 — CHỌN NGOẠI VI\n\nTHIẾT BỊ: switch.binh_nong_lanh | Bình nóng lạnh | "
      "bật 13 lần, tắt 14 lần\nNGOẠI VI — khu vực Ban công:\n"
      "sensor.nhiet_am_ban_cong_temperature | Nhiệt độ ban công | số đo | 24–47 | | \n"
      "Bật đèn bếp khi tối, điện áp, công suất bình nóng lạnh")


class _Dung(Exception):
    pass


class LuotTachBietTests(unittest.TestCase):

    def _chay(self, **them):
        from services.protocol import openai_v1_chat_complete as m

        body = {"model": "AI text", "stream": False,
                "messages": [{"role": "system", "content": "hướng dẫn"},
                             {"role": "user", "content": DE}],
                "response_format": {"type": "json_object"}, **them}
        kb = mock.MagicMock(return_value="TÀI LIỆU ĐIỆN NƯỚC")
        tt = mock.MagicMock(return_value=None)   # đề không hỏi giá vàng
        # Đầu dò: đếm số lần đi qua hai khối tiền xử lý, để ca "không chèn" không
        # đạt oan vì lượt thoát sớm ở chỗ khác. Mã cũ chưa có hàm này — khi đó
        # chính việc tiền xử lý bị gọi đã chứng minh lượt đi tới đúng khối.
        that = getattr(m, "_tach_biet", None)
        self.toi_khoi = 0

        def dau_do(b):
            self.toi_khoi += 1
            return that(b)

        with (mock.patch.object(m, "_tach_biet", side_effect=dau_do) if that
              else mock.patch.object(m, "_extract_last_user_text", wraps=m._extract_last_user_text)), \
             mock.patch("services.mcp_client.prefetch_kb_context", kb), \
             mock.patch("services.mcp_client.prefetch_realtime_context", tt), \
             mock.patch.object(m.backend_router, "get_pipeline", side_effect=_Dung):
            try:
                m._handle_main(body)
            except _Dung:
                pass
        return body, kb, tt

    def test_tach_biet_thi_khong_chen_kho_va_khong_cat_suy_luan(self):
        body, kb, tt = self._chay(x_no_smart_home=True, x_allowed_groups=[])
        tt.assert_not_called()
        self.assertGreaterEqual(self.toi_khoi, 2, "phải thật sự đi tới hai khối tiền xử lý")
        kb.assert_not_called()
        tt.assert_not_called()
        self.assertNotIn("_force_effort", body, "bài đọc bảng số không được bị cắt suy luận")
        self.assertFalse(any("KIẾN THỨC vừa tra cứu" in str(x.get("content"))
                             for x in body["messages"]))

    def test_luot_chat_thuong_van_tien_xu_ly_nhu_cu(self):
        """Không được phá đường nhanh của câu hỏi điện nước thật."""
        # Chặn HA để lượt không rẽ sang đường tắt nhà (đề có "Bật đèn bếp"), nhưng
        # KHÔNG tách biệt: tiền xử lý kho tri thức vẫn phải chạy như cũ.
        body, kb, tt = self._chay(x_no_smart_home=True)
        self.assertGreaterEqual(self.toi_khoi, 2, "phải thật sự đi tới hai khối tiền xử lý")
        tt.assert_called_once()
        kb.assert_called_once()


if __name__ == "__main__":
    unittest.main()
