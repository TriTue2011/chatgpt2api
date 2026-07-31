"""Lớp soi code TĨNH của pipeline code (services/code_runner.kiem_tinh).

Vì sao cần lớp này: `co_the_chay()` từ chối gần hết code thật (hễ có
`from services`, `import httpx`, `import numpy`… là bỏ qua chạy thử), nên trước
đây đa số code do model viết chỉ được ĐỌC rồi phán, không có phép kiểm khách
quan nào. Soi tĩnh chạy cho MỌI code.

Test ở đây chia hai nhóm và nhóm thứ hai quan trọng hơn: BÁO OAN là bắt người
viết sửa code đang đúng — tệ hơn bỏ sót.
"""

from __future__ import annotations

import unittest

from services.code_runner import kiem_tinh


class SoiTinhBatLoi(unittest.TestCase):
    """Những ca PHẢI báo lỗi."""

    def test_loi_cu_phap_kem_so_dong(self):
        kq = kiem_tinh("def cong(a, b)\n    return a + b\n")
        self.assertIn("CÚ PHÁP", kq)
        self.assertIn("def cong(a, b)", kq)

    def test_ten_go_sai(self):
        kq = kiem_tinh("def tinh(xs):\n    result = sum(xs)\n    return resutl\n")
        self.assertIn("resutl", kq)

    def test_chu_ngoai_ascii_lot_vao_ten_bien(self):
        # Lỗi ĐÃ GẶP THẬT: dưới system prompt tiếng Việt dài, vài model rò chữ
        # Trung vào câu trả lời. Rò vào tên biến thì Python vẫn phân tích được
        # (cho phép định danh unicode) nhưng code thành vô nghĩa.
        kq = kiem_tinh("def dem(xs):\n    数量 = len(xs)\n    return 数量\n")
        self.assertIn("ASCII", kq)

    def test_goi_ham_chua_dinh_nghia(self):
        kq = kiem_tinh("def a():\n    return chua_he_co(1)\n")
        self.assertIn("chua_he_co", kq)


class SoiTinhKhongBaoOan(unittest.TestCase):
    """Những ca PHẢI im lặng — báo oan còn tệ hơn bỏ sót."""

    def _sach(self, code: str, ten: str) -> None:
        kq = kiem_tinh(code)
        self.assertEqual(kq, "", f"báo oan với {ten}: {kq}")

    def test_import_du_an_khong_bi_coi_la_loi(self):
        self._sach(
            "from services.config import config\n"
            "def lay(ten: str) -> str:\n"
            "    return str((config.data or {}).get(ten) or '')\n",
            "code cần import dự án",
        )

    def test_tieng_viet_trong_chuoi_va_chu_thich(self):
        self._sach(
            "# đếm số phần tử — chú thích tiếng Việt là chuẩn của dự án\n"
            "def dem(xs):\n"
            "    thong_bao = 'Đã đếm xong'\n"
            "    return f'{thong_bao}: {len(xs)} phần tử'\n",
            "tiếng Việt trong chuỗi/chú thích/f-string",
        )

    def test_lop_comprehension_except_global(self):
        self._sach(
            "import json, os\n"
            "TONG = 0\n"
            "class Kho:\n"
            "    def __init__(self, goc):\n"
            "        self.goc = goc\n"
            "    def doc(self):\n"
            "        global TONG\n"
            "        try:\n"
            "            with open(os.path.join(self.goc, 'a.json')) as f:\n"
            "                d = json.load(f)\n"
            "        except (OSError, ValueError) as exc:\n"
            "            return {'loi': str(exc)}\n"
            "        TONG += 1\n"
            "        return {k: v for k, v in d.items() if v}\n",
            "lớp + comprehension + except-as + global",
        )

    def test_async_decorator_walrus_type_hint(self):
        self._sach(
            "import asyncio\n"
            "from typing import Any\n"
            "def ghi_log(fn):\n"
            "    async def trong(*a, **k):\n"
            "        return await fn(*a, **k)\n"
            "    return trong\n"
            "@ghi_log\n"
            "async def lay(url: str) -> dict[str, Any]:\n"
            "    if (n := len(url)) > 5:\n"
            "        await asyncio.sleep(0)\n"
            "        return {'n': n}\n"
            "    return {}\n",
            "async + decorator + walrus + type hint",
        )

    def test_bien_gan_trong_ham_khac_van_duoc_chap_nhan(self):
        # Bộ gom tên CỐ Ý lấy rộng (mọi phạm vi) để khỏi báo oan.
        self._sach(
            "def a():\n"
            "    tam = 1\n"
            "    return tam\n"
            "def b():\n"
            "    return tam\n",
            "tên gán ở hàm khác",
        )

    def test_code_rong_khong_bao(self):
        self._sach("", "code rỗng")
        self._sach("   \n\n  ", "chỉ khoảng trắng")


if __name__ == "__main__":
    unittest.main()
