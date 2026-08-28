"""System prompt CHỈ nạp phần cần cho VIỆC của lượt này.

Bối cảnh: prompt của MỌI lượt (`orchestrator._build_system_prompt`) từng gộp
mọi khối chỉ dẫn — kể cả khối chỉ dùng cho một loại việc. Kiểm kê 28/08 còn
lộ ra bảng chỉ đường cũ chỉ phủ 10/19 nhóm tool: office (18 tool), teacher
(10), homeassistant (14), server, device, camera, facebook, kho đám mây, loa
đều KHÔNG có dòng chỉ đường nào.

Ba việc file này khoá:
1. Bảng chỉ đường phủ ĐỦ mọi nhóm tool, và mỗi nhánh chỉ nạp khi khớp CẢ hai
   cửa — quyền của thread (`allow`) và việc của tin nhắn.
2. Skill router chỉ nạp skill CHUNG + skill đúng việc (17 skill mọi lượt là
   ~730 token, gồm cả skill dạy học lẫn skill nhà).
3. Trí nhớ sắp theo mức liên quan trong CÙNG ngân sách — không mất dòng nào so
   với trước, và lời dặn cách trả lời không bao giờ bị rơi.

Cộng thêm: đóng hội thoại đã nghỉ >10 phút.
"""

import unittest

from test._fakes import install_data_dir  # noqa: E402

import services.agent.capabilities as caps  # noqa: E402
import services.agent.orchestrator as orch  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._data = install_data_dir()
        self._data.__enter__()
        self.addCleanup(lambda: self._data.__exit__(None, None, None))

    def prompt(self, allow, user_text):
        return orch._build_system_prompt("u_test", allow, user_text)


class PhuDuMoiNhomViec(unittest.TestCase):
    """Không nhóm tool nào bị bỏ quên, và không nhánh nào trỏ nhóm ma."""

    def test_moi_nhom_tool_deu_co_nhanh(self):
        thieu = set(caps._CAP_GROUP.values()) - {g for g, _, _ in orch._BANG_CHI_DUONG}
        self.assertFalse(thieu, f"nhóm tool chưa có nhánh chỉ đường: {sorted(thieu)}")

    def test_khong_co_nhanh_tro_nhom_ma(self):
        thua = {g for g, _, _ in orch._BANG_CHI_DUONG} - set(caps._CAP_GROUP.values())
        self.assertFalse(thua, f"nhánh trỏ nhóm không tồn tại: {sorted(thua)}")


class TungNhomBanDungTool(_Base):
    """Mỗi việc bắn ra ĐÚNG tool của nó — soi từng nhóm một, không bỏ sót."""

    #: (câu người dùng, tool phải có mặt, nhóm cần tích nếu có)
    CA = [
        ("vẽ cho anh con mèo", "generate_image", None),
        ("làm bài hát về mùa thu", "generate_music", None),
        ("tạo video giới thiệu", "generate_video", None),
        ("viết chương trình python", "write_code", None),
        ("tin tức hôm nay", "web_search", None),
        ("nhắc anh 7h sáng mai", "schedule(op=list)", None),
        ("tự động xoá phản hồi sau 15 phút", "tu_xoa_tin", None),
        ("tìm lại chuyện cũ hôm trước", "search_history", None),
        ("quy trình các bước làm việc này", "use_skill", None),
        ("lưu ghi chú vào wiki", "wiki_search", None),
        ("mục tiêu đang làm tới đâu", "goals", None),
        ("ai vừa nhắn trong danh bạ", "contacts", None),
        ("ảnh mới nhất trong thư viện", "library_media", None),
        ("bật đèn phòng khách", "home_status", None),
        ("phát ra loa phòng ngủ", "speak_to_speaker", None),
        ("tạo báo cáo excel cho anh", "office_bao_cao", None),
        ("ra bài tập lớp 4 toán", "search_sgk", None),
        ("máy chủ còn bao nhiêu ram", "system_status", None),
        ("chụp webcam máy tính", "device_capture", None),
        ("đăng bài lên facebook", "dang_facebook", None),
        ("tải file lên google drive", "kho_dam_may", None),
        ("xem camera ngoài cổng", "xem_camera", {"camera"}),
        # Việc lẻ trong nhóm — trước nay không dòng nào nhắc tới.
        ("đọc giúp anh trang https://vnexpress.net/abc", "read_webpage", None),
        ("video này nói gì vậy youtube", "youtube_transcript", None),
        ("nhớ là anh thích cà phê đen", "remember", None),
        ("xoá ảnh vừa tạo đi", "delete_media", None),
        ("dạy em quy trình làm báo cáo này", "teach_skill", None),
        ("tìm sách nâng cao lớp 5", "sgk_fetch", None),
        ("xem tác giả và số trang tài liệu", "office_thong_tin", None),
        ("sửa cấu hình home assistant", "ha_write_config_file", None),
        ("tạo helper input_boolean", "ha_upsert_helper", None),
    ]

    #: Ba tool này có chỉ đường ở CHỖ KHÁC, cố ý không nằm trong bảng:
    #: expand_tool_result ở đuôi bảng (hạ tầng, luôn nêu), hai cai_dat_* nằm
    #: trong khối «đổi cách trình bày» — đúng lúc người dùng dặn cách trả lời.
    NGOAI_BANG = {"expand_tool_result", "cai_dat_cau_duyet", "cai_dat_dinh_dang"}

    def test_moi_tool_deu_co_chi_duong_o_dau_do(self):
        """Không tool nào bị bỏ quên — soi TỪNG tool của TỪNG nhóm."""
        noi = {}
        for g, _rx, text in orch._BANG_CHI_DUONG:
            noi[g] = noi.get(g, "") + " " + text
        thieu = [f"{g}/{t}" for t, g in caps._CAP_GROUP.items()
                 if t not in self.NGOAI_BANG and t not in noi.get(g, "")]
        self.assertFalse(thieu, f"tool chưa có chỉ đường: {sorted(thieu)}")

    def test_ba_tool_ngoai_bang_van_co_cho(self):
        self.assertIn("expand_tool_result",
                      orch._bang_chi_duong(None, "tin tức hôm nay"))
        p = orch._build_system_prompt("u_test", None, "bỏ tóm tắt đi")
        self.assertIn("cai_dat_cau_duyet", p)
        self.assertIn("cai_dat_dinh_dang", p)

    def test_moi_viec_ra_dung_tool(self):
        for cau, tool, allow in self.CA:
            with self.subTest(cau=cau):
                b = orch._bang_chi_duong(allow, cau)
                self.assertIn(tool, b, f"«{cau}» phải chỉ đường tới {tool}")

    def test_moi_ca_deu_duoc_phu(self):
        """Bộ ca trên phải chạm ĐỦ mọi nhóm — kẻo thêm nhóm mà quên thêm ca."""
        cham = set()
        for cau, _tool, allow in self.CA:
            cham |= orch._nhom_viec(cau, allow)
        thieu = set(caps._CAP_GROUP.values()) - cham
        self.assertFalse(thieu, f"chưa có ca kiểm cho nhóm: {sorted(thieu)}")


class KhongKeoNhanhLacDe(_Base):
    """Một việc KHÔNG kéo theo nhánh của việc khác."""

    def test_hoi_tin_khong_keo_ve_anh_dat_lich(self):
        b = orch._bang_chi_duong(None, "tin tức hôm nay")
        for cam in ("generate_image", "schedule(op=list)", "office_bao_cao",
                    "search_sgk", "system_status", "dang_facebook"):
            self.assertNotIn(cam, b, f"lượt tin tức không nên có «{cam}»")

    def test_bat_den_khong_keo_tin_anh_lich(self):
        b = orch._bang_chi_duong(None, "bật đèn phòng khách")
        for cam in ("web_search", "generate_image", "schedule(op=list)",
                    "office_bao_cao", "search_sgk"):
            self.assertNotIn(cam, b, f"lượt bật đèn không nên có «{cam}»")

    def test_tan_gau_khong_co_bang(self):
        self.assertEqual(orch._bang_chi_duong(None, "chào em, khỏe không"), "")


class CuaQuyenVanChan(_Base):
    """Cửa VIỆC mở nhưng cửa QUYỀN đóng thì vẫn không nạp."""

    def test_thread_chi_co_nha_thi_khong_ra_nhanh_ve_anh(self):
        b = orch._bang_chi_duong({"homeassistant"}, "vẽ con mèo")
        self.assertNotIn("generate_image", b)

    def test_camera_phai_tich_moi_co(self):
        """`camera` thuộc _NHOM_PHAI_TICH — thread chưa cấu hình KHÔNG được."""
        self.assertNotIn("xem_camera", orch._bang_chi_duong(None, "xem camera sân"))
        self.assertIn("xem_camera", orch._bang_chi_duong({"camera"}, "xem camera sân"))


class KhoiLoiLuonCon(_Base):
    """Khối lõi không bao giờ bị gác mất, kể cả lượt tán gẫu."""

    def test_tan_gau_van_du_khoi_loi(self):
        p = self.prompt(None, "chào em")
        for y in ("## Ngôn ngữ trả lời", "## Bảo mật secret",
                  "## Độ dài câu trả lời", "## Cách dùng công cụ"):
            self.assertIn(y, p, f"mất khối lõi «{y}»")


class GacSkillTheoViec(_Base):
    """Skill router chỉ nạp skill CHUNG + skill đúng việc."""

    def test_anh_xa_nhan_nhom(self):
        from services.agent import skills as sk
        self.assertEqual(sk.nhom_nang_luc("Nhà thông minh"), "homeassistant")
        self.assertEqual(sk.nhom_nang_luc("Nhà"), "homeassistant")
        self.assertEqual(sk.nhom_nang_luc("Học tập"), "teacher")
        self.assertEqual(sk.nhom_nang_luc("Hệ thống"), "server")
        self.assertEqual(sk.nhom_nang_luc("Nội dung"), "facebook")

    def test_nhan_la_thi_coi_la_chung_luon_nap(self):
        """Nhãn người dùng tự đặt → không ánh xạ được → phải LUÔN nạp."""
        from services.agent import skills as sk
        for la in ("Chung", "Chat", "Giao tiếp", "Nhãn tự chế 123", ""):
            self.assertEqual(sk.nhom_nang_luc(la), "",
                             f"nhãn «{la}» phải coi là CHUNG")

    def test_day_hoc_khong_lot_vao_luot_khac(self):
        from services.agent import skills as sk
        b = sk.router_block({"homeassistant"})
        self.assertNotIn("giao-vien-tieu-hoc", b)
        self.assertIn("dieu-khien-nha", b)

    def test_none_thi_giu_net_cu_nap_het(self):
        from services.agent import skills as sk
        self.assertGreaterEqual(len(sk.router_block(None)),
                                len(sk.router_block({"homeassistant"})))


class TriNhoTheoViec(unittest.TestCase):
    """Sắp theo liên quan trong CÙNG ngân sách — không mất hơn trước."""

    def test_kho_nho_hon_tran_thi_nguyen_ven(self):
        nho = "\n".join(f"- fact {i}" for i in range(20))
        self.assertEqual(orch._tri_nho_theo_viec(nho, "bất kỳ"), nho.strip())

    def test_loi_dan_khong_bao_gio_roi(self):
        loidan = "- chủ nhà dặn: bỏ tóm tắt đi, chỉ ghi tiêu đề"
        rac = "\n".join(f"- chuyện vặt {i} không liên quan" for i in range(400))
        ra = orch._tri_nho_theo_viec(loidan + "\n" + rac, "bật đèn phòng khách")
        self.assertIn(loidan, ra, "lời dặn cách trả lời bị rơi khi kho tràn")

    def test_fact_cu_dung_viec_van_voi_toi(self):
        cu = "- mã wifi phòng khách là ABC123"
        rac = "\n".join(f"- chuyện vặt {i} không liên quan" for i in range(400))
        ra = orch._tri_nho_theo_viec(cu + "\n" + rac, "wifi phòng khách mã gì")
        self.assertIn(cu, ra, "fact cũ đúng việc phải giữ được")

    def test_khong_vuot_tran(self):
        rac = "\n".join(f"- chuyện vặt {i} không liên quan" for i in range(900))
        ra = orch._tri_nho_theo_viec(rac, "wifi")
        self.assertLessEqual(len(ra), orch._TRAN_TRI_NHO)

    def test_giu_thu_tu_goc(self):
        dong = [f"- fact {i} wifi" for i in range(500)]
        ra = orch._tri_nho_theo_viec("\n".join(dong), "wifi")
        so = [int(l.split()[2]) for l in ra.splitlines() if l.strip()]
        self.assertEqual(so, sorted(so), "thứ tự gốc bị đảo")


class DoiCachTrinhBay(_Base):
    def test_luot_thuong_khong_nap(self):
        for viec in ("bật đèn phòng khách", "tin tức hôm nay", "tạo ảnh con mèo"):
            self.assertNotIn("## Khi người dùng xin đổi cách trình bày",
                             self.prompt(None, viec))

    def test_luot_xin_doi_thi_nap(self):
        for viec in ("bỏ tóm tắt đi", "trình bày ngắn hơn", "chia mục ra"):
            p = self.prompt(None, viec)
            self.assertIn("## Khi người dùng xin đổi cách trình bày", p)
            self.assertIn("TUYỆT ĐỐI KHÔNG trả về bản mẫu", p)


class PhienDaNghi(_Base):
    """Idle-close: phiên nghỉ >10 phút thì lượt mới bỏ lịch sử cũ."""

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
