"""Integration API v1 của trình phát trong c2a — chuyển từ test máy chủ của add-on
(youtube_player/tests/test_server.py) sang FastAPI, bỏ các ca của trang web
player (chủ máy 14/09/2026 chọn chỉ phát ra loa/tivi).

Tích hợp HA của repo gọi đúng các đường dẫn và mã lỗi này; lệch một chữ là HA
báo lỗi mà không ai biết vì sao.
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

H = {"Authorization": "Bearer token-thu"}


class YouTubePhatApiTest(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import youtube_phat
        from services.youtube_phat import dich_vu

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        (Path(self._tmp.name) / "integration_token").write_text("token-thu", encoding="utf-8")
        (Path(self._tmp.name) / "zing_keys.json").write_text(
            '{"api_key": "khoa-web-thu", "api_secret": "bi-mat-web-thu"}', encoding="utf-8")
        self.core = dich_vu._reset_for_tests(Path(self._tmp.name))
        self.addCleanup(dich_vu._reset_for_tests)
        cfg = patch.object(dich_vu, "public_base_url_cau_hinh", return_value="")
        cfg.start()
        self.addCleanup(cfg.stop)
        app = FastAPI()
        app.include_router(youtube_phat.create_router())
        self.client = TestClient(app)

    def get(self, path, **kw):
        return self.client.get(f"/yt{path}", **kw)

    def post(self, path, json=None, **kw):
        return self.client.post(f"/yt{path}", json=json, **kw)

    def nho_zing(self, target):
        self.core.remember_public_zing_results([{"source": "zing", "kind": "song", "url": target}])

    # ── xác thực, token ────────────────────────────────────────────────────
    def test_token_sinh_mot_lan_roi_dung_lai(self) -> None:
        from services.youtube_phat.dich_vu import resolve_integration_token

        with TemporaryDirectory() as d:
            a = resolve_integration_token(Path(d))
            self.assertEqual(a, resolve_integration_token(Path(d)))
            self.assertGreaterEqual(len(a), 32)
            self.assertEqual(oct((Path(d) / "integration_token").stat().st_mode & 0o777), "0o600")

    def test_api_doi_bearer(self) -> None:
        for headers in ({}, {"Authorization": "Bearer sai"}):
            with self.subTest(headers=headers):
                r = self.get("/api/integration/health", headers=headers)
                self.assertEqual((401, {"error": "invalid_auth"}), (r.status_code, r.json()))
        d = self.get("/api/integration/health", headers=H).json()
        self.assertEqual(("ok", "1"), (d["status"], d["api_version"]))
        self.assertIn("play", d["capabilities"])
        self.assertEqual(["youtube", "zing", "facebook", "http"], d["playback_sources"])

    # ── phiên phát ─────────────────────────────────────────────────────────
    def test_play_status_history_stop(self) -> None:
        r = self.post("/api/integration/play", {"target": "https://youtu.be/dQw4w9WgXcQ"}, headers=H)
        self.assertEqual(200, r.status_code)
        self.assertEqual("dQw4w9WgXcQ", r.json()["item"]["id"])
        st = self.get("/api/integration/status", headers=H).json()
        self.assertEqual(("playing", 1), (st["state"], st["history_count"]))
        self.assertEqual(st["session"]["item"], st["item"])
        his = self.get("/api/integration/history", headers=H).json()
        self.assertEqual((1, "dQw4w9WgXcQ"), (his["total"], his["items"][0]["id"]))
        dung = self.post("/api/integration/stop", headers=H).json()
        self.assertTrue(dung["success"])
        self.assertEqual("idle", dung["state"])

    def test_dung_theo_revision_khong_dung_phien_moi_hon(self) -> None:
        dau = self.post("/api/integration/play", {"target": "dQw4w9WgXcQ"}, headers=H).json()
        sau = self.post("/api/integration/play", {"target": "M7lc1UVf-VE"}, headers=H).json()
        cu = self.post("/api/integration/stop", {"expected_revision": dau["session_revision"]}, headers=H).json()
        self.assertFalse(cu["stopped"])
        self.assertEqual("M7lc1UVf-VE", cu["session"]["item"]["id"])
        moi = self.post("/api/integration/stop", {"expected_revision": sau["session_revision"]}, headers=H).json()
        self.assertTrue(moi["stopped"])

    @patch("services.youtube_phat.dich_vu.search_youtube")
    def test_tim_roi_phat_giu_metadata_va_hang_doi(self, tim) -> None:
        tim.return_value = [
            {"source": "youtube", "kind": "video", "id": "dQw4w9WgXcQ", "title": "Never Gonna",
             "channel": "Rick Astley", "duration": 213, "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
             "thumbnail": "https://img.example/a.jpg"},
            {"source": "youtube", "kind": "video", "id": "M7lc1UVf-VE", "title": "Dev Live",
             "channel": "YT", "duration": 160, "url": "https://www.youtube.com/watch?v=M7lc1UVf-VE",
             "thumbnail": "https://img.example/b.jpg"}]
        d = self.get("/api/integration/search?q=Rick+Astley&limit=5", headers=H).json()
        self.assertEqual((True, 2), (d["success"], d["total"]))
        tim.assert_called_once_with("Rick Astley", limit=5)
        self.post("/api/integration/play", {"target": "https://youtu.be/dQw4w9WgXcQ"}, headers=H)
        s = self.get("/api/integration/status", headers=H).json()["session"]
        self.assertEqual(("Never Gonna", "Rick Astley", 213), (s["item"]["title"], s["item"]["artist"], s["duration"]))
        self.assertEqual((0, 2), (s["queue"]["index"], len(s["queue"]["items"])))

    @patch("services.youtube_phat.dich_vu.search_youtube", return_value=[])
    def test_tim_nhan_link_youtube_dan_vao(self, tim) -> None:
        # Link chép từ app YouTube dài hơn giới hạn 120 ký tự của từ khoá.
        link = "https://www.youtube.com/watch?app=desktop&v=llPioQNSBLY&list=RDllPioQNSBLY&start_radio=1&pp=ygUadHLDs3QgdGluIHbDoG8gbOG7nWkgaOG7qWGgBwE%3D&ra=m"
        r = self.client.get("/yt/api/integration/search", params={"q": link}, headers=H)
        self.assertEqual(200, r.status_code)
        tim.assert_called_once_with(link, limit=20)
        r = self.client.get("/yt/api/integration/search", params={"q": "x" * 2049}, headers=H)
        self.assertEqual((400, {"error": "invalid_search_query"}), (r.status_code, r.json()))

    def test_tim_sai_nguon_va_sai_cau(self) -> None:
        r = self.get("/api/integration/search?source=unknown&q=music", headers=H)
        self.assertEqual((400, {"error": "invalid_search_source"}), (r.status_code, r.json()))
        r = self.get("/api/integration/search?q=", headers=H)
        self.assertEqual((400, {"error": "invalid_search_query"}), (r.status_code, r.json()))

    @patch("services.youtube_phat.dich_vu.search_zing")
    def test_phien_zing_ghi_loa_va_am_luong(self, tim) -> None:
        target = "https://zingmp3.vn/bai-hat/Thuc-Giac/ZZ90FD0B.html"
        tim.return_value = [{"source": "zing", "kind": "song", "id": "ZZ90FD0B", "url": target,
                             "title": "Thức Giấc", "channel": "Da LAB", "duration": 269,
                             "thumbnail": "https://photo-resize-zmp3.zmdcdn.me/c.jpg"}]
        self.get("/api/integration/search?source=zing&q=Da+LAB&limit=5", headers=H)
        d = self.post("/api/integration/session", {
            "source": "zing", "target": target, "volume_level": 0.42,
            "output_entity_ids": ["media_player.phong_khach", "media_player.nha_bep"]}, headers=H).json()
        self.assertEqual("Thức Giấc", d["session"]["item"]["title"])
        self.assertEqual(0.42, d["session"]["volume_level"])

    def test_phien_http_hop_le_va_tu_choi_trang_web(self) -> None:
        d = self.post("/api/integration/session", {
            "source": "http", "target": "https://audio.example/album/My%20Song.flac",
            "media_content_type": "audio/flac", "output_entity_ids": ["media_player.esp32"]}, headers=H).json()
        self.assertEqual("My Song.flac", d["session"]["item"]["title"])
        r = self.post("/api/integration/session", {
            "source": "http", "target": "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
            "output_entity_ids": ["media_player.speaker"]}, headers=H)
        self.assertEqual((400, {"error": "invalid_http_audio_target"}), (r.status_code, r.json()))

    def test_than_sai_dang_giu_ma_loi_on_dinh(self) -> None:
        for than in (None, [], {"target": "khong-phai-youtube"}):
            with self.subTest(than=than):
                r = self.client.post("/yt/api/integration/play", json=than, headers=H)
                self.assertEqual(400, r.status_code)
                self.assertIn(r.json()["error"], {"invalid_request", "invalid_youtube_target"})

    # ── luồng cho loa ──────────────────────────────────────────────────────
    @patch("services.youtube_phat.dich_vu.resolve_zing_stream")
    def test_zing_chua_tim_thi_403_khong_giai(self, giai) -> None:
        r = self.post("/api/integration/stream", {
            "source": "zing", "target": "https://zingmp3.vn/bai-hat/Unverified/ZZ90FD0B.html"}, headers=H)
        self.assertEqual((403, {"error": "unverified_zing_target"}), (r.status_code, r.json()))
        giai.assert_not_called()

    @patch("api.youtube_phat.urlopen")
    @patch("services.youtube_phat.dich_vu.resolve_zing_stream")
    def test_luong_zing_ky_url_theo_dia_chi_goi_toi_va_tiep_song_range(self, giai, mo) -> None:
        target = "https://zingmp3.vn/bai-hat/Thuc-Giac/ZZ90FD0B.html"
        self.nho_zing(target)
        giai.return_value = {"url": "https://audio.zmdcdn.me/song.mp3",
                             "headers": {"Referer": "https://zingmp3.vn/"}, "content_type": "audio/mpeg"}
        up = io.BytesIO(b"MP3!")
        up.headers = {"Content-Type": "audio/mpeg", "Content-Length": "4",
                      "Content-Range": "bytes 0-3/4", "Accept-Ranges": "bytes"}
        up.getcode = lambda: 206
        mo.return_value = up
        d = self.client.post("/yt/api/integration/stream", json={"source": "zing", "target": target},
                             headers={**H, "host": "172.16.10.38:3030"}).json()
        self.assertTrue(d["stream_url"].startswith("http://172.16.10.38:3030/yt/api/stream/"), d)
        token = d["stream_url"].rsplit("/", 1)[-1]
        r = self.get(f"/api/stream/{token}", headers={"Range": "bytes=0-3"})
        self.assertEqual((206, "audio/mpeg", b"MP3!"), (r.status_code, r.headers["content-type"], r.content))
        self.assertEqual("bytes=0-3", mo.call_args.args[0].get_header("Range"))

    @patch("services.youtube_phat.dich_vu.resolve_zing_stream")
    def test_khoa_zing_doc_tu_thu_muc_du_lieu_thieu_thi_502(self, giai) -> None:
        target = "https://zingmp3.vn/bai-hat/Thuc-Giac/ZZ90FD0B.html"
        self.nho_zing(target)
        giai.return_value = {"url": "https://audio.zmdcdn.me/song.mp3", "headers": {}, "content_type": "audio/mpeg"}
        self.post("/api/integration/stream", {"source": "zing", "target": target}, headers=H)
        giai.assert_called_once_with(target, api_key="khoa-web-thu", api_secret="bi-mat-web-thu")
        (Path(self._tmp.name) / "zing_keys.json").unlink()
        self.core.stream_cache.clear()
        giai.reset_mock()
        from services.youtube_phat.streaming import StreamUnavailableError

        with patch("services.youtube_phat.dich_vu.fetch_zing_web_keys",
                   side_effect=StreamUnavailableError("zing_keys_unavailable")):
            r = self.post("/api/integration/stream", {"source": "zing", "target": target}, headers=H)
        self.assertEqual((502, {"error": "stream_unavailable"}), (r.status_code, r.json()))
        giai.assert_not_called()

    def test_khoa_zing_tu_lay_luu_dem_24_gio_va_lay_lai_khi_zing_doi_khoa(self) -> None:
        from services.youtube_phat.streaming import StreamUnavailableError

        (Path(self._tmp.name) / "zing_keys.json").unlink()  # ai cài cũng chạy: không có tệp đặt tay
        k1 = {"api_key": "khoa-1", "api_secret": "bi-mat-1"}
        k2 = {"api_key": "khoa-2", "api_secret": "bi-mat-2"}
        with patch("services.youtube_phat.dich_vu.fetch_zing_web_keys", side_effect=[k1, k2]) as lay:
            self.assertEqual(k1, self.core.zing_keys())
            self.assertEqual(k1, self.core.zing_keys())          # trong 24 giờ: dùng bản đệm
            self.assertEqual(1, lay.call_count)
            dem = Path(self._tmp.name) / "zing_keys_web.json"
            import json as _json
            cu = _json.loads(dem.read_text(encoding="utf-8"))
            dem.write_text(_json.dumps({**cu, "luc": 0}), encoding="utf-8")   # đệm quá hạn
            self.assertEqual(k2, self.core.zing_keys())
        with patch("services.youtube_phat.dich_vu.fetch_zing_web_keys",
                   side_effect=StreamUnavailableError("zing_keys_unavailable")):
            self.assertEqual(k2, self.core.zing_keys(lam_moi=True))   # mạng hỏng: dùng bản đệm cũ

        target = "https://zingmp3.vn/bai-hat/Thuc-Giac/ZZ90FD0B.html"
        self.nho_zing(target)
        ok = {"url": "https://audio.zmdcdn.me/song.mp3", "headers": {}, "content_type": "audio/mpeg"}
        with patch("services.youtube_phat.dich_vu.fetch_zing_web_keys", return_value=k1) as lay, \
             patch("services.youtube_phat.dich_vu.resolve_zing_stream",
                   side_effect=[StreamUnavailableError("stream_provider_failed"), ok]) as giai:
            r = self.post("/api/integration/stream", {"source": "zing", "target": target}, headers=H)
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual(1, lay.call_count)   # khoá cũ bị Zing từ chối → lấy lại đúng một lần
        self.assertEqual([k2["api_key"], k1["api_key"]], [c.kwargs["api_key"] for c in giai.call_args_list])

    @patch("services.youtube_phat.dich_vu.resolve_zing_stream")
    def test_zing_khong_phat_duoc_502(self, giai) -> None:
        from services.youtube_phat.streaming import StreamUnavailableError

        target = "https://zingmp3.vn/bai-hat/Thuc-Giac/ZZ90FD0B.html"
        self.nho_zing(target)
        giai.side_effect = StreamUnavailableError("stream_provider_failed")
        r = self.post("/api/integration/stream", {"source": "zing", "target": target}, headers=H)
        self.assertEqual((502, {"error": "stream_unavailable"}), (r.status_code, r.json()))

    def test_chu_ky_sai_403_va_range_la_400(self) -> None:
        r = self.get("/api/stream/khong-hop-le")
        self.assertEqual((403, {"error": "invalid_stream_token"}), (r.status_code, r.json()))

    @patch("api.youtube_phat.urlopen")
    @patch("services.youtube_phat.dich_vu.resolve_youtube_audio")
    def test_youtube_audio_giai_mot_lan_tiep_song_va_HEAD(self, giai, mo) -> None:
        giai.return_value = {"url": "https://rr3---sn-abc.googlevideo.com/videoplayback",
                             "headers": {"User-Agent": "TriTue"}, "content_type": "audio/mp4"}
        d = self.post("/api/integration/stream", {"source": "youtube", "target": "https://youtu.be/dQw4w9WgXcQ"},
                      headers=H).json()
        self.assertEqual(("youtube", "audio/mp4"), (d["source"], d["media_content_type"]))
        self.assertTrue(d["stream_url"].startswith("http://testserver/yt/api/stream/"))
        token = d["stream_url"].rsplit("/", 1)[-1]
        up = io.BytesIO(b"M4A!")
        up.headers = {"Content-Type": "audio/mp4", "Content-Length": "4"}
        up.getcode = lambda: 200
        mo.return_value = up
        r = self.get(f"/api/stream/{token}")
        self.assertEqual((200, b"M4A!"), (r.status_code, r.content))
        giai.assert_called_once_with("dQw4w9WgXcQ")

        dau = io.BytesIO(b"")
        dau.headers = {"Content-Type": "audio/mp4", "Content-Range": "bytes 0-0/3449447"}
        with patch("api.youtube_phat.urlopen", return_value=_NgCanh(dau)) as mo_head:
            r = self.client.head(f"/yt/api/stream/{token}")
        self.assertEqual(200, r.status_code)
        self.assertEqual(("bytes", "3449447"), (r.headers["accept-ranges"], r.headers["content-length"]))
        self.assertEqual("bytes=0-0", mo_head.call_args.args[0].get_header("Range"))

        r = self.get(f"/api/stream/{token}", headers={"Range": "chu"})
        self.assertEqual((400, {"error": "invalid_range"}), (r.status_code, r.json()))

    @patch("api.youtube_phat.urlopen")
    @patch("services.youtube_phat.dich_vu.resolve_youtube_audio")
    def test_link_cu_bi_youtube_tu_choi_thi_giai_lai_mot_lan(self, giai, mo) -> None:
        from urllib.error import HTTPError

        giai.side_effect = [
            {"url": "https://rr3---sn-cu.googlevideo.com/videoplayback", "headers": {}, "content_type": "audio/mp4"},
            {"url": "https://rr3---sn-moi.googlevideo.com/videoplayback", "headers": {}, "content_type": "audio/mp4"},
        ]
        up = io.BytesIO(b"M4A!")
        up.headers = {"Content-Type": "audio/mp4", "Content-Length": "4"}
        up.getcode = lambda: 200

        def mo_url(req, timeout):
            if "sn-cu" in req.full_url:
                raise HTTPError(req.full_url, 403, "Forbidden", {}, None)
            return up

        mo.side_effect = mo_url
        d = self.post("/api/integration/stream", {"source": "youtube", "target": "dQw4w9WgXcQ"}, headers=H).json()
        r = self.get(f"/api/stream/{d['stream_url'].rsplit('/', 1)[-1]}")
        self.assertEqual((200, b"M4A!"), (r.status_code, r.content))
        self.assertEqual(2, giai.call_count)

    def test_youtube_playlist_va_nguon_la_bi_tu_choi(self) -> None:
        r = self.post("/api/integration/stream", {
            "source": "youtube", "target": "https://www.youtube.com/playlist?list=PL1234567890"}, headers=H)
        self.assertEqual((400, {"error": "youtube_audio_requires_video"}), (r.status_code, r.json()))
        r = self.post("/api/integration/stream", {"source": "spotify", "target": "x"}, headers=H)
        self.assertEqual((400, {"error": "unsupported_stream_source"}), (r.status_code, r.json()))

    @patch("services.youtube_phat.dich_vu.resolve_youtube_audio")
    def test_url_goc_cau_hinh_thang_dia_chi_request(self, giai) -> None:
        from services.youtube_phat import dich_vu

        giai.return_value = {"url": "https://x.googlevideo.com/v", "headers": {}, "content_type": "audio/mp4"}
        with patch.object(dich_vu, "public_base_url_cau_hinh", return_value="http://10.0.0.9:3030/yt"):
            d = self.post("/api/integration/stream", {"source": "youtube", "target": "dQw4w9WgXcQ"},
                          headers=H).json()
        self.assertTrue(d["stream_url"].startswith("http://10.0.0.9:3030/yt/api/stream/"))

    def test_url_play_chuan_hoa_playlist_short_va_lich_su_gioi_han(self) -> None:
        self.core.max_history = 2
        v = self.post("/api/integration/play", {
            "target": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1234567890abc"}, headers=H).json()
        self.assertEqual(("video", "PL1234567890abc"), (v["item"]["kind"], v["item"]["playlist_id"]))
        p = self.post("/api/integration/play", {"target": "https://youtube.com/playlist?list=PL1234567890abc"},
                      headers=H).json()
        self.assertEqual("playlist", p["item"]["kind"])
        self.post("/api/integration/play", {"target": "https://youtube.com/shorts/aqz-KE-bpKQ"}, headers=H)
        his = self.get("/api/integration/history", headers=H).json()
        self.assertEqual(2, his["total"])
        self.assertEqual("aqz-KE-bpKQ", his["items"][0]["id"])


class _NgCanh:
    """urlopen trả về dùng được với `with`."""

    def __init__(self, r):
        self.r = r

    def __enter__(self):
        return self.r

    def __exit__(self, *a):
        return False


class KetNoiChoCaiDatTest(unittest.TestCase):
    def test_tra_url_va_token_chi_cho_quan_tri(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import youtube_phat
        from services.youtube_phat import dich_vu

        with TemporaryDirectory() as d:
            core = dich_vu._reset_for_tests(Path(d))
            self.addCleanup(dich_vu._reset_for_tests)
            app = FastAPI()
            app.include_router(youtube_phat.create_router())
            c = TestClient(app)
            with patch.object(dich_vu, "public_base_url_cau_hinh", return_value=""), \
                 patch("api.youtube_phat.require_admin", lambda *a, **k: None):
                r = c.get("/api/youtube-phat/ket-noi", headers={"host": "172.16.10.38:3030"}).json()
            self.assertEqual(("http://172.16.10.38:3030/yt", core.integration_token), (r["url"], r["token"]))


if __name__ == "__main__":
    unittest.main()
