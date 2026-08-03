"""Phạm vi dữ liệu: mặc định độc lập tuyệt đối, nhóm/topic không có filter thì dùng chung.

Khoá lại NGUYÊN VĂN bảng hành vi chủ máy chốt 03/08. Đây là nền của mọi thứ
mang tính "của ai": lịch sử, memory, goals, nhắc việc, lịch, persona, file đã
xử lý, cache, khoá chống chạy song song.

Bối cảnh đo thật trên máy chủ 03/08: 1.162 bản ghi memory nằm chung ĐÚNG MỘT
khoá `chatgpt2api`, vì mỗi adapter tự ghép chuỗi khoá rồi truyền xuống dưới cái
tên `user_id`, và tầng memory có đường lùi về khoá mặc định khi thiếu.
"""
from __future__ import annotations

import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import scope as sc  # noqa: E402

TELE, ZALO = "telegram", "zalo_bot"
BOT1, BOT2 = "bot-1", "bot-2"
NHOM = "-100777"
A, B = "u_a", "u_b"


def _rieng(**kw) -> sc.Scope:
    """Chat 1-1."""
    kw.setdefault("channel", TELE)
    kw.setdefault("account_id", BOT1)
    return sc.dung_scope(chat_rieng=True, **kw)


def _nhom(**kw) -> sc.Scope:
    """Nhóm/topic. `co_filter_user=True` = người này có filter riêng."""
    kw.setdefault("channel", TELE)
    kw.setdefault("account_id", BOT1)
    kw.setdefault("chat_id", NHOM)
    return sc.dung_scope(chat_rieng=False, **kw)


class BangHanhVi(unittest.TestCase):
    """Đúng 12 dòng trong bảng đã chốt."""

    def test_hai_nguoi_chat_1_1_khong_thay_nhau(self):
        self.assertNotEqual(_rieng(chat_id=A, actor_id=A).key(),
                            _rieng(chat_id=B, actor_id=B).key())

    def test_cung_nguoi_khac_BOT_thi_khac_bo_nho(self):
        self.assertNotEqual(_rieng(chat_id=A, actor_id=A).key(),
                            _rieng(chat_id=A, actor_id=A, account_id=BOT2).key())

    def test_cung_nguoi_khac_KENH_thi_khac_bo_nho(self):
        self.assertNotEqual(_rieng(chat_id=A, actor_id=A).key(),
                            _rieng(chat_id=A, actor_id=A, channel=ZALO).key())

    def test_nhom_khong_filter_thi_moi_nguoi_DUNG_CHUNG(self):
        self.assertEqual(_nhom(actor_id=A).key(), _nhom(actor_id=B).key())

    def test_topic_khong_filter_thi_DUNG_CHUNG_trong_topic(self):
        self.assertEqual(_nhom(actor_id=A, topic_id="7").key(),
                         _nhom(actor_id=B, topic_id="7").key())

    def test_co_filter_thi_TACH_RIENG_nguoi_do(self):
        rieng_a = _nhom(actor_id=A, co_filter_user=True)
        self.assertNotEqual(rieng_a.key(), _nhom(actor_id=A).key())

    def test_nguoi_con_lai_van_dung_memory_nhom(self):
        """A tách ra không được kéo theo B."""
        _nhom(actor_id=A, co_filter_user=True)
        self.assertEqual(_nhom(actor_id=B).key(), _nhom(actor_id="u_c").key())

    def test_cung_user_hai_NHOM_khac_nhau_thi_tach(self):
        self.assertNotEqual(_nhom(actor_id=A).key(),
                            _nhom(actor_id=A, chat_id="-100888").key())

    def test_cung_user_hai_TOPIC_khac_nhau_thi_tach(self):
        self.assertNotEqual(_nhom(actor_id=A, topic_id="1").key(),
                            _nhom(actor_id=A, topic_id="2").key())

    def test_topic_luon_thang_nhom(self):
        """Topic 1, Topic 2 và General là BA phạm vi độc lập."""
        ba = {_nhom(actor_id=A, topic_id="1").key(),
              _nhom(actor_id=A, topic_id="2").key(),
              _nhom(actor_id=A, topic_id=None).key()}
        self.assertEqual(len(ba), 3)

    def test_admin_trong_nhom_khong_filter_dung_chung_nhu_moi_nguoi(self):
        """Vai trò KHÔNG nằm trong khoá — admin không phải một ngăn riêng."""
        self.assertEqual(_nhom(actor_id="admin_that").key(), _nhom(actor_id=B).key())

    def test_admin_co_filter_thi_rieng_nhu_user_thuong(self):
        self.assertNotEqual(_nhom(actor_id="admin_that", co_filter_user=True).key(),
                            _nhom(actor_id=B).key())


class KhongCoDuongLui(unittest.TestCase):
    """Thiếu định danh phải HỎNG TO TIẾNG. Rơi về khoá chung là gốc của sự cố."""

    def test_thieu_mang_nao_cung_nem_loi(self):
        du = {"channel": TELE, "account_id": BOT1, "chat_id": NHOM, "actor_id": A}
        for thieu in du:
            args = dict(du)
            args[thieu] = ""
            with self.assertRaises(ValueError, msg=thieu):
                sc.dung_scope(**args)

    def test_loi_noi_ro_thieu_gi(self):
        with self.assertRaises(ValueError) as e:
            sc.dung_scope(channel="", account_id="", chat_id=NHOM, actor_id=A)
        self.assertIn("channel", str(e.exception))
        self.assertIn("account_id", str(e.exception))

    def test_khong_co_ham_nao_tu_ve_khoa_mac_dinh(self):
        nguon = (pathlib.Path(__file__).resolve().parents[1]
                 / "services" / "agent" / "scope.py").read_text("utf-8")
        self.assertNotIn("chatgpt2api", nguon)


class KhoaKhongTheGiaMao(unittest.TestCase):
    """id là chuỗi tự do (Zalo cá nhân), dấu ':' '#' trong id không được đẩy
    sang ô bên cạnh — nếu được thì người ta tự đặt tên để chui vào scope khác."""

    def test_dau_hai_cham_trong_id_khong_pha_khoa(self):
        a = sc.dung_scope(TELE, BOT1, "x:y#z", actor_id=A, chat_rieng=True)
        b = sc.dung_scope(TELE, BOT1, "x", actor_id=A, chat_rieng=True, topic_id="z")
        self.assertNotEqual(a.key(), b.key())

    def test_doc_lai_dung_nguyen_ban(self):
        goc = sc.dung_scope(TELE, BOT1, "chat:lạ#1", actor_id="u:a",
                            topic_id="top#2", chat_rieng=True)
        self.assertEqual(sc.doc_key(goc.key()), goc)

    def test_khoa_doi_cu_thi_tra_None(self):
        for cu in ("-100777#7:u123", "zalo_abc:u9", "chatgpt2api", ""):
            self.assertIsNone(sc.doc_key(cu), cu)


class YeuCauDangChoPhaiTheoNGUOI(unittest.TestCase):
    """Memory nhóm chung được, quyền XÁC NHẬN HÀNH ĐỘNG thì không.

    Không tách thì người B bấm "Ok" là duyệt luôn lệnh của người A: tắt máy, gửi
    tin, phát ra loa, chọn ảnh/PDF mà A vừa gửi.
    """

    def test_hai_nguoi_trong_cung_nhom_chung_co_khoa_cho_KHAC_nhau(self):
        s = _nhom(actor_id=A)                     # nhóm dùng chung
        self.assertEqual(s.key(), _nhom(actor_id=B).key())
        self.assertNotEqual(sc.khoa_yeu_cau(s, A, "r1"),
                            sc.khoa_yeu_cau(s, B, "r1"))

    def test_cung_nguoi_hai_yeu_cau_khac_nhau(self):
        s = _nhom(actor_id=A)
        self.assertNotEqual(sc.khoa_yeu_cau(s, A, "r1"), sc.khoa_yeu_cau(s, A, "r2"))

    def test_thieu_actor_thi_nem_loi(self):
        with self.assertRaises(ValueError):
            sc.khoa_yeu_cau(_nhom(actor_id=A), "", "r1")


class BatTatFilter(unittest.TestCase):
    """Bật filter = dùng scope riêng, KHÔNG chép memory nhóm sang. Tắt filter =
    quay lại memory nhóm, memory riêng cũ giữ nguyên chứ không merge."""

    def test_bat_roi_tat_thi_quay_lai_dung_khoa_nhom_cu(self):
        nhom_truoc = _nhom(actor_id=A).key()
        _nhom(actor_id=A, co_filter_user=True)          # bật
        self.assertEqual(_nhom(actor_id=A).key(), nhom_truoc)   # tắt → về chỗ cũ

    def test_bat_lai_thi_ve_dung_khoa_rieng_cu(self):
        rieng_truoc = _nhom(actor_id=A, co_filter_user=True).key()
        _nhom(actor_id=A)                                # tắt
        self.assertEqual(_nhom(actor_id=A, co_filter_user=True).key(), rieng_truoc)

    def test_cua_nhom_tra_dung_pham_vi_dung_chung(self):
        self.assertEqual(_nhom(actor_id=A, co_filter_user=True).cua_nhom().key(),
                         _nhom(actor_id=B).key())


if __name__ == "__main__":
    unittest.main()
