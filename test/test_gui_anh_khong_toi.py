"""Tool trả NHIỀU ảnh mà người dùng KHÔNG nhận được ảnh nào.

Lỗi thật, người dùng báo 30/07/2026 (Zalo cá nhân):

    14:15:16  Nguyễn Việt : Gửi 3 ảnh mới nhất trong thư viện ảnh cho tôi
    14:15:48  Botmitbap   : Dạ em gửi 3 ảnh AI mới nhất trong thư viện rồi nha anh 😊
    14:15:59  Nguyễn Việt : Ảnh đâu
    14:16:10  Botmitbap   : Dạ đây anh nha, em vừa gửi lại 3 ảnh mới nhất rồi đó ạ 😊

Đo lại từng tầng: model GỌI ĐÚNG `library_media{"kind":"image","so_luong":3}`,
handler TRẢ ĐÚNG 3 URL — mà `orchestrate` ra `['text']`, không có ảnh nào.

Nguyên nhân: cổng giao media là ``if produced_media:``, và `produced_media` CHỈ
được đặt trong vòng lặp khoá ``image_url`` (SỐ ÍT). Tool trả riêng ``image_urls``
(số nhiều) thì cổng không mở, lượt chạy rơi xuống nhánh "để model tự viết câu trả
lời từ kết quả tool" — model thấy tool đã trả 3 URL nên viết "em gửi rồi", và câu
đó về tới người dùng KHÔNG kèm ảnh.

Đây là loại lỗi tệ nhất: mọi tầng đều báo thành công, log không có gì, và bot
KHẲNG ĐỊNH đã gửi nên người dùng đi tìm lỗi ở Zalo.
"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.agent.orchestrator as orch  # noqa: E402

BA_ANH = [
    "http://127.0.0.1:80/images/2026/07/30/a.png",
    "http://127.0.0.1:80/images/2026/07/30/b.png",
    "http://127.0.0.1:80/images/2026/07/30/c.png",
]


def _resp_tool(name: str, args: dict) -> dict:
    return {"choices": [{"finish_reason": "tool_calls", "message": {
        "content": "", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def _resp_text(t: str) -> dict:
    return {"choices": [{"finish_reason": "stop", "message": {"content": t}}]}


class TestToolTraNhieuAnh(unittest.TestCase):
    """Chạy THẬT vòng lặp orchestrate với model giả + tool giả."""

    def _chay(self, ket_qua_tool: dict) -> dict:
        buoc = {"n": 0}

        def _cm(model, messages, **kw):
            buoc["n"] += 1
            if buoc["n"] == 1:
                return _resp_tool("library_media", {"kind": "image", "so_luong": 3})
            # Lượt 2 là chỗ model "kể lại" — nếu cổng media mở đúng thì KHÔNG
            # bao giờ tới đây.
            return _resp_text("Dạ em gửi 3 ảnh mới nhất rồi nha anh 😊")

        with mock.patch.object(orch, "call_model", side_effect=_cm), \
             mock.patch.object(orch, "_execute", return_value=ket_qua_tool), \
             mock.patch.object(orch, "_persist_history"), \
             mock.patch.object(orch.run_journal, "log_run"), \
             mock.patch.object(orch, "_ghi_so_anh"):
            # Câu trung tính để test vòng tool giả, không đi tắt qua nhánh đọc
            # sổ ảnh riêng (nhánh đó có bộ test riêng).
            return orch.orchestrate("Yêu cầu kiểm thử công cụ thư viện",
                                    "test_nhieu_anh", model="gma/auto:text")

    def test_chi_co_image_urls_van_phai_toi_tay_nguoi_dung(self):
        """Đây là ca thật đã hỏng: tool trả DUY NHẤT `image_urls`."""
        out = self._chay({"text": "3 ảnh mới nhất trong thư viện ạ.",
                          "image_urls": list(BA_ANH)})
        self.assertEqual(out.get("image_urls"), BA_ANH,
                         "mất ảnh: cổng giao media không mở cho khoá số nhiều")

    def test_van_co_image_url_so_it_cho_kenh_cu(self):
        """Zalo Bot (và kênh chưa đọc `image_urls`) phải gửi được ít nhất 1 tấm,
        chứ không gửi rỗng."""
        out = self._chay({"text": "x", "image_urls": list(BA_ANH)})
        self.assertEqual(out.get("image_url"), BA_ANH[0])

    def test_khong_de_model_ke_lai_thay_cho_gui_anh(self):
        """Câu trả về phải là caption của tool, KHÔNG phải câu model bịa ở lượt 2.

        Phân biệt được vì hai câu khác nhau: caption tool là "3 ảnh mới nhất trong
        thư viện ạ.", còn câu bịa là "Dạ em gửi 3 ảnh mới nhất rồi nha anh".
        """
        out = self._chay({"text": "3 ảnh mới nhất trong thư viện ạ.",
                          "image_urls": list(BA_ANH)})
        self.assertNotIn("em gửi", out.get("text") or "")

    def test_mot_anh_thi_khong_them_khoa_so_nhieu(self):
        out = self._chay({"text": "x", "image_urls": [BA_ANH[0]]})
        self.assertEqual(out.get("image_url"), BA_ANH[0])
        self.assertIsNone(out.get("image_urls"))

    def test_duong_so_it_cu_khong_bi_doi(self):
        """Tool chỉ trả `image_url` — hành vi cũ phải y nguyên."""
        out = self._chay({"text": "ảnh đây", "image_url": BA_ANH[0]})
        self.assertEqual(out.get("image_url"), BA_ANH[0])

    def test_khong_co_anh_thi_khong_mo_cong(self):
        """Tool chỉ trả chữ → phải để model viết câu trả lời như trước."""
        out = self._chay({"text": "Thư viện chưa có ảnh nào ạ."})
        self.assertIsNone(out.get("image_url"))
        self.assertIsNone(out.get("image_urls"))
        self.assertTrue(str(out.get("text") or "").strip())


class TestCongGiaoMedia(unittest.TestCase):
    def test_dieu_kien_xet_ca_produced_images(self):
        """Chốt phòng lớp hai: đường nào chỉ đổ vào `produced_images` cũng không
        được rơi vào đúng cái bẫy này nữa."""
        import inspect
        src = inspect.getsource(orch)
        self.assertIn("if produced_media or produced_images:", src)


class TestTelegramTaiDuoc(unittest.TestCase):
    """"Ta gọi ra được" KHÁC "Telegram tải được" — bản cũ dùng lẫn hai câu hỏi."""

    def setUp(self):
        from services import telegram_bot as tg
        self.tg = tg

    def test_loopback_va_private_thi_telegram_khong_tai_duoc(self):
        for u in ("http://127.0.0.1:80/images/a.png",
                  "http://localhost/images/a.png",
                  "http://172.16.10.38/images/a.png",
                  "http://192.168.1.5/a.png",
                  "http://10.0.0.9/a.png"):
            self.assertFalse(self.tg._telegram_tai_duoc(u), u)

    def test_ten_mien_cong_khai_thi_duoc(self):
        for u in ("https://example.com/a.png", "https://cdn.zalo.me/x.jpg"):
            self.assertTrue(self.tg._telegram_tai_duoc(u), u)

    def test_khong_phai_url_thi_khong(self):
        for u in ("", "abc", "data:image/png;base64,xx"):
            self.assertFalse(self.tg._telegram_tai_duoc(u), u)

    def test_net_guard_van_cho_qua_loopback(self):
        """Ghi lại lý do phải có hàm riêng: net_guard trả True cho 127.0.0.1 (đúng
        với câu hỏi của NÓ), nên dùng nó để quyết định album là sai."""
        from services import net_guard as ng
        self.assertTrue(ng.is_allowed_egress_url("http://127.0.0.1:80/images/a.png"))


class TestAlbumTelegramVoiAnhNoiBo(unittest.TestCase):
    """Ảnh thư viện luôn ở 127.0.0.1 → phải đi đường bytes, VẪN là một album.

    Bản cũ trả False cho URL nội bộ nên caller rơi về gửi TỪNG TẤM: xin "3 ảnh
    một lúc" mà nhận 3 tin nhắn rời, trong khi Zalo đã gộp được một tin.
    """

    def setUp(self):
        from services import telegram_bot as tg
        self.tg = tg

    def test_url_cong_khai_gui_thang_url(self):
        with mock.patch.object(self.tg, "_api_call",
                               return_value={"ok": True}) as api:
            ok = self.tg._gui_album(1, ["https://e.com/a.png", "https://e.com/b.png"],
                                    caption="hai ảnh")
        self.assertTrue(ok)
        media = api.call_args.args[1]["media"]
        self.assertEqual([m["media"] for m in media],
                         ["https://e.com/a.png", "https://e.com/b.png"])
        self.assertEqual(media[0]["caption"], "hai ảnh")

    def test_url_noi_bo_di_duong_bytes_va_van_la_album(self):
        cli = mock.Mock()
        cli.call_multipart.return_value = {"ok": True}
        with mock.patch.object(self.tg, "_fetch_image_bytes", return_value=b"PNG"), \
             mock.patch.object(self.tg, "_cli", return_value=cli), \
             mock.patch.object(self.tg, "_api_call") as api:
            ok = self.tg._gui_album(1, BA_ANH, caption="ba ảnh")
        self.assertTrue(ok)
        api.assert_not_called()          # KHÔNG gọi đường URL (chắc chắn 400)
        cli.call_multipart.assert_called_once()
        method, fields, files = cli.call_multipart.call_args.args[:3]
        self.assertEqual(method, "sendMediaGroup")
        self.assertEqual(len(files), 3)
        media = json.loads(fields["media"])
        self.assertEqual([m["media"] for m in media],
                         ["attach://anh0", "attach://anh1", "attach://anh2"])
        self.assertEqual(media[0]["caption"], "ba ảnh")

    def test_tai_khong_duoc_het_thi_tra_False_de_caller_bao_thieu(self):
        with mock.patch.object(self.tg, "_fetch_image_bytes", return_value=None), \
             mock.patch.object(self.tg, "_cli") as cli:
            self.assertFalse(self.tg._gui_album(1, BA_ANH))
        cli.return_value.call_multipart.assert_not_called()

    def test_duoi_2_anh_thi_khong_phai_album(self):
        self.assertFalse(self.tg._gui_album(1, [BA_ANH[0]]))

    def test_van_gioi_han_10_anh_moi_album(self):
        import inspect
        self.assertIn("urls[:10]", inspect.getsource(self.tg._gui_album))


if __name__ == "__main__":
    unittest.main()
