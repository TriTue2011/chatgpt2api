"""Luồng HÌNH riêng cho trình duyệt khi YouTube không cho nhúng video.

Chủ máy 14/09/2026: video M2M (VEVO) báo "Video này không hoạt động" trong khung nhúng
khi mở trang bằng địa chỉ IP, "trên youtube vẫn xem được"; chọn "chỉ khi YouTube chặn",
chất lượng "theo màn hình, tối đa 1080p". Đo cùng ngày trong Chrome: luồng chỉ-hình
avc1/vp9/av1 1080p của "Trót tin vào lời hứa" phát thẳng bằng <video> 1920×1080.
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services.youtube_phat import streaming

GV = "https://rr1---sn-abc.googlevideo.com/videoplayback?itag={}"


def dinh_dang(itag, ext, vcodec, height, tbr, protocol="https", acodec="none"):
    return {"format_id": str(itag), "url": GV.format(itag), "ext": ext, "vcodec": vcodec, "acodec": acodec,
            "height": height, "tbr": tbr, "protocol": protocol}


# Đúng hình dạng danh sách định dạng yt-dlp trả cho Xruhj0zOI7A (rút gọn).
TROT_TIN = {"formats": [
    dinh_dang(140, "m4a", "none", None, 130, acodec="mp4a.40.2"),
    dinh_dang(231, "mp4", "avc1.4D401E", 480, 556, protocol="m3u8_native"),
    dinh_dang(135, "mp4", "avc1.4d401e", 480, 343),
    dinh_dang(136, "mp4", "avc1.4d401f", 720, 1002),
    dinh_dang(247, "webm", "vp9", 720, 1092),
    dinh_dang(398, "mp4", "av01.0.05M.08", 720, 775),
    dinh_dang(137, "mp4", "avc1.640028", 1080, 2806),
    dinh_dang(248, "webm", "vp9", 1080, 2014),
    dinh_dang(399, "mp4", "av01.0.08M.08", 1080, 1308),
    dinh_dang(614, "mp4", "vp09.00.40.08", 1080, 2100, protocol="m3u8_native"),
]}


class ChonLuongHinhTest(unittest.TestCase):
    def giai(self, target, info=TROT_TIN):
        return streaming.resolve_youtube_video(target, extractor=lambda url, timeout: info)

    def test_cao_nhat_khong_vuot_man_hinh_uu_tien_avc1_bo_m3u8(self) -> None:
        r = self.giai("Xruhj0zOI7A:1080")
        self.assertEqual((GV.format(137), "video/mp4", 1080, 2806), (r["url"], r["content_type"], r["height"], r["bitrate_kbps"]))
        self.assertEqual((GV.format(136), 720), (self.giai("Xruhj0zOI7A:720")["url"], self.giai("Xruhj0zOI7A:720")["height"]))
        # Không có avc1 ở độ cao đó thì lấy vp9 (webm).
        chi_vp9 = {"formats": [f for f in TROT_TIN["formats"] if not f["vcodec"].startswith("avc1")]}
        self.assertEqual((GV.format(247), "video/webm"), (lambda x: (x["url"], x["content_type"]))(self.giai("Xruhj0zOI7A:720", chi_vp9)))

    def test_video_goc_480p_thi_lay_480p_va_khong_co_hinh_thi_bao_loi(self) -> None:
        m2m = {"formats": [f for f in TROT_TIN["formats"] if (f["height"] or 0) <= 480]}
        self.assertEqual(480, self.giai("A_HekkBbd1M:1080", m2m)["height"])
        with self.assertRaises(streaming.StreamUnavailableError):
            self.giai("A_HekkBbd1M:1080", {"formats": [TROT_TIN["formats"][0]]})
        la = {"formats": [dict(TROT_TIN["formats"][2], url="https://evil.example/v.mp4")]}
        with self.assertRaises(streaming.StreamUnavailableError):
            self.giai("A_HekkBbd1M:1080", la)

    def test_dich_luong_hinh_chuan_hoa_do_cao_va_ky_duoc(self) -> None:
        self.assertEqual("Xruhj0zOI7A:720", streaming.youtube_video_target("Xruhj0zOI7A", 900))
        self.assertEqual("Xruhj0zOI7A:360", streaming.youtube_video_target("Xruhj0zOI7A", 100))
        self.assertEqual("Xruhj0zOI7A:1080", streaming.youtube_video_target("Xruhj0zOI7A", 4000))
        self.assertEqual("Xruhj0zOI7A:720", streaming.youtube_video_target("Xruhj0zOI7A", "abc"))
        token = streaming.create_stream_token("Xruhj0zOI7A:720", "bi-mat", source="youtube_video", now=1000)
        self.assertEqual(("youtube_video", "Xruhj0zOI7A:720"), streaming.verify_stream_token(token, "bi-mat", now=1100))
        for sai in ("Xruhj0zOI7A", "Xruhj0zOI7A:999", "../x:720"):
            with self.assertRaises(ValueError):
                streaming.create_stream_token(sai, "bi-mat", source="youtube_video")

    def test_yt_dlp_duoc_chi_duong_deno_canh_python(self) -> None:
        with TemporaryDirectory() as d:
            (Path(d) / "deno").write_text("", encoding="utf-8")
            with patch.object(streaming.sys, "executable", str(Path(d) / "python")):
                self.assertEqual(str(Path(d) / "deno"), streaming.deno_path())


class ApiLuongHinhTest(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import youtube_phat
        from services.youtube_phat import dich_vu

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        (Path(self._tmp.name) / "integration_token").write_text("token-thu", encoding="utf-8")
        self.core = dich_vu._reset_for_tests(Path(self._tmp.name))
        self.addCleanup(dich_vu._reset_for_tests)
        for p in (patch.object(dich_vu, "public_base_url_cau_hinh", return_value=""),
                  patch("api.youtube_phat.require_admin", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        app = FastAPI()
        app.include_router(youtube_phat.create_router())
        self.client = TestClient(app)

    @patch("api.youtube_phat.urlopen")
    @patch("services.youtube_phat.dich_vu.resolve_youtube_video")
    def test_tich_hop_ha_va_tab_lay_luong_hinh_roi_tiep_song(self, giai, mo) -> None:
        giai.return_value = {"url": GV.format(136), "headers": {}, "content_type": "video/mp4", "height": 720, "bitrate_kbps": 1002}
        d = self.client.post("/yt/api/integration/stream", headers={"Authorization": "Bearer token-thu"}, json={
            "source": "youtube_video", "target": "https://www.youtube.com/watch?v=Xruhj0zOI7A", "max_height": 720}).json()
        self.assertEqual(("video/mp4", 720, 1002, GV.format(136)), (d["media_content_type"], d["height"], d["bitrate_kbps"], d["direct_url"]))
        giai.assert_called_once_with("Xruhj0zOI7A:720")
        up = io.BytesIO(b"MP4!")
        up.headers = {"Content-Type": "video/mp4", "Content-Length": "4"}
        up.getcode = lambda: 200
        mo.return_value = up
        r = self.client.get("/yt/api/stream/" + d["stream_url"].rsplit("/", 1)[-1])
        self.assertEqual((200, b"MP4!", "video/mp4"), (r.status_code, r.content, r.headers["content-type"]))

        # Tab c2a: đường cùng nguồn với trang, kèm độ cao và tốc độ để ước lượng dữ liệu 4G.
        t = self.client.post("/api/youtube-phat/nghe", json={"source": "youtube_video", "target": "Xruhj0zOI7A", "max_height": 1080}).json()
        self.assertTrue(t["ok"], t)
        self.assertTrue(t["url"].startswith("/yt/api/stream/"))
        self.assertEqual((720, 1002, "video/mp4", GV.format(136)), (t["height"], t["bitrate_kbps"], t["content_type"], t["direct_url"]))
        self.assertEqual("Xruhj0zOI7A:1080", giai.call_args.args[0])
        # Tiếng vẫn như cũ: không kèm độ cao.
        self.assertNotIn("height", self.client.post("/yt/api/integration/stream", headers={"Authorization": "Bearer token-thu"},
                                                   json={"source": "spotify", "target": "x"}).json())
