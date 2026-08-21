"""Vòng CHẠY THỬ → LẤY LỖI THẬT → CON SỬA, trong pipeline code.

Đường thành công (code đúng ngay từ đầu) không chứng minh được gì về vòng sửa.
Test này giả lập con viết code SAI trước, rồi kiểm ba điều:

1. Bộ chạy bắt được lỗi và pipeline KHÔNG trả code sai ra ngoài.
2. Góp ý gửi cho con là LỖI THẬT khi chạy (có tên loại lỗi), không phải nhận
   xét chủ quan của model.
3. Chạy thử diễn ra TRƯỚC khi gọi bố soi — mỗi lượt bố là một lần gọi model
   (đo thật: claude/auto 184s), không nên tốn khi code còn chưa chạy nổi.

Test bật `_pipeline_chay_thu_bat` tường minh: chạy THẬT mặc định tắt từ
07/08/2026 vì tầng chạy chưa phải sandbox thật. Ở đây kiểm hành vi của vòng sửa
KHI đã bật, không phải kiểm giá trị mặc định — cái đó là việc của
`test_code_exec_default_off.py`.
"""
from __future__ import annotations

import unittest
from unittest import mock

import services.protocol.openai_v1_chat_complete as P


def _tra_loi(noi_dung: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": noi_dung}}]}


CODE_SAI = "```python\ndef cong(a, b):\n    return a - b\nassert cong(2, 3) == 5\n```"
CODE_DUNG = "```python\ndef cong(a, b):\n    return a + b\nassert cong(2, 3) == 5\n```"


class TestVongChayThu(unittest.TestCase):
    def _chay(self, chuoi_tra_loi: list[str]):
        """Chạy _run_pipeline_review với _dispatch giả trả lần lượt các câu."""
        goi: list[dict] = []
        con = iter(chuoi_tra_loi)

        def fake_dispatch(route, messages, tools, tool_choice, body):
            la_bo = getattr(route, "_la_reviewer", False)
            goi.append({"la_bo": la_bo, "messages": messages})
            if la_bo:
                return _tra_loi("APPROVED")
            return _tra_loi(next(con))

        class R:
            model = "gia/con"
            provider = "gia"
        con_route = R()

        class RB:
            model = "gia/bo"
            provider = "gia"
            _la_reviewer = True

        # CHẠY THẬT mặc định TẮT từ 07/08/2026 (`_pipeline_chay_thu_bat`): tầng
        # chạy chưa phải sandbox thật. Không bật tường minh ở đây thì `CODE_SAI`
        # qua được soi tĩnh (cú pháp đúng, không có tên lạ) và cả vòng sửa không
        # bao giờ chạy — đúng thứ test này sinh ra để canh.
        with mock.patch.object(P, "_dispatch", fake_dispatch), \
             mock.patch.object(P, "_pipeline_chay_thu_bat", lambda: True), \
             mock.patch.object(P.backend_router, "route", lambda m: RB()):
            code = P._run_pipeline_review(
                "code", con_route, [{"role": "user", "content": "cộng hai số"}],
                {"stream": False}, "gia/bo", "kế hoạch", "cộng hai số")
        return code, goi

    def test_code_sai_bi_bat_va_duoc_sua(self):
        code, goi = self._chay([CODE_SAI, CODE_DUNG])
        self.assertIn("a + b", code, "phải trả về code ĐÃ SỬA")
        self.assertNotIn("a - b", code, "không được trả code sai ra ngoài")

    def test_gop_y_la_loi_that_khi_chay(self):
        _, goi = self._chay([CODE_SAI, CODE_DUNG])
        # Lượt gọi con thứ hai là lượt sửa — góp ý nằm trong message system cuối.
        luot_sua = [g for g in goi if not g["la_bo"]][1]
        gop_y = str(luot_sua["messages"][-1].get("content") or "")
        self.assertIn("AssertionError", gop_y,
                      "góp ý phải chứa lỗi THẬT lấy từ lúc chạy")
        self.assertIn("lỗi THẬT", gop_y)

    def test_chay_thu_truoc_khi_goi_bo(self):
        """Lượt gọi ĐẦU TIÊN sau khi con viết phải là con SỬA, không phải bố soi
        — nghĩa là đã chạy thử trước, không tốn lượt bố cho code chưa chạy nổi."""
        _, goi = self._chay([CODE_SAI, CODE_DUNG])
        self.assertFalse(goi[0]["la_bo"], "lượt 1 = con viết")
        self.assertFalse(goi[1]["la_bo"], "lượt 2 phải là con SỬA, không phải bố")

    def test_code_dung_ngay_thi_khong_sua_gi(self):
        code, goi = self._chay([CODE_DUNG])
        self.assertIn("a + b", code)
        luot_con = [g for g in goi if not g["la_bo"]]
        self.assertEqual(len(luot_con), 1, "code chạy được thì không gọi con lần hai")

    def test_cong_tac_tat_thi_khong_chay_thu(self):
        with mock.patch.object(P, "_pipeline_chay_thu_bat", lambda: False):
            code, goi = self._chay([CODE_SAI])
        self.assertIn("a - b", code, "tắt chạy thử thì giữ hành vi cũ")


if __name__ == "__main__":
    unittest.main()
