"""Câu điều khiển THIẾT BỊ của người dùng phải tới được tool `device_*`.

Bối cảnh (đo thật 2026-07-29, thiết bị `case-win` đang kết nối mà bot vẫn nói
không truy cập được): có BA tầng cùng chặn, sửa một tầng không đủ.

  1. `device_fs` chưa bật  → 71 tool đang bật, không có `device_*` nào.
     (đây là cấu hình, không phải mã — test không khoá được, xem `trang_thai`.)
  2. Bộ chọn không chọn    → 8/8 câu thử chỉ ra `search_web`/`web_search_exa`.
     Tên tool là `device_*`, không khớp `sub` nào trong `_MCP_INTENT_MAP`; còn
     nhánh server-admin thì lọc riêng `ssh_`/`fs_` nên càng loại `device_*`.
  3. Nhận nhầm lệnh nhà    → "mở/đọc/tạo/sửa/xoá/khoá/tắt" đều là
     `_CONTROL_VERBS`, nên "đọc file D:\\a.txt trên máy tính", "khoá máy tính",
     "tắt máy tính" rơi vào nhánh smart-home; nhánh đó đặt `mcp_tools = []`
     → mất SẠCH tool. 3/8 câu thử bị.

Tầng 2 và 3 là mã, khoá ở đây.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import services.mcp_client as mc  # noqa: E402
import services.protocol.openai_v1_chat_complete as m  # noqa: E402

# 8 câu điều khiển thiết bị thật, đúng cách người dùng nói qua Zalo/Telegram.
CAU_THIET_BI = (
    "đọc file D:\\baocao.txt trên máy tính",
    "liệt kê file trong ổ D của case-win",
    "máy tính còn bao nhiêu RAM",
    "khoá máy tính lại giúp tôi",
    "chụp màn hình máy tính",
    "trên case-win có file nào trong E:\\ không",
    "tắt máy tính đi",
    "xem tiến trình đang chạy trên laptop",
)

# Câu KHÔNG phải thiết bị — nếu những câu này cũng kéo device_* thì mỗi lượt chat
# thường phải cõng thêm 13 schema vô ích.
CAU_KHAC = (
    "bật đèn phòng khách",
    "giá vàng hôm nay bao nhiêu",
    "bài 3 Tiếng Việt 1 dạy gì",
    "thời tiết Hà Nội",
    "dịch câu này sang tiếng Anh",
)

_DEVICE_TOOLS = ("device_list", "device_ls", "device_read", "device_write",
                 "device_sysinfo", "device_resources", "device_processes",
                 "device_screen")
_OTHER_TOOLS = ("ssh_run", "ssh_locate", "fs_list", "fs_read",
                "search_web", "web_search_exa", "wikipedia_search")


def _tool(name: str) -> dict:
    return {"type": "function",
            "function": {"name": name, "description": "", "parameters": {}}}


def _fake_tools() -> list[dict]:
    return [_tool(n) for n in _DEVICE_TOOLS + _OTHER_TOOLS]


def _names(tools) -> list[str]:
    return [(t.get("function") or {}).get("name", "") for t in (tools or [])]


class _Base(unittest.TestCase):
    def setUp(self):
        self._real_enabled = mc.get_enabled_mcp_tools
        mc.get_enabled_mcp_tools = _fake_tools
        # Thiết bị "đã khai" — dựng thẳng cache để không phụ thuộc config máy chạy.
        mc._device_names_cache = {"case-win"}
        mc._device_names_ts = 9e18   # không bao giờ hết hạn trong lúc test
        mc._ssh_names_cache = {"nvr"}
        mc._ssh_names_ts = 9e18

    def tearDown(self):
        mc.get_enabled_mcp_tools = self._real_enabled
        mc._device_names_ts = 0.0
        mc._ssh_names_ts = 0.0


class TestNhanRaCauThietBi(_Base):
    def test_tam_cau_deu_nhan_ra(self):
        for c in CAU_THIET_BI:
            self.assertTrue(mc.is_device_query(c), f"không nhận ra: {c}")

    def test_cau_khac_khong_bi_nhan_lam(self):
        for c in CAU_KHAC:
            self.assertFalse(mc.is_device_query(c), f"nhận nhầm: {c}")

    def test_ten_thiet_bi_moi_khai_la_nhan_ngay(self):
        """Tên đọc từ config nên khai máy mới là hỏi được, không cần sửa mã."""
        mc._device_names_cache = {"case-win", "may-ban-hang"}
        self.assertTrue(mc.is_device_query("còn bao nhiêu chỗ trống ở may-ban-hang"))

    def test_ten_qua_ngan_khong_khop_bua(self):
        """Tên < 3 ký tự không được biến mọi câu thành câu thiết bị."""
        mc._device_names_cache = {"pi"}
        self.assertFalse(mc.is_device_query("pi là số 3.14"))

    def test_goi_bang_NHAN_nhu_tren_giao_dien(self):
        """Người dùng gọi máy bằng cái tên họ THẤY, không phải khoá cấu hình.

        Ca thật (log chat 2026-07-29 10:09): khoá `case-win`, nhãn "Case KT".
        Câu "kiểm tra tài nguyên case KT" trước đây trả False → bot đi tìm cảm
        biến Home Assistant tên "case KT", không thấy, rồi xin IP + user SSH +
        mật khẩu trong khi agent đang nối sẵn.
        """
        mc._device_names_cache = {"case-win", "case kt"}
        for c in ("kiểm tra tài nguyên case KT",
                  "case KT còn bao nhiêu RAM",
                  "Case KT ổ đĩa còn trống không",
                  "CPU của case kt đang bao nhiêu phần trăm"):
            self.assertTrue(mc.is_device_query(c), f"không nhận ra: {c}")

    def test_nhan_nhieu_tu_khong_bi_cat_thanh_token(self):
        """Nhãn nhiều từ phải so CHUỖI CON — nó không bao giờ là một token."""
        mc._device_names_cache = {"may ban hang so 1"}
        self.assertTrue(mc.is_device_query("xem ổ đĩa may ban hang so 1"))
        # nhưng một phần rời của nhãn thì KHÔNG được kích hoạt
        self.assertFalse(mc.is_device_query("hang so 1 là hàng đầu tiên"))

    def test_ten_co_dau_gach_khop_khi_du_cac_phan(self):
        """`case-win` viết rời thành "case win" vẫn phải nhận ra."""
        mc._device_names_cache = {"case-win"}
        self.assertTrue(mc.is_device_query("dung lượng ổ đĩa của case win"))

    def test_danh_sach_thiet_bi(self):
        """Câu thứ hai người dùng hỏi ngay sau đó."""
        mc._device_names_cache = {"case-win"}
        self.assertTrue(mc.is_device_query("kiểm tra danh sách thiết bị của tôi"))

    def test_giu_che_do_o_luot_sau(self):
        """Đã gọi device_* rồi thì câu tiếp vẫn còn tool, không rơi về catch-all."""
        msgs = [{"role": "user", "content": "liệt kê file ổ D"},
                {"role": "assistant", "tool_calls": [
                    {"function": {"name": "device_ls"}}]},
                {"role": "user", "content": "có file nào nữa không"}]
        self.assertTrue(mc.is_device_query("có file nào nữa không", msgs))


class TestBoChonTraDungTool(_Base):
    def test_moi_cau_deu_ra_tool_device(self):
        for c in CAU_THIET_BI:
            got = _names(mc.get_relevant_mcp_tools(c, None))
            self.assertTrue([g for g in got if g.startswith("device_")],
                            f"{c} → {got}")

    def test_khong_kem_web_search(self):
        """Lệnh thiết bị không cần tìm web; kèm vào là mời model đi vòng."""
        got = _names(mc.get_relevant_mcp_tools("đọc file D:\\a.txt trên máy tính"))
        self.assertNotIn("search_web", got)

    def test_thiet_bi_thang_server_admin(self):
        """'ổ đĩa/dung lượng' là từ khoá server-admin — nhưng có 'máy tính' thì
        phải ra tool thiết bị, không phải ssh_/fs_."""
        got = _names(mc.get_relevant_mcp_tools("ổ đĩa D trên máy tính còn bao nhiêu dung lượng"))
        self.assertTrue([g for g in got if g.startswith("device_")], got)

    def test_vua_server_vua_thiet_bi_thi_du_ca_hai(self):
        got = _names(mc.get_relevant_mcp_tools("copy log từ nvr sang máy tính của tôi"))
        self.assertTrue([g for g in got if g.startswith("device_")], got)
        self.assertTrue([g for g in got if g.startswith(("ssh_", "fs_"))], got)

    def test_chua_bat_device_fs_thi_khong_chet(self):
        """Chưa bật MCP thiết bị → vẫn trả bộ catch-all, không ném lỗi."""
        mc.get_enabled_mcp_tools = lambda: [_tool(n) for n in _OTHER_TOOLS]
        got = _names(mc.get_relevant_mcp_tools("đọc file D:\\a.txt trên máy tính"))
        self.assertTrue(got, "phải còn catch-all")
        self.assertFalse([g for g in got if g.startswith("device_")])


class TestKhongBiNhanhNhaThongMinhNuot(_Base):
    """Tầng 3 — tầng đã làm 3/8 câu mất sạch tool."""

    def setUp(self):
        super().setUp()
        self._real_ha = None
        import services.ha_client as ha
        self._ha_mod = ha
        self._real_ha = ha.get_ha_tools
        ha.get_ha_tools = lambda: []

    def tearDown(self):
        self._ha_mod.get_ha_tools = self._real_ha
        super().tearDown()

    def test_cau_co_dong_tu_dieu_khien_van_con_tool(self):
        for c in ("đọc file D:\\baocao.txt trên máy tính",
                  "khoá máy tính lại giúp tôi",
                  "tắt máy tính đi"):
            self.assertTrue(m._is_smarthome_query(c),
                            f"tiền đề của test sai — {c} phải trông giống lệnh nhà")
            got = _names(m._inject_mcp_tools(None, user_text=c, messages=[]))
            self.assertTrue([g for g in got if g.startswith("device_")],
                            f"{c} → {got}")

    def test_lenh_nha_that_khong_bi_keo_them_device(self):
        got = _names(m._inject_mcp_tools(None, user_text="bật đèn phòng khách",
                                        messages=[]))
        self.assertFalse([g for g in got if g.startswith("device_")], got)

    def test_luong_bi_loc_nhom_server_thi_khong_co_cua_sau(self):
        """Thread thiếu nhóm 'server' → device_* phải bị lột, vì nó đọc/ghi file
        trên máy thật, cùng nhóm quyền với ssh_/fs_ trên UI."""
        got = _names(m._inject_mcp_tools(
            None, user_text="đọc file D:\\a.txt trên máy tính", messages=[],
            no_server_admin=True))
        self.assertFalse([g for g in got if g.startswith("device_")], got)


class TestNhacModelDungTool(_Base):
    def test_hint_neu_ten_thiet_bi(self):
        h = mc.device_system_hint()
        self.assertIn("case-win", h)

    def test_hint_chan_viec_di_GHI_NHO_thay_vi_goi_tool(self):
        """Log thật 2026-07-30 08:28: người dùng gõ "Danh sách thiết bị của tôi",
        model gọi tool `remember` để LƯU LẠI đoạn hint này thay vì gọi
        `device_list()` — trả lời "Em định Ghi nhớ:…". Hint phải nói thẳng đây là
        thông tin nền, không phải việc cần làm."""
        mc._device_names_cache = {"case-win", "case kt"}
        h = mc.device_system_hint().lower()
        self.assertIn("remember", h)
        self.assertIn("device_list()", h)
        self.assertIn("device_list", h)

    def test_hint_cam_bao_nguoi_dung_tu_lam(self):
        """Không có câu này thì model vẫn trả lời 'bạn mở File Explorer rồi…'
        dù đang có tool trong tay."""
        h = mc.device_system_hint().lower()
        self.assertIn("không", h)
        self.assertTrue("file explorer" in h or "tu mo" in h or "tự mở" in h)

    def test_chua_khai_thiet_bi_thi_hint_rong(self):
        mc._device_names_cache = set()
        self.assertEqual(mc.device_system_hint(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestMoKhoaManHinh(unittest.TestCase):
    """Định tuyến câu "mở khoá màn hình" — log chat 30/07 (thread zalop).

    Câu đó trả False nên KHÔNG tool thiết bị nào được nạp; model kết luận chức
    năng bị tắt và trả "[BLOCKED]", orchestrator thấy [BLOCKED] thì im lặng
    tuyệt đối. Người dùng gửi tin và không nhận được gì — tệ hơn một câu từ chối,
    vì không phân biệt được với bot chết.
    """

    def test_mo_khoa_man_hinh_la_lenh_thiet_bi(self):
        for t in ("Mở khóa màn hình", "mở khoá màn hình", "mo khoa man hinh",
                  "mở khoá máy", "khoá màn hình lại", "unlock màn hình",
                  "mở khoá windows giúp em"):
            with self.subTest(t):
                self.assertTrue(mc.is_device_query(t, None), t)

    def test_khong_lan_san_mo_khoa_cua_cua_nha_thong_minh(self):
        """"mở khoá cửa" là lệnh Home Assistant thật (domain lock) — nhận nhầm
        sang thiết bị là mất đường điều khiển cửa."""
        for t in ("mở khoá cửa", "mở khóa cửa chính", "khoá cửa lại giúp em",
                  "mở cửa gara"):
            with self.subTest(t):
                self.assertFalse(mc.is_device_query(t, None), t)
