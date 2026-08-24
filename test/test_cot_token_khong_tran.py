"""Token của nhà cung cấp dài dần — cột lưu nó không được có trần.

Đo thật 24/08/2026 trên máy chủ: sáu lần trong một giờ, mỗi lần làm mới token
ChatGPT đều đổ

    psycopg2.errors.StringDataRightTruncation:
    value too long for type character varying(2048)

Token dài nhất đang lưu trong DB lúc đó là 1.964 ký tự — sát trần 2.048. Hỏng ở
đây không chỉ mất token: lượt chat đi qua provider đó chết theo, rồi rơi xuống
model dự phòng yếu hơn (đo 08:56 — bốn provider hỏng liên tiếp, câu trả lời tới
sau 52 giây và chọn nhầm công cụ).

`Base.metadata.create_all` chỉ tạo bảng CÒN THIẾU, không sửa cột của bảng đã có.
Nên đổi khai báo model là đủ cho máy mới, còn máy đang chạy phải có bước nới cột
lúc khởi động.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth-key")

from services.storage.database_storage import (  # noqa: E402
    AccountModel,
    DatabaseStorageBackend,
)


class KhaiBaoCotTests(unittest.TestCase):
    def test_access_token_khong_con_tran_do_dai(self):
        cot = AccountModel.__table__.c.access_token
        self.assertIsNone(getattr(cot.type, "length", None),
                          "đặt trần độ dài là hẹn giờ cho lỗi cũ quay lại")

    def test_van_giu_rang_buoc_khong_trung(self):
        self.assertTrue(AccountModel.__table__.c.access_token.unique)


class LuuTokenDaiTests(unittest.TestCase):
    """Vòng lưu–đọc với token dài hơn trần cũ."""

    def setUp(self):
        self.thu_muc = tempfile.TemporaryDirectory()
        tep = Path(self.thu_muc.name) / "thu.sqlite"
        self.kho = DatabaseStorageBackend(f"sqlite:///{tep}")

    def tearDown(self):
        self.thu_muc.cleanup()

    def test_token_4000_ky_tu_van_luu_va_doc_lai_duoc(self):
        token = "eyJ" + "a" * 4000
        self.kho.save_accounts([{"access_token": token, "email": "x@y.z"}])
        ra = self.kho.load_accounts()
        self.assertEqual(len(ra), 1)
        self.assertEqual(ra[0]["access_token"], token)

    def test_sqlite_thi_khong_dong_toi_schema(self):
        """Bước nới cột chỉ dành cho Postgres; chạy lại nhiều lần cũng không sao."""
        self.kho._noi_cot_access_token()
        self.kho._noi_cot_access_token()
        self.assertEqual(self.kho.load_accounts(), [])


if __name__ == "__main__":
    unittest.main()
