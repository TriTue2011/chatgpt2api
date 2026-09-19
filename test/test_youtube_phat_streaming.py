"""Bộ test của add-on TriTue YouTube Player (youtube_player/tests), chạy trên bản
đã chuyển vào c2a (`services/youtube_phat`) — chứng minh hành vi giữ nguyên."""

import importlib.util
import gzip
import hashlib
import hmac
import io
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "services" / "youtube_phat"
STREAMING_MODULE_PATH = APP_DIR / "streaming.py"


def load_streaming_module():
    spec = importlib.util.spec_from_file_location(
        "tritue_youtube_player_streaming", STREAMING_MODULE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable_to_load_streaming_module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SignedZingStreamTests(unittest.TestCase):
    def setUp(self):
        self.streaming = load_streaming_module()
        self.target = (
            "https://zingmp3.vn/bai-hat/Thuc-Giac-Da-LAB/ZZ90FD0B.html"
        )

    def test_signed_url_round_trip_is_bound_to_zing_and_expiry(self):
        stream_url = self.streaming.build_signed_stream_url(
            "http://172.16.10.200:8099/",
            self.target,
            "integration-secret",
            now=1_000,
            ttl=300,
        )

        self.assertTrue(stream_url.startswith("http://172.16.10.200:8099/api/stream/"))
        token = stream_url.rsplit("/", 1)[-1]
        self.assertEqual(
            ("zing", self.target),
            self.streaming.verify_stream_token(
                token, "integration-secret", now=1_299
            ),
        )

        with self.assertRaises(self.streaming.InvalidStreamTokenError):
            self.streaming.verify_stream_token(
                token, "integration-secret", now=1_301
            )

    def test_tampered_token_and_non_zing_targets_are_rejected(self):
        token = self.streaming.create_stream_token(
            self.target, "integration-secret", now=1_000, ttl=300
        )
        with self.assertRaises(self.streaming.InvalidStreamTokenError):
            self.streaming.verify_stream_token(
                f"{token}x", "integration-secret", now=1_001
            )
        with self.assertRaises(ValueError):
            self.streaming.create_stream_token(
                "https://youtube.com/watch?v=dQw4w9WgXcQ",
                "integration-secret",
                now=1_000,
                ttl=300,
            )

    def test_resolver_follows_public_id_redirect_and_selects_320k_audio(self):
        redirected_target = (
            "https://zingmp3.vn/bai-hat/Thuc-Giac-Da-LAB/XwsdXWtaDHNH.html"
        )
        api_payload = gzip.compress(
            json.dumps(
                {
                    "err": 0,
                    "msg": "Success",
                    "data": {
                        "128": "https://audio.zmdcdn.me/song-128.mp3",
                        "320": "https://audio.zmdcdn.me/song-320.mp3",
                    },
                }
            ).encode()
        )

        class FakeResponse(io.BytesIO):
            def __init__(self, body=b"", *, url, headers=None):
                super().__init__(body)
                self._url = url
                self.headers = headers or {}

            def geturl(self):
                return self._url

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        opener = unittest.mock.Mock()
        opener.open.side_effect = [
            FakeResponse(url=redirected_target),
            FakeResponse(
                api_payload,
                url="https://zingmp3.vn/api/v2/song/get/streaming",
                headers={"Content-Encoding": "gzip"},
            ),
        ]
        with patch.object(self.streaming, "build_opener", return_value=opener):
            result = self.streaming.resolve_zing_stream(
                self.target, api_key="khoa-web-thu", api_secret="bi-mat-web-thu",
                timeout=20, now=1_787_976_165
            )

        self.assertEqual("https://audio.zmdcdn.me/song-320.mp3", result["url"])
        self.assertEqual("audio/mpeg", result["content_type"])
        self.assertEqual(2, opener.open.call_count)
        api_request = opener.open.call_args_list[1].args[0]
        query = parse_qs(urlsplit(api_request.full_url).query)
        self.assertEqual(["XwsdXWtaDHNH"], query["id"])
        self.assertEqual(["1787976165"], query["ctime"])
        self.assertEqual(["1.20.4"], query["version"])
        self.assertEqual(["khoa-web-thu"], query["apiKey"])
        canonical = "ctime=1787976165id=XwsdXWtaDHNHversion=1.20.4"
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        expected_signature = hmac.new(
            b"bi-mat-web-thu",
            f"/api/v2/song/get/streaming{digest}".encode(),
            hashlib.sha512,
        ).hexdigest()
        self.assertEqual([expected_signature], query["sig"])


class ZingWebKeyTests(unittest.TestCase):
    """c2a: khoá web Zing lấy từ mã trang lúc chạy, không để trong git."""

    def setUp(self):
        self.streaming = load_streaming_module()

    def test_trich_cap_khoa_tu_ma_web(self):
        # Đúng dạng đo trong main.min.js 1.20.4 (giá trị ở đây là giả).
        js = 'n.d(t,"c",(function(){return a}));var r="' + "A" * 32 + '",i="' + "b1" * 16 + '",a={pub:1}'
        self.assertEqual({"api_key": "A" * 32, "api_secret": "b1" * 16}, self.streaming.extract_zing_web_keys(js))
        self.assertIsNone(self.streaming.extract_zing_web_keys('var r="ngan",i="' + "b" * 32 + '"'))

    def _mo(self, *than, url="https://zingmp3.vn/"):
        class Resp(io.BytesIO):
            headers = {}

            def geturl(self_inner):
                return self_inner._url

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_):
                self_inner.close()

        phan_hoi = []
        for i, b in enumerate(than):
            r = Resp(b)
            r._url = url if i == 0 else "https://zmdjs.zmdcdn.me/zmp3-desktop/v1.20.4/static/js/main.min.js"
            phan_hoi.append(r)
        opener = unittest.mock.Mock()
        opener.open.side_effect = phan_hoi
        return opener

    def test_tai_trang_chu_roi_bo_ma_main(self):
        html = b'<script src="https://zmdjs.zmdcdn.me/zmp3-desktop/v1.20.4/static/js/main.min.js"></script>'
        js = ('var r="' + "K" * 32 + '",i="' + "S" * 32 + '"').encode()
        opener = self._mo(html, js)
        with patch.object(self.streaming, "build_opener", return_value=opener):
            keys = self.streaming.fetch_zing_web_keys(timeout=5)
        self.assertEqual({"api_key": "K" * 32, "api_secret": "S" * 32}, keys)
        self.assertEqual("https://zmdjs.zmdcdn.me/zmp3-desktop/v1.20.4/static/js/main.min.js",
                         opener.open.call_args_list[1].args[0].full_url)

    def test_khong_thay_bo_ma_hoac_bi_chuyen_huong_la(self):
        with patch.object(self.streaming, "build_opener", return_value=self._mo(b"<html></html>")):
            with self.assertRaisesRegex(self.streaming.StreamUnavailableError, "zing_keys_unavailable"):
                self.streaming.fetch_zing_web_keys()
        with patch.object(self.streaming, "build_opener", return_value=self._mo(b"x", url="https://evil.example/")):
            with self.assertRaisesRegex(self.streaming.StreamUnavailableError, "unsafe_stream_redirect"):
                self.streaming.fetch_zing_web_keys()

    def test_thieu_khoa_thi_khong_goi_mang(self):
        with patch.object(self.streaming, "build_opener") as mo:
            with self.assertRaisesRegex(self.streaming.StreamUnavailableError, "zing_keys_missing"):
                self.streaming.resolve_zing_stream(
                    "https://zingmp3.vn/bai-hat/Thuc-Giac-Da-LAB/ZZ90FD0B.html", api_key="", api_secret="")
        mo.assert_not_called()


class FacebookResolverTests(unittest.TestCase):
    """Nguồn Facebook: nghe và xem tách riêng, đúng như cặp youtube / youtube_video.

    Dữ liệu giả ở đây lấy theo đúng hình dạng ĐO ĐƯỢC ngày 19/09/2026 trên một reel
    thật: một luồng chỉ-có-tiếng (m4a, mp4a.40.5) và hai tệp gộp sẵn "hd"/"sd" mà
    yt-dlp báo vcodec/acodec/height đều là NA — chính chỗ này làm khuôn chọn định dạng
    của YouTube không dùng lại được."""

    def setUp(self):
        self.streaming = load_streaming_module()
        self.video_id = "1807802260572674"

    def _extractor(self, result):
        def extract(watch_url, timeout):
            self.asked = (watch_url, timeout)
            if isinstance(result, Exception):
                raise result
            return result

        return extract

    def _info(self, *, audio=True):
        formats = []
        if audio:
            formats.append(
                {
                    "format_id": "38352274251084823a",
                    "ext": "m4a",
                    "acodec": "mp4a.40.5",
                    "vcodec": "none",
                    "url": "https://video-hkg1-2.xx.fbcdn.net/v/tieng.m4a",
                }
            )
        formats += [
            {"format_id": "sd", "ext": "mp4", "url": "https://video-hkg1-2.xx.fbcdn.net/v/sd.mp4"},
            {"format_id": "hd", "ext": "mp4", "url": "https://video-hkg1-2.xx.fbcdn.net/v/hd.mp4"},
        ]
        return {"formats": formats, "http_headers": {"User-Agent": "yt-dlp-client"}}

    def test_token_round_trip_is_bound_to_facebook_and_expiry(self):
        token = self.streaming.create_stream_token(
            self.video_id, "integration-secret", source="facebook", now=1_000, ttl=300
        )
        self.assertEqual(
            ("facebook", self.video_id),
            self.streaming.verify_stream_token(token, "integration-secret", now=1_299),
        )
        with self.assertRaises(self.streaming.InvalidStreamTokenError):
            self.streaming.verify_stream_token(token, "integration-secret", now=1_301)

    def test_token_rejects_a_non_numeric_id(self):
        with self.assertRaises(ValueError):
            self.streaming.create_stream_token(
                "https://www.facebook.com/reel/1807802260572674/",
                "integration-secret",
                source="facebook",
            )

    def test_audio_resolver_prefers_the_audio_only_stream(self):
        result = self.streaming.resolve_facebook_audio(
            self.video_id, extractor=self._extractor(self._info())
        )
        self.assertEqual("https://video-hkg1-2.xx.fbcdn.net/v/tieng.m4a", result["url"])
        self.assertTrue(result["content_type"].startswith("audio/"), result["content_type"])
        self.assertEqual({"User-Agent": "yt-dlp-client"}, result["headers"])

    def test_audio_resolver_falls_back_to_the_muxed_file(self):
        result = self.streaming.resolve_facebook_audio(
            self.video_id, extractor=self._extractor(self._info(audio=False))
        )
        self.assertEqual("https://video-hkg1-2.xx.fbcdn.net/v/sd.mp4", result["url"])
        self.assertEqual("video/mp4", result["content_type"])

    def test_video_resolver_picks_hd_at_720_and_sd_below(self):
        cao = self.streaming.resolve_facebook_video(
            f"{self.video_id}:720", extractor=self._extractor(self._info())
        )
        self.assertEqual("https://video-hkg1-2.xx.fbcdn.net/v/hd.mp4", cao["url"])
        self.assertEqual("video/mp4", cao["content_type"])
        thap = self.streaming.resolve_facebook_video(
            f"{self.video_id}:480", extractor=self._extractor(self._info())
        )
        self.assertEqual("https://video-hkg1-2.xx.fbcdn.net/v/sd.mp4", thap["url"])

    def test_resolver_rejects_a_stream_outside_fbcdn(self):
        info = {"formats": [{"format_id": "hd", "ext": "mp4", "url": "https://evil.example/ro-ri.mp4"}]}
        with self.assertRaises(self.streaming.StreamUnavailableError):
            self.streaming.resolve_facebook_video(
                f"{self.video_id}:720", extractor=self._extractor(info)
            )

    def test_resolver_fails_when_yt_dlp_exits_nonzero(self):
        with self.assertRaises(self.streaming.StreamUnavailableError):
            self.streaming.resolve_facebook_audio(
                self.video_id,
                extractor=self._extractor(RuntimeError("ERROR: Cannot parse data")),
            )

    def test_resolver_asks_yt_dlp_for_the_watch_page(self):
        self.streaming.resolve_facebook_audio(
            self.video_id, extractor=self._extractor(self._info())
        )
        self.assertEqual(
            f"https://www.facebook.com/watch/?v={self.video_id}", self.asked[0]
        )

    def test_video_resolver_rejects_a_target_without_a_height(self):
        with self.assertRaises(ValueError):
            self.streaming.resolve_facebook_video(
                self.video_id, extractor=self._extractor(self._info())
            )


class YouTubeAudioResolverTests(unittest.TestCase):
    def setUp(self):
        self.streaming = load_streaming_module()

    def _extractor(self, result):
        def extract(watch_url, timeout):
            self.asked = (watch_url, timeout)
            if isinstance(result, Exception):
                raise result
            return result

        return extract

    def test_youtube_token_round_trip_is_bound_to_video_and_expiry(self):
        token = self.streaming.create_stream_token(
            "dQw4w9WgXcQ", "integration-secret", source="youtube", now=1_000, ttl=300
        )
        self.assertEqual(
            ("youtube", "dQw4w9WgXcQ"),
            self.streaming.verify_stream_token(
                token, "integration-secret", now=1_299
            ),
        )
        with self.assertRaises(self.streaming.InvalidStreamTokenError):
            self.streaming.verify_stream_token(
                token, "integration-secret", now=1_301
            )

    def test_youtube_token_rejects_a_non_video_id(self):
        with self.assertRaises(ValueError):
            self.streaming.create_stream_token(
                "https://youtube.com/watch?v=dQw4w9WgXcQ",
                "integration-secret",
                source="youtube",
            )

    def test_resolver_returns_googlevideo_audio_with_forwarded_headers(self):
        info = {
            "url": "https://rr3---sn-abc.googlevideo.com/videoplayback?mime=audio/mp4",
            "ext": "m4a",
            "http_headers": {"User-Agent": "yt-dlp-client"},
        }
        result = self.streaming.resolve_youtube_audio(
            "dQw4w9WgXcQ", extractor=self._extractor(info)
        )

        self.assertEqual(info["url"], result["url"])
        self.assertEqual("audio/mp4", result["content_type"])
        self.assertEqual({"User-Agent": "yt-dlp-client"}, result["headers"])

    def test_resolver_maps_webm_opus_to_its_content_type(self):
        info = {
            "url": "https://rr1---sn-xyz.googlevideo.com/videoplayback",
            "ext": "webm",
        }
        result = self.streaming.resolve_youtube_audio(
            "dQw4w9WgXcQ", extractor=self._extractor(info)
        )
        self.assertEqual("audio/webm", result["content_type"])

    def test_resolver_rejects_a_stream_outside_googlevideo(self):
        info = {"url": "https://evil.example/leak.m4a", "ext": "m4a"}
        with self.assertRaises(self.streaming.StreamUnavailableError):
            self.streaming.resolve_youtube_audio(
                "dQw4w9WgXcQ", extractor=self._extractor(info)
            )

    def test_resolver_fails_when_yt_dlp_exits_nonzero(self):
        with self.assertRaises(self.streaming.StreamUnavailableError):
            self.streaming.resolve_youtube_audio(
                "dQw4w9WgXcQ", extractor=self._extractor(RuntimeError("ERROR: Video unavailable"))
            )

    def test_cache_time_follows_the_googlevideo_expiry(self):
        seconds = self.streaming.stream_cache_seconds
        url = "https://rr3---sn-abc.googlevideo.com/videoplayback?expire={}&mime=audio/mp4"
        self.assertEqual(5 * 3600, seconds(url.format(1_000 + 6 * 3600), now=1_000))
        self.assertEqual(1_800 - 600, seconds(url.format(1_000 + 1_800), now=1_000))
        self.assertEqual(0, seconds(url.format(1_000 + 300), now=1_000))
        self.assertEqual(120, seconds("https://zmdcdn.me/song.mp3?authen=x", now=1_000))

    def test_resolver_asks_yt_dlp_for_the_watch_page_of_the_video(self):
        info = {"url": "https://rr1---sn-xyz.googlevideo.com/videoplayback", "ext": "m4a"}
        self.streaming.resolve_youtube_audio("dQw4w9WgXcQ", extractor=self._extractor(info))
        self.assertEqual("https://www.youtube.com/watch?v=dQw4w9WgXcQ", self.asked[0])

    def test_resolver_rejects_an_invalid_video_id(self):
        with self.assertRaises(ValueError):
            self.streaming.resolve_youtube_audio(
                "not-a-valid-id", extractor=self._extractor({})
            )


if __name__ == "__main__":
    unittest.main()
