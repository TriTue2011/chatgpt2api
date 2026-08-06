"""Trong nhóm: TÁCH hội thoại live theo người, GIỮ CHUNG nhật ký và bộ nhớ.

Chủ máy chốt 06/08: "tách nhưng chỉ tách ở hội thoại live với bot thôi, còn đâu
những cái khác giữ nguyên nhất là nhật ký, bộ nhớ".

Ranh giới đó nằm ở ba hàm khác nhau, dễ sửa nhầm sang nhau:

    khoa phiên  (sess.load_history…)  → CÓ kèm người  → hội thoại riêng
    khoa_du_lieu (bộ nhớ, wiki, lịch) → BỎ người      → cả nhóm dùng chung
    khoa_nhat_ky (sổ chung của nhóm)  → BỎ người      → cả nhóm dùng chung

Đo trên máy chủ 06/08, phiên đang lưu thật:

    zalop_8845089824387263227:u6643404425553198601   ← nhóm, tách theo người
    -1003837425521#638:u6518712943                   ← Telegram nhóm+topic
    zalop_6643404425553198601                        ← chat 1-1, không cần :u
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import scope as sc  # noqa: E402


class _CauHinhGia:
    def __init__(self, data):
        self.data = data

    def get(self):
        return self.data

    def update(self, moi):
        self.data.update(moi)


class RanhGioiTachTests(unittest.TestCase):
    """Ba hàm, ba cách xử người gửi. Lẫn nhau là hỏng đúng chỗ chủ máy dặn."""

    NHOM = "zalop_8845089824387263227"
    A = "zalop_8845089824387263227:u111"
    B = "zalop_8845089824387263227:u222"

    def setUp(self):
        self._goc = sc.config if hasattr(sc, "config") else None
        import services.config as cfg_mod
        self._cfg_goc = cfg_mod.config
        cfg_mod.config = _CauHinhGia({})       # chưa lọc user → nhóm dùng chung
        self.addCleanup(setattr, cfg_mod, "config", self._cfg_goc)

    def test_hoi_thoai_live_TACH_theo_nguoi(self):
        """Khoá phiên của hai người phải khác nhau — đây là cái được tách."""
        self.assertNotEqual(self.A, self.B)
        self.assertEqual(sc.tach_khoa_phien(self.A).actor, "111")
        self.assertEqual(sc.tach_khoa_phien(self.B).actor, "222")

    def test_bo_nho_DUNG_CHUNG_ca_nhom(self):
        self.assertEqual(sc.khoa_du_lieu(self.A), sc.khoa_du_lieu(self.B))

    def test_nhat_ky_DUNG_CHUNG_ca_nhom(self):
        self.assertEqual(sc.khoa_nhat_ky(self.A), sc.khoa_nhat_ky(self.B))

    def test_nhat_ky_chung_KE_CA_khi_da_loc_user(self):
        """Nhật ký là sổ chung — lọc user cũng không tách nó ra."""
        import services.config as cfg_mod
        cfg_mod.config = _CauHinhGia({"thread_user_filters": {
            "zalop:8845089824387263227:111": ["rag"]}})
        self.assertEqual(sc.khoa_nhat_ky(self.A), sc.khoa_nhat_ky(self.B))

    def test_bo_nho_moi_tach_khi_chu_may_khai_loc_user(self):
        """Bộ nhớ theo công tắc riêng của nó, KHÔNG theo việc tách hội thoại."""
        import services.config as cfg_mod
        cfg_mod.config = _CauHinhGia({"thread_user_filters": {
            "zalop:8845089824387263227:111": ["rag"]}})
        self.assertNotEqual(sc.khoa_du_lieu(self.A), sc.khoa_du_lieu(self.B))


class CongTacTachPhienTests(unittest.TestCase):
    """Công tắc phải ĐỌC ĐƯỢC từ config.

    Bản cũ viết `getattr(config, "group_user_isolation", True)` — `config` là
    đối tượng kho cấu hình, không có thuộc tính tên đó, nên luôn rơi về mặc định
    và công tắc không bao giờ có tác dụng. Đo trên máy chủ 06/08 đúng như vậy.
    """

    def setUp(self):
        import services.config as cfg_mod
        self._goc = cfg_mod.config
        self.cfg_mod = cfg_mod
        self.addCleanup(setattr, cfg_mod, "config", self._goc)

    def test_khong_khai_gi_thi_MAC_DINH_TACH(self):
        self.cfg_mod.config = _CauHinhGia({})
        self.assertTrue(sc.tach_phien_theo_nguoi())

    def test_tat_duoc_that_su(self):
        self.cfg_mod.config = _CauHinhGia({"group_user_isolation": False})
        self.assertFalse(sc.tach_phien_theo_nguoi(),
                         "công tắc đặt trong config mà không có tác dụng")

    def test_bat_lai_duoc(self):
        self.cfg_mod.config = _CauHinhGia({"group_user_isolation": True})
        self.assertTrue(sc.tach_phien_theo_nguoi())


class BaKenhDeuDungMotCongTacTests(unittest.TestCase):
    """Ba kênh dựng khoá phiên ở ba chỗ — lệch nhau là hai người cùng nhóm ở
    kênh này chung phiên, kênh kia riêng phiên."""

    KENH = ("zalo_personal.py", "telegram_bot.py", "zalo_bot.py")

    def _src(self, ten):
        return (GOC / "services" / ten).read_text("utf-8")

    def test_khong_kenh_nao_con_doc_bang_getattr(self):
        """Soi bằng CÚ PHÁP, không tìm chữ: chú thích mô tả lại lỗi cũ cũng chứa
        đúng cụm đó, tìm chữ là đỏ oan (đã đỏ oan một lần lúc viết bài này)."""
        import ast
        for ten in self.KENH:
            with self.subTest(kenh=ten):
                cay = ast.parse(self._src(ten))
                for n in ast.walk(cay):
                    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                            and n.func.id == "getattr" and len(n.args) >= 2
                            and isinstance(n.args[1], ast.Constant)
                            and n.args[1].value == "group_user_isolation"):
                        self.fail(f"{ten}:{n.lineno} còn đọc công tắc bằng "
                                  "getattr — nó luôn rơi về mặc định")

    def test_ba_kenh_deu_goi_dung_mot_ham(self):
        for ten in self.KENH:
            with self.subTest(kenh=ten):
                self.assertIn("tach_phien_theo_nguoi", self._src(ten))

    def test_khoa_phien_kem_nguoi_gui(self):
        for ten, mau in (("zalo_personal.py", ':u{_snd}"'),
                         ("telegram_bot.py", ':u{user_id}"'),
                         ("zalo_bot.py", ':u{user_id}"')):
            with self.subTest(kenh=ten):
                self.assertIn(mau, self._src(ten))


if __name__ == "__main__":
    unittest.main()
