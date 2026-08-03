"""Phạm vi dữ liệu đi ĐÚNG QUA CHỖ GHÉP TẦNG: adapter → orchestrator ctx → tool.

Vì sao có file này. Lần làm scope trước (4 commit, revert ở `e68ecba`) có 37 test
xanh mà vẫn gãy khi chạy thật: chúng chỉ khoá TẦNG QUY TẮC — hàm tính phạm vi
đúng, nhưng chỗ ghép hai tầng thì sai. Cụ thể chuỗi khoá phiên bị đổi hình dạng,
và những nơi phía dưới đang PHÂN TÍCH chuỗi đó (`capabilities._channel_of`,
`reminders.channel_of`) hiểu sai → Zalo bị nhận thành Telegram, lịch mới lưu sai
nơi nhận, memory tắt hẳn.

Nên file này không test hàm phạm vi (đã có test_pham_vi_du_lieu.py). Nó gọi
CHÍNH handler tool với CHÍNH `ctx` mà orchestrator dựng, và khoá luôn cái giả
định đã làm gãy lần trước: KHOÁ PHIÊN KHÔNG ĐỔI HÌNH DẠNG.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import capabilities as caps  # noqa: E402
from services.agent import scope  # noqa: E402

# Đúng `ctx` orchestrator dựng (services/agent/orchestrator.py:1105).
def _ctx(user_id: str) -> dict:
    return {"user_id": user_id, "user_message": "", "auto_approve": False,
            "is_admin": False}


# Khoá phiên các adapter đang sinh — lấy nguyên hình dạng từ mã adapter.
KHOA_PHIEN = {
    "tg 1-1": "555",
    "tg nhóm": "-100:u9",
    "tg topic": "-100#7:u9",
    "zalo": "zalo_123:u456",
    "zalop": "zalop_987:u654",
    "email": "email_bo_abc123def456",
}


class KhoaPhienKhongDoiHinhDang(unittest.TestCase):
    """Chốt hồi quy của lần gãy trước — cả hai nơi phân tích khoá phải còn đúng."""

    def test_channel_of_cua_capabilities_van_dung(self):
        self.assertEqual(caps._channel_of(_ctx("zalo_123:u456")), "zalo")
        self.assertEqual(caps._channel_of(_ctx("zalop_987")), "zalop")
        self.assertEqual(caps._channel_of(_ctx("-100#7:u9")), "tg")
        self.assertEqual(caps._channel_of(_ctx("")), "")

    def test_channel_of_cua_reminders_van_dung(self):
        from services.agent import reminders
        self.assertEqual(reminders.channel_of("zalo_123"), ("zalo", "123"))
        self.assertEqual(reminders.channel_of("zalop_987"), ("zalop", "987"))
        self.assertEqual(reminders.channel_of("-100"), ("tg", "-100"))

    def test_hai_noi_phan_tich_khoa_dong_y_ve_kenh(self):
        """scope.py chỉ ĐỌC khoá phiên → phải ra cùng kênh với nơi cũ."""
        for ten, khoa in KHOA_PHIEN.items():
            with self.subTest(ten):
                sc = scope.tach_khoa_phien(khoa)
                if sc.kenh == "mail":
                    continue  # email không đi qua channel_of
                self.assertEqual(sc.kenh, caps._channel_of(_ctx(khoa)), ten)


class ToolWikiNhanPhamViTuCtx(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="wiki-tool-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from services.agent import wiki as w
        self.w = w
        w._reset_for_tests(self.tmp)
        self.cfg = {}
        p = mock.patch("services.config.config.get", side_effect=lambda: self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def _ingest(self, khoa_phien: str, noi_dung: str) -> str:
        out = caps._h_ingest({"content": noi_dung}, _ctx(khoa_phien))
        self.assertIn("Đã thu nạp", out["text"])
        return out["text"]

    def test_ingest_roi_search_qua_tool_khong_lot_sang_chat_khac(self):
        self._ingest("555", "mã cửa nhà là 8642, đừng cho ai biết nhé")
        thay = caps._h_wiki_search({"query": "mã cửa"}, _ctx("555"))
        self.assertIn("mã cửa", thay["text"].lower())
        khong = caps._h_wiki_search({"query": "mã cửa"}, _ctx("556"))
        self.assertIn("Không thấy ghi chú", khong["text"])

    def test_ingest_roi_search_khong_lot_sang_KENH_khac(self):
        """Cùng số chat, khác kênh — 'zalo_555' không phải Telegram '555'."""
        self._ingest("555", "lịch khám của mẹ ngày mai lúc chín giờ")
        khong = caps._h_wiki_search({"query": "lịch khám"}, _ctx("zalo_555"))
        self.assertIn("Không thấy ghi chú", khong["text"])

    def test_wiki_read_qua_tool_bi_chot_theo_slug(self):
        self._ingest("555", "số thẻ ngân hàng của bố là 1234 5678 9012")
        ds = caps._h_wiki_search({"query": ""}, _ctx("555"))["text"]
        slug = ds.split("`")[1]
        self.assertIn("1234", caps._h_wiki_read({"slug": slug}, _ctx("555"))["text"])
        self.assertIn("Không có ghi chú",
                      caps._h_wiki_read({"slug": slug}, _ctx("556"))["text"])

    def test_nhom_chua_loc_user_thi_hai_thanh_vien_thay_chung(self):
        self._ingest("-100:u9", "phân công dọn nhà cuối tuần này")
        thay = caps._h_wiki_search({"query": "dọn nhà"}, _ctx("-100:u10"))
        self.assertIn("dọn nhà", thay["text"].lower())

    def test_nhom_co_loc_user_thi_khong_thay_chung(self):
        self.cfg = {"thread_user_filters": {"tg:-100:9": ["device"]}}
        self._ingest("-100:u9", "ghi chú riêng của tôi trong nhóm này")
        khong = caps._h_wiki_search({"query": "ghi chú riêng"}, _ctx("-100:u10"))
        self.assertIn("Không thấy ghi chú", khong["text"])

    def test_topic_khac_nhau_khong_thay_cua_nhau(self):
        self._ingest("-100#7:u9", "bài tập toán tuần này của lớp bốn")
        khong = caps._h_wiki_search({"query": "bài tập toán"}, _ctx("-100#8:u9"))
        self.assertIn("Không thấy ghi chú", khong["text"])

    def test_digest_qua_tool_theo_pham_vi(self):
        self.cfg = {"agent_wiki": {"digest_llm": False}}
        self._ingest("555", "mua hạt dẻ cho con mang đi học")
        self._ingest("556", "đóng tiền điện tháng này trước ngày mười")
        cua_555 = caps._h_wiki_digest({"op": "build"}, _ctx("555"))["text"]
        self.assertIn("hạt dẻ", cua_555)
        self.assertNotIn("tiền điện", cua_555)

    def test_duong_noi_bo_khong_co_khoa_phien_van_chay(self):
        """Scheduler / lối gọi nội bộ: ctx rỗng → phạm vi mặc định, không hỏng."""
        self._ingest("", "ghi chú do hệ thống tự tạo")
        out = caps._h_wiki_search({"query": "hệ thống"}, _ctx(""))
        self.assertIn("hệ thống", out["text"].lower())


class SuperContextKhongRoQuaSystemPrompt(unittest.TestCase):
    """Bó ngữ cảnh vào system prompt MỌI lượt — rò ở đây không cần gọi tool nào."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="wiki-sc-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from services.agent import wiki as w
        self.w = w
        w._reset_for_tests(self.tmp)
        self.cfg = {}
        p = mock.patch("services.config.config.get", side_effect=lambda: self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def test_wiki_cua_nguoi_khac_khong_vao_prompt(self):
        from services.agent import super_context as sc
        caps._h_ingest({"content": "mã cửa nhà là 8642, đừng cho ai biết"},
                       _ctx("555"))
        cua_minh = sc.build_bundle("555", "mã cửa nhà là gì")
        self.assertIn("mã cửa", cua_minh.lower())
        cua_nguoi_khac = sc.build_bundle("556", "mã cửa nhà là gì")
        self.assertNotIn("8642", cua_nguoi_khac)
        self.assertNotIn("mã cửa", cua_nguoi_khac.lower())

    def test_lich_khai_kenh_nhan_khong_vao_prompt_thread_khac(self):
        from services import calendar_connector as cc
        from services.agent import super_context as sc
        self.cfg = {"calendars": [{
            "id": "c1", "label": "Lịch gia đình", "enabled": True,
            "ics_url": "https://vi.du/lich.ics", "notify_targets": ["tg:-100"],
        }]}
        su_kien = [{"start": __import__("datetime").datetime(2026, 8, 5, 9, 0),
                    "summary": "Họp phụ huynh lớp 4A", "location": ""}]
        with mock.patch.object(cc, "fetch_events", return_value=su_kien):
            trong_nhom = sc.build_bundle("-100:u9", "hôm nay có việc gì")
            ngoai_nhom = sc.build_bundle("-200:u9", "hôm nay có việc gì")
        self.assertIn("Họp phụ huynh", trong_nhom)
        self.assertNotIn("Họp phụ huynh", ngoai_nhom)


if __name__ == "__main__":
    unittest.main()
