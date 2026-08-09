"""Không đổ lỗi cho Google khi trình duyệt còn chưa mở.

SỰ CỐ 09/08/2026, 22:12–22:21 (giờ Việt Nam), `benbap115@gmail.com`.

Chủ máy nhận tin báo:

    ❌ ChatGPT free — benbap115@gmail.com
    KHÔNG tự khôi phục được (đã thử: T2-workspace → T3-đăng-nhập-Google).
    → Đăng nhập lại Google không vào được ô mật khẩu (Google chặn hoặc đổi
      giao diện) — đăng nhập tay MỘT lần qua noVNC cổng 6080…

rồi bấm tay "Chỉ đăng nhập" cho đúng tài khoản đó lúc 22:23 và vào bình thường
(`state=success` lúc 22:24:27). Google không chặn gì cả.

ĐO ĐƯỢC TRÊN MÁY CHỦ

    22:12:12  recover_start free benbap115 (has_profile+has_google_creds)
    22:12:12  fast-failover profile=google-benbap115 already busy → 429
    22:13:41  chatgpt_login: nuked profile google-benbap115      ← xoá phiên Google
    22:13:49  auto_login: clicked account tile for  on chooser screen   ← email RỖNG
    22:14:00  auto_login: bấm lại vào mail lần 1
    …         (giữ khoá hồ sơ suốt 7 phút rưỡi)
    22:17:12  recover_freshen_failed → recover_failed
    22:21:01  auto-login crashed (page.goto timeout) → mới nhả hồ sơ
    22:23:05  chủ máy bấm tay → 22:24:27 state=success

Và access log của solver KHÔNG có nổi một dòng `POST /v1/session/auto-login-saved`
trong suốt 24 giờ — tầng T3 chưa từng chạy tới nơi.

BỐN LỖI TÁCH BẠCH

1. `pool.close_profile()` chờ khoá hồ sơ VÔ HẠN, mà `start_auto_login` lại gọi nó
   ngay trong handler HTTP. Hồ sơ bận → handler treo, không bao giờ trả lời. Hạn
   120 giây thêm sáng cùng ngày nằm ở `_run_inner`, tức SAU chỗ treo, nên không
   che được đường này.
2. Tầng T2 gọi onboard lần hai với `reuse_session=False` và email/mật khẩu RỖNG:
   nó xoá hồ sơ (mất phiên Google đang sống) rồi chạy một lượt đăng nhập chắc
   chắn hỏng — dò tile so khớp chuỗi rỗng nên bấm trúng phần tử đầu tiên gặp
   được. Tài khoản đi từ "chỉ hỏng token" thành "mất luôn phiên Google".
3. `_freshen_google` bắt `except Exception: return False` trần — timeout, lỗi
   mạng, lỗi JSON đều thành cùng một chữ False, không log, không trạng thái.
4. Nhánh thông báo cuối khẳng định "Google chặn hoặc đổi giao diện" cho MỌI kiểu
   trượt, kể cả khi chưa gửi nổi một request.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))

NGUON_POOL = (GOC / "captcha-solver/src/browser_pool.py").read_text(encoding="utf-8")
NGUON_LOGIN = (GOC / "captcha-solver/src/auto_login.py").read_text(encoding="utf-8")
NGUON_CGPT = (GOC / "captcha-solver/src/chatgpt_login.py").read_text(encoding="utf-8")


def _than(nguon: str, dau: str, cuoi: str) -> str:
    i = nguon.index(dau)
    return nguon[i:nguon.index(cuoi, i)]


def _chi_code(nguon: str) -> str:
    """Bỏ dòng chú thích. Bắt buộc cho các khẳng định 'có gọi kèm tham số X':
    chú thích ở đây thường NHẮC ĐÚNG tên tham số đó, nên nếu không bỏ thì test
    xanh nhờ một câu văn và chẳng gác được dòng code nào (đã dính đúng bẫy này
    khi viết file)."""
    return "\n".join(d for d in nguon.splitlines() if not d.lstrip().startswith("#"))


# ── Lỗi 1: close_profile chờ vô hạn ngay trong handler ───────────────────────

class DongHoSoPhaiCoHan(unittest.TestCase):
    """`close_profile` chờ khoá y như `get()`, nên nó phải có hạn y như `get()`."""

    def setUp(self):
        self.than = _than(NGUON_POOL, "async def close_profile", "def is_loaded")

    def test_nhan_tham_so_han_cho(self):
        self.assertIn("cho_toi_da: float | None = None", self.than)

    def test_het_gio_thi_nem_HoSoDangBan(self):
        self.assertIn("asyncio.wait_for(lock.acquire(), timeout=cho_toi_da)", self.than)
        self.assertIn("raise HoSoDangBan(profile, cho_toi_da)", self.than)

    def test_mac_dinh_van_cho_vo_han(self):
        """Mọi nơi gọi cũ không được đổi hành vi."""
        self.assertIn("if cho_toi_da is None:", self.than)
        self.assertIn("await lock.acquire()", self.than)

    def test_khoa_luon_duoc_nha(self):
        """Bỏ `async with` thì phải tự nhả — không thì hồ sơ kẹt vĩnh viễn, tệ
        hơn hẳn bệnh đang chữa."""
        self.assertIn("finally:", self.than)
        self.assertIn("lock.release()", self.than)

    def test_han_cho_va_nha_khoa_chay_that(self):
        """Kiểm trên đúng nguyên thuỷ mà `close_profile` dùng (không import được
        browser_pool ở máy dev vì thiếu patchright/cloakbrowser)."""
        async def chay():
            khoa = asyncio.Lock()
            await khoa.acquire()                       # việc khác đang giữ
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(khoa.acquire(), timeout=0.05)
            khoa.release()                             # việc kia xong
            await asyncio.wait_for(khoa.acquire(), timeout=0.05)
            self.assertTrue(khoa.locked())
        asyncio.run(chay())


class KhoiDongDangNhapKhongDuocTreo(unittest.TestCase):
    """`start_auto_login` phải trả lời NGAY để bên gọi có phiên mà poll."""

    def setUp(self):
        self.than = _than(NGUON_LOGIN, "async def start_auto_login", "_SIGNIN_URL_MARKERS")

    def test_don_context_co_han(self):
        self.assertIn("pool.close_profile(profile, cho_toi_da=_HAN_DON_CONTEXT_S)", self.than)

    def test_het_gio_khong_phai_loi(self):
        """Hồ sơ bận thì để `_run_inner` chờ có hạn rồi báo lý do đọc được —
        không ném ra ngoài handler."""
        self.assertIn("except HoSoDangBan:", self.than)

    def test_han_don_context_ngan(self):
        import re
        m = re.search(r"_HAN_DON_CONTEXT_S = ([\d.]+)", NGUON_LOGIN)
        self.assertIsNotNone(m)
        self.assertLessEqual(float(m.group(1)), 15.0)

    def test_do_phien_google_cung_co_han(self):
        """`_has_google_session` cũng chạy trong handler và cũng chờ khoá."""
        than = _than(NGUON_CGPT, "async def _has_google_session", "async def start_chatgpt_onboard")
        self.assertIn("cho_toi_da=", than)


# ── Lỗi 2: T2 lần hai xoá hồ sơ rồi đăng nhập bằng thông tin rỗng ────────────

class KhongMatKhauThiCamXoaHoSo(unittest.TestCase):
    """Không có mật khẩu = không tồn tại đường đăng nhập Google mới. Xoá hồ sơ
    lúc đó là phá đúng thứ duy nhất còn dùng được."""

    def setUp(self):
        self.than = _than(NGUON_CGPT, "async def start_chatgpt_onboard", "async def _nuke_profile")

    def test_co_phep_kiem_mat_khau(self):
        self.assertIn("co_mat_khau = bool((password or \"\").strip())", self.than)

    def test_khong_mat_khau_thi_dung_truoc_khi_toi_nuke(self):
        """Nhánh bỏ lượt phải nằm TRƯỚC lệnh xoá — sau thì đã muộn."""
        self.assertLess(self.than.index("elif not co_mat_khau:"),
                        self.than.index("await _nuke_profile(profile)"))

    def test_bo_luot_bang_trang_thai_doc_duoc(self):
        khuc = _than(self.than, "elif not co_mat_khau:", "    else:")
        self.assertIn('session.state = "failed"', khuc)
        self.assertIn("return session", khuc)
        self.assertIn("mật khẩu", khuc)

    def test_co_phien_thi_cuoi_phien_du_goi_khong_xin_reuse(self):
        self.assertIn("(reuse_session or not co_mat_khau) and await _has_google_session",
                      self.than)

    def test_nhanh_xoa_cung_khong_duoc_cho_vo_han(self):
        """Nhánh xoá cũng nằm trong handler HTTP — cùng cái bẫy của lỗi 1. Và hết
        giờ thì DỪNG, không được bỏ qua bước xoá rồi vẫn onboard (là đăng nhập đè
        lên hồ sơ việc khác đang dùng)."""
        khuc = _than(self.than, "# Kill any existing browser context",
                     "await _nuke_profile(profile)")
        self.assertIn("cho_toi_da=_HAN_DONG_HO_SO_S", khuc)
        self.assertIn("except HoSoDangBan", khuc)
        self.assertIn("return session", khuc)


class T2ChiThuMotLuot(unittest.TestCase):
    """Lượt hai `reuse_session=False` không thể thành công (email/mật khẩu rỗng),
    chỉ kịp xoá hồ sơ — đã bỏ hẳn."""

    def setUp(self):
        from services import account_recovery as ar
        import inspect
        self.than = inspect.getsource(ar._cgf_reuse)

    def test_khong_con_vong_hai_luot(self):
        self.assertNotIn("for reuse in (True, False)", self.than)

    def test_luot_duy_nhat_la_reuse(self):
        self.assertIn("_cgf_onboard_once(profile, reuse_session=True)", self.than)


# ── Lỗi 3: nuốt lỗi ở _freshen_google ────────────────────────────────────────

class NuotLoiLaCamKy(unittest.TestCase):

    def _chay_voi_loi(self, loi: Exception):
        from services import account_recovery as ar
        ar._LAST_LOGIN_STATE.pop("google-x", None)
        ar._LAST_LOGIN_NOTE.pop("google-x", None)
        ar._glogin_last_done = 0.0
        with mock.patch.object(ar, "_solver_cfg", return_value=("http://x", "k")), \
             mock.patch("requests.post", side_effect=loi):
            ok = ar._freshen_google("google-x")
        return ok, ar.trang_thai_dang_nhap_cuoi("google-x"), ar.ly_do_dang_nhap_cuoi("google-x")

    def test_timeout_duoc_ghi_lai_chu_khong_bien_mat(self):
        ok, trang_thai, ly_do = self._chay_voi_loi(TimeoutError("read timeout=30"))
        self.assertFalse(ok)
        self.assertEqual(trang_thai, "error")
        self.assertIn("read timeout=30", ly_do)
        self.assertIn("TimeoutError", ly_do)

    def test_khong_con_except_tran(self):
        from services import account_recovery as ar
        import inspect
        than = inspect.getsource(ar._freshen_google)
        i = than.index("except Exception")
        self.assertNotIn("return False", than[i:i + 60].split("\n")[1])

    def test_ly_do_solver_noi_duoc_giu_lai(self):
        """Câu của solver ("Hồ sơ đang bận…", "no saved Google credentials…") là
        thứ có ích nhất — không được vứt."""
        from services import account_recovery as ar
        import inspect
        than = inspect.getsource(ar._freshen_google)
        self.assertIn('d.get("error") or d.get("message")', than)


# ── Lỗi 4: thông báo khẳng định thứ chưa đo ──────────────────────────────────

class ThongBaoChiNoiThuDaDo(unittest.TestCase):
    """Tin nhắn cuối phải mang lý do THẬT, không đoán là Google chặn."""

    def _chay(self, ly_do: str, trang_thai: str = "failed") -> list[str]:
        from services import account_recovery as ar
        ar._last_attempt.clear()
        goi: list[str] = []

        def _freshen_gia(profile: str) -> bool:
            ar._ghi_ket_qua(profile, trang_thai, ly_do)
            return False

        prov = dict(ar._PROVIDERS["free"])
        prov["reuse"] = lambda profile, email: ""     # T2 trượt
        with mock.patch.dict(ar._PROVIDERS, {"free": prov}), \
             mock.patch.object(ar, "_notify", side_effect=lambda t, d=None: goi.append(t)), \
             mock.patch.object(ar, "_dong_hang_loat", return_value=None), \
             mock.patch.object(ar, "_has_profile", return_value=True), \
             mock.patch.object(ar, "_has_google_creds", return_value=True), \
             mock.patch.object(ar, "_profile_for", return_value="google-benbap115"), \
             mock.patch.object(ar, "_freshen_google", side_effect=_freshen_gia):
            ar.recover_provider_account(
                {"email": "benbap115@gmail.com"}, "free", "dead:marked_error")
        return goi

    def test_ho_so_ban_thi_noi_ho_so_ban(self):
        cuoi = self._chay("Hồ sơ đang bận — chưa tới lượt")[-1]
        self.assertIn("KHÔNG tự khôi phục được", cuoi)
        self.assertIn("Hồ sơ đang bận", cuoi)

    def test_khong_con_do_loi_google_oan(self):
        cuoi = self._chay("Hồ sơ đang bận — chưa tới lượt")[-1]
        self.assertNotIn("Google chặn", cuoi)
        self.assertNotIn("đổi giao diện", cuoi)
        self.assertNotIn("không vào được ô mật khẩu", cuoi)

    def test_thieu_credential_thi_noi_thieu_credential(self):
        cuoi = self._chay("no saved Google credentials for this profile")[-1]
        self.assertIn("no saved Google credentials", cuoi)

    def test_captcha_that_van_giu_cau_captcha(self):
        """Nhánh đo được thì KHÔNG đổi — vẫn phải chỉ đúng việc cần làm."""
        cuoi = self._chay("", trang_thai="need_captcha")[-1]
        self.assertIn("CAPTCHA", cuoi)
        self.assertIn("6080", cuoi)

    def test_khong_ro_ly_do_thi_noi_thang_la_khong_ro(self):
        cuoi = self._chay("", trang_thai="error")[-1]
        self.assertIn("error", cuoi)
        self.assertNotIn("Google chặn", cuoi)


# ── Tái phát 10/08/2026: dọn dẹp của việc này giết lượt đăng nhập của việc kia ─

class DonDepKhongDuocGietLuotDangNhap(unittest.TestCase):
    """Sau khi ba lỗi trên được vá, lượt khôi phục kế tiếp trượt với lý do MỚI —
    và lần này là lý do thật, đo được, do chính lỗi 3 phơi ra:

        → Lý do: Page.goto: Target page, context or browser has been closed.

    Log máy chủ 10/08/2026:
        05:45:49  opened context google-benbap115 (T2 onboard ChatGPT)
        05:45:49  cưỡi session Google sẵn có — bỏ qua nuke      ← lỗi 2 đã vá
        05:48:55  close_profile: bận quá 5s — bỏ lượt đóng      ← lỗi 1 đã vá
        05:48:57  auto-login crashed profile=google-benbap115   ← lỗi MỚI
        05:48:57  closed browser after chatgpt onboard state=failed

    Tầng T2 hết giờ chờ ở phía người gọi (180s) trong khi tác vụ máy chủ chạy
    tới 188s. Tầng T3 nhận context trong khe 2 giây đó, rồi bước dọn dẹp của T2
    đóng đúng cái context ấy.

    Các luồng đăng nhập lấy context bằng `get()` và thao tác NGOÀI khoá hồ sơ
    (khác `page()` — cái đó giữ khoá suốt lượt), nên khoá không bảo vệ được họ.
    Hàng rào đúng đã có sẵn từ 31/07: cờ `dang_dang_nhap` + tham số
    `bo_qua_khi_dang_nhap`. Nó chỉ chưa được dựng ở các bước DỌN DẸP.
    """

    # (file, hàm/đoạn chứa lời gọi) — mọi chỗ mang nghĩa "xong việc của TÔI"
    DON_DEP = [
        ("captcha-solver/src/auto_login.py", "closed browser after onboard profile"),
        ("captcha-solver/src/chatgpt_login.py", "closed browser after chatgpt onboard profile"),
        ("captcha-solver/src/chatgpt_login.py", "close_profile sau khi dừng onboard bỏ qua"),
        ("captcha-solver/src/gemini_web_login.py", "closed browser after %s onboard profile"),
        ("captcha-solver/src/claude_web_login.py", "closed browser after %s onboard profile"),
        ("captcha-solver/src/openai_native_login.py", "close_profile sau onboard bo qua"),
        ("captcha-solver/src/codex_google_onboard.py", "codex-g: đã đóng browser profile"),
        ("captcha-solver/src/github_codex_onboard.py", "codex_onboard_close_profile_error"),
        ("captcha-solver/src/main.py", 'auto_refresh: %s error: %s'),
    ]

    def test_moi_buoc_don_dep_deu_ne_luot_dang_nhap(self):
        for duong_dan, moc in self.DON_DEP:
            with self.subTest(file=duong_dan, moc=moc):
                nguon = _chi_code((GOC / duong_dan).read_text(encoding="utf-8"))
                i = nguon.index(moc)
                # Lời gọi nằm ngay quanh mốc (trước với nhánh có log sau, sau với
                # nhánh có comment trước) → soi cả hai phía.
                quanh = nguon[max(0, i - 400):i + 400]
                self.assertIn("close_profile", quanh)
                self.assertIn("bo_qua_khi_dang_nhap=True", quanh,
                              f"{duong_dan}: bước dọn dẹp này vẫn đóng được trình "
                              f"duyệt giữa lượt đăng nhập của việc khác")

    def test_nut_dong_tay_van_dong_that(self):
        """Người bấm 'đóng' hay xoá hồ sơ là YÊU CẦU TƯỜNG MINH — không được né."""
        nguon = _chi_code((GOC / "captcha-solver/src/main.py").read_text(encoding="utf-8"))
        for moc in ('async def api_session_close', 'if not profile or "/" in profile'):
            i = nguon.index(moc)
            quanh = nguon[i:i + 700]
            self.assertIn("close_profile", quanh)
            self.assertNotIn("bo_qua_khi_dang_nhap", quanh)

    def test_co_dang_nhap_thi_close_profile_khong_cham_khoa(self):
        """Né phải xảy ra TRƯỚC khi chạm khoá — nếu không thì nó vừa không đóng
        vừa vẫn xếp hàng chờ."""
        than = _than(NGUON_POOL, "async def close_profile", "def is_loaded")
        self.assertLess(than.index("if bo_qua_khi_dang_nhap and self.dang_dang_nhap"),
                        than.index("lock = await self._lock_for(profile)"))


if __name__ == "__main__":
    unittest.main()
