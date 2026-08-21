"""Đăng nhập ChatGPT bằng tài khoản OpenAI gốc — email + mật khẩu + TOTP.

Đường đăng nhập sẵn có (`chatgpt_login.py`) mở `auth.openai.com` rồi đi tìm nút
"Continue with Google", và điền email/mật khẩu vào form của GOOGLE. Nó chỉ phục
vụ tài khoản Google.

Phần lớn tài khoản ChatGPT mua theo lô lại là tài khoản OpenAI gốc. Đo thật
08/08/2026 trên một tài khoản đuôi `@gmail.com`: gõ email vào ô "Địa chỉ email"
của ChatGPT thì đi thẳng sang trang "Nhập mật khẩu của bạn" rồi trang "Kiểm tra
ứng dụng xác thực của bạn" — bốn màn hình đều của OpenAI, không chạm Google lần
nào. Đuôi email (@gmail hay @icloud) không nói lên tài khoản đăng nhập kiểu gì.

GIỚI HẠN CỦA BỘ TEST NÀY: nó không mở trình duyệt thật. Phần bấm nút và điền ô
chỉ chứng minh được bằng một lần chạy thật với tài khoản thật — xem ghi chú ở
`ChuaKiemChungTrenTrangThatTests` cuối file.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import sys
import time
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
sys.path.insert(0, str(GOC / "captcha-solver"))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

NGUON = (GOC / "captcha-solver/src/openai_native_login.py").read_text(encoding="utf-8")
# Phần MÃ, đã bỏ docstring đầu file. Docstring giải thích đường Google cũ khác gì
# đường này, nên nó có chứa "Continue with Google" — grep cả file sẽ bắt vào
# chính lời giải thích của mình và báo đỏ một lỗi không có thật.
THAN = NGUON[NGUON.index('"""', NGUON.index('"""') + 3) + 3:]


def _totp_chuan(seed: str, luc: float) -> str:
    """TOTP theo RFC-6238, viết độc lập để đối chiếu với `pyotp`."""
    s = seed.replace(" ", "").upper()
    s += "=" * (-len(s) % 8)
    khoa = base64.b32decode(s)
    h = hmac.new(khoa, struct.pack(">Q", int(luc) // 30), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


SEED = base64.b32encode(b"0123456789abcdefghij").decode()


class SinhMaTests(unittest.TestCase):
    def setUp(self):
        try:
            import pyotp  # noqa: F401
        except ImportError:
            self.skipTest("pyotp chưa cài trên máy này")
        from test._goi_captcha import nap
        m = nap("openai_native_login")
        self.m = m

    def test_ma_khop_voi_bo_sinh_doc_lap(self):
        """Nếu lệch, mọi lần đăng nhập đều hỏng ở bước cuối mà không rõ vì sao."""
        self.assertEqual(self.m._ma_hien_tai(SEED), _totp_chuan(SEED, time.time()))

    def test_bo_khoang_trang_trong_hat_giong(self):
        """Người dùng dán seed từ ảnh QR hay bị dính khoảng trắng."""
        co_cach = " ".join(SEED[i:i + 4] for i in range(0, len(SEED), 4))
        self.assertEqual(self.m._ma_hien_tai(co_cach), self.m._ma_hien_tai(SEED))


class ChoSangCuaSoMoiTests(unittest.TestCase):
    """Mã 6 số chỉ đổi mỗi 30 giây.

    Sinh lại mã NGAY sau khi bị từ chối sẽ ra đúng con số vừa bị từ chối: ba lần
    thử cháy hết trong hai giây mà chưa hề thử một mã khác, rồi báo "sai mã 3
    lần" trong khi hạt giống hoàn toàn đúng.
    """

    def test_ham_cho_het_cua_so_hien_tai(self):
        i = NGUON.index("async def _ma_moi")
        than = NGUON[i:i + 700]
        self.assertIn("30 - int(time.time()) % 30", than,
                      "không tính thời gian còn lại của cửa sổ hiện tại")
        self.assertIn("await asyncio.sleep", than)

    def test_lan_dau_KHONG_cho(self):
        """Chờ 30 giây trước cả lần thử đầu là phí một cửa sổ."""
        i = NGUON.index("for lan in range(SO_LAN_THU_MA)")
        self.assertIn("_ma_hien_tai(seed) if lan == 0 else await _ma_moi(seed)",
                      NGUON[i:i + 300])


class KhongLoBiMatTests(unittest.TestCase):
    def test_khong_ghi_ma_TOTP_ra_log(self):
        """Mã còn sống tới hết cửa sổ 30 giây, mà log thường được gửi đi nơi khác.

        Đường Google cũ ghi thẳng `TOTP code=%s` ra log."""
        i = NGUON.index("logger.info(\"openai_login: dien ma TOTP")
        self.assertNotIn("%s\", ma", NGUON[i:i + 200])
        self.assertNotIn("code=%s", NGUON)

    def test_khong_ghi_mat_khau_ra_log(self):
        for dong in THAN.splitlines():
            if "logger." in dong:
                self.assertNotIn("password", dong, f"log lộ mật khẩu: {dong.strip()}")
                self.assertNotIn("totp_secret", dong, f"log lộ hạt giống: {dong.strip()}")


class LuongBonManHinhTests(unittest.TestCase):
    def test_di_dung_thu_tu_email_matkhau_ma(self):
        vi_email = NGUON.index("_O_EMAIL, session.email")
        vi_pw = NGUON.index("_O_MAT_KHAU, password")
        vi_2fa = NGUON.index("_qua_buoc_2fa(session, page)")
        self.assertLess(vi_email, vi_pw)
        self.assertLess(vi_pw, vi_2fa)

    def test_ho_so_da_dang_nhap_thi_KHONG_dong_toi_mat_khau(self):
        """Đăng nhập lại một hồ sơ đang khoẻ là tự chuốc thêm một lần 2FA."""
        i = NGUON.index("_scrape_chatgpt_token(page)")
        j = NGUON.index("_O_EMAIL, session.email")
        self.assertLess(i, j, "chưa thử lấy token trước khi đi đăng nhập")

    def test_bo_qua_buoc_2FA_khi_tai_khoan_khong_bat(self):
        """Không phải tài khoản nào cũng bật 2FA — chờ ô mã sẽ treo 20 giây."""
        self.assertIn("if await _co_o_ma(page):", NGUON)

    def test_khong_co_hat_giong_thi_dung_lai_cho_nguoi_nhap(self):
        i = NGUON.index("if not seed or not _CO_PYOTP:")
        self.assertIn('session.state = "need_code"', NGUON[i:i + 400])

    def test_o_ma_KHONG_bat_input_text_tran(self):
        """Trang mã có thể còn ô email ẩn; điền mã vào đó thì hỏng khó hiểu."""
        i = NGUON.index("_O_MA = (")
        khoi = NGUON[i:NGUON.index(")", i)]
        self.assertNotIn('input[type="text"]', khoi)
        self.assertIn('one-time-code', khoi)


class DonDepTaiNguyenTests(unittest.TestCase):
    def test_danh_dau_ho_so_dang_dang_nhap(self):
        """Không đánh dấu thì việc khác đóng trình duyệt giữa lúc đang đăng nhập."""
        i = NGUON.index("async def _run(")
        than = NGUON[i:i + 1200]
        self.assertIn("pool.dau_dang_nhap", than)
        self.assertIn("pool.xong_dang_nhap", than)
        self.assertIn("finally:", than)

    def test_loi_bat_ngo_KHONG_de_phien_treo_o_running(self):
        """Phiên kẹt `running` mãi thì giao diện quay vòng vô hạn."""
        i = NGUON.index("async def _run(")
        than = NGUON[i:i + 1200]
        self.assertIn('session.state = "failed"', than)
        self.assertIn("CancelledError", than, "huỷ tác vụ không phải là lỗi đăng nhập")


class TachKhoiDuongGoogleTests(unittest.TestCase):
    def test_KHONG_dung_toi_nut_Google(self):
        """Cả điểm khác biệt nằm ở đây: không đi qua Google."""
        for tu in ("accounts.google.com", "Continue with Google", "Tiếp tục với Google"):
            self.assertNotIn(tu, THAN, f"vẫn dính đường Google: {tu}")

    def test_KHONG_sua_vao_luong_Google_cu(self):
        """Hàm ở `chatgpt_login.py` đã 1778 dòng với đầy fallback riêng cho
        Google — nhồi thêm một nhánh vào đó là chuốc lấy lỗi ở đường đang chạy."""
        cu = (GOC / "captcha-solver/src/chatgpt_login.py").read_text(encoding="utf-8")
        self.assertNotIn("openai_native", cu)

    def test_dung_lai_bo_lay_token_san_co(self):
        self.assertIn("from .chatgpt_login import _scrape_chatgpt_token", NGUON)


class ComposeTests(unittest.TestCase):
    COMPOSE = (GOC / "docker-compose.yml").read_text(encoding="utf-8")

    def test_co_cong_tac_bat_buoc_ma_hoa(self):
        """Thiếu nó thì gõ sai định dạng khoá một lần là credential về plaintext."""
        self.assertIn("VAULT_REQUIRE_ENCRYPTION:", self.COMPOSE)

    def test_mac_dinh_van_de_TRONG(self):
        """Bật sẵn sẽ làm hỏng bản đang chạy của người chưa đặt khoá."""
        self.assertIn("VAULT_REQUIRE_ENCRYPTION: ${VAULT_REQUIRE_ENCRYPTION:-}",
                      self.COMPOSE)


class ManChanPhienKetThucTests(unittest.TestCase):
    """Màn chắn "Phiên của bạn đã kết thúc" phải được bấm qua trước khi điền email.

    ĐO THẬT 09/08/2026 trên máy chủ, tài khoản OpenAI gốc thật. Luồng chết ở
    ngay màn hình đầu với thông báo "Không tìm thấy ô email trên
    auth.openai.com — trang có thể đang chặn (Cloudflare)". Không phải
    Cloudflare: chỉ cần đã ghé `chatgpt.com` một lần — mà bước dò phiên sẵn có
    ở đầu `_run_inner` thì LUÔN ghé — là trang đăng nhập trả về một màn chắn
    không có lấy một thẻ `<input>` nào. `_dien` chờ hết 6 bộ chọn × 20 giây
    (đúng 120 giây quan sát được) rồi bỏ cuộc.

    Hai cách đã thử và LOẠI, ghi lại để không ai đi lại:
      · đổi URL đăng nhập  → vẫn ra màn chắn (đã đo trên cả hai URL);
      · xoá cookie trước khi vào → vẫn ra màn chắn.
    Cách chạy được là bấm chính link "Đăng nhập" của màn chắn; sau cú bấm trang
    thành "Chào mừng trở lại" với ô email, URL không đổi. Chạy thật sau khi vá:
    qua màn chắn → mật khẩu → mã TOTP đúng ngay lần 1 → lấy được access token.
    """

    def test_co_ham_qua_man_chan(self):
        self.assertIn("async def _qua_man_chan", THAN)

    def test_bam_qua_man_chan_truoc_khi_dien_email(self):
        vi_tri_bam = THAN.index("await _qua_man_chan(page)")
        vi_tri_dien = THAN.index("_dien(page, _O_EMAIL")
        self.assertLess(vi_tri_bam, vi_tri_dien,
                        "phải bấm qua màn chắn TRƯỚC khi tìm ô email, "
                        "nếu không _dien chờ vô ích 120 giây rồi báo lỗi sai hướng")

    def test_khong_bam_nham_khi_da_o_form(self):
        # Vào thẳng trang đăng nhập (hồ sơ chưa ghé chatgpt.com) thì ra form
        # luôn, không có màn chắn. Bấm bừa lúc đó là rời khỏi form.
        i = THAN.index("async def _qua_man_chan")
        than_ham = THAN[i:i + 1400]
        self.assertIn("_O_EMAIL[0]", than_ham,
                      "phải kiểm có ô email chưa rồi mới bấm")

    def test_man_chan_co_nhieu_bo_chon_du_phong(self):
        i = NGUON.index("_NUT_MAN_CHAN = (")
        khoi = NGUON[i:NGUON.index("\n)", i)]
        self.assertGreaterEqual(khoi.count("'"), 6,
                                "_NUT_MAN_CHAN có ít hơn 3 bộ chọn dự phòng")


class ChuaKiemChungTrenTrangThatTests(unittest.TestCase):
    """Ghi lại cho rõ ràng: phần nào ở đây CHƯA được chứng minh.

    Bộ test này không mở trình duyệt. Các bộ chọn (`_O_EMAIL`, `_O_MAT_KHAU`,
    `_O_MA`) được suy ra từ ảnh chụp màn hình đăng nhập ngày 08/08/2026, chưa
    khớp thử với DOM thật lần nào. Auth0 đổi `name`/`id` theo bản dựng, nên lần
    chạy thật đầu tiên rất có thể phải chỉnh lại danh sách này.

    Test ở đây chỉ chốt: mỗi ô đều có NHIỀU dấu hiệu để bắt, và có thông báo lỗi
    nói rõ phải mở noVNC xem — để lần chạy đầu thất bại theo cách chẩn đoán
    được, thay vì treo im lặng.
    """

    def test_moi_o_deu_co_nhieu_bo_chon_du_phong(self):
        for ten in ("_O_EMAIL", "_O_MAT_KHAU", "_O_MA", "_NUT_TIEP_TUC"):
            i = NGUON.index(f"{ten} = (")
            khoi = NGUON[i:NGUON.index("\n)", i)]
            self.assertGreaterEqual(khoi.count("'"), 6,
                                    f"{ten} có ít hơn 3 bộ chọn dự phòng")

    def test_khong_tim_thay_o_thi_bao_MO_noVNC(self):
        for moc in ("Không tìm thấy ô email", "Không tới được trang mật khẩu"):
            i = NGUON.index(moc)
            self.assertIn("noVNC", NGUON[i - 100:i + 400],
                          f"lỗi «{moc}» không chỉ người trực đi đâu xem")

    def test_sai_ma_3_lan_thi_noi_ro_hai_kha_nang(self):
        i = NGUON.index("Sai mã TOTP")
        than = NGUON[i:i + 300].lower()
        self.assertIn("hạt giống", than)
        self.assertIn("đồng hồ", than, "lệch giờ máy chủ cũng làm sai mã")


if __name__ == "__main__":
    unittest.main()
