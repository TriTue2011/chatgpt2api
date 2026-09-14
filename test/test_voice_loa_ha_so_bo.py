"""Loa HA của phần giọng nói không bị sổ «Bỏ khỏi c2a» giấu đi.

Sổ bỏ để bot và tầng học không thấy thiết bị. Nhưng danh sách chọn loa, nút nhập
loa và nút kiểm loa là chỗ CHỦ MÁY tự chọn thiết bị. Đo 14/09/2026: 9/10
media_player của nhà nằm trong sổ, nên ba chỗ đó từng chỉ thấy tivi LG.
"""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

TRANG_THAI = [
    {"entity_id": "media_player.googlehome5802", "state": "idle",
     "attributes": {"friendly_name": "Phòng khách"}},
    {"entity_id": "media_player.lg_webos_tv", "state": "on",
     "attributes": {"friendly_name": "Ti vi phòng khách"}},
    {"entity_id": "light.bep", "state": "on", "attributes": {"friendly_name": "Đèn bếp"}},
    # Tên mang tài khoản:mật khẩu — vẫn phải ẩn ở mọi đường đọc.
    {"entity_id": "media_player.rtsp_admin_pw", "state": "idle",
     "attributes": {"friendly_name": "rtsp://admin:pw@10.0.0.5/loa"}},
]


class LoaHaKhongQuaSoBoTest(unittest.TestCase):
    def setUp(self) -> None:
        from services import ha_client, thiet_bi_bo
        from services.voice import speakers

        self.ha_client, self.speakers = ha_client, speakers
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (
            mock.patch.object(thiet_bi_bo, "_FILE", Path(tmp.name) / "thiet_bi_da_bo.json"),
            mock.patch.object(ha_client, "_get_ha_config", return_value={"url": "http://ha", "token": "t"}),
            mock.patch.object(ha_client.urllib.request, "urlopen",
                              side_effect=lambda *a, **k: io.BytesIO(json.dumps(TRANG_THAI).encode())),
        ):
            p.start()
            self.addCleanup(p.stop)
        thiet_bi_bo._reset_for_tests()
        self.addCleanup(thiet_bi_bo._reset_for_tests)
        thiet_bi_bo.bo("ha", "media_player.googlehome5802", ten_goc="Phòng khách")
        speakers._reset_for_tests(Path(tmp.name) / "speakers.json")
        self.addCleanup(speakers._reset_for_tests)

    def test_bot_van_khong_thay_loa_da_bo(self) -> None:
        ma = {s["entity_id"] for s in self.ha_client.get_states(use_cache=False)}
        self.assertNotIn("media_player.googlehome5802", ma)

    def test_nhap_loa_tu_ha_lay_ca_loa_da_bo_tru_ten_mang_mat_khau(self) -> None:
        them = self.speakers.import_from_ha()
        self.assertEqual({"media_player.googlehome5802", "media_player.lg_webos_tv"},
                         {x["entity_id"] for x in them})

    def test_kiem_loa_ha_da_bo_van_bao_ok(self) -> None:
        ok, ghi_chu = self.speakers.test_reachable({"kind": "ha", "entity_id": "media_player.googlehome5802"})
        self.assertEqual((True, "HA ok (state=idle)"), (ok, ghi_chu))
        ok, _ = self.speakers.test_reachable({"kind": "ha", "entity_id": "media_player.khong_co"})
        self.assertFalse(ok)

    def test_danh_sach_chon_loa_co_loa_da_bo(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import voice

        with mock.patch("api.voice.require_admin", lambda *a, **k: None):
            app = FastAPI()
            app.include_router(voice.create_router())
            rows = TestClient(app).get("/api/voice/ha-media-players").json()["rows"]
        self.assertEqual(["Phòng khách", "Ti vi phòng khách"], [r["name"] for r in rows])


if __name__ == "__main__":
    unittest.main()
