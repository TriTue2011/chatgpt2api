"""Playlist chung cả nhà cho tab YouTube c2a và tích hợp HA.

Chủ máy 14/09/2026: "thêm các bài hát yêu thích vào playlist để nghe hoặc nghe playlist
của người khác chia sẻ. Có thể tạo nhiều playlist khác nhau", "có cách nào lưu luôn
playlist này lại, không phải lưu tay từng bài mà lưu toàn bộ qua link luôn".
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from test.test_youtube_phat_tab import GOOGLE_HOME, _CoSo

YT = [{"source": "youtube", "kind": "video", "id": i, "url": f"https://www.youtube.com/watch?v={i}", "title": f"Bài {n}",
       "channel": "Kênh", "duration": 200, "thumbnail": f"https://i.ytimg.com/vi/{i}/hqdefault.jpg"}
      for n, i in enumerate(["dQw4w9WgXcQ", "M7lc1UVf-VE", "llPioQNSBLY"], 1)]
ZING = {"source": "zing", "kind": "song", "id": "USJgi8Pq9Ouf", "title": "Âm Thầm Bên Em", "channel": "Sơn Tùng M-TP",
        "url": "https://zingmp3.vn/bai-hat/Am-Tham-Ben-Em-Son-Tung-M-TP/USJgi8Pq9Ouf.html", "duration": 291, "thumbnail": ""}


class KhoPlaylistTest(TestCase):
    def setUp(self) -> None:
        from services.youtube_phat import playlists

        self.pl = playlists
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.duong = Path(self._tmp.name) / "playlists.json"
        self.kho = playlists.PlaylistStore(self.duong)

    def test_tao_them_bo_trung_xoa_doi_cho_doi_ten_va_luu_tep(self) -> None:
        p = self.kho.create("Nhạc buổi sáng", [YT[0], {"source": "youtube", "id": "sai"}, YT[0]])
        self.assertEqual(1, len(p["items"]))
        p, them = self.kho.add(p["id"], [YT[0], YT[1], ZING, {"source": "spotify", "id": "x"}])
        self.assertEqual((2, ["dQw4w9WgXcQ", "M7lc1UVf-VE", "USJgi8Pq9Ouf"]), (them, [i["id"] for i in p["items"]]))
        p = self.kho.move(p["id"], 2, 0)
        p = self.kho.remove(p["id"], 1)
        self.assertEqual(["USJgi8Pq9Ouf", "M7lc1UVf-VE"], [i["id"] for i in p["items"]])
        self.kho.rename(p["id"], "Sáng thứ hai")
        # Đọc lại từ tệp bằng kho mới: y như cũ.
        lai = self.pl.PlaylistStore(self.duong).get(p["id"])
        self.assertEqual(("Sáng thứ hai", ["USJgi8Pq9Ouf", "M7lc1UVf-VE"]), (lai["name"], [i["id"] for i in lai["items"]]))
        self.assertTrue(self.kho.contains("zing", ZING["url"]))
        self.kho.delete(p["id"])
        self.assertEqual([], self.kho.list())
        with self.assertRaisesRegex(ValueError, "playlist_not_found"):
            self.kho.get(p["id"])
        with self.assertRaisesRegex(ValueError, "playlist_name_required"):
            self.kho.create("   ")

    def test_ma_chia_se_di_tron_va_ma_hong_bi_tu_choi(self) -> None:
        p = self.kho.create("Chia sẻ", [*YT, ZING])
        ma = self.pl.share_code(p)
        self.assertTrue(ma.startswith("TTPL1."))
        ten, items = self.pl.read_share_code(ma)
        self.assertEqual(("Chia sẻ", [i["id"] for i in p["items"]]), (ten, [i["id"] for i in items]))
        for hong in ("TTPL1.abc", ma[:-10], "khong-phai-ma", "TTPL1." + "A" * 400_000):
            with self.assertRaisesRegex(ValueError, "invalid_share_code"):
                self.pl.read_share_code(hong)


class LenhPlaylistTest(_CoSo):
    def _lenh(self, **payload):
        return self.core.playlist_action(payload)

    def test_luu_ca_playlist_youtube_qua_link(self) -> None:
        tra = {"title": "Nhạc 8x 9x", "entries": [{"id": i["id"], "title": i["title"], "channel": "K", "duration": 200} for i in YT]}
        with patch("services.youtube_phat.search.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout=json.dumps(tra))) as chay:
            kq = self._lenh(action="import", text="https://www.youtube.com/playlist?list=PLlcU_sdTFmvhMC__SD90WlDTTLk0fPs_D")
        lenh = chay.call_args.args[0]
        self.assertIn("https://www.youtube.com/playlist?list=PLlcU_sdTFmvhMC__SD90WlDTTLk0fPs_D", lenh)
        self.assertEqual("500", lenh[lenh.index("--playlist-end") + 1])       # cả playlist, không chỉ 20 kết quả tìm
        self.assertEqual(("Nhạc 8x 9x", 3), (kq["playlist"]["name"], len(kq["playlist"]["items"])))
        # Link xem một bài nằm trong playlist cũng lưu được cả playlist.
        with patch("services.youtube_phat.search.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout=json.dumps(tra))):
            kq = self._lenh(action="import", text="https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLlcU_sdTFmvhMC__SD90WlDTTLk0fPs_D",
                            name="Đặt tên riêng")
        self.assertEqual("Đặt tên riêng", kq["playlist"]["name"])
        self.assertEqual(2, len(kq["playlists"]))

    def test_luu_album_zing_va_ma_chia_se_va_link_sai(self) -> None:
        with patch("services.youtube_phat.dich_vu.fetch_zing_playlist", return_value=("Sơn Tùng hay nhất", [ZING])) as lay, \
             patch.object(self.core, "zing_keys", return_value={"api_key": "k", "api_secret": "s"}):
            kq = self._lenh(action="import", text="https://zingmp3.vn/album/Nhung-Bai-Hat-Hay-Nhat-Cua-Son-Tung-M-TP/n1mqFnz65jGl.html")
        self.assertEqual({"api_key": "k", "api_secret": "s"}, lay.call_args.kwargs)
        pid = kq["playlist"]["id"]
        ma = self._lenh(action="export", id=pid)["code"]
        kq = self._lenh(action="import", text=ma)
        self.assertEqual(("Sơn Tùng hay nhất", ["USJgi8Pq9Ouf"]), (kq["playlist"]["name"], [i["id"] for i in kq["playlist"]["items"]]))
        for sai in ("https://example.com/list", "sơn tùng"):
            with self.assertRaisesRegex(ValueError, "invalid_playlist_link"):
                self._lenh(action="import", text=sai)

    def test_them_bai_tao_moi_neu_chua_co_playlist(self) -> None:
        kq = self._lenh(action="add", name="Yêu thích", items=[YT[0]])
        self.assertEqual((1, "Yêu thích"), (kq["added"], kq["playlist"]["name"]))
        kq = self._lenh(action="add", id=kq["playlist"]["id"], items=[YT[0], YT[1]])
        self.assertEqual((1, 2), (kq["added"], len(kq["playlist"]["items"])))

    def test_phat_playlist_ra_loa_hang_doi_la_ca_playlist_va_zing_da_luu_van_phat(self) -> None:
        pid = self._lenh(action="create", name="Hỗn hợp", items=[YT[0], ZING, YT[2]])["playlist"]["id"]
        goi = []
        with patch.object(self.core, "prepare_stream", side_effect=lambda nguon, ma: (ma if nguon == "zing" else ma[-11:], {"content_type": "audio/mp4"})):
            kq = self.phat_ha.phat("zing", ZING["url"], [GOOGLE_HOME["entity_id"]], "http://x/yt", playlist_id=pid,
                                   goi=lambda d, s, data: goi.append(s) or True)
            hang = kq["phien"]["queue"]
            self.assertEqual((1, ["dQw4w9WgXcQ", "USJgi8Pq9Ouf", "llPioQNSBLY"]), (hang["index"], [i["id"] for i in hang["items"]]))
            # Bài Zing đã lưu trong playlist không cần vừa tìm lại mới phát được.
            self.assertEqual(ZING["url"], self.core.require_public_zing_result(ZING["url"]))
            kq = self.phat_ha.chuyen_bai(kq["phien"]["session_id"], 1, goi=lambda d, s, data: True)
            self.assertEqual("llPioQNSBLY", kq["phien"]["item"]["id"])


class ApiPlaylistTest(_CoSo):
    def setUp(self) -> None:
        super().setUp()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import youtube_phat

        p = patch("api.youtube_phat.require_admin", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        app = FastAPI()
        app.include_router(youtube_phat.create_router())
        self.client = TestClient(app)

    def test_tab_va_tich_hop_ha_dung_chung_mot_kho(self) -> None:
        d = self.client.post("/api/youtube-phat/playlist", json={"action": "create", "name": "Nhà", "items": YT[:2]}).json()
        self.assertTrue(d["ok"], d)
        H = {"Authorization": "Bearer token-thu"}
        d2 = self.client.get("/yt/api/integration/playlists", headers=H).json()
        self.assertEqual(["Nhà"], [p["name"] for p in d2["playlists"]])
        self.assertEqual(401, self.client.get("/yt/api/integration/playlists").status_code)
        loi = self.client.post("/api/youtube-phat/playlist", json={"action": "import", "text": "abc"}).json()
        self.assertEqual((False, "invalid_playlist_link"), (loi["ok"], loi["ma"]))
        self.assertIn("mã chia sẻ", loi["error"])
        # Album Zing không tồn tại / playlist riêng tư: báo đúng là không đọc được playlist.
        from services.youtube_phat.streaming import StreamUnavailableError

        with patch("services.youtube_phat.dich_vu.fetch_zing_playlist", side_effect=StreamUnavailableError("stream_provider_failed")), \
             patch.object(self.core, "zing_keys", return_value={"api_key": "k", "api_secret": "s"}):
            loi = self.client.post("/api/youtube-phat/playlist", json={"action": "import", "text": "https://zingmp3.vn/album/X/ZWZB9WAB.html"}).json()
        self.assertEqual((False, "playlist_unavailable"), (loi["ok"], loi["ma"]))
        r = self.client.post("/yt/api/integration/session", headers=H, json={
            "source": "youtube", "target": YT[1]["url"], "output_entity_ids": [GOOGLE_HOME["entity_id"]],
            "playlist_id": d["playlist"]["id"]})
        self.assertEqual((200, 1, 2), (r.status_code, r.json()["session"]["queue"]["index"], len(r.json()["session"]["queue"]["items"])))
