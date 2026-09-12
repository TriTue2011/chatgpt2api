"""Endpoint `api/hoc_hoi.py` — tab Học hỏi: xem/sửa/xoá + tự thêm tay.

Mỗi endpoint chỉ gọi đúng hàm dịch vụ hẹp tương ứng (không POST cả khối config),
để sửa một công tắc không làm mất khoá khác (bẫy cũ: mất `du_doan.kenh_nhan`).
"""

from __future__ import annotations

import unittest
from unittest import mock


def _app():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import hoc_hoi as api_hoc_hoi

    app = FastAPI()
    app.include_router(api_hoc_hoi.create_router())
    bo_qua = mock.patch("api.hoc_hoi.require_admin", lambda *a, **k: None)
    bo_qua.start()
    return TestClient(app), bo_qua


class TangBatTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self._bo_qua = _app()
        self.addCleanup(self._bo_qua.stop)

    def test_KHOA_LA_TREN_DANH_SACH_TRANG_thi_TU_CHOI(self) -> None:
        """Không cho ghi bừa vào config qua endpoint này."""
        d = self.client.post("/api/hoc-hoi/tang/bat",
                             json={"khoa": "khong_co_that", "bat": True}).json()
        self.assertFalse(d["ok"])

    def test_BAT_TANG_CHI_SUA_DUNG_KHOA_do_KHONG_DUNG_KHOA_KHAC(self) -> None:
        from services.config import config
        config.data.setdefault("mqtt", {})["du_doan"] = {"bat": False, "kenh_nhan": ["zalop:a:b"]}
        d = self.client.post("/api/hoc-hoi/tang/bat", json={"khoa": "du_doan", "bat": True}).json()
        self.assertTrue(d["ok"])
        muc = config.data["mqtt"]["du_doan"]
        self.assertTrue(muc["bat"])
        self.assertEqual(muc["kenh_nhan"], ["zalop:a:b"],
                         "bật/tắt một tầng không được xoá khoá khác trong cùng khối")


class SoTenEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self._bo_qua = _app()
        self.addCleanup(self._bo_qua.stop)
        from services import so_ten_nha as sn
        self.sn = sn

    def test_DAT_TEN_ROI_XOA(self) -> None:
        with mock.patch("services.agent.state.nho_hoac_cap_nhat"):
            d = self.client.post("/api/hoc-hoi/ten/dat",
                                 json={"nguon": "mqtt", "loai": "thiet_bi", "ma": "x",
                                       "ten": "Đèn thử", "khu_vuc": "Bếp"}).json()
        self.assertTrue(d["ok"])
        k = self.sn.khoa("mqtt", "thiet_bi", "x")
        self.assertTrue(any(m["khoa"] == k for m in self.sn.danh_sach()))
        d2 = self.client.post("/api/hoc-hoi/ten/xoa", json={"khoa": k}).json()
        self.assertTrue(d2["ok"])
        self.assertFalse(any(m["khoa"] == k for m in self.sn.danh_sach()))

    def test_DAT_TEN_THIEU_MA_TRA_LOI(self) -> None:
        d = self.client.post("/api/hoc-hoi/ten/dat", json={"ten": "chỉ có tên"}).json()
        self.assertFalse(d["ok"])

    def test_XOA_KHONG_TON_TAI_TRA_LOI(self) -> None:
        d = self.client.post("/api/hoc-hoi/ten/xoa", json={"khoa": "mqtt:thiet_bi#khong_co"}).json()
        self.assertFalse(d["ok"])


class DuKienEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self._bo_qua = _app()
        self.addCleanup(self._bo_qua.stop)

    def test_GHI_ROI_SUA_ROI_XOA(self) -> None:
        d = self.client.post("/api/hoc-hoi/du-kien/ghi", json={"noi_dung": "dữ kiện gốc"}).json()
        self.assertTrue(d["ok"])
        i = d["id"]
        d2 = self.client.post("/api/hoc-hoi/du-kien/ghi", json={"id": i, "noi_dung": "đã sửa"}).json()
        self.assertTrue(d2["ok"])
        ds = self.client.get("/api/hoc-hoi/du-kien").json()["danh_sach"]
        self.assertEqual({x["id"]: x["noi_dung"] for x in ds}[i], "đã sửa")
        d3 = self.client.post("/api/hoc-hoi/du-kien/xoa", json={"id": i}).json()
        self.assertTrue(d3["ok"])

    def test_GHI_RONG_TU_CHOI(self) -> None:
        d = self.client.post("/api/hoc-hoi/du-kien/ghi", json={"noi_dung": "  "}).json()
        self.assertFalse(d["ok"])


class KetLuanEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self._bo_qua = _app()
        self.addCleanup(self._bo_qua.stop)
        from services import hieu_thiet_bi_nha as ht
        self.ht = ht

    def test_CHAM_GOI_DUNG_SUA_CHAM_VOI_NGUOI_CHAM_LA_CHU_MAY(self) -> None:
        with mock.patch.object(self.ht, "sua_cham", return_value=True) as sc:
            d = self.client.post("/api/hoc-hoi/ket-luan/cham",
                                 json={"id": 7, "dung": True, "ghi_chu": "ghi chú"}).json()
        self.assertTrue(d["ok"])
        sc.assert_called_once_with(7, True, cham_boi="chu_may", ghi_chu="ghi chú")

    def test_CHAM_KHONG_CO_TRA_LOI(self) -> None:
        with mock.patch.object(self.ht, "sua_cham", return_value=False):
            d = self.client.post("/api/hoc-hoi/ket-luan/cham", json={"id": 7, "dung": True}).json()
        self.assertFalse(d["ok"])

    def test_XOA_KET_LUAN(self) -> None:
        with mock.patch.object(self.ht, "xoa_ket_luan", return_value=True) as x:
            d = self.client.post("/api/hoc-hoi/ket-luan/xoa", json={"id": 3}).json()
        self.assertTrue(d["ok"])
        x.assert_called_once_with(3)


class HuongDanEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self._bo_qua = _app()
        self.addCleanup(self._bo_qua.stop)
        from services import hieu_thiet_bi_nha as ht
        self.ht = ht

    def test_XEM_ROI_GHI_HUONG_DAN(self) -> None:
        with mock.patch.object(self.ht, "huong_dan", return_value=("nội dung", "abc123")):
            d = self.client.get("/api/hoc-hoi/huong-dan").json()
        self.assertEqual(d["noi_dung"], "nội dung")
        self.assertEqual(d["phien_ban"], "abc123")
        with mock.patch.object(self.ht, "ghi_huong_dan", return_value=True), \
             mock.patch.object(self.ht, "huong_dan", return_value=("mới", "def456")):
            d2 = self.client.post("/api/hoc-hoi/huong-dan/ghi", json={"noi_dung": "mới"}).json()
        self.assertTrue(d2["ok"])
        self.assertEqual(d2["phien_ban"], "def456")


class TinhHuongThemEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self._bo_qua = _app()
        self.addCleanup(self._bo_qua.stop)
        from services import tinh_huong_nha as th
        self.th = th

    def test_THEM_TAY_GOI_DUNG_THAM_SO(self) -> None:
        with mock.patch.object(self.th, "them_tay", return_value=9) as tt:
            d = self.client.post("/api/hoc-hoi/tinh-huong/them",
                                 json={"ten": "ăn tối", "gio": 19.5, "phut": 20, "thu": -1}).json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["id"], 9)
        tt.assert_called_once_with("ăn tối", 19.5, lech_phut=20, thu=-1)

    def test_THIEU_TEN_TU_CHOI(self) -> None:
        d = self.client.post("/api/hoc-hoi/tinh-huong/them", json={"gio": 19}).json()
        self.assertFalse(d["ok"])

    def test_GIO_KHONG_HOP_LE_TU_CHOI(self) -> None:
        d = self.client.post("/api/hoc-hoi/tinh-huong/them",
                             json={"ten": "x", "gio": "khong-phai-so"}).json()
        self.assertFalse(d["ok"])


class DuDoanXoaEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self._bo_qua = _app()
        self.addCleanup(self._bo_qua.stop)
        from services import du_doan_nha as dn
        self.dn = dn

    def test_XOA_GOI_DUNG_HAM(self) -> None:
        with mock.patch.object(self.dn, "xoa", return_value=True) as x:
            d = self.client.post("/api/hoc-hoi/du-doan/xoa", json={"id": 5}).json()
        self.assertTrue(d["ok"])
        x.assert_called_once_with(5)

    def test_CHO_CHAM_TRA_DANH_SACH(self) -> None:
        with mock.patch.object(self.dn, "cho_cham", return_value=[{"id": 1, "ten": "x"}]):
            d = self.client.get("/api/hoc-hoi/du-doan/cho-cham").json()
        self.assertEqual(d["danh_sach"], [{"id": 1, "ten": "x"}])


if __name__ == "__main__":
    unittest.main()
