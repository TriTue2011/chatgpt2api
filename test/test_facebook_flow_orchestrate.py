"""Luồng Facebook đăng link/chữ qua orchestrate — KHÔNG để LLM diễn giải.

Bịt lỗi 11/08: chọn «đăng link» rồi dán URL repo GitHub thì model lạc sang
trợ lý code, đứt mạch. Test chứng minh: khi đang chờ input bài Facebook,
orchestrate bắt tin ở CODE (không gọi call_model) rồi đưa qua cổng duyệt.

Bịt lỗi 12/08: gõ một YÊU CẦU ("đọc repo rồi viết bài") vào ô lời dẫn thì nó
đăng đúng câu yêu cầu đó lên Page. Nay sau khi có nội dung, luồng hỏi thêm một
bước — đăng y nguyên, hay để AI viết thành bài. Chỉ nhánh AI mới chạm tới LLM,
và chỉ khi người dùng bấm chọn.
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

_REPO = "https://github.com/colbymchenry/codegraph"


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

    def _den_buoc_chon(self, loi_dan: str) -> None:
        """Chọn «đăng link» → dán URL → gõ lời dẫn → dừng ở bước chọn cách."""
        out1 = orch.orchestrate(fbp.FLOW_LINK, self._uid)
        self.assertIn("LINK", (out1.get("text") or ""))
        out2 = orch.orchestrate(_REPO, self._uid)
        self.assertIn("dẫn", (out2.get("text") or "").lower())
        out3 = orch.orchestrate(loi_dan, self._uid)
        # Chưa đăng, chưa duyệt — đang hỏi đăng y nguyên hay nhờ AI viết
        self.assertIsNone(approval_gate.get_pending(self._uid))
        self.assertTrue(fbp.co_flow(self._uid))
        self.assertIn("y nguyên", (out3.get("text") or "").lower())

    def test_chon_dang_link_roi_dan_url_khong_goi_llm(self) -> None:
        self._den_buoc_chon("Repo hay nè")

    def test_chon_dang_y_nguyen_toi_cong_duyet_dung_noi_dung(self) -> None:
        self._den_buoc_chon("Repo hay nè")
        orch.orchestrate(fbp.CHON_NGUYEN, self._uid)
        self.assertFalse(fbp.co_flow(self._uid))
        pend = approval_gate.get_pending(self._uid)
        self.assertIsNotNone(pend)
        self.assertEqual(pend.get("capability"), "dang_facebook")
        args = pend.get("args") or {}
        self.assertEqual(args.get("loai"), "link")
        self.assertEqual(args.get("link"), _REPO)
        self.assertEqual(args.get("message"), "Repo hay nè")

    def test_go_lung_tung_o_buoc_chon_thi_hoi_lai_khong_dang(self) -> None:
        self._den_buoc_chon("Repo hay nè")
        out = orch.orchestrate("ờ", self._uid)
        self.assertIn("y nguyên", (out.get("text") or "").lower())
        self.assertTrue(fbp.co_flow(self._uid))          # giữ bài đã soạn
        self.assertIsNone(approval_gate.get_pending(self._uid))

    def test_bo_loi_dan_thi_dang_thang_khong_hoi_them(self) -> None:
        orch.orchestrate(fbp.FLOW_LINK, self._uid)
        orch.orchestrate(_REPO, self._uid)
        orch.orchestrate("đăng", self._uid)
        self.assertFalse(fbp.co_flow(self._uid))
        args = (approval_gate.get_pending(self._uid) or {}).get("args") or {}
        self.assertEqual(args.get("message"), "")
        self.assertEqual(args.get("link"), _REPO)

    def test_gui_video_khi_dang_cho_link_khong_thanh_link_rac(self) -> None:
        """Kênh bơm câu 'thêm video vào bài đăng facebook: <url>' giữa chừng.

        Trước đây cả câu đó bị nuốt làm LINK của bài (đo thật 12/08).
        """
        orch.orchestrate(fbp.FLOW_LINK, self._uid)
        out = orch.orchestrate(
            "thêm video vào bài đăng facebook: https://cdn/x.mp4", self._uid)
        self.assertIn("không ghép", (out.get("text") or ""))
        self.assertTrue(fbp.co_flow(self._uid))
        self.assertIsNone(approval_gate.get_pending(self._uid))

        # Dán link thật vẫn chạy tiếp, không mất bước nào
        orch.orchestrate(_REPO, self._uid)
        orch.orchestrate("Repo hay nè", self._uid)
        orch.orchestrate(fbp.CHON_NGUYEN, self._uid)
        args = (approval_gate.get_pending(self._uid) or {}).get("args") or {}
        self.assertEqual(args.get("link"), _REPO)

    def test_bam_mot_nut_la_ai_doc_link_roi_viet(self) -> None:
        """Bước lời dẫn có nút — bấm là AI viết, không phải gõ chữ nào."""
        orch.orchestrate(fbp.FLOW_LINK, self._uid)
        # Khối <<<ASK>>> bị _finalize tách ra thành `choices` (nút bấm), nên
        # nhãn nút KHÔNG còn trong `text` — kiểm đúng chỗ nó nằm.
        out_menu = orch.orchestrate(_REPO, self._uid)
        nhan = [c["label"] for c in (out_menu.get("choices") or [])]
        self.assertEqual(len(nhan), 4, nhan)
        self.assertTrue(any("đọc link" in n.lower() for n in nhan), nhan)

        self._boom.stop()
        fake = mock.Mock(return_value={
            "choices": [{"message": {"content": "Đây là bài nháp ạ."}}]})
        with mock.patch.object(orch, "call_model", fake):
            out = orch.orchestrate(fbp.CHON_AI_LINK, self._uid)
        self._boom.start()

        self.assertFalse(fbp.co_flow(self._uid))
        self.assertIsNone(approval_gate.get_pending(self._uid))
        self.assertIn("nháp", (out.get("text") or "").lower())
        gui = "\n".join(str(m.get("content") or "")
                        for m in fake.call_args[0][1])
        self.assertIn(_REPO, gui)
        self.assertNotIn(fbp.CHON_AI_LINK, gui)

    def test_cau_duyet_cho_nhin_thay_link(self) -> None:
        self._den_buoc_chon("Repo hay nè")
        out = orch.orchestrate(fbp.CHON_NGUYEN, self._uid)
        self.assertIn(_REPO, (out.get("text") or ""))

    def test_chon_nho_ai_viet_thi_giao_cho_vong_agent(self) -> None:
        yeu_cau = "đọc và phân tích viết 1 bài về tác dụng của repo với coder"
        self._den_buoc_chon(yeu_cau)

        # Nhánh này ĐƯỢC PHÉP gọi LLM — thay bản nổ bằng bản trả lời rỗng tool.
        self._boom.stop()
        fake = mock.Mock(return_value={
            "choices": [{"message": {"content": "Đây là bài nháp ạ."}}]})
        with mock.patch.object(orch, "call_model", fake):
            out = orch.orchestrate(fbp.CHON_AI, self._uid)
        self._boom.start()

        self.assertFalse(fbp.co_flow(self._uid))
        # Không đăng thẳng: chưa có gì ở cổng duyệt, bài phải qua model trước
        self.assertIsNone(approval_gate.get_pending(self._uid))
        self.assertIn("nháp", (out.get("text") or "").lower())

        self.assertTrue(fake.called)
        messages = fake.call_args[0][1]
        gui = "\n".join(str(m.get("content") or "") for m in messages)
        self.assertIn(yeu_cau, gui)          # yêu cầu thật tới được model
        self.assertIn(_REPO, gui)            # kèm link để model đọc trang
        self.assertNotIn(fbp.CHON_AI, gui)   # sentinel không lọt vào lịch sử


class FacebookFlowChuTests(unittest.TestCase):
    """Nhánh «đăng bài chữ» cũng phải qua bước chọn, không đăng thẳng nữa."""

    def setUp(self) -> None:
        self._uid = "zalop_778"
        fbp.xoa_flow(self._uid)
        approval_gate.clear_pending(self._uid)
        self._data = install_data_dir()
        self._data.__enter__()
        self._cfg = mock.patch.dict(config.data, _CFG_FB)
        self._cfg.start()
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

    def test_bai_chu_hoi_cach_dang_roi_moi_toi_cong_duyet(self) -> None:
        orch.orchestrate(fbp.FLOW_CHU, self._uid)
        out = orch.orchestrate("Hôm nay trời đẹp", self._uid)
        self.assertIn("y nguyên", (out.get("text") or "").lower())
        self.assertIsNone(approval_gate.get_pending(self._uid))

        orch.orchestrate(fbp.CHON_NGUYEN, self._uid)
        args = (approval_gate.get_pending(self._uid) or {}).get("args") or {}
        self.assertEqual(args.get("loai"), "chu")
        self.assertEqual(args.get("message"), "Hôm nay trời đẹp")

    def test_huy_giua_chung_thoat_sach(self) -> None:
        orch.orchestrate(fbp.FLOW_CHU, self._uid)
        self.assertTrue(fbp.co_flow(self._uid))
        out = orch.orchestrate("thôi", self._uid)
        self.assertIn("huỷ", (out.get("text") or "").lower())
        self.assertFalse(fbp.co_flow(self._uid))
        self.assertIsNone(approval_gate.get_pending(self._uid))


if __name__ == "__main__":
    unittest.main()
