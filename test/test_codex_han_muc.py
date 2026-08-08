"""Hạn mức Codex đọc từ chính lưu lượng đang chạy.

SỰ CỐ THẬT 08/08/2026 — màn hình Tài khoản báo 6/6 tài khoản codex "Giới hạn"
mà không nói vì sao, cũng không nói bao giờ hồi.

Bốn thanh nó vẽ (nghiên cứu sâu, tải tệp, dán văn bản, tạo ảnh) là hạn mức tính
năng của chatgpt.com. Với tài khoản free thì đó là hạn mức thật. Với tài khoản
codex thì thứ chặn chúng lại là hạn mức chữ của Codex — một đồng hồ hoàn toàn
khác, và giao diện không hề vẽ nó.

Bộ thu thập cũ (`usage_snapshot_poller`) chạy 15 giây/lần nhưng trả về rỗng
sạch. Đo trên máy chủ:

    tong: 3   co_primary_pct: 0/3   co_email: 0   loi: {unauthorized: 2}

Ba nguyên nhân rời nhau, mỗi cái tự nó đủ làm hỏng: sai endpoint (nó gọi
`/sentinel/chat-requirements` — endpoint chống bot), khoá kho trùng
(`access_token[:40]` là phần header JWT, 6 tài khoản gộp còn 3), và đọc email từ
một header không tồn tại.

Số liệu trong file này là header 429 THẬT bắt được ngày 08/08/2026 từ
`/backend-api/codex/responses`.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import codex_usage as cu  # noqa: E402

# Header 429 thật, tài khoản gói `go`, đo 08/08/2026.
HEADER_THAT = {
    "x-codex-active-limit": "premium",
    "x-codex-plan-type": "go",
    "x-codex-primary-used-percent": "100",
    "x-codex-secondary-used-percent": "0",
    "x-codex-primary-window-minutes": "43200",
    "x-codex-primary-over-secondary-limit-percent": "0",
    "x-codex-secondary-window-minutes": "0",
    "x-codex-primary-reset-after-seconds": "1951598",
    "x-codex-secondary-reset-after-seconds": "0",
    "x-codex-primary-reset-at": "1788148926",
    "x-codex-secondary-reset-at": "",
    "x-codex-credits-has-credits": "False",
    "x-codex-credits-balance": "",
    "x-codex-credits-unlimited": "False",
}

# Thân JSON thật của `/backend-api/wham/usage`, cùng tài khoản.
WHAM_THAT = {
    "user_id": "user-Zb3hDDcvaaJw7bQXXf3SW6u7",
    "email": "tritue0610@gmail.com",
    "plan_type": "go",
    "rate_limit": {
        "allowed": False,
        "limit_reached": True,
        "primary_window": {"used_percent": 100, "limit_window_seconds": 2592000,
                           "reset_after_seconds": 1951707, "reset_at": 1788148926},
        "secondary_window": None,
    },
    "credits": {"has_credits": False, "unlimited": False, "balance": None},
    "rate_limit_reached_type": {"type": "rate_limit_reached", "details": "default"},
    "rate_limit_reset_credits": {"available_count": 1, "applicable_available_count": 1},
}


def _jwt(payload: dict) -> str:
    """Dựng JWT giả có CÙNG phần header với JWT thật của ChatGPT.

    Phần header giống nhau là điểm mấu chốt: đó chính là thứ khiến khoá
    `token[:40]` của bản cũ trùng nhau giữa các tài khoản khác nhau.
    """
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b64({'alg': 'RS256', 'kid': 'MHW4DpkL'})}.{b64(payload)}.chu-ky-gia"


CLAIM_MAU = {
    "email": "ai-do@gmail.com",
    "https://api.openai.com/auth": {
        "chatgpt_plan_type": "go",
        "chatgpt_account_id": "391f4a97-e0e7-45dc-a340-007e67fe181c",
    },
}


class DocHeaderTests(unittest.TestCase):
    def test_cua_so_chinh_doc_dung_tu_header_that(self):
        ra = cu.doc_header(HEADER_THAT)
        self.assertIsNotNone(ra)
        chinh = ra["chinh"]
        self.assertEqual(chinh["da_dung_pct"], 100.0)
        self.assertEqual(chinh["con_lai_pct"], 0.0)
        self.assertEqual(chinh["cua_so_phut"], 43200)
        self.assertEqual(chinh["reset_at"], 1788148926)

    def test_43200_phut_hien_ra_la_30_ngay(self):
        """Người trực đọc '30 ngày' được, '43200 phút' thì không."""
        self.assertEqual(cu.doc_header(HEADER_THAT)["chinh"]["nhan"], "30 ngày")

    def test_nhan_cua_so_cac_moc_thuong_gap(self):
        self.assertEqual(cu.nhan_cua_so(5 * 60), "5 giờ")
        self.assertEqual(cu.nhan_cua_so(7 * 24 * 60), "7 ngày")
        self.assertEqual(cu.nhan_cua_so(0), "")
        self.assertEqual(cu.nhan_cua_so(None), "")

    def test_cua_so_phu_TOAN_SO_0_thi_khong_phai_cua_so(self):
        """Codex vẫn gửi `secondary-window-minutes: 0` cho tài khoản một cửa sổ.

        Lấy sự hiện diện của header làm căn cứ sẽ vẽ ra một thanh 'còn 100%' cho
        thứ không tồn tại — tệ hơn không vẽ gì, vì nó trông như tin tốt."""
        self.assertIsNone(cu.doc_header(HEADER_THAT)["phu"])

    def test_lay_duoc_plan_tu_header(self):
        self.assertEqual(cu.doc_header(HEADER_THAT)["plan"], "go")

    def test_bao_dung_la_da_cham_tran(self):
        self.assertTrue(cu.doc_header(HEADER_THAT)["cham_tran"])

    def test_khong_co_header_codex_thi_tra_None(self):
        """400 sai model / 401 hết hạn không mang header nào — đừng ghi bừa."""
        self.assertIsNone(cu.doc_header({"content-type": "application/json"}))
        self.assertIsNone(cu.doc_header({}))

    def test_header_HOA_thuong_deu_doc_duoc(self):
        hoa = {k.upper(): v for k, v in HEADER_THAT.items()}
        self.assertEqual(cu.doc_header(hoa)["chinh"]["cua_so_phut"], 43200)


class DocWhamTests(unittest.TestCase):
    def test_doi_GIAY_sang_PHUT_de_cung_hinh_dang_voi_header(self):
        """JSON đo bằng giây, header đo bằng phút. Không quy về một đơn vị thì
        giao diện phải biết dữ liệu đến từ đâu mới vẽ đúng."""
        self.assertEqual(cu.doc_wham(WHAM_THAT)["chinh"]["cua_so_phut"], 43200)
        self.assertEqual(cu.doc_wham(WHAM_THAT)["chinh"]["nhan"], "30 ngày")

    def test_lay_duoc_email_thu_ma_header_KHONG_co(self):
        self.assertEqual(cu.doc_wham(WHAM_THAT)["email"], "tritue0610@gmail.com")

    def test_dem_dung_so_credit_reset(self):
        """Credit reset xoá sạch cửa sổ ngay — khác hẳn `credits` (số dư trả
        thêm), và là đường ra duy nhất khi mốc phục hồi còn cách ba tuần."""
        self.assertEqual(cu.doc_wham(WHAM_THAT)["credit_reset"], 1)
        self.assertFalse(cu.doc_wham(WHAM_THAT)["credit_du"])

    def test_cua_so_phu_null_thi_la_None(self):
        self.assertIsNone(cu.doc_wham(WHAM_THAT)["phu"])


class TokenTests(unittest.TestCase):
    def test_doc_email_va_plan_tu_claim_chu_khong_tu_header(self):
        """Bản cũ đọc `x-codex-account-email` — header đó không tồn tại, nên
        trường email luôn rỗng. Nguồn đúng là claim của chính JWT."""
        tt = cu.thong_tin_token(_jwt(CLAIM_MAU))
        self.assertTrue(tt["la_jwt"])
        self.assertEqual(tt["email"], "ai-do@gmail.com")
        self.assertEqual(tt["plan"], "go")
        self.assertEqual(tt["account_id"], "391f4a97-e0e7-45dc-a340-007e67fe181c")

    def test_token_phien_KHONG_bi_nham_la_JWT(self):
        """Ba tài khoản codex trên máy chủ đang giữ token phiên (JWE / blob đăng
        nhập). Gọi bằng chúng chỉ đổi lấy 401 — phải nhận ra trước khi gọi."""
        for phien in ("eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0.abc.def.ghi.jkl",
                      "khong-phai-jwt", ""):
            self.assertFalse(cu.thong_tin_token(phien)["la_jwt"], phien[:30])

    def test_khong_goi_mang_voi_token_khong_phai_JWT(self):
        self.assertIsNone(cu.doc_tu_mang("khong-phai-jwt"))


class KhoaKhoTests(unittest.TestCase):
    """Đúng chỗ bản cũ mất 3 trong 6 tài khoản."""

    def setUp(self):
        self.kho = cu.KhoHanMuc()

    def test_hai_token_TRUNG_40_KY_TU_DAU_van_la_hai_ban_ghi(self):
        a = _jwt({**CLAIM_MAU, "email": "a@gmail.com"})
        b = _jwt({**CLAIM_MAU, "email": "b@gmail.com"})
        self.assertEqual(a[:40], b[:40], "mẫu thử sai — hai token phải trùng 40 ký tự đầu")
        self.kho.ghi(a, {"plan": "go", "luc_do": 1.0})
        self.kho.ghi(b, {"plan": "free", "luc_do": 1.0})
        self.assertEqual(self.kho.lay(a)["plan"], "go")
        self.assertEqual(self.kho.lay(b)["plan"], "free")
        self.assertEqual(len(self.kho.tat_ca()), 2)

    def test_ban_ghi_tu_header_KHONG_xoa_email_da_co_tu_wham(self):
        """Header không mang email. Ghi đè nguyên khối sẽ xoá mất nó — đúng lỗi
        đã khiến `co_email: 0` ở bản cũ."""
        tok = _jwt(CLAIM_MAU)
        self.kho.ghi(tok, cu.doc_wham(WHAM_THAT))
        self.kho.ghi(tok, cu.doc_header(HEADER_THAT))
        self.assertEqual(self.kho.lay(tok)["email"], "tritue0610@gmail.com")
        self.assertEqual(self.kho.lay(tok)["credit_reset"], 1)

    def test_ban_moi_van_cap_nhat_duoc_phan_tram(self):
        tok = _jwt(CLAIM_MAU)
        self.kho.ghi(tok, {"chinh": {"da_dung_pct": 10.0}, "luc_do": 1.0})
        self.kho.ghi(tok, {"chinh": {"da_dung_pct": 90.0}, "luc_do": 2.0})
        self.assertEqual(self.kho.lay(tok)["chinh"]["da_dung_pct"], 90.0)

    def test_xoa_tai_khoan_khoi_pool_thi_ban_ghi_di_theo(self):
        a, b = _jwt({**CLAIM_MAU, "email": "a@x"}), _jwt({**CLAIM_MAU, "email": "b@x"})
        self.kho.ghi(a, {"plan": "go"})
        self.kho.ghi(b, {"plan": "free"})
        self.kho.xoa_ngoai([a])
        self.assertIsNotNone(self.kho.lay(a))
        self.assertIsNone(self.kho.lay(b))

    def test_ghi_ban_rong_thi_khong_tao_ban_ghi_ma(self):
        self.kho.ghi(_jwt(CLAIM_MAU), None)
        self.assertEqual(self.kho.tat_ca(), {})

    def test_ban_tu_header_LUON_coi_la_qua_cu(self):
        """Header không có email/credit, nên dù mới tinh vẫn phải hỏi `/wham`
        một lần để có bức tranh đủ."""
        tok = _jwt(CLAIM_MAU)
        self.kho.ghi(tok, cu.doc_header(HEADER_THAT))
        self.assertTrue(self.kho.qua_cu(tok))

    def test_ban_wham_con_han_thi_khong_hoi_lai(self):
        tok = _jwt(CLAIM_MAU)
        self.kho.ghi(tok, cu.doc_wham(WHAM_THAT))
        self.assertFalse(self.kho.qua_cu(tok))


class DungEndpointTests(unittest.TestCase):
    def test_goi_wham_usage_chu_khong_phai_sentinel(self):
        """`/sentinel/chat-requirements` là endpoint chống bot, không phải hạn
        mức. Bản cũ gọi nhầm nó suốt và luôn nhận về số rỗng."""
        self.assertEqual(cu.WHAM_USAGE_URL,
                         "https://chatgpt.com/backend-api/wham/usage")
        src = (GOC / "services/codex_usage.py").read_text(encoding="utf-8")
        i = src.index("WHAM_USAGE_URL =")
        self.assertNotIn("sentinel", src[i:])

    def test_gui_header_ChatGPT_Account_Id(self):
        """Thiếu header này thì tài khoản thuộc workspace gọi đâu hỏng đó."""
        src = (GOC / "services/codex_usage.py").read_text(encoding="utf-8")
        i = src.index("def doc_tu_mang")
        self.assertIn('"ChatGPT-Account-Id"', src[i:i + 1500])


class KhongCon_ThamDo_NenTests(unittest.TestCase):
    def test_file_poller_da_bi_xoa(self):
        self.assertFalse((GOC / "services/usage_snapshot_poller.py").exists())

    def test_khong_con_dich_vu_nen_nao_tro_toi_no(self):
        for f in ("api/app.py", "api/accounts.py", "services/config.py"):
            self.assertNotIn("usage_snapshot",
                             (GOC / f).read_text(encoding="utf-8"), f)

    def test_moi_phan_hoi_codex_deu_duoc_ghi_nhan(self):
        """Đây là chỗ khiến việc thăm dò nền thành thừa: hạn mức đi kèm sẵn
        trong phản hồi mà c2a vốn đã nhận."""
        src = (GOC / "services/providers/openai_oauth.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("codex_usage.ghi_nhan_tu_header(access_token"), 2,
                         "phải ghi nhận ở CẢ lần gửi đầu lẫn lần gửi lại sau refresh 401")

    def test_ghi_nhan_khong_bao_gio_lam_hong_luot_chat(self):
        """Nó nằm trên đường đi của một câu chat thật."""
        src = (GOC / "services/codex_usage.py").read_text(encoding="utf-8")
        i = src.index("def ghi_nhan_tu_header")
        self.assertIn("except Exception:", src[i:i + 700])


class GiaoDienTests(unittest.TestCase):
    TRANG = (GOC / "web/src/app/accounts/page.tsx").read_text(encoding="utf-8")

    def test_han_muc_codex_ve_TRUOC_bon_thanh_tinh_nang(self):
        i = self.TRANG.index("<KhoiHanMucCodex")
        j = self.TRANG.index("account.limits_progress?.map")
        self.assertLess(i, j, "bốn thanh tính năng không phải thứ chặn tài khoản codex")

    def test_goi_RIENG_khoi_cay_provider(self):
        """Endpoint hạn mức có thể phải ra mạng; gộp vào cây provider là bắt cả
        trang chờ nó."""
        self.assertIn("/api/accounts/codex-usage", self.TRANG)
        i = self.TRANG.index("const [healthRes, treeRes]")
        self.assertNotIn("codex-usage", self.TRANG[i:i + 400])

    def test_noi_ro_khi_token_khong_dung_loai(self):
        self.assertIn("token_khong_hop_le", self.TRANG)
        self.assertIn("token phiên đăng nhập", self.TRANG)

    def test_ve_theo_phan_tram_chu_khong_theo_so_luot(self):
        """Codex chỉ nói phần trăm đã dùng; ép vào QuotaBar (tính từ số lượt) là
        bịa ra con số."""
        i = self.TRANG.index("function ThanhCodex")
        than = self.TRANG[i:i + 1600]
        self.assertIn("con_lai_pct", than)
        self.assertNotIn("QuotaBar", than)


if __name__ == "__main__":
    unittest.main()
