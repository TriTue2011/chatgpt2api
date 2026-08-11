"""`/api/settings` không trả secret, và UI lưu lại KHÔNG làm mất secret.

Rủi ro lớn nhất của bản này không phải rò rỉ mà là **mất dữ liệu**:
`web/src/app/combos/page.tsx` GET config rồi POST NGUYÊN CẢ config trở lại.
Khi che secret được bật, payload đó mang toàn nhãn `{"is_set": true}`; thiếu
bộ lọc ghi thì lần lưu đầu tiên ghi nhãn che đè lên khoá thật — mất sạch khoá
R2, token bot, cookie Zalo, mà không có lấy một dòng lỗi.

Vì vậy phần lớn test ở đây kiểm đường GHI, không phải đường đọc.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.settings_secrets import (  # noqa: E402
    che_giau, la_nhan_che, la_truong_bi_mat, loc_ghi, xoa_theo_duong_dan,
)

CAU_HINH = {
    "base_url": "http://192.168.1.10:3030",
    "max_tokens": 4096,
    "backup": {"access_key_id": "AKIA-that", "secret_access_key": "bi-mat-r2",
               "bucket": "c2a-backup"},
    "zalo_bot_token": "token-bot-that",
    "cloudflare_tunnel_token": "token-tunnel-that",
    "providers": {
        "gemini_free": {"enabled": True, "model": "gemini-3.1-flash-lite",
                        "api_key": "khoa-1", "api_keys": ["khoa-1", "khoa-2", "khoa-3"]},
        "claude": {"captcha_solver_url": "/api/captcha",
                   "captcha_solver_api_key": "khoa-solver",
                   "profiles": ["google-abc"]},
    },
    "security": {"trusted_hosts": ["vidu.com"]},
}


class NhanDangTruongBiMatTests(unittest.TestCase):
    def test_nhan_dung_cac_truong_that(self):
        for ten in ("api_key", "api_keys", "auth-key", "secret_access_key",
                    "access_key_id", "zalo_bot_token", "cloudflare_tunnel_token",
                    "captcha_solver_api_key", "session_key", "password",
                    "cookies", "webhook_secret", "totp_seed",
                    # token dài hạn Facebook — từng lọt lưới vì đuôi "_long"
                    "user_token_long", "token_long"):
            self.assertTrue(la_truong_bi_mat(ten), f"{ten} phải bị coi là bí mật")

    def test_user_token_long_bi_che_trong_facebook(self):
        """Đo thật 11/08: user_token_long trả về web UI dạng THÔ vì luật đuôi
        chỉ khớp '_token' — token dài hạn 60 ngày của Facebook lộ ra client."""
        ra = che_giau({"facebook": {"user_token_long": "EAAB-token-that",
                                    "app_id": "123"}})
        self.assertTrue(la_nhan_che(ra["facebook"]["user_token_long"]))
        self.assertEqual(ra["facebook"]["app_id"], "123")

    def test_khong_che_nham_truong_binh_thuong(self):
        """Che nhầm là mất một ô cấu hình mà không ai hiểu vì sao."""
        for ten in ("base_url", "model", "enabled", "profiles", "max_tokens",
                    "token_limit", "captcha_solver_url", "trusted_hosts",
                    "bucket", "cookie_secure", "combo_models"):
            self.assertFalse(la_truong_bi_mat(ten), f"{ten} bị che nhầm")


class CheDuongDocTests(unittest.TestCase):
    def test_khong_con_gia_tri_bi_mat_nao_trong_phan_hoi(self):
        thoi = json.dumps(che_giau(CAU_HINH), ensure_ascii=False)
        for bi_mat in ("bi-mat-r2", "AKIA-that", "token-bot-that",
                       "token-tunnel-that", "khoa-1", "khoa-2", "khoa-3",
                       "khoa-solver"):
            self.assertNotIn(bi_mat, thoi, f"{bi_mat} vẫn lọt ra phản hồi")

    def test_van_biet_duoc_da_dat_hay_chua(self):
        ra = che_giau(CAU_HINH)
        self.assertEqual(ra["backup"]["secret_access_key"], {"is_set": True})
        self.assertEqual(ra["providers"]["gemini_free"]["api_keys"],
                         {"is_set": True, "count": 3})

    def test_chua_dat_thi_bao_is_set_false(self):
        ra = che_giau({"backup": {"secret_access_key": ""}})
        self.assertEqual(ra["backup"]["secret_access_key"], {"is_set": False})

    def test_truong_khong_bi_mat_giu_nguyen(self):
        ra = che_giau(CAU_HINH)
        self.assertEqual(ra["base_url"], "http://192.168.1.10:3030")
        self.assertEqual(ra["providers"]["claude"]["profiles"], ["google-abc"])
        self.assertEqual(ra["security"]["trusted_hosts"], ["vidu.com"])

    def test_khong_sua_ban_goc(self):
        goc = copy.deepcopy(CAU_HINH)
        che_giau(CAU_HINH)
        self.assertEqual(CAU_HINH, goc, "che_giau đã sửa vào chính config đang chạy")


class GhiKhongLamMatSecretTests(unittest.TestCase):
    """Đường quan trọng nhất của cả bản thay đổi."""

    def test_POST_lai_nguyen_config_da_che_thi_secret_van_nguyen(self):
        """Đúng kịch bản của combos/page.tsx: GET rồi POST lại toàn bộ.

        Nhãn che phải được thay lại bằng GIÁ TRỊ ĐANG CHẠY, không phải bỏ đi.
        Bỏ đi chỉ an toàn ở tầng ngoài cùng — `config.update` thay nguyên khối
        các dict top-level như `backup`, nên thiếu khoá bên trong nghĩa là xoá.
        """
        sau_loc = loc_ghi(che_giau(CAU_HINH), CAU_HINH)
        self.assertEqual(sau_loc["backup"]["secret_access_key"], "bi-mat-r2")
        self.assertEqual(sau_loc["backup"]["access_key_id"], "AKIA-that")
        self.assertEqual(sau_loc["zalo_bot_token"], "token-bot-that")
        self.assertEqual(sau_loc["providers"]["gemini_free"]["api_keys"],
                         ["khoa-1", "khoa-2", "khoa-3"])
        self.assertEqual(sau_loc["providers"]["claude"]["captcha_solver_api_key"],
                         "khoa-solver")
        # Phần không bí mật đi qua bình thường.
        self.assertEqual(sau_loc["backup"]["bucket"], "c2a-backup")
        self.assertEqual(sau_loc["providers"]["gemini_free"]["model"],
                         "gemini-3.1-flash-lite")

    def test_chua_tung_dat_thi_bo_han_chu_khong_ghi_rong(self):
        """Không có cả giá trị mới lẫn cũ → đừng ghi chuỗi rỗng đè lên."""
        sau = loc_ghi({"backup": {"secret_access_key": {"is_set": False}}}, {})
        self.assertNotIn("secret_access_key", sau["backup"])

    def test_chuoi_rong_KHONG_xoa_secret(self):
        """Ô input trống do trang chưa nạp xong là chuyện thường."""
        sau = loc_ghi({"backup": {"secret_access_key": "", "bucket": "moi"}}, {})
        self.assertNotIn("secret_access_key", sau["backup"])
        self.assertEqual(sau["backup"]["bucket"], "moi")

    def test_danh_sach_rong_KHONG_xoa_pool_khoa(self):
        sau = loc_ghi({"providers": {"gemini_free": {"api_keys": []}}}, {})
        self.assertNotIn("api_keys", sau["providers"]["gemini_free"])

    def test_gia_tri_MOI_van_ghi_duoc(self):
        sau = loc_ghi({"backup": {"secret_access_key": "khoa-r2-moi"},
                       "providers": {"gemini_free": {"api_keys": ["a", "b"]}}})
        self.assertEqual(sau["backup"]["secret_access_key"], "khoa-r2-moi")
        self.assertEqual(sau["providers"]["gemini_free"]["api_keys"], ["a", "b"])

    def test_danh_sach_lan_lon_nhan_che_thi_bo_nhan_giu_khoa_that(self):
        sau = loc_ghi({"providers": {"g": {"api_keys": ["khoa-that", {"is_set": True}]}}}, {})
        self.assertEqual(sau["providers"]["g"]["api_keys"], ["khoa-that"])

    def test_nhan_dang_nhan_che(self):
        self.assertTrue(la_nhan_che({"is_set": True}))
        self.assertTrue(la_nhan_che({"is_set": True, "count": 3}))
        self.assertFalse(la_nhan_che({}))
        self.assertFalse(la_nhan_che({"is_set": True, "value": "x"}))
        self.assertFalse(la_nhan_che("chuoi-thuong"))


class QuaConfigUpdateThatTests(unittest.TestCase):
    """Đi qua chính `config.update` — nơi logic merge phức tạp nhất.

    Các test trên chỉ chứng minh `loc_ghi` bỏ đúng trường. Test này chứng minh
    thứ thật sự quan trọng: sau một vòng GET-che → POST-toàn-bộ, cấu hình đang
    chạy vẫn còn nguyên khoá. `_merge_provider_config` có nhiều nhánh xử lý
    `api_key`/`api_keys`, và một nhánh sai ở đó không lộ ra ở tầng `loc_ghi`.
    """

    def setUp(self):
        from services.config import config
        self.config = config
        self._data_cu = config.data
        self._save_cu = config._save
        config.data = copy.deepcopy(CAU_HINH)
        config._save = lambda: None          # KHÔNG ghi đè data/config.json thật
        self.addCleanup(self._tra_lai)

    def _tra_lai(self):
        self.config.data = self._data_cu
        self.config._save = self._save_cu

    def test_vong_GET_che_roi_POST_toan_bo_van_con_nguyen_khoa(self):
        payload = loc_ghi(che_giau(self.config.get()), self.config.data)
        self.config.update(payload)
        d = self.config.data
        self.assertEqual(d["backup"]["secret_access_key"], "bi-mat-r2")
        self.assertEqual(d["backup"]["access_key_id"], "AKIA-that")
        self.assertEqual(d["zalo_bot_token"], "token-bot-that")
        self.assertEqual(d["cloudflare_tunnel_token"], "token-tunnel-that")
        self.assertEqual(d["providers"]["gemini_free"]["api_keys"],
                         ["khoa-1", "khoa-2", "khoa-3"])
        self.assertEqual(d["providers"]["claude"]["captcha_solver_api_key"],
                         "khoa-solver")

    def test_van_luu_duoc_thay_doi_khong_bi_mat_trong_cung_vong_do(self):
        """Không được bảo vệ secret bằng cách chặn luôn việc lưu cài đặt."""
        payload = loc_ghi(che_giau(self.config.get()), self.config.data)
        payload["base_url"] = "http://192.168.1.99:3030"
        payload["providers"]["gemini_free"]["model"] = "gemini-2.5-flash"
        self.config.update(payload)
        self.assertEqual(self.config.data["base_url"], "http://192.168.1.99:3030")
        self.assertEqual(self.config.data["providers"]["gemini_free"]["model"],
                         "gemini-2.5-flash")
        self.assertEqual(self.config.data["providers"]["gemini_free"]["api_keys"],
                         ["khoa-1", "khoa-2", "khoa-3"], "đổi model làm mất pool khoá")

    def test_gui_khoa_moi_that_thi_van_ghi_de(self):
        self.config.update(loc_ghi({"backup": {"secret_access_key": "r2-moi"}}, self.config.data))
        self.assertEqual(self.config.data["backup"]["secret_access_key"], "r2-moi")


class XoaPhaiTuongMinhTests(unittest.TestCase):
    def test_xoa_duoc_dung_truong_da_chi_dinh(self):
        d = copy.deepcopy(CAU_HINH)
        da_xoa = xoa_theo_duong_dan(d, ["backup.secret_access_key"])
        self.assertEqual(da_xoa, ["backup.secret_access_key"])
        self.assertEqual(d["backup"]["secret_access_key"], "")
        self.assertEqual(d["backup"]["access_key_id"], "AKIA-that",
                         "xoá một trường đá luôn trường bên cạnh")

    def test_danh_sach_khoa_thi_xoa_thanh_rong(self):
        d = copy.deepcopy(CAU_HINH)
        xoa_theo_duong_dan(d, ["providers.gemini_free.api_keys"])
        self.assertEqual(d["providers"]["gemini_free"]["api_keys"], [])

    def test_KHONG_xoa_duoc_truong_khong_phai_bi_mat(self):
        """Nếu không chặn, endpoint lưu cài đặt thành endpoint xoá cấu hình tuỳ ý."""
        d = copy.deepcopy(CAU_HINH)
        da_xoa = xoa_theo_duong_dan(d, ["base_url", "providers.gemini_free.model",
                                        "security.trusted_hosts"])
        self.assertEqual(da_xoa, [])
        self.assertEqual(d["base_url"], "http://192.168.1.10:3030")
        self.assertEqual(d["security"]["trusted_hosts"], ["vidu.com"])

    def test_duong_dan_khong_ton_tai_thi_bo_qua_yen_lang(self):
        d = copy.deepcopy(CAU_HINH)
        self.assertEqual(xoa_theo_duong_dan(d, ["khong.co.api_key", "", "..."]), [])


class NoiGoiTests(unittest.TestCase):
    def test_duong_ghi_loc_VO_DIEU_KIEN(self):
        """Lọc ghi mà đặt sau cờ thì bật cờ đọc lên là mất secret ngay."""
        src = (GOC / "api/system.py").read_text(encoding="utf-8")
        i = src.index("_changed = body.model_dump")
        than = src[i:i + 1200]
        self.assertIn("loc_ghi(_changed, config.data)", than)
        self.assertNotIn("_che_secret_bat_khong()", than,
                         "lọc ghi không được nằm sau cờ che đọc")

    def test_duong_doc_nam_sau_co(self):
        src = (GOC / "api/system.py").read_text(encoding="utf-8")
        i = src.index("async def get_settings")
        than = src[i:i + 400]
        self.assertIn("_che_secret_bat_khong()", than)

    def test_phan_hoi_cua_POST_cung_duoc_che(self):
        """POST trả nguyên config sau khi lưu — bỏ sót là che GET vẫn rò qua đây."""
        src = (GOC / "api/system.py").read_text(encoding="utf-8")
        i = src.index("async def save_settings")
        than = src[i:src.index("# ── Cloudflare Tunnel ──")]
        self.assertIn("che_giau(result)", than)

    def test_co_mac_dinh_tat(self):
        src = (GOC / "api/system.py").read_text(encoding="utf-8")
        i = src.index("def _che_secret_bat_khong")
        self.assertIn("return False", src[i:i + 900],
                      "không đọc được config thì phải coi như tắt")


if __name__ == "__main__":
    unittest.main()
