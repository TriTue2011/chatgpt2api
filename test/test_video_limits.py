"""Trần cho /v1/video/compose và /v1/video/story.

Hai đường này nhận base64 và số cảnh do client đặt, trước đây không có trần nào:
- compose: mảng `clips` dài tuỳ ý, mỗi clip base64 lớn tuỳ ý → cạn RAM rồi cạn
  đĩa tạm, ffmpeg chạy vô hạn;
- story: `n_scenes` tuỳ ý, mà MỖI cảnh là một lượt gọi Veo có TÍNH PHÍ và mất
  vài chục giây — đây là chi phí thật, không chỉ là tài nguyên máy.
"""
import asyncio
import base64
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from fastapi import HTTPException  # noqa: E402

from api import veo_video as m  # noqa: E402


def _b64(n: int) -> str:
    return base64.b64encode(b"\0" * n).decode()


class DecodeMediaTests(unittest.TestCase):
    def test_duoi_tran_giai_ma_binh_thuong(self):
        self.assertEqual(len(m._decode_media(_b64(1000), max_bytes=4096)), 1000)

    def test_qua_tran_bi_tu_choi_413(self):
        with self.assertRaises(HTTPException) as ctx:
            m._decode_media(_b64(10_000), max_bytes=4096)
        self.assertEqual(ctx.exception.status_code, 413)

    def test_do_do_dai_TRUOC_khi_giai_ma(self):
        """b64decode cấp phát bản giải mã rồi mới trả về — đo sau là RAM đã mất.

        Chuỗi ~40MB base64 phải bị chặn mà KHÔNG gọi b64decode lần nào.
        """
        import base64 as _b64mod
        goi = []
        that = _b64mod.b64decode

        def _theo_doi(*a, **k):
            goi.append(1)
            return that(*a, **k)

        _b64mod.b64decode = _theo_doi
        try:
            with self.assertRaises(HTTPException):
                m._decode_media("A" * 40_000_000, max_bytes=1024)
        finally:
            _b64mod.b64decode = that
        self.assertEqual(goi, [], "đã giải mã dù biết trước là quá trần")

    def test_data_url_van_doc_duoc(self):
        self.assertEqual(len(m._decode_media("data:video/mp4;base64," + _b64(64))), 64)


class ComposeTests(unittest.TestCase):
    def _chay(self, body):
        return asyncio.run(m.handle_video_compose(body))

    def test_qua_nhieu_clip_bi_chan(self):
        with self.assertRaises(HTTPException) as ctx:
            self._chay({"clips": [_b64(8)] * (m.MAX_COMPOSE_CLIPS + 1)})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("too many clips", str(ctx.exception.detail))

    def test_thieu_clips_bi_chan(self):
        with self.assertRaises(HTTPException) as ctx:
            self._chay({})
        self.assertEqual(ctx.exception.status_code, 400)


class StoryTranTests(unittest.TestCase):
    """Chốt bằng mã nguồn: story gọi ra provider thật nên không chạy được ở đây."""

    def test_co_tran_so_canh(self):
        src = (GOC / "api/veo_video.py").read_text(encoding="utf-8")
        self.assertIn("MAX_STORY_SCENES", src)
        self.assertIn("too many scenes", src)
        self.assertIn("n_scenes too large", src)

    def test_tai_video_provider_di_qua_net_guard(self):
        src = (GOC / "api/veo_video.py").read_text(encoding="utf-8")
        self.assertIn("net_guard.fetch_media", src,
                      "URL do provider trả về vẫn phải qua kiểm SSRF + trần byte")
        # `r.content` là chỗ đọc KHÔNG giới hạn của bản cũ. Kiểm chuỗi này thay
        # vì "follow_redirects=True" vì cụm đó còn nằm trong chú thích giải
        # thích lỗi cũ — test sẽ tự khớp với chú thích của chính mình.
        self.assertNotIn("raw = r.content", src,
                         "còn đường đọc video không giới hạn dung lượng")


if __name__ == "__main__":
    unittest.main()
