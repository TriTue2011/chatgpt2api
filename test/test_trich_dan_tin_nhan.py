"""Người dùng bấm "Trả lời" vào một tin cũ rồi hỏi tiếp — bot phải thấy tin đó.

Zalo cá nhân đính tin được trích ở `data.quote` (zca-js), Zalo Bot và Telegram
theo khuôn `reply_to_message`. Cả ba đường trước đây bỏ qua nội dung, nên bot
nhận đúng câu "cái này sao rồi" mà không biết "cái này" là gì.

Bất biến quan trọng: đoạn trích KHÔNG được nhập vào `user_text`. Mọi tầng tra
cứu phía sau (searxng, federated_search, RAG) lấy nguyên văn `user_text` làm
truy vấn, nên trộn vào đó là đi tra cứu cả đoạn trích.

Dự phòng: khi nền tảng chỉ kèm mốc thời gian mà KHÔNG kèm nội dung, tra lại
nội dung tin từ nhật ký phiên / sổ nhóm.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import zalo_bot as zb  # noqa: E402
from services import zalo_personal as zp  # noqa: E402
from services import telegram_bot as tg  # noqa: E402
from services.agent import trich_dan as td  # noqa: E402


class ZaloCaNhanRutTrichDanTests(unittest.TestCase):
    """`_parse_event` rút được `data.quote` của zca-js thành dict thô."""

    def test_trich_tin_cua_bot(self) -> None:
        luc = time.time() - 3600
        ev = zp._parse_event({
            "_accountId": "bot-own-id",
            "threadId": "t1",
            "data": {
                "uidFrom": "user-9", "dName": "Anh Tú",
                "content": "vụ đó giờ sao rồi", "msgId": "m2",
                "quote": {"ownerId": "bot-own-id", "fromD": "Mít Bắp",
                          "msg": "tin về vụ cháy đường Lê Quang Đạo",
                          "ts": int(luc * 1000)},
            },
        })
        self.assertEqual(ev["text"], "vụ đó giờ sao rồi")
        q = ev["trich_dan_raw"]
        self.assertIn("Lê Quang Đạo", q["noi_dung"])
        self.assertEqual(q["cua_ai"], "bot")   # so bằng ownerId, không phải tên
        self.assertAlmostEqual(q["ts"], luc, delta=1.0)

    def test_trich_tin_cua_nguoi_khac(self) -> None:
        ev = zp._parse_event({
            "_accountId": "bot-own-id", "threadId": "t1",
            "data": {"uidFrom": "user-9", "content": "ý này là sao",
                     "quote": {"ownerId": "user-3", "fromD": "Chị Lan",
                               "msg": "mai họp lúc 9h nhé"}},
        })
        self.assertEqual(ev["trich_dan_raw"]["cua_ai"], "Chị Lan")

    def test_khong_trich_thi_rong(self) -> None:
        ev = zp._parse_event({"_accountId": "a", "threadId": "t1",
                              "data": {"uidFrom": "u", "content": "chào em"}})
        self.assertEqual(ev["trich_dan_raw"], {})

    def test_trich_anh_khong_co_chu(self) -> None:
        ev = zp._parse_event({
            "_accountId": "a", "threadId": "t1",
            "data": {"uidFrom": "u", "content": "cái này là gì",
                     "quote": {"ownerId": "u2", "fromD": "Bạn", "msg": "",
                               "attach": '{"href":"http://x/a.jpg"}'}},
        })
        self.assertTrue(ev["trich_dan_raw"]["co_dinh_kem"])
        self.assertEqual(ev["trich_dan_raw"]["noi_dung"], "")


class ZaloBotRutTrichDanTests(unittest.TestCase):
    """`_extract_quote` rút được tin được trả lời ở khuôn Zalo Bot."""

    def test_reply_to_message_khuon_telegram(self) -> None:
        luc = int(time.time() - 7200)
        q = zb._extract_quote({
            "text": "vụ đó giờ sao rồi",
            "reply_to_message": {"text": "tin về vụ cháy đường Lê Quang Đạo",
                                 "from": {"display_name": "Mít Bắp", "is_bot": True},
                                 "date": luc},
        })
        self.assertIn("Lê Quang Đạo", q["noi_dung"])
        self.assertEqual(q["cua_ai"], "bot")
        self.assertAlmostEqual(q["ts"], luc, delta=1.0)

    def test_khoa_quote_thay_cho_reply_to_message(self) -> None:
        q = zb._extract_quote({"quote": {"msg": "mai họp lúc 9h nhé", "fromD": "Chị Lan"}})
        self.assertEqual(q["noi_dung"], "mai họp lúc 9h nhé")
        self.assertEqual(q["cua_ai"], "Chị Lan")

    def test_moc_thoi_gian_mili_giay_thanh_giay(self) -> None:
        luc = time.time() - 60
        q = zb._extract_quote({"quote": {"msg": "x", "ts": int(luc * 1000)}})
        self.assertAlmostEqual(q["ts"], luc, delta=1.0)  # mili-giây → giây

    def test_khong_tra_loi_thi_rong(self) -> None:
        self.assertEqual(zb._extract_quote({"text": "chào em"}), {})
        self.assertEqual(zb._extract_quote({}), {})

    def test_process_update_day_trich_dan_sang_worker(self) -> None:
        zb._seen_ids.clear()
        ghi: dict = {}
        with mock.patch.object(zb, "_zalo_worker",
                               lambda fn, *a, **k: ghi.setdefault("args", a) or True):
            ok = zb.process_update({"message": {
                "message_id": "m1", "chat": {"id": "c1"}, "text": "vụ đó sao rồi",
                "reply_to_message": {"text": "tin về vụ cháy Lê Quang Đạo",
                                     "from": {"display_name": "Mít Bắp"}},
            }}, {"token": "t"})
        self.assertTrue(ok)
        # Tham số cuối là dict trích dẫn; câu người dùng (tham số đầu) NGUYÊN VẸN.
        self.assertIn("Lê Quang Đạo", ghi["args"][-1]["noi_dung"])
        self.assertEqual(ghi["args"][0], "vụ đó sao rồi")


class TelegramRutTrichDanTests(unittest.TestCase):
    """`_extract_quote` rút `reply_to_message` của Telegram."""

    def test_reply_to_message_day_du(self) -> None:
        luc = int(time.time() - 300)
        q = tg._extract_quote({
            "text": "cái đó xong chưa",
            "reply_to_message": {"text": "đang xử lý phần lồng tiếng",
                                 "from": {"first_name": "Mít", "last_name": "Bắp",
                                          "is_bot": True},
                                 "date": luc},
        })
        self.assertEqual(q["noi_dung"], "đang xử lý phần lồng tiếng")
        self.assertEqual(q["cua_ai"], "bot")
        self.assertAlmostEqual(q["ts"], luc, delta=1.0)   # Telegram: date là GIÂY

    def test_reply_media_khong_chu(self) -> None:
        q = tg._extract_quote({"text": "cái này là gì",
                               "reply_to_message": {"photo": [{"file_id": "x"}],
                                                    "from": {"first_name": "Bạn"}}})
        self.assertTrue(q["co_dinh_kem"])
        self.assertEqual(q["noi_dung"], "")

    def test_khong_reply_thi_rong(self) -> None:
        self.assertEqual(tg._extract_quote({"text": "chào"}), {})


class MoTaVaDuPhongTests(unittest.TestCase):
    """`trich_dan.mo_ta` dựng câu, và tra nhật ký khi thiếu nội dung."""

    def test_co_noi_dung_thi_dung_thang(self) -> None:
        luc = time.time() - 86400
        s = td.mo_ta({"noi_dung": "tin cháy Lê Quang Đạo", "ts": luc, "cua_ai": "bot"})
        self.assertIn("chính em (bot)", s)
        self.assertIn("Lê Quang Đạo", s)
        self.assertIn(time.strftime("%d/%m/%Y", time.localtime(luc)), s)

    def test_rong_thi_tra_chuoi_rong(self) -> None:
        self.assertEqual(td.mo_ta(None), "")
        self.assertEqual(td.mo_ta({}), "")
        self.assertEqual(td.mo_ta({"noi_dung": "", "co_dinh_kem": False}), "")

    def test_du_phong_lay_noi_dung_tu_phien(self) -> None:
        """Thiếu nội dung + có mốc thời gian → tra lại từ session.turns."""
        luc = time.time() - 120
        with mock.patch("services.agent.session.turn_gan_ts",
                        return_value={"role": "assistant",
                                      "content": "tin về vụ cháy Lê Quang Đạo",
                                      "created_at": luc}) as fake:
            s = td.mo_ta({"noi_dung": "", "ts": luc, "cua_ai": "", "co_dinh_kem": True},
                         session_key="zalo_c1")
        fake.assert_called_once()
        self.assertIn("Lê Quang Đạo", s)
        self.assertIn("chính em (bot)", s)   # role=assistant → bot

    def test_du_phong_roi_xuong_so_nhom(self) -> None:
        """Phiên không có → thử sổ nhóm (chatlog)."""
        luc = time.time() - 300
        with mock.patch("services.agent.session.turn_gan_ts", return_value=None), \
             mock.patch("services.agent.chatlog.tin_gan_ts",
                        return_value={"ts": luc, "sender": "Chị Lan",
                                      "text": "mai họp 9h nhé"}):
            s = td.mo_ta({"noi_dung": "", "ts": luc, "co_dinh_kem": True},
                         session_key="zalo_c1")
        self.assertIn("Chị Lan", s)
        self.assertIn("mai họp 9h", s)

    def test_khong_session_key_thi_khong_tra(self) -> None:
        """Không có khoá phiên thì không tra nhật ký, chỉ còn câu chữa cháy."""
        s = td.mo_ta({"noi_dung": "", "ts": time.time(), "co_dinh_kem": True})
        self.assertIn("đính kèm", s)


class OrchestratorNhanTrichDanTests(unittest.TestCase):
    """Điểm đấu nối: `trich_dan` tới được system prompt, KHÔNG lẫn vào user_text."""

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
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("TRÍCH DẪN", messages[0]["content"])
        self.assertIn("Lê Quang Đạo", messages[0]["content"])
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
    """`search_history` kèm thời điểm — hỏi "cái đó lúc nào" mới trả lời được."""

    def test_dinh_dang_kem_khoang_cach(self) -> None:
        from services.agent import capabilities as caps
        self.assertIn("3 ngày trước", caps._luc_nao(time.time() - 3 * 86400))
        self.assertIn("2 phút trước", caps._luc_nao(time.time() - 120))
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
