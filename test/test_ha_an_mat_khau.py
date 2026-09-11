"""Thực thể HA có tên mang tài khoản:mật khẩu không được ra khỏi máy.

Đo 11/09/2026: go2rtc đặt tên 4 camera bằng nguyên đường dẫn RTSP kèm mật
khẩu, HA sinh luôn mã thực thể từ tên đó; tên và mã lọt vào ngữ cảnh chat gửi
model và vào tin báo nhóm Zalo "AI học hỏi".
"""

from __future__ import annotations

import json
import unittest
from unittest import mock


class AnThucTheMangMatKhauTest(unittest.TestCase):
    def test_AN_ten_co_MAT_KHAU_ke_ca_MAT_KHAU_CO_A_CONG(self) -> None:
        """Mật khẩu thật của nhà có dấu "@" — cắt ở "@" đầu tiên là lộ nửa sau."""
        from services import ha_client

        ds = [{"entity_id": "camera.go2rtc_rtsp_nguoi_mat_khau1_10_0_0_5_554_cua",
               "attributes": {"friendly_name": "go2rtc rtsp://Nguoi:Mat@Khau1@10.0.0.5:554/cua"}},
              {"entity_id": "camera.cua", "attributes": {"friendly_name": "Cam cửa"}},
              {"entity_id": "camera.bep_sub",
               "attributes": {"friendly_name": "go2rtc rtsp://10.0.0.5:554/bep"}}]
        con = [s["entity_id"] for s in ha_client._an_thuc_the_mang_mat_khau(ds)]
        self.assertEqual(con, ["camera.cua", "camera.bep_sub"],
                         "URL không kèm mật khẩu thì vẫn giữ")

    def test_GET_STATES_da_an_truoc_khi_ai_doc(self) -> None:
        """Ẩn tại chỗ NẠP, nên ngữ cảnh chat, đề bot học hỏi, tin báo đều không thấy."""
        from services import ha_client

        tra = [{"entity_id": "camera.x", "attributes": {"friendly_name": "rtsp://a:b@h/x"}},
               {"entity_id": "light.bep", "attributes": {"friendly_name": "Đèn bếp"}}]

        class _Tra:
            def read(self) -> bytes:
                return json.dumps(tra).encode()

        with mock.patch.object(ha_client, "_state_cache", []), \
             mock.patch.object(ha_client, "_state_cache_ts", 0.0), \
             mock.patch.object(ha_client, "_state_fail_ts", 0.0), \
             mock.patch.object(ha_client, "_get_ha_config",
                               return_value={"url": "http://ha", "token": "t"}), \
             mock.patch("urllib.request.urlopen", return_value=_Tra()):
            ds = ha_client.get_states(use_cache=False)
        self.assertEqual([s["entity_id"] for s in ds], ["light.bep"])

    def test_GET_STATE_MOT_THUC_THE_cung_AN(self) -> None:
        """Đọc lẻ một thực thể (mô tả khả năng, kiểm trước khi gọi dịch vụ) là
        đường thứ hai ra model — phải cùng luật với `get_states`."""
        from services import ha_client

        class _Tra:
            def read(self) -> bytes:
                return json.dumps({"entity_id": "camera.x",
                                   "attributes": {"friendly_name": "rtsp://a:b@h/x"}}).encode()

        with mock.patch.object(ha_client, "_get_ha_config",
                               return_value={"url": "http://ha", "token": "t"}), \
             mock.patch("urllib.request.urlopen", return_value=_Tra()):
            self.assertIsNone(ha_client.get_state("camera.x"))


if __name__ == "__main__":
    unittest.main()
