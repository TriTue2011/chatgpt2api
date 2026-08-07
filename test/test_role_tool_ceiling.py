"""Trần nhóm chức năng theo VAI trên /v1/chat.

Báo cáo bảo mật 07/08 (report 4 Critical): endpoint chỉ gắn _principal, không
kiểm role → bearer 'user' hợp lệ chạm được HA/SSH/ghi cấu hình khi admin chưa
cấu hình ha_allowed_groups. _effective_allowed_groups đặt trần server-side.
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")


class RoleCeilingTests(unittest.TestCase):
    def setUp(self):
        from api.ai import _effective_allowed_groups, _DANGER_GROUPS
        self.eff = _effective_allowed_groups
        self.danger = _DANGER_GROUPS

    def test_admin_khong_tran_giu_hanh_vi_cu(self):
        # admin + không cấu hình gì → None (full, như trước).
        self.assertIsNone(self.eff("admin", None, None))

    def test_user_bi_cat_nhom_nguy_hiem(self):
        got = self.eff("user", None, None)
        self.assertIsNotNone(got)
        for d in self.danger:
            self.assertNotIn(d, got, f"user không được nhóm {d}")
        self.assertIn("web", got, "vẫn giữ nhóm đọc/tra cứu")

    def test_user_giao_voi_ha_allowed_groups(self):
        # admin cấu hình ha_allowed_groups = {web, homeassistant}; user chỉ còn web.
        got = self.eff("user", {"web", "homeassistant"}, None)
        self.assertEqual(got, ["web"])

    def test_client_chi_thu_hep_them(self):
        # user + client tự khai {web, wiki} → giao, không mở rộng ra danh sách nguy hiểm.
        got = self.eff("user", None, {"web", "wiki", "homeassistant"})
        self.assertIn("web", got)
        self.assertIn("wiki", got)
        self.assertNotIn("homeassistant", got, "client không mở rộng vượt trần vai")

    def test_admin_van_ton_trong_ha_allowed_groups(self):
        # admin nhưng cấu hình ha_allowed_groups → vẫn bị giới hạn theo cấu hình đó.
        got = self.eff("admin", {"web"}, None)
        self.assertEqual(got, ["web"])


if __name__ == "__main__":
    unittest.main()
