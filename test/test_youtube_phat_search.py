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
