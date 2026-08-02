"""Tài khoản Flow mất phiên phải được tự đăng nhập lại, kể cả khi traffic không
bao giờ chạm tới nó.

Đo thật 02/08: tài khoản nhãn "Main" (``google-benbap115``) bị đăng xuất Google
và nằm chết ở đó. Nguyên nhân là một vòng khép kín:

  · lỗi → ``_reorder_flow_account(to_front=False)`` đẩy nó xuống CUỐI danh sách;
  · ``_next_account()`` chọn theo ưu tiên CỨNG theo thứ tự (index 0 trước, chỉ
    nhảy tiếp khi index 0 đang cooldown);
  · nên nó không bao giờ được chọn lại → không bao giờ lỗi thêm → nhánh xử lý
    lỗi của adapter tạo ảnh, ĐƯỜNG DUY NHẤT gọi ``flow_recover_and_notify``,
    không bao giờ chạm tới nó.

Suốt 24 giờ log chỉ có ``flow_account_chosen: Backup``, còn mật khẩu + TOTP của
Main vẫn nằm sẵn trong solver — khôi phục được ngay, chỉ là chẳng có gì gọi.

Vì vậy phép đo quan trọng nhất ở đây là ``test_vong_sau_toi_luot_profile_cuoi``:
bộ quét phải tới được tài khoản nằm CUỐI danh sách, đúng chỗ mà cơ chế cũ bỏ sót.
"""
from __future__ import annotations

import pathlib
import sys
import types
import unittest

GOC = pathlib.Path(__file__).resolve().parents[1]

import services.account_recovery as ar  # noqa: E402
import services.flow_session_scheduler as fss  # noqa: E402


def _gia_lap_pool(accounts: list[dict]) -> None:
    """Cắm module flow_google giả — bản thật cần curl_cffi."""
    mod = types.ModuleType("services.image_providers.flow_google")
    mod._pool_config = lambda: {"accounts": accounts}  # type: ignore[attr-defined]
    sys.modules["services.image_providers.flow_google"] = mod


class TestDanhSachProfile(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("services.image_providers.flow_google", None)

    def test_chi_lay_google_bo_disabled_giu_thu_tu(self):
        _gia_lap_pool([
            {"profile": "google-backup", "label": "Backup"},
            {"profile": "fx-khac", "label": "Không phải Google"},
            {"profile": "google-tat", "label": "Đã tắt", "disabled": True},
            {"profile": "google-backup", "label": "Trùng"},
            {"profile": "google-main", "label": "Main"},
        ])
        self.assertEqual(fss._profiles(), ["google-backup", "google-main"])

    def test_khong_co_tai_khoan_thi_tra_rong(self):
        _gia_lap_pool([])
        self.assertEqual(fss._profiles(), [])


class TestQuetPhien(unittest.TestCase):
    def setUp(self):
        self.goi_khoi_phuc: list[str] = []
        self.da_kiem: list[str] = []
        self._ok_that = ar._flow_session_ok
        self._recover_that = ar.flow_recover_and_notify
        fss._last_check.clear()

    def tearDown(self):
        ar._flow_session_ok = self._ok_that
        ar.flow_recover_and_notify = self._recover_that
        sys.modules.pop("services.image_providers.flow_google", None)
        fss._last_check.clear()

    def _cai_dat(self, accounts: list[dict], phien_song: set[str]) -> None:
        _gia_lap_pool(accounts)

        def _ok(profile: str) -> bool:
            self.da_kiem.append(profile)
            return profile in phien_song

        ar._flow_session_ok = _ok
        ar.flow_recover_and_notify = lambda p, reason="": self.goi_khoi_phuc.append(p)

    def test_chi_khoi_phuc_profile_mat_phien(self):
        self._cai_dat(
            [{"profile": "google-song"}, {"profile": "google-chet"}],
            phien_song={"google-song"},
        )
        fss._scan_once()
        self.assertEqual(self.da_kiem, ["google-song", "google-chet"])
        self.assertEqual(self.goi_khoi_phuc, ["google-chet"])

    def test_ton_trong_tran_moi_vong(self):
        """Kiểm phiên phải mở trình duyệt — không được quét cả pool một lượt."""
        self._cai_dat([{"profile": f"google-{i}"} for i in range(5)], phien_song=set())
        fss._scan_once()
        self.assertEqual(len(self.da_kiem), fss._max_per_cycle())

    def test_vong_sau_toi_luot_profile_cuoi(self):
        """ĐÂY là lỗ hổng cũ: tài khoản nằm cuối danh sách phải tới lượt.

        Vòng 1 kiểm 2 cái đầu; vòng 2 (đã qua khoảng cách tối thiểu) phải kiểm
        cái CUỐI — thứ mà `_next_account` ưu-tiên-cứng không bao giờ chọn tới.
        """
        self._cai_dat(
            [{"profile": "google-a"}, {"profile": "google-b"}, {"profile": "google-cuoi"}],
            phien_song={"google-a", "google-b"},
        )
        fss._scan_once()
        self.assertNotIn("google-cuoi", self.da_kiem)

        # Giả lập đã qua khoảng cách tối thiểu giữa 2 lần kiểm cùng profile.
        for p in list(fss._last_check):
            fss._last_check[p] -= fss._PER_ACCOUNT_MIN_GAP_S + 1
        self.da_kiem.clear()
        fss._scan_once()
        self.assertIn("google-cuoi", self.da_kiem)
        self.assertEqual(self.goi_khoi_phuc, ["google-cuoi"])

    def test_loi_mot_profile_khong_chan_nhung_cai_sau(self):
        def _no(profile: str) -> bool:
            self.da_kiem.append(profile)
            raise RuntimeError("solver sập")

        self._cai_dat([{"profile": "google-a"}, {"profile": "google-b"}], phien_song=set())
        ar._flow_session_ok = _no
        fss._scan_once()  # không được ném ra ngoài
        self.assertEqual(self.da_kiem, ["google-a", "google-b"])

    def test_tat_duoc_thi_khong_quet(self):
        self._cai_dat([{"profile": "google-chet"}], phien_song=set())
        that = fss.is_enabled
        fss.is_enabled = lambda: False
        try:
            fss._scan_once()
        finally:
            fss.is_enabled = that
        self.assertEqual(self.da_kiem, [])
        self.assertEqual(self.goi_khoi_phuc, [])


class TestDuocNoiVaoAppStartup(unittest.TestCase):
    def test_app_goi_start(self):
        code = "\n".join(
            l for l in (GOC / "api" / "app.py").read_text("utf-8").splitlines()
            if not l.lstrip().startswith("#")
        )
        self.assertIn("from services.flow_session_scheduler import start", code)
        self.assertIn("start_flow_session_scan()", code)


if __name__ == "__main__":
    unittest.main()
