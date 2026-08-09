"""Hết hạn token thì tự đăng nhập lại — kể cả tài khoản OpenAI gốc.

VẤN ĐỀ (đo 09/08/2026, đọc mã)

`services/jwt_refresh_scheduler` quét token gần hết hạn (~28 ngày) rồi gọi
`GET /v1/chatgpt/{profile}/refresh-jwt` của solver. Tên profile nó suy ra là
`google-<localpart>` cho MỌI tài khoản — JWT không có trường nào nói tài khoản
đăng nhập bằng đường nào, nên nó phải đoán.

Tài khoản OpenAI gốc lại nằm ở profile `openai-<localpart>` (quy ước của
`web/src/app/settings/components/openai-native-card.tsx`). Hậu quả là cả hai
tầng của endpoint đều trượt:

  · tier 1 quét phiên: mở một profile chưa từng đăng nhập → không có token;
  · tier 2 đăng nhập lại: chạy `start_chatgpt_onboard`, tức bấm "Continue with
    Google" rồi điền mật khẩu OpenAI vào form của GOOGLE → không thể qua.

Thêm nữa `resolve_account()` không biết tiền tố `openai-`, nên ngay cả khi gọi
thẳng bằng đúng tên profile thì cũng không tra ra mật khẩu đã lưu.

MỘT CÁI BẪY khi chữa: đừng suy ra kiểu tài khoản bằng "thư mục nào có thật" như
`account_recovery._profile_for`. Thư mục `google-<localpart>` KHÔNG phải bằng
chứng, vì chính tier 1 tạo ra nó (`pool.page()` mở Chrome với user_data_dir đó).
Sau đúng một lần làm mới hụt, tài khoản OpenAI gốc cũng có một thư mục `google-`
đầy đủ mà chưa từng đăng nhập. Chiều ngược lại mới đúng: `openai-<localpart>`
chỉ có thể do thẻ OpenAI gốc tạo ra, nên nó LÀ bằng chứng.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC / "captcha-solver"))

NGUON_MAIN = (GOC / "captcha-solver/src/main.py").read_text(encoding="utf-8")
NGUON_DB = (GOC / "captcha-solver/src/accounts_db.py").read_text(encoding="utf-8")

# Thân của endpoint làm mới, để soi bằng chuỗi những chỗ không chạy nổi trong
# unittest (chúng mở trình duyệt thật).
THAN_REFRESH = NGUON_MAIN[
    NGUON_MAIN.index('@app.get("/v1/chatgpt/{profile}/refresh-jwt"'):
    NGUON_MAIN.index("async def _update_chatgpt2api_token")
]


def _nap_ung_vien(thu_muc: Path):
    """Nạp `_ho_so_ung_vien` với `settings` giả trỏ vào thư mục tạm."""
    dau = NGUON_MAIN.index("_TIEN_TO_HO_SO = (")
    cuoi = NGUON_MAIN.index('@app.get("/v1/chatgpt/{profile}/refresh-jwt"')
    ns = {"settings": SimpleNamespace(data_dir=thu_muc), "Path": Path}
    exec(compile(NGUON_MAIN[dau:cuoi], "ungvien", "exec"), ns)
    return ns["_ho_so_ung_vien"]


class ChonHoSoTests(unittest.TestCase):
    """`_ho_so_ung_vien` phải tìm ra profile OpenAI gốc từ cái tên bộ lịch đoán."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.goc = Path(self._tmp.name)
        (self.goc / "profiles").mkdir()
        self.ung_vien = _nap_ung_vien(self.goc)

    def tearDown(self):
        self._tmp.cleanup()

    def _tao(self, ten: str):
        (self.goc / "profiles" / ten).mkdir(parents=True, exist_ok=True)

    def test_tim_ra_ho_so_openai_tu_ten_google_bo_lich_doan(self):
        self._tao("openai-benbap2011")
        ds = self.ung_vien("google-benbap2011")
        self.assertEqual(ds, ["google-benbap2011", "openai-benbap2011"])
        # Tier 2 lấy ứng viên CUỐI → đăng nhập lại đúng luồng OpenAI gốc.
        self.assertTrue(ds[-1].startswith("openai-"))

    def test_khong_co_ho_so_openai_thi_giu_nguyen_duong_google(self):
        # Tài khoản Google thật: không được bịa thêm ứng viên nào, nếu không
        # tier 2 sẽ đăng nhập lại bằng luồng sai cho tài khoản đang chạy tốt.
        self._tao("google-benbap2011")
        ds = self.ung_vien("google-benbap2011")
        self.assertEqual(ds, ["google-benbap2011"])
        self.assertFalse(ds[-1].startswith("openai-"))

    def test_thu_muc_google_do_lan_lam_moi_hut_tao_ra_khong_lam_lac_huong(self):
        """Cái bẫy chính: tier 1 tạo ra thư mục `google-`, đừng tin vào nó.

        Tài khoản OpenAI gốc sau một lần làm mới hụt sẽ có CẢ HAI thư mục. Nếu
        chọn theo kiểu "cái nào có thật trước thì lấy" thì mãi mãi rơi vào
        `google-` và không bao giờ đăng nhập lại được.
        """
        self._tao("google-benbap2011")   # husk do tier 1 tạo
        self._tao("openai-benbap2011")   # nhà thật của tài khoản
        ds = self.ung_vien("google-benbap2011")
        self.assertEqual(ds[-1], "openai-benbap2011")

    def test_goi_thang_bang_ten_openai_khong_nhan_doi(self):
        self._tao("openai-benbap2011")
        self.assertEqual(self.ung_vien("openai-benbap2011"), ["openai-benbap2011"])

    def test_ten_rong_khong_lam_no_ham(self):
        self.assertEqual(self.ung_vien(""), [])

    def test_localpart_co_dau_cham_van_ra_dung_anh_em(self):
        # Email kiểu `d.ustinbay056483@gmail.com` → localpart giữ dấu chấm ở
        # một số đường tạo profile.
        self._tao("openai-d-ustinbay056483")
        ds = self.ung_vien("google-d-ustinbay056483")
        self.assertEqual(ds[-1], "openai-d-ustinbay056483")


class ChonLuongDangNhapLaiTests(unittest.TestCase):
    """Tier 2 phải chọn luồng theo profile, và tra được credential đã lưu."""

    def test_resolve_account_biet_tien_to_openai(self):
        dau = NGUON_DB.index("def resolve_account")
        than = NGUON_DB[dau:dau + 1500]
        self.assertIn('"openai-"', than,
                      "resolve_account không bóc tiền tố openai- thì tier 2 không "
                      "tra ra mật khẩu đã lưu, dù đã tìm đúng profile")

    def test_ho_so_openai_dang_nhap_bang_luong_openai_goc(self):
        self.assertIn("start_openai_login", THAN_REFRESH,
                      "tier 2 phải gọi luồng OpenAI gốc cho profile openai-")
        self.assertIn('profile.startswith("openai-")', THAN_REFRESH,
                      "phải chọn luồng theo tên profile")

    def test_van_giu_duong_google_cho_tai_khoan_google(self):
        self.assertIn("start_chatgpt_onboard", THAN_REFRESH,
                      "không được bỏ đường Google — phần lớn tài khoản đi đường đó")

    def test_thieu_hat_giong_totp_thi_bao_ngay_thay_vi_treo(self):
        """Không có hạt giống thì luồng dừng ở `need_code` chờ người gõ mã.

        Chạy không người trông thì không ai gõ. Treo hết 5 phút rồi báo "timed
        out" là nói sai nguyên nhân — người vận hành sẽ đi tìm lỗi mạng thay vì
        bổ sung hạt giống.
        """
        self.assertIn('s.state == "need_code"', THAN_REFRESH)
        vi_tri_need = THAN_REFRESH.index('s.state == "need_code"')
        vi_tri_ok = THAN_REFRESH.index('s.state == "success"')
        self.assertLess(vi_tri_need, vi_tri_ok,
                        "phải bắt need_code trước khi vào nhánh success")


if __name__ == "__main__":
    unittest.main()
