"""Chụp webcam / ảnh màn hình máy đã cài agent — khoá lại các CHỐT quyền.

Đây là nhóm năng lực duy nhất nhìn thấy **người** đang ngồi trước máy và **việc
họ đang làm** (tin nhắn riêng, tài khoản đang mở). Allowlist thư mục — thứ chặn
được lệnh đọc file — không che nổi một ảnh màn hình. Nên có ba chốt độc lập, và
file này khoá cả ba:

1. Tầng bot: chỉ **admin** gọi được. Người trong danh bạ nhờ cách nào cũng bị từ
   chối — không phải tiện ích chung.
2. Tầng gateway: thiết bị phải bật `can_capture` tường minh trong config.
3. Tầng agent (kiểm ở `deploy/device_agent/c2a_agent.py`): phải chạy kèm
   `--allow-capture`. Gateway bị chiếm cũng không mở được quyền trên máy.

Chốt quan trọng nhất được khoá ở đây: khi quyền TẮT thì **không hề gọi xuống
thiết bị**. Nếu chỉ chặn ở câu trả lời mà vẫn gửi lệnh đi, camera đã sáng đèn
rồi mới bị từ chối — người bị chụp thấy đèn, và ảnh đã tồn tại trong RAM máy họ.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.agent import capabilities as caps


class _PhienGia:
    """Phiên thiết bị giả — chỉ cần đúng một thuộc tính quyền."""

    def __init__(self, can_capture: bool) -> None:
        self.can_capture = can_capture


def _goi(args: dict, ctx: dict, thiet_bi: list[dict] | None = None,
         phien: _PhienGia | None = None) -> tuple[dict, list]:
    """Gọi tool, trả (kết quả, danh sách lệnh THỰC SỰ gửi xuống thiết bị)."""
    da_goi: list = []
    with patch("services.device_agents.list_devices",
               return_value=thiet_bi if thiet_bi is not None else []), \
         patch("services.device_agents.get", return_value=phien), \
         patch("services.device_agents.call_sync",
               side_effect=lambda *a, **k: (da_goi.append(a),
                                            {"ok": False, "error": "test"})[1]):
        ra = caps._h_device_capture(args, ctx)
    return ra, da_goi


class TestChiAdmin(unittest.TestCase):
    def test_user_thuong_bi_tu_choi(self):
        ra, _ = _goi({"kind": "webcam"}, {"user_id": "u9"})
        self.assertIn("chỉ chủ máy", ra["text"])

    def test_user_thuong_khong_gui_lenh_xuong_may(self):
        """Từ chối phải xảy ra TRƯỚC khi camera được chạm tới."""
        _, da_goi = _goi({"kind": "webcam"}, {"user_id": "u9"},
                         thiet_bi=[{"name": "may1", "connected": True}],
                         phien=_PhienGia(True))
        self.assertEqual(da_goi, [])

    def test_ctx_rong_coi_nhu_khong_phai_admin(self):
        """Thiếu ngữ cảnh không bao giờ được suy ra thành quyền — fail-closed."""
        ra, _ = _goi({"kind": "screenshot"}, {})
        self.assertIn("chỉ chủ máy", ra["text"])


class TestChotQuyenThietBi(unittest.TestCase):
    def test_can_capture_tat_thi_chan(self):
        ra, _ = _goi({"kind": "webcam"}, {"is_admin": True},
                     thiet_bi=[{"name": "may1", "connected": True}],
                     phien=_PhienGia(False))
        self.assertIn("chưa được cấp quyền", ra["text"])

    def test_can_capture_tat_thi_khong_gui_lenh_xuong_may(self):
        _, da_goi = _goi({"kind": "webcam"}, {"is_admin": True},
                         thiet_bi=[{"name": "may1", "connected": True}],
                         phien=_PhienGia(False))
        self.assertEqual(da_goi, [])

    def test_can_capture_bat_thi_moi_gui_lenh(self):
        _, da_goi = _goi({"kind": "screenshot"}, {"is_admin": True},
                         thiet_bi=[{"name": "may1", "connected": True}],
                         phien=_PhienGia(True))
        self.assertEqual([a[1] for a in da_goi], ["screenshot"])


class TestChonMay(unittest.TestCase):
    def test_khong_may_nao_noi_thi_noi_that(self):
        ra, _ = _goi({"kind": "webcam"}, {"is_admin": True}, thiet_bi=[])
        self.assertIn("không có thiết bị nào đang kết nối", ra["text"])

    def test_mot_may_thi_tu_chon(self):
        _, da_goi = _goi({"kind": "webcam"}, {"is_admin": True},
                         thiet_bi=[{"name": "chi-mot", "connected": True}],
                         phien=_PhienGia(True))
        self.assertEqual([a[0] for a in da_goi], ["chi-mot"])

    def test_nhieu_may_thi_hoi_lai_chu_khong_doan(self):
        """Đoán sai máy = chụp máy người khác. Phải hỏi, không được chọn bừa."""
        ds = [{"name": "a", "label": "Case", "connected": True},
              {"name": "b", "label": "Laptop", "connected": True}]
        ra, da_goi = _goi({"kind": "screenshot"}, {"is_admin": True},
                          thiet_bi=ds, phien=_PhienGia(True))
        self.assertIn("máy nào", ra["text"])
        self.assertIn("Case", ra["text"])
        self.assertIn("Laptop", ra["text"])
        self.assertEqual(da_goi, [])

    def test_may_offline_thi_bao_offline(self):
        """Máy CÓ trong sổ mà không kết nối → bảo đúng là chưa kết nối.

        Bản cũ chỉ nói đúng khi KHÔNG máy nào đang kết nối; còn máy khác đang
        online thì nó trả "em không rõ máy nào" cho một cái máy có thật, đẩy
        người dùng đi sửa tên trong khi việc cần làm là bật agent lên.
        (Khuôn cũ của test này truyền một cái tên KHÔNG có trong sổ nên nó kiểm
        nhánh "tên lạ", không phải nhánh offline như tên gọi.)
        """
        ra, _ = _goi({"kind": "webcam", "device": "vang-mat"}, {"is_admin": True},
                     thiet_bi=[{"name": "vang-mat", "connected": False},
                               {"name": "khac", "connected": True}], phien=None)
        self.assertIn("không kết nối", ra["text"])

    def test_ten_la_hoan_toan_thi_hoi_lai_chu_khong_bao_offline(self):
        ra, _ = _goi({"kind": "webcam", "device": "khong-ton-tai"}, {"is_admin": True},
                     thiet_bi=[{"name": "khac", "connected": True}], phien=None)
        self.assertIn("không rõ máy", ra["text"])
        self.assertIn("khac", ra["text"])


class TestLoaiChup(unittest.TestCase):
    def test_tu_tieng_viet_cung_hieu(self):
        for noi, mong in (("camera", "webcam"), ("màn hình", "screenshot"),
                          ("cam", "webcam"), ("screen", "screenshot")):
            _, da_goi = _goi({"kind": noi}, {"is_admin": True},
                             thiet_bi=[{"name": "m", "connected": True}],
                             phien=_PhienGia(True))
            self.assertEqual([a[1] for a in da_goi], [mong], f"kind={noi}")

    def test_loai_la_thi_ve_chup_man_hinh(self):
        """Model đoán bừa `kind` không được thành BẬT CAMERA — mặc định an toàn
        hơn là chụp màn hình, thứ không nhìn vào mặt ai."""
        _, da_goi = _goi({"kind": "xyz"}, {"is_admin": True},
                         thiet_bi=[{"name": "m", "connected": True}],
                         phien=_PhienGia(True))
        self.assertEqual([a[1] for a in da_goi], ["screenshot"])


class TestDoPhanGiaiWebcam(unittest.TestCase):
    """Ảnh webcam phải chụp ở độ phân giải THẬT của cam, không phải 640×480.

    Bản trước gọi `cv2.VideoCapture(idx)` rồi đọc khung luôn, không đặt kích
    thước, nên OpenCV lấy chế độ mặc định của driver — với DirectShow trên
    Windows gần như luôn là 640×480 dù cam hỗ trợ 1080p/4K.
    """

    def _agent(self) -> dict:
        """Nạp RIÊNG phần chụp webcam của agent — import cả file kéo theo
        websockets/cv2 vốn chỉ có trên máy cài agent."""
        import ast
        import pathlib
        goc = pathlib.Path(__file__).resolve().parents[1]
        src = (goc / "deploy" / "device_agent" / "c2a_agent.py").read_text("utf-8")
        can = ("_DPG_WEBCAM", "_DPG_MAC_DINH", "_TRAN_ANH_BYTE",
               "_dat_do_phan_giai", "_nen_jpeg_vua_tran")
        phan = ["from __future__ import annotations"]
        for n in ast.parse(src).body:
            if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in can:
                phan.append(ast.get_source_segment(src, n))
            if isinstance(n, ast.FunctionDef) and n.name in can:
                phan.append(ast.get_source_segment(src, n))
        ns: dict = {}
        exec("\n".join(phan), ns)
        return ns

    def test_mac_dinh_khong_con_la_mac_dinh_cua_driver(self):
        ns = self._agent()
        self.assertEqual(ns["_DPG_MAC_DINH"], "cao")
        self.assertEqual(ns["_DPG_WEBCAM"]["cao"], (1920, 1080))
        self.assertIsNone(ns["_DPG_WEBCAM"]["nhanh"])   # 'nhanh' = giữ hành vi cũ

    def test_dat_MJPG_TRUOC_kich_thuoc(self):
        """Webcam USB chỉ có chế độ cao ở luồng MJPG; đặt sau kích thước là vô ích."""
        class _Cv2:
            CAP_PROP_FOURCC, CAP_PROP_FRAME_WIDTH, CAP_PROP_FRAME_HEIGHT = 6, 3, 4

            @staticmethod
            def VideoWriter_fourcc(*a):
                return 1196444237

        class _Cap:
            def __init__(self):
                self.thu_tu = []

            def set(self, prop, val):
                self.thu_tu.append(prop)
                return True

        ns = self._agent()
        cap = _Cap()
        ns["_dat_do_phan_giai"](_Cv2, cap, (3840, 2160))
        self.assertEqual(cap.thu_tu, [_Cv2.CAP_PROP_FOURCC,
                                      _Cv2.CAP_PROP_FRAME_WIDTH,
                                      _Cv2.CAP_PROP_FRAME_HEIGHT])

    def test_anh_qua_co_thi_ha_chat_luong_chu_khong_bao_loi(self):
        """Đèn camera đã sáng, người dùng đã chờ — trả ảnh nhẹ hơn vẫn hơn báo lỗi."""
        ns = self._agent()

        class _Cv2:
            IMWRITE_JPEG_QUALITY = 1

            @staticmethod
            def imencode(duoi, frame, tham_so):
                chat_luong = tham_so[1]
                class _Buf:
                    def tobytes(_):
                        return b"x" * (chat_luong * 100)
                return True, _Buf()

        raw, cl = ns["_nen_jpeg_vua_tran"](_Cv2, object(), 6000)
        self.assertLessEqual(len(raw), 6000)
        self.assertEqual(cl, 55)          # 85 và 70 quá cỡ, 55 vừa

    def test_anh_vua_co_thi_giu_chat_luong_cao_nhat(self):
        ns = self._agent()

        class _Cv2:
            IMWRITE_JPEG_QUALITY = 1

            @staticmethod
            def imencode(duoi, frame, tham_so):
                class _Buf:
                    def tobytes(_):
                        return b"x" * 100
                return True, _Buf()

        raw, cl = ns["_nen_jpeg_vua_tran"](_Cv2, object(), 6 * 1024 * 1024)
        self.assertEqual(cl, 85)

    def test_muc_la_thi_ve_mac_dinh_chu_khong_hong(self):
        ns = self._agent()
        for xau in ("4k", "", "siêu nét", None):
            dpg = str(xau or ns["_DPG_MAC_DINH"]).strip().lower()
            if dpg not in ns["_DPG_WEBCAM"]:
                dpg = ns["_DPG_MAC_DINH"]
            self.assertIn(dpg, ns["_DPG_WEBCAM"])


class TestTruyenDoPhanGiaiXuongMay(unittest.TestCase):
    """Tham số phải ĐI XUỐNG agent — đặt trong lược đồ mà không truyền là vô nghĩa."""

    def test_truyen_khi_hop_le(self):
        _, da_goi = _goi({"kind": "webcam", "do_phan_giai": "max"},
                         {"user_id": "u1", "is_admin": True},
                         thiet_bi=[{"name": "m", "connected": True}],
                         phien=_PhienGia(True))
        self.assertEqual(da_goi[0][2].get("do_phan_giai"), "max")

    def test_muc_la_thi_khong_truyen_gi(self):
        _, da_goi = _goi({"kind": "webcam", "do_phan_giai": "8k"},
                         {"user_id": "u1", "is_admin": True},
                         thiet_bi=[{"name": "m", "connected": True}],
                         phien=_PhienGia(True))
        self.assertNotIn("do_phan_giai", da_goi[0][2])

    def test_chup_man_hinh_khong_dinh_dang_tham_so_webcam(self):
        _, da_goi = _goi({"kind": "screenshot", "do_phan_giai": "max"},
                         {"user_id": "u1", "is_admin": True},
                         thiet_bi=[{"name": "m", "connected": True}],
                         phien=_PhienGia(True))
        self.assertNotIn("do_phan_giai", da_goi[0][2])

    def test_co_trong_luoc_do_tool(self):
        props = caps.CAPABILITIES["device_capture"].parameters["properties"]
        self.assertEqual(props["do_phan_giai"]["enum"], ["nhanh", "cao", "max"])


class TestDangKyTool(unittest.TestCase):
    def test_co_trong_bo_cong_cu(self):
        self.assertIn("device_capture", caps.CAPABILITIES)

    def test_co_nhom_quyen_rieng(self):
        """Chưa gắn nhóm là rơi vào `_ungrouped` rồi bị chặn ở thread có lọc.
        Nhóm phải RIÊNG, không gộp vào "server": được xem máy chủ không có nghĩa
        là được nhìn vào máy người khác."""
        self.assertEqual(caps.group_of("device_capture"), "device")
        self.assertIn("device", caps.all_groups())

    def test_can_nguoi_dung_duyet(self):
        """risk=CHANGE → bot phải xin duyệt trước khi chụp, không tự bật camera."""
        self.assertEqual(caps.CAPABILITIES["device_capture"].risk, caps.CHANGE)


if __name__ == "__main__":
    unittest.main()
