"""Kênh Zalo Bot: công tắc webhook ⟷ long-poll, xác thực secret, offset.

Bất biến được khoá ở đây (docs bot.zapps.me/docs/apis/getUpdates: "Phương thức
getUpdates sẽ không hoạt động nếu bạn đã thiết lập Webhook trước đó"):
KHÔNG BAO GIỜ để webhook và long-poll cùng bật.
"""
from __future__ import annotations

import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import zalo_bot as zb  # noqa: E402

TOKEN_A = "111111:aaaaaaaaaaaaaaaaaaaa"
TOKEN_B = "222222:bbbbbbbbbbbbbbbbbbbb"
BOT_A = {"token": TOKEN_A, "enabled": True, "label": "botA"}
BOT_B = {"token": TOKEN_B, "enabled": True, "label": "botB"}


def _reset_module_state() -> None:
    """Trạng thái poll là module-level → test rò sang nhau nếu không dọn."""
    zb._poll_threads.clear()
    zb._poll_stop.clear()
    zb._seen_ids.clear()


class ZaloBotSecretTests(unittest.TestCase):
    """Xác thực header X-Bot-Api-Secret-Token."""

    def setUp(self) -> None:
        _reset_module_state()

    def test_secret_dung_tra_ve_dung_bot(self) -> None:
        with mock.patch.object(zb, "_bots", return_value=[BOT_A, BOT_B]), \
             mock.patch.object(zb.config, "get", return_value={}):
            bot = zb.verify_webhook_secret(zb._webhook_secret_for(TOKEN_B))
            self.assertIsNotNone(bot)
            self.assertEqual(bot["token"], TOKEN_B)  # phải là bot B, không phải bot[0]

    def test_secret_sai_hoac_rong_bi_tu_choi(self) -> None:
        with mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb.config, "get", return_value={}):
            self.assertIsNone(zb.verify_webhook_secret("sai-be-bet"))
            self.assertIsNone(zb.verify_webhook_secret(""))
            self.assertIsNone(zb.verify_webhook_secret(None))
            # Tiền tố đúng nhưng thiếu đuôi vẫn phải trượt (chống dò từng byte).
            full = zb._webhook_secret_for(TOKEN_A)
            self.assertIsNone(zb.verify_webhook_secret(full[:-1]))

    def test_mot_bot_khong_con_duong_de_qua_lenient(self) -> None:
        """Bản trước: chỉ 1 bot thì secret nào cũng cho qua — lỗ bảo mật."""
        with mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb.config, "get", return_value={}):
            self.assertIsNone(zb.verify_webhook_secret("bat-ky"))

    def test_bot_tat_khong_nhan_dien_duoc(self) -> None:
        with mock.patch.object(zb, "_bots", return_value=[{**BOT_A, "enabled": False}]), \
             mock.patch.object(zb.config, "get", return_value={}):
            self.assertIsNone(zb.verify_webhook_secret(zb._webhook_secret_for(TOKEN_A)))

    def test_secret_dai_hop_le_va_on_dinh(self) -> None:
        with mock.patch.object(zb.config, "get", return_value={}):
            s = zb._webhook_secret_for(TOKEN_A)
            self.assertEqual(s, zb._webhook_secret_for(TOKEN_A))  # ổn định giữa 2 lần gọi
            self.assertTrue(8 <= len(s) <= 256)  # docs setWebhook: 8–256 ký tự
            self.assertNotEqual(s, zb._webhook_secret_for(TOKEN_B))  # per-token
            self.assertNotIn(TOKEN_A, s)  # không lộ token trong secret
        with mock.patch.object(zb.config, "get", return_value={"zalo_webhook_secret": "muoi"}):
            self.assertNotEqual(zb._webhook_secret_for(TOKEN_A), s)  # muối có tác dụng


class ZaloBotProcessUpdateTests(unittest.TestCase):
    """process_update: payload méo không được làm chết luồng nhận tin."""

    def setUp(self) -> None:
        _reset_module_state()

    def test_payload_thieu_message_tra_false_khong_no(self) -> None:
        with mock.patch.object(zb, "_process_message") as pm:
            for body in ({}, {"ok": True}, {"ok": True, "result": {}},
                         {"result": {"event_name": "x"}}, {"message": {}},
                         None, "khong-phai-dict", {"result": "khong-phai-dict"}):
                self.assertFalse(zb.process_update(body, BOT_A), repr(body))
            pm.assert_not_called()

    def test_message_thieu_chat_id_tra_false(self) -> None:
        with mock.patch.object(zb, "_process_message") as pm:
            body = {"ok": True, "result": {"message": {"message_id": "m1", "text": "hi"}}}
            self.assertFalse(zb.process_update(body, BOT_A))
            pm.assert_not_called()

    def test_nhan_ca_hai_khuon_webhook_va_getupdates(self) -> None:
        msg = {"message_id": "m9", "text": "chào", "chat": {"id": "c1"}}
        for body in ({"ok": True, "result": {"message": msg}}, {"message": msg}):
            _reset_module_state()
            with mock.patch.object(zb, "_process_message") as pm:
                self.assertTrue(zb.process_update(body, BOT_A))
                for th in threading.enumerate():
                    if th is not threading.current_thread() and th.daemon:
                        th.join(timeout=2)
                pm.assert_called_once()
                self.assertEqual(pm.call_args[0][1], "c1")  # chat_id

    def test_dedupe_cung_message_id(self) -> None:
        body = {"result": {"message": {"message_id": "m1", "text": "a", "chat": {"id": "c1"}}}}
        with mock.patch.object(zb, "_process_message"):
            self.assertTrue(zb.process_update(body, BOT_A))
            self.assertFalse(zb.process_update(body, BOT_A))  # retry của Zalo → bỏ


class ZaloBotOffsetTests(unittest.TestCase):
    """offset = max(update_id) + 1, và update thiếu update_id không phá vòng poll."""

    def test_offset_tang_dung(self) -> None:
        self.assertEqual(zb._next_offset([{"update_id": 5}], 0), 6)
        self.assertEqual(zb._next_offset([{"update_id": 5}, {"update_id": 9}], 0), 10)
        self.assertEqual(zb._next_offset([{"result": {"update_id": 12}}], 0), 13)

    def test_offset_khong_bao_gio_tut_lui(self) -> None:
        self.assertEqual(zb._next_offset([{"update_id": 3}], 100), 100)

    def test_update_id_thieu_hoac_rac_bi_bo_qua(self) -> None:
        self.assertEqual(zb._next_offset([{"message": {}}], 7), 7)
        self.assertEqual(zb._next_offset([{"update_id": None}, "rac", None], 7), 7)
        self.assertEqual(zb._next_offset([{"update_id": "khong-phai-so"}], 7), 7)
        # Rác lẫn hàng thật: vẫn phải tiến theo cái thật.
        self.assertEqual(zb._next_offset([{"update_id": "x"}, {"update_id": 41}], 7), 42)

    def test_offset_duoc_gui_kem_getupdates(self) -> None:
        """Vòng poll phải truyền offset đã tiến vào lượt getUpdates kế tiếp."""
        calls: list[dict] = []
        upd = {"update_id": 4, "message": {"message_id": "m1", "chat": {"id": "c1"}}}

        def fake_api(method, data=None, timeout=20, max_retries=2):
            if method != "getUpdates":
                return {"ok": True, "result": {}}
            calls.append(dict(data or {}))
            if len(calls) == 1:
                return {"ok": True, "result": [upd]}
            raise SystemExit  # thoát vòng while sau khi đã bắt được lượt thứ 2

        with mock.patch.object(zb, "_api_call", side_effect=fake_api), \
             mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb, "webhook_enabled", return_value=False), \
             mock.patch.object(zb, "_handle_update"):
            _reset_module_state()
            with self.assertRaises(SystemExit):
                zb._poll_loop(dict(BOT_A))
        self.assertNotIn("offset", calls[0])   # lượt đầu chưa biết offset
        self.assertEqual(calls[1]["offset"], 5)  # 4 + 1
        self.assertEqual(calls[0]["timeout"], 25)


class ZaloBotModeSwitchTests(unittest.TestCase):
    """Công tắc: bật webhook → không polling; tắt → polling, không webhook."""

    def setUp(self) -> None:
        _reset_module_state()

    def tearDown(self) -> None:
        _reset_module_state()

    def test_webhook_bat_thi_start_polling_tu_choi(self) -> None:
        with mock.patch.object(zb, "webhook_enabled", return_value=True), \
             mock.patch.object(zb, "_bots", return_value=[BOT_A]):
            self.assertFalse(zb.start_polling())
            self.assertEqual(zb._poll_threads, {})

    def test_apply_mode_bat_goi_setwebhook_va_khong_polling(self) -> None:
        calls: list[tuple] = []

        def fake_api(method, data=None, timeout=20, max_retries=2):
            calls.append((method, data))
            return {"ok": True, "result": {"url": "https://x.test/api/zalo-bot/webhook"}}

        with mock.patch.object(zb, "webhook_enabled", return_value=True), \
             mock.patch.object(zb, "webhook_url", return_value="https://x.test/api/zalo-bot/webhook"), \
             mock.patch.object(zb, "_bots", return_value=[BOT_A, BOT_B]), \
             mock.patch.object(zb.config, "get", return_value={}), \
             mock.patch.object(zb, "_api_call", side_effect=fake_api):
            out = zb.apply_mode()

        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "webhook")
        self.assertFalse(out["polling"])
        self.assertEqual(zb._poll_threads, {})  # không luồng poll nào được dựng
        methods = [m for m, _ in calls]
        self.assertEqual(methods, ["setWebhook", "setWebhook"])  # đúng 1 lần/bot
        self.assertNotIn("getUpdates", methods)
        for _, data in calls:
            self.assertTrue(data["url"].startswith("https://"))
            self.assertTrue(8 <= len(data["secret_token"]) <= 256)
        # Mỗi bot một secret khác nhau → nhận webhook là biết bot nào.
        self.assertNotEqual(calls[0][1]["secret_token"], calls[1][1]["secret_token"])

    def test_apply_mode_tat_goi_deletewebhook_va_bat_polling(self) -> None:
        calls: list[str] = []
        with mock.patch.object(zb, "webhook_enabled", return_value=False), \
             mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb, "_api_call", side_effect=lambda m, *a, **k: (
                 calls.append(m) or {"ok": True})), \
             mock.patch.object(zb, "_poll_loop"):
            out = zb.apply_mode()
            self.assertTrue(out["ok"])
            self.assertEqual(out["mode"], "long-polling")
            self.assertTrue(out["polling"])
            self.assertIn("deleteWebhook", calls)
            self.assertNotIn("setWebhook", calls)
            self.assertIn(TOKEN_A, zb._poll_threads)

    def test_register_webhook_khong_goi_mang_dong_bo_khi_tat(self) -> None:
        """Đường khởi động: `register_webhook()` chạy trong startup handler của
        FastAPI, nên chế độ long-poll KHÔNG được gọi deleteWebhook đồng bộ
        (urllib chặn 20s × 3 lần thử → Zalo chậm là treo cả boot)."""
        calls: list[str] = []
        with mock.patch.object(zb, "webhook_enabled", return_value=False), \
             mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb, "_api_call", side_effect=lambda m, *a, **k: (
                 calls.append(m) or {"ok": True})), \
             mock.patch.object(zb, "_poll_loop"):
            self.assertTrue(zb.register_webhook())
            self.assertEqual(calls, [])  # không request nào chạy trên luồng gọi
            self.assertIn(TOKEN_A, zb._poll_threads)  # nhưng poll vẫn được bật

    def test_register_webhook_van_setwebhook_khi_bat(self) -> None:
        """Chế độ webhook thì setWebhook BUỘC phải chạy lúc khởi động, kẻo
        Zalo không biết URL nào mà gửi (giống services/telegram_bot.py)."""
        calls: list[str] = []
        with mock.patch.object(zb, "webhook_enabled", return_value=True), \
             mock.patch.object(zb, "webhook_url", return_value="https://x.test/api/zalo-bot/webhook"), \
             mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb.config, "get", return_value={}), \
             mock.patch.object(zb, "_api_call", side_effect=lambda m, *a, **k: (
                 calls.append(m) or {"ok": True})):
            self.assertTrue(zb.register_webhook())
        self.assertEqual(calls, ["setWebhook"])

    def test_setwebhook_tu_choi_url_khong_https(self) -> None:
        """Docs setWebhook: 'URL nhận thông báo dạng HTTPS'."""
        with mock.patch.object(zb, "webhook_url", return_value="http://x.test/api/zalo-bot/webhook"), \
             mock.patch.object(zb, "_api_call") as api:
            r = zb.set_webhook(BOT_A)
            self.assertFalse(r["ok"])
            self.assertIn("HTTPS", r["description"])
            api.assert_not_called()  # không bắn request rác lên Zalo

    def test_setwebhook_tu_choi_khi_chua_co_url(self) -> None:
        with mock.patch.object(zb, "webhook_url", return_value=""), \
             mock.patch.object(zb, "_api_call") as api:
            self.assertFalse(zb.set_webhook(BOT_A)["ok"])
            api.assert_not_called()

    def test_poll_loop_tu_thoat_khi_webhook_duoc_bat(self) -> None:
        """Chuyển chế độ giữa lúc đang poll: luồng phải tự chết, không cần kill."""
        with mock.patch.object(zb, "webhook_enabled", return_value=True), \
             mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb, "_api_call", return_value={"ok": True}) as api:
            zb._poll_threads[TOKEN_A] = mock.Mock()
            zb._poll_loop(dict(BOT_A))
            self.assertNotIn(TOKEN_A, zb._poll_threads)
            self.assertNotIn("getUpdates", [c[0][0] for c in api.call_args_list])

    def test_poll_loop_tu_thoat_khi_co_dung_duoc_dat(self) -> None:
        with mock.patch.object(zb, "webhook_enabled", return_value=False), \
             mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb, "_api_call", return_value={"ok": True}) as api:
            zb._poll_stop[TOKEN_A] = threading.Event()
            zb._poll_stop[TOKEN_A].set()
            zb._poll_threads[TOKEN_A] = mock.Mock()
            zb._poll_loop(dict(BOT_A))
            self.assertNotIn(TOKEN_A, zb._poll_threads)
            self.assertNotIn("getUpdates", [c[0][0] for c in api.call_args_list])

    def test_stop_polling_ra_hieu_cho_moi_luong(self) -> None:
        with mock.patch.object(zb, "webhook_enabled", return_value=False), \
             mock.patch.object(zb, "_bots", return_value=[BOT_A, BOT_B]), \
             mock.patch.object(zb, "_poll_loop"):
            zb.start_polling()
            self.assertEqual(len(zb._poll_threads), 2)
        remaining = zb.stop_polling(join_timeout=0.5)
        self.assertEqual(remaining, 0)
        self.assertTrue(all(ev.is_set() for ev in zb._poll_stop.values()))

    def test_get_status_bao_dung_che_do(self) -> None:
        with mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb.config, "get",
                               return_value={"zalo_webhook_enabled": True,
                                             "zalo_webhook_url": "https://x.test/api/zalo-bot/webhook"}):
            st = zb.get_status()
            self.assertEqual(st["mode"], "webhook")
            self.assertTrue(st["webhook_enabled"])
            self.assertFalse(st["polling"])
        with mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb.config, "get", return_value={}):
            st = zb.get_status()
            self.assertEqual(st["mode"], "long-polling")
            self.assertFalse(st["webhook_enabled"])

    def test_webhook_url_ghep_tu_base_url(self) -> None:
        with mock.patch.object(zb.config, "get",
                               return_value={"base_url": "https://gw.test/"}):
            self.assertEqual(zb.webhook_url(), "https://gw.test/api/zalo-bot/webhook")
        with mock.patch.object(zb.config, "get", return_value={}), \
             mock.patch.object(zb, "_public_base", return_value=""):
            self.assertEqual(zb.webhook_url(), "")

    def test_set_webhook_enabled_luu_config_truoc_khi_ap_dung(self) -> None:
        """Lưu trước rồi áp: ngược lại thì luồng poll cũ đọc config còn thấy TẮT
        và sống lại ngay sau khi vừa bị dừng."""
        order: list[str] = []
        with mock.patch.object(zb.config, "update",
                               side_effect=lambda d: order.append(f"update:{d}")), \
             mock.patch.object(zb, "apply_mode", side_effect=lambda: order.append("apply") or {}):
            zb.set_webhook_enabled(True)
        self.assertEqual(order, ["update:{'zalo_webhook_enabled': True}", "apply"])


def _load_router_standalone():
    """Nạp `api/zalo_bot.py` mà KHÔNG chạy `api/__init__.py`.

    `api/__init__.py` kéo theo `api.app` → toàn bộ provider (PIL, tiktoken,
    sherpa-onnx…), nên chỉ để test một router lại phải dựng đủ nguyên gateway;
    trên môi trường Python < 3.13 thì còn không nạp nổi (`utils/pow.py` dùng
    `str | None` ở chữ ký, đánh giá ngay lúc import). Ở đây chèn stub
    `api.support.require_admin` — test này chỉ cần biết endpoint CÓ đi qua chốt
    admin hay không, còn hành vi thật của require_admin đã có test riêng.
    Trả (module, tên đã chèn vào sys.modules) để dọn lại sau.
    """
    import importlib.util
    import types

    from fastapi import HTTPException

    root = Path(__file__).resolve().parents[1]
    added: list[str] = []
    if "api" not in sys.modules:
        pkg = types.ModuleType("api")
        pkg.__path__ = [str(root / "api")]
        sys.modules["api"] = pkg
        added.append("api")
    if "api.support" not in sys.modules:
        sup = types.ModuleType("api.support")

        def require_admin(authorization):
            raise HTTPException(status_code=403, detail="cần quyền quản trị")

        sup.require_admin = require_admin
        sys.modules["api.support"] = sup
        added.append("api.support")
    spec = importlib.util.spec_from_file_location("_zalo_bot_router_under_test",
                                                 root / "api" / "zalo_bot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, added


class ZaloBotRouterTests(unittest.TestCase):
    """HTTP thật qua TestClient: secret sai → 403, đúng → 200."""

    _added: list[str] = []

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover - môi trường thiếu fastapi/httpx
            raise unittest.SkipTest(f"thiếu fastapi/httpx: {exc}")
        try:  # môi trường đầy đủ (py≥3.13): dùng đúng đường import của app thật
            from api import zalo_bot as zb_api
        except Exception:
            zb_api, cls._added = _load_router_standalone()
        app = FastAPI()
        app.include_router(zb_api.create_router())
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        for name in cls._added:  # đừng để module giả rò sang test khác cùng session
            sys.modules.pop(name, None)

    def setUp(self) -> None:
        _reset_module_state()

    def test_secret_sai_tra_403(self) -> None:
        with mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb.config, "get", return_value={}), \
             mock.patch.object(zb, "process_update") as pu:
            r = self.client.post("/api/zalo-bot/webhook",
                                 json={"ok": True, "result": {"message": {"chat": {"id": "c1"}}}},
                                 headers={"X-Bot-Api-Secret-Token": "sai"})
            self.assertEqual(r.status_code, 403)
            pu.assert_not_called()  # không xử lý gì khi secret sai

    def test_thieu_header_tra_403(self) -> None:
        with mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb.config, "get", return_value={}):
            r = self.client.post("/api/zalo-bot/webhook", json={"ok": True})
            self.assertEqual(r.status_code, 403)

    def test_secret_dung_tra_200(self) -> None:
        with mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb.config, "get", return_value={}), \
             mock.patch.object(zb, "process_update", return_value=True) as pu:
            body = {"ok": True, "result": {"event_name": "message.text.received",
                                           "message": {"message_id": "m1", "text": "hi",
                                                       "chat": {"id": "c1"}}}}
            r = self.client.post("/api/zalo-bot/webhook", json=body,
                                 headers={"X-Bot-Api-Secret-Token":
                                          zb._webhook_secret_for(TOKEN_A)})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["ok"])
            for _ in range(50):
                if pu.called:
                    break
                threading.Event().wait(0.02)
            pu.assert_called_once()
            self.assertEqual(pu.call_args[0][0], body)
            self.assertEqual(pu.call_args[0][1]["token"], TOKEN_A)

    def test_header_khong_phan_biet_hoa_thuong(self) -> None:
        with mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb.config, "get", return_value={}), \
             mock.patch.object(zb, "process_update", return_value=True):
            r = self.client.post("/api/zalo-bot/webhook", json={"ok": True},
                                 headers={"x-bot-api-secret-token":
                                          zb._webhook_secret_for(TOKEN_A)})
            self.assertEqual(r.status_code, 200)

    def test_payload_thieu_message_van_tra_200(self) -> None:
        """Zalo retry khi không nhận 2xx → payload lạ phải được 'nhận' rồi bỏ,
        không để nó dội lại mãi."""
        with mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb.config, "get", return_value={}):
            hdr = {"X-Bot-Api-Secret-Token": zb._webhook_secret_for(TOKEN_A)}
            for body in ({"ok": True}, {"ok": True, "result": {}},
                         {"result": {"event_name": "unknown.event"}}):
                r = self.client.post("/api/zalo-bot/webhook", json=body, headers=hdr)
                self.assertEqual(r.status_code, 200, repr(body))
            r = self.client.post("/api/zalo-bot/webhook", content=b"khong-phai-json",
                                 headers={**hdr, "Content-Type": "application/json"})
            self.assertEqual(r.status_code, 200)

    def test_endpoint_quan_tri_can_admin(self) -> None:
        r = self.client.get("/api/zalo-bot/status")
        self.assertIn(r.status_code, (401, 403))
        r = self.client.post("/api/zalo-bot/webhook-config", json={"enabled": True})
        self.assertIn(r.status_code, (401, 403))
        r = self.client.post("/api/zalo-bot/apply-mode")
        self.assertIn(r.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
