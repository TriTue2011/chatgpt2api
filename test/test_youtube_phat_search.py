"""Bộ test của add-on TriTue YouTube Player (youtube_player/tests), chạy trên bản
đã chuyển vào c2a (`services/youtube_phat`) — chứng minh hành vi giữ nguyên."""

import importlib.util
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "services" / "youtube_phat"
SEARCH_MODULE_PATH = APP_DIR / "search.py"


def load_search_module():
    spec = importlib.util.spec_from_file_location(
        "tritue_youtube_player_search", SEARCH_MODULE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable_to_load_search_module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FacebookMetadataSearchTests(unittest.TestCase):
    """Nguồn Facebook: chỉ tra cứu được bằng LINK DÁN VÀO, không tìm theo từ khoá."""

    def setUp(self):
        self.search = load_search_module()

    def test_facebook_url_query_recognizes_pasted_links(self):
        doc = self.search.facebook_url_query
        self.assertEqual("1807802260572674", doc("https://www.facebook.com/watch/?v=1807802260572674"))
        self.assertEqual("1807802260572674", doc("https://www.facebook.com/reel/1807802260572674/"))
        self.assertEqual(
            "1135095972510953",
            doc("https://www.facebook.com/100080316830026/videos/1135095972510953/"),
        )
        # Dạng mà trình duyệt CHƯA ĐĂNG NHẬP nhận được khi bấm link chia sẻ: Facebook
        # chèn TÊN BÀI vào giữa "videos" và mã, nên lấy đoạn kế tiếp sẽ ra tên bài.
        self.assertEqual(
            "1807802260572674",
            doc(
                "https://www.facebook.com/Emgaibay.686868/videos/"
                "c%C3%B3-nh%E1%BB%AFng-chuy%E1%BB%87n/1807802260572674/?rdid=Nu17Gu2Uz4GFI9xf"
            ),
        )
        # Link chia sẻ KHÔNG mang mã video — `resolve_facebook_share` lo việc đó.
        self.assertIsNone(doc("https://www.facebook.com/share/v/1JjG1BpepR/"))
        self.assertIsNone(doc("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertIsNone(doc("Bolero trữ tình"))

    def test_parse_facebook_payload_returns_video_metadata(self):
        entry = {
            "id": "1807802260572674",
            "title": "Có những chuyện có lẽ nên để trong lòng",
            "uploader": "Em Gái Bay",
            "duration": 148.821,
            "thumbnails": [{"url": "https://scontent.xx.fbcdn.net/v/anh.jpg"}],
        }
        items = self.search.parse_facebook_payload({"entries": [entry]}, limit=5)
        self.assertEqual(1, len(items))
        self.assertEqual("facebook", items[0]["source"])
        self.assertEqual("1807802260572674", items[0]["id"])
        self.assertEqual(
            "https://www.facebook.com/watch/?v=1807802260572674", items[0]["url"]
        )
        self.assertEqual("Em Gái Bay", items[0]["channel"])
        self.assertEqual(148, items[0]["duration"])

    def test_parse_facebook_payload_strips_the_count_prefix(self):
        """Facebook nhét số liệu vào đầu tiêu đề — đo trên dữ liệu thật 19/09/2026."""
        entry = {
            "id": "1807802260572674",
            "title": "49K views · 1.2K reactions | Có những chuyện có lẽ nên để trong lòng",
        }
        items = self.search.parse_facebook_payload({"entries": [entry]}, limit=1)
        self.assertEqual("Có những chuyện có lẽ nên để trong lòng", items[0]["title"])

    def test_parse_facebook_payload_keeps_a_real_pipe_in_the_title(self):
        entry = {"id": "1807802260572674", "title": "Sến Trữ Tình | Tuyển tập hay nhất"}
        items = self.search.parse_facebook_payload({"entries": [entry]}, limit=1)
        self.assertEqual("Sến Trữ Tình | Tuyển tập hay nhất", items[0]["title"])

    def test_parse_facebook_payload_drops_entries_without_a_numeric_id(self):
        entry = {"id": "dQw4w9WgXcQ", "title": "Video YouTube lọt vào"}
        self.assertEqual([], self.search.parse_facebook_payload({"entries": [entry]}, limit=5))

    def test_search_facebook_refuses_plain_text(self):
        with self.assertRaises(ValueError):
            self.search.search_facebook("Bolero trữ tình")

    def test_facebook_share_url_recognizes_share_links(self):
        doc = self.search.facebook_share_url
        self.assertEqual(
            "https://www.facebook.com/share/v/1JjG1BpepR/",
            doc("https://www.facebook.com/share/v/1JjG1BpepR/"),
        )
        self.assertEqual(
            "https://www.facebook.com/share/r/1JjG1BpepR/",
            doc("https://www.facebook.com/share/r/1JjG1BpepR/"),
        )
        self.assertIsNone(doc("https://www.facebook.com/reel/1807802260572674/"))
        self.assertIsNone(doc("https://example.com/share/v/1JjG1BpepR/"))

    def test_resolve_facebook_share_reads_the_internal_media_id(self):
        """Mã video KHÔNG suy ra được từ mã trong link chia sẻ: mã bài viết là
        1135095972510953 còn mã video là 1807802260572674 — phải đọc từ trang."""
        page = io.BytesIO(
            b'player_identifier:{"media_id":'
            b'"100080316830026;1135095972510953;;9::impl_1807802260572674"}'
        )
        page.headers = {}
        with patch.object(self.search, "urlopen", return_value=page) as open_url:
            video_id = self.search.resolve_facebook_share(
                "https://www.facebook.com/share/v/1JjG1BpepR/"
            )

        self.assertEqual("1807802260572674", video_id)
        request = open_url.call_args.args[0]
        # Thiếu nhóm đầu đề giống trình duyệt là Facebook trả 400 — đo 19/09/2026:
        # gọi trần 400 với 3.676 byte, gọi đủ đầu đề 200 với 298.659 byte.
        self.assertIn("Mozilla", request.get_header("User-agent"))
        self.assertEqual("navigate", request.get_header("Sec-fetch-mode"))

    def test_resolve_facebook_share_prefers_the_canonical_tag(self):
        """Dạng /share/r/ (chia sẻ reel): thẻ canonical trỏ THẲNG vào video và trang
        KHÔNG có trường impl_. Đo 19/09/2026 trên trang thật 374 KB — trước khi có
        nhánh này, đúng dạng link ấy báo `facebook_share_unreadable`."""
        page = io.BytesIO(
            b'<link rel="canonical" href="https://www.facebook.com/reel/1359730975917832/" />'
        )
        page.headers = {}
        with patch.object(self.search, "urlopen", return_value=page):
            self.assertEqual(
                "1359730975917832",
                self.search.resolve_facebook_share(
                    "https://www.facebook.com/share/r/19NLbyFKHq/"
                ),
            )

    def test_resolve_facebook_share_falls_back_when_canonical_points_at_the_post(self):
        """Dạng /share/v/: thẻ canonical trỏ vào BÀI VIẾT (mã 1135095972510953) chứ
        không trỏ vào video, nên phải bỏ qua nó và lùi về trường nội bộ."""
        page = io.BytesIO(
            b'<link rel="canonical" href="https://www.facebook.com/Trang/posts/1135095972510953/" />'
            b'"media_id":"1;2;;9::impl_1807802260572674"'
        )
        page.headers = {}
        with patch.object(self.search, "urlopen", return_value=page):
            self.assertEqual(
                "1807802260572674",
                self.search.resolve_facebook_share(
                    "https://www.facebook.com/share/v/1JjG1BpepR/"
                ),
            )

    def test_resolve_facebook_share_says_so_when_facebook_changes_the_page(self):
        """Điểm yếu đã biết: nó đọc một trường nội bộ không có tài liệu. Hỏng thì phải
        BÁO RÕ, không được lặng lẽ thành 'không tìm thấy bài nào'."""
        page = io.BytesIO(b"<html><body>Trang da doi, khong con truong cu</body></html>")
        page.headers = {}
        with patch.object(self.search, "urlopen", return_value=page):
            with self.assertRaises(self.search.SearchUnavailableError):
                self.search.resolve_facebook_share(
                    "https://www.facebook.com/share/v/1JjG1BpepR/"
                )

    def test_search_facebook_follows_a_share_link_then_looks_up_the_video(self):
        page = io.BytesIO(b'"media_id":"1;2;;9::impl_1807802260572674"')
        page.headers = {}
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"id": "1807802260572674", "title": "Tên bài"}),
            stderr="",
        )
        with patch.object(self.search, "urlopen", return_value=page), patch(
            "subprocess.run", return_value=completed
        ) as run:
            items = self.search.search_facebook(
                "https://www.facebook.com/share/v/1JjG1BpepR/"
            )

        self.assertEqual(1, len(items))
        self.assertEqual("1807802260572674", items[0]["id"])
        self.assertEqual(
            "https://www.facebook.com/watch/?v=1807802260572674",
            run.call_args.args[0][-1],
        )

    def test_search_facebook_calls_yt_dlp_through_the_venv_python(self):
        """Container c2a KHÔNG có lệnh `yt-dlp` trên PATH, chỉ có thư viện trong venv.

        Chép nguyên lệnh của add-on sang là hỏng ngay trên máy thật: đo 19/09/2026 trong
        container, `command -v yt-dlp` trả "not found" trong khi tìm kiếm YouTube vẫn
        chạy (nó gọi qua trình thông dịch). Hậu quả là `search_process_failed` bị bọc
        thành `search_unavailable`, người dùng chỉ thấy "không tìm được lúc này" —
        không lần ra được nguyên nhân. Phép kiểm này chặn đường lùi cho lần chuyển mã sau."""
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"id": "1807802260572674", "title": "Tên bài"}),
            stderr="",
        )
        with patch("subprocess.run", return_value=completed) as run:
            self.search.search_facebook(
                "https://www.facebook.com/reel/1807802260572674/"
            )

        command = run.call_args.args[0]
        self.assertEqual([sys.executable, "-m", "yt_dlp"], command[:3])
        self.assertNotIn("yt-dlp", command)


class YouTubeMetadataSearchTests(unittest.TestCase):
    def setUp(self):
        self.search = load_search_module()

    def test_parse_search_payload_returns_only_playable_video_metadata(self):
        payload = {
            "entries": [
                {
                    "id": "dQw4w9WgXcQ",
                    "title": "Never Gonna Give You Up",
                    "channel": "Rick Astley",
                    "duration": 213,
                    "thumbnails": [
                        {"url": "https://img.example/small.jpg"},
                        {"url": "https://img.example/large.jpg"},
                    ],
                },
                {"id": "not-playable", "title": "Invalid"},
                None,
            ]
        }

        self.assertEqual(
            [
                {
                    "source": "youtube",
                    "kind": "video",
                    "id": "dQw4w9WgXcQ",
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "title": "Never Gonna Give You Up",
                    "channel": "Rick Astley",
                    "duration": 213,
                    "thumbnail": "https://img.example/large.jpg",
                }
            ],
            self.search.parse_search_payload(payload, limit=10),
        )

    def test_search_is_metadata_only_and_searches_all_youtube_videos(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"entries": []}), stderr=""
        )
        with patch("subprocess.run", return_value=completed) as run:
            results = self.search.search_youtube("da LAB", limit=12)

        self.assertEqual([], results)
        command = run.call_args.args[0]
        self.assertIn("--flat-playlist", command)
        self.assertIn("--dump-single-json", command)
        self.assertIn("--skip-download", command)
        self.assertIn("--playlist-end", command)
        self.assertIn("12", command)
        # Không chỉ tab "Bài hát" của YouTube Music: nhạc AI / cover là video thường.
        self.assertEqual("ytsearch12:da LAB", command[-1])

    def test_youtube_url_query_recognizes_pasted_links(self):
        link = self.search.youtube_url_query
        # Copied from the YouTube app while a mix was playing (owner, 2026-09-14).
        pasted = (
            "https://www.youtube.com/watch?app=desktop&v=llPioQNSBLY&list=RDllPioQNSBLY"
            "&start_radio=1&pp=ygUadHLDs3QgdGluIHbDoG8gbOG7nWkgaOG7qWGgBwE%3D&ra=m"
        )
        self.assertEqual(("video", "llPioQNSBLY"), link(pasted))
        for value in (
            "https://youtu.be/llPioQNSBLY?si=AbCdEf",
            "https://m.youtube.com/shorts/llPioQNSBLY",
            "https://music.youtube.com/watch?v=llPioQNSBLY&feature=share",
            "youtube.com/watch?v=llPioQNSBLY",
            "https://www.youtube.com/live/llPioQNSBLY",
        ):
            self.assertEqual(("video", "llPioQNSBLY"), link(value), value)
        self.assertEqual(
            ("playlist", "PL1234567890abc"),
            link("https://www.youtube.com/playlist?list=PL1234567890abc"),
        )
        for value in (
            "trót tin vào lời hứa",
            "llPioQNSBLY",
            "https://example.com/watch?v=llPioQNSBLY",
            "https://www.youtube.com/@Krmusic",
            "https://www.youtube.com.evil.test/watch?v=llPioQNSBLY",
        ):
            self.assertIsNone(link(value), value)

    def test_search_youtube_looks_up_the_pasted_video_not_its_text(self):
        video = {
            "id": "llPioQNSBLY",
            "title": "Trót Tin Vào Lời Hứa",
            "channel": "Krmusic",
            "duration": 232,
            "thumbnail": "https://i.ytimg.com/vi/llPioQNSBLY/maxresdefault.jpg",
        }
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(video), stderr=""
        )
        pasted = (
            "https://www.youtube.com/watch?app=desktop&v=llPioQNSBLY&list=RDllPioQNSBLY"
            "&start_radio=1&pp=ygUadHLDs3QgdGluIHbDoG8gbOG7nWkgaOG7qWGgBwE%3D&ra=m"
        )
        self.assertGreater(len(pasted), 120)
        with patch("subprocess.run", return_value=completed) as run:
            results = self.search.search_youtube(pasted, limit=20)

        self.assertEqual(
            "https://www.youtube.com/watch?v=llPioQNSBLY", run.call_args.args[0][-1]
        )
        self.assertEqual(
            [("llPioQNSBLY", "Trót Tin Vào Lời Hứa", "Krmusic", 232)],
            [(r["id"], r["title"], r["channel"], r["duration"]) for r in results],
        )

    def test_search_youtube_lists_a_pasted_playlist(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {"entries": [{"id": "dQw4w9WgXcQ", "title": "A"}, None, {"id": "M7lc1UVf-VE"}]}
            ),
            stderr="",
        )
        with patch("subprocess.run", return_value=completed) as run:
            results = self.search.search_youtube(
                "https://www.youtube.com/playlist?list=PL1234567890abc", limit=5
            )
        self.assertEqual(
            "https://www.youtube.com/playlist?list=PL1234567890abc",
            run.call_args.args[0][-1],
        )
        self.assertEqual(["dQw4w9WgXcQ", "M7lc1UVf-VE"], [r["id"] for r in results])

    def test_parse_search_payload_adds_a_stable_thumbnail_fallback(self):
        results = self.search.parse_search_payload(
            {"entries": [{"id": "M7lc1UVf-VE", "title": "Live"}]},
            limit=1,
        )

        self.assertEqual(
            "https://i.ytimg.com/vi/M7lc1UVf-VE/hqdefault.jpg",
            results[0]["thumbnail"],
        )

    def test_parse_zing_payload_returns_public_song_metadata(self):
        payload = {
            "data": {
                "items": [
                    {
                        "keywords": [{"type": 0, "keyword": "da lab"}],
                    },
                    {
                        "suggestions": [
                            {
                                "type": 1,
                                "id": "ZZ90FD0B",
                                "title": "Thức Giấc",
                                "thumb": "https://photo-resize-zmp3.zmdcdn.me/cover.jpg",
                                "duration": 269,
                                "link": "https://zingmp3.vn/bai-hat/Thuc-Giac-Da-LAB/ZZ90FD0B.html",
                                "status": 1,
                                "privacy": 1,
                                "playStatus": 2,
                                "artists": [{"name": "Da LAB"}],
                            },
                            {"type": 4, "id": "IWZAWB8O", "name": "Da LAB"},
                        ]
                    },
                ]
            }
        }

        self.assertEqual(
            [
                {
                    "source": "zing",
                    "kind": "song",
                    "id": "ZZ90FD0B",
                    "url": "https://zingmp3.vn/bai-hat/Thuc-Giac-Da-LAB/ZZ90FD0B.html",
                    "title": "Thức Giấc",
                    "channel": "Da LAB",
                    "duration": 269,
                    "thumbnail": "https://photo-resize-zmp3.zmdcdn.me/cover.jpg",
                }
            ],
            self.search.parse_zing_payload(payload, limit=10),
        )

    def test_parse_zing_payload_rejects_lookalike_domains(self):
        payload = {
            "data": {
                "items": [
                    {
                        "suggestions": [
                            {
                                "type": 1,
                                "id": "ZZ90FD0B",
                                "title": "Unsafe result",
                                "link": (
                                    "https://notzingmp3.vn/bai-hat/Unsafe/"
                                    "ZZ90FD0B.html"
                                ),
                            }
                        ]
                    }
                ]
            }
        }

        self.assertEqual([], self.search.parse_zing_payload(payload, limit=10))

    def test_parse_zing_payload_requires_explicit_public_playback_flags(self):
        payload = {
            "data": {
                "items": [
                    {
                        "suggestions": [
                            {
                                "type": 1,
                                "id": "ZZ90FD0B",
                                "title": "Unknown entitlement",
                                "link": (
                                    "https://zingmp3.vn/bai-hat/Unknown/"
                                    "ZZ90FD0B.html"
                                ),
                            }
                        ]
                    }
                ]
            }
        }

        self.assertEqual([], self.search.parse_zing_payload(payload, limit=10))

    def test_search_zing_uses_public_suggestion_endpoint(self):
        payload = json.dumps({"err": 0, "data": {"items": []}}).encode()
        response = io.BytesIO(payload)
        response.headers = {}
        with patch.object(self.search, "urlopen", return_value=response) as open_url:
            results = self.search.search_zing("Da LAB", limit=7)

        self.assertEqual([], results)
        request = open_url.call_args.args[0]
        self.assertEqual(
            "https://ac.zingmp3.vn/v1/web/ac-suggestions?query=Da+LAB&num=7",
            request.full_url,
        )
        self.assertEqual("application/json", request.get_header("Accept"))

    def test_search_rejects_empty_or_oversized_queries(self):
        for query in ("", "x" * 121):
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    self.search.search_youtube(query)


if __name__ == "__main__":
    unittest.main()
