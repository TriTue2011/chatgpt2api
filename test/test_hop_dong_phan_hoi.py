"""Cửa điều phối KIỂM hợp đồng phản hồi của adapter — chỉ quan sát, không đổi gì.

Hai lớp lỗi «không báo cho ai» mà cửa điều phối thấy được mà không provider nào tự khai:

* adapter trả một dict không phải lời đáp chat-completion dùng được (thiếu ``choices``,
  dict lỗi, câu trả lời rỗng) — vòng combo vẫn coi là THÀNH CÔNG và dừng;
* yêu cầu có ``tools`` mà adapter khai ``tools=False`` — tools bị bỏ im lặng.

Kiểm ở đây: dòng log, dấu ``hop_dong`` trong vết nguồn, KHÔNG báo oan với các dạng hợp lệ
thật mà handler đang trả, và phản hồi gốc đi ra nguyên vẹn dù khối kiểm có hỏng.
Hành vi định tuyến (handler nào, đối số nào) thuộc ``test_dieu_phoi_provider.py``.
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.protocol.openai_v1_chat_complete as occ  # noqa: E402
from services import adapter_registry  # noqa: E402
from services import request_context as rc  # noqa: E402

MSGS = [{"role": "user", "content": "xin chào"}]
TOOLS = [{"type": "function", "function": {"name": "t"}}]


def _dap(message: dict, finish: str = "stop") -> dict:
    return {"id": "x", "object": "chat.completion", "model": "m",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}]}


class _Hong(dict):
    """Dict mà mọi lần đọc đều nổ — khối kiểm hỏng thì phản hồi vẫn phải đi ra."""

    def get(self, *a, **k):
        raise RuntimeError("đọc là nổ")

    def __getitem__(self, k):
        raise RuntimeError("đọc là nổ")


def goi(tra, *, tools=TOOLS, khai_tools=False, stream=False, provider="thu_hd",
        ghi_tai_khoan=False):
    """Đăng ký tạm một adapter trả ``tra`` rồi gọi `_dispatch_provider`."""
    def chat(route, messages, t, tc, body):
        if ghi_tai_khoan:
            rc.note_provider_account(route.provider, "acc@x", model=route.model, account_id="id9")
        if isinstance(tra, Exception):
            raise tra
        return tra

    route = SimpleNamespace(provider=provider, model="m1")
    cfg = SimpleNamespace(rtk_enabled=False, rtk_other_enabled=False)
    with mock.patch.dict(adapter_registry._BANG), mock.patch.object(occ, "config", cfg):
        if provider != "flow":
            adapter_registry.dang_ky(provider, chat, tools=khai_tools)
        with mock.patch.object(occ, "_chatgpt_free_thang", lambda *a: tra):
            return occ._dispatch_provider(route, MSGS, tools, "auto", {"stream": stream})


class _Nen(unittest.TestCase):
    def setUp(self) -> None:
        rc.reset_all()

    def tearDown(self) -> None:
        rc.reset_all()


class SaiHopDongTests(_Nen):
    def _ly_do(self, tra) -> str:
        with self.assertLogs("chatgpt2api", level="WARNING") as cm:
            kq = goi(tra, tools=None)
        self.assertIs(kq, tra)          # chỉ quan sát: trả về CHÍNH đối tượng gốc
        dong = [m for m in cm.output if "phan_hoi_sai_hop_dong" in m]
        self.assertEqual(len(dong), 1, cm.output)
        self.assertIn('"provider": "thu_hd"', dong[0])
        self.assertIn('"model": "m1"', dong[0])
        return dong[0]

    def test_thieu_choices(self) -> None:
        for tra in ({}, {"choices": []}, {"choices": None}, {"id": "x", "object": "chat.completion"}):
            with self.subTest(tra=tra):
                self.assertIn('"ly_do": "thieu_choices"', self._ly_do(tra))

    def test_dict_loi_thay_cho_cau_tra_loi(self) -> None:
        # Upstream trả 200 kèm {"error": …}: combo coi là thành công — đúng lớp lỗi đã gặp
        # 30/07 với custom provider. Ghi lý do riêng để nhìn log biết ngay.
        self.assertIn('"ly_do": "loi_trong_phan_hoi"', self._ly_do({"error": {"message": "hết hạn mức"}}))

    def test_thieu_message(self) -> None:
        for tra in ({"choices": ["chuỗi"]}, {"choices": [{"index": 0, "finish_reason": "stop"}]}):
            with self.subTest(tra=tra):
                self.assertIn('"ly_do": "thieu_message"', self._ly_do(tra))

    def test_noi_dung_rong(self) -> None:
        for msg in ({"role": "assistant", "content": ""},
                    {"role": "assistant", "content": None},
                    {"role": "assistant", "content": "  \n"},
                    {"role": "assistant", "content": "", "tool_calls": []}):
            with self.subTest(msg=msg):
                self.assertIn('"ly_do": "noi_dung_rong"', self._ly_do(_dap(msg)))

    def test_ghi_hop_dong_vao_vet_nguon(self) -> None:
        with self.assertLogs("chatgpt2api", level="WARNING"):
            goi({}, tools=None)
        d = rc.get_dest()
        self.assertEqual((d["provider"], d["model"], d["hop_dong"]), ("thu_hd", "m1", "thieu_choices"))

    def test_giu_tai_khoan_provider_da_tu_ghi(self) -> None:
        # set_dest THAY cả hàng: ghi lại mà chỉ truyền provider/model là xoá mất tài khoản.
        with self.assertLogs("chatgpt2api", level="WARNING"):
            goi({}, tools=None, ghi_tai_khoan=True)
        d = rc.get_dest()
        self.assertEqual((d["account"], d["account_id"], d["hop_dong"]), ("acc@x", "id9", "thieu_choices"))

    def test_nhanh_thay_the_giu_yeu_cau(self) -> None:
        with self.assertLogs("chatgpt2api", level="WARNING") as cm:
            goi({"choices": []}, tools=None, provider="flow")
        self.assertTrue(any('"provider": "chatgpt_free"' in m and "phan_hoi_sai_hop_dong" in m
                            for m in cm.output), cm.output)
        d = rc.get_dest()
        self.assertEqual((d["provider"], d["yeu_cau"], d["hop_dong"]), ("chatgpt_free", "flow", "thieu_choices"))

    def test_khoi_kiem_hong_thi_phan_hoi_van_nguyen(self) -> None:
        tra = _Hong(choices=[])
        kq = goi(tra, tools=None)
        self.assertIs(kq, tra)


class KhongBaoOanTests(_Nen):
    """Các dạng HỢP LỆ mà handler thật đang trả — đọc mã 10/10/2026."""

    HOP_LE = {
        # completion_response(): grok_web, chatgpt_free, custom «not found»…
        "van_ban": _dap({"role": "assistant", "content": "chào"}),
        # chatgpt_free khi có tool call: content rỗng, finish_reason=tool_calls
        "tool_calls": _dap({"role": "assistant", "content": "", "tool_calls": [{"id": "c"}]}, "tool_calls"),
        # gemini_free gom stream: có tool_calls mà finish_reason vẫn là "stop"
        "tool_calls_finish_stop": _dap({"role": "assistant", "content": "", "tool_calls": [{"id": "c"}]}),
        # chuẩn OpenAI: content=None khi chỉ gọi tool
        "content_none_co_tool": _dap({"role": "assistant", "content": None, "tool_calls": [{"id": "c"}]}, "tool_calls"),
        # content dạng danh sách phần (đa phương thức)
        "content_list": _dap({"role": "assistant", "content": [{"type": "text", "text": "a"}]}),
        # cắt vì hết max_tokens: rỗng nhưng KHÔNG phải "stop" → không kết luận
        "het_token": _dap({"role": "assistant", "content": ""}, "length"),
        # 9router/custom chuyển nguyên resp.json(): không chắc có id/object/usage
        "toi_gian": {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
    }

    def test_dang_hop_le_khong_bi_bao(self) -> None:
        for ten, tra in self.HOP_LE.items():
            with self.subTest(dang=ten):
                rc.reset_all()
                with self.assertNoLogs("chatgpt2api", level="WARNING"):
                    kq = goi(tra, tools=None)
                self.assertIs(kq, tra)
                self.assertNotIn("hop_dong", rc.get_dest())

    def test_stream_khong_kiem_khong_doc(self) -> None:
        da_doc: list = []

        def gen():
            da_doc.append(1)
            yield {}
        g = gen()
        with self.assertNoLogs("chatgpt2api", level="WARNING"):
            kq = goi(g, tools=None, stream=True)
        self.assertIs(kq, g)
        self.assertEqual(da_doc, [])     # chưa kiểm stream: không được đọc trước khúc nào
        self.assertNotIn("hop_dong", rc.get_dest())


class ToolsBiBoTests(_Nen):
    def _dong_tools(self, **k) -> list[str]:
        with self.assertLogs("chatgpt2api", level="INFO") as cm:
            occ.logger.info({"event": "moc"})   # để assertLogs không đỏ khi đúng là không có dòng nào
            goi(_dap({"role": "assistant", "content": "ok"}), **k)
        return [m for m in cm.output if "tools_bi_bo" in m]

    def test_adapter_khong_nhan_tools_thi_bao_mot_dong(self) -> None:
        dong = self._dong_tools(tools=TOOLS + TOOLS, khai_tools=False)
        self.assertEqual(len(dong), 1)
        self.assertIn('"provider": "thu_hd"', dong[0])
        self.assertIn('"so_tool": 2', dong[0])

    def test_ca_khi_stream(self) -> None:
        with self.assertLogs("chatgpt2api", level="INFO") as cm:
            goi(iter([]), tools=TOOLS, stream=True)
        self.assertEqual(len([m for m in cm.output if "tools_bi_bo" in m]), 1)

    def test_khong_bao_khi_adapter_nhan_tools_hoac_khong_co_tools(self) -> None:
        self.assertEqual(self._dong_tools(tools=TOOLS, khai_tools=True), [])
        self.assertEqual(self._dong_tools(tools=None), [])
        self.assertEqual(self._dong_tools(tools=[]), [])

    def test_adapter_bao_loi_thi_khong_bao_tools_bi_bo(self) -> None:
        with self.assertLogs("chatgpt2api", level="INFO") as cm:
            occ.logger.info({"event": "moc"})
            with self.assertRaises(RuntimeError):
                goi(RuntimeError("hỏng"), tools=TOOLS)
        self.assertEqual([m for m in cm.output if "tools_bi_bo" in m], [])

    def test_khong_bao_tools_cho_nhanh_roi_ve_free(self) -> None:
        # chatgpt_free nhận tools (sau khi bóc schema) — không phải bị bỏ
        with self.assertLogs("chatgpt2api", level="INFO") as cm:
            goi(_dap({"role": "assistant", "content": "ok"}), tools=TOOLS, provider="flow")
        self.assertEqual([m for m in cm.output if "tools_bi_bo" in m], [])


if __name__ == "__main__":
    unittest.main()
