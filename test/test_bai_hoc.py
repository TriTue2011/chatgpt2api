"""Sổ bài học: bot sai một lần thì lần sau tự tránh."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


class BaiHocTest(unittest.TestCase):
    def setUp(self) -> None:
        import services.bai_hoc as m
        self.m = m
        self._tmp = Path(tempfile.mkdtemp())
        m._duong = lambda: self._tmp / "bai_hoc.json"

    # ── ca thật 10/09/2026 11h53 ───────────────────────────────────────────
    def test_CAU_TUNG_SAI_thi_tra_ra(self) -> None:
        """Chủ máy hỏi "fingerprint#2 lần cuối lúc mấy giờ", bot đáp giờ hiện
        tại. Đánh dấu sai rồi thì lần sau phải tra ra."""
        self.m.ghi_sai("fingerprint#2 lần cuối lúc mấy giờ",
                       "Hiện tại là 11 giờ 53 phút", "_la_cau_hoi_gio")
        ra = self.m.tra("fingerprint#2 lần cuối lúc mấy giờ")
        self.assertEqual(len(ra), 1)
        self.assertEqual(ra[0]["bo_do"], "_la_cau_hoi_gio")

    def test_KHAC_CHU_CUNG_Y_van_tra_ra(self) -> None:
        """Điểm khác căn bản với danh sách từ khoá: câu không chung chuỗi con
        nào đáng kể vẫn nhận ra là cùng ý."""
        self.m.ghi_sai("fingerprint#2 lần cuối lúc mấy giờ", "…", "x")
        self.assertTrue(self.m.tra("ai mở cửa lúc mấy giờ"),
                        "câu cùng ý nhưng khác chữ phải tra ra")

    def test_CAU_HOI_GIO_THUONG_khong_bi_chan(self) -> None:
        """Lỗi thật của bản nháp: chia cho tập nhỏ hơn thì "mấy giờ rồi" ra
        1.00 với câu vân tay, nên câu hỏi giờ bình thường bị chặn theo."""
        self.m.ghi_sai("fingerprint#2 lần cuối lúc mấy giờ", "…", "x")
        for c in ("mấy giờ rồi", "bây giờ là mấy giờ", "giờ rồi em"):
            self.assertEqual(self.m.tra(c), [], c)

    def test_cau_khac_han_khong_tra_ra(self) -> None:
        self.m.ghi_sai("thời tiết hôm nay thế nào", "…", "x")
        self.assertEqual(self.m.tra("bật đèn bếp"), [])

    def test_chua_co_bai_hoc_thi_rong(self) -> None:
        self.assertEqual(self.m.tra("bất cứ câu gì"), [])
        self.assertEqual(self.m.tra(""), [])

    # ── chấm điểm bộ dò ────────────────────────────────────────────────────
    def test_CHUA_DU_MAU_thi_KHONG_ket_luan_do(self) -> None:
        """Chưa dùng lần nào khác hẳn dùng nhiều mà hay sai."""
        self.m.ghi_sai("câu a", "…", "_bo_do_x")
        self.assertFalse(self.m.bo_do_dang_ngo("_bo_do_x"),
                         "một lần sai chưa đủ để rút đường tắt")

    def test_sai_nhieu_thi_dang_ngo(self) -> None:
        for i in range(5):
            self.m.ghi_sai(f"câu số {i} hoàn toàn khác nhau nhé", "…", "_bo_do_x")
        self.assertTrue(self.m.bo_do_dang_ngo("_bo_do_x"))

    def test_dung_nhieu_thi_TIN_DUOC_va_thoi_hoi(self) -> None:
        for _ in range(6):
            self.m.ghi_dung("thời tiết hôm nay", "_ha_local_weather")
        self.assertTrue(self.m.da_tin_duoc("_ha_local_weather"))
        self.assertFalse(self.m.nen_hoi_lai("_ha_local_weather"),
                         "bộ dò đã tin được thì thôi làm phiền")
        self.assertFalse(self.m.bo_do_dang_ngo("_ha_local_weather"))

    def test_moi_tinh_thi_VAN_HOI(self) -> None:
        self.assertTrue(self.m.nen_hoi_lai("_bo_do_moi"))

    def test_khong_co_ten_bo_do_thi_khong_hoi(self) -> None:
        self.assertFalse(self.m.nen_hoi_lai(""))
        self.assertFalse(self.m.bo_do_dang_ngo(""))

    def test_diem_chua_co_du_lieu_la_CHUA_BIET(self) -> None:
        self.assertEqual(self.m.diem("_chua_dung_bao_gio"), 0.5)

    # ── giữ sổ gọn ─────────────────────────────────────────────────────────
    def test_cung_cau_sai_lai_thi_TANG_DEM(self) -> None:
        self.m.ghi_sai("fingerprint#2 lần cuối lúc mấy giờ", "…", "x")
        self.m.ghi_sai("fingerprint#2 lần cuối lúc mấy giờ", "…", "x")
        ra = self.m.tra("fingerprint#2 lần cuối lúc mấy giờ")
        self.assertEqual(len(ra), 1, "không được nhân đôi dòng")
        self.assertEqual(ra[0]["so_lan"], 2)

    def test_bai_hoc_QUA_CU_thi_thoi_tinh(self) -> None:
        """Nhà thay đổi, thiết bị thay đổi — bài học nửa năm trước hết đúng."""
        self.m.ghi_sai("câu cũ lúc mấy giờ nhỉ", "…", "x")
        d = self.m._doc()
        d["sai"][0]["ts"] = time.time() - (self.m._HAN_NGAY + 1) * 86400
        self.m._ghi(d)
        self.assertEqual(self.m.tra("câu cũ lúc mấy giờ nhỉ"), [])

    def test_cau_rong_thi_khong_luu(self) -> None:
        self.assertFalse(self.m.ghi_sai("", "…", "x"))
        self.assertFalse(self.m.ghi_sai("   ", "…", "x"))

    # ── không bao giờ ném lỗi ──────────────────────────────────────────────
    def test_ghi_hong_khong_raise(self) -> None:
        self.m._duong = lambda: Path("/khong/ton/tai/bai_hoc.json")
        try:
            self.m.ghi_sai("câu gì đó", "…", "x")
            self.assertEqual(self.m.tra("câu gì đó"), [])
        except Exception as exc:
            self.fail(f"không được ném lỗi: {exc}")

    def test_thong_ke(self) -> None:
        self.m.ghi_sai("câu một hai ba bốn", "…", "_a")
        self.m.ghi_dung("câu khác", "_b")
        t = self.m.thong_ke()
        self.assertEqual(t["so_bai_hoc"], 1)
        self.assertEqual(t["bo_do"]["_a"]["sai"], 1)
        self.assertEqual(t["bo_do"]["_b"]["dung"], 1)


class CauHinhTest(unittest.TestCase):
    """Chủ máy phải tắt/chỉnh được — không được bật cứng trong mã."""

    def setUp(self) -> None:
        import services.bai_hoc as m
        from services.config import config
        self.m, self.cfg = m, config
        self._tmp = Path(tempfile.mkdtemp())
        m._duong = lambda: self._tmp / "bai_hoc.json"
        config.data.setdefault("mqtt", {})["bai_hoc"] = {}

    def tearDown(self) -> None:
        self.cfg.data.get("mqtt", {}).pop("bai_hoc", None)

    def test_mac_dinh_la_BAT(self) -> None:
        self.assertTrue(self.m.is_enabled())

    def test_TAT_thi_khong_hoi_va_khong_tra(self) -> None:
        """Tắt rồi thì bot chạy y như trước khi có tính năng này."""
        self.m.ghi_sai("fingerprint#2 lần cuối lúc mấy giờ", "…", "x")
        self.cfg.data["mqtt"]["bai_hoc"] = {"bat": False}
        self.assertFalse(self.m.is_enabled())
        self.assertEqual(self.m.tra("fingerprint#2 lần cuối lúc mấy giờ"), [],
                         "tắt thì không được chặn đường tắt")
        self.assertFalse(self.m.nen_hoi_lai("_bo_do_moi"),
                         "tắt thì không được gắn nút hỏi")

    def test_chinh_duoc_nguong_tin(self) -> None:
        """Chủ máy thấy bị hỏi nhiều thì hạ ngưỡng cho bot sớm tin."""
        self.cfg.data["mqtt"]["bai_hoc"] = {"du_mau": 2, "diem_tin": 0.6}
        for _ in range(2):
            self.m.ghi_dung("thời tiết", "_w")
        self.assertTrue(self.m.da_tin_duoc("_w"),
                        "2 lần đúng với ngưỡng đã hạ là đủ tin")

    def test_chinh_duoc_han_bai_hoc(self) -> None:
        self.m.ghi_sai("câu nào đó dài dòng", "…", "x")
        d = self.m._doc()
        d["sai"][0]["ts"] = time.time() - 10 * 86400
        self.m._ghi(d)
        self.cfg.data["mqtt"]["bai_hoc"] = {"han_ngay": 5}
        self.assertEqual(self.m.tra("câu nào đó dài dòng"), [],
                         "quá hạn 5 ngày thì thôi tính")


class BaoChuDongTest(unittest.TestCase):
    """Bản tin «em học được gì» — mặc định TẮT, bật thì chỉ kể khi có gì."""

    def setUp(self) -> None:
        import services.bai_hoc as m
        from services.config import config
        self.m, self.cfg = m, config
        self._tmp = Path(tempfile.mkdtemp())
        m._duong = lambda: self._tmp / "bai_hoc.json"
        config.data.setdefault("mqtt", {})["bai_hoc"] = {"bao": True}

    def tearDown(self) -> None:
        self.cfg.data.get("mqtt", {}).pop("bai_hoc", None)

    def test_MAC_DINH_TAT(self) -> None:
        """Không ai bật mà tự nhắn là làm phiền."""
        self.cfg.data["mqtt"]["bai_hoc"] = {}
        self.assertEqual(self.m.chay_mot_lan()["gui"], 0)

    def test_CHUA_HOC_GI_thi_KHONG_nhan(self) -> None:
        self.assertEqual(self.m.soan_bao(), "", "sổ rỗng thì không soạn tin")
        self.assertEqual(self.m.chay_mot_lan()["gui"], 0)

    def test_co_bai_hoc_thi_ke(self) -> None:
        self.m.ghi_sai("fingerprint#2 lần cuối lúc mấy giờ", "…", "_x")
        t = self.m.soan_bao()
        self.assertIn("học được gì", t)
        self.assertIn("fingerprint#2", t)

    def test_ke_ca_loai_da_chac_tay(self) -> None:
        for _ in range(6):
            self.m.ghi_dung("thời tiết", "_w")
        self.assertIn("chắc tay", self.m.soan_bao())

    def test_CHUA_TOI_HAN_thi_khong_nhan_lai(self) -> None:
        """Kể mỗi 7 ngày, không phải mỗi nhịp heartbeat 5 phút."""
        self.m.ghi_sai("câu nào đó dài dòng", "…", "_x")
        d = self.m._doc()
        d["bao_lan_cuoi"] = time.time()
        self.m._ghi(d)
        kq = self.m.chay_mot_lan()
        self.assertEqual(kq["gui"], 0)
        self.assertIn("chưa tới hạn", kq["ly_do"])

    def test_TAT_HOC_TAP_thi_cung_khong_bao(self) -> None:
        self.cfg.data["mqtt"]["bai_hoc"] = {"bat": False, "bao": True}
        self.assertEqual(self.m.chay_mot_lan()["gui"], 0)

    def test_CHON_KENH_DICH_DANH(self) -> None:
        """Nhà có nhiều tài khoản Zalo và nhiều nhóm — chọn mỗi "zalo" thì
        không biết là Zalo nào. Phải là khoá `plat:bot:chat` như «Lọc thread»."""
        self.cfg.data["mqtt"]["bai_hoc"] = {
            "bao": True, "kenh_nhan": ["zalop:4757:66427", "tg:8446:1003"]}
        self.assertEqual(self.m._kenh_nhan(), ["zalop:4757:66427", "tg:8446:1003"])

    def test_chua_chon_kenh_thi_rong(self) -> None:
        self.assertEqual(self.m._kenh_nhan(), [])

    def test_gui_dung_kenh_da_chon(self) -> None:
        from services import digest
        self.m.ghi_sai("câu nào đó dài dòng lắm", "…", "_x")
        self.cfg.data["mqtt"]["bai_hoc"] = {
            "bao": True, "kenh_nhan": ["zalop:4757:66427"]}
        with mock.patch.object(digest, "send_targets", return_value=1) as g:
            kq = self.m.chay_mot_lan()
        self.assertEqual(kq["gui"], 1)
        self.assertEqual(g.call_args[0][0], ["zalop:4757:66427"])


class VongKhepKinTest(unittest.TestCase):
    """Chủ máy bấm nút → bot ghi bài học → lần sau tự tránh đường tắt."""

    def setUp(self) -> None:
        import services.bai_hoc as m
        from services.agent import orchestrator as o
        self.m, self.o = m, o
        self._tmp = Path(tempfile.mkdtemp())
        m._duong = lambda: self._tmp / "bai_hoc.json"
        o._bo_do_cuoi.clear()

    def test_CA_THAT_11h53_hoc_mot_lan_tranh_mai(self) -> None:
        """Ca 10/09/2026: hỏi "fingerprint#2 lần cuối lúc mấy giờ", bot đáp giờ
        hiện tại. Chủ máy bấm «Chưa đúng» một lần."""
        self.o._bo_do_cuoi["u1"] = "_ha_local_lunar"
        kq = self.o._cham_diem_tra_loi(
            "bot trả lời chưa đúng: fingerprint#2 lần cuối lúc mấy giờ", "u1")
        self.assertIn("ghi lại", kq)

        # Chính câu đó: tránh
        self.assertTrue(self.m.tra("fingerprint#2 lần cuối lúc mấy giờ"))
        # Câu CHƯA TỪNG GẶP, khác chữ hoàn toàn, cùng ý: cũng tránh
        self.assertTrue(self.m.tra("ai mở cửa lúc mấy giờ"),
                        "đây là điểm khác căn bản với danh sách từ khoá")
        # Câu hỏi giờ bình thường: KHÔNG được chặn
        self.assertEqual(self.m.tra("mấy giờ rồi"), [])
        self.assertEqual(self.m.tra("thời tiết hôm nay"), [])

    def test_bam_DUNG_thi_bo_do_duoc_cong_diem(self) -> None:
        self.o._bo_do_cuoi["u1"] = "_ha_local_weather"
        self.o._cham_diem_tra_loi("dạ đúng rồi", "u1")
        self.assertEqual(
            self.m.thong_ke()["bo_do"]["_ha_local_weather"]["dung"], 1)

    def test_LUOT_DIEU_KHIEN_khong_duoc_nhuong_model(self) -> None:
        """Bản nháp vứt kết quả đường tắt khi có bài học — kể cả lượt ĐÃ BẬT
        ĐÈN THẬT. `_ha_local_intent` chạy `_exec_local_tool_calls` rồi mới trả
        về, nên vứt đi là lượt rơi xuống đường model và bật LẦN HAI.

        Khoá bằng cách đọc chính mã nguồn: điều kiện phải có `not fp_control`.
        """
        import inspect
        from services.agent import orchestrator as o
        src = inspect.getsource(o._orchestrate_locked)
        self.assertIn("if fp_text and not fp_control:", src,
                      "lượt điều khiển KHÔNG được nhường model — đèn đã bật rồi")

    def test_CAU_THUONG_khong_bi_coi_la_cham_diem(self) -> None:
        """Lượt bình thường phải đi tiếp như cũ, không bị nuốt."""
        for c in ("bật đèn bếp", "mấy giờ rồi", "đúng rồi anh ạ", ""):
            self.assertEqual(self.o._cham_diem_tra_loi(c, "u1"), "", c)


if __name__ == "__main__":
    unittest.main()
