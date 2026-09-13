"""Test tầng thói quen — chặng 2: bot ĐỌC THÓI QUEN bật/tắt từ số đo.

Mỗi ca khoá một quyết định nêu lý do trong `services/thoi_quen_nha.py` (phần
"Chặng 2"): ba bẫy của tầng học (không rò rỉ tương lai, có mẫu âm, bỏ do_ai=1),
kiểm bài tại biên, và luật đọc lại để một thói quen không thành câu hỏi mỗi ngày.
"""

from __future__ import annotations

import json
import sqlite3
import time
import unittest
from tempfile import TemporaryDirectory
from unittest import mock

from test.test_hieu_thiet_bi_nha import _nap

#: Mốc tròn ô 30 phút, xa hiện tại để mọi ô nằm trong cửa sổ đo.
_O = 1800
_GOC = (int(time.time()) // _O - 200) * _O


class DocThoiQuenTest(unittest.TestCase):
    def setUp(self) -> None:
        import services.thoi_quen_nha as tq

        self._tmp = TemporaryDirectory()
        self.ht, self.bc, self.ls = _nap(self._tmp.name)
        self.tq = tq
        mqtt = self.ls.config.data.setdefault("mqtt", {})
        mqtt["lich_su"] = {"bat": True}
        mqtt["hieu_thiet_bi"] = {"bat": True}
        self.ls._db()

    def tearDown(self) -> None:
        self.ht._reset_for_tests()
        self.ls._reset_for_tests()
        self.bc._reset_for_tests()
        self._tmp.cleanup()

    def _sk(self, tb: str, gt: str, ts: float, *, do_ai: int = 0, truong: str = "state") -> None:
        with self.ls._khoa_db:
            conn = self.ls._db()
            conn.execute("INSERT INTO su_kien (ts, nguon, thiet_bi, truong, gia_tri, gia_tri_cu,"
                         " do_ai, gio, thu) VALUES (?,?,?,?,?,?,?,12,1)",
                         (ts, "ha", tb, truong, gt, "", do_ai))
            conn.commit()

    def _sd(self, tb: str, ts: float, gt: float) -> None:
        with self.ls._khoa_db:
            conn = self.ls._db()
            conn.execute("INSERT INTO so_do (o_5p, thiet_bi, truong, nho, lon, tb, n)"
                         " VALUES (?,?,?,?,?,?,1)", (int(ts // 300), tb, "state", gt, gt, gt))
            conn.commit()

    def _ro(self) -> sqlite3.Connection:
        ro = sqlite3.connect(f"file:{self.ls._DB_PATH}?mode=ro", uri=True)
        self.addCleanup(ro.close)
        return ro

    # ── ba bẫy ─────────────────────────────────────────────────────────────
    def test_bat_tat_chi_tinh_NGUOI_lam_va_bo_qua_mat_ket_noi(self) -> None:
        g = _GOC
        for ts, gt, ai in ((g, "off", 0), (g + 60, "on", 0),          # người bật
                           (g + 120, "off", 1),                         # BOT tắt
                           (g + 180, "unavailable", 0), (g + 240, "on", 0),  # mất kết nối rồi về
                           (g + 300, "off", 0)):                        # người tắt
            self._sk("light.a", gt, ts, do_ai=ai)
        bat, tat, ts_ds, _ = self.tq._bat_tat(self._ro(), "light.a", g - 10, g + 1000)
        self.assertEqual(bat, [g + 60])
        self.assertEqual(tat, [g + 300], "bot tắt không phải thói quen; on sau unavailable không phải bật")
        self.assertEqual(len(ts_ds), 6, "dòng trạng thái vẫn giữ lần bot làm — đèn bot tắt thì vẫn đang tắt")

    def test_gia_tri_truoc_luc_bat_KHONG_lay_o_so_do_chua_khep(self) -> None:
        """Đèn vừa bật làm sáng chính ô 5 phút chứa lần bật — lấy ô đó là rò rỉ tương lai."""
        bat = _GOC + 150                       # giữa ô 5 phút [GOC, GOC+300)
        self._sd("sensor.lux", _GOC - 300, 3.0)   # ô trước, đã khép lúc GOC
        self._sd("sensor.lux", _GOC, 400.0)       # ô chứa lần bật, khép lúc GOC+300
        ts, gt = self.tq._tuyen(self._ro(), "sensor.lux", "state", _GOC - 3600, _GOC + 3600)
        self.assertEqual(self.tq._truoc(ts, gt, bat), "3")
        self.assertEqual(self.tq._truoc(ts, gt, _GOC + 300), "3", "cùng mốc khép ô cũng chưa được lấy")
        self.assertEqual(self.tq._truoc(ts, gt, _GOC + 301), "400")

    def test_mau_am_la_o_DANG_TAT_ma_khong_ai_bat_va_bo_o_chi_co_bot(self) -> None:
        g = _GOC
        self._sk("light.a", "off", g - 10)
        self._sk("light.a", "on", g + _O + 60)              # ô 1: người bật
        self._sk("sensor.x", "1", g + 5)                     # ô 0: nhà có động, đèn tắt → nền bật
        self._sk("sensor.x", "2", g + 2 * _O + 5, do_ai=1)   # ô 2: chỉ bot làm → không tính
        self._sk("sensor.x", "3", g + 3 * _O + 5)            # ô 3: đèn đang bật → nền tắt
        ro = self._ro()
        o_nha = self.tq._o_nha(ro, g - 60, g + 4 * _O)
        do = self.tq.do_thoi_quen(ro, "light.a", [], tu=g - 60, den=g + 4 * _O, o_nha=o_nha)
        self.assertEqual((do["o_bat"], do["nen_bat"], do["o_tat"], do["nen_tat"]), (1, 1, 0, 1))

    def test_so_do_ngoai_vi_dat_luc_bat_CANH_nen(self) -> None:
        g = _GOC
        self._sk("light.a", "off", g - 10)
        self._sk("binary_sensor.co_nguoi", "off", g - 5)
        for i in range(4):                                   # 4 ô nền: không người, đèn tắt
            self._sk("sensor.x", "1", g + i * _O + 5)
        self._sk("binary_sensor.co_nguoi", "on", g + 4 * _O + 30)
        self._sk("light.a", "on", g + 4 * _O + 60)           # ô 4: có người rồi bật
        ro = self._ro()
        tu, den = g - 60, g + 5 * _O
        do = self.tq.do_thoi_quen(ro, "light.a", [{"ma": "binary_sensor.co_nguoi", "ten": "Có người",
                                                   "vai_tro": "hien_dien"}],
                                  tu=tu, den=den, o_nha=self.tq._o_nha(ro, tu, den))
        nv = do["ngoai_vi"]["binary_sensor.co_nguoi"]
        self.assertEqual((nv["bat"], nv["nen_bat"]), ("on 100%, n=1", "off 100%, n=4"))
        self.assertEqual(nv["gia_tri"], ["off", "on"])
        de = self.tq.de_thoi_quen(do, ["THIẾT BỊ: light.a"], self.tq._pham_vi(self.tq._o_nha(ro, tu, den)))
        self.assertIn("binary_sensor.co_nguoi | Có người | hien_dien | trạng thái | on 100%, n=1", de)
        self.assertNotIn("10% trước", de, "giờ các lần bật mà không có nền là thiếu mẫu âm")

    # ── kiểm bài ───────────────────────────────────────────────────────────
    DO = {"ngoai_vi": {"binary_sensor.p": {"kieu": "trạng thái", "gia_tri": ["off", "on"]},
                       "sensor.lux": {"kieu": "số đo", "gia_tri": []}}}

    def _bai(self, bat: list, tat: list | None = None) -> dict:
        return {"bat": {"thoi_quen": "tối có người thì bật", "dieu_kien": bat},
                "tat": {"thoi_quen": "", "dieu_kien": tat or []}, "chac": 0.7, "vi_sao": "x"}

    def test_kiem_nhan_bai_dung(self) -> None:
        kq = self.tq.kiem_thoi_quen(self._bai([
            {"ma": "binary_sensor.p", "la": "on"}, {"ma": "sensor.lux", "duoi": 30},
            {"ma": "gio", "tu": "18:00", "den": "24:00"}],
            [{"ma": "gio", "tu": "06:00", "den": "09:00"}, {"ma": "gio", "tu": "21:00", "den": "24:00"}]),
            self.DO)
        self.assertEqual(kq["bat"]["dieu_kien"][1], {"ma": "sensor.lux", "duoi": 30.0})
        self.assertEqual(len(kq["tat"]["dieu_kien"]), 2, "hai khoảng giờ rời nhau là hợp lệ (HOẶC)")

    def test_kiem_loai_bai_pham_luat(self) -> None:
        for bat, ly_do in (
                ([{"ma": "sensor.bia", "tren": 1}], "mã không có trong đề"),
                ([{"ma": "binary_sensor.p", "la": "detected"}], "giá trị trạng thái chưa từng thấy"),
                ([{"ma": "sensor.lux", "la": "tối"}], "số đo không có ngưỡng"),
                ([{"ma": "sensor.lux", "duoi": 30, "tren": 5}], "hai ngưỡng"),
                ([{"ma": "sensor.lux", "duoi": True}], "ngưỡng kiểu bool"),
                ([{"ma": "sensor.lux", "duoi": "30"}], "ngưỡng là chuỗi"),
                ([{"ma": "gio", "tu": "24:00", "den": "06:00"}], "24:00 chỉ làm mốc cuối"),
                ([{"ma": "gio", "tu": "18h", "den": "23:00"}], "giờ sai dạng"),
                ([{"ma": "ngay", "la": "thu_bay"}], "ngày lạ"),
                ([{"ma": "binary_sensor.p", "la": "on"}] * 2, "mã lặp"),
                ([{"ma": "gio", "tu": "0%d:00" % i, "den": "0%d:30" % i} for i in range(4)], "quá 3")):
            with self.subTest(ly_do):
                self.assertIsInstance(self.tq.kiem_thoi_quen(self._bai(bat), self.DO), str)
        self.assertIsInstance(self.tq.kiem_thoi_quen({"bat": {"dieu_kien": []}}, self.DO), str)

    # ── lưu sổ và đọc lại ──────────────────────────────────────────────────
    def _ket_luan(self, **doi) -> dict:
        k = {"ma_hoc": "switch.bep_left", "chac": 0.8, "vi_sao": "có người thì bật",
             "bat": {"thoi_quen": "Bật khi bếp có người, chiều tối",
                     "dieu_kien": [{"ma": "binary_sensor.p", "la": "on"},
                                   {"ma": "gio", "tu": "15:00", "den": "24:00"},
                                   {"ma": "gio", "tu": "06:00", "den": "09:00"}]},
             "tat": {"thoi_quen": "Chưa rõ", "dieu_kien": []},
             "ngoai_vi": ["binary_sensor.p"], "ten_ngoai_vi": {"binary_sensor.p": "Hiện diện bếp"}}
        k.update(doi)
        return k

    def test_cau_hoi_doc_duoc_va_viet_lai_chu_khong_hoi_lai(self) -> None:
        lan = self.ht._ghi_lan("b", "m", 1, 1, 0, 0, "", viec="thoi_quen")
        ghi = self.ht.ghi_thoi_quen(lan, [self._ket_luan()])
        self.assertEqual(len(ghi["moi"]), 1)
        d = next(x for x in self.ht.dang_hieu_luc() if x["id"] == ghi["moi"][0]["id"])
        cau = self.ht._cau_doc(d, {"switch.bep_left": "Đèn bếp"})
        self.assertEqual(cau, "Đèn bếp [switch] — bật: Bật khi bếp có người, chiều tối (khi trong "
                              "15:00–24:00 hoặc 06:00–09:00, Hiện diện bếp là on); "
                              "tắt: Chưa rõ (không điều kiện)")
        khac_chu = self._ket_luan(bat={**self._ket_luan()["bat"], "thoi_quen": "Viết khác đi"})
        self.assertEqual(self.ht.ghi_thoi_quen(lan, [khac_chu])["moi"], [],
                         "điều kiện y hệt thì lời văn khác không thành câu hỏi mới")

    def test_luot_HIEU_THIET_BI_hang_ngay_KHONG_xoa_ket_luan_thoi_quen(self) -> None:
        self.ht.ghi_thoi_quen(self.ht._ghi_lan("b", "m", 1, 1, 0, 0, ""), [self._ket_luan()])
        g = {"ma": ["switch.bep_left"], "ma_hoc": "switch.bep_left", "nguon_nhanh": "",
             "loai": "bat_tat", "hoc": True, "chac": 0.9, "vi_sao": "", "dieu_kien": ["buoi"]}
        self.ht.ghi_ket_qua(self.ht._ghi_lan("b", "m", 1, 1, 0, 0, ""), [g])
        self.assertEqual(len([d for d in self.ht.dang_hieu_luc() if d["loai_cau_hoi"] == "thoi_quen"]), 1)

    def test_doc_lai_khi_chua_co_bi_cham_sai_doi_ngoai_vi_hoac_da_cu(self) -> None:
        now = time.time()
        nv = {"ngoai_vi": [{"ma": "binary_sensor.p"}]}
        cu = {"ket_qua": "cho", "ts": now - 86400, "nhom": {"ngoai_vi": ["binary_sensor.p"], "doc_luc": now}}
        self.assertTrue(self.tq._can_doc_lai(nv, None, now))
        self.assertFalse(self.tq._can_doc_lai(nv, cu, now))
        self.assertTrue(self.tq._can_doc_lai(nv, {**cu, "ket_qua": "sai"}, now))
        self.assertTrue(self.tq._can_doc_lai({"ngoai_vi": [{"ma": "sensor.lux"}]}, cu, now))
        self.assertTrue(self.tq._can_doc_lai(nv, cu, now + self.tq._DOC_LAI_SAU_GIAY + 1))

    def test_doc_goi_bot_kiem_bai_va_bo_ngoai_vi_HA_da_vang(self) -> None:
        """Ngoại vi HA không còn trong `get_states` (mang mật khẩu, hoặc chủ máy đã bỏ)
        thì không bày; bài phạm luật thì vào `loi`, không vào kết luận."""
        g = _GOC
        self._sk("light.a", "off", g - 10)
        self._sk("light.a", "on", g + 60)
        self._sk("binary_sensor.p", "on", g + 30)
        self._sk("light.b", "off", g - 10)
        nv_hoc = {"light.a": {"khu_vuc": "Bếp", "ngoai_vi": [
                      {"ma": "binary_sensor.p", "ten": "P", "vai_tro": "hien_dien"},
                      {"ma": "camera.vang", "ten": "vắng", "vai_tro": "khac"}]},
                  "light.b": {"khu_vuc": "", "ngoai_vi": []}}
        de_da_gui: list[str] = []

        def _goi(model: str, huong: str, de: str) -> dict:
            de_da_gui.append(de)
            bai = ({"bat": {"thoi_quen": "có người thì bật",
                            "dieu_kien": [{"ma": "binary_sensor.p", "la": "on"}]},
                    "tat": {"thoi_quen": "", "dieu_kien": []}, "chac": 0.6, "vi_sao": ""}
                   if "light.a" in de else {"bat": {"dieu_kien": [{"ma": "bia"}]}})
            return {"choices": [{"message": {"content": json.dumps(bai, ensure_ascii=False)}}]}

        with mock.patch.object(self.ht, "ngoai_vi_hoc", return_value=nv_hoc), \
             mock.patch("services.ha_client.get_states", return_value=[
                 {"entity_id": e} for e in ("light.a", "light.b", "binary_sensor.p")]), \
             mock.patch.object(self.ht, "huong_dan", return_value=("hd", "ban")), \
             mock.patch.object(self.ht, "_model", return_value="m"), \
             mock.patch.object(self.ht, "_goi_model", side_effect=_goi):
            kq = self.tq.doc()
        self.assertEqual([k["ma_hoc"] for k in kq["ket_luan"]], ["light.a"])
        self.assertEqual(kq["ket_luan"][0]["ngoai_vi"], ["binary_sensor.p"])
        self.assertEqual([x["ma"] for x in kq["loi"]], ["light.b"])
        self.assertTrue(all("camera.vang" not in d for d in de_da_gui))

    def test_chay_mot_lan_ghi_luot_thoi_quen_va_bao_chung_mot_tin(self) -> None:
        kq_nv = {"phien_ban": "b1", "model": "m", "so_thiet_bi": 1, "ket_luan": [], "loi": []}
        kq_tq = {"phien_ban": "b2", "model": "m", "so_thiet_bi": 1, "ket_luan": [self._ket_luan()],
                 "loi": []}
        with mock.patch.object(self.tq, "giai", return_value=kq_nv), \
             mock.patch.object(self.tq, "doc", return_value=kq_tq), \
             mock.patch.object(self.ht, "bao_nhom", return_value=1) as bao, \
             mock.patch.object(self.ht, "_ten_ha", return_value={}):
            kq = self.tq.chay_mot_lan()
        self.assertEqual(kq["thoi_quen"]["moi"], 1)
        tin = bao.call_args[0][0]
        self.assertIn("đọc thói quen bật/tắt cho 1 thiết bị", tin)
        self.assertNotIn("chọn khu vực", tin, "ngoại vi không đổi thì không kể")
        self.assertFalse(self.ht.co_du_kien_moi("thoi_quen"))


if __name__ == "__main__":
    unittest.main()
