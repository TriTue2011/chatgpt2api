"""Endpoint `api/thong_bao.py` — Cài đặt → Thông báo.

Mỗi endpoint chỉ ghi đúng mục ``thong_bao``, KHÔNG POST cả khối config. Đây là
bẫy #9 của kho này: thẻ Cài đặt cũ gửi nguyên cả config lên, nên thẻ nạp dữ liệu
cũ ghi đè phần của thẻ khác — đã có lần mất ``du_doan.kenh_nhan`` đúng theo kiểu
đó. Trang Thông báo sinh ra để gom cài đặt về MỘT nơi, nên nó càng không được
lặp lại chính cái bẫy ấy.

Không đụng vào `services.config` thật: nó là singleton dùng chung cả tiến trình,
test nào sửa mà không trả lại nguyên trạng thì test chạy sau trong cùng lô đọc
phải giá trị giả.
"""

from __future__ import annotations

import pathlib
import unittest
from unittest import mock


class _Cfg:
    """Config giả — gộp NÔNG đúng như `config.update` thật (config.py:1355)."""

    def __init__(self, data: dict | None = None) -> None:
        self.data = data or {}

    def update(self, d: dict) -> dict:
        self.data.update(d)
        return self.data

    def get(self) -> dict:
        return self.data


def _app(cfg: _Cfg):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api import thong_bao as api_tb
    from services import thong_bao as tb

    app = FastAPI()
    app.include_router(api_tb.create_router())
    bo_qua = mock.patch("api.thong_bao.require_admin", lambda *a, **k: None)
    bo_qua.start()
    vá = mock.patch.object(tb, "config", cfg)
    vá.start()
    return TestClient(app), (bo_qua, vá)


class _Nen(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = _Cfg()
        self.client, self._va = _app(self.cfg)
        for v in self._va:
            self.addCleanup(v.stop)


class DanhSachTests(_Nen):
    def test_tra_du_so_dang_ky(self) -> None:
        d = self.client.get("/api/thong-bao").json()
        self.assertTrue(d["ok"])
        khoa = {x["khoa"] for x in d["su_kien"]}
        for k in ("nha.khoa_cua.hoi_ten", "nha.khoa_cua.mo_khuya",
                  "nha.khoa_cua.tom_tat", "he_thong.loi", "tai_khoan.log",
                  "tai_khoan.cap_nhat", "chat.moi"):
            self.assertIn(k, khoa)

    def test_moi_dong_du_thong_tin_de_dung_bang(self) -> None:
        d = self.client.get("/api/thong-bao").json()
        for x in d["su_kien"]:
            for truong in ("khoa", "nhan", "mo_ta", "nhom", "bat", "kenh"):
                self.assertIn(truong, x)

    def test_chua_khai_thi_tat_va_khong_co_kenh(self) -> None:
        """"Không mặc định": chưa cài thì không có kênh nào cả."""
        d = self.client.get("/api/thong-bao").json()
        for x in d["su_kien"]:
            self.assertFalse(x["bat"])
            self.assertEqual(x["kenh"], [])


class LuuTests(_Nen):
    def test_ghi_dung_muc_thong_bao(self) -> None:
        r = self.client.post("/api/thong-bao/luu", json={"muc": {
            "he_thong.loi": {"bat": True, "kenh": ["zalo:194:abc"]}}}).json()
        self.assertTrue(r["ok"])
        self.assertEqual(self.cfg.data["thong_bao"]["he_thong.loi"],
                         {"bat": True, "kenh": ["zalo:194:abc"]})

    def test_KHONG_dung_vao_khoa_khac(self) -> None:
        """Bẫy #9: lưu một thứ không được làm mất thứ khác."""
        self.cfg.data["mqtt"] = {"du_doan": {"kenh_nhan": ["zalop:475:313"]}}
        self.cfg.data["zalo_bots"] = [{"enabled": True}]
        self.client.post("/api/thong-bao/luu", json={"muc": {
            "nha.goi_y": {"bat": True, "kenh": ["zalo:194:abc"]}}})
        self.assertEqual(self.cfg.data["mqtt"],
                         {"du_doan": {"kenh_nhan": ["zalop:475:313"]}})
        self.assertEqual(self.cfg.data["zalo_bots"], [{"enabled": True}])

    def test_thieu_muc_thi_bao_loi(self) -> None:
        r = self.client.post("/api/thong-bao/luu", json={}).json()
        self.assertFalse(r["ok"])

    def test_khoa_la_bi_bo(self) -> None:
        self.client.post("/api/thong-bao/luu", json={"muc": {
            "khoa.bia.dat": {"bat": True, "kenh": ["zalo:1:2"]}}})
        self.assertNotIn("khoa.bia.dat", self.cfg.data.get("thong_bao", {}))


class GuiThuTests(_Nen):
    def test_chua_chon_kenh_thi_noi_RO_ly_do(self) -> None:
        self.cfg.data["thong_bao"] = {"he_thong.loi": {"bat": True, "kenh": []}}
        r = self.client.post("/api/thong-bao/thu",
                             json={"khoa": "he_thong.loi"}).json()
        self.assertFalse(r["ok"])
        self.assertIn("chưa chọn kênh", r["error"])

    def test_dang_tat_thi_noi_dang_tat(self) -> None:
        self.cfg.data["thong_bao"] = {"he_thong.loi": {"bat": False,
                                                       "kenh": ["zalo:1:2"]}}
        r = self.client.post("/api/thong-bao/thu",
                             json={"khoa": "he_thong.loi"}).json()
        self.assertFalse(r["ok"])
        self.assertIn("đang tắt", r["error"])

    def test_co_kenh_thi_gui_that(self) -> None:
        self.cfg.data["thong_bao"] = {"nha.khoa_cua.hoi_ten":
                                      {"bat": True, "kenh": ["zalop:475:313"]}}
        with mock.patch("services.digest.send_targets", return_value=1) as g:
            r = self.client.post("/api/thong-bao/thu",
                                 json={"khoa": "nha.khoa_cua.hoi_ten"}).json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["gui"], 1)
        self.assertEqual(g.call_args[0][0], ["zalop:475:313"])

    def test_thieu_khoa_thi_bao_loi(self) -> None:
        r = self.client.post("/api/thong-bao/thu", json={}).json()
        self.assertFalse(r["ok"])


class DaGanVaoUngDungTests(unittest.TestCase):
    """Route viết xong mà không ai gắn thì nhìn như đủ mà gọi không tới."""

    GOC = pathlib.Path(__file__).resolve().parents[1]

    def test_router_co_du_ba_duong(self) -> None:
        from api.thong_bao import create_router

        duong = {getattr(r, "path", "") for r in create_router().routes}
        self.assertIn("/api/thong-bao", duong)
        self.assertIn("/api/thong-bao/luu", duong)
        self.assertIn("/api/thong-bao/thu", duong)

    def test_da_gan_trong_api_app(self) -> None:
        src = (self.GOC / "api" / "app.py").read_text("utf-8")
        self.assertIn("thong_bao.create_router()", src)
        # Tìm ĐÚNG dòng `from api import …`, KHÔNG neo vào số dòng: thêm một
        # import phía trên là phép đo gãy oan, trong khi thứ cần khoá vẫn đúng.
        dong_import = next(d for d in src.splitlines()
                           if d.startswith("from api import "))
        self.assertIn("thong_bao", dong_import)


if __name__ == "__main__":
    unittest.main()
