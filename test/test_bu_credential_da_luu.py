"""Chọn một tài khoản đã lưu rồi bấm đăng nhập phải chạy được.

SỰ CỐ 08/08/2026, do chính đợt vá bảo mật cùng ngày gây ra.

Bản vá đó bịt một lỗ thật: `GET /v1/accounts/saved/{email}` trước đây trả
`dict(acct)` nguyên vẹn, tức mật khẩu và hạt giống TOTP đi thẳng về trình duyệt
— làm vậy thì lớp mã hoá của `vault.py` chẳng còn nghĩa gì, vì đã có sẵn một
endpoint giải mã rồi đưa ra ngoài.

Nhưng các thẻ onboard vẫn gửi đúng những trường đó LÊN. Nên sau khi chọn một tài
khoản trong danh sách đã lưu, form rỗng, bấm đăng nhập là gửi mật khẩu RỖNG. Chủ
máy báo: "sau khi lưu tài khoản xong không thấy hiện mật khẩu, mã otp" và "kích
chỉ đăng nhập đang không được".

Sửa ở PHÍA MÁY CHỦ chứ không sửa từng thẻ: `bu_credential()` tra kho khi request
gửi rỗng, nên mọi thẻ được vá cùng lúc và mật khẩu vẫn không rời khỏi tiến trình
solver — đúng đường mà `/v1/session/auto-login-saved` đã đi từ trước.

Kèm một cái bẫy phải chặn: `save_account()` GHI ĐÈ. Gọi nó với chuỗi rỗng là xoá
mất mật khẩu đã lưu, mà form thì giờ luôn rỗng. Hai endpoint (`api_auto_login`,
`api_gemini_web_onboard`) đang gọi nó không điều kiện.
"""
from __future__ import annotations

import ast
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC / "captcha-solver"))

NGUON = (GOC / "captcha-solver/src/main.py").read_text(encoding="utf-8")


@dataclass
class YeuCauGia:
    email: str = ""
    profile: str = ""
    password: str = ""
    totp_secret: str = ""


def _bu(monkey_store: dict):
    """Nạp `bu_credential` với `resolve_account` giả — khỏi cần sqlite thật.

    Từ 09/08/2026 `bu_credential` còn suy ra KHO (google / openai gốc) từ tên hồ
    sơ rồi truyền xuống, nên hàm giả phải nhận thêm tham số đó. Kho ở đây không
    ảnh hưởng khẳng định nào — chuyện tách kho được chốt riêng ở
    `test_tach_kho_credential.py`.
    """
    than = NGUON[NGUON.index("def bu_credential"):NGUON.index("class TwoFactorCodeReq")]
    ns = {
        "resolve_account": lambda k, loai=None: monkey_store.get(k),
        "loai_theo_profile": lambda p: (
            "openai" if str(p or "").strip().lower().startswith("openai-") else "google"),
    }
    exec(compile(than, "bu", "exec"), ns)
    return ns["bu_credential"]


KHO = {
    "benbap2011@gmail.com": {"password": "mk-that", "totp_secret": "seed-that"},
    "google-benbap2011": {"password": "mk-that", "totp_secret": "seed-that"},
}


class BuTuKhoTests(unittest.TestCase):
    def setUp(self):
        self.bu = _bu(KHO)

    def test_form_RONG_thi_lay_tu_kho(self):
        """Đúng kịch bản đã hỏng: chọn tài khoản đã lưu rồi bấm đăng nhập."""
        self.assertEqual(self.bu(YeuCauGia(email="benbap2011@gmail.com")),
                         ("mk-that", "seed-that"))

    def test_tra_duoc_theo_TEN_PROFILE_chu_khong_chi_email(self):
        """Vài thẻ chỉ biết tên hồ sơ (`google-benbap2011`), không biết email."""
        self.assertEqual(self.bu(YeuCauGia(profile="google-benbap2011"))[0], "mk-that")

    def test_go_TAY_thi_kho_KHONG_duoc_de_len(self):
        """Người dùng gõ mật khẩu mới là ý định thật — thường là vì mật khẩu cũ
        đã đổi, đè lên bằng giá trị cũ thì đăng nhập hỏng mãi mãi."""
        ra = self.bu(YeuCauGia(email="benbap2011@gmail.com", password="mk-moi"))
        self.assertEqual(ra[0], "mk-moi")
        self.assertEqual(ra[1], "seed-that", "vẫn phải bù hạt giống còn thiếu")

    def test_khong_co_trong_kho_thi_tra_ve_nguyen_trang(self):
        self.assertEqual(self.bu(YeuCauGia(email="la@gmail.com", password="p")),
                         ("p", ""))

    def test_khong_co_email_lan_profile_thi_khong_no(self):
        self.assertEqual(self.bu(YeuCauGia()), ("", ""))

    def test_kho_loi_thi_khong_lam_hong_ca_luot_dang_nhap(self):
        def no(_):
            raise RuntimeError("sqlite hỏng")
        than = NGUON[NGUON.index("def bu_credential"):NGUON.index("class TwoFactorCodeReq")]
        ns = {"resolve_account": no}
        exec(compile(than, "bu", "exec"), ns)
        self.assertEqual(ns["bu_credential"](YeuCauGia(email="x@y", password="p")),
                         ("p", ""))


class KhongGhiDeRongLenKhoTests(unittest.TestCase):
    """`save_account` ghi đè — gọi nó với chuỗi rỗng là XOÁ credential đã lưu.

    Nguy hiểm hơn hẳn việc đăng nhập hỏng: đăng nhập hỏng thì thử lại, còn mất
    mật khẩu đã lưu thì tự khôi phục tài khoản (`account_recovery._freshen_google`)
    cũng chết theo, và không ai biết cho tới lúc một phiên hết hạn.
    """

    def _than_ham(self, ten: str) -> str:
        i = NGUON.index(f"async def {ten}(")
        return NGUON[i:NGUON.index("\n@app.", i)]

    def test_moi_lan_goi_save_account_deu_co_dieu_kien_bao_ve(self):
        for dong_so, dong in enumerate(NGUON.splitlines(), 1):
            if "save_account(req.email" not in dong:
                continue
            truoc = "\n".join(NGUON.splitlines()[max(0, dong_so - 6):dong_so])
            self.assertIn("req.password", truoc,
                          f"dòng {dong_so}: ghi kho mà không kiểm mật khẩu rỗng")
            self.assertIn("strip()", truoc, f"dòng {dong_so}")

    def test_hai_endpoint_tung_goi_khong_dieu_kien_nay_da_co_chan(self):
        for ten in ("api_auto_login", "api_gemini_web_onboard"):
            than = self._than_ham(ten)
            i = than.index("save_account(req.email")
            self.assertIn('str(req.password or "").strip()', than[:i],
                          f"{ten} vẫn ghi kho vô điều kiện")

    def test_ghi_kho_dung_gia_tri_NGUOI_DUNG_GUI_chu_khong_phai_gia_tri_da_bu(self):
        """Ghi lại giá trị vừa bù từ kho là thừa, và che mất việc form rỗng."""
        for dong in NGUON.splitlines():
            if "save_account(req.email" in dong:
                self.assertIn("req.password", dong, dong.strip())
                self.assertNotIn("mat_khau", dong, dong.strip())


class MoiEndpointDeuDungTests(unittest.TestCase):
    """Vá ở máy chủ để mọi thẻ được vá cùng lúc — nên phải phủ hết endpoint."""

    CAN_CO = ("api_auto_login", "api_gemini_web_onboard", "api_chatgpt_onboard",
              "api_openai_native_onboard", "api_claude_web_onboard", "_run_multi")

    def test_moi_endpoint_nhan_mat_khau_deu_goi_bu_credential(self):
        for ten in self.CAN_CO:
            i = NGUON.index(f"async def {ten}(")
            than = NGUON[i:NGUON.index("\n@app.", i) if "\n@app." in NGUON[i:] else i + 4000]
            self.assertIn("bu_credential(req)", than, f"{ten} chưa bù credential")

    def test_khong_con_truyen_thang_req_password_vao_ham_dang_nhap(self):
        for m in ("start_auto_login", "start_gemini_web_login", "start_chatgpt_onboard",
                  "start_openai_login", "start_claude_web_login"):
            i = 0
            while (i := NGUON.find(f"{m}(", i + 1)) > 0:
                khoi = NGUON[i:i + 400]
                self.assertNotIn("password=req.password", khoi,
                                 f"{m} vẫn nhận thẳng mật khẩu từ form")

    def test_ham_bu_khong_bao_gio_nem_ra_ngoai(self):
        than = NGUON[NGUON.index("def bu_credential"):NGUON.index("class TwoFactorCodeReq")]
        self.assertIn("except Exception:", than)
        cay = ast.parse(than)
        self.assertTrue(any(isinstance(n, ast.Try) for n in ast.walk(cay)))


class KhongTraBiMatVeTrinhDuyetTests(unittest.TestCase):
    """Chốt lại lớp vá đang được giữ — sửa lỗi trên không được mở lại lỗ này."""

    def test_endpoint_chi_tiet_van_KHONG_tra_mat_khau_hay_hat_giong(self):
        i = NGUON.index("async def api_accounts_get(")
        than = NGUON[i:NGUON.index("\n@app.", i)]
        self.assertIn('"has_password"', than)
        self.assertIn('"has_totp"', than)
        self.assertNotIn('"password": acct', than)
        self.assertNotIn('"totp_secret": acct', than)

    def test_endpoint_totp_tra_MA_chu_khong_tra_hat_giong(self):
        i = NGUON.index("async def api_accounts_totp(")
        than = NGUON[i:NGUON.index("\n@app.", i)]
        self.assertIn('"code": code', than)
        self.assertNotIn("seed}", than)


if __name__ == "__main__":
    unittest.main()
