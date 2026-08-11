"""Luồng Facebook đăng link/chữ qua orchestrate — KHÔNG để LLM diễn giải.

Bịt lỗi 11/08: chọn «đăng link» rồi dán URL repo GitHub thì model lạc sang
trợ lý code, đứt mạch. Test chứng minh: khi đang chờ input bài Facebook,
orchestrate bắt tin ở CODE (không gọi call_model) rồi đưa qua cổng duyệt.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.agent.orchestrator as orch  # noqa: E402
import services.facebook_page as fbp  # noqa: E402
from services.agent import approval_gate  # noqa: E402
from services.config import config  # noqa: E402
from test._fakes import install_data_dir  # noqa: E402

_CFG_FB = {"facebook": {"pages": [
    {"id": "111", "name": "Blog cá nhân", "access_token": "tokA"}]}}


class FacebookFlowOrchestrateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._uid = "zalop_777"
        fbp.xoa_flow(self._uid)
        approval_gate.clear_pending(self._uid)
        self._data = install_data_dir()
        self._data.__enter__()
        self._cfg = mock.patch.dict(config.data, _CFG_FB)
        self._cfg.start()
        # Không gọi model thật — và bắt lỗi nếu luồng lỡ chạm tới LLM.
        self._boom = mock.patch.object(
            orch, "call_model",
            side_effect=AssertionError("LLM bị gọi — luồng FB đã đứt mạch!"))
        self._boom.start()

    def tearDown(self) -> None:
        self._boom.stop()
        self._cfg.stop()
        self._data.__exit__(None, None, None)
        fbp.xoa_flow(self._uid)
        approval_gate.clear_pending(self._uid)

    def test_chon_dang_link_roi_dan_url_khong_goi_llm_va_toi_cong_duyet(self) -> None:
        # 1) Chọn mục «đăng link» (sentinel như resolve_reply trả về)
        out1 = orch.orchestrate(fbp.FLOW_LINK, self._uid)
        self.assertIn("LINK", (out1.get("text") or ""))
        self.assertTrue(fbp.co_flow(self._uid))

        # 2) Dán đúng URL từng gây lỗi — phải hỏi lời dẫn, KHÔNG lạc sang code
        out2 = orch.orchestrate(
            "https://github.com/colbymchenry/codegraph", self._uid)
        self.assertIn("dẫn", (out2.get("text") or "").lower())
        self.assertTrue(fbp.co_flow(self._uid))

        # 3) Lời dẫn → gom đủ, vào CỔNG DUYỆT của dang_facebook (chưa đăng)
        out3 = orch.orchestrate("Repo hay nè", self._uid)
        self.assertFalse(fbp.co_flow(self._uid))
        pend = approval_gate.get_pending(self._uid)
        self.assertIsNotNone(pend)
        self.assertEqual(pend.get("capability"), "dang_facebook")
        args = pend.get("args") or {}
        self.assertEqual(args.get("loai"), "link")
        self.assertEqual(args.get("link"),
                         "https://github.com/colbymchenry/codegraph")
        self.assertEqual(args.get("message"), "Repo hay nè")
        _ = out3  # câu duyệt do approval_gate dựng; không kiểm text cứng

    def test_huy_giua_chung_thoat_sach(self) -> None:
        orch.orchestrate(fbp.FLOW_CHU, self._uid)
        self.assertTrue(fbp.co_flow(self._uid))
        out = orch.orchestrate("thôi", self._uid)
        self.assertIn("huỷ", (out.get("text") or "").lower())
        self.assertFalse(fbp.co_flow(self._uid))
        self.assertIsNone(approval_gate.get_pending(self._uid))


if __name__ == "__main__":
    unittest.main()
