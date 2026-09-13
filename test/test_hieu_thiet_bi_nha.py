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
                  # HA thật trả MỌI thực thể đang có; mã HA vắng ở đây thì
                  # `ho_so` coi là đã đổi tên hoặc đã xoá.
                  mock.patch.object(ha_client, "get_states", return_value=[
                      {"entity_id": "switch.bep_left",
                       "attributes": {"friendly_name": "Đèn bếp"}},
                      {"entity_id": "light.bep_left",
                       "attributes": {"friendly_name": "Đèn bếp"}},
                      *({"entity_id": ma, "attributes": {}} for ma in (
                          "light.nha_tam", "switch.quat_nha_tam", "light.hien",
                          "binary_sensor.cua", *(f"light.a_le_{k}" for k in range(6)),
                          *(f"switch.cam_{k}" for k in range(12))))]),
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
        # Kênh nhận dời sang sổ đăng ký `thong_bao` (13/09/2026), không còn đọc
        # `mqtt.du_doan.kenh_nhan`. `config` là singleton nên phải trả lại.
        self.ls.config.data["thong_bao"] = {
            "hoc_hoi.hieu_thiet_bi": {"bat": True, "kenh": ["zalop:acc:nhom"]}}
        self.addCleanup(self.ls.config.data.pop, "thong_bao", None)

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
        tin, id_ = self.ht.soan_bao(
            kq, moi, [], {"switch.bep_left": "Đèn bếp", "light.bep_left": "Đèn bếp"})
        self.assertEqual(id_, moi[0]["id"])
        self.assertIn("Đèn bếp [switch]", tin)
        self.assertIn("MỘT thiết bị", tin)
        self.assertIn("đổi cùng lúc 100%", tin)
        self.assertIn(f"hh {id_} ", tin)
        self.assertNotIn("_", tin)
        self.assertNotIn("switch.bep", tin)

    def test_XAC_MINH_LAN_LUOT_moi_lan_MOT_CAU(self) -> None:
        """Chủ máy chốt 11/09/2026: "tin gửi để tôi xác minh đang dài quá. Tôi
        muốn nó xác minh lần lượt, khi tôi phản hồi xong thì mới gửi xác minh
        tiếp". Bản 19:20 hôm đó là bốn tin dài kể mọi kết luận."""
        moi = self._luu(self._nhom_bep())["moi"]
        kq = {"phien_ban": "abc", "loi": "", "bo_sot": 0, "loai_bo": 0}
        ten = {"switch.bep_left": "Đèn bếp"}
        tin, id_ = self.ht.soan_bao(kq, moi, [], ten)
        self.assertEqual(tin.count("«hh "), 2, "đúng MỘT câu hỏi (mẫu đúng và mẫu sai)")
        self.ht.danh_dau_da_hoi(id_)
        self.assertEqual(self.ht.cau_hoi_tiep(ten), ("", 0),
                         "chưa trả lời thì không hỏi câu sau")
        dap = self.ht.tra_loi(f"hh {id_} đúng")
        self.assertIn(f"Câu #{moi[1]['id']}", dap, "trả lời xong thì hỏi câu kế tiếp")
        self.assertEqual(self.ht.cau_hoi_tiep(ten), ("", 0),
                         "câu kế tiếp vừa hỏi trong câu đáp — lại chờ")

    def test_CAU_CLAUDE_DA_CHAM_thi_KHONG_HOI_CHU_MAY(self) -> None:
        moi = self._luu(self._nhom_bep())["moi"]
        for d in moi[:-1]:
            self.ht.cham(d["id"], True, cham_boi="claude")
        _, id_ = self.ht.cau_hoi_tiep({})
        self.assertEqual(id_, moi[-1]["id"])

    def test_KHONG_CO_GI_MOI_thi_KHONG_NHAN(self) -> None:
        kq = {"phien_ban": "abc", "loi": "", "bo_sot": 0, "loai_bo": 0}
        self.assertEqual(self.ht.soan_bao(kq, [], [], {}), ("", 0))

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

    def test_BAN_GOC_DOI_thi_BAN_CHAY_THAT_THEO_tru_khi_da_sua_tay(self) -> None:
        """13/09/2026: code chọn ngoại vi sang hai bước mà bản chạy thật vẫn là
        bản một bước, vì bản cũ chép MỘT lần rồi không bao giờ theo bản gốc."""
        goc = Path(self._tmp.name) / "goc" / "hieu_thiet_bi.md"
        goc.parent.mkdir()
        goc.write_text("bản 1", encoding="utf-8")
        with mock.patch.object(self.ht, "_HUONG_DAN_GOC", goc):
            self.assertEqual(self.ht.huong_dan()[0], "bản 1")
            goc.write_text("bản 2", encoding="utf-8")
            self.assertEqual(self.ht.huong_dan()[0], "bản 2", "chưa ai sửa tay thì theo bản gốc")
            self.assertTrue(self.ht.ghi_huong_dan("bản giáo viên sửa"))
            goc.write_text("bản 3", encoding="utf-8")
            self.assertEqual(self.ht.huong_dan()[0], "bản giáo viên sửa")

    def test_BAN_CU_KHONG_CO_SO_GOC(self) -> None:
        """Bản chạy thật có từ trước khi có sổ `.goc`: khớp bản gốc thì ghi sổ và
        từ đó theo bản gốc; khác thì không biết là cũ hay đã sửa tay — giữ nguyên."""
        goc = Path(self._tmp.name) / "goc" / "hieu_thiet_bi.md"
        goc.parent.mkdir()
        chay = self.ht._duong_huong_dan()
        chay.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(self.ht, "_HUONG_DAN_GOC", goc):
            goc.write_text("gốc", encoding="utf-8")
            chay.write_text("không rõ nguồn", encoding="utf-8")
            self.assertEqual(self.ht.huong_dan()[0], "không rõ nguồn")
            chay.write_text("gốc", encoding="utf-8")
            self.ht.huong_dan()
            goc.write_text("gốc mới", encoding="utf-8")
            self.assertEqual(self.ht.huong_dan()[0], "gốc mới")

    # ── chủ máy DẠY bot (11/09/2026) ───────────────────────────────────────
    def test_HH_HIEU_DAU_PHAY_va_GHI_PHAN_DAY_THEM(self) -> None:
        """Chủ máy nhắn «hh 11, 32 đúng, aptomat …»: bản cũ trả "Anh gõ giúp
        em…" vì "11," có dấu phẩy, và phần dạy phía sau bị vứt."""
        ids = [d["id"] for d in self._luu(self._nhom_bep())["moi"]]
        dap = self.ht.tra_loi(f"hh {ids[0]}, {ids[1]} đúng, aptomat và điều hòa "
                              "link với nhau qua automation", nguoi="Việt")
        theo = {d["id"]: d for d in self.ht.dang_hieu_luc()}
        self.assertEqual((theo[ids[0]]["ket_qua"], theo[ids[1]]["ket_qua"]),
                         ("dung", "dung"))
        self.assertEqual(theo[ids[0]]["cham_boi"], "chu_may")
        self.assertIn("dữ kiện #", dap)
        self.assertEqual([x["noi_dung"] for x in self.ht.du_kien_gan_day()],
                         ["aptomat và điều hòa link với nhau qua automation"])

    def test_CHU_MAY_CHAM_LAI_de_len_diem_CLAUDE(self) -> None:
        """Claude chấm "đúng" cho việc học cảm biến phòng khách; chủ máy nói đó
        là cảm biến. Điểm, thành tích và thứ được học phải đổi theo chủ máy."""
        hoc = next(d for d in self._luu(self._nhom_bep())["moi"]
                   if d["loai_cau_hoi"] == "hoc")
        self.ht.cham(hoc["id"], True, cham_boi="claude")
        self.assertEqual(self.ht._thanh_tich("hoc"), (1, 0))
        self.ht.tra_loi(f"hh {hoc['id']} sai vì là cảm biến")
        self.assertEqual(self.ht._thanh_tich("hoc"), (0, 1))
        self.assertEqual(self.ht.thiet_bi_hoc(), [])

    def test_CHAM_LAI_CAU_LAP_LAI_khong_tru_oan(self) -> None:
        """Câu lặp lại mang chữ "sai" nhưng chưa từng được cộng vào thành tích."""
        hoc = next(d for d in self._luu(self._nhom_bep())["moi"]
                   if d["loai_cau_hoi"] == "hoc")
        self.ht.cham(hoc["id"], False, cham_boi="claude")
        self._luu(self._nhom_bep(hoc=False, ma_hoc="", loai="khong_ro"))
        lap = self._luu(self._nhom_bep())["lap_lai"][0]
        self.assertEqual(self.ht._thanh_tich("hoc"), (0, 1))
        self.assertTrue(self.ht.sua_cham(lap["id"], True, cham_boi="chu_may"))
        self.assertEqual(self.ht._thanh_tich("hoc"), (1, 1))

    def test_TIN_DAY_THUONG_la_DU_KIEN_va_GIAI_LAI_NGAY(self) -> None:
        """Chủ máy dạy xong là muốn xem bot hiểu ra sao, không phải chờ tới mai."""
        self.assertFalse(self.ht.co_du_kien_moi())
        dap = self.ht.nhan_du_kien("Cảm biến phòng khách là cảm biến", nguoi="Việt")
        self.assertIn("dữ kiện #", dap)
        self.assertTrue(self.ht.co_du_kien_moi())
        self.ht._ghi_lan("v", "m", 1, 1, 0, 0, "")
        self.assertFalse(self.ht.co_du_kien_moi())
        self.assertIsNone(self.ht.nhan_du_kien("   "))

    def test_DU_KIEN_VAO_DE_cua_bot(self) -> None:
        """Chủ máy biết cái gì nối bằng automation; số đo thì không."""
        self._den_bep()
        self.ht.ghi_du_kien("aptomat và điều hòa là hai thiết bị", nguoi="Việt")
        de_nhan: list[dict] = []

        def bot(model, huong, de):
            de_nhan.append(json.loads(de))
            return {"choices": [{"message": {"content": '{"nhom": []}'}}]}

        with mock.patch.object(self.ht, "_goi_model", side_effect=bot), \
             mock.patch.object(self.ht, "_model", return_value="m"), \
             mock.patch.object(self.ht, "bao_nhom", return_value=1):
            self.ht.chay_mot_lan()
        self.assertEqual([x["noi_dung"] for x in de_nhan[0]["du_kien_chu_may"]],
                         ["aptomat và điều hòa là hai thiết bị"])

    def test_HO_SO_do_DO_LECH_MS(self) -> None:
        """Đo 11/09/2026: hai mã của cùng bóng lệch 0–3 ms, hai thiết bị nối bằng
        automation lệch 29–60 ms — mà tỉ lệ trùng thì như nhau."""
        self._den_bep()
        theo = {x["ma"]: x for x in self.ht.ho_so(so_ngay=30)["thiet_bi"]}
        kem = {k["ma"]: k for k in theo["switch.bep_left"]["doi_cung_luc"]}
        self.assertEqual(kem["light.bep_left"]["lech_ms"], 50)
        self.assertEqual(kem["zigbee2mqtt/Bếp#state_left"]["lech_ms"], 3)

    def test_KIEM_BIEN_nhan_LOAI_CAM_BIEN(self) -> None:
        phan = [{"ma": "switch.x", "ha_bat_duoc": True}]
        nhom, _ = self.ht._kiem({"nhom": [{"ma": ["switch.x"], "hoc": False,
                                          "ma_hoc": "", "loai": "cam_bien",
                                          "chac": 0.9}]}, phan)
        self.assertEqual(nhom[0]["loai"], "cam_bien")

    def test_HAI_LUOT_GIAI_khong_CHONG_NHAU(self) -> None:
        """Dữ kiện mới làm heartbeat gọi lại mỗi tick; lượt cũ chưa xong thì bỏ."""
        with self.ht._dang_giai:
            self.assertIn("bo_qua", self.ht.chay_mot_lan())

    # ── cổng nhóm học hỏi trong Zalo Cá Nhân ───────────────────────────────
    def _cong(self, text: str, *, thread: str = "nhom", tag: bool = False):
        import services.zalo_personal as zp

        # Cổng VÀO của nhóm học hỏi đọc kênh từ sổ đăng ký `thong_bao`
        # (13/09/2026), không còn đọc `mqtt.du_doan.kenh_nhan`. Đây là đường
        # vào — phần GỬI không chạm tới, nên quên chỗ này là hỏng âm thầm: tin
        # vẫn ra nhóm đều, chỉ câu chấm và lời dạy là rơi mất.
        self.ls.config.data["thong_bao"] = {
            "hoc_hoi.hieu_thiet_bi": {"bat": True, "kenh": ["zalop:acc:nhom"]}}
        self.addCleanup(self.ls.config.data.pop, "thong_bao", None)
        ev = {"account_id": "acc", "thread_id": thread, "sender_id": "u1",
              "display_name": "Việt", "text": text, "thread_type": 1, "mentions": []}
        with mock.patch("services.agent.capabilities.mention_required_for",
                        return_value=(True, "@bot")), \
             mock.patch.object(zp, "is_bot_tagged", return_value=tag):
            return zp._nhom_hoc_hoi(ev, thread, text)

    def test_CONG_NHOM_HOC_HOI_nhan_CAU_CHAM_va_DU_KIEN(self) -> None:
        """Tin dạy không tag bot từng bị cổng tag bỏ im lặng."""
        ids = [d["id"] for d in self._luu(self._nhom_bep())["moi"]]
        self.assertIn("Em ghi rồi", self._cong(f"hh {ids[0]} đúng"))
        self.assertIn("dữ kiện #", self._cong("Dàn âm thanh bật theo công tắc mini"))
        self.assertEqual(len(self.ht.du_kien_gan_day()), 1)

    def test_CONG_NHOM_HOC_HOI_de_TIN_TAG_BOT_va_NHOM_KHAC_di_tiep(self) -> None:
        """Tag bot là muốn trò chuyện; nhóm khác không phải nơi dạy bot."""
        self.assertIsNone(self._cong("@bot bật đèn bếp", tag=True))
        self.assertIsNone(self._cong("chào cả nhà", thread="nhom_khac"))
        self.assertEqual(self.ht.du_kien_gan_day(), [])

    def test_CONG_NHOM_HOC_HOI_nhan_CAU_CHAM_GOI_Y_gy(self) -> None:
        """Trước 11/09/2026 gợi ý bật thiết bị chỉ chấm được trên web."""
        import services.du_doan_nha as dd

        id_ = dd.ghi_nhan("switch.bep_left", "on", 0.9, {}, "goi_y")
        self.assertIn("Em ghi rồi", self._cong(f"gy {id_} đúng"))
        self.assertEqual(dd.so_luot("switch.bep_left"), 1)
        self.assertEqual(self.ht.du_kien_gan_day(), [], "câu chấm không phải dữ kiện")

    # ── điều kiện kiểu khoá phòng đã bỏ (13/09/2026) ────────────────────────
    def test_LUOT_HIEU_THIET_BI_KHONG_con_de_THUC_DON_hay_hoi_DIEU_KIEN(self) -> None:
        """Chủ máy chốt 13/09/2026: tầng xác suất học theo thói quen bot đọc; lượt
        hiểu thiết bị không gửi thực đơn điều kiện, không sinh câu `dieu_kien` —
        bot còn trả trường đó thì bỏ qua, không loại cả nhóm."""
        self._den_bep()
        de_da_gui: list[dict] = []

        def bot(model, huong, de):
            de_da_gui.append(json.loads(de))
            ma = [x["ma"] for x in de_da_gui[-1]["thiet_bi"]]
            bai = {"nhom": [{"ma": ma, "ma_hoc": "switch.bep_left", "nguon_nhanh": ma[0],
                             "loai": "bat_tat", "hoc": True, "chac": 0.9,
                             "dieu_kien": ["buoi"], "vi_sao": ""}]}
            return {"choices": [{"message": {"content": json.dumps(bai, ensure_ascii=False)}}]}

        with mock.patch.object(self.ht, "_goi_model", side_effect=bot), \
             mock.patch.object(self.ht, "_model", return_value="m"):
            kq = self.ht.giai_mot_thiet_bi("switch.bep_left")
        self.assertEqual(kq["loi"], "")
        self.assertNotIn("thuc_don_dieu_kien", de_da_gui[0])
        self.assertFalse(any(d["loai_cau_hoi"] == "dieu_kien" for d in self.ht.dang_hieu_luc()))

    def test_CAU_DIEU_KIEN_CU_trong_so_HET_HIEU_LUC(self) -> None:
        """Câu `dieu_kien` lưu trước 13/09/2026 không còn gì dùng — không được hỏi
        chủ máy chấm nữa."""
        conn = self.ht._db()
        conn.execute("INSERT INTO quyet_dinh (lan_giai, ts, loai_cau_hoi, khoa, gia_tri, nhom)"
                     " VALUES (1, 0, 'dieu_kien', 'switch.bep_left', '{\"dieu_kien\": [\"buoi\"]}', '{}')")
        conn.commit()
        self.ht._reset_for_tests()
        self.assertEqual([d for d in self.ht.dang_hieu_luc() if d["loai_cau_hoi"] == "dieu_kien"], [])
        self.assertEqual(self.ht.cau_hoi_tiep({}), ("", 0))

    def test_HO_SO_BO_MA_KHONG_CON_TRONG_HA(self) -> None:
        """Mã HA không còn trong HA (đổi tên, xoá, hay bị ẩn vì tên mang mật
        khẩu) thì không ra đề — kể cả khi lịch sử 30 ngày còn giữ mã cũ."""
        from services import ha_client

        self._den_bep()
        goc = time.time() - 3 * 86400
        for i in range(6):
            self._sk("camera.go2rtc_rtsp_u_p_10_0_0_5_554_cua_sub",
                     "streaming" if i % 2 == 0 else "idle", goc + i * 3600)
        with mock.patch.object(ha_client, "get_service_catalog",
                               return_value={**_SO_DICH_VU, "camera": {"turn_on": {}}}):
            hs = self.ht.ho_so(so_ngay=30)
        ma = {x["ma"] for x in hs["thiet_bi"]}
        self.assertIn("switch.bep_left", ma)
        self.assertNotIn("camera.go2rtc_rtsp_u_p_10_0_0_5_554_cua_sub", ma)

    # ── Tab Học hỏi: xoá / sửa kết luận, dữ kiện, hướng dẫn, lịch sử, sơ đồ ──
    def test_XOA_KET_LUAN_KHONG_CON_TRONG_DANG_HIEU_LUC(self) -> None:
        moi = self._luu(self._nhom_bep())["moi"]
        id_ = moi[0]["id"]
        self.assertTrue(self.ht.xoa_ket_luan(id_))
        self.assertFalse(any(d["id"] == id_ for d in self.ht.dang_hieu_luc()))

    def test_XOA_KET_LUAN_KHONG_TON_TAI_TRA_FALSE(self) -> None:
        self.assertFalse(self.ht.xoa_ket_luan(999999))

    def test_GHI_VA_SUA_VA_XOA_DU_KIEN(self) -> None:
        i = self.ht.ghi_du_kien("bình nóng lạnh bật theo giờ quen", nguon="tab")
        self.assertTrue(i)
        self.assertTrue(self.ht.sua_du_kien(i, "bình nóng lạnh bật theo mùa"))
        noi = {d["id"]: d["noi_dung"] for d in self.ht.du_kien_gan_day()}
        self.assertEqual(noi[i], "bình nóng lạnh bật theo mùa")
        self.assertTrue(self.ht.xoa_du_kien(i))
        self.assertNotIn(i, {d["id"] for d in self.ht.du_kien_gan_day()})

    def test_SUA_DU_KIEN_RONG_KHONG_SUA(self) -> None:
        i = self.ht.ghi_du_kien("dữ kiện gốc")
        self.assertFalse(self.ht.sua_du_kien(i, "  "))
        noi = {d["id"]: d["noi_dung"] for d in self.ht.du_kien_gan_day()}
        self.assertEqual(noi[i], "dữ kiện gốc")

    def test_GHI_HUONG_DAN_DOI_PHIEN_BAN(self) -> None:
        _, ban_cu = self.ht.huong_dan()
        self.assertTrue(self.ht.ghi_huong_dan("nội dung hướng dẫn mới hoàn toàn"))
        noi, ban_moi = self.ht.huong_dan()
        self.assertEqual(noi, "nội dung hướng dẫn mới hoàn toàn")
        self.assertNotEqual(ban_cu, ban_moi)

    def test_GHI_HUONG_DAN_RONG_KHONG_GHI(self) -> None:
        self.assertFalse(self.ht.ghi_huong_dan(""))

    def test_LICH_SU_GIAI_MOI_TRUOC(self) -> None:
        self._luu(self._nhom_bep())
        self._luu(self._nhom_bep(vi_sao="lượt hai"))
        ls = self.ht.lich_su_giai()
        self.assertEqual(len(ls), 2)
        self.assertGreater(ls[0]["id"], ls[1]["id"], "mới nhất đứng đầu")

    def _thoi_quen_bep(self) -> None:
        """Bot đã chọn ngoại vi và đọc thói quen cho đèn bếp (chặng 1–2)."""
        self.ht.ghi_ngoai_vi(self.ht._ghi_lan("b", "m", 1, 1, 0, 0, "", viec="ngoai_vi"), [{
            "ma_hoc": "switch.bep_left", "khu_vuc": "Bếp", "chac": 0.9, "vi_sao": "",
            "ngoai_vi": [{"ma": "binary_sensor.hien_dien_bep", "ten": "Hiện diện bếp",
                          "vai_tro": "hien_dien"}]}])
        self.ht.ghi_thoi_quen(self.ht._ghi_lan("b", "m", 1, 1, 0, 0, "", viec="thoi_quen"), [{
            "ma_hoc": "switch.bep_left", "chac": 0.8, "vi_sao": "",
            "bat": {"thoi_quen": "tối có người thì bật", "dieu_kien": [
                {"ma": "gio", "tu": "18:00", "den": "22:00"},
                {"ma": "binary_sensor.hien_dien_bep", "la": "on"},
                {"ma": "gio", "tu": "06:00", "den": "08:00"}]},
            "tat": {"thoi_quen": "", "dieu_kien": []},
            "ngoai_vi": ["binary_sensor.hien_dien_bep"],
            "ten_ngoai_vi": {"binary_sensor.hien_dien_bep": "Hiện diện bếp"}}])

    def test_SO_DO_KICH_HOAT_la_DIEU_KIEN_THOI_QUEN_va_NGOAI_VI_BOT_CHON(self) -> None:
        """Chủ máy chốt 13/09/2026: sơ đồ hiện đúng điều kiện tầng xác suất học theo."""
        self._luu(self._nhom_bep())
        self._thoi_quen_bep()
        nut = {n["khoa"]: n for n in self.ht.so_do_kich_hoat(kem_so_do=False)}["switch.bep_left"]
        self.assertEqual([(d["khoa"], d["ten"]) for d in nut["dieu_kien"]], [
            ("gio", "trong 18:00–22:00 hoặc 06:00–08:00"),
            ("binary_sensor.hien_dien_bep", "Hiện diện bếp là on")])
        self.assertEqual([n["ten"] for n in nut["ngoai_vi"]], ["Hiện diện bếp"])

    def test_SO_DO_KHONG_KEM_SO_DO_thi_KHONG_DO_GI(self) -> None:
        """Đường web `/api/hoc-hoi/so-do` phải trả NGAY; phần đo đọc lịch sử 30
        ngày nên tách sang `/so-do/do`."""
        from services import du_doan_nha

        self._luu(self._nhom_bep())
        self._thoi_quen_bep()
        with mock.patch.object(du_doan_nha, "hoc") as hoc:
            so_do = self.ht.so_do_kich_hoat(kem_so_do=False)
        hoc.assert_not_called()
        self.assertIsNone(so_do[0]["dieu_kien"][0]["do"])

    def test_SO_DO_KEM_SO_DO_lay_TY_LE_KHOP_tu_BANG_DEM_cua_tang_xac_suat(self) -> None:
        """Số % trên sơ đồ là đúng bảng đếm tầng xác suất dùng — không đo riêng một kiểu."""
        from services import du_doan_nha

        self._luu(self._nhom_bep())
        self._thoi_quen_bep()
        bang = {"switch.bep_left": {"dk": {"gio=khop": {"bat": 8, "khong": 40},
                                          "gio=lech": {"bat": 2, "khong": 300}}}}
        with mock.patch.object(du_doan_nha, "hoc", return_value=bang):
            nut = self.ht.so_do_kich_hoat(kem_so_do=True)[0]
        do = {d["khoa"]: d["do"] for d in nut["dieu_kien"]}
        self.assertEqual(do["gio"], {"nhan_hay_gap": "khớp", "mau": 10, "ty_le": 0.8})
        self.assertEqual(do["binary_sensor.hien_dien_bep"]["mau"], 0, "chưa đo được thì nói 0 mẫu")

    def test_SO_DO_BO_QUA_THIET_BI_CHAM_SAI(self) -> None:
        moi = self._luu(self._nhom_bep())["moi"]
        hoc = next(d for d in moi if d["loai_cau_hoi"] == "hoc")
        self.ht.cham(hoc["id"], False, cham_boi="chu_may")
        self.assertEqual(self.ht.so_do_kich_hoat(), [])

    # ── Phân tích một thiết bị theo yêu cầu (mục 7 — "bot bỏ sót") ──────────
    def test_GIAI_MOT_THIET_BI_KHONG_THAY_MA_TRA_LOI(self) -> None:
        self._den_bep()
        kq = self.ht.giai_mot_thiet_bi("khong_co_that")
        self.assertTrue(kq.get("loi"))

    def test_GIAI_MOT_THIET_BI_CHI_GUI_MA_LIEN_QUAN(self) -> None:
        self._den_bep()
        nhan: list[list[str]] = []

        def bot(model, huong, de):
            ma = [x["ma"] for x in json.loads(de)["thiet_bi"]]
            nhan.append(sorted(ma))
            bai = {"nhom": [{"ma": ma, "ma_hoc": "switch.bep_left",
                             "nguon_nhanh": "zigbee2mqtt/Bếp#state_left",
                             "loai": "bat_tat", "hoc": True, "chac": 0.9,
                             "vi_sao": "đổi cùng lúc"}]}
            return {"choices": [{"message": {
                "content": json.dumps(bai, ensure_ascii=False)}}]}

        with mock.patch.object(self.ht, "_goi_model", side_effect=bot), \
             mock.patch.object(self.ht, "_model", return_value="m"):
            kq = self.ht.giai_mot_thiet_bi("switch.bep_left")
        self.assertEqual(kq["loi"], "")
        self.assertEqual(kq["moi"], 3)
        # Chỉ gửi switch.bep_left + các mã đổi CÙNG LÚC với nó, không gửi cả
        # nhà (đo 11/09/2026: light.a_le_0..5, switch.cam_0..11 không liên quan).
        self.assertIn("switch.bep_left", nhan[0])
        self.assertNotIn("light.a_le_0", nhan[0])
        self.assertEqual(self.ht.thiet_bi_hoc(), ["switch.bep_left"])


if __name__ == "__main__":
    unittest.main()
