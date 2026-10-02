"""Bị chặn / từ chối thì PHẢI báo lý do — không im lặng.

Chủ máy 02/10/2026: "Toàn bộ dự án, bị block hay từ chối phải phản hồi lý do". Trước đó
(yêu cầu 15/07) thread lọc hỏi chức năng tắt thì bot im hẳn; đo runs.sqlite 14 ngày tới
02/10: 5 lượt Zalo status=blocked đều trả lời RỖNG — người hỏi không phân biệt được
"chưa bật" với "bot chết", và lượt [BLOCKED] oan cũng không ai thấy để báo.

Lý do phải ĐÚNG: chỉ nêu tên nhóm khi nó thật sự là nhóm đang tắt của thread.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.agent.orchestrator as orch  # noqa: E402
from services import photo_intent  # noqa: E402
from services.agent import capabilities as caps  # noqa: E402
from test._fakes import install_data_dir  # noqa: E402


def _tra(chu: str) -> dict:
    return {"choices": [{"message": {"content": chu}}]}


def _goi_tool(ten: str) -> dict:
    return {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": ten, "arguments": "{}"}}]}}]}


class OrchestratorBaoLyDoTests(unittest.TestCase):
    def _chay(self, seq, chu="chụp cam phòng khách"):
        with install_data_dir():
            with mock.patch.object(orch, "call_model", side_effect=seq):
                return orch.orchestrate(chu, "zalop_chan", allow={"memory"})

    def test_blocked_dung_nhom_tat_thi_neu_ten_nhom(self) -> None:
        out = self._chay([_tra("[BLOCKED] camera")])
        self.assertFalse(out.get("silent"))
        self.assertIn("«camera» đang TẮT", out["text"])
        self.assertIn("Lọc thread", out["text"])

    def test_blocked_ghi_bua_thi_khong_khang_dinh_ly_do_sai(self) -> None:
        out = self._chay([_tra("[BLOCKED] bay lên mặt trăng")])
        self.assertFalse(out.get("silent"))
        self.assertIn("chưa được bật", out["text"])
        self.assertNotIn("nhóm chức năng", out["text"])

    def test_model_co_goi_tool_nhom_tat_thi_bao_ten_viec_va_nhom(self) -> None:
        out = self._chay([_goi_tool("xem_camera")])
        self.assertFalse(out.get("silent"))
        self.assertIn("«camera» đang TẮT", out["text"])

    def test_loi_dan_chi_cho_blocked_voi_nhom_dang_tat(self) -> None:
        """Việc không nhóm nào làm được thì model phải nói thẳng — không [BLOCKED] (sẽ thành lý do sai)."""
        with install_data_dir():
            with mock.patch.object(orch, "call_model", return_value=_tra("Dạ")) as fake:
                orch.orchestrate("xin chào", "zalop_chan2", allow={"memory"})
        he = fake.call_args.args[1][0]["content"]
        self.assertIn("«[BLOCKED] <tên nhóm", he)
        self.assertIn("KHÔNG nhóm nào làm được", he)
        self.assertIn("Nhóm chức năng đã TẮT cho khung chat này:", he)


class CauBaoTests(unittest.TestCase):
    def test_cau_bao(self) -> None:
        self.assertIn("việc «Tạo ảnh từ ảnh này» chưa được bật",
                      caps.cau_bi_chan(photo_intent.nhan(photo_intent.GENERATE)))
        self.assertIn("thuộc nhóm chức năng «image» đang TẮT", caps.cau_bi_chan("Vẽ", nhom="image"))
        self.assertTrue(caps.cau_bi_chan().startswith("⛔ Dạ việc này chưa được bật"))

    def test_moi_viec_voi_anh_deu_co_nhan(self) -> None:
        for code in photo_intent.INTENT_ORDER:
            self.assertNotEqual(photo_intent.nhan(code), code)
            self.assertNotIn("**", photo_intent.nhan(code))


if __name__ == "__main__":
    unittest.main()
