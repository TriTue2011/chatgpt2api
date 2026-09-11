"""Endpoint `/api/mqtt/du-doan` — hai thứ dễ sai âm thầm.

1. TÔN TRỌNG CỜ TẮT. Chủ máy tắt phần học thói quen trong cài đặt thì nó phải
   tắt HẲN. Bản đầu chỉ chặn được đường heartbeat: endpoint này không xét cờ,
   nên ai mở trang cài đặt là `quet()` vẫn chạy — tắt mà không tắt.

2. KHÔNG CHẶN VÒNG LẶP SỰ KIỆN. `quet()` gọi `hoc()`, việc thuần CPU đọc hàng
   trăm nghìn dòng lịch sử. Gọi thẳng trong `async def` là trong lúc nó chạy
   MỌI endpoint khác ngừng trả lời, kể cả `/health`.

   Khớp đúng dấu hiệu vụ c2a treo hẳn đêm 11/09/2026 (tiến trình `R (running)`,
   mọi endpoint trả 000), và chỉ cần mở trang cài đặt một lần là đủ kích hoạt.

Hai lỗi này không ném ngoại lệ, không ghi log — nhìn từ ngoài chỉ thấy "dịch
vụ chết" mà không rõ vì sao. Nên phải khoá bằng test.
"""

from __future__ import annotations

import unittest
from unittest import mock


def _app():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import mqtt as api_mqtt

    app = FastAPI()
    app.include_router(api_mqtt.create_router())
    bo_qua = mock.patch("api.mqtt.require_admin", lambda *a, **k: None)
    bo_qua.start()
    return TestClient(app), bo_qua


class DuDoanEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self._bo_qua = _app()
        self.addCleanup(self._bo_qua.stop)
        from services import du_doan_nha as dn
        self.dn = dn

    def test_TAT_thi_KHONG_goi_quet(self) -> None:
        """Tắt trong cài đặt = tắt hẳn, không phải chỉ tắt đường heartbeat."""
        with mock.patch.object(self.dn, "is_enabled", return_value=False), \
             mock.patch.object(self.dn, "quet") as q, \
             mock.patch.object(self.dn, "thong_ke", return_value={"bat": False}):
            d = self.client.get("/api/mqtt/du-doan").json()
        q.assert_not_called()
        self.assertTrue(d["ok"])
        self.assertEqual(d["dang_nghi"], [])
        self.assertIn("bo_qua", d)

    def test_BAT_thi_co_goi_quet(self) -> None:
        with mock.patch.object(self.dn, "is_enabled", return_value=True), \
             mock.patch.object(self.dn, "quet", return_value=[{"ten": "x"}]) as q, \
             mock.patch.object(self.dn, "thong_ke", return_value={}):
            d = self.client.get("/api/mqtt/du-doan").json()
        q.assert_called_once()
        self.assertEqual(d["dang_nghi"], [{"ten": "x"}])

    def test_QUET_chay_trong_LUONG_RIENG(self) -> None:
        """`quet()` phải chạy ngoài luồng chính, kẻo nó chặn cả gateway.

        Đo bằng cách so tên luồng: luồng chạy `quet()` không được trùng luồng
        đang phục vụ request.
        """
        import threading

        luong: dict[str, int] = {}

        def _ghi_luong():
            luong["quet"] = threading.get_ident()
            return []

        def _ghi_luong_chinh():
            luong["chinh"] = threading.get_ident()
            return {}

        with mock.patch.object(self.dn, "is_enabled", return_value=True), \
             mock.patch.object(self.dn, "quet", side_effect=_ghi_luong), \
             mock.patch.object(self.dn, "thong_ke", side_effect=_ghi_luong_chinh):
            self.client.get("/api/mqtt/du-doan")

        self.assertIn("quet", luong)
        self.assertIn("chinh", luong)
        self.assertNotEqual(luong["quet"], luong["chinh"],
                            "quet() phải chạy ở luồng khác luồng phục vụ request")

    def test_QUET_HONG_thi_bao_loi_chu_khong_no_500(self) -> None:
        with mock.patch.object(self.dn, "is_enabled", return_value=True), \
             mock.patch.object(self.dn, "quet", side_effect=RuntimeError("kho hỏng")):
            r = self.client.get("/api/mqtt/du-doan")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])


if __name__ == "__main__":
    unittest.main()
