"""Model viết tool call dạng JSON TRẦN thì phải THỰC THI, không rò ra người dùng.

Đo thật 03/09/2026 trên Zalo: chuỗi dự phòng tụt xuống `nemotron-3-ultra-free`,
model này không gọi tool theo chuẩn mà trả về đúng chuỗi

    {"tool": "search_web", "args": {"query": "...", "max_results": 5}}

và nó đi thẳng ra màn hình người dùng. Bộ bóc cũ chỉ hiểu thẻ `<tool_call>` nên
không nhận ra.

Bộ test giữ bốn tính chất:

  1. Bóc được dạng JSON trần, kể cả khi bọc trong rào ```json.
  2. Nhận nhiều cách đặt tên khoá mà các model hay dùng.
  3. KHÔNG nuốt nhầm: tên tool không có thật, JSON lẫn trong văn xuôi, hay
     object JSON thường đều để nguyên — người dùng có quyền hỏi xin JSON.
  4. Chuẩn hoá xong thì content rỗng: cả nội dung LÀ lệnh gọi, không còn chữ nào
     cho người đọc, để lại là rò nguyên lệnh.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import runtime as rt

TEN = {"search_web", "control_home"}


def _ten_va_args(calls):
    f = calls[0]["function"]
    return f["name"], json.loads(f["arguments"])


class BocDuocTests(unittest.TestCase):
    def test_dang_tool_args(self):
        txt = '{"tool": "search_web", "args": {"query": "abc", "max_results": 5}}'
        ten, args = _ten_va_args(rt.extract_text_tool_calls(txt, TEN))
        self.assertEqual(ten, "search_web")
        self.assertEqual(args["query"], "abc")

    def test_boc_trong_rao_code(self):
        txt = '```json\n{"name": "control_home", "arguments": {"cmd": "bật đèn"}}\n```'
        ten, args = _ten_va_args(rt.extract_text_tool_calls(txt, TEN))
        self.assertEqual(ten, "control_home")
        self.assertEqual(args["cmd"], "bật đèn")

    def test_nhieu_cach_dat_ten_khoa(self):
        for txt in ('{"tool_name": "search_web", "parameters": {"q": 1}}',
                    '{"function": "search_web", "params": {"q": 1}}',
                    '{"action": "search_web", "input": {"q": 1}}'):
            calls = rt.extract_text_tool_calls(txt, TEN)
            self.assertIsNotNone(calls, txt)
            self.assertEqual(calls[0]["function"]["name"], "search_web", txt)

    def test_thieu_args_van_boc_duoc(self):
        ten, args = _ten_va_args(rt.extract_text_tool_calls('{"tool": "search_web"}', TEN))
        self.assertEqual((ten, args), ("search_web", {}))


class KhongNuotNhamTests(unittest.TestCase):
    def test_ten_tool_khong_co_that_thi_bo_qua(self):
        txt = '{"tool": "khong_he_ton_tai", "args": {}}'
        self.assertIsNone(rt.extract_text_tool_calls(txt, TEN))

    def test_json_lan_trong_van_xuoi_thi_bo_qua(self):
        # Chỉ nhận khi TOÀN BỘ nội dung là object — kẻo cắt mất câu trả lời.
        txt = 'Đây là ví dụ: {"tool": "search_web", "args": {}} — anh xem nhé.'
        self.assertIsNone(rt.extract_text_tool_calls(txt, TEN))

    def test_object_json_thuong_thi_bo_qua(self):
        self.assertIsNone(rt.extract_text_tool_calls('{"ten": "Nam", "tuoi": 30}', TEN))

    def test_cau_tra_loi_thuong_thi_bo_qua(self):
        self.assertIsNone(rt.extract_text_tool_calls("Dạ hôm nay trời nắng ạ.", TEN))


class ChuanHoaTests(unittest.TestCase):
    def _data(self, content):
        return {"choices": [{"message": {"role": "assistant", "content": content}}]}

    def test_doi_thanh_tool_calls_va_don_sach_content(self):
        d = self._data('{"tool": "search_web", "args": {"query": "abc"}}')
        rt._normalize_text_tool_calls(d, TEN)
        msg = d["choices"][0]["message"]
        self.assertEqual(len(msg["tool_calls"]), 1)
        # Cả nội dung LÀ lệnh gọi → không còn chữ nào; để lại là rò ra người dùng.
        self.assertEqual(msg["content"], "")

    def test_da_co_tool_calls_native_thi_khong_dung_toi(self):
        d = self._data('{"tool": "search_web"}')
        d["choices"][0]["message"]["tool_calls"] = [{"id": "x"}]
        rt._normalize_text_tool_calls(d, TEN)
        self.assertEqual(d["choices"][0]["message"]["tool_calls"], [{"id": "x"}])

    def test_khong_phai_lenh_goi_thi_giu_nguyen_cau_tra_loi(self):
        d = self._data("Dạ em đã bật đèn phòng khách.")
        rt._normalize_text_tool_calls(d, TEN)
        msg = d["choices"][0]["message"]
        self.assertNotIn("tool_calls", msg)
        self.assertEqual(msg["content"], "Dạ em đã bật đèn phòng khách.")


if __name__ == "__main__":
    unittest.main()
