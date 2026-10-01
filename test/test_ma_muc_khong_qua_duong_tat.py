"""Chọn MÃ MỤC thì câu hệ thống dựng không được đi qua các đường tắt khớp chữ.

Lỗi thật (chủ máy, Zalo cá nhân 01/10/2026 08:01): bản tin sáng gửi theo lịch,
người dùng trích lại rồi gõ «B3» = "Khối mây khổng lồ gây mưa lớn bất thường đến
250 mm…". Orchestrator thay câu thành «Nói kỹ hơn về mục này: "<tiêu đề>"…» rồi
để đường tắt nhà thông minh đọc nó: bỏ dấu thấy "khong" (khổng) + "bat" (bất) +
"den" (đến = đèn) → bot đáp "Tất cả 9 đèn trong nhà đều đang tắt ạ."
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import muc_luc as ml  # noqa: E402
from services.protocol import openai_v1_chat_complete as oc  # noqa: E402
from test._fakes import install_data_dir  # noqa: E402

# Bản tin thật 01/10 08:00 (rút gọn) như Zalo gửi lại trong tin trích.
BAN_TIN = """⏰ Việc theo lịch:
Bản tin sáng 01/10/2026

B. 💼 Kinh tế
B1. Người gửi tiền “săn” ngân hàng lãi suất cao
B3. Khối mây khổng lồ gây mưa lớn bất thường đến 250 mm ở Thành phố Hồ Chí Minh

(Muốn xem kỹ mục nào thì nhắn mã mục đó cho em — ví dụ A1.)"""

TRA_LOI_MODEL = {"choices": [{"message": {"content": "Mưa lớn ở TP.HCM do khối mây đối lưu."}}]}


@pytest.mark.adapter
class MaMucKhongQuaDuongTatTests(unittest.TestCase):
    def setUp(self) -> None:
        ml._reset_for_tests()
        p = mock.patch.object(ml, "_db", lambda: None)
        p.start()
        self.addCleanup(p.stop)

    def _chay(self, cau: str, trich_dan: str = ""):
        import services.agent.orchestrator as orch
        goi_fp: list[str] = []

        def _fp(text: str):
            goi_fp.append(text)
            return "Tất cả 9 đèn trong nhà đều đang tắt ạ.", False, "_ha_local_status"

        with install_data_dir(), \
                mock.patch.object(oc, "ha_local_fastpath_chi_tiet", side_effect=_fp), \
                mock.patch.object(orch, "call_model", return_value=TRA_LOI_MODEL):
            out = orch.orchestrate(cau, "zalop_test_ma_muc", trich_dan=trich_dan,
                                   ha_fastpath=True, auto_approve=True)
        return str(out.get("text") or ""), goi_fp

    def test_go_ma_tu_tin_trich_khong_qua_duong_tat_nha(self) -> None:
        text, goi_fp = self._chay("B3", trich_dan=BAN_TIN)
        self.assertEqual(goi_fp, [], "câu hệ thống dựng từ mã mục lọt vào đường tắt nhà")
        self.assertNotIn("đèn", text)
        self.assertIn("Mưa lớn", text)

    def test_go_ma_tu_ban_cho_khong_qua_duong_tat_nha(self) -> None:
        ml.set_pending("zalop_test_ma_muc", [{
            "ma": "B3", "noi_dung": "Khối mây khổng lồ gây mưa lớn bất thường đến 250 mm"}])
        _, goi_fp = self._chay("B3")
        self.assertEqual(goi_fp, [])

    def test_cau_nguoi_go_van_di_duong_tat_nha(self) -> None:
        """Chặn đúng câu hệ thống dựng — câu người gõ vẫn đi đường tắt như cũ."""
        _, goi_fp = self._chay("đèn trong nhà bật chưa")
        self.assertEqual(goi_fp, ["đèn trong nhà bật chưa"])


if __name__ == "__main__":
    unittest.main()
