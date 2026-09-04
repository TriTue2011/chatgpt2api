"""Tool chỉ đường: hỏi phương tiện → link Google Maps + chỉ dẫn + khoảng cách.

Chủ máy 04/09: bot trả lời "đường từ A về B" — HỎI phương tiện trước, rồi trả
khoảng cách + chỉ dẫn chi tiết + link Google Maps. Hoàn toàn miễn phí, không API
key: Nominatim (geocode) + OSRM (route) + Maps URL (deep-link).

Test dùng mock cho requests.get — KHÔNG gọi mạng thật.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import chi_duong as cd  # noqa: E402
from services.agent import capabilities as caps  # noqa: E402


def _resp(json_data):
    m = MagicMock()
    m.json.return_value = json_data
    m.raise_for_status.return_value = None
    return m


_HN = {"city": "Thành phố Hà Nội"}
_DN = {"city": "Thành phố Đà Nẵng"}
_GEO_DI = [{"lat": "21.0114", "lon": "105.8506",
            "display_name": "114 Mai Hắc Đế, Hà Nội", "address": _HN}]
_GEO_DEN = [{"lat": "20.9653", "lon": "105.8232",
             "display_name": "CT4B X2 Bắc Linh Đàm, Hà Nội", "address": _HN}]
_GEO_DI_DN = [{"lat": "16.0544", "lon": "108.2022",
               "display_name": "Mai Hắc Đế, Đà Nẵng", "address": _DN}]
_OSRM_OK = {"code": "Ok", "routes": [{"distance": 7300, "duration": 600, "legs": [{"steps": [
    {"name": "Phố Mai Hắc Đế", "distance": 235, "maneuver": {"type": "turn", "modifier": "right"}},
    {"name": "Đường Giải Phóng", "distance": 1400, "maneuver": {"type": "new name"}},
    {"name": "", "distance": 20, "maneuver": {"type": "arrive"}},
]}]}]}


def _fake_get(geo_seq, osrm=_OSRM_OK):
    """Trả hàm giả lập requests.get: geocode lần lượt theo geo_seq, rồi OSRM."""
    calls = {"geo": 0}

    def _g(url, params=None, headers=None, timeout=None):
        if "nominatim" in url:
            i = calls["geo"]; calls["geo"] += 1
            return _resp(geo_seq[i] if i < len(geo_seq) else [])
        return _resp(osrm)
    return _g


class MapsLinkTests(unittest.TestCase):
    def test_url_dung_khuon_va_urlencode(self):
        u = cd.maps_link("114 Mai Hắc Đế", "Bắc Linh Đàm", "driving")
        self.assertIn("https://www.google.com/maps/dir/?", u)
        self.assertIn("api=1", u)
        self.assertIn("travelmode=driving", u)
        self.assertIn("origin=114+Mai+H", u)          # dấu tiếng Việt đã encode
        self.assertNotIn(" ", u)

    def test_travelmode_theo_phuong_tien(self):
        self.assertIn("travelmode=transit", cd.maps_link("a", "b", "transit"))


class ChuanPhuongTienTests(unittest.TestCase):
    def test_cac_ten(self):
        self.assertEqual(cd.chuan_phuong_tien("Xe Máy"), ("driving", "driving", True))
        self.assertEqual(cd.chuan_phuong_tien("xe buýt")[2], False)
        self.assertEqual(cd.chuan_phuong_tien("đi bộ"), ("walking", "walking", True))

    def test_la_thi_mac_dinh_xe_may(self):
        self.assertEqual(cd.chuan_phuong_tien("tàu ngầm"), ("driving", "driving", True))


class GeocodeTests(unittest.TestCase):
    def test_doc_lat_lon_ten_tinh(self):
        with patch("services.chi_duong.requests.get", return_value=_resp(_GEO_DI)):
            self.assertEqual(cd.geocode("114 Mai Hắc Đế"),
                             (21.0114, 105.8506, "114 Mai Hắc Đế, Hà Nội",
                              "Thành phố Hà Nội", True))

    def test_rong_tra_none(self):
        with patch("services.chi_duong.requests.get", return_value=_resp([])):
            self.assertIsNone(cd.geocode("địa chỉ ma"))

    def test_loi_mang_tra_none(self):
        with patch("services.chi_duong.requests.get", side_effect=RuntimeError("timeout")):
            self.assertIsNone(cd.geocode("x"))

    def test_bo_ma_toa_giu_phay(self):
        # 1 đoạn: bỏ token mã đứng đầu.
        self.assertEqual(cd._bo_ma_toa("CT4B X2 Bắc Linh Đàm"), "Bắc Linh Đàm")
        # Nhiều đoạn: bỏ đoạn mã đầu, GIỮ dấu phẩy (Nominatim kén phẩy).
        self.assertEqual(cd._bo_ma_toa("CT4BX2, phường Hoàng Liệt, quận Hoàng Mai"),
                         "phường Hoàng Liệt, quận Hoàng Mai")
        self.assertEqual(cd._bo_ma_toa("Bắc Linh Đàm"), "Bắc Linh Đàm")

    def test_geocode_thu_bien_the_khi_nguyen_van_hong(self):
        """Nguyên văn (có mã toà) không ra → bỏ mã toà thử lại."""
        seq = [[], _GEO_DEN]   # lượt 1 rỗng, lượt 2 (đã bỏ mã toà) ra
        calls = {"n": 0}

        def _g(url, params=None, headers=None, timeout=None):
            i = calls["n"]; calls["n"] += 1
            return _resp(seq[i] if i < len(seq) else [])
        with patch("services.chi_duong.requests.get", side_effect=_g):
            r = cd.geocode("CT4B X2 Bắc Linh Đàm")
        self.assertIsNotNone(r, "phải thử biến thể sau khi nguyên văn hỏng")
        self.assertEqual(calls["n"], 2, "đúng 2 lượt: nguyên văn + bỏ mã toà")

    def test_geocode_khong_lam_qua_2_luot(self):
        """Tôn trọng giới hạn Nominatim: tối đa 2 lượt gọi."""
        calls = {"n": 0}

        def _g(url, params=None, headers=None, timeout=None):
            calls["n"] += 1
            return _resp([])
        with patch("services.chi_duong.requests.get", side_effect=_g):
            cd.geocode("CT4B X2 Bắc Linh Đàm")
        self.assertLessEqual(calls["n"], 2)


class ChiDuongTests(unittest.TestCase):
    def test_full_ok(self):
        # Thứ tự geocode: ĐIỂM ĐẾN trước (lấy tỉnh gợi ý), rồi ĐIỂM ĐI.
        with patch("services.chi_duong.requests.get", side_effect=_fake_get([_GEO_DEN, _GEO_DI])):
            r = cd.chi_duong("114 Mai Hắc Đế", "CT4B X2 Bắc Linh Đàm", "xe máy")
        self.assertTrue(r["ok"])
        self.assertEqual(r["km"], 7.3)
        self.assertEqual(r["phut"], 10)
        self.assertFalse(r["gan_dung"], "cả hai đầu khớp nguyên văn → chính xác")
        self.assertTrue(any("Phố Mai Hắc Đế" in b for b in r["buoc"]))

    def test_geocode_diem_den_rong(self):
        # Điểm đến geocode TRƯỚC — rỗng thì dừng ngay, không geocode điểm đi.
        with patch("services.chi_duong.requests.get", side_effect=_fake_get([[]])):
            r = cd.chi_duong("A có thật", "địa chỉ ma", "xe máy")
        self.assertFalse(r["ok"])
        self.assertEqual(r["ly_do"], "khong_ra_diem_den")
        self.assertIn("google.com/maps", r["link"])   # link vẫn dựng được

    def test_hai_dau_khac_tinh_thi_HOI_LAI_khong_dua_km_sai(self):
        """Đúng lỗi 04/09: 'Mai Hắc Đế' lạc sang Đà Nẵng → 766 km. Nay HỎI LẠI.

        Điểm đến (Bắc Linh Đàm) ở Hà Nội; điểm đi vẫn ra Đà Nẵng dù đã bù tỉnh
        → khác tỉnh → không định tuyến, trả ly_do để handler hỏi."""
        # den → Hà Nội; di (cả nguyên văn lẫn biến thể) → Đà Nẵng.
        seq = [_GEO_DEN, _GEO_DI_DN, _GEO_DI_DN]
        with patch("services.chi_duong.requests.get", side_effect=_fake_get(seq)):
            r = cd.chi_duong("Mai Hắc Đế", "Bắc Linh Đàm", "xe máy")
        self.assertFalse(r["ok"])
        self.assertEqual(r["ly_do"], "tinh_khong_khop")
        self.assertIn("Đà Nẵng", r["tinh_di"])
        self.assertIn("Hà Nội", r["tinh_den"])

    def test_gan_dung_khi_mot_dau_dung_bien_the(self):
        """Điểm đến chỉ ra được sau khi bỏ mã toà (biến thể) → gan_dung=True."""
        seq = [[], _GEO_DEN, _GEO_DI]   # den: nguyên văn rỗng → biến thể ra; rồi di
        with patch("services.chi_duong.requests.get", side_effect=_fake_get(seq)):
            r = cd.chi_duong("114 Mai Hắc Đế", "CT4BX2 Bắc Linh Đàm", "xe máy")
        self.assertTrue(r["ok"])
        self.assertTrue(r["gan_dung"])

    def test_xe_buyt_khong_goi_osrm(self):
        # requests.get side_effect nổ nếu bị gọi → chứng minh xe buýt KHÔNG geocode/route.
        with patch("services.chi_duong.requests.get", side_effect=AssertionError("không được gọi mạng")):
            r = cd.chi_duong("A", "B", "xe buýt")
        self.assertFalse(r["ok"])
        self.assertEqual(r["ly_do"], "khong_dinh_tuyen")
        self.assertIn("travelmode=transit", r["link"])


class HandlerTests(unittest.TestCase):
    def test_thieu_phuong_tien_thi_hoi(self):
        out = caps._h_chi_duong({"diem_di": "A", "diem_den": "B"}, {})
        self.assertTrue(out.get("deliver_now"))
        self.assertIn("<<<ASK>>>", out["text"])
        self.assertEqual(out["text"].count("| chỉ đường"), 4)

    def test_thieu_diem(self):
        out = caps._h_chi_duong({"diem_di": "", "diem_den": "B"}, {})
        self.assertIn("ĐIỂM ĐI", out["text"])
        self.assertNotIn("<<<ASK>>>", out["text"])

    def test_du_tham_so_ok(self):
        r = {"ok": True, "km": 7.3, "phut": 10, "buoc": ["Rẽ phải Phố X (~235 m)"],
             "link": "https://www.google.com/maps/dir/?api=1&x", "tu": "A", "den": "B"}
        with patch.object(caps, "_h_chi_duong", wraps=caps._h_chi_duong), \
             patch("services.chi_duong.chi_duong", return_value=r):
            out = caps._h_chi_duong({"diem_di": "A", "diem_den": "B", "phuong_tien": "xe máy"}, {})
        self.assertIn("7.3 km", out["text"])
        self.assertIn("google.com/maps", out["text"])
        self.assertNotIn("<<<ASK>>>", out["text"])

    def test_khac_tinh_thi_handler_HOI_dia_chi_khong_dua_km(self):
        r = {"ok": False, "ly_do": "tinh_khong_khop",
             "tinh_di": "Thành phố Đà Nẵng", "tinh_den": "Thành phố Hà Nội",
             "link": "https://www.google.com/maps/dir/?api=1"}
        with patch("services.chi_duong.chi_duong", return_value=r):
            out = caps._h_chi_duong({"diem_di": "Mai Hắc Đế", "diem_den": "Bắc Linh Đàm",
                                     "phuong_tien": "xe máy"}, {})
        self.assertIn("Đà Nẵng", out["text"])
        self.assertIn("Hà Nội", out["text"])
        self.assertNotIn("km", out["text"].split("Google")[0].lower(), "không được đưa km sai")

    def test_gan_dung_thi_handler_them_ghi_chu(self):
        r = {"ok": True, "km": 6.8, "phut": 9, "gan_dung": True,
             "buoc": ["Rẽ phải Phố X (~235 m)"], "tu": "A", "den": "B",
             "link": "https://www.google.com/maps/dir/?api=1"}
        with patch("services.chi_duong.chi_duong", return_value=r):
            out = caps._h_chi_duong({"diem_di": "A", "diem_den": "B", "phuong_tien": "xe máy"}, {})
        self.assertIn("6.8 km", out["text"])
        self.assertIn("gần đúng", out["text"])

    def test_xe_buyt_handler_ra_link(self):
        r = {"ok": False, "ly_do": "khong_dinh_tuyen",
             "link": "https://www.google.com/maps/dir/?api=1&travelmode=transit"}
        with patch("services.chi_duong.chi_duong", return_value=r):
            out = caps._h_chi_duong({"diem_di": "A", "diem_den": "B", "phuong_tien": "xe buýt"}, {})
        self.assertIn("google.com/maps", out["text"])
        self.assertIn("transit", out["text"])


if __name__ == "__main__":
    unittest.main()
