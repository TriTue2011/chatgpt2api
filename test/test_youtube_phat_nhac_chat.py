"""Mở nhạc qua kênh chat: 10 bài → chọn loa (một, nhiều, tất cả) → phát; điều khiển.

Chủ máy 14/09/2026: "Khi mở nhạc cần hiện list danh sách 10 bài nhạc để lựa chọn,
sau đó là list loa phát, phát 1 hoặc nhiều loa hoặc tất cả". Loa dựng theo đúng
media_player thật của nhà (xem test_youtube_phat_tab).
"""

from __future__ import annotations

from unittest.mock import patch

from services.agent import ask_choices
from test.test_youtube_phat_tab import FPT, GOOGLE_HOME, LG, _CoSo

IDS = ["dQw4w9WgXcQ", "M7lc1UVf-VE", "llPioQNSBLY", "9bZkp7q19f0", "kJQP7kiw5Fk", "JGwWNGJdvx8",
       "RgKAFK5djSk", "OPf0YbXqDm0", "fRh_vgS2dFE", "hT_nvWreIhg", "CevxZvSJLk8", "YQHsXMglC9A"]


class NhacChatTest(_CoSo):
    def setUp(self) -> None:
        super().setUp()
        from services.youtube_phat import nhac_chat

        self.nc = nhac_chat
        self.ket_qua = [{"source": "youtube", "kind": "video", "id": i, "url": f"https://www.youtube.com/watch?v={i}",
                         "title": f"Bài | số «{n}»", "channel": "Kênh", "duration": 185}
                        for n, i in enumerate(IDS, 1)]
        for dich, gia_tri in (
                ("search_youtube", lambda q, limit=20: self.ket_qua[:limit]),):
            p = patch.object(self.dich_vu, dich, side_effect=gia_tri)
            p.start()
            self.addCleanup(p.stop)
        for p in (patch.object(self.core, "prepare_stream", side_effect=lambda nguon, ma: (ma, {"content_type": "audio/mp4"})),
                  patch.object(self.phat_ha.ha_client, "call_service", side_effect=self.goi),
                  patch.object(self.phat_ha, "url_goc_nen", return_value="https://gpt.example/yt")):
            p.start()
            self.addCleanup(p.stop)

    def _menu(self, ra: dict) -> tuple[str, list[dict[str, str]]]:
        self.assertTrue(ra.get("deliver_now"), ra)
        return ask_choices.extract(ra["text"])

    def _bam(self, lua_chon: dict[str, str], cho_phep=None) -> dict:
        args = self.nc.doc_nut(lua_chon["send"])
        self.assertIsNotNone(args, lua_chon)
        return self.nc.mo_nhac(args, cho_phep)

    def test_muoi_bai_roi_danh_sach_loa_roi_phat_tat_ca(self) -> None:
        _, bai = self._menu(self.nc.mo_nhac({"tu_khoa": "sơn tùng"}, None))
        self.assertEqual(10, len(bai))
        self.assertTrue(bai[0]["label"].startswith("Bài / số \"1\" (Kênh · 3:05)"), bai[0])
        self.assertEqual({"nguon": "youtube", "bai": self.ket_qua[1]["url"]}, self.nc.doc_nut(bai[1]["send"]))

        _, loa = self._menu(self._bam(bai[1]))
        # Chỉ loa trực tuyến, nhận phát nhạc, không phải media player ảo; «Tất cả» ở cuối.
        self.assertEqual(["FPT Box", "Google Home", "Tivi LG", "Tất cả loa"], [c["label"] for c in loa])

        ra = self._bam(loa[-1])
        self.assertIn("Bài | số «2»", ra["text"])
        phien = self.phat_ha.cac_phien()
        self.assertEqual([sorted([FPT["entity_id"], GOOGLE_HOME["entity_id"], LG["entity_id"]])],
                         [sorted(p["output_entity_ids"]) for p in phien])
        # Hàng đợi là 10 bài vừa tìm: bài kế chạy được qua chat.
        self.assertEqual(1, phien[0]["queue"]["index"])

    def test_go_nhieu_loa_theo_ten_va_so_thu_tu(self) -> None:
        url = self.ket_qua[0]["url"]
        ra = self.nc.mo_nhac({"bai": url, "loa": "google home và 3"}, None)
        self.assertIn("Google Home, Tivi LG", ra["text"])
        self.assertEqual([sorted([GOOGLE_HOME["entity_id"], LG["entity_id"]])],
                         [sorted(p["output_entity_ids"]) for p in self.phat_ha.cac_phien()])

    def test_loa_khong_nhan_ra_thi_hien_lai_danh_sach_khong_phat(self) -> None:
        text, loa = self._menu(self.nc.mo_nhac({"bai": self.ket_qua[0]["url"], "loa": "loa bếp"}, None))
        self.assertIn("không nhận ra loa trong «loa bếp»", text)
        self.assertEqual(4, len(loa))
        self.assertEqual([], self.cuoc_goi)

    def test_neu_loa_ngay_tu_dau_thi_nut_bai_phat_luon(self) -> None:
        _, bai = self._menu(self.nc.mo_nhac({"tu_khoa": "lofi", "loa": "google home"}, None))
        self.assertEqual({"nguon": "youtube", "bai": self.ket_qua[0]["url"], "loa": "google home"},
                         self.nc.doc_nut(bai[0]["send"]))
        self.assertIn("Google Home", self._bam(bai[0])["text"])

    def test_dan_link_video_bo_qua_buoc_tim(self) -> None:
        with patch.object(self.dich_vu, "search_youtube") as tim:
            _, loa = self._menu(self.nc.mo_nhac({"tu_khoa": "https://youtu.be/dQw4w9WgXcQ"}, None))
        tim.assert_not_called()
        self.assertEqual("https://youtu.be/dQw4w9WgXcQ", self.nc.doc_nut(loa[0]["send"])["bai"])

    def test_khung_chat_bi_gioi_han_loa(self) -> None:
        cho_phep = {GOOGLE_HOME["entity_id"]}
        _, loa = self._menu(self.nc.mo_nhac({"bai": self.ket_qua[0]["url"]}, cho_phep))
        self.assertEqual(["Google Home"], [c["label"] for c in loa])       # một loa: không có «Tất cả»
        self._bam({"send": f"phát nhạc youtube «{self.ket_qua[0]['url']}» ra loa «tất cả»"}, cho_phep)
        self.assertEqual([[GOOGLE_HOME["entity_id"]]], [p["output_entity_ids"] for p in self.phat_ha.cac_phien()])

    def test_loi_phat_thanh_cau_tieng_viet(self) -> None:
        self.ha_nhan = False
        ra = self.nc.mo_nhac({"bai": self.ket_qua[0]["url"], "loa": "google home"}, None)
        self.assertIn("Home Assistant không nhận lệnh", ra["text"])

    def test_dang_phat_va_dieu_khien_moi_loa_mot_bai(self) -> None:
        gh, lg = GOOGLE_HOME["entity_id"], LG["entity_id"]
        self.dich_vu.core().search("youtube", "x", 10)
        self.nc.mo_nhac({"bai": self.ket_qua[0]["url"], "loa": "google home"}, None)
        self.nc.mo_nhac({"bai": self.ket_qua[4]["url"], "loa": "tivi lg"}, None)

        dang = self.nc.dang_phat(None)["text"]
        self.assertIn("Google Home: «Bài | số «1»»", dang)
        self.assertIn("Tivi LG: «Bài | số «5»»", dang)

        # Hai nhóm mà không nêu loa: chuyển bài phải hỏi, không đoán.
        self.cuoc_goi.clear()
        self.assertIn("cho loa nào", self.nc.dieu_khien({"lenh": "bai_ke"}, None)["text"])
        self.assertEqual([], self.cuoc_goi)
        ra = self.nc.dieu_khien({"lenh": "bai_ke", "loa": "google home"}, None)
        self.assertIn("«Bài | số «2»» trên Google Home", ra["text"])
        self.assertEqual([gh], [d["entity_id"] for _, s, d in self.cuoc_goi if s == "play_media"])

        self.cuoc_goi.clear()
        self.nc.dieu_khien({"lenh": "tam_dung"}, None)
        self.assertEqual({gh, lg}, {d["entity_id"] for _, s, d in self.cuoc_goi if s == "media_pause"})

        self.nc.dieu_khien({"lenh": "dung", "loa": "tivi lg"}, None)
        self.assertEqual([[gh]], [p["output_entity_ids"] for p in self.phat_ha.cac_phien()])
        self.nc.dieu_khien({"lenh": "dung"}, None)
        self.assertEqual([], self.phat_ha.cac_phien())
        self.assertIn("không loa nào", self.nc.dieu_khien({"lenh": "tiep_tuc"}, None)["text"])


class DauNoiBotTest(_CoSo):
    def test_capability_nhom_quyen_va_hoi_du_truoc_khi_duyet(self) -> None:
        from services.agent import capabilities as caps

        for ten in ("mo_nhac", "dieu_khien_nhac", "nhac_dang_phat"):
            self.assertIsNotNone(caps.get(ten), ten)
            self.assertEqual("tts_speaker", caps.group_of(ten))
        self.assertTrue(caps.con_thieu_thong_tin("mo_nhac", {"tu_khoa": "lofi"}))
        self.assertTrue(caps.con_thieu_thong_tin("mo_nhac", {"bai": "https://youtu.be/dQw4w9WgXcQ"}))
        self.assertFalse(caps.con_thieu_thong_tin("mo_nhac", {"bai": "https://youtu.be/dQw4w9WgXcQ", "loa": "bếp"}))

    def test_menu_giu_du_muoi_lua_chon(self) -> None:
        khoi = "\n".join(["Chọn:", "<<<ASK>>>", *[f"Bài {i} | chọn {i}" for i in range(1, 13)], "<<<END>>>"])
        self.assertEqual(10, len(ask_choices.extract(khoi)[1]))

    def test_nut_la_cau_nguoi_go_thuong_khong_bi_bat(self) -> None:
        from services.youtube_phat import nhac_chat

        for cau in ("mở nhạc sơn tùng", "phát nhạc ra loa phòng khách", "mở nhạc youtube chọn loa"):
            self.assertIsNone(nhac_chat.doc_nut(cau), cau)

    def test_bam_nut_chay_thang_mo_nhac_khong_qua_model(self) -> None:
        import services.agent.orchestrator as orch

        menu = {"text": "🔊 Phát ra loa nào ạ?\n<<<ASK>>>\nGoogle Home | phát nhạc youtube «u» ra loa «Google Home»\n<<<END>>>",
                "deliver_now": True}
        with patch.object(orch, "call_model", side_effect=AssertionError("không được gọi model")), \
             patch.object(orch, "_execute", return_value=menu) as chay, \
             patch.object(orch, "_persist_history"), \
             patch.object(orch.run_journal, "log_run"):
            ra = orch.orchestrate("mở nhạc youtube «https://www.youtube.com/watch?v=dQw4w9WgXcQ» chọn loa",
                                  "test_nut_nhac", model="gma/auto:text", allow={"tts_speaker"})
        cap, args = chay.call_args.args[:2]
        self.assertEqual("mo_nhac", cap.name)
        self.assertEqual({"nguon": "youtube", "bai": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}, args)
        self.assertEqual(["Google Home"], [c["label"] for c in ra.get("choices") or []])
