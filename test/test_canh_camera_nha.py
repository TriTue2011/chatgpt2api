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
        # `khoang_khung_giay: 0` — vẫn nhìn đủ 5 khung như thật (để test chạm vào
        # phần gom đại diện), nhưng KHÔNG ngủ giữa các khung. Để mặc định 0,5 s
        # thì riêng bộ test này mất 32 giây thay vì 3.
        self.cfg = {"canh": {"bat": True, "camera_ve": ["Cam cửa"], "hoi_ten_sau": 3,
                             "phien_phut": 10, "camera": ["Cam cửa", "Cam bếp"],
                             "khoang_khung_giay": 0},
                    "khuon_mat": {"bo": "buffalo_s"}}
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

    def test_KHONG_tich_camera_nao_thi_KHONG_canh_gi(self):
        """Rỗng = không canh gì, KHÔNG phải canh mọi camera.

        Chủ máy 16/09/2026: *"khi không tích cam nào là không dùng yolo"*.
        Trước đây rỗng nghĩa là mọi camera nên bỏ tích hết vẫn quét cả bốn.
        """
        self.cfg["canh"]["camera"] = []
        self.assertEqual(cc._camera_duoc_canh(cc.cfg()), [])
        self.assertFalse(cc.yeu_cau("Cam cửa", "yolo"))
        self.assertFalse(cc.yeu_cau("Cam bếp", "frigate"))

    def test_nguoi_la_dua_LUA_CHON_nguoi_da_biet_va_them_moi(self):
        """Chủ máy 16/09/2026: người lạ thì đưa danh sách người đã dạy để bấm.

        Bắt người dùng gõ «mặt lạ ab12 là ...» là bắt họ nhớ một mã băm.
        """
        with mock.patch.object(self.sm, "danh_sach_nguoi",
                               lambda: [{"ten": "Bà ngoại"}, {"ten": "Chú Tư"}]):
            dong = cc._lua_chon_mat_la("ab12")
        self.assertEqual(dong[0], "<<<ASK>>>")
        self.assertEqual(dong[-1], "<<<END>>>")
        ca = "\n".join(dong)
        self.assertIn("Là Bà ngoại | mặt lạ ab12 là Bà ngoại", ca)
        self.assertIn("Là Chú Tư | mặt lạ ab12 là Chú Tư", ca)
        self.assertIn("Thêm người mới", ca)
        self.assertIn("thôi hỏi về mặt lạ ab12", ca)

    def test_LUA_CHON_co_TRAN_va_nhan_nut_khong_qua_40_ky_tu(self):
        """`ask_choices` cắt nhãn ở 40 ký tự — phải rút ở đây, đừng để nó cắt."""
        nhieu = [{"ten": f"Người thứ {i} tên rất dài để thử cắt"} for i in range(20)]
        with mock.patch.object(self.sm, "danh_sach_nguoi", lambda: nhieu):
            dong = cc._lua_chon_mat_la("ab12")
        self.assertEqual(len([d for d in dong if d.startswith("Là ")]),
                         cc._TOI_DA_NGUOI_CHON)
        for d in dong:
            if "|" in d:
                self.assertLessEqual(len(d.split("|")[0].strip()), 40)

    def test_ten_luong_phu_chi_nhan_TEN_go2rtc_khong_nhan_URL(self):
        """Khai URL thì không suy ra tên luồng được — và KHÔNG được đoán «-sub».

        Ghép «-sub» là quy ước của riêng một nhà; nhà khác đặt tên khác thì
        đoán như vậy là đọc nhầm sang camera của người ta.
        """
        from services import camera_nha

        self.assertEqual(
            camera_nha._ten_luong_phu({"kind": "go2rtc", "src_ai": "cua-sub"}), "cua-sub")
        self.assertEqual(
            camera_nha._ten_luong_phu({"kind": "go2rtc", "src_ai": "rtsp://may/cua"}), "")
        self.assertEqual(camera_nha._ten_luong_phu({"kind": "go2rtc", "src_ai": ""}), "")
        self.assertEqual(
            camera_nha._ten_luong_phu({"kind": "rtsp", "src_ai": "cua-sub"}), "")

    def test_khung_ben_bi_camera_khong_co_thi_tra_None_chu_khong_nem(self):
        """Đường TĂNG TỐC: hỏng thì rơi về cách cũ, không được làm mất ảnh."""
        from services import camera_nha

        self.assertIsNone(camera_nha.khung_ben_bi("camera không tồn tại bao giờ"))

    def test_chat_luong_MAT_TO_NET_hon_thi_diem_CAO_hon(self):
        """Chấm để CHỌN khung tốt nhất trong lượt, nên phải phân biệt được to/nhỏ."""
        anh = np.random.default_rng(7).integers(0, 255, (400, 400, 3), dtype=np.uint8)
        to = cc._diem_chat_luong(anh, {"hop": [10, 10, 210, 210], "diem_do": 0.9})
        nho = cc._diem_chat_luong(anh, {"hop": [10, 10, 55, 55], "diem_do": 0.9})
        self.assertGreater(to, nho)
        # Hộp hỏng thì chấm theo mỗi điểm dò, KHÔNG được ném lỗi làm hỏng cả lượt
        self.assertGreater(cc._diem_chat_luong(anh, {"hop": None, "diem_do": 0.8}), 0)

    def test_chon_dai_dien_lay_khung_DIEM_CAO_NHAT_cua_moi_nguoi(self):
        a = np.zeros((10, 10, 3), np.uint8)
        xau = self._m("quen", _vec(1), ten="Việt", nguoi_id="n1", do_giong=60)
        tot = self._m("quen", _vec(1), ten="Việt", nguoi_id="n1", do_giong=90)
        ra = cc._chon_dai_dien([(0.2, xau, a), (0.9, tot, a)], dong_thuan=2)
        self.assertEqual(len(ra), 1)
        self.assertEqual(ra[0][0]["do_giong"], 90)
        self.assertEqual(ra[0][0]["loai"], "quen")      # đủ 2 lần nhìn → giữ «quen»

    def test_THIEU_DONG_THUAN_thi_ha_tu_QUEN_xuong_CO_THE(self):
        """Một khung ăn may vượt ngưỡng không đủ để khẳng định tên ai."""
        a = np.zeros((10, 10, 3), np.uint8)
        m = self._m("quen", _vec(1), ten="Việt", nguoi_id="n1", do_giong=80)
        ra = cc._chon_dai_dien([(0.9, m, a)], dong_thuan=2)
        self.assertEqual(ra[0][0]["loai"], "co_the")
        self.assertEqual(m["loai"], "quen")            # không sửa vào dict gốc

    def test_MOT_nguoi_la_qua_NHIEU_KHUNG_chi_thanh_MOT_dai_dien(self):
        """Không gom thì một người đi qua đẻ ra năm cụm mặt lạ."""
        a = np.zeros((10, 10, 3), np.uint8)
        ds = [(0.3 + i / 10, self._m("la", _vec(5)), a) for i in range(5)]
        self.assertEqual(len(cc._chon_dai_dien(ds, dong_thuan=2)), 1)

    def test_HAI_nguoi_la_KHAC_nhau_thi_van_tach_lam_hai(self):
        """Gom chung hết thành một là gộp nhầm hai người khách cùng đứng."""
        a = np.zeros((10, 10, 3), np.uint8)
        ds = [(0.5, self._m("la", _vec(2)), a), (0.6, self._m("la", _vec(9)), a)]
        self.assertEqual(len(cc._chon_dai_dien(ds, dong_thuan=2)), 2)

    def test_khong_tich_nhan_nao_thi_chi_tim_NGUOI(self):
        """Mặc định phải là «person» — nhãn khác là thứ người dùng chủ động thêm."""
        self.assertEqual(cc._nhan_canh({}), {"person"})
        self.assertEqual(cc._nhan_canh({"nhan": []}), {"person"})
        self.assertEqual(cc._nhan_canh({"nhan": ["dog", "  cat  ", ""]}), {"dog", "cat"})

    def test_bao_thay_vat_GOP_theo_phien_khong_bao_moi_vong_quet(self):
        """Không gộp thì con mèo nằm trong khung sinh một tin mỗi 2 giây."""
        c = cc.cfg()
        cc._bao_vat("Cam cửa", {"dog"}, self.gio[0], c)
        cc._bao_vat("Cam cửa", {"dog"}, self.gio[0] + 60, c)        # cùng phiên
        vat = [g for g in self.gui if g[0] == "camera.thay_vat"]
        self.assertEqual(len(vat), 1)
        self.assertIn("chó", vat[0][1])                              # tên tiếng Việt
        cc._bao_vat("Cam cửa", {"dog"}, self.gio[0] + 11 * 60, c)   # quá 10 phút
        self.assertEqual(len([g for g in self.gui if g[0] == "camera.thay_vat"]), 2)

    def test_khoa_thay_vat_co_trong_so_dang_ky_thong_bao(self):
        """Khoá lạ thì `thong_bao.gui` nuốt mất — phải đăng ký mới gửi được."""
        from services import thong_bao

        self.assertIn("camera.thay_vat", {s.khoa for s in thong_bao.SU_KIEN})


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
                              ("post", "/api/nhin-nha/mat-la/x/thoi-hoi"),
                              ("post", "/api/nhin-nha/mat-la/x/dat-ten"),
                              ("post", "/api/nhin-nha/nguoi/x/doi-ten"),
                              ("post", "/api/nhin-nha/mat/x/chuyen"),
                              ("post", "/api/nhin-nha/su-kien/1/chuyen")):
            # POST nào nhận `body: dict` thì thiếu body là FastAPI trả 422 ở bước
            # kiểm dữ liệu, TRƯỚC khi `require_admin` kịp chạy — tức bài test sẽ
            # không đo cổng quyền nữa mà đo bộ kiểm body. Gửi body rỗng hợp lệ để
            # thứ bị đo đúng là cổng quyền. (Route không nhận body thì bỏ qua nó.)
            kw = {"json": {}} if phuong == "post" else {}
            self.assertIn(getattr(c, phuong)(duong, **kw).status_code, (401, 403), duong)


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

    def test_tran_anh_lich_su_tinh_theo_TUNG_TAB_khong_phai_toan_cuc(self):
        """Lượt của người quen KHÔNG được mất ảnh chỉ vì người lạ đi qua nhiều.

        Đo thật 17/09/2026: 100 trong 111 lượt là «không nhận ra ai», nên trần
        toàn cục làm 3 lượt người quen mất ảnh — đúng tab dùng để soi nhận nhầm.
        """
        from api import nhin_nha as api_nn

        gio = self.gio[0]
        # Lượt của người quen là CŨ NHẤT; sau nó là một đống lượt người lạ mới hơn.
        self.sm.ghi_su_kien("Cam cửa", "yolo", "quen", nguoi_id="ng1",
                            anh="http://x/images/a.jpg", ts=gio - 9999)
        for i in range(api_nn.TOI_DA_ANH_SU_KIEN + 5):
            self.sm.ghi_su_kien("Cam cửa", "yolo", "la", mat_la_id="cum1",
                                anh="http://x/images/b.jpg", ts=gio - i)
        with mock.patch("time.time", lambda: gio), \
             mock.patch.object(api_nn, "_anh_su_kien", lambda u: "ANH" if u else ""):
            ds = self.client.get("/api/nhin-nha/su-kien?so_gio=24").json()["su_kien"]
        quen = [s for s in ds if s["nguoi_id"] == "ng1"]
        la = [s for s in ds if not s["nguoi_id"]]
        self.assertEqual(len(quen), 1)
        self.assertEqual(quen[0]["anh_nho"], "ANH")       # tab người quen vẫn có ảnh
        self.assertEqual(sum(1 for s in la if s["anh_nho"]), api_nn.TOI_DA_ANH_SU_KIEN)
        # URL nội bộ (127.0.0.1) không được lọt ra web — bấm vào chỉ báo lỗi.
        self.assertFalse(any("anh" in s for s in ds))

    def test_chuyen_mat_nham_sang_dung_nguoi_qua_tuyen_web(self):
        """Đi qua HTTP thật, không gọi thẳng hàm: route, quyền và hình dạng trả về
        đều là chỗ hỏng được mà test mức dịch vụ không thấy."""
        import cv2

        class _May:
            bo = self.nn.bo_mat()

            def do(self_may, anh, nguong=0.5):
                from services import khuon_mat_nha as km
                return [km.Mat((100.0, 100.0, 260.0, 300.0), 0.9, None)]

            def vector(self_may, anh, m):
                m.vector = _vec(3)
                return m.vector

        _ok, buf = cv2.imencode(".jpg", np.full((480, 640, 3), 120, np.uint8))
        with mock.patch.object(self.nn, "mat", lambda: _May()):
            self.assertTrue(self.client.post(
                "/api/nhin-nha/day", data={"ten": "Lan"},
                files={"anh": ("a.jpg", buf.tobytes(), "image/jpeg")}).json()["ok"])
        # Web phải nhận được MÃ của từng ảnh mặt, không chỉ ảnh — không có mã thì
        # nhìn thấy ảnh sai cũng không trỏ vào nó mà sửa được.
        ds = self.client.get("/api/nhin-nha/nguoi").json()["nguoi"]
        self.assertEqual(len(ds[0]["mat_ds"]), 1)
        self.assertEqual(ds[0]["mat_ds"][0]["nguon"], "web")
        mat_id = ds[0]["mat_ds"][0]["id"]

        d = self.client.post(f"/api/nhin-nha/mat/{mat_id}/chuyen", json={"ten": "Việt"}).json()
        self.assertTrue(d["ok"], d)
        self.assertTrue(d["nguoi_moi"])
        theo_ten = {n["ten"]: n for n in self.client.get("/api/nhin-nha/nguoi").json()["nguoi"]}
        self.assertEqual(theo_ten["Việt"]["so_mat"], 1)
        self.assertEqual(theo_ten["Lan"]["so_mat"], 0)   # người cũ còn đó, chỉ hết ảnh
        loi = self.client.post("/api/nhin-nha/mat/khong-co/chuyen", json={"ten": "X"}).json()
        self.assertFalse(loi["ok"])
        self.assertIn("khong-co", loi["error"])

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
