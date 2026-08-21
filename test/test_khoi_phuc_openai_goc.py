"""Tài khoản OpenAI GỐC không được lôi đi đường Google.

SỰ CỐ 20/08/2026 — `bios.disused99+6e84t67f@icloud.com` (ChatGPT free). Chủ máy
nhận tin báo:

    ⚠️ ChatGPT free — bios.disused99+6e84t67f@icloud.com
    Lỗi: dead:periodic_scan
    → Đang tự khôi phục (tài khoản Google)…
    🔧 [T3] Đang đăng nhập lại tài khoản Google (giống nút 'Chỉ đăng nhập')…
    ❌ KHÔNG tự khôi phục được (đã thử: T2-workspace → T3-đăng-nhập-Google).
    → Lý do: no saved Google credentials for this profile.

Tài khoản này KHÔNG có tài khoản Google nào. Đo trên máy chủ thật hôm đó:

  · `accounts.db` có ĐÚNG MỘT bản ghi cho địa chỉ đó, cột `loai='openai'`, đủ cả
    mật khẩu lẫn hạt giống TOTP;
  · thư mục hồ sơ `openai-bios-disused99-6e84t67f` CÓ THẬT (chỉ thẻ "OpenAI gốc"
    tạo ra được nó), bên cạnh một thư mục `google-…` do chính các lượt khôi phục
    sai đường sinh ra;
  · `resolve_account("openai-bios-disused99-6e84t67f")` vẫn trả None.

BA LỖI NỐI NHAU

1. `_has_google_creds` hỏi kho credential mà KHÔNG kèm cột `loai`, nên bản ghi
   kho 'openai' bị đếm thành "có mật khẩu Google" → thang khôi phục bật nhánh
   Google và chạy T3 `auto-login-saved`.
2. Nhánh Google còn được giữ sống bởi `has_profile`: thư mục `google-…` có thật,
   nhưng nó không chứng minh gì cả — mọi lượt mở Chrome đều tạo ra nó.
3. `accounts_db.resolve_account` chuẩn hoá localpart bằng cách bỏ '-' và '.',
   trong khi tên hồ sơ đổi MỌI ký tự lạ thành '-'. Địa chỉ có dấu '+' — cả hai
   tài khoản OpenAI gốc đang lưu đều thế — không bao giờ khớp, nên ngay cả khi
   gọi đúng hồ sơ `openai-…` thì mật khẩu đã lưu vẫn coi như không tồn tại.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
sys.path.insert(0, str(GOC / "captcha-solver"))

EMAIL = "bios.disused99+6e84t67f@icloud.com"
HO_SO_OPENAI = "openai-bios-disused99-6e84t67f"
HO_SO_GOOGLE = "google-bios-disused99-6e84t67f"


def _dung_db(duong: str, hang: list[tuple[str, str]]) -> None:
    """accounts.db tối thiểu: (email, loai) — mật khẩu để chữ thường cho gọn."""
    c = sqlite3.connect(duong)
    c.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, "
              "email TEXT NOT NULL, password TEXT NOT NULL, "
              "totp_secret TEXT NOT NULL DEFAULT '', label TEXT DEFAULT '', "
              "loai TEXT NOT NULL DEFAULT 'google')")
    c.executemany("INSERT INTO accounts (email, password, totp_secret, loai) "
                  "VALUES (?,?,?,?)",
                  [(em, "mk", "hat-giong", loai) for em, loai in hang])
    c.commit()
    c.close()


class TraCredentialDungKho(unittest.TestCase):
    """Bản ghi kho 'openai' KHÔNG được tính là "có mật khẩu Google"."""

    def setUp(self):
        from services import account_recovery as ar
        self.ar = ar
        self._tmp = tempfile.TemporaryDirectory()
        db = os.path.join(self._tmp.name, "accounts.db")
        _dung_db(db, [(EMAIL, "openai"), ("benbap2011@gmail.com", "google")])
        self._vá = mock.patch.object(ar, "_ACCOUNTS_DB", db)
        self._vá.start()

    def tearDown(self):
        self._vá.stop()
        self._tmp.cleanup()

    def test_chi_co_mat_khau_openai_thi_khong_phai_mat_khau_google(self):
        self.assertFalse(self.ar._has_google_creds(HO_SO_GOOGLE, EMAIL))
        self.assertTrue(self.ar._has_openai_creds(email=EMAIL))

    def test_tra_theo_ten_ho_so_van_khop_dia_chi_co_dau_cong(self):
        """Tên hồ sơ đã đổi '+' và '.' thành '-' — hai bên phải chuẩn hoá giống nhau."""
        self.assertTrue(self.ar._co_creds("openai", HO_SO_OPENAI))
        self.assertFalse(self.ar._co_creds("google", HO_SO_OPENAI))

    def test_tai_khoan_google_thuc_su_van_duoc_nhan(self):
        self.assertTrue(self.ar._has_google_creds("google-benbap2011",
                                                  "benbap2011@gmail.com"))
        self.assertFalse(self.ar._has_openai_creds(email="benbap2011@gmail.com"))


class NhanDangHoSoOpenAiGoc(unittest.TestCase):
    """Thư mục `openai-…` LÀ bằng chứng; thư mục `google-…` thì không."""

    def setUp(self):
        from services import account_recovery as ar
        self.ar = ar
        self._tmp = tempfile.TemporaryDirectory()
        self.thu_muc = Path(self._tmp.name)
        self._vá = mock.patch.object(ar, "_CAPTCHA_PROFILES", str(self.thu_muc))
        self._vá.start()

    def tearDown(self):
        self._vá.stop()
        self._tmp.cleanup()

    def test_thu_muc_openai_la_bang_chung(self):
        (self.thu_muc / HO_SO_OPENAI).mkdir()
        (self.thu_muc / HO_SO_GOOGLE).mkdir()   # do lượt khôi phục hụt tạo ra
        self.assertEqual(self.ar._ho_so_openai(EMAIL), HO_SO_OPENAI)

    def test_chi_co_thu_muc_google_thi_khong_phai_openai_goc(self):
        (self.thu_muc / "google-benbap2011").mkdir()
        with mock.patch.object(self.ar, "_has_openai_creds", return_value=False):
            self.assertEqual(self.ar._ho_so_openai("benbap2011@gmail.com"), "")

    def test_chua_co_thu_muc_nhung_kho_chi_co_mat_khau_openai(self):
        with mock.patch.object(self.ar, "_has_openai_creds", return_value=True), \
             mock.patch.object(self.ar, "_has_google_creds", return_value=False):
            self.assertEqual(self.ar._ho_so_openai(EMAIL), HO_SO_OPENAI)


class ThangKhoiPhucDiDungNhanh(unittest.TestCase):
    """`recover_provider_account` phải bỏ HẲN nhánh Google cho tài khoản này."""

    def setUp(self):
        from services import account_recovery as ar
        self.ar = ar
        ar._last_attempt.clear()
        self.tin: list[str] = []
        self.goi: list[str] = []

        def _reuse(profile, email):
            self.goi.append(f"reuse:{profile}")
            return ""

        def _freshen(profile, **kw):
            self.goi.append(f"freshen:{profile}")
            return False

        self.openai_ket_qua = "eyJ-token-moi"

        def _openai(profile, email):
            self.goi.append(f"openai:{profile}")
            return self.openai_ket_qua

        self.vá = [
            mock.patch.object(ar, "_notify", lambda text, detail=None: self.tin.append(text)),
            mock.patch.object(ar, "_dong_hang_loat", lambda email: None),
            mock.patch.object(ar, "_ho_so_openai", lambda email: HO_SO_OPENAI),
            # Hai thứ này BẬT để chứng minh chúng bị bỏ qua đúng như phải thế.
            mock.patch.object(ar, "_has_profile", lambda profile: True),
            mock.patch.object(ar, "_has_google_creds", lambda profile, email="": True),
            mock.patch.object(ar, "_freshen_google", _freshen),
            mock.patch.dict(ar._PROVIDERS["free"],
                            {"reuse": _reuse, "openai": _openai}),
        ]
        for v in self.vá:
            v.start()

    def tearDown(self):
        for v in self.vá:
            v.stop()
        self.ar._last_attempt.clear()

    def _chay(self):
        self.ar.recover_provider_account({"email": EMAIL}, "free", "dead:periodic_scan")

    def test_chay_dung_tang_openai_va_khong_dong_toi_google(self):
        self._chay()
        self.assertEqual(self.goi, [f"openai:{HO_SO_OPENAI}"])

    def test_tin_bao_khong_goi_day_la_tai_khoan_google(self):
        self._chay()
        mo_dau = self.tin[0]
        self.assertIn("tài khoản OpenAI gốc", mo_dau)
        self.assertNotIn("tài khoản Google", mo_dau)

    def test_khoi_phuc_duoc_thi_bao_xong(self):
        self._chay()
        self.assertTrue(any(t.startswith("✅") for t in self.tin), self.tin)

    def test_that_bai_thi_chi_duong_OpenAI_chu_khong_phai_Google(self):
        self.openai_ket_qua = ""
        self._chay()
        cuoi = self.tin[-1]
        self.assertIn("KHÔNG tự khôi phục được", cuoi)
        self.assertIn("T2/T3-OpenAI-gốc", cuoi)
        self.assertNotIn("T3-đăng-nhập-Google", cuoi)
        self.assertIn("OpenAI gốc", cuoi)

    def test_T0_biet_van_con_duong_de_thu(self):
        """Thiếu chỗ này thì T0 tuyên bố 'cần đăng nhập tay' trước khi máy kịp thử."""
        self.assertTrue(self.ar.con_tang_trinh_duyet(EMAIL, "free"))


class KhoCredentialTraDuocTheoTenHoSo(unittest.TestCase):
    """`resolve_account` của solver: tên hồ sơ ↔ địa chỉ có dấu '+'."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db = os.path.join(self._tmp.name, "accounts.db")
        os.environ["ACCOUNTS_DB"] = db
        from src import accounts_db as adb
        self.adb = adb
        self._vá = mock.patch.object(adb, "_DB_PATH", db)
        self._vá.start()
        adb.init_db()
        adb.save_account(EMAIL, "mat-khau-openai", "hat-giong", "", adb.LOAI_OPENAI)
        adb.save_account("benbap2011@gmail.com", "mat-khau-google", "", "",
                         adb.LOAI_GOOGLE)

    def tearDown(self):
        self._vá.stop()
        self._tmp.cleanup()

    def test_tim_ra_mat_khau_tu_ten_ho_so_openai(self):
        acct = self.adb.resolve_account(HO_SO_OPENAI)
        self.assertIsNotNone(acct, "hồ sơ openai-… phải tra ra bản ghi kho openai")
        self.assertEqual(acct["email"], EMAIL)
        self.assertEqual(acct["password"], "mat-khau-openai")

    def test_khong_lay_nham_sang_kho_google(self):
        """Hồ sơ `google-…` cùng localpart KHÔNG được trả về mật khẩu OpenAI."""
        self.assertIsNone(self.adb.resolve_account(HO_SO_GOOGLE))

    def test_tai_khoan_google_van_tra_binh_thuong(self):
        acct = self.adb.resolve_account("google-benbap2011")
        self.assertIsNotNone(acct)
        self.assertEqual(acct["password"], "mat-khau-google")

    def test_profile_trung_localpart_thi_khong_chon_dai_credential(self):
        """a+b, a-b, a.b cùng ra a-b trên tên profile: phải từ chối khi mơ hồ."""
        self.adb.save_account("a+b@example.com", "mat-khau-cong", "", "",
                              self.adb.LOAI_OPENAI)
        self.adb.save_account("a-b@example.com", "mat-khau-gach", "", "",
                              self.adb.LOAI_OPENAI)

        self.assertIsNone(self.adb.resolve_account("openai-a-b"))


class GoiDungEndpointCuaSolver(unittest.TestCase):
    """`_cgf_openai` đọc đúng câu trả lời của `GET /v1/chatgpt/{ho_so}/refresh-jwt`."""

    def setUp(self):
        from services import account_recovery as ar
        self.ar = ar
        self.da_ghi: list[tuple] = []
        self.vá = [
            mock.patch.object(ar, "_solver_cfg", lambda: ("http://solver:8010", "khoa")),
            mock.patch.object(ar, "_cgf_ghi_pool",
                              lambda token, email, profile, nguon:
                              (self.da_ghi.append((token, profile, nguon)) or token)),
        ]
        for v in self.vá:
            v.start()

    def tearDown(self):
        for v in self.vá:
            v.stop()

    def _tra_loi(self, d: dict):
        con = mock.Mock()
        con.json.return_value = d
        return mock.patch("requests.get", return_value=con)

    def test_quet_duoc_phien_thi_lay_token(self):
        with self._tra_loi({"ok": True, "method": "scrape",
                            "access_token": "eyJ-token"}) as g:
            self.assertEqual(self.ar._cgf_openai(HO_SO_OPENAI, EMAIL), "eyJ-token")
        duong_dan = g.call_args[0][0]
        self.assertEqual(duong_dan,
                         f"http://solver:8010/v1/chatgpt/{HO_SO_OPENAI}/refresh-jwt")
        self.assertEqual(self.da_ghi, [("eyJ-token", HO_SO_OPENAI, "scrape")])

    def test_dang_nhap_lai_bang_luong_openai_cung_duoc_tinh_la_xong(self):
        with self._tra_loi({"ok": True, "method": "relogin-openai",
                            "access_token": "eyJ-moi"}):
            self.assertEqual(self.ar._cgf_openai(HO_SO_OPENAI, EMAIL), "eyJ-moi")

    def test_that_bai_thi_giu_lai_LY_DO_cua_solver(self):
        """Không có lý do thì tin báo cuối lại là một câu đoán mò."""
        with self._tra_loi({"ok": False, "error": "Cần mã 2FA nhập tay"}):
            self.assertEqual(self.ar._cgf_openai(HO_SO_OPENAI, EMAIL), "")
        self.assertIn("Cần mã 2FA nhập tay",
                      self.ar.ly_do_dang_nhap_cuoi(HO_SO_OPENAI))
        self.assertEqual(self.da_ghi, [])

    def test_loi_mang_khong_bi_nuot(self):
        with mock.patch("requests.get", side_effect=OSError("mất mạng")):
            self.assertEqual(self.ar._cgf_openai(HO_SO_OPENAI, EMAIL), "")
        self.assertIn("mất mạng", self.ar.ly_do_dang_nhap_cuoi(HO_SO_OPENAI))


if __name__ == "__main__":
    unittest.main()
