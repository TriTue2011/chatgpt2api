"""Người dùng bấm "Trả lời" vào một tin cũ rồi hỏi tiếp — bot phải thấy tin đó.

Zalo cá nhân đính tin được trích ở `data.quote` (zca-js), Zalo Bot đi khuôn
Telegram nên nằm ở `reply_to_message`. Trước đây cả hai đều bị bỏ qua, nên bot
nhận được đúng câu "cái này sao rồi" mà không biết "cái này" là gì.

Bất biến quan trọng: đoạn trích KHÔNG được nhập vào `user_text`. Mọi tầng tra
cứu phía sau (searxng, federated_search, RAG) lấy nguyên văn `user_text` làm
truy vấn, nên trộn vào đó là đi tra cứu cả đoạn trích.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import zalo_bot as zb  # noqa: E402
from services import zalo_personal as zp  # noqa: E402


class ZaloCaNhanTrichDanTests(unittest.TestCase):
    """`_parse_event` phải rút được `data.quote` của zca-js."""

    def test_trich_tin_cua_bot(self) -> None:
        luc = time.time() - 3600
        ev = zp._parse_event({
            "_accountId": "bot-own-id",
            "threadId": "t1",
            "data": {
                "uidFrom": "user-9",
                "dName": "Anh Tú",
                "content": "vụ đó giờ sao rồi",
                "msgId": "m2",
                "quote": {
                    "ownerId": "bot-own-id",
                    "fromD": "Mít Bắp",
                    "msg": "Hôm nay có tin về vụ cháy trên đường Lê Quang Đạo",
                    "ts": int(luc * 1000),
                },
            },
        })
        self.assertEqual(ev["text"], "vụ đó giờ sao rồi")
        self.assertIn("Lê Quang Đạo", ev["trich_dan"])
        # Tin được trích do CHÍNH tài khoản bot gửi → nói rõ để model khỏi tưởng
        # là lời người dùng.
        self.assertIn("chính em (bot)", ev["trich_dan"])
        self.assertIn(time.strftime("%d/%m/%Y", time.localtime(luc)), ev["trich_dan"])

    def test_trich_tin_cua_nguoi_khac(self) -> None:
        ev = zp._parse_event({
            "_accountId": "bot-own-id",
            "threadId": "t1",
            "data": {"uidFrom": "user-9", "content": "ý này là sao",
                     "quote": {"ownerId": "user-3", "fromD": "Chị Lan",
                               "msg": "mai họp lúc 9h nhé"}},
        })
        self.assertIn("Chị Lan", ev["trich_dan"])
        self.assertIn("mai họp lúc 9h", ev["trich_dan"])

    def test_khong_trich_thi_rong(self) -> None:
        ev = zp._parse_event({"_accountId": "a", "threadId": "t1",
                              "data": {"uidFrom": "u", "content": "chào em"}})
        self.assertEqual(ev["trich_dan"], "")

    def test_trich_anh_khong_co_chu(self) -> None:
        """Trích một tấm ảnh: `msg` rỗng nhưng vẫn phải báo là có đính kèm."""
        ev = zp._parse_event({
            "_accountId": "a", "threadId": "t1",
            "data": {"uidFrom": "u", "content": "cái này là gì",
                     "quote": {"ownerId": "u2", "fromD": "Bạn",
                               "msg": "", "attach": '{"href":"http://x/a.jpg"}'}},
        })
        self.assertIn("đính kèm", ev["trich_dan"])


class ZaloBotTrichDanTests(unittest.TestCase):
    """`_extract_quote` phải rút được tin được trả lời ở khuôn Zalo Bot."""

    def test_reply_to_message_khuon_telegram(self) -> None:
        luc = int(time.time() - 7200)
        out = zb._extract_quote({
            "text": "vụ đó giờ sao rồi",
            "reply_to_message": {
                "text": "Hôm nay có tin về vụ cháy trên đường Lê Quang Đạo",
                "from": {"display_name": "Mít Bắp", "is_bot": True},
                "date": luc,
            },
        })
        self.assertIn("Lê Quang Đạo", out)
        self.assertIn("chính em (bot)", out)
        self.assertIn(time.strftime("%d/%m/%Y", time.localtime(luc)), out)

    def test_khoa_quote_thay_cho_reply_to_message(self) -> None:
        out = zb._extract_quote({"quote": {"msg": "mai họp lúc 9h nhé",
                                           "fromD": "Chị Lan"}})
        self.assertIn("Chị Lan", out)
        self.assertIn("mai họp lúc 9h", out)

    def test_moc_thoi_gian_mili_giay(self) -> None:
        """`ts` mili-giây phải được nhận ra, không bị đọc thành năm 56xxx."""
        luc = time.time() - 60
        out = zb._extract_quote({"quote": {"msg": "x", "ts": int(luc * 1000)}})
        self.assertIn(time.strftime("%d/%m/%Y", time.localtime(luc)), out)

    def test_khong_tra_loi_thi_rong(self) -> None:
        self.assertEqual(zb._extract_quote({"text": "chào em"}), "")
        self.assertEqual(zb._extract_quote({}), "")

    def test_process_update_day_trich_dan_sang_worker(self) -> None:
        """Đoạn trích phải đi TỚI worker — nối dây hụt là tính năng chết lặng."""
        zb._seen_ids.clear()
        ghi: dict = {}

        def _bat(fn, *args, **kwargs):
            ghi["args"] = args
            return True

        with mock.patch.object(zb, "_zalo_worker", _bat):
            ok = zb.process_update({"message": {
                "message_id": "m1", "chat": {"id": "c1"}, "text": "vụ đó sao rồi",
                "reply_to_message": {"text": "tin về vụ cháy Lê Quang Đạo",
                                     "from": {"display_name": "Mít Bắp"}},
            }}, {"token": "t"})
        self.assertTrue(ok)
        # Tham số cuối là trich_dan; câu người dùng (tham số đầu) phải NGUYÊN VẸN.
        self.assertIn("Lê Quang Đạo", ghi["args"][-1])
        self.assertEqual(ghi["args"][0], "vụ đó sao rồi")


class OrchestratorNhanTrichDanTests(unittest.TestCase):
    """Điểm đấu nối: `trich_dan` phải tới được system prompt, và KHÔNG lẫn vào
    `user_text` (thứ được đem đi tra cứu nguyên văn ở mọi tầng phía sau)."""

    def test_doan_trich_vao_system_prompt_khong_vao_cau_hoi(self) -> None:
        import services.agent.orchestrator as orch
        from test._fakes import install_data_dir

        xong = {"choices": [{"message": {"content": "Dạ vụ đó đã dập tắt ạ."}}]}
        with install_data_dir():
            with mock.patch.object(orch, "call_model", return_value=xong) as fake:
                orch.orchestrate(
                    "vụ đó giờ sao rồi", "zalo_trichdan",
                    trich_dan="chính em (bot) lúc 17:39 29/08/2026 đã nhắn: "
                              "“tin về vụ cháy đường Lê Quang Đạo”",
                )
        messages = fake.call_args[0][1]
        sys_prompt = messages[0]["content"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("TRÍCH DẪN", sys_prompt)
        self.assertIn("Lê Quang Đạo", sys_prompt)
        # Lượt của người dùng phải NGUYÊN VĂN, không bị nối thêm đoạn trích.
        luot_nguoi = [m for m in messages if m.get("role") == "user"][-1]
        self.assertEqual(luot_nguoi["content"], "vụ đó giờ sao rồi")

    def test_khong_trich_thi_prompt_khong_co_khoi_do(self) -> None:
        import services.agent.orchestrator as orch
        from test._fakes import install_data_dir

        xong = {"choices": [{"message": {"content": "Dạ em nghe ạ."}}]}
        with install_data_dir():
            with mock.patch.object(orch, "call_model", return_value=xong) as fake:
                orch.orchestrate("chào em", "zalo_khongtrich")
        self.assertNotIn("TRÍCH DẪN", fake.call_args[0][1][0]["content"])


class LucNaoTests(unittest.TestCase):
    """`search_history` phải kèm thời điểm — hỏi "cái đó lúc nào" mới trả lời được."""

    def test_dinh_dang_kem_khoang_cach(self) -> None:
        from services.agent import capabilities as caps
        s = caps._luc_nao(time.time() - 3 * 86400)
        self.assertIn("3 ngày trước", s)
        s2 = caps._luc_nao(time.time() - 120)
        self.assertIn("2 phút trước", s2)
        self.assertEqual(caps._luc_nao(0), "")
        self.assertEqual(caps._luc_nao(None), "")

    def test_ket_qua_tim_kiem_co_thoi_gian(self) -> None:
        from services.agent import capabilities as caps
        luc = time.time() - 86400
        with mock.patch("services.agent.session.search",
                        return_value=[{"role": "user", "content": "sân nhỏ cỏ đen là gì",
                                       "created_at": luc}]):
            out = caps._h_search_history({"query": "sân nhỏ cỏ đen"},
                                         {"user_id": "zalo_c1"})
        self.assertIn("sân nhỏ cỏ đen", out["text"])
        self.assertIn("1 ngày trước", out["text"])
        self.assertIn(time.strftime("%d/%m/%Y", time.localtime(luc)), out["text"])


if __name__ == "__main__":
    unittest.main()
