"""Khôi phục Codex: Google login hỏng thì DỪNG, không cầm session chết đi thử tiếp.

Đo thật 30/07 (smarthomebanbap2011@gmail.com, dead:periodic_scan):

  T2  BotGuard chặn ngay bước email; code bấm "Thử lại" đúng 1 lần trong ~12s
      rồi chết CÂM — không một dòng nào ra docker logs, chỉ ai poll status mới
      thấy "email field not found".
  T1  cầm session Google ĐÃ CHẾT sang OpenAI → Google trả /signin/rejected
      ("trình duyệt không an toàn"); vòng lặp đọc màn hình 8s/lần suốt 120s,
      KHÔNG bấm nút "Thử lại" có sẵn, không nhận ra ngõ cụt.
  T3  bulk với Gmail cũng đi "Tiếp tục với Google" → đúng bức tường đó.
  Rồi scheduler ghi `dead_recovery_ok` NGAY SAU `recover_failed` — vì email còn
  một token active KHÁC trong pool, không phải vì khôi phục thành công.

Người vận hành chốt quy trình đúng: đăng nhập tài khoản Google XONG rồi mới
đăng nhập Codex lấy token; Google hỏng thì các tầng sau đều vô ích ("sai cách
refresh nhiều tầng").

Test đọc mã nguồn (bỏ dòng chú thích trước khi soi — chú thích của bản vá nhắc
lại hành vi cũ để giải thích): thứ cần khoá là các QUYẾT ĐỊNH rẽ nhánh, nằm gọn
trong vài dòng; dựng Playwright + Google giả cho việc này là đổi phép đo chắc
chắn lấy phép đo phụ thuộc mock.
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


class TestBuocEmailKienNhan(unittest.TestCase):
    """auto_login: bước email phải kiên nhẫn như bước mật khẩu, và không chết câm."""

    def setUp(self):
        self.src = (GOC / "captcha-solver" / "src" / "auto_login.py").read_text("utf-8")
        self.code = "\n".join(l for l in self.src.splitlines()
                              if not l.lstrip().startswith("#"))

    def test_khong_con_6_lan_chop_nhoang(self):
        self.assertNotIn("for _retry in range(6)", self.code)

    def test_dung_deadline(self):
        self.assertIn("_email_deadline = time.time() + 180", self.code)
        self.assertIn("while time.time() < _email_deadline", self.code)

    def test_botguard_o_buoc_email_co_ra_logger(self):
        """Chết câm là thứ vừa tốn 20 phút chẩn đoán — phải để lại dấu."""
        self.assertIn("BotGuard chặn ở bước email", self.code)

    def test_that_bai_ghi_ca_man_hinh_dang_thay(self):
        i = self.code.index("bước email THẤT BẠI")
        khuc = self.code[max(0, i - 800):i + 400]
        self.assertIn("page.url", khuc)
        self.assertIn("logger.warning", khuc)


class TestKhongNhieuTangVoIch(unittest.TestCase):
    """account_recovery: Google login hỏng → dừng, không T1/T3 cho Gmail."""

    def setUp(self):
        self.code = _code(GOC / "services" / "account_recovery.py")

    def test_google_first_hong_thi_khong_ride_session_chet(self):
        """Bản cũ: freshen trượt → "vẫn thử ride session cũ (may ra)". Đo thật:
        may ra = signin/rejected + 120 giây. Nhánh đó phải biến mất."""
        i = self.code.index("google_first")
        khuc = self.code[i:i + 2500]
        self.assertIn("google_login_failed = True", khuc)

    def test_gmail_login_hong_thi_chan_T3(self):
        i = self.code.index("if is_google and google_login_failed:")
        khuc = self.code[i:i + 1200]
        self.assertIn("return", khuc)
        # Thông báo phải chỉ đúng việc cần làm: đăng nhập tay qua noVNC.
        self.assertIn("noVNC", khuc)
        self.assertIn("6080", khuc)

    def test_chan_T3_dung_TRUOC_khoi_batch(self):
        self.assertLess(self.code.index("if is_google and google_login_failed:"),
                        self.code.index("tried.append(\"T3-batch\")"))

    def test_khong_phai_gmail_van_con_T3(self):
        """T3 là đường BẮT BUỘC cho account không phải Gmail — không được chặn."""
        i = self.code.index('tried.append("T3-batch")')
        khuc = self.code[max(0, i - 600):i]
        self.assertIn("if batch and time.time() - started < budget", khuc)


class TestLogOkNoiThat(unittest.TestCase):
    def test_dead_recovery_ok_noi_ro_nho_dau(self):
        code = _code(GOC / "services" / "codex_error_recovery_scheduler.py")
        i = code.index('"tier": "T1-T3"')
        khuc = code[i:i + 400]
        self.assertIn("token active KHÁC", khuc)


if __name__ == "__main__":
    unittest.main()
