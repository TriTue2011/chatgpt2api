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


class TestKienTriNhuChiDangNhap(unittest.TestCase):
    """auto_login: MỘT vòng kiên trì — Thử lại → bấm lại vào mail → dò ô mật khẩu.

    Đúng thao tác người dùng lặp khi bấm "Chỉ đăng nhập". Hai thứ bị cấm ở đây:
    cắt bớt số lần thử, và thêm bước không có trong luồng đó (ví dụ tự bấm "Sử
    dụng một tài khoản khác" — bấm là rời màn chọn tài khoản, hết đường bấm lại
    vào mail).
    """

    def setUp(self):
        self.code = _code(GOC / "captcha-solver" / "src" / "auto_login.py")

    def test_khong_con_6_lan_chop_nhoang(self):
        self.assertNotIn("for _retry in range(6)", self.code)

    def test_mot_vong_duy_nhat_du_dai(self):
        """Không còn hai vòng ngân sách riêng; vòng duy nhất phải đủ ~100 lượt."""
        import re
        self.assertNotIn("_email_deadline", self.code)
        m = re.search(r"_VAO_O_MAT_KHAU_S = ([\d.]+)", self.code)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(float(m.group(1)), 420.0)
        self.assertIn("pwd_deadline = time.time() + _VAO_O_MAT_KHAU_S", self.code)

    def test_thu_lai_XONG_thi_bam_lai_vao_mail(self):
        """Bấm 'Thử lại' rồi phải bấm lại vào mail như lần đầu — nếu không thì
        vẫn đứng ở màn chặn và chẳng bao giờ tới ô mật khẩu."""
        i = self.code.index("await _click_try_again()")
        khuc = self.code[i:i + 700]
        self.assertIn("_bam_lai_vao_mail()", khuc)

    def test_bam_lai_vao_mail_MOI_VONG_khong_gian_nhip(self):
        """Không có `% 2`/`% 3` nào chặn bớt nhịp bấm vào mail."""
        i = self.code.index("if await _bam_lai_vao_mail():")
        khuc = self.code[max(0, i - 400):i]
        self.assertNotIn("%", khuc.split("await asyncio.sleep")[-1])

    def test_bam_lai_vao_mail_uu_tien_tile_roi_moi_den_o_email(self):
        i = self.code.index("async def _bam_lai_vao_mail")
        khuc = self.code[i:i + 2600]
        self.assertIn("data-identifier", khuc)
        self.assertLess(khuc.index("data-identifier"), khuc.index('input[type="email"]'))

    def test_khong_tu_them_buoc_dung_tai_khoan_khac(self):
        """Bước này KHÔNG có trong luồng "Chỉ đăng nhập" — đã bỏ hẳn."""
        self.assertNotIn("_ve_lai_form_dang_nhap", self.code)
        self.assertNotIn("use another account", self.code)

    def test_dang_nhap_san_la_THANH_CONG(self):
        """Trang ở myaccount.google.com = đã đăng nhập = đích của "Chỉ đăng nhập",
        phải xong NGAY, không dò ô mật khẩu cho hết giờ rồi báo BotGuard oan."""
        i = self.code.index("pwd_deadline = time.time() + _VAO_O_MAT_KHAU_S")
        khuc = self.code[i:i + 1200]
        self.assertIn("_already_logged_in(ctx)", khuc)
        j = khuc.index("_already_logged_in(ctx)")
        self.assertIn('session.state = "success"', khuc[j:j + 400])

    def test_khong_con_raise_o_buoc_email(self):
        self.assertNotIn("email field not found", self.code)

    def test_captcha_thi_khong_pha_trang_cua_nguoi_dung(self):
        """Người đang gõ captcha trên noVNC — không bấm/điền gì đè lên."""
        i = self.code.index('captcha_flagged = True')
        khuc = self.code[i:i + 400]
        self.assertIn("if captcha_flagged:", khuc)
        self.assertIn("continue", khuc)

    def test_that_bai_noi_ro_da_thu_bao_nhieu_lan(self):
        i = self.code.index("Không lọt được ô mật khẩu")
        khuc = self.code[i:i + 400]
        self.assertIn("block_retries", khuc)
        self.assertIn("tile_clicks", khuc)


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


class TestXongViecThiDongTab(unittest.TestCase):
    """Onboard xong (thành công hay thất bại) phải đóng browser ngay.

    Đo thật 30/07: tầng 2 xong lúc 21:00:33 nhưng tab vẫn mở, phải chờ
    browser_pool tự dọn khi rỗi (~5 phút) — nhiều tài khoản thì đó là vài trình
    duyệt ngồi không trên Xvfb. Các luồng khác (auto_login, chatgpt, gemini,
    claude, onboard hàng loạt) đều đã đóng; chỉ codex_google_onboard bỏ sót.
    """

    def test_codex_google_onboard_dong_browser(self):
        code = _code(GOC / "captcha-solver" / "src" / "codex_google_onboard.py")
        self.assertIn("finally:", code)
        i = code.index("finally:")
        self.assertIn("pool.close_profile(req.profile)", code[i:i + 600])

    def test_moi_luong_onboard_deu_co_dong(self):
        goc = GOC / "captcha-solver" / "src"
        for ten in ("auto_login", "chatgpt_login", "gemini_web_login",
                    "claude_web_login", "codex_google_onboard",
                    "github_codex_onboard"):
            with self.subTest(luong=ten):
                self.assertIn("close_profile", _code(goc / f"{ten}.py"))


class TestKhongBaoLoiOanKhiDaLayDuocToken(unittest.TestCase):
    """Đua đổi code với listener :1455 — thua cuộc đua KHÔNG phải là thất bại.

    Trình duyệt chạy cùng container nên khi nó đi tới localhost:1455/auth/callback
    thì listener đổi code trước; state dùng-một-lần nên lần đổi thứ hai của ta
    ném ValueError. Đo thật 30/07: token mới ĐÃ vào pool, account về active, mà
    lượt khôi phục vẫn bị ghi `dead_recovery_t13_error` và báo ❌.
    """

    def setUp(self):
        self.code = _code(GOC / "services" / "account_recovery.py")

    def test_loi_doi_code_khong_thoat_ra_ngoai(self):
        i = self.code.index("def _codex_exchange_from_redirect")
        khuc = self.code[i:i + 1600]
        self.assertIn("try:", khuc)
        self.assertIn("except Exception", khuc)
        # exchange phải nằm TRONG try
        self.assertLess(khuc.index("try:"), khuc.index("exchange_codex_code(code, st)"))

    def test_phan_xu_bang_token_trong_pool(self):
        """Sau khi đổi code, kết luận dựa trên CÓ TOKEN DÙNG ĐƯỢC hay không."""
        self.assertIn("def _cho_token_song", self.code)
        for ham in ("_codex_reuse", "_codex_batch"):
            i = self.code.index(f"def {ham}")
            khuc = self.code[i:self.code.index("def ", i + 10) if "def " in self.code[i + 10:] else len(self.code)]
            self.assertIn("_cho_token_song(email)", khuc, f"{ham} phải chờ token")

    def test_cho_lai_vai_nhip_vi_doi_code_xong_sau(self):
        """onboard trả về NGAY khi bắt được request callback — hỏi pool đúng một
        lần là dễ hụt."""
        i = self.code.index("def _cho_token_song")
        khuc = self.code[i:i + 900]
        self.assertIn("time.sleep", khuc)
        self.assertIn("for lan in range(so_lan)", khuc)


class TestLogOkNoiThat(unittest.TestCase):
    def test_dead_recovery_ok_noi_ro_nho_dau(self):
        code = _code(GOC / "services" / "codex_error_recovery_scheduler.py")
        i = code.index('"tier": "T1-T3"')
        khuc = code[i:i + 400]
        self.assertIn("token active KHÁC", khuc)


class TestTaiKhoanBiVoHieuHoa(unittest.TestCase):
    """Đường T2 (tài khoản Google) phải nhận ra `AccountDeactivated`.

    Đo thật 02/08 (benbap2011@gmail.com): OpenAI đã xóa tài khoản, nên sau khi
    bấm "Tiếp tục với Google" là sang thẳng auth.openai.com/error — Google
    không hề trục trặc (đăng nhập lại xong trong 8 giây). Nhưng vòng lặp onboard
    không biết trang đó là ngõ cụt: nó chụp lại đúng một trang chết 1,2s/lần
    suốt 131 giây rồi trả "no callback; stuck at …". Chuỗi vô danh đó khiến:
      · `handle_deactivated` không chạy → account giữ status 'error' → lượt quét
        định kỳ lôi ra thử lại mỗi 2 tiếng, vô tận;
      · thông báo rơi vào nhánh gợi ý chung → "Kiểm tra profile Google + mật
        khẩu/TOTP", sai hướng hoàn toàn.
    Nhánh hàng loạt (T3) đã bắt `account_deactivated` từ trước; đường Google thì
    chưa — test này khoá cả hai đầu lại.
    """

    def test_giai_ma_payload_lay_kind(self):
        """Hàm thuần → gọi thật. Payload hỏng phải trả "" chứ không nổ."""
        import ast
        import base64
        import json

        src = (GOC / "captcha-solver" / "src" / "codex_google_onboard.py").read_text("utf-8")
        fn = next(n for n in ast.parse(src).body
                  if isinstance(n, ast.FunctionDef) and n.name == "_openai_error_kind")
        ns: dict = {}
        exec(ast.get_source_segment(src, fn), ns)
        kind = ns["_openai_error_kind"]

        that = base64.urlsafe_b64encode(json.dumps(
            {"kind": "AccountDeactivated", "requestId": "5c81b234"}).encode()).decode()
        self.assertEqual(kind(f"https://auth.openai.com/error?payload={that}"),
                         "AccountDeactivated")
        self.assertEqual(kind("https://auth.openai.com/error"), "")
        self.assertEqual(kind("https://auth.openai.com/error?payload=%%%"), "")

    def test_onboard_dung_ngay_o_trang_loi(self):
        code = _code(GOC / "captcha-solver" / "src" / "codex_google_onboard.py")
        i = code.index('"auth.openai.com/error" in url')
        khuc = code[i:i + 900]
        self.assertIn('"error_code": "account_deactivated"', khuc)
        self.assertIn('"state": "failed"', khuc)
        # Không đọc được payload thì còn đối chiếu chữ trên trang (VN + EN).
        self.assertIn("đã bị xóa hoặc vô hiệu hóa", khuc)
        self.assertIn("has been deleted or deactivated", khuc)
        # Phải nằm TRƯỚC vòng chờ callback, nếu không vẫn đốt hết ngân sách.
        self.assertLess(i, code.index("no callback; stuck at"))

    def test_t2_bao_deactivated_giong_nhanh_hang_loat(self):
        code = _code(GOC / "services" / "account_recovery.py")
        i = code.index("def _codex_reuse")
        khuc = code[i:code.index("def ", i + 10)]
        self.assertIn("account_deactivated", khuc)
        self.assertIn("handle_deactivated(", khuc)
        self.assertIn("raise CodexAccountDeactivated(email)", khuc)

    def test_khong_bao_that_bai_chung_chung_nua(self):
        """Nhánh Google phải nuốt CodexAccountDeactivated và return — để không
        gửi tiếp "KHÔNG tự khôi phục được" đè lên thông báo ⛔ vừa gửi."""
        code = _code(GOC / "services" / "account_recovery.py")
        i = code.index("if can_google:")
        khuc = code[i:code.index("tried_s = ", i)]
        self.assertIn("except CodexAccountDeactivated:", khuc)
        self.assertIn("recover_stop_deactivated", khuc)
        self.assertIn("return", khuc[khuc.index("except CodexAccountDeactivated:"):])


if __name__ == "__main__":
    unittest.main()
