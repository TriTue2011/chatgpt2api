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
        ra, _ = _goi({"kind": "webcam", "device": "vang-mat"}, {"is_admin": True},
                     thiet_bi=[{"name": "khac", "connected": True}], phien=None)
        self.assertIn("không kết nối", ra["text"])


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
