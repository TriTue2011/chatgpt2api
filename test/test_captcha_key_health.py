"""Khoá captcha-solver của provider lệch với CAPTCHA_SOLVER_API_KEY.

Đây là kiểu lỗi cấu hình có triệu chứng ở CHỖ KHÁC nguyên nhân: solver trả 401,
gateway báo "không lấy được session", nên người ta đi tìm phía đăng nhập chứ
không nghĩ tới khoá. Đã mất thời gian chẩn đoán hai lần trong một tuần:

  - 07/08/2026 — Flow: `auto-login-status` trả 401, tưởng hỏng phiên Google.
  - 08/08/2026 — Claude: không tự đăng nhập lại được, tưởng hết hạn sessionKey.

Bộ kiểm này chỉ đối chiếu cấu hình, không gọi mạng. Ràng buộc quan trọng nhất
nằm ở `test_khong_ro_ri_gia_tri_khoa`: một bộ kiểm khoá mà lại in khoá ra thì
tự nó thành lỗ hổng.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import branch_health  # noqa: E402
from services.config import config  # noqa: E402

KHOA = "solver-key-that-su-dai-va-bi-mat"
KHOA_KHAC = "solver-key-cu-chua-doi"


class _Nen(unittest.TestCase):
    """Thay `config.data` và biến môi trường, trả nguyên trạng sau mỗi test."""

    def dat(self, providers: dict, env_key: str | None = KHOA) -> None:
        self._data_cu = config.data
        self._env_cu = os.environ.get("CAPTCHA_SOLVER_API_KEY")
        self.addCleanup(self._tra_lai)
        config.data = {"providers": providers}
        if env_key is None:
            os.environ.pop("CAPTCHA_SOLVER_API_KEY", None)
        else:
            os.environ["CAPTCHA_SOLVER_API_KEY"] = env_key

    def _tra_lai(self) -> None:
        config.data = self._data_cu
        if self._env_cu is None:
            os.environ.pop("CAPTCHA_SOLVER_API_KEY", None)
        else:
            os.environ["CAPTCHA_SOLVER_API_KEY"] = self._env_cu


class DoiChieuKhoaTests(_Nen):
    def test_cung_khoa_thi_khong_canh_bao(self):
        self.dat({
            "flow": {"captcha_solver_url": "http://127.0.0.1:8010",
                     "captcha_solver_api_key": KHOA},
            "claude": {"captcha_solver_url": "/api/captcha",
                       "captcha_solver_api_key": KHOA},
            "gemini_web_api": {"captcha_solver_url": "/api/captcha",
                               "captcha_solver_api_key": KHOA},
        })
        kq = branch_health.kiem_khoa_captcha()
        self.assertEqual(kq["warnings"], [])
        self.assertEqual({r["provider"] for r in kq["checked"]},
                         {"flow", "claude", "gemini_web_api"})

    def test_mot_provider_lech_thi_chi_bao_dung_no(self):
        self.dat({
            "flow": {"captcha_solver_url": "/api/captcha",
                     "captcha_solver_api_key": KHOA},
            "claude": {"captcha_solver_url": "/api/captcha",
                       "captcha_solver_api_key": KHOA_KHAC},
        })
        kq = branch_health.kiem_khoa_captcha()
        self.assertEqual(kq["warnings"],
                         [{"provider": "claude", "status": "key_mismatch"}])

    def test_provider_khong_dung_solver_thi_khong_bao_gia(self):
        """Serper, Brave… không dính gì tới solver — đừng lôi vào."""
        self.dat({
            "serper": {"api_key": "abc"},
            "brave": {"api_key": "def"},
            "nvidia_nim": {"enabled": True},
        })
        kq = branch_health.kiem_khoa_captcha()
        self.assertEqual(kq["checked"], [])
        self.assertEqual(kq["warnings"], [])

    def test_khai_url_ma_thieu_khoa(self):
        """Gọi solver không kèm Authorization — hỏng y hệt lệch khoá."""
        self.dat({"claude": {"captcha_solver_url": "/api/captcha"}})
        kq = branch_health.kiem_khoa_captcha()
        self.assertEqual(kq["warnings"],
                         [{"provider": "claude", "status": "provider_key_missing"}])

    def test_thieu_bien_moi_truong(self):
        self.dat({"claude": {"captcha_solver_url": "/api/captcha",
                             "captcha_solver_api_key": KHOA}},
                 env_key=None)
        kq = branch_health.kiem_khoa_captcha()
        self.assertFalse(kq["expected_key_configured"])
        self.assertEqual(
            kq["warnings"],
            [{"provider": "claude", "status": "CAPTCHA_SOLVER_API_KEY_missing"}])

    def test_doc_config_data_chu_khong_phai_config_get(self):
        """Chốt vào đúng khe hở đã để lọt lần trước.

        `config.get()` tự điền `providers.flow.captcha_solver_api_key` từ biến
        môi trường (config.py:1100) nhưng KHÔNG ghi ngược vào `config.data`,
        trong khi `flow_google._pool_config()` lại đọc `config.data`. Kiểm bằng
        `get()` sẽ thấy "khớp" trong khi lúc chạy thật header Authorization
        rỗng — đúng cách bộ kiểm bỏ sót sự cố 07/08.
        """
        self.dat({"flow": {"captcha_solver_url": "http://127.0.0.1:8010"}})
        self.assertEqual(
            branch_health.kiem_khoa_captcha()["warnings"],
            [{"provider": "flow", "status": "provider_key_missing"}],
            "đang kiểm trên bản đã được env điền sẵn, không phải bản đang chạy")

    def test_khoa_co_dau_khong_lam_sap_bo_kiem(self):
        """`hmac.compare_digest` ném TypeError khi chuỗi có ký tự ngoài ASCII.

        "comparing strings with non-ASCII characters is not supported" — một
        khoá có dấu sẽ biến bộ kiểm sức khoẻ thành HTTP 500, tức là đúng lúc
        cần nó nhất thì nó chết. So trên bytes thì không.
        """
        self.dat({"claude": {"captcha_solver_url": "/api/captcha",
                             "captcha_solver_api_key": "khóa-bí-mật"}},
                 env_key="khoa-bi-mat")
        self.assertEqual(branch_health.kiem_khoa_captcha()["warnings"],
                         [{"provider": "claude", "status": "key_mismatch"}])

    def test_khoa_co_dau_van_khop_duoc(self):
        self.dat({"claude": {"captcha_solver_url": "/api/captcha",
                             "captcha_solver_api_key": "khóa-bí-mật"}},
                 env_key="khóa-bí-mật")
        self.assertEqual(branch_health.kiem_khoa_captcha()["warnings"], [])

    def test_solver_rieng_khong_bi_bao_lech(self):
        """`captcha_base` giữ nguyên URL HTTPS lạ — solver riêng là hợp lệ.

        Khoá của một solver riêng KHÔNG có lý do gì phải trùng
        CAPTCHA_SOLVER_API_KEY của solver nội bộ; báo lệch ở đây là kêu oan.
        """
        self.dat({"claude": {"captcha_solver_url": "https://solver.example.com",
                             "captcha_solver_api_key": KHOA_KHAC}})
        kq = branch_health.kiem_khoa_captcha()
        self.assertEqual(kq["warnings"], [])
        self.assertEqual(
            kq["checked"],
            [{"provider": "claude", "status": "independent_solver_not_compared"}])

    def test_moi_dang_url_noi_bo_deu_duoc_so(self):
        """Ba dạng dưới đây `captcha_base` đều quy về 127.0.0.1:8010."""
        self.dat({})          # giữ nguyên trạng một lần, rồi thay tự do bên dưới
        for url in ("/api/captcha", "", "http://127.0.0.1:8010",
                    "http://captcha-solver:8010",
                    "https://vi-du.com/api/captcha"):
            with self.subTest(url=url):
                config.data = {"providers": {
                    "claude": {"captcha_solver_url": url,
                               "captcha_solver_api_key": KHOA_KHAC}}}
                self.assertEqual(
                    branch_health.kiem_khoa_captcha()["warnings"],
                    [{"provider": "claude", "status": "key_mismatch"}],
                    f"{url!r} là solver nội bộ, phải được đối chiếu")

    def test_khong_ro_ri_gia_tri_khoa(self):
        self.dat({
            "flow": {"captcha_solver_url": "/api/captcha",
                     "captcha_solver_api_key": KHOA},
            "claude": {"captcha_solver_url": "/api/captcha",
                       "captcha_solver_api_key": KHOA_KHAC},
        })
        thoi = json.dumps(branch_health.kiem_khoa_captcha(), ensure_ascii=False)
        for bi_mat in (KHOA, KHOA_KHAC):
            self.assertNotIn(bi_mat, thoi)
            self.assertNotIn(bi_mat[:8], thoi, "lộ tiền tố cũng là lộ")
        self.assertNotIn(str(len(KHOA)), thoi, "độ dài khoá cũng không được trả")


class GhepVaoCheckTests(_Nen):
    """Cảnh báo phải THẤY được, nhưng không được nhuộm đỏ cả bộ kiểm."""

    def setUp(self):
        self._ids_cu = branch_health._model_ids
        self._bm_cu = branch_health.branch_model
        self._br_cu = branch_health.BRANCHES
        branch_health._model_ids = lambda: set()
        branch_health.branch_model = lambda name, channel="": ""
        branch_health.BRANCHES = {"vision": ("Phân tích ảnh", "gma/auto")}

    def tearDown(self):
        branch_health._model_ids = self._ids_cu
        branch_health.branch_model = self._bm_cu
        branch_health.BRANCHES = self._br_cu

    def test_lech_khoa_khong_lam_ok_thanh_false(self):
        """Provider được phép dùng solver riêng — lệch là cảnh báo, không phải hỏng."""
        self.dat({"claude": {"captcha_solver_url": "/api/captcha",
                             "captcha_solver_api_key": KHOA_KHAC}})
        kq = branch_health.check()
        self.assertTrue(kq["ok"])
        self.assertEqual(kq["captcha_solver"]["warnings"],
                         [{"provider": "claude", "status": "key_mismatch"}])

    def test_tom_tat_noi_ro_hau_qua(self):
        """Nhãn `key_mismatch` không nói cho người trực biết chuyện gì sẽ hỏng."""
        self.dat({"claude": {"captcha_solver_url": "/api/captcha",
                             "captcha_solver_api_key": KHOA_KHAC}})
        tom_tat = branch_health.check()["tom_tat"]
        self.assertIn("claude", tom_tat)
        self.assertIn("CAPTCHA_SOLVER_API_KEY", tom_tat)
        self.assertIn("401", tom_tat)
        self.assertNotIn(KHOA_KHAC, tom_tat)

    def test_moi_thu_khop_thi_tom_tat_khong_them_tieng_on(self):
        self.dat({"claude": {"captcha_solver_url": "/api/captcha",
                             "captcha_solver_api_key": KHOA}})
        self.assertNotIn("captcha", branch_health.check()["tom_tat"].lower())


if __name__ == "__main__":
    unittest.main()
