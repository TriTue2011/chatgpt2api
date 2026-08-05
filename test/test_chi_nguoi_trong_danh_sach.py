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

File này khoá năm hành vi:
  * tắt công tắc (mặc định) → mọi người vẫn nói được, y như trước;
  * bật → người CÓ bản ghi qua được, người KHÔNG có bị chặn;
  * bản ghi ở cấp topic thắng bản ghi cả nhóm;
  * chốt chặn nằm SAU khối nhật ký ở cả zalo_personal lẫn telegram_bot;
  * người dùng nêu đích danh kênh thì câu của họ thắng giá trị model đoán
    (lỗi gửi nhầm kênh 05/08 13:12);
  * gửi FILE có sẵn sang người/nhóm khác — chặn đường dẫn ra ngoài workspace,
    Zalo Bot báo thẳng là không gửi được, và bản Word/Excel giữ TÊN GỐC.
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



class KenhNguoiDungNeuThangTests(unittest.TestCase):
    """Người dùng nêu đích danh kênh thì câu của họ THẮNG giá trị model đoán.

    Đo thật 05/08 13:12 — chủ máy gõ "bằng zalo cá nhân" (mã `zalop`) mà tool
    nhận platform='zalo' (Zalo Bot) nên tra nhầm danh bạ, trả về
    "«8845089824387263227» không thấy trong danh bạ kênh zalo". Bản cũ chỉ hỏi
    "người dùng CÓ nêu kênh không" (để bỏ platform khi họ không nêu), không hề
    đối chiếu model ánh xạ có ĐÚNG kênh họ nêu hay không.
    """

    def test_nhan_dung_kenh_tu_cau_noi(self):
        from services.agent.capabilities import _kenh_nguoi_dung_neu as f

        for cau, mong in (
                ("gửi vào nhóm homeassistant bằng zalo cá nhân", "zalop"),
                ("gui bang zalo ca nhan", "zalop"),
                ("gửi cho mẹ bằng zalo bot", "zalo"),
                ("gửi qua oa", "zalo"),
                ("nhắn qua telegram cho anh A", "tg"),
                # Mập mờ → trả "" để giữ nguyên giá trị model, không đoán bừa.
                ("gửi bằng zalo", ""),
                ("gửi cho mẹ", ""),
                ("", "")):
            self.assertEqual(f(cau.lower()), mong, cau)

    def test_zalo_ca_nhan_khong_bi_doc_thanh_zalo_bot(self):
        """"zalo cá nhân" chứa cả 'zalo' — thứ tự xét phải cho 'cá nhân' thắng."""
        from services.agent.capabilities import _kenh_nguoi_dung_neu as f

        self.assertEqual(f("bằng zalo cá nhân"), "zalop")



class GuiTepTrongWorkspaceTests(unittest.TestCase):
    """Gửi file đã có sang người/nhóm khác + giữ tên file khi chuyển PDF.

    Đo thật 05/08 13:22–13:24: chủ máy bảo "gửi file word vào nhóm homeassistant"
    mà bot cứ đòi tải file lên — tool gửi tin chỉ nhận ảnh và thoại, không có
    đường nào cho tài liệu. Kèm theo: bản Word tới tay mang tên uuid thuần
    ("1785910932720-d5cc…docx"), mở ra mới biết là tài liệu gì.
    """

    def test_chan_duong_dan_thoat_ra_ngoai_workspace(self):
        """Tên file do MODEL điền — không chốt thì '../..' đọc được file hệ thống."""
        import tempfile
        from services.agent.capabilities import tep_trong_workspace

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("services.officecli.status",
                            return_value={"ok": True, "workspace": tmp}):
                duong, loi = tep_trong_workspace("../../etc/passwd")
        self.assertEqual(duong, "")
        self.assertIn("ngoài workspace", loi)

    def test_lay_file_moi_nhat_cho_cau_noi_tu_nhien(self):
        import tempfile
        import time
        from pathlib import Path
        from services.agent.capabilities import tep_trong_workspace

        with tempfile.TemporaryDirectory() as tmp:
            cu = Path(tmp) / "cu.docx"
            cu.write_text("x")
            time.sleep(0.01)
            moi = Path(tmp) / "moi.docx"
            moi.write_text("y")
            with mock.patch("services.officecli.status",
                            return_value={"ok": True, "workspace": tmp}):
                duong, loi = tep_trong_workspace("moi_nhat")
                self.assertEqual(loi, "")
                self.assertEqual(Path(duong).name, "moi.docx")
                # Tên cụ thể vẫn tra đúng file đó.
                duong2, loi2 = tep_trong_workspace("cu.docx")
                self.assertEqual(loi2, "")
                self.assertEqual(Path(duong2).name, "cu.docx")

    def test_khong_thay_file_thi_bao_ro(self):
        import tempfile
        from services.agent.capabilities import tep_trong_workspace

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("services.officecli.status",
                            return_value={"ok": True, "workspace": tmp}):
                duong, loi = tep_trong_workspace("khong-co.docx")
        self.assertEqual(duong, "")
        self.assertIn("không thấy file", loi)

    def test_zalo_bot_bao_thang_la_khong_gui_duoc_file(self):
        """API Zalo Bot không có sendDocument — báo rõ, đừng im lặng."""
        from services.agent.capabilities import _send_one_contact

        ok, mo_ta = _send_one_contact(
            {"platform": "zalo", "bot_id": "1", "chat_id": "9", "alias": "Nhóm X"},
            "chú thích", file_path="/tmp/bao-cao.docx")
        self.assertFalse(ok)
        self.assertIn("không gửi được file", mo_ta)
        self.assertIn("bao-cao.docx", mo_ta)

    def test_ten_file_word_giu_theo_ten_pdf_goc(self):
        from services.zalo_personal import _ten_tep_phuc_vu as f

        self.assertEqual(f("HTT - Phướng án CHCN cơ sở.pdf", ".docx"),
                         "HTT_-_Phuong_an_CHCN_co_so.docx")
        self.assertEqual(f("báo cáo quý 1.PDF", ".xlsx"), "bao_cao_quy_1.xlsx")
        # Không có tên thì vẫn phải ra một tên đọc được, không rỗng.
        self.assertEqual(f("   ", ".docx"), "tai-lieu.docx")
        # Tên dài bị cắt, nhưng đuôi phải còn nguyên.
        self.assertTrue(f("x" * 90 + ".pdf", ".docx").endswith(".docx"))


class NhanWordExcelNhuPdfTests(unittest.TestCase):
    """Word/Excel gửi vào bot đi CHUNG đường với PDF — cùng menu ý định.

    Đo thật 05/08 13:23: bot trả "📎 Hiện em chỉ hỗ trợ chuyển PDF → Word" cho
    mọi file không phải PDF, nên .docx/.xlsx chưa từng có menu nào. Yêu cầu của
    chủ máy: "nạp rag kiến thức, nạp rag teacher như pdf cho word và excel".
    """

    def test_nhan_dien_file_office(self):
        from services import pdf_intent as pi

        for t in ("a.docx", "B.XLSX", "x.pptx", "y.doc"):
            self.assertTrue(pi.la_office(t), t)
        for t in ("a.pdf", "anh.png", "", "docx"):
            self.assertFalse(pi.la_office(t), t)

    def test_menu_office_chi_co_hai_muc_rag(self):
        """Gửi .docx vào rồi "chuyển Word" thì vô nghĩa — bỏ hai mục chuyển đổi."""
        from services import pdf_intent as pi

        self.assertEqual(pi.y_dinh_cho_office(None),
                         {pi.RAG_KNOWLEDGE, pi.RAG_TEACHER})
        # Bộ lọc thread vẫn siết được như cũ.
        self.assertEqual(pi.y_dinh_cho_office({"rag"}), {pi.RAG_KNOWLEDGE})
        self.assertEqual(pi.y_dinh_cho_office({"word"}), set())

    def test_menu_goi_dung_ten_loai_file(self):
        from services import pdf_intent as pi

        self.assertIn("Đã nhận Word/Excel",
                      pi.ask_text("bao-cao.docx", pi.y_dinh_cho_office(None)))
        self.assertIn("Đã nhận PDF",
                      pi.ask_text("a.pdf", pi.allowed_intents(None)))

    def test_file_tam_giu_dung_duoi_that(self):
        """markitdown nhận dạng theo ĐUÔI — đặt nhầm .pdf là đọc ra rỗng."""
        from pathlib import Path
        from services import pdf_intent as pi

        pi.set_pending("k-test", b"PK\x03\x04 gia lap docx", "bao-cao.docx", ".docx")
        try:
            p = pi.get_pending("k-test") or {}
            self.assertTrue(Path(p.get("path") or "").name.endswith(".docx"))
        finally:
            pi.pop_pending("k-test")

    def test_kenh_zalo_ca_nhan_khong_con_chan_file_office(self):
        src = (GOC / "services" / "zalo_personal.py").read_text("utf-8")
        self.assertNotIn("Hiện em chỉ hỗ trợ chuyển PDF → Word", src)
        self.assertIn("_pi.la_office(name)", src)

if __name__ == "__main__":
    unittest.main()
