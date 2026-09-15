"""Canh camera: hai nguồn (Frigate, YOLO) → nhận mặt → ghi lượt → báo tin.

Không camera, không model thật: `chup_tho`/`doc_anh`/`phan_tich_khung` giả, sổ
khuôn mặt thật trong thư mục tạm, `thong_bao.gui` giả để đếm tin.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np
import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import canh_camera_nha as cc  # noqa: E402


def _vec(i: int):
    v = np.zeros(512, np.float32)
    v[i] = 1.0
    return v


class _Nen(unittest.TestCase):
    def setUp(self):
        pytest.importorskip("cv2")
        from services import camera_nha, nhin_nha, so_mat_nha, yolo_nha

        self.sm, self.nn = so_mat_nha, nhin_nha
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        so_mat_nha._reset_for_tests()
        self.cfg = {"canh": {"bat": True, "camera_ve": ["Cam cửa"], "hoi_ten_sau": 3,
                             "phien_phut": 10}, "khuon_mat": {"bo": "buffalo_s"}}
        self.gui: list[tuple[str, str, str]] = []
        self.mat: list[dict] = []
        self.gio = [1_000_000.0]
        self.p = [
            mock.patch.object(so_mat_nha, "_DB_PATH", tmp / "km.sqlite"),
            mock.patch.object(so_mat_nha, "_THU_MUC_ANH", tmp / "anh"),
            mock.patch.dict(nhin_nha.config.data, {"nhin_nha": self.cfg}),
            mock.patch.object(nhin_nha, "co_mat", lambda: True),
            mock.patch.object(camera_nha, "chup_tho", lambda ten, **kw: (ten, b"jpeg")),
            mock.patch.object(camera_nha, "danh_sach",
                              lambda: [{"name": "Cam cửa"}, {"name": "Cam bếp"}]),
            mock.patch.object(yolo_nha, "doc_anh",
                              lambda b: np.full((720, 1280, 3), 90, np.uint8)),
            mock.patch.object(nhin_nha, "phan_tich_khung",
                              lambda anh, **kw: nhin_nha.KhungDaXem(1280, 720, [], list(self.mat))),
            mock.patch("services.thong_bao.gui",
                       lambda khoa, tin, anh_url="": self.gui.append((khoa, tin, anh_url)) or 1),
            mock.patch.object(cc, "_luu_anh_bao", lambda anh, hop: "http://cong/images/x.jpg"),
            mock.patch.object(cc.time, "time", lambda: self.gio[0]),
        ]
        for x in self.p:
            x.start()
        cc._phien.clear()
        cc._lan_mat.clear()
        cc._dang_cho.clear()

    def tearDown(self):
        for x in reversed(self.p):
            x.stop()
        self.sm._reset_for_tests()
        self._tmp.cleanup()

    def _m(self, loai, vec, *, ten=None, nguoi_id=None, do_giong=0.0, nho=False, diem=0.9):
        return {"hop": [500, 200, 580, 300], "diem_do": diem, "nho": nho, "vector": vec,
                "nguoi_id": nguoi_id, "ten": ten, "do_giong": do_giong, "loai": loai,
                "nguoi_so": 0}

    def _tien(self, phut: float):
        self.gio[0] += phut * 60


class LuotVaBaoTinTests(_Nen):
    def test_nguoi_quen_ve_o_camera_cua_bao_mot_lan_moi_luot(self):
        self.mat = [self._m("quen", _vec(1), ten="Việt", nguoi_id="n1", do_giong=77)]
        r = cc.xu_ly("Cam cửa", "frigate")
        self.assertEqual(len(r["su_kien"]), 1)
        self.assertEqual([g[0] for g in self.gui], ["camera.nguoi_quen"])
        self.assertIn("Việt vừa về — Cam cửa", self.gui[0][1])
        self.assertEqual(self.gui[0][2], "http://cong/images/x.jpg")
        self._tien(3)                                   # vẫn trong 10 phút: cùng lượt
        self.assertEqual(cc.xu_ly("Cam cửa", "yolo")["su_kien"], [])
        self.assertEqual(len(self.gui), 1)
        self._tien(11)                                  # quá phiên: lượt mới
        self.assertEqual(len(cc.xu_ly("Cam cửa", "yolo")["su_kien"]), 1)
        self.assertEqual(len(self.gui), 2)

    def test_nguoi_quen_o_camera_khong_phai_cua_chi_ghi_khong_bao(self):
        self.mat = [self._m("quen", _vec(1), ten="Việt", nguoi_id="n1", do_giong=77)]
        self.assertEqual(len(cc.xu_ly("Cam bếp", "yolo")["su_kien"]), 1)
        self.assertEqual(self.gui, [])

    def test_mat_la_gom_cum_dem_luot_va_hoi_ten_khi_du_luot(self):
        self.mat = [self._m("la", _vec(7))]
        ma = set()
        for _ in range(3):
            r = cc.xu_ly("Cam cửa", "frigate")
            ma.add(r["su_kien"][0]["mat_la_id"])
            self._tien(15)
        self.assertEqual(len(ma), 1, "cùng một mặt lạ phải là MỘT cụm")
        khoa = [g[0] for g in self.gui]
        self.assertEqual(khoa.count("camera.nguoi_la"), 3)
        self.assertEqual(khoa.count("camera.hoi_ten"), 1)       # đủ 3 lượt mới hỏi
        hoi = next(g[1] for g in self.gui if g[0] == "camera.hoi_ten")
        ma_la = ma.pop()
        self.assertIn(f"thôi hỏi về mặt lạ {ma_la}", hoi)
        self.assertEqual(self.sm.mat_la(ma_la)["so_lan"], 3)
        self.assertEqual(self.sm.mat_la(ma_la)["da_hoi"], 1)
        # Lượt thứ 4, 5: chưa tới mốc 6 → không hỏi lại.
        for _ in range(2):
            cc.xu_ly("Cam cửa", "frigate")
            self._tien(15)
        self.assertEqual([g[0] for g in self.gui].count("camera.hoi_ten"), 1)

    def test_mat_nho_hoac_diem_do_thap_khong_ghi(self):
        self.mat = [self._m("la", _vec(7), nho=True), self._m("la", _vec(8), diem=0.4)]
        self.assertEqual(cc.xu_ly("Cam cửa", "yolo")["su_kien"], [])
        self.assertEqual(self.sm.danh_sach_mat_la(), [])
        self.assertEqual(self.gui, [])

    def test_dat_ten_mat_la_chuyen_luot_cu_sang_nguoi(self):
        self.mat = [self._m("la", _vec(7))]
        ma = cc.xu_ly("Cam cửa", "frigate")["su_kien"][0]["mat_la_id"]
        self._tien(15)
        cc.xu_ly("Cam cửa", "frigate")

        class _May:
            bo = self.nn.bo_mat()

            def do(self_may, anh, nguong=0.5):
                from services import khuon_mat_nha as km
                return [km.Mat((10.0, 10.0, 90.0, 110.0), 0.9, None)]

            def vector(self_may, anh, m):
                m.vector = _vec(7)
                return m.vector

        with mock.patch.object(self.nn, "mat", lambda: _May()):
            kq = self.sm.dat_ten_mat_la(ma, "Bà ngoại")
        self.assertEqual((kq["ten"], kq["so_luot"]), ("Bà ngoại", 2))
        self.assertIsNone(self.sm.mat_la(ma))
        ds = self.sm.su_kien_gan(24)
        self.assertEqual({(s["ten"], s["loai"]) for s in ds}, {("Bà ngoại", "quen")})


class NguonTests(_Nen):
    def test_su_kien_frigate_person_xin_nhan_mat_dung_camera(self):
        cc.su_kien_frigate({"type": "new", "after": {"camera": "cua", "label": "person"}})
        cc.su_kien_frigate({"type": "new", "after": {"camera": "cua", "label": "car"}})
        cc.su_kien_frigate({"type": "end", "after": {"camera": "cua", "label": "person"}})
        cc.su_kien_frigate({"type": "new", "after": {"camera": "la", "label": "person"}})
        self.assertEqual(cc._dang_cho, {"Cam cửa"})
        self.assertEqual(cc._hang.get_nowait(), ("Cam cửa", "frigate"))
        cc._dang_cho.clear()

    def test_ma_frigate_CUA_khop_Cam_cua_du_cua_la_tu_chung(self):
        """Lỗi thật 15/09/2026: `camera_nha.tim("cua")` bỏ «cua» (của) như từ
        chung nên camera cửa của Frigate không khớp «Cam cửa» — đúng camera cần
        nhất cho «người quen về»."""
        from services import camera_nha
        ds = [{"name": "Cam ban công"}, {"name": "Cam bếp"}, {"name": "Cam cửa"},
              {"name": "Cam phòng khách"}, {"name": "Cam phòng ngủ"}]
        c = cc.cfg()
        with mock.patch.object(camera_nha, "danh_sach", lambda: ds):
            self.assertEqual(camera_nha.tim("cua")[1], None)          # bằng chứng của lỗi
            for ma, ten in (("cua", "Cam cửa"), ("bep", "Cam bếp"), ("ban-cong", "Cam ban công"),
                            ("phong-khach", "Cam phòng khách"), ("phong_ngu", "Cam phòng ngủ"),
                            ("phong", ""), ("garage", ""), ("", "")):
                self.assertEqual(cc.camera_tu_frigate(ma, c), ten, ma)
            self.assertEqual(cc.camera_tu_frigate("cam1", {"frigate_ban_do": {"cam1": "Cam bếp"}}),
                             "Cam bếp")

    def test_tat_canh_thi_frigate_khong_xep_hang(self):
        self.cfg["canh"]["bat"] = False
        cc.su_kien_frigate({"type": "new", "after": {"camera": "cua", "label": "person"}})
        self.assertEqual(cc._dang_cho, set())

    def test_hai_nguon_cung_luc_chi_nhan_mat_mot_lan(self):
        self.assertTrue(cc.yeu_cau("Cam cửa", "frigate"))
        self.assertFalse(cc.yeu_cau("Cam cửa", "yolo"))          # đang chờ sẵn
        cc._hang.get_nowait()
        cc._dang_cho.clear()
        cc._lan_mat["Cam cửa"] = self.gio[0]
        self.assertFalse(cc.yeu_cau("Cam cửa", "yolo"))          # vừa nhận xong
        self._tien(1)
        self.assertTrue(cc.yeu_cau("Cam cửa", "yolo"))
        cc._hang.get_nowait()
        cc._dang_cho.clear()

    def test_camera_khong_nam_trong_danh_sach_canh_bi_bo_qua(self):
        self.cfg["canh"]["camera"] = ["Cam bếp"]
        self.assertFalse(cc.yeu_cau("Cam cửa", "frigate"))


if __name__ == "__main__":
    unittest.main()


class ToolKhuonMatTests(_Nen):
    def _goi(self, **args):
        from services.agent import capabilities as C
        return C.CAPABILITIES["khuon_mat"].handler(args, {"user_id": "u"})["text"]

    def test_tool_chi_co_khi_tich_camera(self):
        from services.agent import capabilities as C
        self.assertNotIn("khuon_mat", [t["function"]["name"] for t in C.tools_schema(None)])
        self.assertIn("khuon_mat", [t["function"]["name"] for t in C.tools_schema({"camera"})])

    def test_xem_ke_luot_theo_ten_va_nguoi_la_theo_ma(self):
        self.assertIn("chưa ghi ai", self._goi())
        self.mat = [self._m("quen", _vec(1), ten="Việt", nguoi_id="n1", do_giong=77),
                    self._m("la", _vec(7))]
        with mock.patch.object(self.sm.time, "time", lambda: self.gio[0]):
            cc.xu_ly("Cam cửa", "frigate")
        with mock.patch.object(self.sm, "su_kien_gan", wraps=self.sm.su_kien_gan) as sk, \
             mock.patch("time.time", lambda: self.gio[0]):
            tl = self._goi(so_gio=2)
        self.assertTrue(sk.called)
        ma = self.sm.danh_sach_mat_la()[0]["id"]
        self.assertIn(f"người lạ «{ma}» ở Cam cửa", tl)

    def test_xem_khi_tat_canh_thi_noi_ro(self):
        self.cfg["canh"]["bat"] = False
        self.assertIn("canh camera đang TẮT", self._goi())

    def test_dat_ten_bo_trong_ma_lay_mat_la_gan_nhat_va_thoi_hoi(self):
        self.mat = [self._m("la", _vec(7))]
        cc.xu_ly("Cam cửa", "frigate")
        ma = self.sm.danh_sach_mat_la()[0]["id"]
        self.assertIn(ma, self._goi(viec="thoi_hoi", ma=ma))
        self.assertTrue(self.sm.mat_la(ma)["bo_qua"])
        self.assertIn("Anh/chị nêu mã", self._goi(viec="thoi_hoi"))
        with mock.patch.object(self.sm, "dat_ten_mat_la",
                               return_value={"ten": "Bà", "so_luot": 1}) as d, \
             mock.patch.object(self.sm, "danh_sach_mat_la", return_value=[{"id": "abc"}]):
            self.assertIn("mặt lạ «abc» là **Bà**", self._goi(viec="dat_ten", ten="Bà"))
        d.assert_called_once_with("abc", "Bà")


class ApiQuyenTests(unittest.TestCase):
    def test_khong_co_khoa_admin_thi_tu_choi(self):
        """Ảnh mặt là dữ liệu sinh trắc — mọi đường của sổ mặt đòi quyền admin."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import nhin_nha as api_nn

        app = FastAPI()
        app.include_router(api_nn.create_router())
        c = TestClient(app)
        for phuong, duong in (("get", "/api/nhin-nha/nguoi"), ("get", "/api/nhin-nha/mat-la"),
                              ("get", "/api/nhin-nha/su-kien"), ("get", "/api/nhin-nha/trang-thai"),
                              ("delete", "/api/nhin-nha/nguoi/x"),
                              ("post", "/api/nhin-nha/mat-la/x/thoi-hoi")):
            self.assertIn(getattr(c, phuong)(duong).status_code, (401, 403), duong)


class ApiNhinNhaTests(_Nen):
    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api import nhin_nha as api_nn

        app = FastAPI()
        app.include_router(api_nn.create_router())
        bo_qua = mock.patch("api.nhin_nha.require_admin", lambda *a, **k: None)
        bo_qua.start()
        self.addCleanup(bo_qua.stop)
        self.client = TestClient(app)

    def test_mat_la_dat_ten_thoi_hoi_va_su_kien(self):
        self.mat = [self._m("la", _vec(7))]
        cc.xu_ly("Cam cửa", "frigate")
        ds = self.client.get("/api/nhin-nha/mat-la").json()["mat_la"]
        self.assertEqual(len(ds), 1)
        self.assertTrue(ds[0]["anh"].startswith("data:image/jpeg;base64,"))
        with mock.patch("time.time", lambda: self.gio[0]):
            sk = self.client.get("/api/nhin-nha/su-kien?so_gio=1").json()["su_kien"]
        self.assertEqual([s["loai"] for s in sk], ["la"])
        self.assertTrue(self.client.post(f"/api/nhin-nha/mat-la/{ds[0]['id']}/thoi-hoi").json()["ok"])
        self.assertEqual(self.client.get("/api/nhin-nha/mat-la").json()["mat_la"], [])
        d = self.client.post("/api/nhin-nha/mat-la/khong-co/dat-ten", json={"ten": "A"}).json()
        self.assertFalse(d["ok"])
        self.assertIn("Không có mặt lạ", d["error"])

    def test_day_mat_qua_web_va_doi_ten_xoa(self):
        import cv2

        class _May:
            bo = self.nn.bo_mat()

            def do(self_may, anh, nguong=0.5):
                from services import khuon_mat_nha as km
                return [km.Mat((100.0, 100.0, 260.0, 300.0), 0.9, None)]

            def vector(self_may, anh, m):
                m.vector = _vec(3)
                return m.vector

        ok, buf = cv2.imencode(".jpg", np.full((480, 640, 3), 120, np.uint8))
        with mock.patch.object(self.nn, "mat", lambda: _May()):
            d = self.client.post("/api/nhin-nha/day", data={"ten": "Lan"},
                                 files={"anh": ("a.jpg", buf.tobytes(), "image/jpeg")}).json()
        self.assertTrue(d["ok"], d)
        ds = self.client.get("/api/nhin-nha/nguoi").json()["nguoi"]
        self.assertEqual([(n["ten"], n["so_mat"]) for n in ds], [("Lan", 1)])
        self.assertTrue(ds[0]["anh"].startswith("data:image/jpeg;base64,"))
        nid = ds[0]["id"]
        self.assertTrue(self.client.post(f"/api/nhin-nha/nguoi/{nid}/doi-ten",
                                         json={"ten": "Lan Anh"}).json()["ok"])
        self.assertTrue(self.client.delete(f"/api/nhin-nha/nguoi/{nid}").json()["ok"])
        self.assertEqual(self.client.get("/api/nhin-nha/nguoi").json()["nguoi"], [])
