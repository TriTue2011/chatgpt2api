"""Năm model chốt cho tài khoản Free phải có mặt trong GET /v1/models.

Bối cảnh (chủ máy chốt 08/08/2026, có test chạy thật):
    cgf/gpt-5-5-instant · gma/3.5-flash · claude/auto · claude/sonnet-5 · cx/gpt-5.6-terra

Ba trong năm cái đó ĐỊNH TUYẾN được nhưng không được LIỆT KÊ — hai chuyện khác
nhau. Không có trong danh sách thì không chọn được trong giao diện và không đưa
vào `enabled_models` được, dù gọi thẳng bằng API vẫn chạy:

* `gma/3.5-flash` có trong `_GMA_ALIASES` (đo thật: trả OK, adapter gọi
  BASIC_FLASH) nhưng `gma_models` chỉ liệt kê 3.1-*;
* `claude/sonnet-5` có trong `CLAUDE_MODEL_ALIASES` và có ở `/v1/claude/models`,
  nhưng thiếu ở danh sách chính — hai danh sách lệch nhau;
* `cx/gpt-5.6-terra`: hậu tố sau `cx/` được truyền THẲNG sang Codex nên vốn
  route được, chỉ thiếu trong danh sách.
"""
import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

MODEL_FREE = [
    "cgf/gpt-5-5-instant",
    "gma/3.5-flash",
    "claude/auto",
    "claude/sonnet-5",
    "cx/gpt-5.6-terra",
]


def _ids() -> set[str]:
    """Danh sách model TĨNH, không gọi mạng.

    `list_models()` có nhánh dò provider qua HTTP; test đơn vị không được phụ
    thuộc vào đó, nên đọc thẳng mã nguồn của các danh sách khai cứng.
    """
    from services.protocol import openai_v1_models as m
    src = Path(m.__file__).read_text(encoding="utf-8")
    return src


class DanhSachModelTests(unittest.TestCase):
    def test_du_nam_model_chot_cho_free(self):
        src = _ids()
        for mid in MODEL_FREE:
            if mid == "claude/sonnet-5":
                # Dựng từ vòng lặp `for b in [...]` nên không có chuỗi đầy đủ.
                self.assertIn('"sonnet-5"', src, "claude/sonnet-5 thiếu trong danh sách chính")
                continue
            self.assertIn(f'"{mid}"', src, f"{mid} chưa có trong GET /v1/models")

    def test_sonnet_5_dong_bo_giua_hai_danh_sach(self):
        """`/v1/models` và `/v1/claude/models` phải cùng biết `sonnet-5`.

        Đây chính là kiểu lệch đã xảy ra: alias map và endpoint riêng của Claude
        có sonnet-5, còn danh sách chính thì không.
        """
        chinh = _ids()
        claude_src = (GOC / "api/claude.py").read_text(encoding="utf-8")
        self.assertIn('"sonnet-5"', claude_src)
        self.assertIn('"sonnet-5"', chinh)

    def test_alias_gma_va_danh_sach_khop_nhau(self):
        """Mọi `gma/x` được liệt kê đều phải giải được qua _GMA_ALIASES.

        Liệt kê một tên mà adapter không hiểu là tái diễn đúng lỗi
        `gma_unknown_model_fallback`: người dùng chọn được trong giao diện,
        nhận HTTP 200, nhưng câu trả lời đến từ model khác.
        """
        import re
        chinh = _ids()
        khoi = re.search(r"gma_models = \[(.*?)\]", chinh, re.S)
        self.assertIsNotNone(khoi, "không tìm thấy gma_models")
        ten = re.findall(r'"gma/([^"]+)"', khoi.group(1))
        self.assertIn("3.5-flash", ten)

        gw = (GOC / "api/gemini_web.py").read_text(encoding="utf-8")
        alias = re.search(r"_GMA_ALIASES = \{(.*?)\n\}", gw, re.S)
        self.assertIsNotNone(alias)
        co_alias = set(re.findall(r'"([^"]+)":', alias.group(1)))
        for t in ten:
            if t in ("auto", "image"):
                continue   # xử lý riêng, không đi qua bảng alias
            self.assertIn(t, co_alias,
                          f"gma/{t} được liệt kê nhưng _GMA_ALIASES không có → sẽ rơi về auto")


class CanhBaoModelLaTests(unittest.TestCase):
    def test_model_khong_giai_duoc_phai_ghi_warning(self):
        """Trả lời bằng model KHÁC cái được yêu cầu là chuyện phải nói to.

        Bản cũ chỉ `logger.info`, nên `gma/3.6-flash` trả OK mà không ai biết nó
        chạy model auto.
        """
        gw = (GOC / "api/gemini_web.py").read_text(encoding="utf-8")
        # Tìm ĐÚNG chỗ ghi log, không phải chú thích có nhắc tên sự kiện.
        i = gw.index('"event": "gma_unknown_model_fallback"')
        truoc = gw[max(0, i - 400):i]
        self.assertIn("_logger().warning(", truoc,
                      "fallback model phải ghi mức warning, không phải info")
        self.assertNotIn("_logger().info({\n            \"event\": \"gma_unknown", gw)


if __name__ == "__main__":
    unittest.main()
