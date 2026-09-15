"""Thời tiết theo ĐỊA DANH MẶC ĐỊNH của từng cuộc trò chuyện — AccuWeather, tách khỏi HA.

Đo thật trên máy chủ (runs.sqlite, bản tin 8h, việc «tin tức + thời tiết tại
Hoàng Mai, Hà Nội»):

    12/09  tra 2 lần → «Công cụ thời tiết … bị lệch địa điểm»
    13/09  tra 2 lần → «nhiều mây, nguy cơ mưa do áp thấp» (đoán từ tin báo)
    14/09  tra 1 lần → «mưa rào, 24°C, độ ẩm 91%…»
    15/09  tra 1 lần → «mưa phùn dày, 24°C, độ ẩm 94%…»

Lượt tra RIÊNG câu thời tiết gửi `vn_weather` cụm «Hoàng Mai Hà Nội» và nhận về
«Thời tiết Quinh Loi / Lang Yen»; lượt tra GỘP rơi về «Hà Nội», mà bộ dò của
`vn_weather` lại đổi «Hà Nội» thành một nơi trùng tên thuộc Hà Nam (lệch 64 km).
Tức cả những ngày «đầy đủ số liệu» cũng sai chỗ.

Chủ máy chốt 15/09/2026: thời tiết tách khỏi HA; hỏi thời tiết/tổng hợp thời
tiết dùng địa danh mặc định, chưa có thì hỏi, đổi được bất cứ lúc nào; mỗi cuộc
trò chuyện một địa danh; loa HA giữ thực thể HA.

HTML mẫu dưới đây cắt từ trang AccuWeather thật của mã 3558175 lúc 13:23 ngày
15/09/2026, chỉ giữ phần thẻ mà bộ đọc dùng.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import accu_thoi_tiet as accu  # noqa: E402
from services.agent import capabilities as caps  # noqa: E402
from services.agent import thoi_tiet as tt  # noqa: E402
import services.protocol.openai_v1_chat_complete as api  # noqa: E402

HTML_HIEN_TAI = (
    '<div class="current-weather-card card-module content-module"> <div class="card-header sp'
    'aced-content"> <h1>Thời tiết hiện tại</h1> <p class="sub">13:23</p> </div> <div class="c'
    'ard-content"> <div class="current-weather"> <div class="current-weather-info"> <img clas'
    's="icon" height="62" src="/images/weathericons/v2a/12.svg" width="62"/> <div class="temp'
    '"> <div class="display-temp">29°<span class="sub">C</span> </div> </div> </div> <div cla'
    'ss="phrase">Mưa nhỏ</div> </div> <div class="current-weather-extra no-realfeel-phrase"> '
    '<div> RealFeel® 35° <div class="label-tooltip" data-js="prevent-accordion-toggle"> <div '
    'class="label">Nóng</div> </div> </div> <div class="realfeel-shade-details"> RealFeel Sha'
    'de™ 33° <div class="label-tooltip" data-js="prevent-accordion-toggle"> <div class="label'
    '">Nóng</div> </div> </div> </div> </div> <div class="current-weather-details no-realfeel'
    '-phrase"> <div class="detail-item spaced-content"> <div>RealFeel®</div> <div>35°</div> <'
    '/div> <div class="detail-item spaced-content"> <div>RealFeel Shade™</div> <div>33°</div>'
    ' </div> <div class="detail-item spaced-content"> <div>Chỉ số nhiệt</div> <div>35°</div> '
    '</div> <div class="detail-item spaced-content"> <div>Chỉ số UV tối đa</div> <div>1.9 (Th'
    'ấp)</div> </div> <div class="detail-item spaced-content"> <div>Gió</div> <div>ĐB 15 km/h'
    '</div> </div> <div class="detail-item spaced-content"> <div>Gió giật mạnh</div> <div>19 '
    'km/h</div> </div> <div class="detail-item spaced-content"> <div>Độ ẩm</div> <div>83%</di'
    'v> </div> <div class="detail-item spaced-content"> <div>Điểm sương</div> <div>26° C</div'
    '> </div> <div class="detail-item spaced-content"> <div>Khí áp</div> <div>↔ 1012 mb</div>'
    ' </div> <div class="detail-item spaced-content"> <div>Mật độ mây</div> <div>100%</div> <'
    '/div> <div class="detail-item spaced-content"> <div>Tầm nhìn</div> <div>16 km</div> </di'
    'v> <div class="detail-item spaced-content"> <div>Trần mây</div> <div>500 m</div> </div> '
    '</div> </div>')

HTML_KHONG_KHI = (
    '<div id="current"> <div class="air-quality-card content-module" data-qa="airQualityCard"'
    '> <h2 class="air-quality-card__header module-title"> Chất lượng không khí hiện tại </h2>'
    ' <div class="air-quality-content"> <div class="date-wrapper"> <p class="day-of-week">H.n'
    'ay</p> <p class="date">15/9</p> </div> <div class="content-wrapper"> <div class="particl'
    'e-chart"> <div class="aq-particles" style="width:180px;height:180px;"><div class="aq-num'
    'ber-wrapper"> <div class="aq-number-container"> <div class="aq-number"> 29 </div> <div c'
    'lass="aq-unit">AQI</div> </div> </div> </div> </div> <div class="air-quality-data-wrappe'
    'r"> <h3 class="air-quality-data"> <div class="category-color-bar" style="background: #43'
    'D357;"></div> <p class="category-text">Vừa phải</p> <p class="statement"> Chất lượng khô'
    'ng khí mở mức chấp nhận được đối với hầu hết đối tượng. Tuy nhiên, ở các nhóm đối tượng '
    'nhạy cảm có thể sẽ xuất hiện triệu chứng từ nhẹ đến trung bình nếu tiếp xúc quá lâu. </p'
    '> <p class="based-on"> Căn cứ theo các chất ô nhiễm hiện tại </p>  </h3> </div> </div> <'
    '/div></div></div>')

HTML_MINUTECAST = (
    '<div class="minute-cast-chart">'
    '<div class="current-summary"> <div class="summary"> Mưa kéo dài trong ít nhất 120 ph </d'
    'iv> <div class="conditions"> <div class="conditions-icon"> <img class="icon" height="64"'
    ' src="/images/weathericons/v2a/12.svg" width="64"/> <div> <p class="time">13:23</p> <p c'
    'lass="icon-phrase">Mưa nhẹ</p> </div> </div> <div class="temps"> <div> <span class="curr'
    'ent-temp">26°</span> <span class="current-temp-unit">C</span> </div> <div class="realfee'
    'l-temp"> <span class="">RealFeel®</span> <span class="value">31°</span> </div> </div> </'
    'div> </div>'
    '</div>')

# Ứng viên autocomplete THẬT (language=vi) đo 15/09/2026. AccuWeather trả «Hoàng
# Mai» ở Hồ Bắc TRƯỚC Hoàng Mai ở Hà Nội.
HOANG_MAI_HN = {"key": "3558175", "ten": "Hoàng Mai", "day_du": "Hoàng Mai, Hà Nội, VN",
                "quoc_gia": "VN"}
HOANG_MAI_CN = {"key": "59288", "ten": "Hoàng Mai", "day_du": "Hoàng Mai, Hồ Bắc, CN",
                "quoc_gia": "CN"}
HA_NOI = {"key": "353412", "ten": "Hà Nội", "day_du": "Hà Nội, Hà Nội, VN", "quoc_gia": "VN"}
# Trùng tên trong nước — dựng tay để kiểm menu chọn.
TAN_BINH_HCM = {"key": "1001", "ten": "Tân Bình", "day_du": "Tân Bình, Hồ Chí Minh, VN",
                "quoc_gia": "VN"}
TAN_BINH_TQ = {"key": "1002", "ten": "Tân Bình", "day_du": "Tân Bình, Tuyên Quang, VN",
               "quoc_gia": "VN"}
# Đo thật 15/09: «ha noi» không dấu ra 0 ứng viên, bớt còn «ha» thì ra Hailar.
HAILAR = {"key": "102621", "ten": "Hailar", "day_du": "Hailar, Nội Mông, CN", "quoc_gia": "CN"}
AUTOCOMPLETE = {"Hoàng Mai": [HOANG_MAI_CN, HOANG_MAI_HN], "Hà Nội": [HA_NOI],
                "Tân Bình": [TAN_BINH_HCM, TAN_BINH_TQ], "ha": [HAILAR]}


def _autocomplete_gia(q: str):
    return list(AUTOCOMPLETE.get(q, []))


class DocTrangAccuWeather(unittest.TestCase):
    def setUp(self):
        accu._cache.clear()

    def test_the_hien_tai(self):
        ht = accu.doc_hien_tai(HTML_HIEN_TAI)
        self.assertEqual(ht["gio_do"], "13:23")
        self.assertEqual(ht["nhiet_do"], 29)
        self.assertEqual(ht["mo_ta"], "Mưa nhỏ")
        self.assertEqual(ht["cam_giac"], 35)
        self.assertEqual(ht["cam_giac_chu"], "Nóng")
        self.assertEqual(ht["do_am"], 83)
        self.assertEqual(ht["uv"], "1.9 (Thấp)")
        self.assertEqual(ht["gio"], "ĐB 15 km/h")

    def test_trang_do_f_duoc_doi_sang_c(self):
        """Thiếu cookie đơn vị thì AccuWeather có thể trả °F — 84°F không được
        thành «84°C»."""
        html = HTML_HIEN_TAI.replace('29°<span class="sub">C</span>',
                                     '84°<span class="sub">F</span>')
        self.assertAlmostEqual(accu.doc_hien_tai(html)["nhiet_do"], 28.9, places=1)

    def test_khong_khi_va_minutecast(self):
        self.assertEqual(accu.doc_khong_khi(HTML_KHONG_KHI), {"aqi": 29, "muc": "Vừa phải"})
        self.assertEqual(accu.doc_minutecast(HTML_MINUTECAST), "Mưa kéo dài trong ít nhất 120 ph")

    def test_doan_van_day_du(self):
        trang = {"current-weather": HTML_HIEN_TAI, "air-quality-index": HTML_KHONG_KHI,
                 "minute-weather-forecast": HTML_MINUTECAST}
        with patch.object(accu, "_html", side_effect=lambda dd, t: trang[t]):
            text = accu.thoi_tiet_hien_tai(HOANG_MAI_HN)
        self.assertEqual(
            text,
            "Thời tiết Hoàng Mai, Hà Nội lúc 13:23: mưa nhỏ, 29°C, cảm giác như 35°C (nóng), "
            "độ ẩm 83%, gió ĐB 15 km/h. Chỉ số UV 1.9 (Thấp). Chất lượng không khí vừa phải "
            "(AQI 29). Mưa kéo dài trong ít nhất 120 ph.")

    def test_trang_phu_hong_van_co_doan_chinh(self):
        trang = {"current-weather": HTML_HIEN_TAI}
        with patch.object(accu, "_html", side_effect=lambda dd, t: trang.get(t)):
            text = accu.thoi_tiet_hien_tai(HOANG_MAI_HN)
        self.assertIn("29°C", text)
        self.assertNotIn("không khí", text)

    def test_doi_giao_dien_thi_none_khong_bia(self):
        with patch.object(accu, "_html", return_value="<html><body>đổi giao diện</body></html>"):
            self.assertIsNone(accu.thoi_tiet_hien_tai(HOANG_MAI_HN))


class TimDiaDanh(unittest.TestCase):
    def _tim(self, ten):
        with patch.object(accu, "_autocomplete", side_effect=_autocomplete_gia):
            return accu.tim_dia_danh(ten)

    def test_cum_co_tinh_thanh_tu_khu_trung_ten(self):
        """AccuWeather tra nguyên cụm «Hoàng Mai, Hà Nội» ra 0 ứng viên (đo thật)."""
        self.assertEqual(self._tim("Hoàng Mai, Hà Nội"), [HOANG_MAI_HN])
        self.assertEqual(self._tim("Hoàng Mai Hà Nội"), [HOANG_MAI_HN])
        self.assertEqual(self._tim("hoang mai ha noi"), [])     # autocomplete giả chỉ khớp có dấu

    def test_bot_tu_khong_duoc_doi_sang_noi_ten_khac(self):
        """Lỗi đo được trên máy chủ: «thoi tiet ha noi» ra thời tiết Nội Mông."""
        self.assertEqual(self._tim("ha noi"), [])

    def test_viet_nam_xep_truoc(self):
        self.assertEqual(self._tim("Hoàng Mai")[0], HOANG_MAI_HN)

    def test_phan_biet_khong_tim_thay_voi_mat_mang(self):
        self.assertEqual(self._tim("Không Có Nơi Này"), [])
        with patch.object(accu, "_autocomplete", return_value=None):
            self.assertIsNone(accu.tim_dia_danh("Hoàng Mai"))


class NhanCauHoiThoiTiet(unittest.TestCase):
    """Câu thật lấy từ runs.sqlite, cộng các ca biên của luồng đặt địa danh."""

    CHAT = [
        ("thời tiết hôm nay", ""),
        ("Thời tiết hôm nay", ""),
        ("thoi tiet ha noi hom nay the nao?", "ha noi"),
        ("thời tiết bắc ninh", "bắc ninh"),
        ("thời tiết hoàng mai", "hoàng mai"),
        ("thời tiết Mai Châu", "Mai Châu"),                 # «mai» không bị cắt như «ngày mai»
        ("thời tiết hôm nay tại Hoàng Mai", "Hoàng Mai"),
        ("Thời tiết Hoàng Mai, Hà Nội hôm nay?", "Hoàng Mai, Hà Nội"),
        ("chất lượng không khí hà nội", "hà nội"),
        # Còn ý khác ngoài hỏi thời tiết → nhường model.
        ("đổi địa danh thời tiết sang Đà Nẵng", None),
        ("anh lại hỏi thời tiết hồ chí minh", None),
        ("thời tiết hôm nay có bão không", None),           # để đường bão trả lời
        ("một chú mèo mướp nằm cạnh cửa sổ, ngoài trời đang mưa", None),
        ("vẽ cảnh ngoài trời đang mưa", None),
        ("giá vàng hôm nay", None),
        ("thông tin thời tiết lấy được sao báo lỗi", None),
    ]

    def test_cau_chat(self):
        for cau, mong in self.CHAT:
            with self.subTest(cau=cau):
                self.assertEqual(tt.phan_tich(cau, cau_chat=True), mong)

    def test_cau_tra_do_model_soan(self):
        self.assertEqual(tt.phan_tich("tin tức mới trong ngày và thời tiết tại Hoàng Mai, Hà Nội",
                                      cau_chat=False), "Hoàng Mai, Hà Nội")
        self.assertEqual(tt.phan_tich("dự báo thời tiết hôm nay", cau_chat=False), "")
        self.assertIsNone(tt.phan_tich("tin tức hôm nay", cau_chat=False))


class _SoTam(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        so = Path(self._tmp.name) / "thoi_tiet_mac_dinh.json"
        self._va = [
            patch.object(tt, "_duong", return_value=so),
            patch.object(tt, "_pham_vi", side_effect=lambda uid: uid),
            patch.object(accu, "_autocomplete", side_effect=_autocomplete_gia),
            patch.object(accu, "thoi_tiet_hien_tai",
                         side_effect=lambda dd: f"Thời tiết {dd['ten']} lúc 13:23: 29°C."),
            patch.object(tt, "_du_phong_vn_weather", return_value=None),
        ]
        for v in self._va:
            v.start()

    def tearDown(self):
        for v in reversed(self._va):
            v.stop()
        self._tmp.cleanup()


class LuongDiaDanhMacDinh(_SoTam):
    def test_chua_co_thi_hoi_roi_dat_theo_cau_tra_loi(self):
        hoi = tt.tra_loi("thời tiết hôm nay", "u1")
        self.assertIn("địa danh mặc định", hoi["text"])
        self.assertNotIn("29°C", hoi["text"])
        ra = tt.tra_loi("Hoàng Mai", "u1")
        self.assertEqual(tt.doc_mac_dinh("u1")["key"], "3558175")
        self.assertIn("Đã đặt «Hoàng Mai, Hà Nội»", ra["text"])
        self.assertIn("Thời tiết Hoàng Mai", ra["text"])

    def test_co_roi_thi_moi_lan_theo_dia_danh_do(self):
        tt.dat_mac_dinh("u1", HOANG_MAI_HN)
        for _ in range(2):
            ra = tt.tra_loi("thời tiết hôm nay", "u1")
            self.assertTrue(ra["text"].startswith("📍 Hoàng Mai, Hà Nội (địa danh mặc định)"))
            self.assertIn(("📍 Đổi địa danh mặc định", "__thoi_tiet__:doi"), ra["nut"])

    def test_moi_cuoc_tro_chuyen_mot_dia_danh(self):
        tt.dat_mac_dinh("u1", HOANG_MAI_HN)
        self.assertIn("địa danh mặc định", tt.tra_loi("thời tiết hôm nay", "u2")["text"])
        self.assertIsNone(tt.doc_mac_dinh("u2"))

    def test_dang_cho_ma_noi_chuyen_khac_thi_khong_nuot_tin(self):
        tt.tra_loi("thời tiết hôm nay", "u1")
        self.assertIsNone(tt.tra_loi("bật đèn bếp", "u1"))
        self.assertIsNone(tt.tra_loi("Hoàng Mai", "u1"), "hết chờ rồi thì tên nơi trần không phải lệnh")
        self.assertIsNone(tt.doc_mac_dinh("u1"))

    def test_nut_doi_dia_danh(self):
        tt.dat_mac_dinh("u1", HOANG_MAI_HN)
        hoi = tt.tra_loi("__thoi_tiet__:doi", "u1")
        self.assertIn("đang là «Hoàng Mai, Hà Nội»", hoi["text"])
        tt.tra_loi("Hà Nội", "u1")
        self.assertEqual(tt.doc_mac_dinh("u1")["key"], "353412")

    def test_trung_ten_trong_nuoc_thi_hien_menu(self):
        tt.tra_loi("thời tiết hôm nay", "u1")
        menu = tt.tra_loi("Tân Bình", "u1")
        self.assertEqual([g for _, g in menu["nut"]],
                         ["__thoi_tiet__:dat:1001", "__thoi_tiet__:dat:1002"])
        self.assertIsNone(tt.doc_mac_dinh("u1"), "chưa bấm chọn thì chưa được lưu")
        tt.tra_loi("__thoi_tiet__:dat:1002", "u1")
        self.assertEqual(tt.doc_mac_dinh("u1")["key"], "1002")

    def test_hoi_noi_khac_khong_doi_mac_dinh(self):
        tt.dat_mac_dinh("u1", HOANG_MAI_HN)
        ra = tt.tra_loi("thời tiết Hà Nội", "u1")
        self.assertIn("Thời tiết Hà Nội", ra["text"])
        self.assertEqual(tt.doc_mac_dinh("u1")["key"], "3558175")

    def test_noi_accuweather_khong_xac_nhan_thi_nhuong_model(self):
        """«không khí» khớp từ khoá thời tiết — đường tắt không được đoán nơi."""
        self.assertIsNone(tt.tra_loi("không khí gia đình dạo này thế nào", "u1"))


class CongCuDungChungLoi(_SoTam):
    def test_web_search_chua_co_mac_dinh_thi_dan_model_hoi(self):
        text = tt.cho_cong_cu("thời tiết hôm nay", "u1")
        self.assertIn("CHƯA có địa danh mặc định", text)
        self.assertIsNone(tt._lay_cho("u1"), "việc tự động không được mở chế độ chờ tên nơi")

    def test_web_search_cau_gop_tin_tuc_lay_dung_noi(self):
        text = tt.cho_cong_cu("tin tức mới trong ngày và thời tiết tại Hoàng Mai, Hà Nội", "u1")
        self.assertEqual(text, "Thời tiết Hoàng Mai lúc 13:23: 29°C.")

    def test_web_search_theo_mac_dinh(self):
        tt.dat_mac_dinh("u1", HA_NOI)
        self.assertIn("Thời tiết Hà Nội", tt.cho_cong_cu("dự báo thời tiết hôm nay", "u1"))

    def test_capability_doi_mac_dinh(self):
        tt.dat_mac_dinh("u1", HOANG_MAI_HN)
        ra = caps._h_thoi_tiet({"dia_danh": "Hà Nội", "dat_lam_mac_dinh": True}, {"user_id": "u1"})
        self.assertEqual(tt.doc_mac_dinh("u1")["key"], "353412")
        self.assertNotIn("choices", ra)
        self.assertNotIn("__thoi_tiet__", ra["text"])

    def test_capability_trung_ten_tra_choices(self):
        ra = caps._h_thoi_tiet({"dia_danh": "Tân Bình", "dat_lam_mac_dinh": True}, {"user_id": "u1"})
        self.assertEqual(len(ra["choices"]), 2)

    def test_capability_viec_theo_lich_khong_hoi_menu(self):
        ra = caps._h_thoi_tiet({"dia_danh": "Tân Bình"}, {"user_id": "u1", "auto_approve": True})
        self.assertNotIn("choices", ra)
        self.assertIn("Thời tiết Tân Bình", ra["text"])


class WebSearchChenKhoiThoiTiet(unittest.TestCase):
    def _chay(self, khoi):
        from services import mcp_client
        from services.search_service import search_service
        goi = {}

        def _search_all(query, **kw):
            goi.update(kw)
            return [{"title": "Tin", "snippet": "nội dung", "url": "https://vd.vn"}]

        with patch.object(tt, "cho_cong_cu", return_value=khoi), \
             patch.object(mcp_client, "prefetch_realtime_context", return_value=None), \
             patch.object(search_service, "search_all", side_effect=_search_all):
            ra = caps._h_web_search({"query": "tin tức và thời tiết hôm nay"}, {"user_id": "u1"})
        return ra, goi

    def test_co_khoi_thoi_tiet_thi_bo_vn_weather(self):
        ra, goi = self._chay("Thời tiết Hoàng Mai lúc 13:23: 29°C.")
        self.assertEqual(goi.get("bo_mcp"), ("vn_weather",))
        self.assertTrue(ra["text"].startswith("THỜI TIẾT (AccuWeather):\nThời tiết Hoàng Mai"))
        self.assertIn("nội dung", ra["text"])

    def test_khong_hoi_thoi_tiet_thi_giu_nguyen(self):
        ra, goi = self._chay(None)
        self.assertEqual(goi.get("bo_mcp"), ())
        self.assertNotIn("THỜI TIẾT", ra["text"])


class SearchAllBoMcp(unittest.TestCase):
    def test_server_bi_bo_khong_duoc_goi(self):
        from unittest.mock import PropertyMock
        from services import mcp_client as mc
        from services.search_service import SearchService, _intent_router
        da_goi = []
        with patch.object(_intent_router, "detect", return_value={
                "mcp_tools": ["vn_weather", "vn_search"], "kb_collections": [], "needs_live": True}), \
             patch.object(SearchService, "search_combo", new_callable=PropertyMock, return_value=["test"]), \
             patch.object(SearchService, "_get_backend", return_value=None), \
             patch.object(mc, "call_mcp_tool",
                          side_effect=lambda tool, args, **kw: da_goi.append(tool) or "kết quả đủ dài để được nhận vào"):
            SearchService().search_all("thời tiết Hoàng Mai", bo_mcp=("vn_weather",))
        self.assertNotIn("get_current_weather", da_goi)
        self.assertIn("search_web", da_goi)


class OrchestratorKhongCanQuyenHA(_SoTam):
    """Thời tiết tách khỏi HA: luồng chỉ có quyền «web» vẫn hỏi–đặt–báo được."""

    def _chay(self, cau, allow, mem=""):
        import services.agent.orchestrator as orch
        from services import bai_hoc
        from services.agent import state
        goi_model = []

        def _model(*a, **k):
            goi_model.append(a)
            # Bày lại GIỮ đủ nội dung gốc (chốt «mất tin» của `_ap_so_thich` loại
            # bản cụt) rồi thêm phần lời dặn.
            goc = str(a[1][-1].get("content") or "").split("Nội dung:\n", 1)[-1]
            return {"choices": [{"message": {"content": goc + "\nLưu ý: nhớ mang ô."}}]}

        with patch.object(orch, "call_model", side_effect=_model), \
             patch.object(orch, "_persist_history", lambda *a, **k: None), \
             patch.object(state, "load_memory", return_value=mem), \
             patch.object(bai_hoc, "tra", return_value=[]), \
             patch.object(bai_hoc, "nen_hoi_lai", return_value=False):
            ra = orch._orchestrate_locked(cau, "u_orch", allow=allow, ha_fastpath=False)
        return ra, goi_model

    def test_hoi_dat_bao_khong_qua_model(self):
        ra, model = self._chay("thời tiết hôm nay", {"web"})
        self.assertIn("địa danh mặc định", ra["text"])
        ra, model2 = self._chay("Hoàng Mai", {"web"})
        self.assertEqual(tt.doc_mac_dinh("u_orch")["key"], "3558175")
        self.assertIn("Thời tiết Hoàng Mai", ra["text"])
        self.assertIn("__thoi_tiet__:doi", [c["send"] for c in ra.get("choices") or []])
        self.assertEqual(model + model2, [])

    def test_loi_dan_them_khuyen_cao_van_duoc_ap_va_con_nut(self):
        """Lời dặn đã lưu ngày 29/08: «hỏi thời tiết thì thêm lưu ý, khuyến cáo»."""
        tt.dat_mac_dinh("u_orch", HOANG_MAI_HN)
        dan = ("- Khi người dùng hỏi thời tiết, ngoài thông tin thời tiết cần thêm phần "
               "lưu ý/lời dặn dò, khuyến cáo phù hợp như mang ô/áo mưa.")
        ra, model = self._chay("thời tiết hôm nay", {"web"}, mem=dan)
        self.assertEqual(len(model), 1, "một lượt bày lại theo lời dặn")
        he_thong = " ".join(str(m.get("content")) for m in model[0][1] if m.get("role") == "system")
        self.assertIn("khuyến cáo", he_thong)
        self.assertIn("Lưu ý: nhớ mang ô.", ra["text"])
        self.assertIn("Thời tiết Hoàng Mai", ra["text"])
        self.assertIn("__thoi_tiet__:doi", [c["send"] for c in ra.get("choices") or []])

    def test_luong_khong_duoc_tra_mang_thi_khong_vao(self):
        ra, model = self._chay("thời tiết hôm nay", {"homeassistant"})
        self.assertNotIn("địa danh mặc định", ra.get("text") or "")
        self.assertIsNone(tt._lay_cho("u_orch"))


class DuongChatKhongConDocThoiTietHA(unittest.TestCase):
    """Loa HA vẫn đọc thực thể qua RT1; kênh chat bot thì không."""

    def test_fastpath_chat_khong_tra_thoi_tiet_ha(self):
        khong = dict.fromkeys(["_ha_local_level", "_ha_local_intent", "_ha_local_entity_state",
                               "_ha_local_query", "_ha_local_status", "_ha_local_lunar",
                               "_ha_local_bao"])
        vas = [patch.object(api, ten, return_value=None) for ten in khong]
        vas.append(patch.object(api, "_ha_local_weather", return_value="Thời tiết HA 30°C"))
        for v in vas:
            v.start()
        try:
            self.assertEqual(api.ha_local_fastpath_chi_tiet("thời tiết hôm nay"), (None, False, ""))
            self.assertNotIn("Thời tiết HA", api._collect_fastpath_facts(
                [{"role": "user", "content": "thời tiết hôm nay"}]))
        finally:
            for v in reversed(vas):
                v.stop()


if __name__ == "__main__":
    unittest.main()
