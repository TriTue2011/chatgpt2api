"""Endpoint gửi RA của Zalo Bot (`POST /api/zalo-bot/send`) — cho Home Assistant.

Điều phải khoá lại ở đây KHÔNG phải "gọi được Zalo hay không" (việc đó cần bot
token thật), mà là ba quyết định dễ sai âm thầm:

1. Đưa cho send_photo ĐƯỜNG DẪN tương đối, không phải URL đầy đủ. `save_image_bytes`
   dựng URL từ `config.base_url` — trên máy chủ này là http://172.16.10.38:3030,
   một địa chỉ LAN. `_ensure_public_photo_url` chỉ viết lại localhost/127.0.0.1
   nên URL LAN đi nguyên vào Zalo, rồi Zalo im lặng không tải được ảnh: không
   lỗi, không log, chỉ là ảnh không tới.
2. Ảnh không phải PNG phải được CHUYỂN thật sang PNG. save_image_bytes luôn đặt
   tên .png, nên byte JPEG trong tệp .png làm StaticFiles trả sai content-type.
3. Thiếu chat_id thì báo lỗi rõ, không gửi vào chỗ trống.
"""
from __future__ import annotations

import io
import sys
import types
import unittest


def _app():
    """Dựng app tối thiểu với services.zalo_bot GIẢ.

    Nạp router thật (api.zalo_bot) nhưng chặn `services.zalo_bot` bằng module
    giả: kênh thật sẽ đi gọi mạng ra Zalo lúc import/gửi.
    """
    fake = types.ModuleType("services.zalo_bot")
    fake.goi = []

    def send_photo(chat_id, photo_url, caption=""):
        fake.goi.append(("photo", chat_id, photo_url, caption))
        return {"ok": True}

    def send_message(chat_id, text, rich=True, bot=None):
        fake.goi.append(("text", chat_id, text, rich))
        return {"ok": True}

    fake.send_photo = send_photo
    fake.send_message = send_message
    fake._resolve_admin_delivery = lambda: ("admin-chat-1", None)
    fake.process_update = lambda *a, **k: None
    fake.verify_webhook_secret = lambda h: None
    fake.get_webhook_status = lambda: {}
    fake.set_webhook_enabled = lambda b: {}
    fake.apply_mode = lambda: {}

    # Đặt module giả vào sys.modules chỉ để api.zalo_bot nạp được lần đầu, rồi
    # TRẢ LẠI NGUYÊN TRẠNG (xem tearDown). Bỏ bước trả lại thì bộ test webhook
    # chạy sau sẽ dùng module giả này và 4 phép đo secret hoá ra "sai" — đo thật
    # 30/07: chạy riêng 8/8 xanh, chạy chung thì 4 lỗi 403≠200, và lỗi hiện ở
    # file KHÁC nên rất dễ đi sửa oan chỗ không hỏng.
    cu = sys.modules.get("services.zalo_bot")
    sys.modules["services.zalo_bot"] = fake

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import api.zalo_bot as mod
    # Vá trên CHÍNH module router, không vá api.support: api.support dùng chung
    # cho mọi router nên sửa ở đó là mở toang xác thực cho các bộ test khác.
    mod.zb = fake
    mod_require_cu = mod.require_admin
    mod.require_admin = lambda authorization: {"role": "admin"}
    app = FastAPI()
    app.include_router(mod.create_router())
    return TestClient(app), fake, (mod, cu, mod_require_cu)


def _png() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(b, format="PNG")
    return b.getvalue()


def _jpeg() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 255, 0)).save(b, format="JPEG")
    return b.getvalue()


class TestGuiRa(unittest.TestCase):
    def setUp(self):
        self.cli, self.zb, self._hoan = _app()

    def tearDown(self):
        mod, zb_cu, require_cu = self._hoan
        if zb_cu is None:
            sys.modules.pop("services.zalo_bot", None)
        else:
            sys.modules["services.zalo_bot"] = zb_cu
        mod.zb = zb_cu
        mod.require_admin = require_cu

    def test_anh_di_bang_duong_dan_tuong_doi_khong_phai_url_lan(self):
        r = self.cli.post("/api/zalo-bot/send",
                          data={"text": "Có người ở cửa"},
                          files={"photo": ("cam.png", _png(), "image/png")})
        self.assertEqual(r.status_code, 200, r.text)
        kieu, cid, anh, caption = self.zb.goi[-1]
        self.assertEqual(kieu, "photo")
        self.assertTrue(anh.startswith("/images/"), f"phải là đường dẫn: {anh}")
        self.assertNotIn("172.16.", anh)
        self.assertNotIn("http", anh)
        self.assertEqual(caption, "Có người ở cửa")

    def test_jpeg_duoc_chuyen_that_sang_png(self):
        r = self.cli.post("/api/zalo-bot/send",
                          files={"photo": ("cam.jpg", _jpeg(), "image/jpeg")})
        self.assertEqual(r.status_code, 200, r.text)
        _, _, anh, _ = self.zb.goi[-1]
        self.assertTrue(anh.endswith(".png"))
        # Tệp trên đĩa phải là PNG THẬT, không phải byte JPEG mang tên .png.
        from services.config import config
        p = config.images_dir / anh.split("/images/", 1)[1]
        self.assertTrue(p.exists(), p)
        self.assertTrue(p.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_chi_co_chu_thi_gui_text(self):
        r = self.cli.post("/api/zalo-bot/send", data={"text": "Mất điện"})
        self.assertEqual(r.status_code, 200, r.text)
        kieu, cid, text, rich = self.zb.goi[-1]
        self.assertEqual((kieu, text), ("text", "Mất điện"))
        self.assertFalse(rich, "cảnh báo hệ thống gửi plain, tránh vỡ URL")
        self.assertEqual(cid, "admin-chat-1")

    def test_photo_url_san_co_thi_dung_luon(self):
        r = self.cli.post("/api/zalo-bot/send",
                          data={"photo_url": "https://x.tld/a.png", "text": "kèm"})
        self.assertEqual(r.status_code, 200, r.text)
        _, _, anh, _ = self.zb.goi[-1]
        self.assertEqual(anh, "https://x.tld/a.png")

    def test_chat_id_truyen_vao_thang_hon_admin_mac_dinh(self):
        self.cli.post("/api/zalo-bot/send", data={"text": "x", "chat_id": "9999"})
        self.assertEqual(self.zb.goi[-1][1], "9999")

    def test_khong_co_gi_thi_400(self):
        r = self.cli.post("/api/zalo-bot/send", data={})
        self.assertEqual(r.status_code, 400)

    def test_khong_co_chat_id_nao_thi_bao_ro_chu_khong_gui_vao_cho_trong(self):
        self.zb._resolve_admin_delivery = lambda: ("", None)
        r = self.cli.post("/api/zalo-bot/send", data={"text": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("chat_id", r.text)

    def test_anh_hong_bao_400_chu_khong_no_500(self):
        r = self.cli.post("/api/zalo-bot/send",
                          files={"photo": ("x.jpg", b"khong-phai-anh", "image/jpeg")})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self.zb.goi, [], "không được gửi gì khi ảnh hỏng")


if __name__ == "__main__":
    unittest.main()
