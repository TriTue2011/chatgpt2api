"""Phạm vi dữ liệu: wiki, digest, lịch — mặc định độc lập, nhóm chưa lọc thì chung.

Quy tắc chủ máy chốt 03/08 (services/agent/scope.py):
  * mặc định ĐỘC LẬP TUYỆT ĐỐI theo kênh / chat / topic / người;
  * nhóm (hay topic) KHÔNG có bộ lọc user nào thì thành viên DÙNG CHUNG;
  * topic luôn thắng nhóm.

Hai chỗ rò đã dựng lại được trên mã cũ:
  1. `wiki.search/read/list_recent` đọc toàn bộ thư mục notes — ghi chú người này
     lọt sang lượt người khác;
  2. `super_context.build_bundle` gộp wiki + MỌI lịch đang bật vào system prompt
     của MỌI lượt, nên rò cả khi không ai gọi tool nào.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import scope  # noqa: E402

GOC = pathlib.Path(__file__).resolve().parents[1]


class TachKhoaPhien(unittest.TestCase):
    """Đọc đúng 4 hình dạng khoá phiên các adapter đang sinh."""

    def test_telegram_1_1(self):
        sc = scope.tach_khoa_phien("555")
        self.assertEqual((sc.kenh, sc.chat, sc.topic, sc.actor), ("tg", "555", "", ""))
        self.assertFalse(sc.la_nhom)

    def test_telegram_nhom_topic_nguoi(self):
        sc = scope.tach_khoa_phien("-100#7:u9")
        self.assertEqual((sc.kenh, sc.chat, sc.topic, sc.actor), ("tg", "-100", "7", "9"))
        self.assertTrue(sc.la_nhom)

    def test_zalo_bot(self):
        sc = scope.tach_khoa_phien("zalo_123:u456")
        self.assertEqual((sc.kenh, sc.chat, sc.actor), ("zalo", "123", "456"))

    def test_zalo_ca_nhan(self):
        sc = scope.tach_khoa_phien("zalop_987")
        self.assertEqual((sc.kenh, sc.chat, sc.actor), ("zalop", "987", ""))

    def test_email_khoa_la_chinh_chu_the(self):
        sc = scope.tach_khoa_phien("email_bo_abc123def456")
        self.assertEqual(sc.kenh, "mail")
        self.assertEqual(sc.actor, sc.chat)

    def test_khoa_rong(self):
        self.assertEqual(scope.tach_khoa_phien("").kenh, "")


class KhoaDuLieu(unittest.TestCase):
    def setUp(self):
        self.cfg = {}
        p = mock.patch("services.config.config.get", side_effect=lambda: self.cfg)
        p.start()
        self.addCleanup(p.stop)

    # ------------------------------------------------- độc lập theo mặc định
    def test_hai_kenh_khac_nhau_khac_pham_vi(self):
        self.assertNotEqual(scope.khoa_du_lieu("123"), scope.khoa_du_lieu("zalo_123"))

    def test_hai_chat_1_1_khac_pham_vi(self):
        self.assertNotEqual(scope.khoa_du_lieu("555"), scope.khoa_du_lieu("556"))

    def test_topic_thang_nhom(self):
        self.assertNotEqual(scope.khoa_du_lieu("-100#7"), scope.khoa_du_lieu("-100"))
        self.assertNotEqual(scope.khoa_du_lieu("-100#7"), scope.khoa_du_lieu("-100#8"))

    def test_thanh_phan_khong_tron_duoc_sang_nhau(self):
        """Chat 'a|b' không được trộn thành phạm vi của chat 'a' topic 'b'."""
        self.assertNotEqual(scope.khoa_du_lieu("a|b"), scope.khoa_du_lieu("a#b"))

    # -------------------------------------------- ngoại lệ: nhóm chưa lọc user
    def test_nhom_chua_loc_user_thi_dung_CHUNG(self):
        a = scope.khoa_du_lieu("-100:u9")
        b = scope.khoa_du_lieu("-100:u10")
        self.assertEqual(a, b)

    def test_nhom_co_loc_user_thi_TACH(self):
        self.cfg = {"thread_user_filters": {"tg:-100:9": ["device"]}}
        a = scope.khoa_du_lieu("-100:u9")
        b = scope.khoa_du_lieu("-100:u10")
        self.assertNotEqual(a, b)

    def test_loc_user_cua_nhom_KHAC_khong_lam_tach(self):
        self.cfg = {"thread_user_filters": {"tg:-200:9": ["device"]}}
        self.assertEqual(scope.khoa_du_lieu("-100:u9"), scope.khoa_du_lieu("-100:u10"))

    def test_loc_theo_topic_chi_tach_dung_topic_do(self):
        self.cfg = {"thread_user_filters": {"tg:-100#7:9": ["device"]}}
        self.assertNotEqual(scope.khoa_du_lieu("-100#7:u9"),
                            scope.khoa_du_lieu("-100#7:u10"))
        self.assertEqual(scope.khoa_du_lieu("-100#8:u9"),
                         scope.khoa_du_lieu("-100#8:u10"))

    def test_khoa_co_bot_id_van_nhan_ra(self):
        self.cfg = {"thread_user_filters": {"tg:botA:-100:9": ["device"]}}
        self.assertNotEqual(scope.khoa_du_lieu("-100:u9"),
                            scope.khoa_du_lieu("-100:u10"))

    def test_chat_1_1_luon_tach_du_khong_co_loc(self):
        self.assertNotEqual(scope.khoa_du_lieu("zalo_1:u1"),
                            scope.khoa_du_lieu("zalo_2:u2"))

    # ------------------------------------------------------------------ băm
    def test_bam_khac_nhau_cho_pham_vi_khac_nhau(self):
        self.assertNotEqual(scope.ma_pham_vi("555"), scope.ma_pham_vi("556"))

    def test_bam_khong_gop_dau_phan_cach(self):
        """Bản nháp trước bỏ dấu phân cách nên hai email khác nhau ra 1 file."""
        self.assertNotEqual(scope.ma_pham_vi("email_ab_h1"),
                            scope.ma_pham_vi("email_a.b_h1"))

    def test_bam_dung_lam_ten_file(self):
        ma = scope.ma_pham_vi("-100#7:u9")
        self.assertRegex(ma, r"^[0-9a-f]{16}$")


class WikiTheoPhamVi(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="wiki-scope-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from services.agent import wiki as w
        self.w = w
        w._reset_for_tests(self.tmp)
        self.cfg = {}
        p = mock.patch("services.config.config.get", side_effect=lambda: self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def _them(self, noi_dung: str, pham_vi: str) -> str:
        out = self.w.ingest(noi_dung, title=noi_dung[:20], pham_vi=pham_vi)
        self.assertTrue(out.get("ok"), out)
        return out["slug"]

    def test_ghi_chu_khong_lot_sang_pham_vi_khac(self):
        pv_a = scope.khoa_du_lieu("555")
        pv_b = scope.khoa_du_lieu("556")
        self._them("mật khẩu két nhà là 4321 nhé bạn", pv_a)
        self.assertTrue(self.w.search("két", pham_vi=pv_a))
        self.assertEqual(self.w.search("két", pham_vi=pv_b), [])

    def test_read_theo_slug_cung_bi_chot(self):
        """Slug đoán được / thấy lại từ lượt trước → chốt phải nằm cả ở read."""
        pv_a = scope.khoa_du_lieu("555")
        pv_b = scope.khoa_du_lieu("556")
        slug = self._them("số tài khoản ngân hàng của bố là 123", pv_a)
        self.assertIsNotNone(self.w.read(slug, pham_vi=pv_a))
        self.assertIsNone(self.w.read(slug, pham_vi=pv_b))

    def test_list_recent_theo_pham_vi(self):
        pv_a = scope.khoa_du_lieu("555")
        pv_b = scope.khoa_du_lieu("556")
        self._them("ghi chú riêng của người thứ nhất", pv_a)
        self._them("ghi chú riêng của người thứ hai", pv_b)
        self.assertEqual(len(self.w.list_recent(10, pham_vi=pv_a)), 1)
        self.assertEqual(len(self.w.list_recent(10, pham_vi=pv_b)), 1)
        self.assertEqual(len(self.w.list_recent(10)), 2)  # nội bộ: thấy tất cả

    def test_list_recent_du_so_luong_khi_co_ghi_chu_ngoai_pham_vi(self):
        """Lọc rồi mới cắt: cắt trước thì phạm vi đông ghi chú làm rỗng kết quả."""
        pv_a = scope.khoa_du_lieu("555")
        pv_b = scope.khoa_du_lieu("556")
        for i in range(5):
            self._them(f"ghi chú của người khác số {i}", pv_b)
        self._them("ghi chú của chính tôi cần thấy", pv_a)
        self.assertEqual(len(self.w.list_recent(3, pham_vi=pv_a)), 1)

    def test_ghi_chu_cu_khong_co_scope_van_doc_duoc(self):
        """Dữ liệu tạo trước khi có phạm vi: không ẩn (migration là bước riêng)."""
        slug = self._them("ghi chú cũ từ thời chưa có phạm vi", "")
        self.assertIsNotNone(self.w.read(slug, pham_vi=scope.khoa_du_lieu("555")))

    def test_nhom_chua_loc_user_thi_thanh_vien_doc_chung(self):
        pv9 = scope.khoa_du_lieu("-100:u9")
        self._them("lịch trực nhật của nhóm tuần này", pv9)
        pv10 = scope.khoa_du_lieu("-100:u10")
        self.assertTrue(self.w.search("trực nhật", pham_vi=pv10))

    def test_nhom_co_loc_user_thi_khong_doc_chung(self):
        self.cfg = {"thread_user_filters": {"tg:-100:9": ["device"]}}
        pv9 = scope.khoa_du_lieu("-100:u9")
        self._them("ghi chú riêng trong nhóm có lọc", pv9)
        pv10 = scope.khoa_du_lieu("-100:u10")
        self.assertEqual(self.w.search("lọc", pham_vi=pv10), [])

    def test_digest_moi_pham_vi_mot_file(self):
        pv_a = scope.khoa_du_lieu("555")
        pv_b = scope.khoa_du_lieu("556")
        self.assertNotEqual(self.w.digest_path("2026-08-04", pv_a),
                            self.w.digest_path("2026-08-04", pv_b))

    def test_digest_gom_dung_ghi_chu_cua_pham_vi(self):
        self.cfg = {"agent_wiki": {"digest_llm": False}}
        pv_a = scope.khoa_du_lieu("555")
        pv_b = scope.khoa_du_lieu("556")
        self._them("mua hạt dẻ cho con mang đi học", pv_a)
        self._them("đóng tiền điện tháng này trước ngày mười", pv_b)
        out = self.w.build_daily_digest(force=True, pham_vi=pv_a)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["note_count"], 1)
        self.assertIn("hạt dẻ", out["text"])
        self.assertNotIn("tiền điện", out["text"])


class LichTheoKenhNhan(unittest.TestCase):
    """Lịch chỉ vào prompt của thread mà chủ máy đã khai trong `notify_targets`."""

    def _sc(self, khoa: str):
        return scope.tach_khoa_phien(khoa)

    def test_khop_khoa_co_va_khong_co_bot(self):
        from services import calendar_connector as cc
        self.assertTrue(cc.khop_muc_tieu("tg:-100", self._sc("-100:u9")))
        self.assertTrue(cc.khop_muc_tieu("tg:botA:-100", self._sc("-100:u9")))

    def test_khong_khop_chat_khac(self):
        from services import calendar_connector as cc
        self.assertFalse(cc.khop_muc_tieu("tg:-200", self._sc("-100")))

    def test_khong_khop_kenh_khac(self):
        from services import calendar_connector as cc
        self.assertFalse(cc.khop_muc_tieu("zalo:-100", self._sc("-100")))

    def test_muc_tieu_tro_topic_thi_chi_topic_do(self):
        from services import calendar_connector as cc
        self.assertTrue(cc.khop_muc_tieu("tg:-100#7", self._sc("-100#7")))
        self.assertFalse(cc.khop_muc_tieu("tg:-100#7", self._sc("-100#8")))

    def test_muc_tieu_tro_ca_nhom_thi_moi_topic_nhan(self):
        from services import calendar_connector as cc
        self.assertTrue(cc.khop_muc_tieu("tg:-100", self._sc("-100#7")))

    def test_lich_co_kenh_nhan_khong_ro_ri_sang_thread_khac(self):
        from services import calendar_connector as cc
        cal = {"notify_targets": ["tg:-100"]}
        self.assertTrue(cc._lich_cho_luot(cal, self._sc("-100")))
        self.assertFalse(cc._lich_cho_luot(cal, self._sc("-200")))

    def test_lich_chua_khai_kenh_nhan_thi_khong_gioi_han(self):
        from services import calendar_connector as cc
        self.assertTrue(cc._lich_cho_luot({"notify_targets": []}, self._sc("-999")))

    def test_duong_noi_bo_khong_bi_chan(self):
        from services import calendar_connector as cc
        self.assertTrue(cc._lich_cho_luot({"notify_targets": ["tg:-100"]}, None))


class SuperContextTruyenPhamVi(unittest.TestCase):
    """Bó ngữ cảnh vào system prompt MỌI lượt — chỗ rò rộng nhất, phải có phạm vi."""

    def test_ma_nguon_truyen_pham_vi_cho_wiki_va_lich(self):
        src = (GOC / "services" / "agent" / "super_context.py").read_text("utf-8")
        self.assertIn("pham_vi=_pv", src)
        self.assertIn("cal.prompt_block(user_id)", src)


if __name__ == "__main__":
    unittest.main()
