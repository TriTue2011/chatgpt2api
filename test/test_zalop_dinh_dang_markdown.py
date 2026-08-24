"""Markdown của model → định dạng Zalo: đọc THEO DÒNG, không lệch, không lọt dấu.

Bản cũ quét cả bài bằng một ngăn xếp dấu mở/đóng. Một dấu `*` lẻ — mà dấu đầu
dòng kiểu `* mục` thì luôn lẻ — làm lệch ngăn xếp cho TOÀN BỘ phần còn lại.

Đo thật trên tin bot gửi lúc 06:26 ngày 24/08/2026 (log máy chủ, bản dội về của
chính Zalo): người dùng nhận nguyên chuỗi `## Goose là gì?` và `**1**. MCP rất
mạnh`, còn các dòng gạch đầu dòng thì mất sạch dấu chấm. Đó là ba triệu chứng
của cùng một nguyên nhân.

Các test dưới đây khoá đúng những chỗ đó, cộng một vòng kiểm chung: mọi vùng
định dạng phải nằm gọn trong chuỗi và phải có chữ để tô — vùng rỗng hay vùng
tràn là thứ Zalo có thể từ chối cả tin, mà từ chối thì im lặng.
"""
from __future__ import annotations

import unittest

from services.zalo_markdown import _js_len, markdown_to_zalo_message


def _md(text: str, **kw):
    return markdown_to_zalo_message(text, color="orange", size="normal", **kw)


class DauSaoDauDongTests(unittest.TestCase):
    """`* mục` là DẤU ĐẦU DÒNG, không phải mở đầu chữ nghiêng."""

    GOC = "Điểm mạnh:\n\n* Chạy local\n* Có CLI\n* Nhiều mô hình\n"

    def test_thanh_danh_sach_chu_khong_thanh_nghieng(self):
        ra = _md(self.GOC)
        self.assertEqual([s["st"] for s in ra["styles"]], ["lst_1"] * 3)

    def test_khong_nuot_chu_va_khong_de_lai_khoang_thua(self):
        ra = _md(self.GOC)
        for dong in ("Chạy local", "Có CLI", "Nhiều mô hình"):
            self.assertIn("\n" + dong, "\n" + ra["msg"])
        self.assertNotIn(" Chạy local", ra["msg"], "còn sót khoảng trắng của dấu *")

    def test_dau_le_khong_keo_theo_phan_sau(self):
        """Một `*` lẻ giữa bài không được nuốt tiêu đề và chữ đậm phía dưới."""
        ra = _md("Ghi chú * lưu ý\n\n## Tiêu đề\nCó **đậm** ở đây")
        self.assertNotIn("##", ra["msg"])
        self.assertNotIn("**", ra["msg"])
        self.assertIn("Tiêu đề", ra["msg"])


class DauTrongTieuDeVaTrichDanTests(unittest.TestCase):
    """Dấu nằm TRONG tiêu đề / trích dẫn cũng phải được bóc."""

    def test_dam_trong_tieu_de(self):
        ra = _md("## Goose là **gì**?")
        self.assertNotIn("**", ra["msg"])
        self.assertEqual(ra["msg"], "Goose là gì?")

    def test_dam_trong_trich_dan(self):
        ra = _md("> Goose là agent **mở**.")
        self.assertNotIn("**", ra["msg"])


class BangVaKhoiCodeTests(unittest.TestCase):
    """Zalo không có bảng, không có khối code — phải dịch sang thứ đọc được."""

    def test_bang_khong_con_gach_dung(self):
        ra = _md("| Goose | Ben Bắp |\n|-|-|\n| local | gia đình |")
        self.assertNotIn("|", ra["msg"])
        self.assertIn("Goose", ra["msg"])
        self.assertIn("gia đình", ra["msg"])

    def test_hang_ngan_cach_bi_bo_han_khong_de_dong_trong(self):
        ra = _md("| A | B |\n|-|-|\n| 1 | 2 |")
        self.assertEqual(len(ra["msg"].split("\n")), 2, ra["msg"])

    def test_rao_code_va_nhan_ngon_ngu_bi_bo(self):
        ra = _md("Chạy:\n\n```bash\ndocker restart c2a\n```\n\nXong.")
        self.assertNotIn("```", ra["msg"])
        self.assertNotIn("bash", ra["msg"])
        self.assertIn("docker restart c2a", ra["msg"])

    def test_dau_trong_khoi_code_giu_nguyen(self):
        ra = _md("```\nls *.py\n```")
        self.assertIn("ls *.py", ra["msg"])


class VungDinhDangKhongTranTests(unittest.TestCase):
    """Bỏ '1. ' khỏi dòng thì vùng đậm của dòng đó phải ngắn lại theo.

    Bản cũ chỉ dời `start`, không sửa `len`, nên `**1. mục**` để lại vùng đậm
    dài 15 trên một dòng chỉ còn 12 ký tự — nó tràn sang dòng kế.
    """

    def test_dam_ca_dong_danh_so_khong_tran_sang_dong_sau(self):
        ra = _md("**1. MCP rất mạnh**\nGoose tích hợp sâu.")
        for s in ra["styles"]:
            doan = ra["msg"][s["start"]: s["start"] + s["len"]]
            self.assertNotIn("\n", doan, f"vùng {s} tràn sang dòng khác")


class NghiengBangGachDuoiTests(unittest.TestCase):
    def test_gach_duoi_don_thanh_nghieng(self):
        ra = _md("Đây là _rất quan trọng_ nhé")
        self.assertNotIn("_", ra["msg"])
        self.assertIn("i", [s["st"] for s in ra["styles"]])

    def test_ten_ham_co_gach_duoi_khong_bi_bien_dang(self):
        """`send_message` / `zalo_personal` không được thành chữ nghiêng."""
        ra = _md("Hàm send_message trong zalo_personal đó anh")
        self.assertEqual(ra["msg"], "Hàm send_message trong zalo_personal đó anh")
        self.assertEqual(ra["styles"], [])


class DuongKeNgangTests(unittest.TestCase):
    def test_ba_dau_gach_thanh_duong_ke(self):
        ra = _md("Phần một\n\n---\n\nPhần hai")
        self.assertNotIn("---", ra["msg"])
        self.assertIn("─", ra["msg"])


class MoiVungPhaiHopLeTests(unittest.TestCase):
    """Vòng kiểm chung cho cả một rổ văn bản kiểu model hay viết."""

    RO = [
        "Điểm mạnh:\n\n* Một\n* Hai\n",
        "## Tiêu đề\nCó **đậm**, có *nghiêng*, có `mã`.\n",
        "| A | B |\n|-|-|\n| 1 | 2 |\n",
        "```py\nprint('*')\n```\n",
        "1. Một\n2. Hai\n   - con\n",
        "> trích **dẫn**\n\n---\n\nXem [tài liệu](https://x.vn/a) nhé",
        "**1. MCP rất mạnh**\nDòng sau.",
        "Dấu lẻ * ở giữa và _ ở đây",
        "Nhiệt độ: **28°C**, ẩm **65%** 🌡️ emoji ngoài BMP 𝟙",
    ]

    def test_khong_lot_dau_markdown_va_vung_nam_gon_trong_chuoi(self):
        for goc in self.RO:
            ra = _md(goc)
            tran = _js_len(ra["msg"])
            self.assertNotIn("**", ra["msg"], goc)
            self.assertNotIn("```", ra["msg"], goc)
            for s in ra["styles"]:
                self.assertGreater(s["len"], 0, f"vùng rỗng trong {goc!r}")
                self.assertGreaterEqual(s["start"], 0, goc)
                self.assertLessEqual(s["start"] + s["len"], tran,
                                     f"vùng {s} tràn khỏi chuỗi trong {goc!r}")


if __name__ == "__main__":
    unittest.main()
