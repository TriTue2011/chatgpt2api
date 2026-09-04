"""Tạo ảnh phải gọi ĐÚNG endpoint /v1/images/generations, không đi nhờ chat.

Lỗi thật 04/09 (chủ máy): "Tạo ảnh em bé" → chọn model 5 "AI image" → bot trả
một đoạn văn của model ("bạn đang ở phiên trò chuyện tạm thời nên mình không có
quyền truy cập công cụ tạo ảnh"), không có ảnh. Lần khác ra tệp .docx base64.

Gốc: `_h_generate_image` gọi `call_model(model, "Vẽ: …")` qua /chat/completions.
Combo ảnh "AI image" không được endpoint chat mở (nó chỉ mở ở
/v1/images/generations), nên rơi về ChatGPT pool "vẽ hộ" — flow đứng đầu combo
chưa bao giờ được thử. Sửa: thêm `call_image` gọi thẳng endpoint ảnh.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import capabilities as caps  # noqa: E402
from services.agent import runtime as rt  # noqa: E402

# Prompt DÀI (≥70 ký tự) để `_mo_rong_prompt_media` giữ nguyên, không gọi model.
PROMPT_DAI = ("Một em bé đáng yêu, gương mặt hồn nhiên, ánh sáng mềm mại, phong "
              "cách chân dung tự nhiên, nền mờ dịu, không chữ")


class CallImageDungEndpointTests(unittest.TestCase):
    def test_post_dung_images_generations(self):
        ghi = {}

        class _Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def _gia_urlopen(req, timeout=0):
            ghi["url"] = req.full_url
            ghi["body"] = json.loads(req.data.decode())
            return _Resp(json.dumps({"data": [{"url": "http://x/a.png"}]}).encode())

        with patch("urllib.request.urlopen", _gia_urlopen):
            resp = rt.call_image("vẽ mèo", model="AI image")

        self.assertTrue(ghi["url"].endswith("/images/generations"),
                        f"phải gọi endpoint ảnh, đang gọi {ghi['url']}")
        self.assertNotIn("/chat/completions", ghi["url"])
        self.assertEqual(ghi["body"]["response_format"], "url")
        self.assertEqual(ghi["body"]["model"], "AI image")
        self.assertEqual(resp["data"][0]["url"], "http://x/a.png")

    def test_http_error_tra_dict_khong_raise(self):
        import urllib.error

        def _no(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, io.BytesIO(b"loi"))

        with patch("urllib.request.urlopen", _no):
            resp = rt.call_image("x", model="AI image")
        self.assertIn("error", resp)
        self.assertIn("500", resp["error"])


class HGenerateImageTests(unittest.TestCase):
    """`_h_generate_image` đọc kết quả endpoint ảnh, không rò văn bản model."""

    def _goi(self, resp: dict) -> dict:
        # model= sẵn → bỏ qua menu; auto_approve=True → bỏ hỏi thông số.
        with patch.object(caps, "call_image", return_value=resp), \
             patch.object(caps, "_mo_rong_prompt_media", side_effect=lambda p, *a, **k: p), \
             patch.object(caps, "_alert_branch"):
            return caps._h_generate_image(
                {"prompt": PROMPT_DAI, "model": "AI image"},
                {"auto_approve": True})

    def test_url_thi_tra_image_url(self):
        out = self._goi({"data": [{"url": "http://x/baby.png"}]})
        self.assertEqual(out.get("image_url"), "http://x/baby.png")
        self.assertNotIn("image_urls", out)

    def test_nhieu_anh_thi_tra_image_urls(self):
        out = self._goi({"data": [{"url": "http://x/1.png"}, {"url": "http://x/2.png"}]})
        self.assertEqual(out.get("image_urls"), ["http://x/1.png", "http://x/2.png"])
        self.assertEqual(out.get("image_url"), "http://x/1.png")

    def test_b64_thi_luu_roi_tra_url(self):
        png = base64.b64encode(bytes.fromhex("89504e470d0a1a0a") + b"x" * 50).decode()
        out = self._goi({"data": [{"b64_json": png}]})
        self.assertIn("image_url", out)
        self.assertIn("/images/", out["image_url"])

    def test_endpoint_loi_thi_bao_ngan_khong_ro_base64(self):
        """Endpoint hỏng → câu lỗi ngắn theo khuôn (như video), không rò base64.

        Chuỗi `error` là chẩn đoán HTTP (call_image cắt 200 ký tự), được phép
        hiện — khác hẳn việc trả NGUYÊN VĂN model như bug cũ.
        """
        out = self._goi({"error": "HTTP 500: upstream busy"})
        self.assertTrue(out.get("deliver_now"))
        self.assertIn("bị lỗi", out["text"])
        self.assertNotIn("data:image", out["text"])

    def test_KHONG_con_duong_tra_van_ban_model(self):
        """Chống tái diễn cốt lõi: dù model trả prose kèm base64 trong `content`
        (khuôn chat cũ), `_h_generate_image` nay CHỈ đọc data/error nên prose đó
        không có đường nào ra người dùng."""
        prose = ("Mình đang ở phiên tạm thời nên không tạo ảnh được. "
                 "data:image/png;base64,AAAABBBB")
        out = self._goi({"choices": [{"message": {"content": prose}}], "data": []})
        self.assertNotIn("phiên tạm thời", out["text"])
        self.assertNotIn("data:image", out["text"])
        self.assertNotIn("base64", out["text"])

    def test_khong_co_anh_KHONG_ro_van_ban_model(self):
        out = self._goi({"data": []})
        self.assertTrue(out.get("deliver_now"))
        self.assertIn("chưa lấy được ảnh", out["text"])
        self.assertNotIn("data:image", out["text"])


class MenuVanRaKhiChuaChonModelTests(unittest.TestCase):
    def test_chua_chon_model_thi_ra_menu(self):
        out = caps._h_generate_image({"prompt": "em bé"}, {})
        self.assertTrue(out.get("deliver_now"))
        self.assertIn("<<<ASK>>>", out["text"])
        self.assertIn("model nào", out["text"])


if __name__ == "__main__":
    unittest.main()
