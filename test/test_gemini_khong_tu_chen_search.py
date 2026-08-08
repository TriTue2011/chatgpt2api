"""Không tự chèn `googleSearch` vào mọi request Gemini.

Sự cố thật 08/08/2026. `_convert_request` chèn `{"googleSearch": {}}` vào MỌI
request "để giống hành vi duyệt web sẵn có của ChatGPT". Cái giá không nhìn
thấy được: grounding bằng Google Search tính vào một hạn mức RIÊNG, chặt hơn
nhiều so với hạn mức sinh nội dung.

Hậu quả là một triệu chứng chỉ sai một chút — và vì thế rất tốn thời gian:
Gemini trả `429 exceeded your current quota`, nên mọi người (kể cả tôi) kết
luận "pool hết quota" và đi thay khoá. Đo trên chính pool production
08/08/2026, cùng một khoá, cùng một model:

    gemini-3.1-flash-lite   CÓ googleSearch → 429    KHÔNG → 200
    gemini-3.6-flash        CÓ googleSearch → 429    KHÔNG → 200

Cùng khoá đó dùng thẳng từ Home Assistant vẫn chạy bình thường, vì HA không
chèn Search.

Với đường Vision của camera thì việc chèn này vô nghĩa hoàn toàn: phân tích
một khung hình không cần tra web, mà lại hỏng vì nó.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.providers.gemini_free import _convert_request, _muon_tim_web  # noqa: E402

TIN = [{"role": "user", "content": "xin chào"}]
CONG_CU = [{"type": "function", "function": {"name": "tra_cuu", "description": "",
                                             "parameters": {}}}]


def _co_search(gtools) -> bool:
    return any("googleSearch" in t for t in gtools)


class MacDinhKhongChenTests(unittest.TestCase):
    def test_request_thuong_KHONG_kem_search(self):
        _, _, gtools = _convert_request(TIN, None)
        self.assertFalse(_co_search(gtools),
                         "vẫn tự chèn googleSearch — đường Vision sẽ lại 429")

    def test_co_cong_cu_van_khong_kem_search(self):
        """Tool calling là chuyện khác hẳn tìm web."""
        _, _, gtools = _convert_request(TIN, CONG_CU)
        self.assertFalse(_co_search(gtools))
        self.assertTrue(any("functionDeclarations" in t for t in gtools),
                        "bỏ Search mà bỏ luôn tool calling")

    def test_yeu_cau_tuong_minh_thi_van_co(self):
        """Bỏ hẳn tính năng cũng là một kiểu hỏng — chỉ đổi mặc định."""
        _, _, gtools = _convert_request(TIN, None, google_search=True)
        self.assertTrue(_co_search(gtools))

    def test_vua_cong_cu_vua_search_thi_co_ca_hai(self):
        _, _, gtools = _convert_request(TIN, CONG_CU, google_search=True)
        self.assertTrue(_co_search(gtools))
        self.assertTrue(any("functionDeclarations" in t for t in gtools))


class NhanDangYeuCauTimWebTests(unittest.TestCase):
    """Bám quy ước sẵn có của repo: `api/claude.py` dùng hậu tố `-search`."""

    def test_hau_to_search_thi_bat(self):
        for m in ("gemini-3.6-flash-search", "gemini-3.5-flash-lite-websearch"):
            self.assertTrue(_muon_tim_web(m, {}), f"{m} phải bật tìm web")

    def test_ten_thuong_thi_tat(self):
        for m in ("gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash", ""):
            self.assertFalse(_muon_tim_web(m, {}), f"{m} không được tự bật")

    def test_kwarg_tuong_minh_de_len_ten_model(self):
        self.assertTrue(_muon_tim_web("gemini-3.6-flash", {"google_search": True}))
        self.assertFalse(_muon_tim_web("gemini-3.6-flash-search", {"google_search": False}))


class BocHauToTruocKhiGoiGoogleTests(unittest.TestCase):
    """`-search` là quy ước CỦA TA — Google không biết nó.

    Không bóc ra thì URL trỏ vào một model không tồn tại và nhận 404: một lỗi
    chẳng liên quan gì tới việc người dùng vừa yêu cầu, nên rất tốn công lần.
    """

    def test_boc_dung_hau_to(self):
        from services.providers.gemini_free import _bo_hau_to_search
        self.assertEqual(_bo_hau_to_search("gemini-3.6-flash-search"), "gemini-3.6-flash")
        self.assertEqual(_bo_hau_to_search("gemini-2.5-flash-websearch"), "gemini-2.5-flash")

    def test_websearch_duoc_xet_TRUOC_search(self):
        """Xét ngược thì `-websearch` chỉ rụng `-search`, còn lại đuôi `-web`."""
        from services.providers.gemini_free import _bo_hau_to_search
        self.assertNotIn("-web", _bo_hau_to_search("gemini-3.6-flash-websearch"))

    def test_ten_thuong_khong_bi_dong_vao(self):
        from services.providers.gemini_free import _bo_hau_to_search
        for m in ("gemini-3.6-flash", "gemini-2.5-flash", "gemini-3.1-flash-lite"):
            self.assertEqual(_bo_hau_to_search(m), m)

    def test_khong_boc_nham_giua_ten(self):
        from services.providers.gemini_free import _bo_hau_to_search
        self.assertEqual(_bo_hau_to_search("gemini-search-pro"), "gemini-search-pro")

    def test_chat_completions_boc_TRUOC_khi_dung_url(self):
        src = (GOC / "services/providers/gemini_free.py").read_text(encoding="utf-8")
        i = src.index("def chat_completions")
        than = src[i:]
        vi_boc = than.index("_bo_hau_to_search(model)")
        vi_url = than.index("f\"{_gemini_base_url()}/models/{model}")
        self.assertLess(vi_boc, vi_url, "dựng URL trước khi bóc hậu tố")


class PhoiRaDanhSachModelTests(unittest.TestCase):
    """Không khai ở /v1/models thì client không có cách nào chọn được."""

    # Đọc khối literal trong mã nguồn thay vì import: `openai_v1_models` kéo
    # theo `utils/pow.py`, vốn dùng cú pháp cần Python 3.10+. Ở đây thứ cần
    # kiểm CHÍNH LÀ một danh sách hằng, nên đọc văn bản là kiểm trung thực.
    def _khoi_gemini(self) -> str:
        src = (GOC / "services/protocol/openai_v1_models.py").read_text(encoding="utf-8")
        i = src.index('"gemini_free": [')
        return src[i:src.index("],", i)]

    def test_hai_model_da_do_deu_co_mat(self):
        khoi = self._khoi_gemini()
        self.assertIn('"gemini_free/gemini-3.6-flash"', khoi)
        self.assertIn('"gemini_free/gemini-3.5-flash-lite"', khoi)

    def test_co_bien_the_search_de_bat_grounding(self):
        self.assertIn('-search"', self._khoi_gemini(),
                      "bỏ tự chèn mà không để đường bật lại = mất hẳn tính năng")


class NoiGoiTests(unittest.TestCase):
    def test_chen_nam_TRONG_dieu_kien(self):
        src = (GOC / "services/providers/gemini_free.py").read_text(encoding="utf-8")
        i = src.index('gtools.append({"googleSearch": {}})')
        truoc = src[:i].rstrip().splitlines()[-1]
        self.assertIn("if google_search", truoc,
                      "lệnh chèn không nằm sau điều kiện nào")

    def test_chat_completions_truyen_co_xuong(self):
        src = (GOC / "services/providers/gemini_free.py").read_text(encoding="utf-8")
        i = src.index("def chat_completions")
        than = src[i:i + 1200]
        self.assertIn("_muon_tim_web(model, kwargs)", than)
        self.assertIn("google_search=tim_web", than)

    def test_log_ghi_ro_co_search_hay_khong(self):
        """Không ghi thì lần sau lại mất từng đó thời gian để tìm ra."""
        src = (GOC / "services/providers/gemini_free.py").read_text(encoding="utf-8")
        i = src.index('"event": "gemini_request"')
        self.assertIn('"google_search"', src[i:i + 200])


if __name__ == "__main__":
    unittest.main()
