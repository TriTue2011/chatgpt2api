"""Test tầng ghi lịch sử nhà.

Không chạm máy chủ thật: DB tạm trong tmp_path, mọi hàm gọi thẳng.
"""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


def _nap_module(thu_muc: str):
    """Trỏ DB của module vào thư mục tạm.

    KHÔNG dùng importlib.reload: reload kéo theo services.config nạp lại và
    làm mất CHATGPT2API_AUTH_KEY mà conftest đã đặt → mọi test hỏng vì lỗi
    xác thực chứ không phải vì logic sai.
    """
    import services.lich_su_nha as m

    m._reset_for_tests()          # đóng kết nối cũ TRƯỚC khi đổi đường dẫn
    m._DB_PATH = Path(thu_muc) / "lich_su_nha.sqlite"
    m._conn = None                # ép mở lại vào file mới
    return m


class LichSuNhaTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.m = _nap_module(self._tmp.name)
        self.m.config.data.setdefault("mqtt", {})["lich_su"] = {"bat": True}

    def tearDown(self) -> None:
        self.m._reset_for_tests()
        self._tmp.cleanup()

    # ── ghi thẳng (không qua hàng đợi) ─────────────────────────────────────
    def _ghi(self, *a, **kw) -> None:
        conn = self.m._db()
        self.m._ghi_thang(conn, *a, **kw)
        conn.commit()

    def test_su_kien_chi_ghi_khi_doi(self) -> None:
        """Ghi cùng giá trị nhiều lần chỉ ra MỘT bản ghi — chỗ 67 triệu rút còn 1,7."""
        now = time.time()
        for i in range(5):
            self._ghi("mqtt", "den_phong_khach", "state", "on", False, now + i)
        n = self.m._db().execute("SELECT COUNT(*) FROM su_kien").fetchone()[0]
        self.assertEqual(n, 1)

        self._ghi("mqtt", "den_phong_khach", "state", "off", False, now + 10)
        n = self.m._db().execute("SELECT COUNT(*) FROM su_kien").fetchone()[0]
        self.assertEqual(n, 2)

    def test_SU_KIEN_LAP_LAI_KHONG_BI_GOP(self) -> None:
        """Cùng người mở cửa hai lần là HAI lần về, không phải một.

        Lỗi thật 09/09/2026: luật "chỉ ghi khi đổi" đúng với cảm biến nhưng sai
        với sự kiện rời rạc — 48 lần mở cửa nạp vào chỉ còn 35, mất 13 lần, và
        phần học thói quen không đủ mẫu để dựng nếp.
        """
        now = time.time()
        for i in range(5):
            self._ghi("tuya", "khoa_cua", "nguoi_mo", "van_tay#11", False, now + i * 3600)
        n = self.m._db().execute(
            "SELECT COUNT(*) FROM su_kien WHERE truong='nguoi_mo'").fetchone()[0]
        self.assertEqual(n, 5, "mỗi lần mở cửa phải là một bản ghi riêng")

    def test_cam_bien_thuong_VAN_bi_gop(self) -> None:
        """Sửa cho sự kiện lặp lại KHÔNG được làm hỏng luật gộp của cảm biến."""
        now = time.time()
        for i in range(5):
            self._ghi("mqtt", "den", "state", "on", False, now + i)
        n = self.m._db().execute(
            "SELECT COUNT(*) FROM su_kien WHERE truong='state'").fetchone()[0]
        self.assertEqual(n, 1, "đèn báo 'on' 5 lần vẫn chỉ là một lần bật")

    def test_gia_tri_cu_duoc_luu(self) -> None:
        """Giai đoạn 2 cần biết chiều đổi (bot bật → người tắt ngay sau)."""
        now = time.time()
        self._ghi("mqtt", "den", "state", "on", False, now)
        self._ghi("mqtt", "den", "state", "off", False, now + 5)
        r = self.m._db().execute(
            "SELECT gia_tri, gia_tri_cu FROM su_kien ORDER BY ts DESC LIMIT 1").fetchone()
        self.assertEqual(r["gia_tri"], "off")
        self.assertEqual(r["gia_tri_cu"], "on")

    def test_do_ai_ghi_dung_cot(self) -> None:
        """Cột CỐT LÕI: không có nó thì bot học từ chính mình."""
        now = time.time()
        self._ghi("mqtt", "den", "state", "on", True, now)
        self._ghi("mqtt", "den", "state", "off", False, now + 5)
        rows = self.m._db().execute(
            "SELECT gia_tri, do_ai FROM su_kien ORDER BY ts").fetchall()
        self.assertEqual([(r["gia_tri"], r["do_ai"]) for r in rows],
                         [("on", 1), ("off", 0)])

    def test_linkquality_vao_so_do_khong_vao_su_kien(self) -> None:
        """Nếu sai chỗ này, 90 ngày sẽ phình — linkquality đổi 94 lần/phút."""
        now = time.time()
        for i in range(20):
            self._ghi("mqtt", "aptomat", "linkquality", 50 + i, False, now + i)
        sk = self.m._db().execute(
            "SELECT COUNT(*) FROM su_kien WHERE truong='linkquality'").fetchone()[0]
        sd = self.m._db().execute(
            "SELECT COUNT(*) FROM so_do WHERE truong='linkquality'").fetchone()[0]
        self.assertEqual(sk, 0, "linkquality KHÔNG được vào su_kien")
        self.assertGreater(sd, 0)

    def test_so_do_gop_dung_min_max_tb(self) -> None:
        now = time.time()
        for v in (10.0, 20.0, 30.0):
            self._ghi("mqtt", "cb", "temperature", v, False, now)
        r = self.m._db().execute("SELECT nho, lon, tb, n FROM so_do").fetchone()
        self.assertEqual((r["nho"], r["lon"], r["n"]), (10.0, 30.0, 3))
        self.assertAlmostEqual(r["tb"], 20.0)

    def test_tuoi_luon_la_gia_tri_moi_nhat(self) -> None:
        """Yêu cầu của chủ máy: hỏi thì phải lấy theo thời gian thực."""
        now = time.time()
        self._ghi("mqtt", "cb", "illuminance", 100, False, now)
        self._ghi("mqtt", "cb", "illuminance", 250, False, now + 1)
        t = self.m.doc_tuoi("cb")
        self.assertEqual(len(t), 1)
        self.assertEqual(t[0]["gia_tri"], "250")

    def test_truong_la_khong_bi_mat(self) -> None:
        """Bỏ trường lạ là mất vĩnh viễn — số → so_do, chữ → su_kien."""
        now = time.time()
        self._ghi("mqtt", "x", "truong_chua_tung_thay", "abc", False, now)
        self._ghi("mqtt", "x", "so_la_hoac", 42, False, now)
        sk = self.m._db().execute(
            "SELECT COUNT(*) FROM su_kien WHERE truong='truong_chua_tung_thay'").fetchone()[0]
        sd = self.m._db().execute(
            "SELECT COUNT(*) FROM so_do WHERE truong='so_la_hoac'").fetchone()[0]
        self.assertEqual(sk, 1)
        self.assertEqual(sd, 1)

    def test_gio_va_thu_theo_gio_VN(self) -> None:
        """168 ô phải theo giờ nhà, không phải UTC."""
        # 2026-09-09 08:30 giờ VN = thứ Tư (weekday 2)
        t = datetime(2026, 9, 9, 8, 30, tzinfo=timezone(timedelta(hours=7)))
        self._ghi("mqtt", "den", "state", "on", False, t.timestamp())
        r = self.m._db().execute("SELECT gio, thu FROM su_kien").fetchone()
        self.assertEqual(r["gio"], 8)
        self.assertEqual(r["thu"], 2)

    # ── không bao giờ làm chết gương ───────────────────────────────────────
    def test_ghi_khong_raise_khi_db_hong(self) -> None:
        """Ghi hỏng thì mất bản ghi, TUYỆT ĐỐI không được ném lỗi lên gương."""
        with mock.patch.object(self.m, "_db", side_effect=RuntimeError("đĩa hỏng")):
            try:
                self.m.ghi("mqtt", "den", "state", "on")
            except Exception as exc:
                self.fail(f"ghi() đã ném lỗi: {exc}")

    def test_ghi_khong_raise_khi_hang_day(self) -> None:
        with mock.patch.object(self.m._hang, "put_nowait",
                               side_effect=__import__("queue").Full):
            self.m.ghi("mqtt", "den", "state", "on")
        self.assertGreater(self.m._stats["bo"], 0)

    def test_ghi_bo_qua_truong_han(self) -> None:
        self.m.ghi("mqtt", "den", "last_seen", "2026-09-09")
        self.m.ghi("mqtt", "zigbee2mqtt/bridge/state", "state", "online")
        self.assertEqual(self.m._hang.qsize(), 0)

    def test_khong_bao_gio_ghi_mat_khau(self) -> None:
        """Lịch sử giữ 90 ngày và có API đọc ra — bí mật lọt vào là nằm đó rất lâu.

        Thiết bị ESP tự chế hay phát cả cấu hình (kèm mật khẩu) lên chủ đề
        trạng thái của chính nó, nên đây không phải tình huống giả tưởng.
        """
        mk = "MatKhauBiMat@123"
        now = time.time()
        for tb, tr in [("may_chu", "password"), ("esp", "mqtt_password"),
                       ("x", "api_token"), ("y", "wifi_psk"), ("z", "secret_key")]:
            self._ghi("mqtt", tb, tr, mk, False, now)
        self._ghi("mqtt", "den", "state", "on", False, now)

        conn = self.m._db()
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(FULL)")   # ép WAL xuống file chính
        raw = Path(self.m._DB_PATH).read_bytes()
        self.assertNotIn(mk.encode(), raw, "MẬT KHẨU LỌT XUỐNG ĐĨA")
        con = [r["thiet_bi"] for r in conn.execute("SELECT thiet_bi FROM su_kien")]
        self.assertEqual(con, ["den"], "chỉ bản ghi lành mới được giữ")

    # ── dọn ────────────────────────────────────────────────────────────────
    def test_don_xoa_dung_qua_han_giu_dung_trong_han(self) -> None:
        now = time.time()
        self._ghi("mqtt", "den", "state", "on", False, now - 200 * 86400)
        self._ghi("mqtt", "den", "state", "off", False, now - 1 * 86400)
        self.m.don()
        rows = self.m._db().execute("SELECT gia_tri FROM su_kien").fetchall()
        self.assertEqual([r["gia_tri"] for r in rows], ["off"])

    # ── nạp lịch sử HA ─────────────────────────────────────────────────────
    def _gia_lap_ha(self):
        now = datetime.now(timezone.utc)
        return [[
            {"entity_id": "light.phong_khach", "state": "on",
             "last_changed": (now - timedelta(hours=5)).isoformat()},
            {"entity_id": "light.phong_khach", "state": "unavailable",
             "last_changed": (now - timedelta(hours=4)).isoformat()},
            {"entity_id": "light.phong_khach", "state": "off",
             "last_changed": (now - timedelta(hours=3)).isoformat()},
        ]]

    def test_nap_tu_ha_chay_hai_lan_khong_nhan_doi(self) -> None:
        """UNIQUE(thiet_bi, truong, ts) phải chặn — chủ máy sẽ bấm nút nhiều lần."""
        with mock.patch.object(self.m, "_ha_lay", return_value=self._gia_lap_ha()):
            a = self.m.nap_tu_ha(7, thuc_the=["light.phong_khach"])
            b = self.m.nap_tu_ha(7, thuc_the=["light.phong_khach"])
        self.assertEqual(a["nap"], 2, "2 giá trị tốt, bỏ 1 unavailable")
        self.assertEqual(b["nap"], 0, "lần hai không được nạp thêm")
        n = self.m._db().execute("SELECT COUNT(*) FROM su_kien").fetchone()[0]
        self.assertEqual(n, 2)

    def test_nap_tu_ha_danh_dau_nguon_va_do_ai(self) -> None:
        """/api/history không biết ai bật → phải là do_ai=0, nguon='ha_nhap'."""
        with mock.patch.object(self.m, "_ha_lay", return_value=self._gia_lap_ha()):
            self.m.nap_tu_ha(7, thuc_the=["light.phong_khach"])
        rows = self.m._db().execute("SELECT nguon, do_ai FROM su_kien").fetchall()
        self.assertTrue(all(r["nguon"] == "ha_nhap" and r["do_ai"] == 0 for r in rows))

    def test_nap_tu_ha_bo_unavailable(self) -> None:
        with mock.patch.object(self.m, "_ha_lay", return_value=self._gia_lap_ha()):
            kq = self.m.nap_tu_ha(7, thuc_the=["light.phong_khach"])
        self.assertEqual(kq["bo_qua"], 1)
        gt = [r["gia_tri"] for r in
              self.m._db().execute("SELECT gia_tri FROM su_kien ORDER BY ts")]
        self.assertEqual(gt, ["on", "off"])

    # ── soi hỏng ───────────────────────────────────────────────────────────
    def test_soi_hong_bat_duoc_cam_bien_do(self) -> None:
        """Đúng ca thật: phòng học VẪN GỬI TIN ĐỀU nhưng lux đứng yên ở 86.

        Đây là loại nguy hiểm hơn chết hẳn: nhìn vào tưởng còn chạy. Phải phân
        biệt với 'chet' (im lặng hoàn toàn) — hai cách chữa khác nhau.
        """
        now = time.time()
        for i in range(48):  # gửi đều 2 ngày, giá trị KHÔNG ĐỔI
            self._ghi("mqtt", "hien_dien_phong_hoc", "illuminance", 86,
                      False, now - i * 3600)
        ra = self.m.soi_hong(7)
        do = [x for x in ra if x["loai"] == "do" and "phong_hoc" in x["thiet_bi"]]
        self.assertTrue(do, f"phải phát hiện cảm biến ĐƠ, nhận được: {ra}")

    def test_soi_hong_phan_biet_chet_voi_do(self) -> None:
        """Im lặng hẳn = 'chet'; vẫn gửi mà giá trị đứng yên = 'do'."""
        now = time.time()
        self._ghi("mqtt", "cb_im", "illuminance", 50, False, now - 6 * 86400)
        loai = {x["thiet_bi"]: x["loai"] for x in self.m.soi_hong(7)}
        self.assertEqual(loai.get("cb_im"), "chet")

    def test_soi_hong_khong_bao_nham_cam_bien_khoe(self) -> None:
        now = time.time()
        for i in range(10):
            self._ghi("mqtt", "cb_tot", "illuminance", 50 + i * 7, False, now - i * 600)
        ra = self.m.soi_hong(7)
        self.assertFalse([x for x in ra if x["thiet_bi"] == "cb_tot"],
                         "cảm biến đang đổi giá trị đều thì không được báo hỏng")

    def test_soi_hong_ngach_pin_khac_ngach_lux(self) -> None:
        """Pin không đổi 10 ngày là bình thường; lux không đổi 10 ngày là hỏng."""
        now = time.time()
        self._ghi("mqtt", "cb_a", "battery", 98, False, now - 10 * 86400)
        self._ghi("mqtt", "cb_b", "illuminance", 86, False, now - 10 * 86400)
        loai = {x["thiet_bi"]: x["loai"] for x in self.m.soi_hong(30)}
        self.assertNotIn("cb_a", loai, "pin đứng yên 10 ngày là bình thường")
        self.assertIn("cb_b", loai, "lux đứng yên 10 ngày là hỏng")

    def test_soi_hong_bat_ca_thiet_bi_IM_LANG_ngoai_cua_so(self) -> None:
        """Cảm biến hỏng LÂU không có bản ghi nào trong cửa sổ.

        Lỗi thật đã gặp: lọc "ts >= cửa sổ" lúc gom danh sách thì loại đúng cái
        cần tìm — cảm biến phòng học im 9 ngày biến mất khỏi kết quả soi 9 ngày.
        """
        now = time.time()
        self._ghi("mqtt", "cb_chet_lau", "illuminance", 86, False, now - 20 * 86400)
        ten = [x["thiet_bi"] for x in self.m.soi_hong(7)]
        self.assertIn("cb_chet_lau", ten,
                      "thiết bị im lặng lâu hơn cửa sổ vẫn PHẢI bị bắt")

    def test_nguong_tra_theo_ten_thiet_bi(self) -> None:
        """Dữ liệu nạp từ HA có trường luôn là 'state', loại nằm trong TÊN.

        Chỉ tra theo trường thì mọi cảm biến HA rơi về mặc định 7 ngày.
        """
        self.assertEqual(self.m._nguong("sensor.abc_illuminance", "state"),
                         self.m._NGUONG_DO_GIAY["illuminance"])
        self.assertEqual(self.m._nguong("sensor.abc_battery", "state"),
                         self.m._NGUONG_DO_GIAY["battery"])
        self.assertEqual(self.m._nguong("light.khong_ro", "state"),
                         self.m._NGUONG_DO_MAC_DINH)

    def test_nap_tu_ha_ghi_ca_bang_tuoi(self) -> None:
        """soi_hong đo im lặng từ bảng tuoi — không ghi thì không soi ra được."""
        with mock.patch.object(self.m, "_ha_lay", return_value=self._gia_lap_ha()):
            self.m.nap_tu_ha(7, thuc_the=["light.phong_khach"])
        t = self.m.doc_tuoi("light.phong_khach")
        self.assertTrue(t, "nạp xong phải có hàng trong bảng tuoi")
        self.assertEqual(t[0]["gia_tri"], "off", "phải là giá trị MỚI NHẤT")

    def test_soi_hong_bat_chap_chon(self) -> None:
        now = time.time()
        for i in range(20):
            gt = "unavailable" if i % 2 == 0 else str(i)
            self._ghi("mqtt", "cb_chap", "temperature", gt, False, now - i * 3600)
        cc = [x for x in self.m.soi_hong(7) if x["loai"] == "chap_chon"]
        self.assertTrue(cc, "phải bắt được cảm biến chập chờn")

    # ── frigate ────────────────────────────────────────────────────────────
    def test_frigate_chi_ghi_bat_dau_va_ket_thuc(self) -> None:
        """Chủ máy chốt: bỏ 'update' — Frigate phát 208 tin/40 giây."""
        now = time.time()
        for loai in ("new", "update", "update", "end"):
            self.m.ghi_frigate({"type": loai, "after": {
                "camera": "phong_khach", "label": "person",
                "start_time": now, "end_time": now + 30}})
        self.assertEqual(self.m._hang.qsize(), 2)

    # ── thống kê ───────────────────────────────────────────────────────────
    def test_thong_ke_khong_raise_khi_db_hong(self) -> None:
        with mock.patch.object(self.m, "_db", side_effect=RuntimeError("hỏng")):
            kq = self.m.thong_ke()
        self.assertIn("loi", kq)

    def test_luong_nen_ghi_that(self) -> None:
        """Đường đầy đủ: ghi() → hàng đợi → luồng nền → đĩa."""
        self.assertTrue(self.m.start())
        try:
            self.m.ghi("mqtt", "den_test", "state", "on")

            # Đọc PHẢI qua _khoa_db, y như mọi hàm đọc thật trong module.
            # Đọc thẳng _db() song song với luồng nền đang ghi lô → SQLite
            # "database is locked". Đây là lý do doc_su_kien/thong_ke đều
            # giữ khoá chứ không phải cho vui.
            def _dem() -> int:
                with self.m._khoa_db:
                    return self.m._db().execute(
                        "SELECT COUNT(*) FROM su_kien WHERE thiet_bi='den_test'"
                    ).fetchone()[0]

            for _ in range(50):
                if _dem():
                    break
                time.sleep(0.1)
            self.assertEqual(_dem(), 1)
        finally:
            self.m.stop()



class PhanBietDieuHoaVaAptomat(unittest.TestCase):
    """"Bật điều hoà" trỏ vào HAI thiết bị khác nhau → phải hỏi lại.

    Nhà chủ máy có `climate.dieu_hoa_panasonic` (máy lạnh) VÀ
    `switch.aptomat_dieu_hoa_phong_ngu` (aptomat cấp điện). Đoán sai theo chiều
    nào cũng hỏng: tắt nhầm aptomat là cắt điện cả máy; aptomat đang tắt mà bật
    máy lạnh thì bấm mãi không lên.
    """

    THAT = [
        {"entity_id": "climate.dieu_hoa_panasonic", "state": "cool",
         "attributes": {"friendly_name": "Điều hòa Panasonic"}},
        {"entity_id": "switch.aptomat_dieu_hoa_phong_ngu", "state": "on",
         "attributes": {"friendly_name": "Aptomat điều hòa phòng ngủ"}},
    ]

    def _hoi(self, cau, states=None):
        from services import ha_client
        from services.agent import capabilities as cap
        with mock.patch.object(ha_client, "get_states",
                               return_value=self.THAT if states is None else states):
            return cap._lan_lon_dieu_hoa(cau)

    def test_cau_mo_ho_thi_hoi_lai(self) -> None:
        for cau in ("bật điều hòa", "tắt điều hoà", "mở điều hòa"):
            self.assertIsNotNone(self._hoi(cau), f"{cau!r} phải hỏi lại")

    def test_CHU_BAT_KHONG_DUOC_COI_LA_CONG_TAC(self) -> None:
        """Lỗi thật đã gặp: "at" nằm trong từ khoá công tắc, mà "bật" chứa "at"
        → mọi câu "bật …" bị tưởng đã nói rõ, nhánh hỏi lại không bao giờ chạy.
        """
        self.assertIsNotNone(self._hoi("bật điều hòa"),
                             "chữ 'bật' KHÔNG được coi là đã nêu công tắc")

    def test_noi_ro_thi_di_thang(self) -> None:
        for cau in ("bật aptomat điều hòa", "bật công tắc điều hòa",
                    "bật điều hòa 25 độ", "bật máy lạnh"):
            self.assertIsNone(self._hoi(cau), f"{cau!r} đã rõ, không được hỏi lại")

    def test_khong_lien_quan_thi_khong_hoi(self) -> None:
        self.assertIsNone(self._hoi("bật đèn phòng khách"))

    def test_nha_chi_co_may_lanh_thi_khong_hoi(self) -> None:
        """Không có aptomat riêng thì chẳng có gì để nhầm."""
        self.assertIsNone(self._hoi("bật điều hòa", states=self.THAT[:1]))

    def test_bao_them_khi_aptomat_dang_TAT(self) -> None:
        """Aptomat tắt thì bật máy lạnh vô ích — phải nói cho người dùng biết."""
        st = [self.THAT[0], {**self.THAT[1], "state": "off"}]
        r = self._hoi("bật điều hòa", states=st)
        self.assertIn("đang TẮT", r["text"])

    def test_ha_loi_thi_khong_chan_duong(self) -> None:
        from services import ha_client
        from services.agent import capabilities as cap
        with mock.patch.object(ha_client, "get_states",
                               side_effect=RuntimeError("HA sập")):
            self.assertIsNone(cap._lan_lon_dieu_hoa("bật điều hòa"))

if __name__ == "__main__":
    unittest.main()


class UuTienMqttTest(unittest.TestCase):
    """Nhánh ưu tiên MQTT trong control_home.

    Luật sống còn: KHÔNG chắc thì trả None để rơi về Home Assistant. Đoán bừa
    ở đây là bật nhầm thiết bị trong nhà người ta.
    """

    def setUp(self) -> None:
        from services.agent import capabilities as cap
        self.cap = cap

    def _gia_lap(self, ten_khop: str, dieu_khien: list[str]):
        """Giả lập mqtt_nha với đúng cấu trúc danh_sach_thiet_bi() thật."""
        from services import mqtt_nha

        return [
            mock.patch.object(mqtt_nha, "_khop_ten", return_value=ten_khop),
            mock.patch.object(mqtt_nha, "danh_sach_thiet_bi", return_value=[
                {"ten": ten_khop or "x", "nguon": "tu_khai_bao", "doc": [],
                 "dieu_khien": [{"ten": t} for t in dieu_khien]}]),
        ]

    def test_nhuong_ha_khi_ten_map_mo(self) -> None:
        """_khop_ten trả '' nghĩa là mập mờ → phải nhường HA, không đoán."""
        for p in self._gia_lap("", ["state"]):
            p.start()
            self.addCleanup(p.stop)
        self.assertIsNone(self.cap._thu_mqtt_truoc("bật đèn"))

    def test_nhuong_ha_khi_nhieu_cong_tac(self) -> None:
        """Đèn 3 công tắc: không biết bật cái nào → nhường HA."""
        for p in self._gia_lap("Đèn phòng khách", ["state_l1", "state_l2", "state_l3"]):
            p.start()
            self.addCleanup(p.stop)
        self.assertIsNone(self.cap._thu_mqtt_truoc("bật đèn phòng khách"))

    def test_nhuong_ha_khi_khong_ro_bat_hay_tat(self) -> None:
        for p in self._gia_lap("Đèn phòng khách", ["state"]):
            p.start()
            self.addCleanup(p.stop)
        self.assertIsNone(self.cap._thu_mqtt_truoc("đèn phòng khách thế nào"))
        # có CẢ bật lẫn tắt trong một câu → câu phức, để HA lo
        self.assertIsNone(self.cap._thu_mqtt_truoc("bật đèn rồi tắt quạt"))

    def test_nhuong_ha_khi_gui_lenh_hong(self) -> None:
        """MQTT gửi hỏng thì vẫn phải rơi về HA, không báo lỗi cho người dùng."""
        from services import mqtt_nha
        for p in self._gia_lap("Đèn phòng khách", ["state"]):
            p.start()
            self.addCleanup(p.stop)
        with mock.patch.object(mqtt_nha, "dieu_khien",
                               side_effect=RuntimeError("mất mạng")):
            self.assertIsNone(self.cap._thu_mqtt_truoc("bật đèn phòng khách"))

    def test_nhan_lenh_khi_khop_chinh_xac(self) -> None:
        from services import mqtt_nha
        for p in self._gia_lap("Đèn phòng khách", ["state"]):
            p.start()
            self.addCleanup(p.stop)
        with mock.patch.object(mqtt_nha, "dieu_khien", return_value=True) as dk:
            kq = self.cap._thu_mqtt_truoc("bật đèn phòng khách")
        self.assertIsNotNone(kq)
        self.assertIn("MQTT", kq["text"])
        dk.assert_called_once_with("Đèn phòng khách", "state", True)

    def test_tat_truyen_gia_tri_False(self) -> None:
        from services import mqtt_nha
        for p in self._gia_lap("Quạt", ["state"]):
            p.start()
            self.addCleanup(p.stop)
        with mock.patch.object(mqtt_nha, "dieu_khien", return_value=True) as dk:
            self.cap._thu_mqtt_truoc("tắt quạt")
        dk.assert_called_once_with("Quạt", "state", False)

    def test_uu_tien_tat_thi_khong_dung_mqtt(self) -> None:
        """Ô tích tắt (mặc định) → control_home không được ngó tới MQTT."""
        from services import mqtt_nha
        self.assertFalse(mqtt_nha.uu_tien_mqtt(),
                         "mặc định phải TẮT — bật sẵn là đổi hành vi sau lưng chủ máy")
