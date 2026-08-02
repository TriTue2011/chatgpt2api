"""Zalo Bot: URL webhook RIÊNG từng bot, và bật webhook không được làm kênh chết.

Hai bất biến khoá ở đây:

  1. `setWebhook` đăng ký URL riêng cho từng bot (`…/webhook/<bot_id>`). Nhiều bot
     dùng chung một URL thì VẪN chạy — secret trong header phân biệt được — nhưng
     người vận hành không nhìn ra URL nào của bot nào, và `getWebhookInfo` của mọi
     bot trả về cùng một chuỗi nên không soi được cái nào lệch.
     Đường KHÔNG có `<bot_id>` phải tiếp tục nhận, kẻo webhook đã đăng ký ngoài
     thực địa bị phá.

  2. Bật công tắc mà `setWebhook` trượt HẾT thì phải TỰ QUAY VỀ long-polling.
     `apply_mode` dừng poll TRƯỚC khi đăng ký, nên đăng ký trượt mà không quay lại
     là kênh im lặng hoàn toàn: webhook chưa đặt được, poll thì vừa tắt. Ca này
     rất dễ gặp — docs setWebhook đòi URL HTTPS công khai, mà base_url thực địa
     từng là http://<IP LAN>:3030 nên bị từ chối ngay.

Ghi chú: KHÔNG có test cho "chuyển tiếp tin ra webhook ngoài" ở kênh bot, vì việc
đó thuộc tab "Lọc thread" (`thread_forward_filters` → `capabilities.forward_event`,
đã nối sẵn ở services/zalo_bot.py) — không phải của panel Webhook.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import zalo_bot as zb  # noqa: E402

BOT_A = {"token": "111111:aaaaaaaaaaaaaaaaaaaa", "enabled": True, "label": "botA"}
BOT_B = {"token": "222222:bbbbbbbbbbbbbbbbbbbb", "enabled": True, "label": "botB"}


class UrlRiengTungBotTests(unittest.TestCase):
    def _cfg(self, **kw) -> dict:
        base = {"base_url": "https://vi-du.test"}
        base.update(kw)
        return base

    def test_moi_bot_mot_url_khac_nhau(self):
        with mock.patch.object(zb.config, "get", return_value=self._cfg()):
            a = zb.webhook_url(BOT_A)
            b = zb.webhook_url(BOT_B)
        self.assertEqual(a, "https://vi-du.test/api/zalo-bot/webhook/111111")
        self.assertEqual(b, "https://vi-du.test/api/zalo-bot/webhook/222222")
        self.assertNotEqual(a, b)

    def test_khong_truyen_bot_thi_ra_url_goc(self):
        with mock.patch.object(zb.config, "get", return_value=self._cfg()):
            self.assertEqual(zb.webhook_url(),
                             "https://vi-du.test/api/zalo-bot/webhook")

    def test_dat_tay_zalo_webhook_url_thi_ton_trong_nguyen_van(self):
        """Vận hành có thể trỏ qua proxy riêng với đường dẫn khác hẳn."""
        cfg = self._cfg(zalo_webhook_url="https://khac.test/hook-rieng")
        with mock.patch.object(zb.config, "get", return_value=cfg):
            self.assertEqual(zb.webhook_url(BOT_A), "https://khac.test/hook-rieng")

    def test_khong_co_base_thi_tra_rong(self):
        with mock.patch.object(zb.config, "get", return_value={}):
            self.assertEqual(zb.webhook_url(BOT_A), "")

    def test_set_webhook_dang_ky_url_RIENG(self):
        goi: list[dict] = []
        with mock.patch.object(zb.config, "get", return_value=self._cfg()), \
             mock.patch.object(zb, "_api_call",
                               side_effect=lambda m, p=None: goi.append({"m": m, "p": p}) or {"ok": True}):
            zb.set_webhook(BOT_B)
        self.assertEqual(goi[0]["m"], "setWebhook")
        self.assertEqual(goi[0]["p"]["url"],
                         "https://vi-du.test/api/zalo-bot/webhook/222222")
        # Docs: secret_token dài 8–256 ký tự.
        self.assertGreaterEqual(len(goi[0]["p"]["secret_token"]), 8)
        self.assertLessEqual(len(goi[0]["p"]["secret_token"]), 256)

    def test_duong_khong_co_bot_id_van_con(self):
        """Webhook đã đăng ký ngoài thực địa trỏ đường cũ — không được phá."""
        code = (Path(__file__).resolve().parents[1] / "api" / "zalo_bot.py").read_text("utf-8")
        self.assertIn('@router.post("/api/zalo-bot/webhook")', code)
        self.assertIn('@router.post("/api/zalo-bot/webhook/{bot_id}")', code)

    def test_bot_id_tren_url_khong_dung_de_xac_thuc(self):
        """bot_id là phần CÔNG KHAI của token — ai cũng đoán được. Quyền phải do
        secret trong header quyết định, lệch thì chỉ ghi log."""
        code = (Path(__file__).resolve().parents[1] / "api" / "zalo_bot.py").read_text("utf-8")
        i = code.index('@router.post("/api/zalo-bot/webhook/{bot_id}")')
        khuc = code[i:i + 2200]
        self.assertIn("verify_webhook_secret(hdr)", khuc)
        self.assertIn("Bad secret token", khuc)
        # Lệch bot_id → log, KHÔNG raise.
        self.assertIn("logger.warning", khuc[khuc.index("that = "):])


class QuayVePollingKhiWebhookTruotTests(unittest.TestCase):
    def _apply(self, set_ok: bool, mo_ta: str = ""):
        self.da_update: list[dict] = []
        with mock.patch.object(zb, "_bots", return_value=[BOT_A]), \
             mock.patch.object(zb, "webhook_enabled", return_value=True), \
             mock.patch.object(zb, "webhook_url",
                               return_value="http://172.16.10.38:3030/x"), \
             mock.patch.object(zb, "stop_polling", return_value=0), \
             mock.patch.object(zb, "start_polling", return_value=True), \
             mock.patch.object(zb, "set_webhook",
                               return_value={"ok": set_ok, "description": mo_ta}), \
             mock.patch.object(zb.config, "update", side_effect=self.da_update.append):
            return zb.apply_mode()

    def test_truot_het_thi_quay_ve_polling_va_ha_co(self):
        out = self._apply(False, "webhook url phải là HTTPS, đang là http")
        self.assertTrue(out["fell_back_to_polling"])
        self.assertEqual(out["mode"], "long-polling")
        self.assertTrue(out["polling"])
        self.assertIn("HTTPS", out["fallback_reason"])
        # Hạ cờ để trạng thái chỉ có MỘT nguồn đúng.
        self.assertEqual(self.da_update, [{"zalo_webhook_enabled": False}])

    def test_dat_duoc_thi_khong_quay_ve(self):
        out = self._apply(True)
        self.assertNotIn("fell_back_to_polling", out)
        self.assertEqual(out["mode"], "webhook")
        self.assertFalse(out["polling"])
        self.assertEqual(self.da_update, [])


if __name__ == "__main__":
    unittest.main()
