"""Tab YouTube của web c2a: danh sách loa/tivi HA, sổ ẩn, phát và điều khiển.

Bảng khả năng và lệnh mở YouTube chuyển từ tích hợp HA của repo (playback.py,
actions.py); các ca dưới đây dựng theo đúng 10 media_player thật của nhà đo
14/09/2026 (LG webOS, Google Home cast speaker, FPT Box androidtv, R1 mất kết
nối, media player ảo của TriTue).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

LG = {"entity_id": "media_player.lg_webos_tv", "state": "on",
      "attributes": {"friendly_name": "Tivi LG", "device_class": "tv", "supported_features": 24381,
                     "volume_level": 0.2}}
GOOGLE_HOME = {"entity_id": "media_player.googlehome5802", "state": "idle",
               "attributes": {"friendly_name": "Google Home", "device_class": "speaker",
                              "supported_features": 152461, "volume_level": 0.5, "media_position": 42}}
FPT = {"entity_id": "media_player.fpt_play_box_s", "state": "idle",
       "attributes": {"friendly_name": "FPT Box", "supported_features": 131968}}
R1 = {"entity_id": "media_player.phicomm_r1_den", "state": "unavailable",
      "attributes": {"friendly_name": "R1 đen", "supported_features": 21565}}
KHONG_PHAT = {"entity_id": "media_player.phicomm", "state": "idle",
              "attributes": {"friendly_name": "Phicomm", "supported_features": 0}}
AO = {"entity_id": "media_player.tritue_youtube_player_172_16_10_200", "state": "idle",
      "attributes": {"friendly_name": "TriTue", "supported_features": 4329984}}
NEN_TANG = {LG["entity_id"]: "webostv", GOOGLE_HOME["entity_id"]: "cast", FPT["entity_id"]: "androidtv",
            R1["entity_id"]: "dlna_dmr", AO["entity_id"]: "tritue_youtube_player"}


class _CoSo(unittest.TestCase):
    def setUp(self) -> None:
        from services.youtube_phat import dich_vu, phat_ha

        self.dich_vu, self.phat_ha = dich_vu, phat_ha
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        (Path(self._tmp.name) / "integration_token").write_text("token-thu", encoding="utf-8")
        self.core = dich_vu._reset_for_tests(Path(self._tmp.name))
        self.addCleanup(dich_vu._reset_for_tests, Path(self._tmp.name))
        phat_ha._xoa_bo_dem()
        self.addCleanup(phat_ha._xoa_bo_dem)
        for dich, gia_tri in (("doc_media_player_tho", lambda: [LG, GOOGLE_HOME, FPT, R1, KHONG_PHAT, AO]),
                              ("get_ha_area_index", lambda use_cache=True: {"entity_platform": NEN_TANG})):
            p = patch.object(phat_ha.ha_client, dich, side_effect=gia_tri)
            p.start()
            self.addCleanup(p.stop)
        # Luồng tự chuyển bài chạy nền: test gọi thẳng `mot_vong`, không bật luồng thật.
        p = patch("services.youtube_phat.tu_chuyen_bai.dam_bao_chay")
        p.start()
        self.addCleanup(p.stop)
        self.cuoc_goi: list[tuple[str, str, dict]] = []
        self.ha_nhan = True

    def goi(self, domain, service, data):
        self.cuoc_goi.append((domain, service, data))
        return self.ha_nhan


class KhaNangVaLenhTest(_CoSo):
    def test_bang_kha_nang_theo_nen_tang(self) -> None:
        k = self.phat_ha.kha_nang
        self.assertEqual(("google_cast_audio", "am_thanh"), tuple(k("cast", "speaker", 152461)[x] for x in ("transport", "youtube")))
        self.assertEqual(("google_cast_video", "goc"), tuple(k("cast", "tv", 512)[x] for x in ("transport", "youtube")))
        self.assertEqual("goc", k("webostv", "tv", 512)["youtube"])
        self.assertEqual("goc", k("androidtv", None, 512)["youtube"])
        self.assertEqual(("dlna", "am_thanh"), tuple(k("dlna_dmr", None, 512)[x] for x in ("transport", "youtube")))
        self.assertFalse(k("esphome", "speaker", 0)["phat_duoc"])

    def test_lenh_mo_youtube_goc(self) -> None:
        video = {"kind": "video", "id": "dQw4w9WgXcQ", "playlist_id": "PL1234567890abc"}
        self.assertEqual(("webostv", "command", {"command": "system.launcher/launch",
                                                 "payload": {"id": "youtube.leanback.v4", "contentId": "dQw4w9WgXcQ"}}),
                         self.phat_ha.lenh_mo_youtube(video, "webostv", "tv"))
        _, _, cast = self.phat_ha.lenh_mo_youtube(video, "cast", "tv")
        self.assertEqual(('{"app_name":"youtube","media_id":"dQw4w9WgXcQ","playlist_id":"PL1234567890abc"}', "cast"),
                         (cast["media_content_id"], cast["media_content_type"]))
        _, _, atv = self.phat_ha.lenh_mo_youtube(video, "androidtv", "")
        self.assertEqual("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1234567890abc", atv["media_content_id"])
        with self.assertRaisesRegex(ValueError, "webos_playlist_requires_video"):
            self.phat_ha.lenh_mo_youtube({"kind": "playlist", "id": "PL1234567890abc"}, "webostv", "tv")

    def test_url_am_thanh_truc_tiep(self) -> None:
        y = self.phat_ha.yeu_cau_http
        self.assertEqual("audio/flac", y("https://nhac.lan/a.flac")["media_content_type"])
        self.assertEqual("application/vnd.apple.mpegurl", y("http://radio.lan/live.m3u8")["media_content_type"])
        for sai in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "http://u:p@nhac.lan/a.mp3", "ftp://nhac.lan/a.mp3"):
            with self.assertRaisesRegex(ValueError, "invalid_http_audio_target"):
                y(sai)
        with self.assertRaisesRegex(ValueError, "invalid_http_audio_target"):
            y("https://nhac.lan/a.mp3", "text/html")


class DanhSachVaSoAnTest(_CoSo):
    def test_danh_sach_bo_media_player_ao_va_gan_kha_nang(self) -> None:
        ds = {d["entity_id"]: d for d in self.phat_ha.danh_sach()}
        self.assertNotIn(AO["entity_id"], ds)
        self.assertEqual(("tivi", "lg_webos", "goc", 0.2), tuple(ds[LG["entity_id"]][x] for x in ("loai", "transport", "youtube", "am_luong")))
        self.assertEqual(("loa", "am_thanh", True), tuple(ds[GOOGLE_HOME["entity_id"]][x] for x in ("loai", "youtube", "chinh_am_luong")))
        self.assertFalse(ds[KHONG_PHAT["entity_id"]]["phat_duoc"])
        # Google Home thật (152461) không có bit SEEK; loa dừng thì vị trí giữ nguyên.
        self.assertEqual((False, 42.0), (ds[GOOGLE_HOME["entity_id"]]["tua"], ds[GOOGLE_HOME["entity_id"]]["vi_tri"]))
        self.assertIsNone(ds[LG["entity_id"]]["vi_tri"])

    def test_vi_tri_dang_phat_tinh_toi_luc_tra_loi(self) -> None:
        from datetime import datetime, timezone

        bay_gio = datetime(2026, 9, 14, 8, 0, 10, tzinfo=timezone.utc)
        a = {"media_position": 100, "media_position_updated_at": "2026-09-14T08:00:00+00:00"}
        self.assertEqual(110.0, self.phat_ha.vi_tri_phat("playing", a, bay_gio))
        self.assertEqual(100.0, self.phat_ha.vi_tri_phat("paused", a, bay_gio))
        self.assertEqual(100.0, self.phat_ha.vi_tri_phat("playing", {"media_position": 100}, bay_gio))
        self.assertIsNone(self.phat_ha.vi_tri_phat("playing", {"media_position": True}, bay_gio))

    def test_an_song_qua_khoi_dong_lai_va_khoi_phuc_duoc(self) -> None:
        self.phat_ha.dat_an([R1["entity_id"], KHONG_PHAT["entity_id"]], True)
        self.dich_vu._reset_for_tests(Path(self._tmp.name))  # như container khởi động lại
        ds = self.phat_ha.danh_sach(dung_bo_dem=False)
        self.assertEqual([False, False, False, True, True], [d["an"] for d in ds])
        self.assertEqual({R1["entity_id"], KHONG_PHAT["entity_id"]}, {d["entity_id"] for d in ds if d["an"]})
        self.assertEqual([KHONG_PHAT["entity_id"]], self.phat_ha.dat_an([R1["entity_id"]], False))
        with self.assertRaisesRegex(ValueError, "invalid_target_entity"):
            self.phat_ha.dat_an(["light.bep"], True)


class PhatTest(_CoSo):
    def _luong(self, nguon, ma):
        return ("dQw4w9WgXcQ" if nguon == "youtube" else ma), {"content_type": "audio/mp4"}

    def test_youtube_tivi_mo_ung_dung_loa_nhan_luong_may_bo_qua(self) -> None:
        with patch.object(self.core, "prepare_stream", side_effect=self._luong) as chuan_bi:
            kq = self.phat_ha.phat("youtube", "https://youtu.be/dQw4w9WgXcQ",
                                   [LG["entity_id"], GOOGLE_HOME["entity_id"], R1["entity_id"], KHONG_PHAT["entity_id"]],
                                   "http://172.16.10.38:3030/yt", goi=self.goi)
        chuan_bi.assert_called_once_with("youtube", "dQw4w9WgXcQ")
        self.assertEqual([LG["entity_id"], GOOGLE_HOME["entity_id"]], kq["da_gui"])
        self.assertEqual({R1["entity_id"]: "khong_truc_tuyen", KHONG_PHAT["entity_id"]: "khong_nhan_play_media"},
                         {b["entity_id"]: b["ly_do"] for b in kq["bo_qua"]})
        (d1, s1, lg), (d2, s2, gh) = self.cuoc_goi
        self.assertEqual(("webostv", "command", LG["entity_id"]), (d1, s1, lg["entity_id"]))
        self.assertEqual(("media_player", "play_media", "audio/mp4"), (d2, s2, gh["media_content_type"]))
        self.assertTrue(gh["media_content_id"].startswith("http://172.16.10.38:3030/yt/api/stream/"))
        self.assertEqual([LG["entity_id"], GOOGLE_HOME["entity_id"]], kq["phien"]["output_entity_ids"])
        self.assertEqual("dQw4w9WgXcQ", self.core.load_history()[0]["id"])

    def test_zing_chua_tim_thi_khong_goi_ha(self) -> None:
        with self.assertRaisesRegex(ValueError, "unverified_zing_target"):
            self.phat_ha.phat("zing", "https://zingmp3.vn/bai-hat/Bai/ZWZB9WAB.html",
                              [GOOGLE_HOME["entity_id"]], "http://x/yt", goi=self.goi)
        self.assertEqual([], self.cuoc_goi)

    def test_ha_tu_choi_het_thi_bao_loi_va_khong_ghi_phien(self) -> None:
        self.ha_nhan = False
        with self.assertRaisesRegex(ValueError, "ha_tu_choi"):
            self.phat_ha.phat("http", "https://nhac.lan/a.mp3", [GOOGLE_HOME["entity_id"], FPT["entity_id"]],
                              "http://x/yt", goi=self.goi)
        self.assertEqual(2, len(self.cuoc_goi))
        self.assertEqual("idle", self.core.get_session()["state"])

    def test_chon_sai_hoac_qua_16_thiet_bi(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_target_entity"):
            self.phat_ha.phat("http", "https://nhac.lan/a.mp3", ["light.bep"], "http://x/yt", goi=self.goi)
        with self.assertRaisesRegex(ValueError, "invalid_target_entities"):
            self.phat_ha.phat("http", "https://nhac.lan/a.mp3", [f"media_player.loa_{i}" for i in range(17)],
                              "http://x/yt", goi=self.goi)
        with self.assertRaisesRegex(ValueError, "khong_co_thiet_bi_phat_duoc"):
            self.phat_ha.phat("http", "https://nhac.lan/a.mp3", [R1["entity_id"]], "http://x/yt", goi=self.goi)

    def test_dieu_khien_am_luong_va_dung(self) -> None:
        self.assertEqual([GOOGLE_HOME["entity_id"]],
                         self.phat_ha.dieu_khien("am_luong", [GOOGLE_HOME["entity_id"]], 0.35, goi=self.goi))
        self.assertEqual(("media_player", "volume_set", {"volume_level": 0.35, "entity_id": GOOGLE_HOME["entity_id"]}),
                         self.cuoc_goi[-1])
        for sai in (1.5, True, "0.3", None):
            with self.assertRaisesRegex(ValueError, "invalid_volume_level"):
                self.phat_ha.dieu_khien("am_luong", [GOOGLE_HOME["entity_id"]], sai, goi=self.goi)
        # Dừng loa nào thì loa đó rời phiên; loa khác trong phiên vẫn phát.
        self.core.record_session("http", "https://nhac.lan/a.mp3", output_entity_ids=[LG["entity_id"], GOOGLE_HOME["entity_id"]])
        self.phat_ha.dieu_khien("dung", [LG["entity_id"]], goi=self.goi)
        self.assertEqual([[GOOGLE_HOME["entity_id"]]], [p["output_entity_ids"] for p in self.phat_ha.cac_phien()])
        with self.assertRaisesRegex(ValueError, "lenh_khong_ho_tro"):
            self.phat_ha.dieu_khien("tat_nguon", [LG["entity_id"]], goi=self.goi)
        # Loa nhập vào video đang xem trên trang thì tua tới chỗ video.
        self.phat_ha.dieu_khien("tua", [GOOGLE_HOME["entity_id"]], vi_tri=93, goi=self.goi)
        self.assertEqual(("media_player", "media_seek", {"seek_position": 93.0, "entity_id": GOOGLE_HOME["entity_id"]}),
                         self.cuoc_goi[-1])
        for sai in (-1, None, "10", True):
            with self.assertRaisesRegex(ValueError, "invalid_seek_position"):
                self.phat_ha.dieu_khien("tua", [GOOGLE_HOME["entity_id"]], vi_tri=sai, goi=self.goi)


class PhienTheoNhomLoaTest(_CoSo):
    """Mỗi loa một bài / nhiều loa chung bài, bài kế theo phiên, dừng, bỏ loa, tự chuyển bài."""

    def _luong(self, nguon, ma):
        return ma, {"content_type": "audio/mp4"}

    def setUp(self) -> None:
        super().setUp()
        ket_qua = [{"source": "youtube", "kind": "video", "id": i, "url": f"https://www.youtube.com/watch?v={i}",
                    "title": f"Bai {n}", "channel": "K", "duration": 200}
                   for n, i in enumerate(["dQw4w9WgXcQ", "M7lc1UVf-VE", "llPioQNSBLY"], 1)]
        with patch("services.youtube_phat.dich_vu.search_youtube", return_value=ket_qua):
            self.core.search("youtube", "x", 3)
        self.urls = [k["url"] for k in ket_qua]
        p = patch.object(self.core, "prepare_stream", side_effect=self._luong)
        p.start()
        self.addCleanup(p.stop)

    def test_moi_loa_mot_bai_chuyen_bai_dung_va_bo_loa(self) -> None:
        a, b = GOOGLE_HOME["entity_id"], FPT["entity_id"]
        self.phat_ha.phat("youtube", self.urls[0], [a], "http://x/yt", goi=self.goi)
        pb = self.phat_ha.phat("youtube", self.urls[1], [b], "http://x/yt", goi=self.goi)["phien"]
        phien = {tuple(p["output_entity_ids"]): p for p in self.phat_ha.cac_phien()}
        self.assertEqual({(a,): "Bai 1", (b,): "Bai 2"}, {k: v["item"]["title"] for k, v in phien.items()})
        self.assertEqual({"c2a"}, {p["controller"] for p in phien.values()})

        self.cuoc_goi.clear()
        self.phat_ha.chuyen_bai(pb["session_id"], 1, goi=self.goi)
        self.assertEqual([b], [d["entity_id"] for _, s, d in self.cuoc_goi if s == "play_media"])
        self.assertEqual("Bai 3", {tuple(p["output_entity_ids"]): p for p in self.phat_ha.cac_phien()}[(b,)]["item"]["title"])
        with self.assertRaisesRegex(ValueError, "het_hang_doi"):
            self.phat_ha.chuyen_bai(pb["session_id"], 1, goi=self.goi)

        # Chung một bài rồi bỏ một loa: loa kia vẫn trong phiên.
        chung = self.phat_ha.phat("youtube", self.urls[0], [a, b], "http://x/yt", goi=self.goi)["phien"]
        self.assertEqual([sorted([a, b])], [sorted(p["output_entity_ids"]) for p in self.phat_ha.cac_phien()])
        self.phat_ha.bo_loa([b], goi=self.goi)
        self.assertEqual([[a]], [p["output_entity_ids"] for p in self.phat_ha.cac_phien()])
        # Cho b nghe cùng: chỉ b nhận bài, a giữ trong phiên.
        self.cuoc_goi.clear()
        self.phat_ha.phat("youtube", self.urls[0], [b], "http://x/yt", session_id=chung["session_id"], join_ids=[a], goi=self.goi)
        self.assertEqual([b], [d["entity_id"] for _, s, d in self.cuoc_goi if s == "play_media"])
        self.assertEqual([sorted([a, b])], [sorted(p["output_entity_ids"]) for p in self.phat_ha.cac_phien()])
        self.cuoc_goi.clear()
        self.phat_ha.dung_phien(chung["session_id"], goi=self.goi)
        self.assertEqual([], self.phat_ha.cac_phien())
        # FPT Box mẫu (131968) không có bit STOP: chỉ loa dừng được mới nhận media_stop.
        self.assertEqual([a], [d["entity_id"] for _, s, d in self.cuoc_goi if s == "media_stop"])

    def test_tu_chuyen_bai_khi_loa_het_bai_khong_khi_dung_giua_bai(self) -> None:
        from services.youtube_phat import tu_chuyen_bai

        tu_chuyen_bai._theo_doi.clear()
        a = GOOGLE_HOME["entity_id"]
        phien = self.phat_ha.phat("youtube", self.urls[0], [a], "http://x/yt", goi=self.goi)["phien"]
        trang_thai = {"trang_thai": "playing", "vi_tri": 190.0, "thoi_luong": 200.0}

        with patch.object(self.phat_ha, "danh_sach", side_effect=lambda dung_bo_dem=True: [
                {"entity_id": a, "youtube": "am_thanh", **trang_thai}]), \
             patch.object(self.phat_ha, "chuyen_bai") as chuyen:
            self.assertEqual([], tu_chuyen_bai.mot_vong(100.0))
            trang_thai.update(trang_thai="idle")
            self.assertEqual([phien["session_id"]], tu_chuyen_bai.mot_vong(105.0))
            chuyen.assert_called_once_with(phien["session_id"], 1)
            # Dừng tay giữa bài: không chuyển.
            chuyen.reset_mock()
            tu_chuyen_bai._theo_doi.clear()
            trang_thai.update(trang_thai="playing", vi_tri=40.0)
            tu_chuyen_bai.mot_vong(200.0)
            trang_thai.update(trang_thai="idle")
            self.assertEqual([], tu_chuyen_bai.mot_vong(203.0))
            chuyen.assert_not_called()

    def test_tivi_mo_youtube_goc_khong_lam_loa_dan(self) -> None:
        from services.youtube_phat import tu_chuyen_bai

        tu_chuyen_bai._theo_doi.clear()
        phien = self.phat_ha.phat("youtube", self.urls[0], [LG["entity_id"]], "http://x/yt", goi=self.goi)["phien"]
        with patch.object(self.phat_ha, "danh_sach", return_value=[
                {"entity_id": LG["entity_id"], "youtube": "goc", "trang_thai": "idle", "vi_tri": None, "thoi_luong": None}]), \
             patch.object(self.phat_ha, "chuyen_bai") as chuyen:
            tu_chuyen_bai.mot_vong(1.0)
            tu_chuyen_bai.mot_vong(2.0)
        chuyen.assert_not_called()
        self.assertTrue(phien["session_id"])


class ApiTabTest(_CoSo):
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

    def test_dia_chi_lan_luu_lai_va_thang_dia_chi_trinh_duyet(self) -> None:
        h = {"host": "gpt.vi-du.vn", "x-forwarded-proto": "https"}
        self.assertEqual("https://gpt.vi-du.vn/yt", self.client.get("/api/youtube-phat/ket-noi", headers=h).json()["url"])
        r = self.client.post("/api/youtube-phat/ket-noi", json={"url_lan": "http://172.16.10.38:3030/"}, headers=h).json()
        self.assertEqual(("http://172.16.10.38:3030/yt", "http://172.16.10.38:3030", "token-thu"),
                         (r["url"], r["url_lan"], r["token"]))
        self.assertEqual("http://172.16.10.38:3030/yt", self.dich_vu.public_base_url_cau_hinh())
        for sai in ("172.16.10.38:3030", "http://172.16.10.38:3030/yt", "http://u:p@172.16.10.38", "http://h:99999"):
            d = self.client.post("/api/youtube-phat/ket-noi", json={"url_lan": sai}).json()
            self.assertEqual((False, "url_lan_khong_hop_le"), (d["ok"], d["ma"]), sai)
        self.client.post("/api/youtube-phat/ket-noi", json={"url_lan": ""})
        self.assertEqual("", self.dich_vu.public_base_url_cau_hinh())

    def test_thiet_bi_va_loi_ha_bao_bang_loi_de_hieu(self) -> None:
        d = self.client.get("/api/youtube-phat/thiet-bi").json()
        self.assertEqual((True, 5, "idle"), (d["ok"], len(d["items"]), d["phien"]["state"]))
        with patch.object(self.phat_ha.ha_client, "doc_media_player_tho", side_effect=OSError("timed out")):
            self.phat_ha._xoa_bo_dem()
            d = self.client.get("/api/youtube-phat/thiet-bi").json()
        self.assertEqual((False, "ha_khong_doc_duoc"), (d["ok"], d["ma"]))
        self.assertIn("Home Assistant", d["error"])

    def test_phat_bao_luong_hong_va_an_khoi_phuc(self) -> None:
        from services.youtube_phat.streaming import StreamUnavailableError

        with patch.object(self.core, "prepare_stream", side_effect=StreamUnavailableError("x")):
            d = self.client.post("/api/youtube-phat/phat", json={
                "source": "youtube", "target": "dQw4w9WgXcQ", "entity_ids": [GOOGLE_HOME["entity_id"]]}).json()
        self.assertEqual((False, "stream_unavailable"), (d["ok"], d["ma"]))
        self.assertEqual([FPT["entity_id"]], self.client.post(
            "/api/youtube-phat/an", json={"entity_ids": [FPT["entity_id"]], "an": True}).json()["an"])
        self.assertEqual([], self.client.post(
            "/api/youtube-phat/an", json={"entity_ids": [FPT["entity_id"]], "an": False}).json()["an"])

    def test_tim_tra_loi_de_hieu_khi_nguon_hong(self) -> None:
        from services.youtube_phat.search import SearchUnavailableError

        with patch("services.youtube_phat.dich_vu.search_youtube", side_effect=SearchUnavailableError("x")):
            d = self.client.get("/api/youtube-phat/tim", params={"q": "trót tin vào lời hứa"}).json()
        self.assertEqual((False, "search_unavailable"), (d["ok"], d["ma"]))
        d = self.client.get("/api/youtube-phat/tim", params={"q": ""}).json()
        self.assertEqual("invalid_search_query", d["ma"])


if __name__ == "__main__":
    unittest.main()
