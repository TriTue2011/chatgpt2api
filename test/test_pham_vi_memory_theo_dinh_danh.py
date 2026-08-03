"""Kho ký ức phải theo DANH TÍNH ĐÃ XÁC THỰC, không theo field `user` client gửi.

Lỗ đã dựng lại trên mã cũ: `MemoryService.prepare` lấy khoá kho từ
`body["user"]` — field chuẩn OpenAI, do người gọi tự khai. Một bearer token hợp
lệ chỉ cần gửi `user="<id người khác>"` là đọc được ký ức người đó (và ghi đè
vào kho đó). Xác thực không cứu được: token hợp lệ nhưng chọn kho của người khác.

Hai lối cố tình giữ kho cũ (chưa migration dữ liệu 1.162 bản ghi hiện có):
đường nội bộ không có `_principal`, và admin không khai `user`.
"""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.memory_service import MemoryService  # noqa: E402

GOC = pathlib.Path(__file__).resolve().parents[1]


class KhoaKhoTheoDanhTinh(unittest.TestCase):
    def setUp(self):
        self.ms = MemoryService()
        p = mock.patch.object(type(self.ms), "_cfg",
                              new_callable=mock.PropertyMock,
                              return_value={})
        p.start()
        self.addCleanup(p.stop)

    def _kho(self, **body) -> str:
        return self.ms._khoa_kho(body)

    # ---------------------------------------------------------------- lỗ cũ
    def test_client_KHONG_the_chon_kho_nguoi_khac(self):
        """Đúng ca khai thác: token của 'u_b' khai user='u_a'."""
        kho_a = self._kho(_principal="u_a")
        kho_b_gia_dang = self._kho(_principal="u_b", user="u_a")
        self.assertNotEqual(kho_b_gia_dang, kho_a)
        self.assertTrue(kho_b_gia_dang.startswith("u_b"), kho_b_gia_dang)

    def test_client_KHONG_the_cham_kho_chung(self):
        """Khai user='chatgpt2api' cũng không với tới kho mặc định."""
        self.assertNotEqual(self._kho(_principal="u_b", user="chatgpt2api"),
                            "chatgpt2api")

    def test_client_KHONG_the_gia_mao_principal(self):
        """`_principal` client gửi bị api/ai.py gán đè — chốt bằng mã nguồn."""
        src = (GOC / "api" / "ai.py").read_text("utf-8")
        i = src.index('payload["_principal"]')
        # Phải là phép GÁN từ identity, không phải đọc từ payload client.
        self.assertIn('payload["_principal"] = str(identity.get("id") or "")',
                      src[i - 40:i + 120])

    # ------------------------------------------------------- tách theo người
    def test_hai_danh_tinh_hai_kho(self):
        self.assertNotEqual(self._kho(_principal="u_a"), self._kho(_principal="u_b"))

    def test_user_la_khoa_con_trong_pham_vi(self):
        """Một danh tính vẫn tách được người dùng cuối của chính nó."""
        a1 = self._kho(_principal="u_a", user="e1")
        a2 = self._kho(_principal="u_a", user="e2")
        self.assertNotEqual(a1, a2)
        self.assertTrue(a1.startswith("u_a") and a2.startswith("u_a"))

    # --------------------------------------------------- giữ nguyên kho cũ
    def test_duong_noi_bo_giu_kho_mac_dinh(self):
        """Agent runtime / scheduler không qua HTTP → không có danh tính."""
        self.assertEqual(self._kho(), "chatgpt2api")
        self.assertEqual(self._kho(user="bat_ky"), "chatgpt2api")

    def test_admin_khong_khai_user_giu_kho_chung(self):
        self.assertEqual(self._kho(_principal="admin"), "chatgpt2api")

    def test_admin_khai_user_thi_tach_ra(self):
        self.assertNotEqual(self._kho(_principal="admin", user="e1"), "chatgpt2api")

    def test_ten_kho_mac_dinh_theo_config(self):
        with mock.patch.object(type(self.ms), "_cfg",
                               new_callable=mock.PropertyMock,
                               return_value={"user_id": "nha_toi"}):
            self.assertEqual(self._kho(), "nha_toi")
            self.assertEqual(self._kho(_principal="admin"), "nha_toi")


class PrepareDungKhoaKho(unittest.TestCase):
    """prepare() phải đi qua _khoa_kho, không tự đọc lại body['user']."""

    def test_recall_nhan_khoa_theo_danh_tinh(self):
        ms = MemoryService()
        body = {
            "model": "auto",
            "_principal": "u_b",
            "user": "u_a",
            "messages": [{"role": "user", "content": "ghi chú dài đủ để recall"}],
        }
        with mock.patch.object(ms, "recall", return_value=[]) as r:
            ctx = ms.prepare(body)
        self.assertIsNotNone(ctx)
        self.assertEqual(r.call_args[0][1], "u_b:u_a")
        self.assertEqual(ctx.user_id, "u_b:u_a")

    def test_khong_con_doc_thang_body_user(self):
        src = (GOC / "services" / "memory_service.py").read_text("utf-8")
        self.assertNotIn('str(body.get("user") or self._cfg.get("user_id")', src)


if __name__ == "__main__":
    unittest.main()
