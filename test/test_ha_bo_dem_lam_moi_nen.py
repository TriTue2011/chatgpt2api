"""Bộ đệm HA hết hạn thì trả bản cũ NGAY, làm mới ở nền.

SỰ CỐ 26/09/2026 19:27: "Tắt hết đèn" chờ 16 giây vì `exposed` và `area_index` hết
hạn đúng lúc đó, làm mới ngay trong lượt trả lời và cùng hết giờ 8 giây.
"""
from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.ha_client as ha  # noqa: E402


class BoDemTests(unittest.TestCase):
    def setUp(self):
        self.cu = (ha._exposed_cache, ha._exposed_cache_ts, ha._area_idx_cache, ha._area_idx_cache_ts)

    def tearDown(self):
        ha._exposed_cache, ha._exposed_cache_ts, ha._area_idx_cache, ha._area_idx_cache_ts = self.cu

    def test_het_han_tra_ngay_lam_moi_nen(self):
        xong = threading.Event()

        def cham(*_a):
            time.sleep(0.5)
            xong.set()
            return {"light.moi"}
        ha._exposed_cache, ha._exposed_cache_ts = {"light.cu"}, time.time() - ha._EXPOSED_TTL - 1
        with patch.object(ha, "_get_ha_config", return_value={"url": "http://x", "token": "t"}), \
             patch.object(ha, "_ws_fetch_exposed", side_effect=cham):
            t0 = time.time()
            self.assertEqual(ha.get_exposed_entity_ids(), {"light.cu"})
            self.assertLess(time.time() - t0, 0.2, "không được chờ HA")
            self.assertTrue(xong.wait(3))
            for _ in range(50):
                if ha._exposed_cache == {"light.moi"}:
                    break
                time.sleep(0.02)
        self.assertEqual(ha._exposed_cache, {"light.moi"})

    def test_chua_co_gi_thi_van_cho(self):
        ha._area_idx_cache, ha._area_idx_cache_ts = None, 0.0
        idx = {"entity_area": {"light.a": "Bếp"}, "area_names": {"bep": "Bếp"}, "entity_aliases": {}}
        with patch.object(ha, "_get_ha_config", return_value={"url": "http://x", "token": "t"}), \
             patch.object(ha, "_ws_fetch_registries", return_value=idx):
            self.assertEqual(ha.get_ha_area_index()["entity_area"], {"light.a": "Bếp"})


if __name__ == "__main__":
    unittest.main()
