"""System prompt CHỈ nạp phần cần cho VIỆC của lượt này.

Bối cảnh: prompt của MỌI lượt (`orchestrator._build_system_prompt`) từng gộp
~3.240 token khối chỉ dẫn CỐ ĐỊNH — kể cả khối chỉ dùng cho một loại việc. Gộp
hết vào mọi lượt làm prompt phình to và chèn chỉ dẫn lạc đề, khiến model lan man.

Giờ mỗi khối nạp theo HAI cửa:
- Cửa nhóm (`allow`): thread không bật nhóm nào thì bỏ nhánh của nhóm đó.
- Cửa việc (từ khoá tin nhắn): lượt hỏi «tin tức» KHÔNG kéo theo nhánh vẽ ảnh,
  đặt lịch… Tán gẫu → không nạp Bảng chỉ đường / phát loa / mã mục.

Khối lõi (persona, ngôn ngữ, bảo mật, độ dài, cách dùng công cụ) LUÔN giữ.
"""

import unittest

from test._fakes import install_data_dir  # noqa: E402

import services.agent.orchestrator as orch  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._data = install_data_dir()
        self._data.__enter__()
        self.addCleanup(lambda: self._data.__exit__(None, None, None))

    def prompt(self, allow, user_text):
        return orch._build_system_prompt("u_test", allow, user_text)


class HoiTinTuc(_Base):
    """Lượt hỏi tin tức → nạp nhánh web + khối mã mục, KHÔNG kéo nhánh khác."""

    def setUp(self) -> None:
        super().setUp()
        self.p = self.prompt(None, "tin tức hôm nay")

    def test_co_nhanh_tin_va_8_muc(self):
        self.assertIn("## Bảng chỉ đường", self.p)
        self.assertIn("web_search", self.p)
        for ten in ("⚽ Thể thao", "🌍 Thế giới", "🩺 Y tế"):
            self.assertIn(ten, self.p)

    def test_co_khoi_ma_muc(self):
        self.assertIn("## Danh sách có MÃ MỤC", self.p)

    def test_khong_keo_nhanh_ve_anh_dat_lich_phat_loa(self):
        for cam in ("generate_image", "generate_music", "schedule(op=list)",
                    "tu_xoa_tin", "QUY TRÌNH PHÁT LOA"):
            self.assertNotIn(cam, self.p, f"lượt tin tức không nên có «{cam}»")


class VeAnh(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.p = self.prompt(None, "vẽ cho anh con mèo dễ thương")

    def test_co_nhanh_ve_anh(self):
        self.assertIn("generate_image", self.p)

    def test_khong_co_nhanh_tin_lich(self):
        for cam in ("web_search", "schedule(op=list)", "## Danh sách có MÃ MỤC"):
            self.assertNotIn(cam, self.p)


class DatLich(_Base):
    """Lượt đặt lịch → nhánh schedule + khối phát loa/báo cáo bật."""

    def setUp(self) -> None:
        super().setUp()
        self.p = self.prompt(None, "nhắc anh 7h sáng mai uống thuốc")

    def test_co_nhanh_schedule(self):
        self.assertIn("schedule(op=list)", self.p)
        self.assertIn("op=cancel", self.p)

    def test_co_khoi_phat_loa_bao_cao(self):
        self.assertIn("QUY TRÌNH PHÁT LOA", self.p)

    def test_khong_co_nhanh_anh_tin(self):
        self.assertNotIn("generate_image", self.p)
        self.assertNotIn("web_search", self.p)


class TanGau(_Base):
    """Chào hỏi / tán gẫu → KHÔNG nạp Bảng chỉ đường / phát loa / mã mục."""

    def setUp(self) -> None:
        super().setUp()
        self.p = self.prompt(None, "chào em, hôm nay khỏe không")

    def test_khong_co_bang_chi_duong(self):
        self.assertNotIn("## Bảng chỉ đường", self.p)

    def test_khong_co_phat_loa_ma_muc(self):
        self.assertNotIn("QUY TRÌNH PHÁT LOA", self.p)
        self.assertNotIn("## Danh sách có MÃ MỤC", self.p)

    def test_van_giu_khoi_loi(self):
        for y in ("## Ngôn ngữ trả lời", "## Bảo mật secret",
                  "## Độ dài câu trả lời", "## Cách dùng công cụ"):
            self.assertIn(y, self.p, f"mất khối lõi «{y}»")


class CuaNhomVanChan(_Base):
    """Cửa việc mở nhưng cửa NHÓM đóng thì vẫn không nạp nhánh."""

    def test_ve_anh_nhung_thread_khong_co_image(self):
        # Thread chỉ bật nhà thông minh: câu «vẽ ảnh» khớp việc, nhưng nhóm image
        # tắt → không có nhánh vẽ (tool cũng không có trong schema).
        p = self.prompt({"homeassistant"}, "vẽ con mèo")
        self.assertNotIn("generate_image", p)
        self.assertNotIn("## Bảng chỉ đường", p)


class DoiCachTrinhBay(_Base):
    def test_luot_thuong_khong_nap(self):
        for viec in ("bật đèn phòng khách", "tin tức hôm nay", "tạo ảnh con mèo"):
            p = self.prompt(None, viec)
            self.assertNotIn("## Khi người dùng xin đổi cách trình bày", p)

    def test_luot_xin_doi_thi_nap(self):
        for viec in ("bỏ tóm tắt đi", "trình bày ngắn hơn", "chia mục ra"):
            p = self.prompt(None, viec)
            self.assertIn("## Khi người dùng xin đổi cách trình bày", p)
            self.assertIn("TUYỆT ĐỐI KHÔNG trả về bản mẫu", p)


class NhanDienViec(unittest.TestCase):
    """Đơn vị: bộ dò từ khoá theo nhánh (đã bỏ dấu)."""

    def test_image(self):
        for t in ("vẽ con mèo", "tao anh phong canh", "minh hoạ giúp anh"):
            self.assertTrue(orch._KW_IMAGE.search(orch._bo_dau(t)), t)

    def test_web(self):
        for t in ("tin tức hôm nay", "giá vàng", "thời tiết Hà Nội", "tra cứu giúp"):
            self.assertTrue(orch._KW_WEB.search(orch._bo_dau(t)), t)

    def test_lich(self):
        for t in ("nhắc anh 7h", "đặt lịch báo cáo", "mỗi sáng nhắc em", "xem lịch nhắc"):
            self.assertTrue(orch._KW_LICH.search(orch._bo_dau(t)), t)

    def test_khong_dinh_tuyen_khi_tan_gau(self):
        for t in ("chào em", "cảm ơn nhé", "hôm nay khỏe không", "ừ được"):
            low = orch._bo_dau(t)
            self.assertFalse(
                any(rx.search(low) for rx in (orch._KW_IMAGE, orch._KW_WEB,
                                              orch._KW_LICH, orch._KW_MUSIC,
                                              orch._KW_VIDEO, orch._KW_CODE)),
                f"tán gẫu «{t}» không nên khớp nhánh nào")


class PhienDaNghi(_Base):
    """Idle-close: phiên nghỉ quá mốc thì lượt mới bỏ lịch sử cũ."""

    def test_moc_10_phut(self):
        self.assertEqual(orch._NGHI_DONG_PHIEN, 600.0)

    def test_vua_hoat_dong_thi_khong_dong(self):
        import services.agent.session as sess
        if not sess.is_enabled():
            self.skipTest("session store tắt")
        sess.save_history("u_moi", [{"role": "user", "content": "xin chào"}])
        self.assertFalse(orch._phien_da_nghi("u_moi"))

    def test_nghi_lau_thi_dong(self):
        import time
        import services.agent.session as sess
        if not sess.is_enabled():
            self.skipTest("session store tắt")
        sess.save_history("u_cu", [{"role": "user", "content": "đột quỵ"}])
        with sess._lock:
            sess._db().execute(
                "UPDATE sessions SET updated_at=? WHERE user_id=?",
                (time.time() - 3600, "u_cu"))
            sess._db().commit()
        self.assertTrue(orch._phien_da_nghi("u_cu"))


if __name__ == "__main__":
    unittest.main()
