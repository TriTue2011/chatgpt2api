"""Khôi phục Codex nhiều tầng: đúng thứ tự, đúng phân loại, không bỏ tầng nào oan.

Thang tầng (người vận hành chốt 30/07):
  T1  refresh_token — như cũ.
  T2  mở đăng nhập Codex trong workspace của tài khoản đó (ride session Google
      của profile) rồi authorize lại.
  T3  đăng nhập lại tài khoản:
        · KHÔNG có dòng trong `codex_auto_list` → là tài khoản Google → dùng đúng
          nút "Chỉ đăng nhập" (auto-login-saved: mật khẩu + TOTP trong solver),
          xong quay lại T2 để lấy token;
        · CÓ dòng → tài khoản đăng nhập hàng loạt → chạy lại đúng luồng hàng loạt
          nhưng chỉ với dòng của tài khoản đang lỗi.

Đo thật 30/07 (smarthomebanbap2011@gmail.com, dead:periodic_scan) — ba lỗi nối
nhau làm cả thang thành vô ích:

  1. Vì `reason` chứa chữ "dead", code bỏ qua T2 và đăng nhập Google trước. Mà
     scheduler LUÔN gửi reason "dead:…" → T2 chưa bao giờ chạy từ đường quét.
  2. auto_login mở profile ra thì trang đã ở `myaccount.google.com` — TỨC LÀ ĐANG
     ĐĂNG NHẬP — nhưng vòng email cứ dò ô email suốt 176 lần/180s rồi kết luận
     "BotGuard chặn gắt" và raise. Vòng MẬT KHẨU (có sẵn nhánh "đã đăng nhập
     sẵn", có lặp 'Thử lại' + nhập lại email 300s) nằm ngay sau đó, không bao giờ
     được chạy tới.
  3. Một verdict "Google login failed" sai đó chặn nốt các tầng còn lại, và người
     vận hành nhận thông báo "Google TỪ CHỐI trình duyệt tự động (BotGuard)" —
     sai nguyên nhân, sai cả việc cần làm.

Test đọc mã nguồn (bỏ dòng chú thích trước khi soi — chú thích của bản vá nhắc
lại hành vi cũ để giải thích): thứ cần khoá là các QUYẾT ĐỊNH rẽ nhánh, nằm gọn
trong vài dòng; dựng Playwright + Google giả cho việc này là đổi phép đo chắc
chắn lấy phép đo phụ thuộc mock. Riêng phân loại tài khoản là hàm thuần → test
thật, gọi hàm.
"""
from __future__ import annotations

import pathlib
import unittest

GOC = pathlib.Path(__file__).resolve().parents[1]


def _code(p: pathlib.Path) -> str:
    return "\n".join(l for l in p.read_text("utf-8").splitlines()
                     if not l.lstrip().startswith("#"))


class TestOnboardNhanRaNgoCut(unittest.TestCase):
    """codex_google_onboard phải xử lý màn /signin/rejected."""

    def setUp(self):
        self.code = _code(GOC / "captcha-solver" / "src" / "codex_google_onboard.py")

    def test_co_nhanh_rejected(self):
        self.assertIn('"/signin/rejected" in url', self.code)

    def test_bam_thu_lai_chu_khong_chi_doc_man_hinh(self):
        i = self.code.index('"/signin/rejected" in url')
        khuc = self.code[i:i + 1500]
        self.assertIn('has-text("Thử lại")', khuc)

    def test_qua_4_lan_thi_dung_han_voi_ly_do_ro(self):
        i = self.code.index('"/signin/rejected" in url')
        khuc = self.code[i:i + 1500]
        self.assertIn("rejected_tries > 4", khuc)
        self.assertIn('"state": "failed"', khuc)
        self.assertIn("từ chối trình duyệt", khuc)

    def test_bien_dem_duoc_khoi_tao(self):
        self.assertIn("rejected_tries = 0", self.code)


class TestBuocEmailKhongChetOan(unittest.TestCase):
    """auto_login: bước email không được kết luận thất bại — nó chỉ là bước đầu."""

    def setUp(self):
        self.code = _code(GOC / "captcha-solver" / "src" / "auto_login.py")

    def test_khong_con_6_lan_chop_nhoang(self):
        self.assertNotIn("for _retry in range(6)", self.code)

    def test_dung_deadline(self):
        self.assertIn("_email_deadline = time.time() + 90", self.code)
        self.assertIn("while time.time() < _email_deadline", self.code)

    def test_dang_nhap_san_la_THANH_CONG_ngay_o_buoc_email(self):
        """Trang ở myaccount.google.com = đã đăng nhập = đích của "Chỉ đăng nhập".
        Nhánh này phải nằm TRONG vòng email, trước cả phần dò BotGuard."""
        i = self.code.index("_email_deadline = time.time() + 90")
        khuc = self.code[i:i + 1200]
        self.assertIn("_already_logged_in(ctx)", khuc)
        j = khuc.index("_already_logged_in(ctx)")
        self.assertIn('session.state = "success"', khuc[j:j + 400])

    def test_het_gio_buoc_email_KHONG_raise(self):
        """Bản cũ raise "email field not found" → chết trước vòng mật khẩu."""
        self.assertNotIn("email field not found", self.code)
        i = self.code.index("if not email_success:")
        khuc = self.code[i:i + 900]
        self.assertNotIn("raise", khuc)
        self.assertIn("chuyển sang vòng mật khẩu kiên trì", khuc)

    def test_khong_thay_o_nao_thi_LAI_trang_ve_form(self):
        """Đứng chờ ở màn chọn tài khoản thì ô email không tự hiện ra."""
        self.assertIn("async def _ve_lai_form_dang_nhap", self.code)
        khuc = self.code[self.code.index("async def _ve_lai_form_dang_nhap"):][:2400]
        self.assertIn("use another account", khuc)
        self.assertIn("_GOOGLE_SIGNIN_URL", khuc)

    def test_vong_mat_khau_kien_tri_ca_khi_khong_doc_duoc_chu_chan(self):
        """Chỉ thử lại khi ĐỌC ĐƯỢC chữ chặn của BotGuard là chưa đủ: mọi màn hình
        khác đều đứng im hết 300s. Phải nhập lại email / lái về form theo nhịp."""
        i = self.code.index("pwd_deadline = time.time() + 300")
        khuc = self.code[i:i + 3000]
        self.assertIn("stuck_rounds", khuc)
        self.assertIn("_reenter_email()", khuc)
        self.assertIn("_ve_lai_form_dang_nhap()", khuc)

    def test_captcha_thi_khong_pha_trang_cua_nguoi_dung(self):
        """Người đang gõ captcha trên noVNC — không được nhập lại email đè lên."""
        i = self.code.index("stuck_rounds += 1")
        khuc = self.code[max(0, i - 300):i]
        self.assertIn("if not captcha_flagged:", khuc)


class TestPhanLoaiTheoDanhSachHangLoat(unittest.TestCase):
    """Phân loại bằng `codex_auto_list`, KHÔNG bằng đuôi email."""

    def test_ham_doc_dung_dong_cua_email(self):
        import sys
        import types

        from services.account_recovery import _dong_hang_loat

        # Stub `services.config`: hàm chỉ đọc `config.data["codex_auto_list"]`, và
        # import thật kéo theo cả tầng storage/sqlalchemy — không liên quan gì tới
        # việc tách dòng.
        that = sys.modules.get("services.config")
        stub = types.ModuleType("services.config")
        stub.config = types.SimpleNamespace(data={})
        sys.modules["services.config"] = stub
        try:
            stub.config.data = {
                "codex_auto_list": (
                    "acc1@outlook.com|pw1|imap1@gmail.com|ap1\n"
                    "  \n"
                    "hangloat@gmail.com|pw2\n"
                )
            }
            # có dòng → tài khoản đăng nhập hàng loạt
            self.assertEqual(
                _dong_hang_loat("acc1@outlook.com"),
                ["acc1@outlook.com", "pw1", "imap1@gmail.com", "ap1"],
            )
            # Gmail VẪN có thể là tài khoản hàng loạt — đây là ca mà cách phân
            # loại cũ (theo đuôi @gmail.com) làm sai.
            self.assertEqual(_dong_hang_loat("hangloat@gmail.com"),
                             ["hangloat@gmail.com", "pw2"])
            self.assertIsNone(_dong_hang_loat("google@gmail.com"))
            # Workspace (đuôi công ty) không có dòng → là tài khoản Google, chứ
            # không phải "non-Google → chỉ bulk" như bản cũ.
            self.assertIsNone(_dong_hang_loat("nguoi@congty.com"))
            self.assertIsNone(_dong_hang_loat(""))
        finally:
            if that is None:
                sys.modules.pop("services.config", None)
            else:
                sys.modules["services.config"] = that

    def test_khong_con_phan_loai_theo_duoi_email(self):
        code = _code(GOC / "services" / "account_recovery.py")
        self.assertNotIn("_is_google_email", code)
        self.assertNotIn('endswith("@gmail.com")', code)


class TestThuTuTang(unittest.TestCase):
    """account_recovery: T2 trước T3, và không bỏ tầng nào vì một verdict sai."""

    def setUp(self):
        self.code = _code(GOC / "services" / "account_recovery.py")

    def test_T2_workspace_dung_TRUOC_T3_dang_nhap_lai(self):
        """So CHỖ GỌI, không so chỗ định nghĩa hàm."""
        self.assertLess(self.code.index('_do_reuse("T2-workspace"'),
                        self.code.index("if _do_freshen():"))

    def test_khong_con_bo_qua_T2_vi_reason_co_chu_dead(self):
        """`google_first` cũ bật lên với MỌI reason của scheduler ("dead:…")."""
        self.assertNotIn("google_first", self.code)
        self.assertNotIn("session_dead", self.code)

    def test_sau_T3_phai_lam_lai_T2(self):
        i = self.code.index("if _do_freshen():")
        khuc = self.code[i:i + 500]
        self.assertIn("T2-sau-T3", khuc)

    def test_dang_nhap_hang_loat_chi_chay_khi_co_dong(self):
        """Không có dòng thì đừng gọi — bản cũ luôn gọi rồi báo thất bại chung."""
        self.assertIn("can_batch = bool(batch and hang_loat)", self.code)

    def test_ngan_sach_chua_du_ca_thang(self):
        """Trần thời gian phải lớn hơn một lượt đăng nhập Google (~390s), nếu
        không tầng cuối bị chặt giữa đường."""
        import re
        m = re.search(r"_RECOVER_BUDGET_S = ([\d.]+)", self.code)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(float(m.group(1)), 600.0)

        sched = _code(GOC / "services" / "codex_error_recovery_scheduler.py")
        m2 = re.search(r"_PER_ACCOUNT_TIMEOUT_S = ([\d.]+)", sched)
        self.assertIsNotNone(m2)
        self.assertGreaterEqual(float(m2.group(1)), float(m.group(1)))


class TestLogOkNoiThat(unittest.TestCase):
    def test_dead_recovery_ok_noi_ro_nho_dau(self):
        code = _code(GOC / "services" / "codex_error_recovery_scheduler.py")
        i = code.index('"tier": "T1-T3"')
        khuc = code[i:i + 400]
        self.assertIn("token active KHÁC", khuc)


if __name__ == "__main__":
    unittest.main()
