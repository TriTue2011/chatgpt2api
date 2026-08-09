"""Tài khoản OpenAI gốc và tài khoản Google KHÔNG dùng chung kho credential.

VÌ SAO PHẢI TÁCH (chủ máy yêu cầu 09/08/2026)

Cùng một địa chỉ `@gmail.com` có thể vừa là tài khoản Google vừa là tài khoản
OpenAI gốc, với HAI mật khẩu khác hẳn nhau. Bảng cũ để `email` UNIQUE nên hai
thứ đó đè lên nhau, và tệ hơn: `resolve_account` khớp theo LOCALPART, nên hồ sơ
`openai-benbap2011` khớp trúng bản ghi Google `benbap2011@gmail.com` và luồng
đăng nhập OpenAI nhận về mật khẩu Google.

Hậu quả không phải "đăng nhập hỏng rồi thử lại". Gõ sai mật khẩu vài lần liên
tiếp là đường ngắn nhất tới khoá tài khoản — và vì mỗi vòng khôi phục tự động
lại thử tiếp, nó tự bồi thêm.

Đo trên máy chủ trước khi tách: 10 bản ghi, 9 cái có hồ sơ `google-…`, đúng 1
cái (`d.ustinbay056483@gmail.com`) có hồ sơ `openai-…`. Bản chuyển đổi phân loại
theo đúng bằng chứng đó.
"""
from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC / "captcha-solver"))


def _nap_kho(thu_muc: Path):
    """Nạp lại `accounts_db` với DB nằm trong thư mục tạm."""
    os.environ["ACCOUNTS_DB"] = str(thu_muc / "accounts.db")
    import src.accounts_db as db
    return importlib.reload(db)


class TachKhoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.goc = Path(self._tmp.name)
        (self.goc / "profiles").mkdir()
        self.db = _nap_kho(self.goc)

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("ACCOUNTS_DB", None)

    def test_cung_email_hai_kho_la_hai_ban_ghi_doc_lap(self):
        """Đây là điều kiện cần: một Gmail có thể có cả hai loại tài khoản."""
        self.db.save_account("a@gmail.com", "mk-google", "seed-google", "", "google")
        self.db.save_account("a@gmail.com", "mk-openai", "seed-openai", "", "openai")

        g = self.db.get_account("a@gmail.com", "google")
        o = self.db.get_account("a@gmail.com", "openai")
        self.assertEqual(g["password"], "mk-google")
        self.assertEqual(o["password"], "mk-openai")
        self.assertEqual(g["totp_secret"], "seed-google")
        self.assertEqual(o["totp_secret"], "seed-openai")

    def test_luu_kho_nay_khong_de_len_kho_kia(self):
        self.db.save_account("a@gmail.com", "mk-google", "", "", "google")
        self.db.save_account("a@gmail.com", "mk-openai", "", "", "openai")
        self.db.save_account("a@gmail.com", "mk-openai-moi", "", "", "openai")
        self.assertEqual(self.db.get_account("a@gmail.com", "google")["password"], "mk-google")
        self.assertEqual(self.db.get_account("a@gmail.com", "openai")["password"], "mk-openai-moi")

    def test_ho_so_openai_KHONG_lay_duoc_mat_khau_google(self):
        """Lỗi nguy hiểm nhất: khớp localpart vắt qua hai kho."""
        self.db.save_account("benbap2011@gmail.com", "mk-google", "", "", "google")
        # Chưa lưu bản ghi OpenAI nào → phải trả None, TUYỆT ĐỐI không rơi sang
        # bản ghi Google cùng localpart.
        self.assertIsNone(self.db.resolve_account("openai-benbap2011"))

    def test_ho_so_google_KHONG_lay_duoc_mat_khau_openai(self):
        self.db.save_account("benbap2011@gmail.com", "mk-openai", "", "", "openai")
        self.assertIsNone(self.db.resolve_account("google-benbap2011"))

    def test_resolve_dung_kho_theo_tien_to_ho_so(self):
        self.db.save_account("benbap2011@gmail.com", "mk-google", "", "", "google")
        self.db.save_account("benbap2011@gmail.com", "mk-openai", "", "", "openai")
        self.assertEqual(self.db.resolve_account("google-benbap2011")["password"], "mk-google")
        self.assertEqual(self.db.resolve_account("openai-benbap2011")["password"], "mk-openai")
        # Các dịch vụ khác vẫn thuộc kho Google — không được đổi hành vi cũ.
        for ho_so in ("chatgpt-benbap2011", "gemini-web-benbap2011",
                      "claude-web-benbap2011", "codex-benbap2011"):
            self.assertEqual(self.db.resolve_account(ho_so)["password"], "mk-google", ho_so)

    def test_danh_sach_loc_theo_kho(self):
        self.db.save_account("g@gmail.com", "x", "", "", "google")
        self.db.save_account("o@gmail.com", "y", "", "", "openai")
        self.assertEqual([a["email"] for a in self.db.list_accounts("google")], ["g@gmail.com"])
        self.assertEqual([a["email"] for a in self.db.list_accounts("openai")], ["o@gmail.com"])
        self.assertEqual(len(self.db.list_accounts()), 2)   # None = cả hai

    def test_xoa_kho_nay_khong_dung_toi_kho_kia(self):
        self.db.save_account("a@gmail.com", "mk-google", "", "", "google")
        self.db.save_account("a@gmail.com", "mk-openai", "", "", "openai")
        self.assertTrue(self.db.delete_account("a@gmail.com", "openai"))
        self.assertIsNone(self.db.get_account("a@gmail.com", "openai"))
        self.assertIsNotNone(self.db.get_account("a@gmail.com", "google"))

    def test_dat_totp_khong_lan_sang_kho_kia(self):
        self.db.save_account("a@gmail.com", "mk", "seed-google", "", "google")
        self.db.save_account("a@gmail.com", "mk", "seed-openai", "", "openai")
        self.db.set_totp("a@gmail.com", "seed-moi", "openai")
        self.assertEqual(self.db.get_account("a@gmail.com", "google")["totp_secret"], "seed-google")
        self.assertEqual(self.db.get_account("a@gmail.com", "openai")["totp_secret"], "seed-moi")

    def test_mac_dinh_la_google_giu_nguyen_hanh_vi_cu(self):
        """Mọi nơi gọi cũ không truyền `loai` phải chạy y như trước."""
        self.db.save_account("a@gmail.com", "mk-google")
        self.assertEqual(self.db.get_account("a@gmail.com")["password"], "mk-google")
        self.assertEqual(self.db.resolve_account("a@gmail.com")["password"], "mk-google")


class ChuyenDoiBangCuTests(unittest.TestCase):
    """Bảng cũ (email UNIQUE, không có cột `loai`) phải lên được bảng mới."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.goc = Path(self._tmp.name)
        (self.goc / "profiles").mkdir()

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("ACCOUNTS_DB", None)

    def _dung_bang_cu(self, emails: list[str]) -> None:
        duong = self.goc / "accounts.db"
        c = sqlite3.connect(duong)
        c.execute("""CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            totp_secret TEXT NOT NULL DEFAULT '',
            label TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        for e in emails:
            c.execute("INSERT INTO accounts (email, password) VALUES (?, ?)", (e, "mk-" + e))
        c.commit(); c.close()

    def test_giu_du_ban_ghi_va_phan_loai_theo_ho_so_tren_dia(self):
        self._dung_bang_cu(["benbap2011@gmail.com", "d.ustinbay056483@gmail.com"])
        # Bằng chứng duy nhất đáng tin: hồ sơ `openai-…` chỉ do thẻ OpenAI tạo.
        (self.goc / "profiles" / "openai-d-ustinbay056483").mkdir()
        (self.goc / "profiles" / "google-benbap2011").mkdir()

        db = _nap_kho(self.goc)
        self.assertEqual(len(db.list_accounts()), 2, "chuyển đổi làm mất bản ghi")
        self.assertEqual([a["email"] for a in db.list_accounts("google")],
                         ["benbap2011@gmail.com"])
        self.assertEqual([a["email"] for a in db.list_accounts("openai")],
                         ["d.ustinbay056483@gmail.com"])

    def test_khong_co_ho_so_openai_thi_tat_ca_ve_google(self):
        """Kho cũ chỉ phục vụ tài khoản Google — mặc định phải là 'google'."""
        self._dung_bang_cu(["a@gmail.com", "b@gmail.com"])
        db = _nap_kho(self.goc)
        self.assertEqual(len(db.list_accounts("google")), 2)
        self.assertEqual(len(db.list_accounts("openai")), 0)

    def test_chay_lai_init_khong_hong_gi(self):
        self._dung_bang_cu(["a@gmail.com"])
        db = _nap_kho(self.goc)
        db.init_db()          # gọi lại: không được ném, không được mất dữ liệu
        db.init_db()
        self.assertEqual(len(db.list_accounts()), 1)


if __name__ == "__main__":
    unittest.main()
