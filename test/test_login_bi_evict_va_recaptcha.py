"""Lượt đăng nhập Google bị chính máy mình cắt ngang, và trang reCAPTCHA không ai nhận ra.

SỰ CỐ 24/08/2026. Chủ máy nhận đúng chuỗi này, hai lần:

    ⚠️ Flow — google-benbap2011  Lỗi: quét định kỳ: mất phiên labs.google
    🔧 [T1] mất phiên → [T2] đang đăng nhập lại tài khoản Google…
    ❌ KHÔNG tự khôi phục được. Cần đăng nhập lại tay (noVNC cổng 6080).

Log máy chủ cùng lượt đó:

    15:26:30 RuntimeError: Could not find 'Dự án mới' … (page:
             https://accounts.google.com/v3/signin/challenge/recaptcha?TL=…)
    15:26:39 opened context profile=google-benbap2011 headless=False
    15:26:45 Google chặn — bấm Thử lại lần 1
    15:31:41 bấm lại vào mail lần 135          ← 135 lần trong 5 phút
    15:31:51 auto-evicting idle profile=google-benbap2011   ← ĐÓNG TRÌNH DUYỆT
    15:33:46 closed browser after onboard state=failed
             recover_failed provider=flow profile=google-benbap2011

BA LỖI CHỒNG NHAU

1. `_eviction_loop` của pool đóng trình duyệt của lượt đăng nhập ĐANG chạy.
   `auto_login` gọi `pool.get()` đúng một lần rồi lái trang suốt 420 giây mà
   không chạm lại pool, nên `last_used` đứng im từ giây đầu → tới phút thứ 5
   hồ sơ trông y hệt một tab bỏ quên. Hai phút cuối lái một trang đã đóng, mọi
   thao tác ném lỗi rồi bị nuốt. `close_profile` đã có cờ `bo_qua_khi_dang_nhap`
   đúng để tránh chuyện này — vòng quét nhàn rỗi thì chưa bao giờ hỏi cờ đó.

2. Trang thử thách reCAPTCHA không được nhận ra là "cần người".
   `_CAPTCHA_SELECTORS` chỉ biết captcha ẢNH đời cũ (`img#captchaimg`), còn
   `/v3/signin/challenge/recaptcha` để captcha trong iframe. Không ai gắn cờ
   `need_captcha` nên vòng lặp quay hết ngân sách rồi đổ cho "Google chặn" —
   trong khi việc cần làm chỉ là một người gõ captcha trên noVNC.

3. Tin báo không nói lý do. "KHÔNG tự khôi phục được" gộp chung ba tình huống
   xử lý khác hẳn nhau: Google bắt captcha (ra noVNC gõ một lần), thiếu TOTP
   (thêm TOTP), solver lỗi mạng (không cần làm gì). Nhánh khôi phục nhiều tầng
   đã nói đúng lý do từ 30/07; riêng nhánh Flow thì chưa.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))

NGUON_POOL = (GOC / "captcha-solver/src/browser_pool.py").read_text(encoding="utf-8")
NGUON_LOGIN = (GOC / "captcha-solver/src/auto_login.py").read_text(encoding="utf-8")
NGUON_FLOW = (GOC / "captcha-solver/src/solvers/flow_google.py").read_text(encoding="utf-8")


def _than(nguon: str, tu: str, den: str) -> str:
    i = nguon.index(tu)
    return nguon[i:nguon.index(den, i)]


class EvictKhongDungVaoLuotDangNhapTests(unittest.TestCase):
    """Vòng quét nhàn rỗi phải hỏi cờ `dang_dang_nhap` trước khi đóng."""

    THAN = _than(NGUON_POOL, "async def _eviction_loop", "def _profile_dir")

    def test_bo_qua_ho_so_dang_dang_nhap(self):
        self.assertIn("dang_dang_nhap", self.THAN,
                      "vòng evict không hỏi cờ đăng nhập → đóng trình duyệt "
                      "giữa lượt đăng nhập, đúng lỗi 24/08/2026")

    def test_hoi_co_TRUOC_khi_xep_vao_danh_sach_dong(self):
        vi_tri_co = self.THAN.index("dang_dang_nhap")
        vi_tri_xep = self.THAN.index("to_evict.append")
        self.assertLess(vi_tri_co, vi_tri_xep,
                        "phải loại hồ sơ đang đăng nhập ra từ lúc gom danh sách")

    def test_kiem_lai_co_ngay_truoc_khi_dong(self):
        """Giữa lúc xếp hàng chờ khoá, một lượt đăng nhập mới có thể vừa bắt đầu."""
        khuc = self.THAN[self.THAN.index("for profile in to_evict"):]
        self.assertIn("dang_dang_nhap", khuc)

    def test_van_giu_nguong_5_phut_cho_tab_bo_quen(self):
        self.assertIn("last_used > 300", self.THAN,
                      "không được nhân tiện bỏ luôn việc dọn tab nhàn rỗi")


class KhongMoChongLenLuotDangNhapTests(unittest.TestCase):
    """`pool.page()` phải coi "đang đăng nhập" là BẬN, trả 429 chứ đừng mở chồng.

    Đo thật 24/08/2026: lượt đăng nhập headful của google-benbap2011 chạy từ
    15:56:40; 16:00:01 một cú bấm "Tái dùng" trên giao diện (get-or-create-project,
    headless) mở tiếp trên đúng hồ sơ đó; 16:03:48 lượt đăng nhập chết. `page()`
    chỉ hỏi khoá hồ sơ — mà `auto_login` nhả khoá ngay sau `get()` rồi mới lái
    trang suốt 420 giây, nên khoá LÚC NÀO CŨNG rảnh trong suốt lượt đăng nhập.
    """

    THAN = _than(NGUON_POOL, "async def page(", "def _attach_model_tracker")

    def test_dang_dang_nhap_cung_la_ban(self):
        cong = _than(self.THAN, "if lock.locked()", "await lock.acquire()")
        self.assertIn("dang_dang_nhap", cong,
                      "chỉ hỏi khoá là chưa đủ: suốt lượt đăng nhập khoá vẫn rảnh")

    def test_tra_429_chu_khong_phai_loi_that(self):
        cong = _than(self.THAN, "if lock.locked()", "await lock.acquire()")
        self.assertIn("429", cong)
        self.assertIn("Account Busy", cong,
                      "429/'ban' để bên gọi xoay sang tài khoản khác; báo lỗi "
                      "thật thì `_flow_session_trang_thai` đọc thành 'mất phiên' "
                      "rồi khôi phục oan một tài khoản đang lành")


class NhanRaTrangThuThachRecaptchaTests(unittest.TestCase):
    """`/challenge/recaptcha` = cần người, bỏ ngay; không phải 'Google chặn'."""

    THAN = _than(NGUON_LOGIN, "_CAPTCHA_SELECTORS = ", "if pwd_input is None:")

    def test_co_bo_nhan_dien_theo_duong_dan(self):
        self.assertIn("/challenge/recaptcha", self.THAN,
                      "chỉ dò `img#captchaimg` thì trang thử thách reCAPTCHA "
                      "không bao giờ bị bắt")

    def test_gan_co_need_captcha_chu_khong_phai_failed(self):
        # Cắt tới đúng ranh giới câu lệnh kế tiếp, KHÔNG đếm ký tự: cửa sổ cố
        # định là một con số tình cờ, thêm vài dòng chú thích là test đỏ oan.
        nhanh = _than(self.THAN, "any(p in url_hien for p in _CAPTCHA_URL_PATHS)",
                      "body = (await page")
        self.assertIn('"need_captcha"', nhanh,
                      "trạng thái phải là need_captcha — nó nằm trong _CAN_NGUOI "
                      "nên vòng poll bỏ ngay thay vì chờ hết 700 giây")
        self.assertIn("captcha_flagged = True", nhanh,
                      "gắn cờ thì vòng sau mới thôi bấm, để yên trang cho người gõ")

    def test_khong_bat_nham_man_mat_khau_va_2FA(self):
        """`/challenge/pwd` và `/challenge/totp` máy tự đi tiếp được."""
        dong = next(d for d in self.THAN.splitlines() if "_CAPTCHA_URL_PATHS" in d and "=" in d)
        self.assertNotIn("/challenge/pwd", dong)
        self.assertNotIn("/challenge/totp", dong)
        self.assertNotIn('("/challenge/",)', dong)

    def test_nhan_dien_TRUOC_nhanh_bam_thu_lai(self):
        """Thấy captcha thì dừng tay; bấm tiếp chỉ càng giống bot."""
        vi_tri_captcha = self.THAN.index("_CAPTCHA_URL_PATHS")
        vi_tri_bam = self.THAN.index("_BLOCK_TEXTS")
        self.assertLess(vi_tri_captcha, vi_tri_bam)

    def test_ghi_url_vao_log_va_ly_do_that_bai(self):
        """Không có URL trong log thì lần hỏng sau lại phải đoán trang ở đâu."""
        self.assertIn("url=%s", self.THAN)
        loi = _than(NGUON_LOGIN, "Không lọt được ô mật khẩu", "session.completed_at")
        self.assertIn("url=", loi)


class LoiTaiDungPhaiChiDungViecCanLamTests(unittest.TestCase):
    """Dừng ở trang Google thì nói ĐÚNG trang nào, và chỉ đúng nút phải bấm.

    Chủ máy bấm "Tái dùng" và nhận:

        Could not find 'Dự án mới' / 'New project' button (page:
        .../v3/signin/rejected?app_domain=https%3A%2F%2Flabs.google&client_id=…).
        Account may not have Flow access or session is expired.

    rồi nói lại: "chỉ đăng nhập bằng tay tôi bình thường". Đúng — tài khoản
    không thiếu quyền Flow, và cũng không hẳn là "đăng xuất". Log 24/08/2026
    cho thấy chuỗi thật: chooser → bấm tile → `/signin/challenge/pwd` (Google
    hỏi lại mật khẩu cho labs.google) → `_prime_flow_session` chỉ biết BẤM chứ
    không gõ được mật khẩu nên bấm lại tile → Google chốt bằng
    `/signin/rejected`.
    """

    # Hàm dựng câu này chỉ ăn một chuỗi URL nên bóc ra chạy thẳng được — kiểm
    # hành vi thật, không phải kiểm mã nguồn có chứa chữ gì.
    _NS: dict = {}
    exec(compile(_than(NGUON_FLOW, "def _loi_chua_vao_duoc_flow",
                       "async def get_or_create_project"),
                 "flow_google.py", "exec"), _NS)
    _loi = staticmethod(_NS["_loi_chua_vao_duoc_flow"])

    def test_trang_rejected_khong_do_cho_quyen_Flow(self):
        tin = self._loi("https://accounts.google.com/v3/signin/rejected"
                        "?app_domain=https%3A%2F%2Flabs.google&client_id=365941595420")
        self.assertIn("TỪ CHỐI", tin)
        self.assertIn("Chỉ đăng nhập", tin)
        self.assertNotIn("Flow access", tin)

    def test_trang_hoi_mat_khau_noi_dung_ly_do(self):
        tin = self._loi("https://accounts.google.com/v3/signin/challenge/pwd?TL=abc")
        self.assertIn("mật khẩu", tin)
        self.assertIn("Chỉ đăng nhập", tin)

    def test_trang_captcha_van_chi_ra_noVNC(self):
        tin = self._loi("https://accounts.google.com/v3/signin/challenge/recaptcha?TL=abc")
        self.assertIn("reCAPTCHA", tin)
        self.assertIn("6080", tin)
        self.assertIn("màn hình đen", tin,
                      "phải nói vì sao noVNC đen: nút 'Tái dùng' chạy ẩn")

    def test_trang_Google_khac_van_co_cau_tra_loi(self):
        tin = self._loi("https://accounts.google.com/v3/signin/identifier?abc")
        self.assertIn("Chỉ đăng nhập", tin)

    def test_luon_kem_dia_chi_trang_de_con_lan_ra(self):
        for u in ("https://accounts.google.com/v3/signin/rejected?x=1",
                  "https://accounts.google.com/v3/signin/challenge/pwd?x=1",
                  "https://accounts.google.com/v3/signin/identifier?x=1"):
            self.assertIn("accounts.google.com", self._loi(u))


class CoDuAnCuThiDungTaoDuAnMoiTests(unittest.TestCase):
    """"Nếu dự án cũ rồi thì không tạo dự án mới."

    Phép dò cũ quét DOM ĐÚNG MỘT LẦN ngay sau khi prime xong. Danh sách dự án
    render sau, nên "không thấy link /project/ nào" phần lớn là "chưa kịp hiện"
    — mà kết luận đó đi thẳng xuống nhánh bấm "Dự án mới", tức đẻ thêm một dự
    án nữa vào tài khoản đã có sẵn dự án.
    """

    THAN = _than(NGUON_FLOW, "async def get_or_create_project",
                 'raise RuntimeError(\n                f"Could not find')

    def test_do_nhieu_luot_truoc_khi_ket_luan_chua_co_du_an(self):
        self.assertIn("_SO_LUOT_DO_DU_AN", self.THAN)
        so = int(_than(NGUON_FLOW, "_SO_LUOT_DO_DU_AN = ", "\n").split("=")[1])
        self.assertGreaterEqual(so, 2, "một lượt quét DOM là quá sớm")

    def test_dung_lai_du_an_cu_TRUOC_khi_bam_tao_moi(self):
        vi_tri_dung_lai = self.THAN.index('"use_existing"')
        vi_tri_tao_moi = self.THAN.index("dự án mới|new project")
        self.assertLess(vi_tri_dung_lai, vi_tri_tao_moi)

    def test_chua_vao_duoc_Flow_thi_KHONG_bam_tao_moi(self):
        """Trang đăng nhập Google cũng 'không có dự án nào' theo phép dò trên."""
        khuc = self.THAN[self.THAN.index('"use_existing"'):]
        vi_tri_chan = khuc.index("accounts.google.com")
        vi_tri_tao_moi = khuc.index("dự án mới|new project")
        self.assertLess(vi_tri_chan, vi_tri_tao_moi,
                        "phải chặn trước khi bấm tạo mới, không phải sau ba lượt "
                        "bấm hụt + re-prime")


class TinBaoFlowNoiDungLyDoTests(unittest.TestCase):
    """Tin ❌ của Flow phải nói VÌ SAO — ba lý do, ba cách xử lý khác nhau."""

    def _chay(self, *, profile: str, dang_nhap_ok: bool,
              trang_thai_login: str = "", ly_do_login: str = "",
              trang_thai_phien: list[str] | None = None) -> list[str]:
        """Chạy thang thật, trả về danh sách tin đã báo.

        `trang_thai_phien`: trạng thái phiên trả lần lượt cho từng lượt kiểm
        (T0, T1-1, T1-2, T3-1…); hết danh sách thì lặp lại giá trị cuối.
        """
        from services import account_recovery as ar
        ar._last_attempt.pop(f"recover:flow:{profile}", None)
        chuoi = list(trang_thai_phien or ["mat"])
        tin: list[str] = []

        def _tt(_p: str) -> str:
            return chuoi.pop(0) if len(chuoi) > 1 else chuoi[0]

        with mock.patch.object(ar, "_notify", lambda t, d=None: tin.append(t)), \
                mock.patch.object(ar.time, "sleep", lambda *_: None), \
                mock.patch.object(ar, "_flow_session_trang_thai", _tt), \
                mock.patch.object(ar, "_freshen_google", lambda _p, **_k: dang_nhap_ok), \
                mock.patch.object(ar, "trang_thai_dang_nhap_cuoi",
                                  lambda _p: trang_thai_login), \
                mock.patch.object(ar, "ly_do_dang_nhap_cuoi", lambda _p: ly_do_login):
            ar.flow_recover_and_notify(profile, reason="quét định kỳ: mất phiên labs.google")
        self.assertTrue(tin, "phải có tin báo")
        return tin

    def test_captcha_thi_chi_ra_noVNC_go_captcha(self):
        tin = self._chay(profile="google-test-captcha", dang_nhap_ok=False,
                         trang_thai_login="need_captcha")[-1]
        self.assertIn("❌", tin)
        self.assertIn("CAPTCHA", tin)
        self.assertIn("6080", tin)

    def test_thieu_TOTP_thi_noi_thieu_TOTP(self):
        tin = self._chay(profile="google-test-2fa", dang_nhap_ok=False,
                         trang_thai_login="need_code")[-1]
        self.assertIn("TOTP", tin)

    def test_loi_solver_thi_dan_nguyen_ly_do_doc_duoc(self):
        tin = self._chay(profile="google-test-mang", dang_nhap_ok=False,
                         trang_thai_login="error",
                         ly_do_login="ReadTimeout: hết hạn 30s")[-1]
        self.assertIn("ReadTimeout", tin)

    def test_dang_nhap_xong_ma_phien_van_chet_la_chuyen_KHAC(self):
        tin = self._chay(profile="google-test-phien", dang_nhap_ok=True,
                         trang_thai_login="success")[-1]
        self.assertIn("phiên labs.google vẫn chưa lên", tin)
        self.assertNotIn("CAPTCHA", tin)

    def test_khong_bia_ly_do_captcha_khi_dang_nhap_that_su_chay_xong(self):
        """Trạng thái cũ còn sót của lượt trước không được đội lốt lý do lần này."""
        tin = self._chay(profile="google-test-cu", dang_nhap_ok=True,
                         trang_thai_login="need_captcha")[-1]
        self.assertNotIn("CAPTCHA", tin)


class ThangNhieuTangGiongChatGPTTests(unittest.TestCase):
    """Flow cũng phải đi từ tầng rẻ lên tầng đắt, như thang của ChatGPT/Codex.

    Bản cũ chỉ có hai nước: kiểm một lần, trượt là đăng nhập lại ngay. Mà mỗi
    lượt đăng nhập tự động là một lần mời Google bung captcha — tức tự tay đẩy
    tài khoản vào đúng cái bẫy làm nó hết tự chữa được. Trong khi đo thật
    24/08/2026 (google-benbap115): prime trượt lúc 16:02:53, ĐẠT lúc 16:03:55,
    không có gì xen vào giữa — một lần trượt chưa đủ để kết luận mất phiên.
    """

    _chay = TinBaoFlowNoiDungLyDoTests._chay

    def test_T1_cuu_duoc_thi_KHONG_dang_nhap_lai(self):
        from services import account_recovery as ar
        goi = {"n": 0}

        def _freshen(_p, **_k):
            goi["n"] += 1
            return False

        ar._last_attempt.pop("recover:flow:google-test-thang", None)
        tin: list[str] = []
        with mock.patch.object(ar, "_notify", lambda t, d=None: tin.append(t)), \
                mock.patch.object(ar.time, "sleep", lambda *_: None), \
                mock.patch.object(ar, "_freshen_google", _freshen), \
                mock.patch.object(ar, "_flow_session_trang_thai",
                                  mock.Mock(side_effect=["mat", "ok"])):
            ar.flow_recover_and_notify("google-test-thang", reason="quét định kỳ")
        self.assertEqual(goi["n"], 0,
                         "phiên tự lên lại ở T1 thì đừng đăng nhập lại — mỗi lượt "
                         "đăng nhập tự động là một lần mời Google bung captcha")
        self.assertIn("✅", tin[-1])

    def test_bao_da_thu_nhung_tang_nao(self):
        tin = self._chay(profile="google-test-tried", dang_nhap_ok=False,
                         trang_thai_login="failed")[-1]
        self.assertIn("đã thử:", tin)
        self.assertIn("T0", tin)
        self.assertIn("T1", tin)
        self.assertIn("T2", tin)

    def test_dang_nhap_xong_van_kiem_lai_nhieu_luot(self):
        """Một lần kiểm sau đăng nhập là quá sớm — prime chập chờn."""
        from services import account_recovery as ar
        tin = self._chay(profile="google-test-t3", dang_nhap_ok=True,
                         trang_thai_login="success",
                         trang_thai_phien=["mat", "mat", "mat", "mat", "ok"])
        self.assertIn("✅", tin[-1], "lượt kiểm thứ hai sau đăng nhập phải được chạy")
        self.assertGreaterEqual(ar._FLOW_KIEM_LAI, 2)

    def test_ban_giua_chung_thi_hoan_chu_khong_bao_hong(self):
        """Hồ sơ bị việc khác chiếm để tạo ảnh = đang khoẻ, đừng báo ❌."""
        tin = self._chay(profile="google-test-ban-giua", dang_nhap_ok=False,
                         trang_thai_phien=["mat", "ban"])
        self.assertNotIn("❌", tin[-1])
        self.assertIn("bận", tin[-1].lower())

    def test_bao_tin_T2_dung_luc_toi_luot_xep_hang(self):
        """Chờ tới lượt có thể mất hàng chục phút; báo trước là nói sai rằng
        mọi tài khoản đang đăng nhập cùng lúc."""
        from services import account_recovery as ar
        ar._last_attempt.pop("recover:flow:google-test-hang", None)
        tin: list[str] = []

        def _freshen(_p, khi_toi_luot=None):
            if khi_toi_luot is not None:
                khi_toi_luot(180.0)      # nằm chờ 3 phút rồi mới tới lượt
            return False

        with mock.patch.object(ar, "_notify", lambda t, d=None: tin.append(t)), \
                mock.patch.object(ar.time, "sleep", lambda *_: None), \
                mock.patch.object(ar, "_flow_session_trang_thai", lambda _p: "mat"), \
                mock.patch.object(ar, "_freshen_google", _freshen):
            ar.flow_recover_and_notify("google-test-hang", reason="quét định kỳ")
        t2 = [t for t in tin if "[T2]" in t]
        self.assertTrue(t2, "phải có tin của tầng T2")
        self.assertIn("xếp hàng", t2[0],
                      "tin T2 phải phát ra ĐÚNG lúc tới lượt, kèm thời gian đã chờ")


if __name__ == "__main__":
    unittest.main()
