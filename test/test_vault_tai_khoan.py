"""Mã hoá tại chỗ cho mật khẩu Google và hạt giống TOTP trong accounts.db.

Hai giá trị đó cộng lại là toàn quyền vào tài khoản Google. Hạt giống TOTP
không phải "mã 6 số" — nó SINH RA mọi mã 6 số từ nay về sau, nên lộ nó là mất
luôn yếu tố thứ hai chứ không phải một lần đăng nhập. File `accounts.db` nằm
trên volume và đi theo mọi bản sao lưu.

Ràng buộc khó nhất không phải "mã hoá được" mà là **không làm hỏng dữ liệu
đang có**: bản ghi cũ chưa mã hoá vẫn phải đọc được, và mất khoá thì phải im
lặng trả rỗng chứ không đưa chuỗi rác đi đăng nhập.
"""
from __future__ import annotations

import base64
import importlib.util
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


def _nap_vault():
    """`captcha-solver` có dấu gạch nên không import theo tên gói được."""
    duong = GOC / "captcha-solver" / "src" / "vault.py"
    spec = importlib.util.spec_from_file_location("_vault_under_test", duong)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    CO_CRYPTO = True
except Exception:
    CO_CRYPTO = False

KHOA = base64.b64encode(bytes(range(32))).decode()
KHOA_KHAC = base64.b64encode(bytes(range(32, 64))).decode()


class _Nen(unittest.TestCase):
    def dat_khoa(self, gia_tri: str | None):
        self.vault = _nap_vault()
        cu = os.environ.get("VAULT_MASTER_KEY")

        def tra_lai():
            if cu is None:
                os.environ.pop("VAULT_MASTER_KEY", None)
            else:
                os.environ["VAULT_MASTER_KEY"] = cu

        self.addCleanup(tra_lai)
        if gia_tri is None:
            os.environ.pop("VAULT_MASTER_KEY", None)
        else:
            os.environ["VAULT_MASTER_KEY"] = gia_tri


@unittest.skipUnless(CO_CRYPTO, "cần cryptography (có trong CI và trong container)")
class MaHoaTests(_Nen):
    def test_vong_ma_hoa_giai_ma(self):
        self.dat_khoa(KHOA)
        ct = self.vault.ma_hoa("mat-khau-that", "a@gmail.com", "password")
        self.assertNotIn("mat-khau-that", ct)
        self.assertTrue(ct.startswith("v1:"))
        self.assertEqual(self.vault.giai_ma(ct, "a@gmail.com", "password"), "mat-khau-that")

    def test_moi_lan_ma_hoa_ra_khac_nhau(self):
        """Nonce cố định thì hai tài khoản cùng mật khẩu lộ ra là trùng nhau."""
        self.dat_khoa(KHOA)
        a = self.vault.ma_hoa("cung-mot-mat-khau", "a@gmail.com", "password")
        b = self.vault.ma_hoa("cung-mot-mat-khau", "a@gmail.com", "password")
        self.assertNotEqual(a, b)

    def test_khong_be_ciphertext_sang_tai_khoan_khac(self):
        """AAD gồm email — bê khối của A sang B phải hỏng, không phải ra giá trị."""
        self.dat_khoa(KHOA)
        ct = self.vault.ma_hoa("mat-khau-cua-A", "a@gmail.com", "password")
        self.assertEqual(self.vault.giai_ma(ct, "b@gmail.com", "password"), "")

    def test_khong_doi_cho_password_voi_totp(self):
        """AAD gồm tên trường."""
        self.dat_khoa(KHOA)
        ct = self.vault.ma_hoa("JBSWY3DPEHPK3PXP", "a@gmail.com", "totp_secret")
        self.assertEqual(self.vault.giai_ma(ct, "a@gmail.com", "password"), "")

    def test_khoa_khac_thi_khong_doc_duoc(self):
        self.dat_khoa(KHOA)
        ct = self.vault.ma_hoa("bi-mat", "a@gmail.com", "password")
        self.dat_khoa(KHOA_KHAC)
        self.assertEqual(self.vault.giai_ma(ct, "a@gmail.com", "password"), "")

    def test_sua_mot_byte_thi_hong(self):
        """GCM có xác thực — sửa ciphertext phải bị phát hiện."""
        self.dat_khoa(KHOA)
        ct = self.vault.ma_hoa("bi-mat", "a@gmail.com", "password")
        hong = ct[:-5] + ("A" if ct[-5] != "A" else "B") + ct[-4:]
        self.assertEqual(self.vault.giai_ma(hong, "a@gmail.com", "password"), "")


class TuongThichNguocTests(_Nen):
    def test_ban_ghi_CU_chua_ma_hoa_van_doc_duoc(self):
        """Không có tiền tố `v1:` = dữ liệu cũ. Vỡ chỗ này là mất hết tài khoản."""
        self.dat_khoa(KHOA if CO_CRYPTO else None)
        self.assertEqual(self.vault.giai_ma("mat-khau-cu-chua-ma-hoa",
                                            "a@gmail.com", "password"),
                         "mat-khau-cu-chua-ma-hoa")

    def test_chua_dat_khoa_thi_ghi_thuong_nhu_cu(self):
        """Bắt buộc VAULT_MASTER_KEY sẽ làm container không lên được."""
        self.dat_khoa(None)
        self.assertFalse(self.vault.dang_bat())
        self.assertEqual(self.vault.ma_hoa("abc", "a@gmail.com", "password"), "abc")
        self.assertEqual(self.vault.giai_ma("abc", "a@gmail.com", "password"), "abc")

    def test_mat_khoa_thi_tra_RONG_chu_khong_tra_rac(self):
        """Đem chuỗi rác đi đăng nhập sẽ nhận một lỗi chẳng liên quan."""
        if not CO_CRYPTO:
            self.skipTest("cần cryptography")
        self.dat_khoa(KHOA)
        ct = self.vault.ma_hoa("bi-mat", "a@gmail.com", "password")
        self.dat_khoa(None)
        self.assertEqual(self.vault.giai_ma(ct, "a@gmail.com", "password"), "")

    def test_khoa_sai_dinh_dang_thi_coi_nhu_chua_dat(self):
        for xau in ("khong-phai-base64!!", base64.b64encode(b"ngan").decode()):
            self.dat_khoa(xau)
            self.assertFalse(self.vault.dang_bat(), f"{xau!r} không được coi là hợp lệ")

    def test_gia_tri_rong_van_la_rong(self):
        self.dat_khoa(KHOA if CO_CRYPTO else None)
        self.assertEqual(self.vault.ma_hoa("", "a@gmail.com", "password"), "")


class KhongLoTotpRaDanhSachTests(unittest.TestCase):
    """`list_accounts` từng ghi 'without password for safety' mà vẫn trả TOTP."""

    def test_list_accounts_khong_tra_totp_secret(self):
        src = (GOC / "captcha-solver/src/accounts_db.py").read_text(encoding="utf-8")
        i = src.index("def list_accounts")
        than = src[i:src.index("def get_account")]
        self.assertIn('d.pop("totp_secret"', than,
                      "totp_secret vẫn nằm trong danh sách trả về")
        self.assertIn("has_totp", than)

    def test_save_ma_hoa_TRUOC_khi_cham_sql(self):
        """SQLite ghi cả câu lệnh vào WAL — giá trị thường không được vào SQL."""
        src = (GOC / "captcha-solver/src/accounts_db.py").read_text(encoding="utf-8")
        i = src.index("def save_account")
        than = src[i:i + 1400]
        vi_ma_hoa = than.index("vault.ma_hoa")
        vi_sql = than.index("_conn()")
        self.assertLess(vi_ma_hoa, vi_sql, "mã hoá sau khi mở kết nối SQL")

    def test_get_account_giai_ma_ca_hai_truong(self):
        src = (GOC / "captcha-solver/src/accounts_db.py").read_text(encoding="utf-8")
        i = src.index("def get_account")
        than = src[i:src.index("def resolve_account")]
        self.assertIn('vault.giai_ma(d.get("password")', than)
        self.assertIn('vault.giai_ma(d.get("totp_secret")', than)


if __name__ == "__main__":
    unittest.main()
