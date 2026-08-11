"""Theo dõi bão: phân cấp, dự báo đổ bộ, và ba khoảng cách dùng để xếp hạng.

Không gọi mạng — `_get_json` bị thay bằng bộ dữ liệu giả có hình dạng ĐÚNG như
endpoint thật của Windy (đo 12/08/2026): `history` xếp mới nhất trước,
`forecast[].records` xếp tương lai XA trước, gió m/s, áp suất Pascal.

Ba chỗ dễ sai nhất, mỗi chỗ một test:
- `records` để nguyên thứ tự feed thì báo lần áp bờ CUỐI → sai tỉnh, trễ cả ngày.
- Cơn ở miền Nam bị coi là xa khi chủ nhà ở Hà Nội → không được tải đường đi →
  không có dự báo đổ bộ nào để hiện.
- Không gọi được Windy mà lại trả "không có bão" — đang bão thì đó là kiểu sai
  tệ nhất.
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import thoi_tiet_bao as tb  # noqa: E402

HA_NOI = (21.03, 105.85)

# Bão mạnh ngoài Biển Đông, đường JMA vòng vào Quảng Bình.
YAGI = {"id": "yagi", "name": "Yagi", "lat": 17.0, "lon": 112.0,
        "strength": 1, "windSpeed": 30.0}
# Áp thấp yếu trong vịnh Bắc Bộ — GẦN Hà Nội hơn Yagi, nhưng không đổ bộ.
AP_THAP = {"id": "ap-thap", "name": "Ap Thap", "lat": 21.5, "lon": 108.5,
           "strength": 0, "windSpeed": 12.0}
# Cơn ở tây bắc Thái Bình Dương, ngoài bán kính quan tâm.
XA = {"id": "xa", "name": "Xa", "lat": 30.0, "lon": 160.0,
      "strength": 0, "windSpeed": 20.0}

CHI_TIET_YAGI = {
    **YAGI,
    # Mới nhất trước, như feed thật.
    "history": [
        {"lat": 17.0, "lon": 112.0, "windSpeed": 30.0,
         "pressure": 96000.0, "time": "2026-08-12T06:00:00+00:00"},
        {"lat": 16.5, "lon": 112.6, "windSpeed": 28.0,
         "pressure": 96500.0, "time": "2026-08-12T00:00:00+00:00"},
    ],
    "forecast": [
        # ecmwf đứng TRƯỚC trong feed nhưng jma phải thắng theo thứ tự tin cậy.
        # Điểm này cách Nghệ An 64 km — cũng lọt ngưỡng 80 km, nên nếu ưu tiên mô
        # hình sai thì test bắt được ngay bằng tên tỉnh.
        {"modelIdentifier": "ecmwf", "reftime": "2026-08-12T00:00:00+00:00",
         "records": [
             {"lat": 18.9, "lon": 105.2, "windSpeed": 22.0,
              "pressure": 98000.0, "time": "2026-08-14T00:00:00+00:00"},
         ]},
        # Tương lai XA trước, như feed thật.
        {"modelIdentifier": "jma", "reftime": "2026-08-12T03:00:00+00:00",
         "records": [
             {"lat": 18.5, "lon": 105.5, "windSpeed": 18.0,
              "pressure": 98500.0, "time": "2026-08-14T00:00:00+00:00"},
             {"lat": 17.4, "lon": 107.0, "windSpeed": 28.0,
              "pressure": 96500.0, "time": "2026-08-13T12:00:00+00:00"},
             {"lat": 16.8, "lon": 110.0, "windSpeed": 30.0,
              "pressure": 96000.0, "time": "2026-08-13T00:00:00+00:00"},
         ]},
    ],
}

CHI_TIET_AP_THAP = {
    **AP_THAP,
    "history": [
        {"lat": 21.5, "lon": 108.5, "windSpeed": 12.0,
         "pressure": 100200.0, "time": "2026-08-12T06:00:00+00:00"},
        {"lat": 21.3, "lon": 109.1, "windSpeed": 11.0,
         "pressure": 100300.0, "time": "2026-08-12T00:00:00+00:00"},
    ],
    "forecast": [],  # không có đường đi → không có dự báo đổ bộ
}


def _gia_lap(bao_list, chi_tiet=None, hong=False):
    """Trả một hàm thay cho `_get_json`, phục vụ theo URL."""
    chi_tiet = chi_tiet or {}

    def _fake(url):
        if hong:
            return None
        if url == tb.WINDY_STORMS_URL:
            return {"storms": bao_list, "defaultCircles": {"24": 74000.0}}
        for sid, du_lieu in chi_tiet.items():
            if url.endswith("/" + sid):
                return du_lieu
        return None
    return _fake


class PhanCapTests(unittest.TestCase):

    def test_phan_cap_theo_thang_viet_nam(self):
        """Bản tin Việt Nam đọc bão theo Beaufort, không phải Saffir-Simpson."""
        for gio_ms, mong in ((60.0, "Siêu bão"), (51.0, "Siêu bão"),
                             (35.0, "Bão rất mạnh"), (26.0, "Bão mạnh"),
                             (18.0, "Bão"), (11.0, "Áp thấp nhiệt đới"),
                             (5.0, "Vùng áp thấp")):
            with self.subTest(gio_ms=gio_ms):
                self.assertEqual(tb.phan_cap_bao(gio_ms), mong)

    def test_thieu_gio_thi_khong_bia_cap(self):
        self.assertIsNone(tb.phan_cap_bao(None))
        self.assertIsNone(tb.cap_beaufort(None))

    def test_gio_dia_phuong_doi_sang_gio_viet_nam(self):
        """Windy đóng dấu UTC; in thẳng ra là sớm 7 tiếng, hay lệch sang ngày khác."""
        self.assertEqual(tb.gio_dia_phuong("2026-08-13T12:00:00+00:00"),
                         "19:00 13/08")
        self.assertEqual(tb.gio_dia_phuong("2026-08-13T18:00:00+00:00"),
                         "01:00 14/08")
        self.assertIsNone(tb.gio_dia_phuong(None))


class DuDoanDoBoTests(unittest.TestCase):

    def test_uu_tien_jma_hon_ecmwf(self):
        du_bao = {
            "ecmwf": {"track": [{"latitude": 18.9, "longitude": 105.2,
                                 "time": "2026-08-14T00:00:00+00:00"}]},
            "jma": {"track": [{"latitude": 17.4, "longitude": 107.0,
                               "time": "2026-08-13T12:00:00+00:00"}]},
        }
        vao_bo = tb.du_doan_vao_bo(du_bao)
        self.assertEqual(vao_bo["model"], "jma")
        self.assertEqual(vao_bo["tinh"], "Quảng Bình")

    def test_diem_xa_bo_thi_khong_ket_luan_do_bo(self):
        du_bao = {"jma": {"track": [{"latitude": 16.8, "longitude": 110.0,
                                     "time": "2026-08-13T00:00:00+00:00"}]}}
        self.assertIsNone(tb.du_doan_vao_bo(du_bao))

    def test_bo_gan_nhat_khong_phu_thuoc_vi_tri_nguoi_hoi(self):
        tinh, cach = tb.bo_gan_nhat(17.4, 107.0)
        self.assertEqual(tinh, "Quảng Bình")
        self.assertLess(cach, 80.0)


class DanhSachBaoTests(unittest.TestCase):

    def setUp(self):
        self._that = tb._get_json
        tb._CACHE.clear()

    def tearDown(self):
        tb._get_json = self._that
        tb._CACHE.clear()

    def _chay(self, bao_list=None, chi_tiet=None, hong=False, toa_do=HA_NOI):
        tb._get_json = _gia_lap(
            bao_list if bao_list is not None else [YAGI, AP_THAP, XA],
            chi_tiet if chi_tiet is not None else {"yagi": CHI_TIET_YAGI,
                                                   "ap-thap": CHI_TIET_AP_THAP},
            hong=hong)
        return tb.danh_sach_bao(*(toa_do or (None, None)))

    def _tim(self, dl, sid):
        return next(b for b in dl["storms"] if b["id"] == sid)

    def test_records_xep_nguoc_van_ra_diem_cham_bo_dau_tien(self):
        """Feed xếp tương lai xa trước. Để nguyên thì báo Nghệ An 14/08 (lần áp bờ
        cuối) thay vì Quảng Bình 13/08 — sai tỉnh và trễ cả ngày."""
        yagi = self._tim(self._chay(), "yagi")
        self.assertEqual(yagi["vao_bo"]["tinh"], "Quảng Bình")
        self.assertEqual(yagi["vao_bo"]["time"], "2026-08-13T12:00:00+00:00")

    def test_ba_khoang_cach_deu_co_va_cach_min_lay_nho_nhat(self):
        yagi = self._tim(self._chay(), "yagi")
        self.assertAlmostEqual(yagi["cach_nha_km"], 786.5, places=0)
        self.assertAlmostEqual(yagi["cach_diem_do_bo_km"], 533.0, places=0)
        self.assertAlmostEqual(yagi["do_bo_cach_nha_km"], 421.3, places=0)
        self.assertAlmostEqual(yagi["cach_min_km"], 421.3, places=0)
        self.assertEqual(yagi["co_so_min"], "do_bo_toi_nha")

    def test_khong_do_bo_thi_khong_co_hai_so_do_bo(self):
        ap_thap = self._tim(self._chay(), "ap-thap")
        self.assertIsNone(ap_thap["vao_bo"])
        self.assertNotIn("cach_diem_do_bo_km", ap_thap)
        self.assertNotIn("do_bo_cach_nha_km", ap_thap)
        self.assertEqual(ap_thap["co_so_min"], "nha")

    def test_gan_toi_khac_voi_do_bo_gan_toi_va_sap_do_bo(self):
        """Ba câu hỏi khác nhau cho ra hai cơn khác nhau — đúng ý người dùng."""
        dl = self._chay()
        self.assertEqual(dl["gan_nha"]["id"], "ap-thap")
        self.assertEqual(tb.bao_do_bo_gan_nguoi_hoi(dl)["id"], "yagi")
        self.assertEqual(tb.bao_sap_do_bo(dl)["id"], "yagi")

    def test_huong_di_chuyen_suy_tu_hai_diem_moi_nhat(self):
        yagi = self._tim(self._chay(), "yagi")
        self.assertEqual(yagi["huong_di"], "Tây Bắc")
        self.assertIsNotNone(yagi["toc_do_kmh"])
        self.assertIn("Tây Bắc", yagi["di_chuyen_text"])

    def test_con_ngoai_ban_kinh_khong_bi_tai_duong_di(self):
        """Mỗi cơn tải chi tiết là thêm 1 request; cơn ở Thái Bình Dương không đáng."""
        xa = self._tim(self._chay(), "xa")
        self.assertNotIn("co_chi_tiet", xa)

    def test_khong_goi_duoc_windy_thi_khong_noi_khong_co_bao(self):
        dl = self._chay(hong=True)
        self.assertFalse(dl["available"])
        self.assertEqual(dl["count"], 0)
        tb._get_json = _gia_lap([], hong=True)
        self.assertEqual(tb.tra_loi_bao("tong_quan", *HA_NOI), "")

    def test_troi_yen_that_thi_noi_ro_la_khong_co_bao(self):
        dl = self._chay(bao_list=[])
        self.assertTrue(dl["available"])
        self.assertEqual(dl["count"], 0)
        self.assertIn("không có cơn bão", tb.tra_loi_bao("tong_quan", *HA_NOI))

    def test_qua_han_thi_bo_tai_them_chu_khong_bao_het_bao(self):
        """Windy chậm thì dừng tải quỹ đạo, nhưng danh sách bão phải còn nguyên —
        tuyệt đối không được biến thành "không có bão"."""
        dl = self._chay_voi_han(han_giay=-1.0)  # hết hạn ngay từ cơn đầu
        self.assertTrue(dl["available"])
        self.assertEqual(dl["count"], 3)
        self.assertFalse(any(b.get("co_chi_tiet") for b in dl["storms"]))
        self.assertIsNone(tb.bao_sap_do_bo(dl))

    def _chay_voi_han(self, han_giay):
        tb._get_json = _gia_lap([YAGI, AP_THAP, XA],
                                {"yagi": CHI_TIET_YAGI,
                                 "ap-thap": CHI_TIET_AP_THAP})
        return tb.danh_sach_bao(*HA_NOI, han_giay=han_giay)

    def test_toa_do_null_trong_feed_khong_lam_no_phep_tinh(self):
        """Feed không có tài liệu chính thức; một toạ độ null từng làm hỏng cả lượt."""
        loi = {"id": "loi", "name": "Loi", "lat": None, "lon": None,
               "strength": 0, "windSpeed": None}
        dl = self._chay(bao_list=[loi, YAGI], chi_tiet={"yagi": CHI_TIET_YAGI})
        self.assertEqual(dl["count"], 2)
        self.assertEqual(dl["dang_lo_nhat"]["id"], "yagi")


class BaoMienNamTests(unittest.TestCase):
    """Cơn sắp đổ bộ Cà Mau vẫn phải được tính, dù chủ nhà ở Hà Nội.

    Đây là điểm yếu của bản gốc: nó chọn cơn để tải đường đi theo khoảng cách tới
    NHÀ, nên ba cơn lảng vảng gần Hà Nội chiếm hết ba suất và cơn ở miền Nam không
    bao giờ có `vao_bo`.
    """

    CA_MAU = {"id": "ca-mau", "name": "Ca Mau Storm", "lat": 8.0, "lon": 106.0,
              "strength": 1, "windSpeed": 28.0}
    CHI_TIET_CA_MAU = {
        **CA_MAU,
        "history": [
            {"lat": 8.0, "lon": 106.0, "windSpeed": 28.0,
             "pressure": 97000.0, "time": "2026-08-12T06:00:00+00:00"},
            {"lat": 7.8, "lon": 106.9, "windSpeed": 27.0,
             "pressure": 97200.0, "time": "2026-08-12T00:00:00+00:00"},
        ],
        "forecast": [
            {"modelIdentifier": "jma", "reftime": "2026-08-12T03:00:00+00:00",
             "records": [
                 {"lat": 8.7, "lon": 105.1, "windSpeed": 25.0,
                  "pressure": 97500.0, "time": "2026-08-13T06:00:00+00:00"},
             ]},
        ],
    }

    def setUp(self):
        self._that = tb._get_json
        tb._CACHE.clear()

    def tearDown(self):
        tb._get_json = self._that
        tb._CACHE.clear()

    def test_ba_con_gan_ha_noi_khong_chiem_het_suat_tai_chi_tiet(self):
        gan_hn = [
            {"id": f"gan{i}", "name": f"Gan {i}", "lat": 21.0 + i * 0.5,
             "lon": 109.0 + i * 0.5, "strength": 0, "windSpeed": 10.0}
            for i in range(3)
        ]
        tb._get_json = _gia_lap(gan_hn + [self.CA_MAU],
                                {"ca-mau": self.CHI_TIET_CA_MAU})
        dl = tb.danh_sach_bao(*HA_NOI)
        ca_mau = next(b for b in dl["storms"] if b["id"] == "ca-mau")
        self.assertTrue(ca_mau.get("co_chi_tiet"),
                        "cơn ở miền Nam không được tải đường đi")
        self.assertEqual(ca_mau["vao_bo"]["tinh"], "Cà Mau")
        self.assertEqual(tb.bao_sap_do_bo(dl)["id"], "ca-mau")


class YDinhCauHoiTests(unittest.TestCase):
    """Nhận ý câu hỏi về bão. Chỗ dễ hỏng nhất là chữ "bao" khi bỏ dấu:
    bao nhiêu / bao giờ / thông báo / báo cáo / bảo vệ / báo thức / còn bao lâu
    đều thành "bao" mà không cái nào nói về bão."""

    def _y(self, cau):
        from services.ha_client import _fold_diacritics
        return tb.y_dinh_cau_hoi(cau, _fold_diacritics(cau).replace("đ", "d"))

    def test_tung_y_dinh_ung_voi_kieu_cau_hoi(self):
        for cau, mong in (
                ("có bão không", "tong_quan"),
                ("tình hình bão thế nào", "tong_quan"),
                ("bão gần tôi nhất", "gan_toi"),
                ("bão cách đây bao nhiêu km", "gan_toi"),
                ("bão đổ bộ gần tôi nhất vào đâu", "do_bo_gan_toi"),
                ("bão số 3 vào tỉnh nào", "do_bo_gan_toi"),
                ("bão sắp vào Việt Nam chưa", "sap_do_bo"),
                ("khi nào bão vào bờ", "sap_do_bo"),
                ("bão đổ bộ chưa", "sap_do_bo"),
                ("bão còn cách bao xa thì vào đất liền", "con_cach_bao_xa"),
                ("đang có mấy cơn bão", "so_luong")):
            with self.subTest(cau=cau):
                self.assertEqual(self._y(cau), mong)

    def test_go_khong_dau_van_nhan_ra(self):
        for cau, mong in (("co bao khong", "tong_quan"),
                          ("may con bao dang hoat dong", "so_luong"),
                          ("bao so 3 vao dau", "do_bo_gan_toi"),
                          # "ở đâu" hỏi vị trí HIỆN TẠI, "vào đâu" hỏi nơi đổ bộ.
                          ("ap thap nhiet doi o dau", "gan_toi")):
            with self.subTest(cau=cau):
                self.assertEqual(self._y(cau), mong)

    def test_cac_chu_bao_khac_khong_bi_bat_lam_cau_hoi_bao(self):
        for cau in ("bây giờ là bao nhiêu độ",
                    "còn bao lâu nữa thì xong",
                    "thông báo cho tôi biết",
                    "đặt báo thức 6 giờ",
                    "báo cáo doanh thu tháng này",
                    "bảo vệ dữ liệu thế nào",
                    "mua bảo hiểm ở đâu",
                    "thời tiết Hà Nội hôm nay",
                    "khi nào thì trời mưa",
                    "bao gio thi xong viec",
                    "con bao lau nua thi den",
                    "co bao gi khong"):
            with self.subTest(cau=cau):
                self.assertIsNone(self._y(cau), f"bắt oan: {cau}")


class CauTraLoiTests(unittest.TestCase):

    def setUp(self):
        self._that = tb._get_json
        tb._CACHE.clear()
        tb._get_json = _gia_lap([YAGI, AP_THAP, XA],
                                {"yagi": CHI_TIET_YAGI,
                                 "ap-thap": CHI_TIET_AP_THAP})

    def tearDown(self):
        tb._get_json = self._that
        tb._CACHE.clear()

    def test_gan_toi_tra_ve_con_gan_nhat_kem_khoang_cach(self):
        cau = tb.tra_loi_bao("gan_toi", *HA_NOI)
        self.assertIn("Ap Thap", cau)
        self.assertIn("280 km", cau)
        self.assertIn("Áp thấp nhiệt đới", cau)

    def test_do_bo_gan_toi_noi_ten_tinh_va_khoang_cach_toi_nguoi_hoi(self):
        cau = tb.tra_loi_bao("do_bo_gan_toi", *HA_NOI)
        self.assertIn("Quảng Bình", cau)
        self.assertIn("421 km", cau)

    def test_sap_do_bo_noi_thoi_diem_gio_viet_nam(self):
        cau = tb.tra_loi_bao("sap_do_bo", *HA_NOI)
        self.assertIn("Quảng Bình", cau)
        self.assertIn("19:00 13/08", cau)

    def test_con_cach_bao_xa_tra_ve_khoang_cach_bao_toi_diem_do_bo(self):
        cau = tb.tra_loi_bao("con_cach_bao_xa", *HA_NOI)
        self.assertIn("533 km", cau)
        self.assertIn("Quảng Bình", cau)

    def test_so_luong_dem_du_ca_con_o_xa(self):
        cau = tb.tra_loi_bao("so_luong", *HA_NOI)
        self.assertIn("3 cơn", cau)

    def test_ban_tin_chung_dan_bang_con_do_bo_roi_moi_toi_con_gan_nhat(self):
        """Áp thấp yếu ở gần KHÔNG được mở đầu bản tin, và cơn cấp 11 sắp đổ bộ
        KHÔNG được gộp vào cụm "còn N cơn khác" — đó là kiểu sai đọc lên thấy ngay."""
        cau = tb.tra_loi_bao("tong_quan", *HA_NOI)
        self.assertLess(cau.index("Yagi"), cau.index("Ap Thap"),
                        "cơn đổ bộ phải đứng trước cơn gần nhất")
        self.assertIn("Quảng Bình", cau)
        self.assertIn("Cơn gần anh nhất", cau)
        self.assertNotIn("ở xa", cau)

    def test_cau_canh_bao_uu_tien_con_do_bo_khong_phai_con_gan_nhat(self):
        """Áp thấp yếu cách 280 km gần hơn, nhưng bão đổ bộ mới là việc có hậu quả."""
        cau = tb.cau_canh_bao_bao(*HA_NOI)
        self.assertIn("Yagi", cau)
        self.assertNotIn("Ap Thap", cau)
        self.assertIn("Quảng Bình", cau)
        self.assertIn("chỗ đổ bộ cách anh", cau)

    def test_cau_canh_bao_im_lang_khi_khong_co_gi_dang_bao(self):
        tb._CACHE.clear()
        tb._get_json = _gia_lap([XA])
        self.assertEqual(tb.cau_canh_bao_bao(*HA_NOI), "")

    def test_khong_co_du_bao_do_bo_thi_noi_ro_chua_co(self):
        tb._CACHE.clear()
        tb._get_json = _gia_lap([AP_THAP], {"ap-thap": CHI_TIET_AP_THAP})
        cau = tb.tra_loi_bao("sap_do_bo", *HA_NOI)
        self.assertIn("Chưa cơn nào có dự báo đổ bộ", cau)
        self.assertIn("Ap Thap", cau)

    def test_khong_co_toa_do_nguoi_hoi_van_tra_loi_duoc(self):
        """Không có Home Assistant thì vẫn phải nói được cơn nào đổ bộ vào đâu."""
        cau = tb.tra_loi_bao("sap_do_bo")
        self.assertIn("Quảng Bình", cau)


if __name__ == "__main__":
    unittest.main()
