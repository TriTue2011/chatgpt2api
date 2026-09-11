"""Test tầng hiểu thiết bị — code chỉ ĐO, bot GIẢI, người CHẤM.

Mỗi ca khoá một quyết định thiết kế đã nêu lý do trong `hieu_thiet_bi_nha.py`.
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_SO_DICH_VU = {"light": {"turn_on": {}}, "switch": {"turn_on": {}},
               "binary_sensor": {}, "sensor": {}}


def _nap(thu_muc: str):
    import services.boi_canh_nha as bc
    import services.du_doan_nha as dd
    import services.hieu_thiet_bi_nha as ht
    import services.lich_su_nha as ls

    ls._reset_for_tests()
    ls._DB_PATH = Path(thu_muc) / "lich_su_nha.sqlite"
    ls._conn = None
    dd._reset_for_tests()
    dd._DB_PATH = Path(thu_muc) / "du_doan_nha.sqlite"
    ht._reset_for_tests()
    ht._DB_PATH = Path(thu_muc) / "hieu_thiet_bi_nha.sqlite"
    bc._reset_for_tests()
    return ht, bc, ls


class HieuThietBiNhaTest(unittest.TestCase):
    def setUp(self) -> None:
        from services import ha_client

        self._tmp = TemporaryDirectory()
        self.ht, self.bc, self.ls = _nap(self._tmp.name)
        mqtt = self.ls.config.data.setdefault("mqtt", {})
        mqtt["lich_su"] = {"bat": True}
        mqtt["hieu_thiet_bi"] = {"bat": True}
        mqtt["du_doan"] = {"bat": True, "kenh_nhan": ["zalop:acc:nhom"]}
        mqtt["bai_hoc"] = {}
        huong = Path(self._tmp.name) / "hoc_hoi" / "hieu_thiet_bi.md"
        for p in (mock.patch.object(self.ht, "_duong_huong_dan", return_value=huong),
                  mock.patch.object(ha_client, "get_service_catalog",
                                    return_value=_SO_DICH_VU),
                  mock.patch.object(ha_client, "get_states", return_value=[
                      {"entity_id": "switch.bep_left",
                       "attributes": {"friendly_name": "Đèn bếp"}},
                      {"entity_id": "light.bep_left",
                       "attributes": {"friendly_name": "Đèn bếp"}}]),
                  mock.patch.object(self.bc, "phong_cua", return_value="Bếp")):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self) -> None:
        self.ht._reset_for_tests()
        self.ls._reset_for_tests()
        self.bc._reset_for_tests()
        self._tmp.cleanup()

    def _sk(self, thiet_bi: str, gt: str, ts: float, truong: str = "state",
            nguon: str = "", do_ai: int = 0) -> None:
        nguon = nguon or ("mqtt" if "/" in thiet_bi else "ha")
        with self.ls._khoa_db:
            conn = self.ls._db()
            conn.execute(
                "INSERT INTO su_kien (ts, nguon, thiet_bi, truong, gia_tri,"
                " gia_tri_cu, do_ai, gio, thu) VALUES (?,?,?,?,?,?,?,12,1)",
                (ts, nguon, thiet_bi, truong, gt, "", do_ai))
            conn.commit()

    def _den_bep(self, lan: int = 20) -> None:
        """Một bóng đèn hiện BA mã, đúng như nhà thật đo 11/09/2026: bản MQTT
        báo trước 3 ms, công tắc HA, rồi đèn bọc lại công tắc theo sau 50 ms."""
        goc = time.time() - lan * 600 - 60
        for i in range(lan):
            t = goc + i * 600
            gt = "on" if i % 2 == 0 else "off"
            self._sk("zigbee2mqtt/Bếp", gt.upper(), t - 0.003, truong="state_left")
            self._sk("switch.bep_left", gt, t)
            self._sk("light.bep_left", gt, t + 0.05)

    @staticmethod
    def _nhom_bep(**doi) -> dict:
        g = {"ma": ["light.bep_left", "switch.bep_left", "zigbee2mqtt/Bếp#state_left"],
             "ma_hoc": "switch.bep_left", "nguon_nhanh": "zigbee2mqtt/Bếp#state_left",
             "loai": "bat_tat", "hoc": True, "chac": 0.9,
             "vi_sao": "đổi cùng lúc 100% cả hai chiều"}
        g.update(doi)
        return g

    def _luu(self, *nhom: dict) -> dict:
        lan = self.ht._ghi_lan("ban_thu", "m", 3, len(nhom), 0, 0, "")
        return self.ht.ghi_ket_qua(lan, list(nhom))

    # ── code chỉ ĐO ────────────────────────────────────────────────────────
    def test_HO_SO_do_TRUNG_HAI_CHIEU_va_AI_DOI_TRUOC(self) -> None:
        """Bot nhận ra ba mã là một bóng đèn nhờ ĐỔI CÙNG LÚC ở cả hai chiều,
        và chọn nguồn nhanh nhờ biết AI ĐỔI TRƯỚC."""
        self._den_bep()
        theo = {x["ma"]: x for x in self.ht.ho_so(so_ngay=30)["thiet_bi"]}
        cong_tac = {k["ma"]: k for k in theo["switch.bep_left"]["doi_cung_luc"]}
        self.assertEqual(cong_tac["light.bep_left"]["ty_le_minh"], 1.0)
        self.assertEqual(cong_tac["light.bep_left"]["ty_le_ban"], 1.0)
        self.assertEqual(cong_tac["light.bep_left"]["minh_doi_truoc"], 1.0)
        self.assertEqual(cong_tac["zigbee2mqtt/Bếp#state_left"]["minh_doi_truoc"], 0.0,
                         "bản MQTT báo trước công tắc HA")
        self.assertIn("zigbee2mqtt/Bếp#state_left", theo,
                      "bản MQTT của công tắc phải vào đề — nó là nguồn nhanh")
        self.assertEqual(theo["zigbee2mqtt/Bếp#state_left"]["nguon"], {"mqtt": 20})
        self.assertTrue(theo["switch.bep_left"]["ha_bat_duoc"])
        self.assertEqual(theo["switch.bep_left"]["ten"], "Đèn bếp")

    def test_NGUON_MOI_GHI_chi_so_trong_luc_CA_HAI_cung_ghi(self) -> None:
        """Đo kho thật 11/09/2026: MQTT mới ghi 1,5 ngày, HA có 11,8 ngày. Chia
        cho mọi lần đổi của công tắc HA thì bản MQTT của chính nó chỉ "trùng
        9%" — bot sẽ tách một bóng đèn làm hai."""
        now = time.time()
        goc = now - 20 * 86400
        for i in range(40):
            t = goc + i * 43200
            gt = "on" if i % 2 == 0 else "off"
            self._sk("switch.bep_left", gt, t)
            if t > now - 3 * 86400:
                self._sk("zigbee2mqtt/Bếp", gt.upper(), t - 0.003, truong="state_left")
        theo = {x["ma"]: x for x in self.ht.ho_so(so_ngay=30)["thiet_bi"]}
        kem = {k["ma"]: k for k in theo["switch.bep_left"]["doi_cung_luc"]}
        self.assertGreaterEqual(kem["zigbee2mqtt/Bếp#state_left"]["ty_le_minh"], 0.9)
        self.assertGreaterEqual(kem["zigbee2mqtt/Bếp#state_left"]["ty_le_ban"], 0.9)

    def test_MA_DOI_MOT_LAN_luc_KHOI_DONG_khong_DAY_BAN_SAO_THAT_ra(self) -> None:
        """Đo kho thật 11/09/2026: cặp "Điều hòa ↔ Aptomat" rơi khỏi đề vì những
        mã chỉ đổi đúng một lần lúc HA khởi động lại "trùng 100%" ở chiều của
        chúng và chiếm hết năm chỗ."""
        self._den_bep()
        khoi_dong = time.time() - 20 * 600 - 60
        for k in range(6):
            self._sk(f"light.a_le_{k}", "on", khoi_dong + 0.01 * (k + 1))
        theo = {x["ma"]: x for x in self.ht.ho_so(so_ngay=30)["thiet_bi"]}
        kem = [k["ma"] for k in theo["switch.bep_left"]["doi_cung_luc"]]
        self.assertEqual(kem[:2], ["light.bep_left", "zigbee2mqtt/Bếp#state_left"])

    def test_BAT_CACH_NHAU_VAI_PHUT_khong_phai_CUNG_LUC(self) -> None:
        """Hai thứ hay bật cùng buổi là HAI thiết bị có thói quen đi kèm."""
        goc = time.time() - 20 * 86400
        for i in range(10):
            t = goc + i * 86400
            self._sk("light.nha_tam", "on", t)
            self._sk("switch.quat_nha_tam", "on", t + 300)
        theo = {x["ma"]: x for x in self.ht.ho_so(so_ngay=30)["thiet_bi"]}
        self.assertEqual(theo["light.nha_tam"]["doi_cung_luc"], [])

    def test_CAM_BIEN_khong_vao_de(self) -> None:
        """Học chỉ thứ bật tắt được — HA nói miền nào có lệnh bật, không phải code."""
        goc = time.time() - 5 * 86400
        for i in range(10):
            self._sk("binary_sensor.cua", "on", goc + i * 3600)
            self._sk("light.hien", "on", goc + i * 3600 + 900)
        ma = {x["ma"] for x in self.ht.ho_so(so_ngay=30)["thiet_bi"]}
        self.assertIn("light.hien", ma)
        self.assertNotIn("binary_sensor.cua", ma)

    def test_DOI_DONG_LOAT_duoc_DO_ra(self) -> None:
        """Mười hai công tắc đổi cùng giây — code đo ra con số, bot mới phán rác."""
        goc = time.time() - 5 * 86400
        for i in range(5):
            for k in range(12):
                self._sk(f"switch.cam_{k}", "on" if i % 2 == 0 else "off",
                         goc + i * 3600 + k * 0.01)
        theo = {x["ma"]: x for x in self.ht.ho_so(so_ngay=30)["thiet_bi"]}
        self.assertEqual(theo["switch.cam_0"]["so_ma_khac_doi_cung_luc"]["trung_vi"], 11)

    def test_HA_SAP_thi_KHONG_RA_DE_va_GIU_KET_LUAN_CU(self) -> None:
        """Không biết cái gì bật được thì không ra đề — học rỗng tệ hơn im."""
        from services import ha_client

        self._luu(self._nhom_bep())
        with mock.patch.object(ha_client, "get_service_catalog", return_value={}), \
             mock.patch.object(self.ht, "_goi_model") as goi:
            kq = self.ht.chay_mot_lan()
        self.assertIn("bo_qua", kq)
        goi.assert_not_called()
        self.assertEqual(self.ht.thiet_bi_hoc(), ["switch.bep_left"])

    # ── bot GIẢI, kiểm ở biên ──────────────────────────────────────────────
    def test_LOI_GOI_TACH_BIET_chi_co_HUONG_DAN(self) -> None:
        """Chủ máy chốt: "promt chỉ duy mình hướng dẫn để tránh nhiễu"."""
        import services.agent.runtime as rt

        with mock.patch.object(rt, "call_model", return_value={}) as cm:
            self.ht._goi_model("m", "HƯỚNG DẪN", "{}")
        tin = cm.call_args.args[1]
        self.assertEqual([m["role"] for m in tin], ["system", "user"])
        self.assertEqual(tin[0]["content"], "HƯỚNG DẪN")
        kw = cm.call_args.kwargs
        self.assertTrue(kw["no_smart_home"])
        self.assertEqual(kw["allowed_groups"], set())
        self.assertNotIn("tools", kw)

    def test_JSON_HONG_thi_GIU_KET_LUAN_CU(self) -> None:
        self._den_bep()
        self._luu(self._nhom_bep())
        tra = {"choices": [{"message": {"content": "xin lỗi em không biết"}}]}
        with mock.patch.object(self.ht, "_goi_model", return_value=tra) as goi, \
             mock.patch.object(self.ht, "_model", return_value="m"), \
             mock.patch.object(self.ht, "bao_nhom", return_value=1):
            kq = self.ht.chay_mot_lan()
        self.assertTrue(kq["loi"])
        huong, _ = self.ht.huong_dan()
        self.assertEqual(goi.call_args.args[1], huong, "system prompt CHỈ có hướng dẫn")
        self.assertEqual(self.ht.thiet_bi_hoc(), ["switch.bep_left"],
                         "lượt hỏng không được xoá kết luận cũ")

    def test_KIEM_BIEN_bo_MA_BIA_va_khong_cho_hoc_CAM_BIEN(self) -> None:
        """Nhóm phạm luật cứng thì LOẠI, không sửa hộ — sửa hộ là làm bài thay
        học trò, và lỗi sẽ không bao giờ lộ ra để sửa hướng dẫn."""
        phan = [{"ma": "switch.a", "ha_bat_duoc": True},
                {"ma": "binary_sensor.b", "ha_bat_duoc": False}]
        data = {"nhom": [
            {"ma": ["switch.a", "switch.bia"], "ma_hoc": "switch.a", "hoc": True,
             "loai": "bat_tat", "chac": 0.9},
            {"ma": ["switch.a"], "ma_hoc": "switch.a", "hoc": True, "loai": "bat_tat"},
            {"ma": ["binary_sensor.b"], "ma_hoc": "binary_sensor.b", "hoc": True,
             "loai": "bat_tat", "chac": 0.9}]}
        nhom, loai_bo = self.ht._kiem(data, phan)
        self.assertEqual([g["ma"] for g in nhom], [["switch.a"]])
        self.assertEqual(loai_bo, 2)

    def test_CHAY_TRON_VONG_voi_JSON_BOC_TRONG_KHOI_CODE(self) -> None:
        self._den_bep()

        def bot(model, huong, de):
            ma = [x["ma"] for x in json.loads(de)["thiet_bi"]]
            bai = {"nhom": [{"ma": ma, "ma_hoc": "switch.bep_left",
                             "nguon_nhanh": "zigbee2mqtt/Bếp#state_left",
                             "loai": "bat_tat", "hoc": True, "chac": 0.95,
                             "vi_sao": "đổi cùng lúc 100%"}]}
            return {"choices": [{"message": {
                "content": "```json\n" + json.dumps(bai, ensure_ascii=False) + "\n```"}}]}

        with mock.patch.object(self.ht, "_goi_model", side_effect=bot), \
             mock.patch.object(self.ht, "_model", return_value="m"), \
             mock.patch("services.digest.send_targets", return_value=1) as gui:
            kq = self.ht.chay_mot_lan()
        self.assertEqual(kq["loi"], "")
        self.assertEqual(kq["moi"], 3)
        self.assertEqual(gui.call_args.args[0], ["zalop:acc:nhom"])
        self.assertEqual(self.ht.thiet_bi_hoc(), ["switch.bep_left"])

    # ── sổ kết luận ────────────────────────────────────────────────────────
    def test_KET_LUAN_Y_HET_thi_KHONG_HOI_LAI(self) -> None:
        a = self._luu(self._nhom_bep())
        b = self._luu(self._nhom_bep(vi_sao="lý do khác"))
        self.assertEqual(sorted(d["loai_cau_hoi"] for d in a["moi"]),
                         ["cung_thiet_bi", "hoc", "nguon_nhanh"])
        self.assertEqual(b["moi"], [])

    def test_CHAM_SAI_thi_THOI_HOC_NGAY(self) -> None:
        moi = self._luu(self._nhom_bep())["moi"]
        hoc = next(d for d in moi if d["loai_cau_hoi"] == "hoc")
        self.assertEqual(self.ht.thiet_bi_hoc(), ["switch.bep_left"])
        self.assertTrue(self.ht.cham(hoc["id"], False, cham_boi="claude"))
        self.assertEqual(self.ht.thiet_bi_hoc(), [])
        self.assertFalse(self.ht.cham(hoc["id"], True, cham_boi="claude"),
                         "chấm hai lần không được cộng dồn")

    def test_GOP_SAI_thi_THOI_HOC_THEO_NHOM_DO(self) -> None:
        moi = self._luu(self._nhom_bep())["moi"]
        gop = next(d for d in moi if d["loai_cau_hoi"] == "cung_thiet_bi")
        self.ht.cham(gop["id"], False, cham_boi="chu_may")
        self.assertEqual(self.ht.thiet_bi_hoc(), [])

    def test_LAP_LAI_CAU_DA_SAI_thi_KHONG_DUNG_KHONG_HOI(self) -> None:
        """Bot lặp lại đúng câu từng sai là dấu hiệu hướng dẫn còn thiếu."""
        moi = self._luu(self._nhom_bep())["moi"]
        hoc = next(d for d in moi if d["loai_cau_hoi"] == "hoc")
        self.ht.cham(hoc["id"], False, cham_boi="claude")
        self._luu(self._nhom_bep(hoc=False, ma_hoc="", loai="khong_ro"))
        kq = self._luu(self._nhom_bep())
        self.assertEqual([d["loai_cau_hoi"] for d in kq["lap_lai"]], ["hoc"])
        self.assertNotIn("hoc", [d["loai_cau_hoi"] for d in kq["moi"]])
        self.assertEqual(self.ht.thiet_bi_hoc(), [])

    def test_BOT_BO_SOT_MA_thi_GIU_KET_LUAN_CU(self) -> None:
        """Bỏ sót không phải là đổi ý."""
        quat = {"ma": ["switch.quat"], "ma_hoc": "switch.quat", "nguon_nhanh": "",
                "loai": "bat_tat", "hoc": True, "chac": 0.8, "vi_sao": ""}
        self._luu(self._nhom_bep(), quat)
        self._luu(self._nhom_bep())
        self.assertEqual(self.ht.thiet_bi_hoc(), ["switch.bep_left", "switch.quat"])

    # ── thang tin cậy ──────────────────────────────────────────────────────
    def _cham_mot_cau(self, i: int, dung: bool) -> None:
        cau = {"ma": [f"switch.x{i}"], "ma_hoc": f"switch.x{i}", "nguon_nhanh": "",
               "loai": "bat_tat", "hoc": True, "chac": 0.9, "vi_sao": ""}
        self.ht.cham(self._luu(cau)["moi"][0]["id"], dung, cham_boi="claude")

    def test_CHUA_DU_50_LUOT_thi_CON_HOI(self) -> None:
        for i in range(49):
            self._cham_mot_cau(i, True)
        self.assertTrue(self.ht.can_hoi("hoc"))

    def test_DU_LUOT_DUNG_thi_THOI_HOI_roi_SAI_HAI_LAN_thi_HOI_LAI(self) -> None:
        """Chủ máy chốt: chính xác tăng dần thì bỏ dần câu hỏi — cùng thang
        `du_doan_nha.cap`, đường xuống nhạy hơn đường lên."""
        for i in range(60):
            self._cham_mot_cau(i, True)
        self.assertFalse(self.ht.can_hoi("hoc"))
        self.assertTrue(self.ht.can_hoi("cung_thiet_bi"), "mỗi loại câu lên cấp riêng")
        for i in range(60, 62):
            self._cham_mot_cau(i, False)
        self.assertTrue(self.ht.can_hoi("hoc"))

    # ── người CHẤM trong nhóm ──────────────────────────────────────────────
    def test_TRA_LOI_hh_ghi_diem_dung_cau(self) -> None:
        ids = [d["id"] for d in self._luu(self._nhom_bep())["moi"]]
        self.assertIsNone(self.ht.tra_loi("bật đèn bếp"))
        self.assertIsNone(self.ht.tra_loi("hhh 1 đúng"))
        self.assertIn(f"#{ids[0]}", self.ht.tra_loi(f"HH {ids[0]} {ids[1]} dung"))
        self.ht.tra_loi(f"hh #{ids[2]} sai vì là quạt")
        theo = {d["id"]: d for d in self.ht.dang_hieu_luc()}
        self.assertEqual(theo[ids[0]]["ket_qua"], "dung")
        self.assertEqual(theo[ids[1]]["ket_qua"], "dung")
        self.assertEqual(theo[ids[2]]["ket_qua"], "sai")
        self.assertEqual(theo[ids[2]]["ghi_chu"], "vì là quạt")
        self.assertEqual(theo[ids[2]]["cham_boi"], "chu_may")
        self.assertIn("Không thấy", self.ht.tra_loi("hh 99999 đúng"))
        self.assertIn("hh <số>", self.ht.tra_loi("hh bậy"))

    # ── báo nhóm học hỏi ───────────────────────────────────────────────────
    def test_TIN_NHAN_noi_VI_SAO_va_KHONG_CON_MA_MAY(self) -> None:
        """Chủ máy muốn biết "bot nghĩ gì". Zalo gửi markdown nên gạch dưới bị
        ăn — bài học `test_TIN_NHAN_khong_con_MA_MAY` của `du_doan_nha`."""
        moi = self._luu(self._nhom_bep())["moi"]
        kq = {"phien_ban": "abc", "loi": "", "bo_sot": 0, "loai_bo": 0}
        tin = "\n".join(self.ht.soan_bao(
            kq, moi, [], {"switch.bep_left": "Đèn bếp", "light.bep_left": "Đèn bếp"}))
        self.assertIn("Đèn bếp [switch]", tin)
        self.assertIn("MỘT thiết bị", tin)
        self.assertIn("đổi cùng lúc 100%", tin)
        self.assertIn("hh ", tin)
        self.assertNotIn("_", tin)
        self.assertNotIn("switch.bep", tin)

    def test_KHONG_CO_GI_MOI_thi_KHONG_NHAN(self) -> None:
        kq = {"phien_ban": "abc", "loi": "", "bo_sot": 0, "loai_bo": 0}
        self.assertEqual(self.ht.soan_bao(kq, [], [], {}), [])

    def test_CHUA_CHON_KENH_thi_KHONG_GUI_LUNG_TUNG(self) -> None:
        """Chủ máy chỉ định nhóm "AI học hỏi" — không rơi về admin như gợi ý đèn."""
        self.ls.config.data["mqtt"]["du_doan"] = {"bat": True}
        with mock.patch("services.digest.send_targets") as gui:
            self.assertEqual(self.ht.bao_nhom(["tin"]), 0)
        gui.assert_not_called()

    # ── hướng dẫn ──────────────────────────────────────────────────────────
    def test_HUONG_DAN_CHEP_MOT_LAN_va_DOI_CHU_LA_DOI_PHIEN_BAN(self) -> None:
        """Giáo viên sửa bản chạy thật mà không dựng lại ảnh; điểm chấm không
        được lẫn giữa hai bản."""
        noi, ban = self.ht.huong_dan()
        self.assertIn("CHỈ JSON", noi)
        self.assertRegex(ban, r"^[0-9a-f]{12}$")
        self.ht._duong_huong_dan().write_text(noi + "\nThêm một luật.", encoding="utf-8")
        noi2, ban2 = self.ht.huong_dan()
        self.assertNotEqual(ban, ban2)
        self.assertIn("Thêm một luật.", noi2, "không được ghi đè bản giáo viên đã sửa")


if __name__ == "__main__":
    unittest.main()
