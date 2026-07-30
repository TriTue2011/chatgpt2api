"""Backend tìm kiếm MCP — trả KẾT QUẢ, không trả tên tool.

Bản cũ trả về ``{"title": <TÊN TOOL>, "snippet": text, "url": ""}``. Ba chỗ sai
cùng lúc, và cả ba đều im lặng:

1. `title` là tên tool ("search_web"), không phải tiêu đề trang.
2. `url` LUÔN rỗng → `sgk_fetch` lọc ứng viên bằng `_looks_like_pdf(url)` nên
   KHÔNG BAO GIỜ có ứng viên. Cả đường tìm sách chết đứng, mà log vẫn ghi
   "search_success results=5" — sai mà báo thành công.
3. `len(text) > 10` khiến chuỗi "Không tìm thấy kết quả." (23 ký tự) được tính là
   một kết quả.

Và nó gọi cả `get_news` + `get_current_weather` cho MỌI câu hỏi. Hai tool đó
không tìm được gì nhưng mỗi lần gọi vẫn chờ hết timeout — đo thật 30/07: một lượt
tìm 89 giây, có lượt 601 giây.
"""
from __future__ import annotations

import unittest
from unittest import mock


def _backend():
    from services.search_service import MCPSearch
    return MCPSearch()


def _goi(text_theo_tool: dict) -> tuple[list, list]:
    """Chạy search với call_mcp_tool giả. Trả (kết quả, danh sách tool đã gọi)."""
    da_goi: list[str] = []

    def fake(tool, args, **kw):
        da_goi.append(tool)
        if tool not in text_theo_tool:
            raise RuntimeError("tool không có")
        return text_theo_tool[tool]

    import services.mcp_client as mc
    with mock.patch.object(mc, "call_mcp_tool", fake, create=True):
        return _backend().search("sách giáo viên toán 4 pdf"), da_goi


TEXT_THAT = """1. Sách giáo viên Toán 4 - Kết nối tri thức
https://sytu.vn/sgv-toan-4.pdf
Trọn bộ sách giáo viên lớp 4, bản PDF.

2. Toán 4 tập hai
https://taphuan.nxbgd.vn/doc-sach/sgv-toan-4-tap-hai
Tài liệu dành cho giáo viên.
"""


class TestTraKetQuaThat(unittest.TestCase):
    def test_co_url_that_khong_phai_rong(self):
        r, _ = _goi({"search_web": TEXT_THAT})
        self.assertTrue(r, "phải có kết quả")
        self.assertTrue(all(x["url"].startswith("http") for x in r), r)

    def test_title_la_tieu_de_khong_phai_ten_tool(self):
        r, _ = _goi({"search_web": TEXT_THAT})
        tens = {"search_web", "search_all", "search", "get_news", "get_current_weather"}
        for x in r:
            self.assertNotIn(x["title"], tens, f"title vẫn là tên tool: {x}")
        self.assertIn("Sách giáo viên Toán 4", r[0]["title"])

    def test_lay_dung_url(self):
        r, _ = _goi({"search_web": TEXT_THAT})
        self.assertEqual(r[0]["url"], "https://sytu.vn/sgv-toan-4.pdf")


class TestKhongCoKetQua(unittest.TestCase):
    def test_khong_tim_thay_thi_tra_rong(self):
        """23 ký tự nên bản cũ tính là 1 kết quả thành công."""
        r, _ = _goi({"search_web": "Không tìm thấy kết quả.",
                     "search_all": "Không tìm thấy kết quả.",
                     "search": "Không tìm thấy kết quả."})
        self.assertEqual(r, [])

    def test_text_khong_co_url_thi_bo(self):
        """Kết quả tìm kiếm không có link thì không dùng được vào việc gì."""
        r, _ = _goi({"search_web": "Toán 4 rất hay\nCó nhiều bài tập\n",
                     "search_all": "", "search": ""})
        self.assertEqual(r, [])


class TestKhongGoiToolVoIch(unittest.TestCase):
    def test_khong_goi_thoi_tiet_va_tin_tuc(self):
        _, da_goi = _goi({"search_web": TEXT_THAT})
        self.assertNotIn("get_current_weather", da_goi)
        self.assertNotIn("get_news", da_goi)

    def test_dung_o_tool_dau_tien_co_ket_qua(self):
        _, da_goi = _goi({"search_web": TEXT_THAT, "search_all": TEXT_THAT})
        self.assertEqual(da_goi, ["search_web"],
                         "có kết quả rồi thì đừng gọi thêm tool")

    def test_tool_dau_rong_thi_di_tool_sau(self):
        r, da_goi = _goi({"search_web": "Không tìm thấy kết quả.",
                          "search_all": TEXT_THAT})
        self.assertTrue(r)
        self.assertEqual(da_goi, ["search_web", "search_all"])


class TestGioiHanSoKetQua(unittest.TestCase):
    def test_khong_vuot_max_results(self):
        from services.search_service import MCPSearch
        nhieu = "\n".join(f"Tiêu đề {i}\nhttps://x.tld/{i}.pdf\nmô tả {i}"
                          for i in range(10))
        import services.mcp_client as mc
        with mock.patch.object(mc, "call_mcp_tool",
                               lambda *a, **k: nhieu, create=True):
            r = MCPSearch().search("q", max_results=3)
        self.assertEqual(len(r), 3)



class TestKhongNhanLoiLamKetQua(unittest.TestCase):
    """Text LỖI có kèm URL vẫn bị coi là kết quả nếu không chặn.

    Đo thật 30/07 sau khi vá vòng một: gọi search trả về ĐÚNG MỘT "kết quả" mà
    tiêu đề là "Unexpected keyword argument [type=unexpected_keyword" và url là
    https://errors.pydantic.dev/... — tức lời gọi tool bị pydantic từ chối (định
    tuyến sang server MCP có chữ ký khác), rồi chính text lỗi lọt qua bộ tách vì
    nó CÓ url. Sai mà báo thành công.
    """

    LOI_PYDANTIC = ("1 validation error for search\n"
                    "Unexpected keyword argument [type=unexpected_keyword]\n"
                    "For further information visit https://errors.pydantic.dev/2.12/v/unexpected_keyword\n")

    def test_loi_pydantic_khong_thanh_ket_qua(self):
        r, _ = _goi({"search_web": self.LOI_PYDANTIC,
                     "search_all": "", "search": ""})
        self.assertEqual(r, [], f"text lỗi bị nhận làm kết quả: {r}")

    def test_loi_o_tool_dau_thi_di_tool_sau(self):
        r, da_goi = _goi({"search_web": self.LOI_PYDANTIC, "search_all": TEXT_THAT})
        self.assertTrue(r)
        self.assertIn("Sách giáo viên Toán 4", r[0]["title"])
        self.assertEqual(da_goi, ["search_web", "search_all"])

    def test_chan_ca_loi_jsonrpc(self):
        r, _ = _goi({"search_web": '{"error":{"code":-32602,"message":"bad params"}}',
                     "search_all": "", "search": ""})
        self.assertEqual(r, [])

if __name__ == "__main__":
    unittest.main()
