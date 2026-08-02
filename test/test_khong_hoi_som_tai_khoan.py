"""Tài khoản đang nghỉ CHƯA tới hạn thì không được bật lại `active`.

ĐO THẬT trên máy chủ 02/08, 11:06 UTC — cả 7 tài khoản Codex:

    status=active | restore_at=2026-08-03T06:00:42   (còn 19 giờ nữa mới hồi)
    status=active | restore_at=2026-08-03T11:01:11
    status=active | restore_at=2026-08-03T10:35:50
    status=active | restore_at=2026-08-03T10:40:52
    status=active | restore_at=2026-08-02T22:00:32

`active` nhưng hạn nghỉ còn ở tương lai là mâu thuẫn, và đây là đường đi:

  1. Cú 429 usage_limit của Codex → `status=limited` + `restore_at` lấy từ header
     `x-codex-primary-reset-at` (services/providers/openai_oauth.py).
  2. `api/support.py` mỗi 5 phút refresh MỌI tài khoản `limited`.
  3. `OpenAIBackendAPI.get_user_info()` tính `status` từ hạn mức **ẢNH**
     (`_extract_quota_and_restore_at` chỉ đọc `feature_name == "image_gen"`),
     thấy còn lượt tạo ảnh → trả `status="active"`.
  4. Tài khoản cạn quota TEXT được bật lại sau 5 phút.
  5. Lượt chat sau lấy nó ra. `_handle_openai_oauth_chat` thử tới 8 tài khoản
     một lượt ⇒ mỗi câu chat đốt cả loạt 429 THẬT trước khi rơi xuống provider
     kế tiếp — đúng cái chủ máy thấy: "mỗi lượt chat đang ăn một cú 429".

Hai đồng hồ khác nhau: hạn mức ảnh của chatgpt.com và quota text của Codex.
Đồng hồ ảnh vẫn được cập nhật `quota`/`limits_progress`/email như cũ — nó chỉ
không còn quyền xoá hạn nghỉ mà upstream đã đặt.
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.account_service import giu_han_nghi, han_nghi_chua_toi  # noqa: E402


def _iso(delta_hours: float, *, tz: bool = False) -> str:
    t = datetime.now(timezone.utc) + timedelta(hours=delta_hours)
    return t.isoformat() if tz else t.replace(tzinfo=None).isoformat()


# Nguyên văn thứ get_user_info() trả về cho một tài khoản còn lượt tạo ảnh.
KQ_REFRESH = {
    "email": "mitbap0610@gmail.com",
    "user_id": "u-1",
    "plan": "plus",
    "quota": 25,
    "image_quota_unknown": False,
    "limits_progress": [{"feature_name": "image_gen", "remaining": 25}],
    "default_model_slug": "gpt-5-5",
    "restore_at": None,
    "status": "active",
}


class HanNghiChuaToiTests(unittest.TestCase):
    def test_dang_nghi_va_han_o_tuong_lai(self):
        self.assertTrue(han_nghi_chua_toi({"status": "limited", "restore_at": _iso(19)}))

    def test_han_da_qua_thi_het_nghi(self):
        self.assertFalse(han_nghi_chua_toi({"status": "limited", "restore_at": _iso(-1)}))

    def test_khong_co_han_thi_de_tang_khac_quyet(self):
        """`revive_stuck_limited` lo ca không có mốc thời gian — đừng giành."""
        self.assertFalse(han_nghi_chua_toi({"status": "limited", "restore_at": None}))
        self.assertFalse(han_nghi_chua_toi({"status": "limited"}))

    def test_khong_phai_limited_thi_khong_lien_quan(self):
        for st in ("active", "disabled", "error", "deactivated", ""):
            self.assertFalse(han_nghi_chua_toi({"status": st, "restore_at": _iso(19)}), st)

    def test_han_khong_doc_duoc_thi_coi_nhu_khong_co(self):
        self.assertFalse(han_nghi_chua_toi({"status": "limited", "restore_at": "hôm nào đó"}))

    def test_nhan_ca_han_co_mui_gio(self):
        self.assertTrue(han_nghi_chua_toi({"status": "limited", "restore_at": _iso(19, tz=True)}))
        self.assertTrue(han_nghi_chua_toi(
            {"status": "limited", "restore_at": _iso(19, tz=True).replace("+00:00", "Z")}))

    def test_dau_vao_rac_thi_khong_no(self):
        for x in (None, "", 5, [], {}):
            self.assertFalse(han_nghi_chua_toi(x))


class GiuHanNghiTests(unittest.TestCase):
    def test_dang_nghi_thi_BO_status_va_restore_at(self):
        ra = giu_han_nghi({"status": "limited", "restore_at": _iso(19)}, dict(KQ_REFRESH))
        self.assertNotIn("status", ra)
        self.assertNotIn("restore_at", ra)

    def test_van_cap_nhat_quota_email_limits(self):
        """Đồng hồ ảnh không bị chặn — nó chỉ mất quyền xoá hạn nghỉ."""
        ra = giu_han_nghi({"status": "limited", "restore_at": _iso(19)}, dict(KQ_REFRESH))
        self.assertEqual(ra["quota"], 25)
        self.assertEqual(ra["email"], "mitbap0610@gmail.com")
        self.assertEqual(ra["limits_progress"], KQ_REFRESH["limits_progress"])
        self.assertEqual(ra["plan"], "plus")

    def test_het_han_thi_refresh_duoc_bat_lai_active(self):
        ra = giu_han_nghi({"status": "limited", "restore_at": _iso(-1)}, dict(KQ_REFRESH))
        self.assertEqual(ra["status"], "active")

    def test_tai_khoan_binh_thuong_thi_khong_can_thiep(self):
        cu = {"status": "active", "restore_at": None}
        self.assertEqual(giu_han_nghi(cu, dict(KQ_REFRESH)), KQ_REFRESH)

    def test_khong_co_tai_khoan_cu_thi_giu_nguyen(self):
        self.assertEqual(giu_han_nghi(None, dict(KQ_REFRESH)), KQ_REFRESH)

    def test_khong_sua_dict_goc(self):
        goc = dict(KQ_REFRESH)
        giu_han_nghi({"status": "limited", "restore_at": _iso(19)}, goc)
        self.assertEqual(goc["status"], "active")   # bản gốc còn nguyên


class BoDem5PhutChiDoTaiKhoanDenHanTests(unittest.TestCase):
    """`list_limited_tokens(due_only=True)` — thôi gọi upstream cho tài khoản
    còn đang nghỉ (vừa tốn request, vừa là chỗ đồng hồ ảnh bật `active` sớm)."""

    def setUp(self):
        from services.account_service import AccountService
        self.svc = AccountService.__new__(AccountService)
        from threading import Lock
        self.svc._lock = Lock()
        self.svc._accounts = {
            "t_con_nghi": {"access_token": "t_con_nghi", "status": "limited",
                           "restore_at": _iso(19)},
            "t_den_han": {"access_token": "t_den_han", "status": "limited",
                          "restore_at": _iso(-2)},
            "t_khong_moc": {"access_token": "t_khong_moc", "status": "limited",
                            "restore_at": None},
            "t_khoe": {"access_token": "t_khoe", "status": "active",
                       "restore_at": None},
        }

    def test_mac_dinh_van_tra_het_nhu_cu(self):
        self.assertEqual(sorted(self.svc.list_limited_tokens()),
                         ["t_con_nghi", "t_den_han", "t_khong_moc"])

    def test_due_only_bo_tai_khoan_con_nghi(self):
        ra = self.svc.list_limited_tokens(due_only=True)
        self.assertNotIn("t_con_nghi", ra)
        self.assertIn("t_den_han", ra)
        self.assertIn("t_khong_moc", ra)     # không có mốc → vẫn dò như cũ
        self.assertNotIn("t_khoe", ra)


class BoDemDaDoiSangDueOnlyTests(unittest.TestCase):
    def test_api_support_goi_due_only(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "api" / "support.py").read_text("utf-8")
        self.assertIn("list_limited_tokens(due_only=True)", src)

    def test_fetch_remote_info_di_qua_giu_han_nghi(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "services" / "account_service.py").read_text("utf-8")
        self.assertIn("giu_han_nghi(self.get_account(access_token), result)", src)


if __name__ == "__main__":
    unittest.main()
