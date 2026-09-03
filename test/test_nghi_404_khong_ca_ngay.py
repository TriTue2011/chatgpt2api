"""Một lần 404 không được phạt nghỉ cả ngày.

Bảng phạt cũ quy định 404 = nghỉ 12 tiếng, dựa trên giả định "404 nghĩa là model
này không tồn tại, có thử lại cũng vô ích". Đo ngày 03/09/2026 trên máy chủ thật
cho thấy giả định đó sai với Codex: chatgpt.com trả 404 THÂN RỖNG cho một tài
khoản đã bị OpenAI thu hồi quyền, trong khi model vẫn sống nguyên — cùng lúc đó
gpt-5.5 và gpt-5.6-luna gọi bằng tài khoản khác vẫn trả lời bình thường.

Hậu quả đo được trong log: đúng một lần vớ phải tài khoản chết lúc 21:45 là cả
codex lẫn chatgpt free bị bỏ qua suốt buổi tối, mọi request tụt xuống model yếu
hơn ở cuối chuỗi dự phòng.

Bộ test giữ ba tính chất:

  1. 404 VẪN được ghi nghỉ — provider hỏng thật thì đừng nện vào nó liên tục.
  2. Nhưng án phải tính bằng PHÚT, không phải bằng giờ. Mốc kiểm: dưới một
     tiếng, và không dài hơn án 401 (401 là "token sai" — chắc chắn hơn 404
     nhiều, nên 404 không có lý gì bị phạt nặng hơn).
  3. Các mã khác giữ nguyên: 413 không bao giờ nghỉ, 5xx vẫn nghỉ ngắn.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.model_cooldown import ModelCooldownManager


class An404Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.qly = ModelCooldownManager()

    def _nghi(self, ma: int) -> float:
        st = self.qly.record_failure("tk1", "gpt-5.5", status_code=ma)
        return st.remaining_seconds

    def test_404_van_bi_ghi_nghi(self):
        self.assertGreater(self._nghi(404), 0)
        self.assertFalse(self.qly.is_available("tk1", "gpt-5.5"))

    def test_404_tinh_bang_phut_chu_khong_bang_gio(self):
        con = self._nghi(404)
        self.assertLess(con, 3600, f"404 vẫn bị phạt {con/3600:.1f} tiếng")

    def test_404_khong_nang_hon_401(self):
        # 401 là "token sai" — kết luận chắc chắn hơn hẳn 404 thân rỗng.
        self.assertLessEqual(ModelCooldownManager.BACKOFF_404_COOLDOWN,
                             ModelCooldownManager.BACKOFF_401_COOLDOWN)

    def test_413_van_khong_bao_gio_nghi(self):
        self.qly.record_failure("tk2", "gpt-5.5", status_code=413)
        self.assertTrue(self.qly.is_available("tk2", "gpt-5.5"))

    def test_5xx_van_nghi_ngan(self):
        self.assertLessEqual(self._nghi(503), 120)


if __name__ == "__main__":
    unittest.main()
