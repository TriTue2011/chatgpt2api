"""Hai ô mới của tab «Lọc thread»: tag riêng để chuyển tiếp, và tắt hẳn ChatGPT.

TAG RIÊNG (`thread_forward_filters[...].keyword`) — «bắt buộc tag» (`@bot`) là
để GỌI AI, còn tag chuyển tiếp (`@n8n`) là để ĐẨY ĐI CHỖ KHÁC rồi AI im: hai
việc ngược nhau nên phải hai ô. Bộ test giữ:

  1. Bộ chuẩn hoá config GIỮ LẠI trường `keyword`. Đây là chỗ từng nuốt mất
     `reply_to_self` khiến bấm Lưu xong tải lại là mất cấu hình.
  2. Bản ghi CỤ THỂ NHẤT có khai từ khóa thì thắng (user > topic > nhóm), và
     bản ghi bỏ trống thì đi tiếp xuống bản ghi rộng hơn chứ không chặn.
  3. Không khai gì → '' → caller giữ nguyên nếp cũ (dùng chung từ khóa của ô
     «bắt buộc tag»), nên cấu hình đang chạy không đổi hành vi.

TẮT HẲN CHATGPT (`thread_mention_filters[...].ai_off`) — trước đây muốn AI im
chỉ có hai đường vòng: bật chuyển tiếp nuốt hết (bắt buộc có URL), hoặc chặn
thread (nhưng chặn nằm TRƯỚC bước chuyển tiếp nên webhook chết theo). Bộ test
giữ: bật thì tắt, không khai thì AI vẫn chạy, bản ghi cũ không có cờ vẫn chạy,
chuẩn hoá giữ được cờ mà không nhồi trường thừa khi tắt, và cờ này không đụng
tới bộ lọc tag sẵn có.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class ChuanHoaGiuKeywordTests(unittest.TestCase):
    def test_giu_lai_keyword(self):
        from services.config import _normalize_thread_forward_filters as chuan
        ra = chuan({"zalop:acc1:th1": {
            "enabled": True, "url": "http://n8n/x", "tag_mode": True,
            "keyword": "  @n8n  ",
        }})
        self.assertEqual(ra["zalop:acc1:th1"], {
            "enabled": True, "url": "http://n8n/x", "tag_mode": True,
            "keyword": "@n8n",
        })

    def test_ban_ghi_cu_khong_co_keyword_van_doc_duoc(self):
        from services.config import _normalize_thread_forward_filters as chuan
        ra = chuan({"tg:bot1:th1": {"enabled": True, "url": "http://x", "tag_mode": False}})
        self.assertEqual(ra["tg:bot1:th1"]["keyword"], "")


class ForwardKeywordForTests(unittest.TestCase):
    def _cfg(self, m):
        return {"thread_forward_filters": m}

    def test_lay_tu_ban_ghi_thread(self):
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get", return_value=self._cfg({
                "zalop:acc1:th1": {"enabled": True, "url": "u", "keyword": "@n8n"}})):
            self.assertEqual(
                caps.forward_keyword_for("zalop", "acc1", "th1", "u9"), "@n8n")

    def test_ban_ghi_user_thang_ban_ghi_thread(self):
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get", return_value=self._cfg({
                "zalop:acc1:th1": {"enabled": True, "url": "u", "keyword": "@nhom"},
                "zalop:acc1:th1:u9": {"enabled": True, "url": "u", "keyword": "@rieng"}})):
            self.assertEqual(
                caps.forward_keyword_for("zalop", "acc1", "th1", "u9"), "@rieng")

    def test_user_bo_trong_thi_lan_xuong_thread(self):
        # Bỏ trống = "không khai", không phải "cấm kế thừa".
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get", return_value=self._cfg({
                "zalop:acc1:th1": {"enabled": True, "url": "u", "keyword": "@nhom"},
                "zalop:acc1:th1:u9": {"enabled": True, "url": "u", "keyword": ""}})):
            self.assertEqual(
                caps.forward_keyword_for("zalop", "acc1", "th1", "u9"), "@nhom")

    def test_khong_khai_gi_thi_rong(self):
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get", return_value={}):
            self.assertEqual(
                caps.forward_keyword_for("zalop", "acc1", "th1", "u9"), "")

    def test_khong_lam_hong_forward_rule_for(self):
        # Thêm trường mới không được đụng tới URL/tag_mode đang chạy.
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get", return_value=self._cfg({
                "zalop:acc1:th1": {"enabled": True, "url": "http://u",
                                   "tag_mode": True, "keyword": "@n8n"}})):
            self.assertEqual(
                caps.forward_rule_for("zalop", "acc1", "th1", None),
                ("http://u", True))


class AiOffTests(unittest.TestCase):
    """Cờ TẮT HẲN ChatGPT cho một thread."""

    def _cfg(self, rec):
        return {"thread_mention_filters": {"zalop:acc1:th1": rec}}

    def test_bat_thi_tat_ai(self):
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get",
                        return_value=self._cfg({"ai_off": True})):
            self.assertTrue(caps.ai_off_for("zalop", "acc1", "th1"))

    def test_khong_cau_hinh_thi_ai_van_chay(self):
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get", return_value={}):
            self.assertFalse(caps.ai_off_for("zalop", "acc1", "th1"))

    def test_ban_ghi_cu_khong_co_co_thi_ai_van_chay(self):
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get",
                        return_value=self._cfg({"required": True, "keyword": "@bot"})):
            self.assertFalse(caps.ai_off_for("zalop", "acc1", "th1"))

    def test_chuan_hoa_giu_lai_ai_off(self):
        from services.config import _normalize_thread_mention_filters as chuan
        ra = chuan({"zalop:acc1:th1": {"required": True, "keyword": "@bot", "ai_off": True}})
        self.assertTrue(ra["zalop:acc1:th1"]["ai_off"])

    def test_chuan_hoa_khong_ghi_co_khi_tat(self):
        # Tắt là mặc định → không nhồi trường thừa vào mọi bản ghi.
        from services.config import _normalize_thread_mention_filters as chuan
        ra = chuan({"zalop:acc1:th1": {"required": True, "keyword": "@bot"}})
        self.assertNotIn("ai_off", ra["zalop:acc1:th1"])

    def test_khong_dam_vao_bo_loc_tag_san_co(self):
        from services.agent import capabilities as caps
        with mock.patch("services.config.config.get", return_value=self._cfg(
                {"required": True, "keyword": "@bot", "ai_off": True})):
            self.assertEqual(caps.mention_required_for("zalop", "acc1", "th1"),
                             (True, "@bot"))


if __name__ == "__main__":
    unittest.main()
