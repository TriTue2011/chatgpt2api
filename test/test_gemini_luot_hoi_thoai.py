"""Gemini: kết quả công cụ là lượt NGƯỜI DÙNG, không phải lượt model.

Đo thật 24/08/2026 lúc 08:57 trên máy chủ. Người dùng nhắn một câu bình thường,
provider đầu chết vì lỗi khác, orchestrator gửi lại đúng danh sách tin nhắn đó
sang Gemini và nhận:

    Gemini error 400: "Requests ending with a model turn are not supported."

Cả hai khoá đều hỏng như nhau, lượt chat rơi tiếp xuống provider thứ tư và tới
tay người dùng sau 52 giây.

Nguyên nhân trong `_convert_request`: mọi vai không phải user/system đều bị gộp
thành "model". Kết quả công cụ (role="tool") vì thế bị gửi lên như thể chính
model nói ra — vừa sai mô hình hội thoại của Gemini, vừa làm request kết thúc
bằng lượt model. Lượt assistant gọi công cụ thì ngược lại: chữ rỗng nên chỉ còn
một lượt trống, mất luôn việc model đã gọi hàm gì.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")

from services.providers.gemini_free import _convert_request  # noqa: E402

GOI_CONG_CU = [
    {"role": "system", "content": "Em là trợ lý."},
    {"role": "user", "content": "Nhà có ai không?"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "call_1", "type": "function",
         "function": {"name": "home_status", "arguments": '{"khu_vuc": "phong khach"}'}}]},
    {"role": "tool", "tool_call_id": "call_1", "content": "Không có ai."},
]


class KetQuaCongCuTests(unittest.TestCase):
    def setUp(self):
        self.contents, self.si, _ = _convert_request(GOI_CONG_CU, None)

    def test_khong_ket_thuc_bang_luot_model(self):
        self.assertEqual(self.contents[-1]["role"], "user",
                         "đúng thứ làm Gemini trả 400")

    def test_ket_qua_cong_cu_thanh_functionResponse_dung_ten(self):
        cuoi = self.contents[-1]["parts"][0]
        self.assertIn("functionResponse", cuoi)
        self.assertEqual(cuoi["functionResponse"]["name"], "home_status")
        self.assertEqual(cuoi["functionResponse"]["response"]["result"], "Không có ai.")

    def test_luot_goi_cong_cu_giu_duoc_ten_va_tham_so(self):
        goi = next(c for c in self.contents
                   if any("functionCall" in p for p in c["parts"]))
        self.assertEqual(goi["role"], "model")
        fc = goi["parts"][0]["functionCall"]
        self.assertEqual(fc["name"], "home_status")
        self.assertEqual(fc["args"], {"khu_vuc": "phong khach"})

    def test_system_van_tach_rieng(self):
        self.assertIn("Em là trợ lý.", self.si["parts"][0]["text"])
        self.assertTrue(all(c["role"] in ("user", "model") for c in self.contents))


class ThieuTenHamTests(unittest.TestCase):
    """Không tra ra tên hàm thì giữ nội dung dạng chữ, đừng gửi thiếu tên."""

    def test_khong_co_tool_call_id_khop(self):
        contents, _, _ = _convert_request([
            {"role": "user", "content": "hỏi"},
            {"role": "tool", "tool_call_id": "khong-biet", "content": "kết quả"},
        ], None)
        cuoi = contents[-1]
        self.assertEqual(cuoi["role"], "user")
        self.assertIn("kết quả", cuoi["parts"][0]["text"])
        self.assertNotIn("functionResponse", cuoi["parts"][0])


class KetThucBangAssistantTests(unittest.TestCase):
    """Hội thoại kết thúc bằng câu trả lời của model vẫn phải gửi được."""

    def test_them_mot_luot_nguoi_dung_toi_thieu(self):
        contents, _, _ = _convert_request([
            {"role": "user", "content": "chào em"},
            {"role": "assistant", "content": "Dạ em đây ạ."},
        ], None)
        self.assertEqual(contents[-1]["role"], "user")
        self.assertEqual(len(contents), 3)

    def test_hoi_thoai_binh_thuong_khong_bi_them_gi(self):
        contents, _, _ = _convert_request([
            {"role": "user", "content": "chào em"},
        ], None)
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["role"], "user")


if __name__ == "__main__":
    unittest.main()
