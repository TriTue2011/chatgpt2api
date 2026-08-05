"""Công tắc "chỉ người trong danh sách mới được giao tiếp" (theo từng thread).

Trước đây bot có lọc theo NGƯỜI (`thread_user_filters`) nhưng nó chỉ thu hẹp
CHỨC NĂNG, không chặn được ai nói chuyện: người bị lọc mà không tick nhóm nào
thì quyền là tập RỖNG — khác `None` (chưa cấu hình) nên vẫn qua cổng `permitted`,
bot vẫn tán gẫu bình thường, chỉ là không gọi được tool. Không có cách nào bảo
"trong nhóm này chỉ mấy người sau được nói chuyện".

Công tắc mới `thread_user_only` (khóa giống `thread_filters`) trả lời đúng câu
đó. Yêu cầu 05/08 của chủ máy, nguyên văn hai vế:

    "Bật lên thì ai không có bản ghi trong thread_user_filters sẽ bị bot bỏ qua
     im lặng" — và — "Chỉ là không phản hồi nhưng memory vẫn phải có".

Vế sau là lý do chốt chặn được đặt SAU khối ghi nhật ký nhóm trong cả hai kênh
có nhật ký: ghi ≠ trả lời, cùng lý lẽ với cổng tag.

File này khoá bốn hành vi:
  * tắt công tắc (mặc định) → mọi người vẫn nói được, y như trước;
  * bật → người CÓ bản ghi qua được, người KHÔNG có bị chặn;
  * bản ghi ở cấp topic thắng bản ghi cả nhóm;
  * chốt chặn nằm SAU khối nhật ký ở cả zalo_personal lẫn telegram_bot.
"""
from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from services.agent import capabilities as caps
from services.config import config

GOC = pathlib.Path(__file__).resolve().parents[1]

NHOM = "tg:bot1:-100123"
NGUOI_CO = "u_co_ten"
NGUOI_KHONG = "u_nguoi_la"


def _cfg(**them):
    goc = {"thread_user_filters": {f"{NHOM}:{NGUOI_CO}": ["homeassistant"]}}
    goc.update(them)
    return mock.patch.dict(config.data, goc)


class CongTacTatTests(unittest.TestCase):
    def test_khong_cau_hinh_thi_ai_cung_noi_duoc(self):
        with _cfg():
            for ai in (NGUOI_CO, NGUOI_KHONG, ""):
                self.assertTrue(
                    caps.duoc_giao_tiep("tg", "bot1", "-100123", ai), ai)

    def test_ghi_False_cung_la_tat(self):
        with _cfg(thread_user_only={NHOM: False}):
            self.assertTrue(caps.duoc_giao_tiep("tg", "bot1", "-100123", NGUOI_KHONG))


class CongTacBatTests(unittest.TestCase):
    def test_nguoi_co_ban_ghi_noi_duoc_nguoi_la_bi_chan(self):
        with _cfg(thread_user_only={NHOM: True}):
            self.assertTrue(caps.duoc_giao_tiep("tg", "bot1", "-100123", NGUOI_CO))
            self.assertFalse(caps.duoc_giao_tiep("tg", "bot1", "-100123", NGUOI_KHONG))

    def test_ban_ghi_rong_van_tinh_la_co_ten(self):
        """Tick 0 nhóm chức năng = "được nói, không được dùng tool" — vẫn có tên."""
        with mock.patch.dict(config.data, {
                "thread_user_filters": {f"{NHOM}:{NGUOI_CO}": []},
                "thread_user_only": {NHOM: True}}):
            self.assertTrue(caps.duoc_giao_tiep("tg", "bot1", "-100123", NGUOI_CO))
            # …và quyền chức năng vẫn là tập rỗng, không phải None.
            self.assertEqual(
                caps.allowed_groups_for_member("tg", "bot1", "-100123", NGUOI_CO),
                set())

    def test_khoa_khong_kem_bot_van_khop(self):
        """Khóa 'plat:chat' (áp cho mọi bot) là cấp rộng hơn, vẫn phải ăn."""
        with mock.patch.dict(config.data, {
                "thread_user_filters": {f"tg:-100123:{NGUOI_CO}": ["homeassistant"]},
                "thread_user_only": {"tg:-100123": True}}):
            self.assertTrue(caps.duoc_giao_tiep("tg", "bot1", "-100123", NGUOI_CO))
            self.assertFalse(caps.duoc_giao_tiep("tg", "bot1", "-100123", NGUOI_KHONG))

    def test_topic_thang_ca_nhom(self):
        with mock.patch.dict(config.data, {
                "thread_user_filters": {f"{NHOM}#7:{NGUOI_CO}": ["homeassistant"]},
                "thread_user_only": {NHOM: False, f"{NHOM}#7": True}}):
            self.assertFalse(caps.duoc_giao_tiep("tg", "bot1", "-100123", NGUOI_KHONG, 7))
            self.assertTrue(caps.duoc_giao_tiep("tg", "bot1", "-100123", NGUOI_CO, 7))
            # Ngoài topic đó thì cả nhóm vẫn mở.
            self.assertTrue(caps.duoc_giao_tiep("tg", "bot1", "-100123", NGUOI_KHONG))


class GhiVanPhaiCoTests(unittest.TestCase):
    """"Chỉ là không phản hồi nhưng memory vẫn phải có" — chốt chặn đặt SAU nhật ký.

    Kiểm ở mức chuỗi nguồn: import hai module kênh sẽ kéo theo cả zalo-server /
    Telegram client, mà thứ cần khoá ở đây là THỨ TỰ hai khối trong hàm.
    """

    def _vi_tri(self, ten: str) -> tuple[int, int]:
        src = (GOC / "services" / ten).read_text("utf-8")
        return src.index("_chatlog.ghi("), src.index("duoc_giao_tiep(")

    def test_zalo_ca_nhan_ghi_nhat_ky_truoc_khi_chan(self):
        ghi, chan = self._vi_tri("zalo_personal.py")
        self.assertLess(ghi, chan)

    def test_telegram_ghi_nhat_ky_truoc_khi_chan(self):
        ghi, chan = self._vi_tri("telegram_bot.py")
        self.assertLess(ghi, chan)


class ChuanHoaConfigTests(unittest.TestCase):
    def test_bo_khoa_rong_va_gia_tri_tat(self):
        from services.config import _normalize_thread_user_only as chuan

        self.assertEqual(chuan({NHOM: True, "  ": True, "x": False, "y": 0}),
                         {NHOM: True})
        self.assertEqual(chuan(None), {})
        self.assertEqual(chuan("bậy"), {})


if __name__ == "__main__":
    unittest.main()
