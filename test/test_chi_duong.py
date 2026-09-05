"""Tool chỉ đường: hỏi phương tiện → link Google Maps + chỉ dẫn + khoảng cách.

Chủ máy 04/09: bot trả lời "đường từ A về B" — HỎI phương tiện trước, rồi trả
khoảng cách + chỉ dẫn chi tiết + link Google Maps. Miễn phí, không API key:
geocode bóc TỪ WEB Google Maps (`_gmaps_pb`, đúng ghim như Google) → fallback
Nominatim khi Google hỏng; OSRM (route) + Maps URL dựng từ TOẠ ĐỘ (deep-link).

Test KHÔNG gọi mạng: `GeocodeTests`/`ChiDuongTests` ép `_gmaps_pb`→None để kiểm
đường FALLBACK Nominatim bằng mock `requests.get`; `GmapsPbTests` kiểm riêng
đường Google bằng mock `curl_cffi`.
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
    def setUp(self):
        # Ép đường Google (pb) trả None → geocode rơi xuống FALLBACK Nominatim,
        # đúng thứ các test dưới mock bằng requests.get. Không đụng mạng thật.
        p = patch("services.chi_duong._gmaps_pb", return_value=None)
        p.start(); self.addCleanup(p.stop)

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

    def test_bo_chu_dem_toa_nha(self):
        # "tòa nhà"/"số"/"căn hộ" là chữ đệm — bỏ để tra khái quát.
        self.assertEqual(cd._bo_ma_toa("tòa nhà CT4Bx2 Bắc Linh Đàm"), "Bắc Linh Đàm")
        self.assertEqual(cd._bo_ma_toa("căn hộ N01 Ecohome"), "Ecohome")

    def test_giai_link_maps_place(self):
        eff = ("https://www.google.com/maps/place/"
               "CT4B-X2+B%E1%BA%AFc+Linh+%C4%90%C3%A0m,+Ho%C3%A0ng+Li%E1%BB%87t,+H%C3%A0+N%E1%BB%99i/data=x")
        resp = MagicMock(); resp.url = eff
        with patch("services.chi_duong.requests.get", return_value=resp):
            r = cd._giai_link_maps("https://maps.app.goo.gl/abc")
        self.assertEqual(r, "CT4B-X2 Bắc Linh Đàm, Hoàng Liệt, Hà Nội")

    def test_giai_link_maps_toa_do(self):
        resp = MagicMock(); resp.url = "https://www.google.com/maps/@21.0114,105.8506,17z"
        with patch("services.chi_duong.requests.get", return_value=resp):
            r = cd._giai_link_maps("https://maps.app.goo.gl/xyz")
        self.assertEqual(r, (21.0114, 105.8506))

    def test_giai_link_maps_khong_phai_url(self):
        self.assertIsNone(cd._giai_link_maps("114 Mai Hắc Đế"))

    def test_geocode_link_maps_toa_do_dung_thang(self):
        resp = MagicMock(); resp.url = "https://www.google.com/maps/@21.0114,105.8506,17z"
        with patch("services.chi_duong.requests.get", return_value=resp):
            g = cd.geocode("https://maps.app.goo.gl/xyz")
        self.assertEqual((g[0], g[1]), (21.0114, 105.8506))
        self.assertIn("ghim", g[2].lower())

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
    def setUp(self):
        # Như GeocodeTests: kiểm đường FALLBACK Nominatim (mock requests.get).
        p = patch("services.chi_duong._gmaps_pb", return_value=None)
        p.start(); self.addCleanup(p.stop)

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

    def test_xe_buyt_geocode_lam_link_nhung_khong_goi_osrm(self):
        # Xe buýt KHÔNG định tuyến (OSRM), nhưng VẪN geocode để link mở đúng chỗ.
        # pb trả toạ độ (không dùng requests); requests.get nổ nếu bị gọi → chứng
        # minh không đụng OSRM/Nominatim.
        with patch("services.chi_duong._gmaps_pb",
                   side_effect=lambda q: (21.0, 105.85, q, "Hà Nội")), \
             patch("services.chi_duong.requests.get",
                   side_effect=AssertionError("không được gọi OSRM/Nominatim")):
            r = cd.chi_duong("A", "B", "xe buýt")
        self.assertFalse(r["ok"])
        self.assertEqual(r["ly_do"], "khong_dinh_tuyen")
        self.assertIn("travelmode=transit", r["link"])
        self.assertIn("origin=21.0", r["link"])   # link dựng từ TOẠ ĐỘ


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

    def test_co_phuong_tien_chua_xac_nhan_thi_HOI_XAC_NHAN(self):
        """Bước 2 (chủ máy chốt 04/09: luôn xác nhận): hiện địa chỉ, chưa đưa km."""
        dv = {"ok": True, "tu": "Hoàng Thành Tower, 114 Mai Hắc Đế", "den": "Bắc Linh Đàm",
              "gan_dung": False, "link": "https://www.google.com/maps/dir/?api=1"}
        with patch("services.chi_duong.dinh_vi", return_value=dv):
            out = caps._h_chi_duong({"diem_di": "A", "diem_den": "B", "phuong_tien": "xe máy"}, {})
        self.assertIn("xác nhận lại địa chỉ", out["text"])
        self.assertIn("Điểm đi", out["text"])
        self.assertIn("<<<ASK>>>", out["text"])
        self.assertIn("đã xác nhận địa chỉ", out["text"])   # nút re-gọi tool
        self.assertNotIn("km", out["text"].lower(), "chưa được đưa km ở bước xác nhận")

    def test_da_xac_nhan_thi_chi_duong_that(self):
        r = {"ok": True, "km": 7.3, "phut": 10, "buoc": ["Rẽ phải Phố X (~235 m)"],
             "link": "https://www.google.com/maps/dir/?api=1&x", "tu": "A", "den": "B"}
        with patch("services.chi_duong.chi_duong", return_value=r):
            out = caps._h_chi_duong({"diem_di": "A", "diem_den": "B",
                                     "phuong_tien": "xe máy", "xac_nhan": True}, {})
        self.assertIn("7.3 km", out["text"])
        self.assertIn("google.com/maps", out["text"])
        self.assertNotIn("<<<ASK>>>", out["text"])
        self.assertTrue(out.get("deliver_now"))

    def test_khac_tinh_o_buoc_xac_nhan_thi_HOI_dia_chi(self):
        # dinh_vi (bước 2) phát hiện khác tỉnh → hỏi lại địa chỉ, KHÔNG đưa km.
        dv = {"ok": False, "ly_do": "tinh_khong_khop",
              "tinh_di": "Thành phố Đà Nẵng", "tinh_den": "Thành phố Hà Nội",
              "link": "https://www.google.com/maps/dir/?api=1", "phuong_tien": "xe máy"}
        with patch("services.chi_duong.dinh_vi", return_value=dv):
            out = caps._h_chi_duong({"diem_di": "Mai Hắc Đế", "diem_den": "Bắc Linh Đàm",
                                     "phuong_tien": "xe máy"}, {})
        self.assertIn("Đà Nẵng", out["text"])
        self.assertIn("Hà Nội", out["text"])
        self.assertNotIn("km", out["text"].split("Google")[0].lower(), "không được đưa km sai")
        self.assertTrue(out.get("deliver_now"))

    def test_da_xac_nhan_gan_dung_thi_them_ghi_chu(self):
        r = {"ok": True, "km": 6.8, "phut": 9, "gan_dung": True,
             "buoc": ["Rẽ phải Phố X (~235 m)"], "tu": "A", "den": "B",
             "link": "https://www.google.com/maps/dir/?api=1"}
        with patch("services.chi_duong.chi_duong", return_value=r):
            out = caps._h_chi_duong({"diem_di": "A", "diem_den": "B",
                                     "phuong_tien": "xe máy", "xac_nhan": True}, {})
        self.assertIn("6.8 km", out["text"])
        self.assertIn("gần đúng", out["text"])
        self.assertTrue(out.get("deliver_now"))

    def test_xe_buyt_khong_xac_nhan_ra_thang_link(self):
        # Xe buýt không định tuyến → bỏ bước xác nhận, ra link luôn.
        dv = {"ok": False, "ly_do": "khong_dinh_tuyen",
              "link": "https://www.google.com/maps/dir/?api=1&travelmode=transit",
              "phuong_tien": "xe buýt"}
        with patch("services.chi_duong.dinh_vi", return_value=dv):
            out = caps._h_chi_duong({"diem_di": "A", "diem_den": "B", "phuong_tien": "xe buýt"}, {})
        self.assertIn("google.com/maps", out["text"])
        self.assertIn("transit", out["text"])


def _pb_body(lat, lng, ten, full, tinh, *, rong_nhanh=False):
    """Dựng body giả của endpoint Google Maps: ")]}'\\n" + JSON.

    `data[0][1][0][14]` = kết quả đầu; `[9]`=[_,_,lat,lng], `[11]`=tên, `[18]`=địa
    chỉ đầy đủ, `[2]`=[dòng, quận, tỉnh, "Việt Nam"]. `rong_nhanh`: [14] rỗng,
    toạ độ nằm rải trong cây (kiểm nhánh duyệt cây)."""
    import json as _json
    if rong_nhanh:
        data = [[None, [[None, [None, None, [None, None, lat, lng]]]]]]
    else:
        r14 = [None] * 19
        r14[2] = [full.split(",")[0].strip(), "Hai Bà Trưng", tinh, "Việt Nam"]
        r14[9] = [None, None, lat, lng]
        r14[11] = ten
        r14[18] = full
        result0 = [None] * 15
        result0[14] = r14
        data = [[None, [result0]]]
    return ")]}'\n" + _json.dumps(data, ensure_ascii=False)


class GmapsPbTests(unittest.TestCase):
    """Đường CHÍNH: bóc toạ độ + địa chỉ từ endpoint Google Maps nội bộ."""

    def _mock_pb(self, body):
        resp = MagicMock(); resp.text = body
        return patch("curl_cffi.requests.get", return_value=resp)

    def test_boc_ghim_ten_tinh_tu_ket_qua_dau(self):
        body = _pb_body(21.0103763, 105.8507264, "114 P. Mai Hắc Đế",
                        "114 P. Mai Hắc Đế, Hai Bà Trưng, Hà Nội, Việt Nam", "Hà Nội")
        with self._mock_pb(body):
            g = cd._gmaps_pb("114 Mai Hắc Đế, Hà Nội")
        self.assertEqual(g, (21.0103763, 105.8507264,
                             "114 P. Mai Hắc Đế, Hai Bà Trưng, Hà Nội, Việt Nam",
                             "Hà Nội"))

    def test_duyet_cay_khi_ket_qua_dau_rong_nhanh(self):
        body = _pb_body(20.9651653, 105.8234007, "", "", "", rong_nhanh=True)
        with self._mock_pb(body):
            g = cd._gmaps_pb("CT4B X2 Bắc Linh Đàm")
        self.assertIsNotNone(g)
        self.assertAlmostEqual(g[0], 20.9651653, places=5)
        self.assertAlmostEqual(g[1], 105.8234007, places=5)

    def test_pb_hong_tra_none(self):
        with patch("curl_cffi.requests.get", side_effect=RuntimeError("chặn")):
            self.assertIsNone(cd._gmaps_pb("x"))

    def test_geocode_uu_tien_google_khong_dung_nominatim(self):
        # pb ra kết quả → geocode dùng ngay, KHÔNG đụng Nominatim (requests.get).
        with patch("services.chi_duong._gmaps_pb",
                   return_value=(21.01, 105.85, "114 P. Mai Hắc Đế, Hà Nội", "Hà Nội")), \
             patch("services.chi_duong.requests.get",
                   side_effect=AssertionError("không được gọi Nominatim")):
            g = cd.geocode("114 Mai Hắc Đế")
        self.assertEqual(g, (21.01, 105.85, "114 P. Mai Hắc Đế, Hà Nội", "Hà Nội", True))

    def test_geocode_tut_xuong_nominatim_khi_google_rong(self):
        # pb None → geocode dùng Nominatim (mock requests.get).
        with patch("services.chi_duong._gmaps_pb", return_value=None), \
             patch("services.chi_duong.requests.get", return_value=_resp(_GEO_DI)):
            g = cd.geocode("114 Mai Hắc Đế")
        self.assertEqual(g[0], 21.0114)
        self.assertEqual(g[4], True)


class TinhThanhTests(unittest.TestCase):
    """Chuẩn hoá tỉnh + bỏ đuôi tỉnh/thành khỏi truy vấn Google (đo 05/09)."""

    def test_chuan_tinh_bo_tien_to(self):
        self.assertEqual(cd._chuan_tinh("Thành phố Hà Nội"), cd._chuan_tinh("Hà Nội"))
        self.assertEqual(cd._chuan_tinh("Tỉnh Quảng Nam"), cd._chuan_tinh("Quảng Nam"))

    def test_tinh_ngan_giu_dau(self):
        self.assertEqual(cd._tinh_ngan("Thành phố Hà Nội"), "Hà Nội")
        self.assertEqual(cd._tinh_ngan("Tỉnh Quảng Nam"), "Quảng Nam")
        self.assertEqual(cd._tinh_ngan("Hà Nội"), "Hà Nội")

    def test_bo_tinh_tp_giu_quan_phuong(self):
        # Bỏ đoạn 'thành phố …' (gây sai ghim), GIỮ quận/phường/landmark.
        self.assertEqual(
            cd._bo_tinh_tp("CT4B-X2 Bắc Linh Đàm, phường Hoàng Liệt, quận Hoàng Mai, thành phố Hà Nội"),
            "CT4B-X2 Bắc Linh Đàm, phường Hoàng Liệt, quận Hoàng Mai")
        self.assertEqual(cd._bo_tinh_tp("114 Mai Hắc Đế, Tỉnh Nghệ An"), "114 Mai Hắc Đế")

    def test_tinh_khac_tien_to_khong_bao_khac_tinh(self):
        # "Hà Nội" vs "Thành phố Hà Nội" là CÙNG nơi → không được chặn định tuyến.
        a = (21.01, 105.85, "A", "Hà Nội", True)
        b = (20.96, 105.82, "B", "Thành phố Hà Nội", True)
        with patch("services.chi_duong.geocode", side_effect=[b, a]):
            _a, _b, ly = cd._dinh_vi_hai_dau("A", "B")
        self.assertIsNone(ly, "cùng Hà Nội mà báo khác tỉnh là sai")

    def test_that_su_khac_tinh_van_chan(self):
        a = (16.05, 108.20, "A", "Đà Nẵng", True)
        b = (20.96, 105.82, "B", "Thành phố Hà Nội", True)
        with patch("services.chi_duong.geocode", side_effect=[b, a]):
            _a, _b, ly = cd._dinh_vi_hai_dau("A", "B")
        self.assertEqual(ly, "tinh_khong_khop")


if __name__ == "__main__":
    unittest.main()
