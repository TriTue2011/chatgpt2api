"""Dừng loa theo LUỒNG của c2a, không chỉ theo phiên c2a còn nhớ.

Chủ máy 06/10/2026: dừng/gỡ add-on giữa bài thì loa phát tiếp, TTS chen vào là nhạc tự phát lại (đã tái hiện trên loa
camera thật với tích hợp HA 0.27.8). c2a cùng lỗi: khởi động lại để lên bản mới là quên phiên, «dừng nhạc» không thấy
gì để dừng. Loa vẫn báo `media_content_id` là URL luồng có chữ ký của c2a — dò theo đó thì không sót loa nào.
"""

from __future__ import annotations

from unittest.mock import patch

from test.test_youtube_phat_tab import FPT, GOOGLE_HOME, LG, _CoSo


def _luong(secret: str = "token-thu", ttl: int = 300, now: int | None = None) -> str:
    from services.youtube_phat.streaming import build_signed_stream_url

    return build_signed_stream_url("https://gpt.example/yt", "dQw4w9WgXcQ", secret, source="youtube", ttl=ttl, now=now)


def _loa(goc: dict, state: str, content: str, features: int | None = None) -> dict:
    a = {**goc["attributes"], "media_content_id": content}
    if features is not None:
        a["supported_features"] = features
    return {**goc, "state": state, "attributes": a}


CAM = {"entity_id": "media_player.loa_cam_bep", "state": "playing",
       "attributes": {"friendly_name": "Loa cam bếp", "supported_features": 256 | 1}}
CHI_PAUSE = {"entity_id": "media_player.chi_pause", "state": "playing",
             "attributes": {"friendly_name": "Chỉ pause", "supported_features": 1}}


class ChuKyLuongTest(_CoSo):
    def test_chi_nhan_luong_ky_bang_khoa_minh_ke_ca_da_het_han(self) -> None:
        from services.youtube_phat.streaming import luong_ky_boi

        self.assertTrue(luong_ky_boi(_luong(), "token-thu"))
        # Bài phát từ trước khi c2a khởi động lại: token đã hết hạn nhưng loa vẫn đang phát luồng đó.
        self.assertTrue(luong_ky_boi(_luong(ttl=30, now=1_000), "token-thu"))
        self.assertFalse(luong_ky_boi(_luong(secret="khoa-nguoi-khac"), "token-thu"))
        for sai in ("", None, "https://nhac.lan/a.mp3", "media-source://tts/abc", "/api/stream/abc"):
            self.assertFalse(luong_ky_boi(sai, "token-thu"), sai)
        self.assertFalse(luong_ky_boi(_luong(), ""))


class DungLoaLuongTest(_CoSo):
    def _dat_loa(self, *loa: dict) -> None:
        p = patch.object(self.phat_ha.ha_client, "doc_media_player_tho", side_effect=lambda: list(loa))
        p.start()
        self.addCleanup(p.stop)
        self.phat_ha._xoa_bo_dem()

    def test_dung_moi_loa_phat_luong_minh_bo_qua_noi_dung_khac(self) -> None:
        self._dat_loa(_loa(GOOGLE_HOME, "playing", _luong()),
                      _loa(LG, "paused", _luong()),                         # TTS chen → tạm dừng, vẫn phải dừng
                      _loa(FPT, "playing", "https://nhac.lan/a.mp3"),        # nguồn khác: không đụng
                      _loa(CAM, "idle", _luong()))                           # đã nghỉ: không đụng
        self.assertEqual(["media_player.googlehome5802", "media_player.lg_webos_tv"],
                         self.phat_ha.dung_loa_luong(goi=self.goi))
        self.assertEqual([("media_player", "media_stop", {"entity_id": "media_player.googlehome5802"}),
                          ("media_player", "media_stop", {"entity_id": "media_player.lg_webos_tv"})], self.cuoc_goi)

    def test_loa_khong_co_stop_thi_turn_off_roi_pause(self) -> None:
        self._dat_loa(_loa(CAM, "playing", _luong()), _loa(CHI_PAUSE, "buffering", _luong()),
                      _loa(FPT, "playing", _luong(), features=0))            # không lệnh nào: không giả là đã dừng
        self.assertEqual(["media_player.chi_pause", "media_player.loa_cam_bep"], self.phat_ha.dung_loa_luong(goi=self.goi))
        self.assertEqual({("media_player.loa_cam_bep", "turn_off"), ("media_player.chi_pause", "media_pause")},
                         {(d["entity_id"], dv) for _, dv, d in self.cuoc_goi})

    def test_loc_theo_quyen_va_ha_tu_choi_thi_khong_bao_da_dung(self) -> None:
        self._dat_loa(_loa(GOOGLE_HOME, "playing", _luong()), _loa(LG, "playing", _luong()))
        self.assertEqual(["media_player.lg_webos_tv"],
                         self.phat_ha.dung_loa_luong(cho_phep={"media_player.lg_webos_tv"}, goi=self.goi))
        self.ha_nhan = False
        self.assertEqual([], self.phat_ha.dung_loa_luong(goi=self.goi))

    def test_don_luc_khoi_dong_khong_cat_bai_cua_phien_dang_co(self) -> None:
        self._dat_loa(_loa(GOOGLE_HOME, "playing", _luong()), _loa(LG, "playing", _luong()))
        with patch.object(self.phat_ha, "cac_phien", return_value=[
                {"session_id": "s1", "output_entity_ids": ["media_player.googlehome5802"]}]):
            self.assertEqual(["media_player.lg_webos_tv"], self.phat_ha.dung_loa_luong(chi_mo_coi=True, goi=self.goi))


class DungKhiMatPhienTest(_CoSo):
    def setUp(self) -> None:
        super().setUp()
        p = patch.object(self.phat_ha.ha_client, "doc_media_player_tho",
                         side_effect=lambda: [_loa(GOOGLE_HOME, "playing", _luong()), _loa(LG, "playing", _luong())])
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(self.phat_ha.ha_client, "call_service", side_effect=self.goi)
        p.start()
        self.addCleanup(p.stop)
        self.phat_ha._xoa_bo_dem()

    def test_bot_dung_nhac_khi_c2a_quen_phien(self) -> None:
        from services.youtube_phat import nhac_chat

        self.assertEqual([], self.phat_ha.cac_phien())
        ra = nhac_chat.dieu_khien({"lenh": "dung"}, {"media_player.googlehome5802"})
        self.assertIn("đã dừng nhạc trên media_player.googlehome5802", ra["text"])
        self.assertEqual([("media_player", "media_stop", {"entity_id": "media_player.googlehome5802"})], self.cuoc_goi)

    def test_api_dung_phien_da_mat_van_dung_loa(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import youtube_phat

        p = patch("api.youtube_phat.require_admin", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        app = FastAPI()
        app.include_router(youtube_phat.create_router())
        d = TestClient(app).post("/api/youtube-phat/dung-phien", json={"session_id": "phien-cu"}).json()
        self.assertEqual((True, ["media_player.googlehome5802", "media_player.lg_webos_tv"]), (d["ok"], d["ket_qua"]))

