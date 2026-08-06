"""Mục «Lưu lên kho đám mây» trong menu ý định khi nhận tệp.

Chủ máy chốt 05/08: "ngoài các lựa chọn sẵn có theo loại tệp, thêm lựa chọn lưu
online". Người dùng tự chọn mục này thì KHÔNG hỏi admin lần nữa — họ vừa tự
quyết rồi.

Bài quan trọng nhất ở đây là `SoTrongMenuKhopSoGiaiRaTests`: số hiện trên màn
hình phải khớp số lúc giải. Đó là một lỗi CÓ THẬT trước khi thêm mục này — menu
tệp Office dựng bằng `y_dinh_cho_office` (3 mục) còn lúc giải số lại dùng
`allowed_intents` (5 mục), nên gõ "3" ra Word trong khi màn hình ghi "3. Tóm
tắt". Thêm mục thứ sáu vào giữa cảnh đó là làm nó tệ hơn.
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import pdf_intent as pi  # noqa: E402
from services.agent import luu_tru_online as lt  # noqa: E402


class _CauHinhGia:
    def __init__(self, data):
        self.data = data

    def get(self):
        return self.data

    def update(self, moi):
        self.data.update(moi)


class ChiHienKhiDaKhaiKhoTests(unittest.TestCase):
    """Hiện một lựa chọn bấm vào không ra gì thì tệ hơn là không hiện."""

    def setUp(self):
        self._goc = lt.config
        self.addCleanup(setattr, lt, "config", self._goc)

    def test_chua_khai_kho_thi_khong_hien(self):
        lt.config = _CauHinhGia({})
        self.assertNotIn(pi.LUU_ONLINE,
                         pi.them_luu_online({pi.TOM_TAT}, "zalop", "nhom1"))

    def test_da_khai_kho_thi_hien(self):
        lt.config = _CauHinhGia({"luu_tru_online": {
            "zalop:nhom1": {"enabled": True, "kho": "drive"}}})
        self.assertIn(pi.LUU_ONLINE,
                      pi.them_luu_online({pi.TOM_TAT}, "zalop", "nhom1"))

    def test_khong_lam_mat_muc_dang_co(self):
        lt.config = _CauHinhGia({"luu_tru_online": {
            "zalop:nhom1": {"enabled": True, "kho": "drive"}}})
        ra = pi.them_luu_online({pi.TOM_TAT, pi.WORD}, "zalop", "nhom1")
        self.assertIn(pi.TOM_TAT, ra)
        self.assertIn(pi.WORD, ra)

    def test_khong_loc_thread_van_khong_tu_hien(self):
        """`allow=None` = thread không lọc gì. Vẫn phải khai kho mới hiện mục."""
        self.assertNotIn(pi.LUU_ONLINE, pi.allowed_intents(None))

    def test_pham_vi_khac_khong_an_theo(self):
        lt.config = _CauHinhGia({"luu_tru_online": {
            "zalop:nhom1": {"enabled": True, "kho": "drive"}}})
        self.assertNotIn(pi.LUU_ONLINE,
                         pi.them_luu_online({pi.TOM_TAT}, "zalop", "nhom-khac"))


class NhanRaYDinhTests(unittest.TestCase):

    def test_tu_khoa_tieng_viet(self):
        for t in ("lưu online", "lưu đám mây", "lưu lên mây giúp em",
                  "lưu drive", "luu dam may", "upload lên kho"):
            with self.subTest(t=t):
                self.assertEqual(pi.parse_intent(t, {pi.LUU_ONLINE}), pi.LUU_ONLINE)

    def test_khong_lan_voi_y_dinh_khac(self):
        cap = [("tóm tắt giúp em", pi.TOM_TAT), ("chuyển word", pi.WORD),
               ("nạp rag kiến thức", pi.RAG_KNOWLEDGE), ("excel", pi.EXCEL)]
        for t, mong in cap:
            with self.subTest(t=t):
                self.assertEqual(pi.parse_intent(t, set(pi.ALL_INTENTS)), mong)


class SoTrongMenuKhopSoGiaiRaTests(unittest.TestCase):
    """Số hiện trên màn hình phải ra đúng việc đó — bấm đúng số mà ra việc khác
    là lỗi im lặng, người dùng không có cách nào biết."""

    def _muc_trong_menu(self, ten_tep: str, intents: set[str]) -> list[str]:
        """Đọc lại menu đã in, trả nhãn theo thứ tự đánh số."""
        s = pi.ask_text(ten_tep, intents)
        return [d.split(". ", 1)[1] for d in s.splitlines()
                if d[:1].isdigit() and ". " in d]

    def _khop(self, ten_tep: str, intents: set[str]):
        nhan = self._muc_trong_menu(ten_tep, intents)
        for i in range(1, len(nhan) + 1):
            y = pi.parse_intent(str(i), intents)
            self.assertIsNotNone(y, f"gõ {i} ra None dù menu có mục thứ {i}")
            # Nhãn của ý định giải ra phải chính là nhãn đứng ở vị trí đó.
            tu_khoa = {pi.RAG_KNOWLEDGE: "RAG kiến thức", pi.RAG_TEACHER: "RAG teacher",
                       pi.WORD: "Word", pi.EXCEL: "Excel", pi.TOM_TAT: "Tóm tắt",
                       pi.LUU_ONLINE: "kho đám mây"}[y]
            self.assertIn(tu_khoa, nhan[i - 1],
                          f"gõ {i} ra {y} nhưng màn hình ghi {nhan[i - 1]!r}")

    def test_pdf_du_moi_muc(self):
        self._khop("bao-cao.pdf", set(pi.ALL_INTENTS))

    def test_office_bo_word_excel(self):
        """Đúng cảnh đã sai trước đây: menu 3 mục, số phải khớp 3 mục đó."""
        self._khop("bao-cao.docx", pi.y_dinh_cho_office(None) | {pi.LUU_ONLINE})

    def test_chi_co_hai_muc(self):
        self._khop("a.pdf", {pi.TOM_TAT, pi.LUU_ONLINE})

    def test_moi_muc_deu_go_so_duoc_khong_bo_sot(self):
        """Bảng số trong parse_intent từng dừng ở 4 rồi ở 5 — nay phải tới 6."""
        nhan = self._muc_trong_menu("a.pdf", set(pi.ALL_INTENTS))
        self.assertEqual(len(nhan), len(pi.INTENT_ORDER))
        self.assertIsNotNone(pi.parse_intent(str(len(nhan)), set(pi.ALL_INTENTS)))


class NhoBoYDinhDaHienTests(unittest.TestCase):
    """Bản chờ phải nhớ bộ đã hiện, không thì lúc giải số lại suy lại — chính là
    nguồn của lỗi lệch số."""

    def test_nho_va_tra_lai_dung_bo(self):
        pend = {"intents": [pi.TOM_TAT, pi.LUU_ONLINE]}
        self.assertEqual(pi.y_dinh_da_moi(pend, set(pi.ALL_INTENTS)),
                         {pi.TOM_TAT, pi.LUU_ONLINE})

    def test_ban_ghi_cu_khong_co_thi_dung_mac_dinh(self):
        """Bản chờ tạo trước lần nâng cấp này không có khoá đó."""
        self.assertEqual(pi.y_dinh_da_moi({"path": "/tmp/x"}, {pi.WORD}), {pi.WORD})
        self.assertEqual(pi.y_dinh_da_moi(None, {pi.WORD}), {pi.WORD})

    def test_set_pending_ghi_bo_da_hien(self):
        import tempfile
        khoa = "test:nho-bo-y-dinh"
        with tempfile.TemporaryDirectory():
            pi.set_pending(khoa, b"%PDF-1.4 x", "a.pdf", ".pdf",
                           intents={pi.TOM_TAT, pi.LUU_ONLINE})
        try:
            pend = pi.get_pending(khoa)
            self.assertEqual(set(pend["intents"]), {pi.TOM_TAT, pi.LUU_ONLINE})
        finally:
            p = (pi.pop_pending(khoa) or {}).get("path")
            if p and os.path.exists(p):
                os.unlink(p)


class NoiVaoBaKenhTests(unittest.TestCase):
    """Thêm mục vào menu mà kênh không xử lý thì bấm vào là im lặng."""

    KENH = ("zalo_personal.py", "telegram_bot.py", "zalo_bot.py")

    def _src(self, ten):
        return (GOC / "services" / ten).read_text("utf-8")

    def test_moi_kenh_deu_them_muc_vao_menu(self):
        for ten in self.KENH:
            with self.subTest(ten=ten):
                self.assertIn("them_luu_online(", self._src(ten))

    def test_moi_kenh_deu_nho_bo_da_hien(self):
        for ten in self.KENH:
            with self.subTest(ten=ten):
                src = self._src(ten)
                self.assertIn("intents=", src, "set_pending phải ghi bộ đã hiện")
                self.assertIn("y_dinh_da_moi(", src, "giải số phải dùng bộ đã hiện")

    def test_moi_kenh_deu_xu_ly_y_dinh_do(self):
        for ten in self.KENH:
            with self.subTest(ten=ten):
                src = self._src(ten)
                self.assertIn("_pi.LUU_ONLINE", src)
                self.assertIn("luu_ngay(", src)


if __name__ == "__main__":
    unittest.main()
