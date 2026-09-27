"""Đường tắt HA: chữ lạ giữa động từ và tên thiết bị thì nhường cả câu cho model.

Đo 27/09/2026 bằng bộ vi.json của assist-canonicalizer (122 câu) qua `_ha_local_intent`: «mở tiếp
tv» (chuyển bài) bị BẬT TV. Tự sinh thêm câu cùng lớp thì bản cũ bấm nhầm 4/4: «tắt tiếng tv» TẮT
TV, «mở bài tiếp theo trên loa» bật loa, «bật chế độ ngủ cho điều hòa» bật điều hoà. Động từ đi với
tân ngữ khác (tiếp, tiếng, bài, chế độ) — tên thiết bị chỉ là bổ ngữ phía sau.
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.ha_client as ha_client  # noqa: E402
import services.protocol.openai_v1_chat_complete as api  # noqa: E402

TB = [("light.phong_khach", "Đèn phòng khách", "Phòng khách"),
      ("media_player.tivi", "Tivi", "Phòng khách"),
      ("climate.phong_ngu", "Điều hòa phòng ngủ", "Phòng ngủ"),
      ("switch.binh_nong_lanh", "Bình nóng lạnh", "Phòng tắm")]


def _chay(cau: str):
    states = [{"entity_id": e, "state": "off", "attributes": {"friendly_name": t}} for e, t, _ in TB]
    idx = {"entity_area": {e: a for e, _, a in TB},
           "area_names": {ha_client._fold_diacritics(a).strip(): a for _, _, a in TB},
           "entity_aliases": {}}
    with patch.object(ha_client, "get_states", return_value=states), \
         patch.object(ha_client, "get_exposed_entity_ids", return_value={e for e, _, _ in TB}), \
         patch.object(ha_client, "get_ha_area_index", return_value=idx):
        out = api._ha_local_intent([{"role": "user", "content": cau}])
    return None if out is None else [(t["function"]["name"], json.loads(t["function"]["arguments"])["_eids"])
                                     for t in out]


class ChuLaGiuaDongTuVaThietBiTests(unittest.TestCase):

    def test_dong_tu_di_voi_tan_ngu_khac_thi_nhuong_model(self):
        for cau in ("mở tiếp tivi", "tắt tiếng tivi", "bật chế độ ngủ cho điều hòa phòng ngủ",
                    "mở bài tiếp theo trên tivi"):
            with self.subTest(cau=cau):
                self.assertIsNone(_chay(cau))

    def test_mot_cum_nghi_ngo_thi_nhuong_ca_cau(self):
        """Làm nửa lệnh còn tệ hơn: «bật đèn … và tắt tiếng tivi» không được chỉ bật đèn."""
        self.assertIsNone(_chay("bật đèn phòng khách và tắt tiếng tivi"))

    def test_tu_dem_va_bo_ngu_nguon_dien_van_tu_xu_ly(self):
        self.assertEqual(_chay("bật giúp em cái đèn phòng khách"), [("HassTurnOn", ["light.phong_khach"])])
        self.assertEqual(_chay("bật sáng đèn phòng khách"), [("HassTurnOn", ["light.phong_khach"])])
        # «điện» gấp dấu thành "đien" (`_fold_diacritics` giữ «đ») — vẫn phải nhận là từ đệm.
        self.assertEqual(_chay("ngắt điện bình nóng lạnh"), [("HassTurnOff", ["switch.binh_nong_lanh"])])
        self.assertEqual(_chay("tắt tivi"), [("HassTurnOff", ["media_player.tivi"])])


if __name__ == "__main__":
    unittest.main()
