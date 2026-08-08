"""Telegram gửi media phải có TRẦN, và phải biết trước khi đọc.

Bản cũ `open(path).read()` / `Path.read_bytes()` nạp cả tệp vào RAM, rồi
`call_multipart` dựng thêm một bản sao nữa trong bộ đệm multipart — một video
2GB do provider trả về là ~4GB RAM. Telegram lại từ chối tệp quá 50MB, nên đọc
hết rồi mới biết là phí hoàn toàn.

Hằng số trần đã có sẵn trong services/telegram/constants.py từ trước nhưng
không nơi nào áp. Test này chốt lại là chúng được áp thật.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.telegram.constants import MAX_UPLOAD_FILE_BYTES  # noqa: E402
from services.telegram_bot import _doc_media_co_tran  # noqa: E402


class TepTrenDiaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _tep(self, n: int) -> str:
        p = Path(self.tmp.name) / "media.bin"
        p.write_bytes(b"\0" * n)
        return str(p)

    def test_duoi_tran_doc_binh_thuong(self):
        self.assertEqual(len(_doc_media_co_tran("path", self._tep(1024), 4096, "video")), 1024)

    def test_qua_tran_bi_tu_choi(self):
        with self.assertRaises(ValueError) as ctx:
            _doc_media_co_tran("path", self._tep(5000), 4096, "video")
        self.assertIn("quá lớn", str(ctx.exception))

    def test_khong_doc_mot_byte_nao_khi_qua_tran(self):
        """Phải hỏi stat() TRƯỚC khi đọc — đọc rồi mới đo là đã mất RAM."""
        p = self._tep(5000)
        goc = Path(p).read_bytes  # noqa: F841  (chỉ để chắc chắn tệp tồn tại)

        da_doc = []
        that = Path.read_bytes

        def _theo_doi(self_p):
            da_doc.append(str(self_p))
            return that(self_p)

        Path.read_bytes = _theo_doi
        try:
            with self.assertRaises(ValueError):
                _doc_media_co_tran("path", p, 4096, "video")
        finally:
            Path.read_bytes = that
        self.assertEqual(da_doc, [], "đã đọc tệp dù biết trước là quá trần")


class UrlTests(unittest.TestCase):
    def test_url_truyen_max_bytes_xuong_fetch_media(self):
        """fetch_media đã có sẵn tham số max_bytes (kèm kiểm SSRF + redirect);
        lỗi cũ là gọi mà KHÔNG truyền nên nó dùng mặc định rộng hơn trần thật."""
        from unittest import mock
        from services import net_guard

        with mock.patch.object(net_guard, "fetch_media", return_value=b"ok") as gia:
            _doc_media_co_tran("url", "https://x/a.mp4", 1234, "video")
        gia.assert_called_once()
        self.assertEqual(gia.call_args.kwargs.get("max_bytes"), 1234)


class HangSoTests(unittest.TestCase):
    def test_tran_khop_gioi_han_that_cua_telegram(self):
        self.assertEqual(MAX_UPLOAD_FILE_BYTES, 50 * 1024 * 1024)

    def test_moi_duong_gui_media_deu_di_qua_helper(self):
        src = (GOC / "services/telegram_bot.py").read_text(encoding="utf-8")
        self.assertNotIn("with open(src, \"rb\") as f", src,
                         "còn đường đọc video không qua trần")
        self.assertEqual(src.count("_doc_media_co_tran("), 4,
                         "video + audio + tài liệu phải cùng đi qua helper (3 nơi gọi + 1 định nghĩa)")


if __name__ == "__main__":
    unittest.main()
