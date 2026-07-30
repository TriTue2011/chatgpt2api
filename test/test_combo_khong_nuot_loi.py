"""Handler provider KHÔNG được trả chuỗi lỗi như một câu-trả-lời-thành-công.

Lỗi thật, người dùng nhận nguyên văn trên Zalo 30/07 17:28:

    [tokenrouter] Error: [tokenrouter] Connection failed: Failed to perform,
    curl: (56) Connection closed abruptly...

Vòng combo phân biệt thành/bại bằng EXCEPTION (`except Exception → last_error →
continue`). Handler nào bắt exception rồi trả `completion_response(content=
"<chuỗi lỗi>")` là trả về một dict HỢP LỆ → combo coi là THÀNH CÔNG:
`record_success` cho provider đang hỏng (đầu độc cả circuit-breaker lẫn
model_cooldown — cơ chế "xoay model lỗi xuống cuối" thành vô hiệu vì lỗi được
đếm là thành công), DỪNG tại đó, các model đứng sau không bao giờ được thử.

Đo thật cùng ngày, sau khi vá dây chuyền: cx (hết quota) → tokenrouter (curl 56)
→ gemini (hết key) → agnes TRẢ LỜI ĐƯỢC. Trước khi vá, người dùng nhận chuỗi lỗi
của tokenrouter dù agnes/gma vẫn sống.

Test đọc mã nguồn: điều cần khoá là "except → raise, không chế content" — nằm
gọn trong từng khối except. Năm handler cùng mẫu: custom_openai (tokenrouter/
agnes-config...), gemini, agnes, nvidia_nim, opencode.
"""
from __future__ import annotations

import pathlib
import re
import unittest

SRC = (pathlib.Path(__file__).resolve().parents[1]
       / "services" / "protocol" / "openai_v1_chat_complete.py").read_text("utf-8")
CODE = "\n".join(l for l in SRC.splitlines() if not l.lstrip().startswith("#"))


class TestKhongNuotLoi(unittest.TestCase):
    def test_khong_con_completion_response_chua_chuoi_loi(self):
        """Mọi `content=f"...{exc}"` trong nhánh except là một ca nuốt lỗi."""
        xau = re.findall(r'content=f"[^"]*\{exc\}[^"]*"', CODE)
        self.assertEqual(xau, [], f"còn chỗ trả lỗi như content: {xau}")

    def _khoi_except_sau(self, moc: str) -> str:
        i = CODE.index(moc)
        j = CODE.index("except Exception as exc:", i)
        return CODE[j:j + 400]

    def test_tung_handler_raise(self):
        for moc, ten in (
            ('"event": "custom_openai_fatal"', "custom provider"),
            ('"event": "gemini_fatal"', "gemini"),
            ('"event": "agnes_fatal"', "agnes"),
            ('"event": "nvidia_nim_fatal"', "nvidia nim"),
            ('"event": "opencode_completion_error"', "opencode"),
        ):
            i = CODE.index(moc)
            khuc = CODE[i:i + 300]
            self.assertIn("raise", khuc, f"handler {ten} không raise")
            self.assertNotIn("completion_response", khuc,
                             f"handler {ten} vẫn chế câu trả lời")

    def test_combo_van_bat_exception_de_thu_model_ke(self):
        """Nửa kia của cùng cơ chế: vòng combo phải còn nhánh continue theo
        exception — raise mà không ai bắt là đổi lỗi này lấy lỗi 500."""
        i = CODE.index('"event": "combo_fail"')
        khuc = CODE[max(0, i - 400):i + 900]
        self.assertIn("last_error = str(exc)", khuc)
        self.assertIn("continue", khuc)

    def test_that_bai_duoc_ghi_vao_cooldown_va_circuit(self):
        """Đây chính là cái "xoay model lỗi xuống cuối" người dùng xin: có sẵn,
        chỉ vô hiệu vì lỗi bị đếm thành thành công."""
        i = CODE.index('"event": "combo_fail"')
        khuc = CODE[i:i + 1200]
        self.assertIn("model_cooldown.record_failure", khuc)
        self.assertIn("provider_circuit.record_failure", khuc)


if __name__ == "__main__":
    unittest.main()
