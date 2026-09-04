"""Trích dẫn lại bản tin đã đánh mã rồi gõ mã → bot vẫn chọn đúng mục.

Lỗi thật (chủ máy, Zalo cá nhân 03/09 21:45): bản tin có mã A1…E5, người dùng
chọn D1 xong thì `resolve_reply` dọn bản chờ; những mã còn lại (và cả D1 lần
sau) hết chọn được, bot đổ cho "quá 30 phút" trong khi chưa hết hạn. Cách chữa:
kênh cá nhân gửi lại NGUYÊN nội dung tin trích, mà mã đã in sẵn trong chữ
(`D1. …`), nên bóc thẳng mã từ tin trích — không phụ thuộc bản chờ còn sống.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import muc_luc as ml  # noqa: E402

# Bản tin thật (rút gọn) SAU KHI đã đánh mã và gửi qua Zalo — markdown đã bị lột
# (`zalo_markdown` bỏ `**`), nên đầu mục còn plain, mỗi tin có `A1. …`.
TIN_DA_GUI = """A. Thể thao
A1. Tiền đạo Thái Lan nỗ lực lấy cúp khỏi Việt Nam
A2. Barcelona thắng 5-0 trận mở màn La Liga

D. Công nghệ
D1. Công ty bán dẫn Trung Quốc công bố 6 thiết bị chip một ngày
D12. Một tin khác dài hơn không được nhầm với D1

(Muốn xem kỹ mục nào thì nhắn mã mục đó cho em — ví dụ A1.)"""


class BocMaTuVanTests(unittest.TestCase):
    def test_boc_dung_ma(self):
        nd = ml._boc_ma_tu_van(TIN_DA_GUI, "D1")
        self.assertIn("Công ty bán dẫn Trung Quốc", nd)

    def test_ma_ngan_khong_dinh_ma_dai(self):
        """'D1' không được nuốt dòng 'D12. …'."""
        nd = ml._boc_ma_tu_van(TIN_DA_GUI, "D1")
        self.assertNotIn("dài hơn", nd)

    def test_khong_phan_biet_hoa_thuong(self):
        self.assertTrue(ml._boc_ma_tu_van(TIN_DA_GUI, "d1"))

    def test_van_giu_dam_markdown_van_boc_duoc(self):
        """Nếu tin trích còn dấu `**` (một số client giữ) thì vẫn bóc được."""
        van = "**D1. Công ty bán dẫn công bố 6 thiết bị chip**\n- x\n- y"
        self.assertIn("Công ty bán dẫn", ml._boc_ma_tu_van(van, "D1"))

    def test_ma_khong_co_tra_rong(self):
        self.assertEqual(ml._boc_ma_tu_van(TIN_DA_GUI, "Z9"), "")

    def test_van_rong(self):
        self.assertEqual(ml._boc_ma_tu_van("", "D1"), "")


class ResolveTuTrichTests(unittest.TestCase):
    UID = "test-tu-trich-user"

    def setUp(self):
        ml.clear_pending(self.UID)

    def tearDown(self):
        ml.clear_pending(self.UID)

    def test_ban_cho_het_van_chon_duoc_tu_tin_trich(self):
        """Không còn bản chờ (đã bị dọn / hết 30') mà tin trích có mã → chọn được."""
        out = ml.resolve_tu_trich(self.UID, "D1", TIN_DA_GUI)
        self.assertIsNotNone(out)
        self.assertEqual(out["ma"], "D1")
        self.assertIn("Công ty bán dẫn", out["noi_dung"])
        # Không có bản chờ → nhánh CHUNG (nguon rỗng, kèm câu dặn cho model).
        self.assertEqual(out["nguon"], "")
        self.assertIn("Nói kỹ hơn", out["cau_hoi"])

    def test_ban_cho_con_song_thi_uu_tien_ban_cho(self):
        """Bản chờ còn (trong 30') giữ đúng `nguon='tin'` → tra thẳng tiêu đề."""
        ml.set_pending(self.UID,
                       [{"ma": "D1", "noi_dung": "Tiêu đề chuẩn từ bản chờ"}],
                       nguon="tin")
        out = ml.resolve_tu_trich(self.UID, "D1", TIN_DA_GUI)
        self.assertIsNotNone(out)
        self.assertEqual(out["nguon"], "tin")
        self.assertEqual(out["noi_dung"], "Tiêu đề chuẩn từ bản chờ")

    def test_cau_co_chu_khong_phai_ma_bo_qua(self):
        self.assertIsNone(
            ml.resolve_tu_trich(self.UID, "D1 là tin gì vậy", TIN_DA_GUI))

    def test_ma_khong_co_trong_tin_trich_tra_none(self):
        self.assertIsNone(ml.resolve_tu_trich(self.UID, "Z9", TIN_DA_GUI))

    def test_khong_co_tin_trich_tra_none(self):
        self.assertIsNone(ml.resolve_tu_trich(self.UID, "D1", ""))


class TrangThaiChonTests(unittest.TestCase):
    """CODE nói lý do THẬT vì sao một mã trần không chọn được."""
    UID = "test-trang-thai-user"

    def setUp(self):
        ml.clear_pending(self.UID)

    def tearDown(self):
        ml.clear_pending(self.UID)

    def test_khong_co_ban_cho_thi_trong(self):
        self.assertEqual(ml.trang_thai_chon(self.UID, "D1"), "trong")

    def test_ban_cho_co_ma_thi_khop(self):
        ml.set_pending(self.UID, [{"ma": "D1", "noi_dung": "x"}], nguon="tin")
        self.assertEqual(ml.trang_thai_chon(self.UID, "D1"), "khop")

    def test_ban_cho_thieu_ma_thi_khong_co(self):
        ml.set_pending(self.UID, [{"ma": "D1", "noi_dung": "x"}], nguon="tin")
        self.assertEqual(ml.trang_thai_chon(self.UID, "Z9"), "khong_co")

    def test_ban_cho_qua_han_thi_het_han(self):
        ml.set_pending(self.UID, [{"ma": "D1", "noi_dung": "x"}], nguon="tin")
        # Dời mốc thời gian ra ngoài TTL để giả lập bản tin cũ hơn 30'.
        old = time.time() - ml._TTL - 60
        with ml._lock:
            ml._pending[self.UID]["ts"] = old
        c = ml._db()
        if c is not None:
            c.execute("UPDATE muc_pending SET ts=? WHERE user_id=?",
                      (old, self.UID))
            c.commit()
        self.assertEqual(ml.trang_thai_chon(self.UID, "D1"), "het_han")


class RutTrichDanUuTienKhoTests(unittest.TestCase):
    """`full_msg` (nguyên văn tra từ kho zalo-server) phải thắng `msg` (đoạn Zalo gọt).

    Zalo chỉ kèm một đoạn xem trước ở `quote.msg` với tin dài, nên mã mục cuối
    bản tin bị cắt mất. zalo-server tra tin gốc theo `globalMsgId` rồi gắn thêm
    `full_msg`; nếu Python vẫn đọc `msg` thì cả đường tra ngược thành vô nghĩa.
    """

    def setUp(self):
        from services import zalo_personal
        self.rut = zalo_personal._rut_trich_dan

    def test_co_full_msg_thi_dung_full_msg(self):
        q = {"msg": "A1. Tin mot…", "full_msg": TIN_DA_GUI,
             "ownerId": "bot-1", "ts": 1756900000000}
        ra = self.rut(q, "bot-1")
        self.assertIn("D1. Công ty bán dẫn", ra["noi_dung"])
        self.assertEqual(ra["cua_ai"], "bot", "ownerId trùng own_id → tin của bot")

    def test_khong_co_full_msg_thi_dung_msg_nhu_cu(self):
        q = {"msg": "A1. Tin mot", "ownerId": "ai-do", "ts": 1756900000000}
        self.assertEqual(self.rut(q, "bot-1")["noi_dung"], "A1. Tin mot")

    def test_full_msg_rong_thi_roi_ve_msg(self):
        q = {"msg": "A1. Tin mot", "full_msg": "   ", "ownerId": "ai-do"}
        self.assertEqual(self.rut(q, "bot-1")["noi_dung"], "A1. Tin mot")

    def test_ma_cuoi_bi_got_van_chon_duoc_nho_full_msg(self):
        """Ca thật: Zalo cắt mất D1, nhưng kho có nguyên văn → chọn D1 vẫn ra."""
        q = {"msg": "A. Thể thao\nA1. Tiền đạo Thái Lan…", "full_msg": TIN_DA_GUI,
             "ownerId": "bot-1"}
        noi_dung = self.rut(q, "bot-1")["noi_dung"]
        self.assertEqual(ml._boc_ma_tu_van(noi_dung, "D1")[:20],
                         "Công ty bán dẫn Trun"[:20])


if __name__ == "__main__":
    unittest.main()
