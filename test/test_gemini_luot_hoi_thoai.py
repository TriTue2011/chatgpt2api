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


class ChuKySuyNghiTests(unittest.TestCase):
    """06/10/2026: Gemini 3 trả 400 "Function call is missing a thought_signature" ở bước 2 của MỌI lượt có gọi công
    cụ — chữ ký đi kèm functionCall bị vứt khi đọc, nên bot rơi xuống model dự phòng yếu (trả lời lẫn tiếng Nga)."""

    def test_loi_goi_do_model_khac_tao_dung_chu_ky_thay(self):
        from services.providers import gemini_free
        contents, _, _ = _convert_request(GOI_CONG_CU, None)
        goi = next(p for c in contents for p in c["parts"] if "functionCall" in p)
        self.assertEqual(goi["thoughtSignature"], gemini_free._CHU_KY_THAY)

    def test_loi_goi_do_gemini_tao_gui_tra_dung_chu_ky_that(self):
        from services.providers import gemini_free
        gemini_free._CHU_KY["call_1"] = "CHU_KY_THAT"
        self.addCleanup(gemini_free._CHU_KY.pop, "call_1", None)
        contents, _, _ = _convert_request(GOI_CONG_CU, None)
        goi = next(p for c in contents for p in c["parts"] if "functionCall" in p)
        self.assertEqual(goi["thoughtSignature"], "CHU_KY_THAT")

    def test_doc_luong_nho_chu_ky_roi_luot_sau_gui_tra(self):
        """Trọn vòng: Gemini trả functionCall kèm chữ ký → lượt sau (cùng mã lời gọi) gửi trả đúng chữ ký đó."""
        import json as _json

        from services.providers import gemini_free

        class _Tra:
            def iter_lines(self):
                yield ("data: " + _json.dumps({"candidates": [{"content": {"parts": [
                    {"functionCall": {"name": "home_status", "args": {}}, "thoughtSignature": "CK_TU_GEMINI"}]}}]})).encode()

            def close(self):
                pass

        goi = [tc for ch in gemini_free._parse_gemini_stream(_Tra(), "gemini-3.5-flash-lite")
               for tc in (ch["choices"][0]["delta"].get("tool_calls") or [])]
        self.assertEqual(len(goi), 1)
        self.addCleanup(gemini_free._CHU_KY.pop, goi[0]["id"], None)
        tin = [{"role": "user", "content": "Nhà có ai không?"},
               {"role": "assistant", "content": "", "tool_calls": goi},
               {"role": "tool", "tool_call_id": goi[0]["id"], "content": "Không có ai."}]
        contents, _, _ = _convert_request(tin, None)
        fc = next(p for c in contents for p in c["parts"] if "functionCall" in p)
        self.assertEqual(fc["thoughtSignature"], "CK_TU_GEMINI")
