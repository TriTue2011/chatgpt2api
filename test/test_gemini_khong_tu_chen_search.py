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


class MotMoiDuyNhatTests(unittest.TestCase):
    """Grounding chỉ có MỘT đường bật: kwarg tường minh.

    Từng có ba đường cho cùng một việc — combo tìm kiếm (backend `gemini`),
    trường `search_model`, và hậu tố `-search` trong tên model. Ba đường thì
    người dùng phải nhớ đường nào làm gì, còn ta phải giữ cả ba đúng; và khi
    chúng lệch nhau thì triệu chứng hiện ra ở chỗ chẳng liên quan.

    Nay chỉ còn: muốn tra web thì chọn backend `gemini` trong combo tìm kiếm.
    Kwarg `google_search` giữ lại cho mã gọi nội bộ (chính backend đó dùng).
    """

    def test_kwarg_tuong_minh_van_bat_duoc(self):
        self.assertTrue(_muon_tim_web("bat-ky", {"google_search": True}))

    def test_khong_co_kwarg_thi_TAT(self):
        self.assertFalse(_muon_tim_web("gemini-3.6-flash", {}))

    def test_TEN_MODEL_khong_con_bat_duoc_grounding(self):
        """Bỏ hậu tố `-search`: một tên model không được là công tắc ẩn."""
        for m in ("gemini-3.6-flash-search", "gemini-2.5-flash-websearch"):
            self.assertFalse(_muon_tim_web(m, {}),
                             f"{m} vẫn bật grounding qua tên — cơ chế thứ ba chưa bỏ hết")

    def test_khong_con_ham_boc_hau_to(self):
        src = (GOC / "services/providers/gemini_free.py").read_text(encoding="utf-8")
        self.assertNotIn("_bo_hau_to_search", src)
        self.assertNotIn("_HAU_TO_SEARCH", src)

    def test_khong_con_alias_search_trong_danh_sach_model(self):
        src = (GOC / "services/protocol/openai_v1_models.py").read_text(encoding="utf-8")
        i = src.index("FALLBACK_MODELS = {")
        j = src.index('"chatgpt": [', i)
        self.assertNotIn("-search", src[i:j])
        k = src.index("ALIAS_MODELS: dict")
        self.assertIn("ALIAS_MODELS: dict[str, list[str]] = {}", src[k:k + 200],
                      "alias để trống — mọi model đều do thượng nguồn khai")

    def test_backend_gemini_VAN_luon_bat_grounding(self):
        """Bỏ đường thừa mà bỏ luôn tính năng thì là hỏng, không phải gọn."""
        src = (GOC / "services/search_service.py").read_text(encoding="utf-8")
        i = src.index("class GeminiGrounding")
        self.assertIn("google_search", src[i:i + 4000])


class ThongBaoLoiNoiDUNG_NGUYEN_NHANTests(unittest.TestCase):
    """Hạn mức grounding cạn cũng trả đúng chữ "exceeded your current quota".

    Thông báo mặc định vì thế dẫn người trực đi thay khoá, trong khi chính
    những khoá đó vẫn gọi được nếu bỏ tra web. Đo 08/08/2026: 5/5 khoá như
    vậy, và cả tôi lẫn chủ máy đều đọc nhầm triệu chứng này.
    """

    def test_bao_ro_la_han_muc_GROUNDING(self):
        src = (GOC / "services/providers/gemini_free.py").read_text(encoding="utf-8")
        i = src.index('if tim_web and "429" in str(last_error')
        than = src[i:i + 700]
        self.assertIn("GOOGLE SEARCH GROUNDING", than)
        self.assertIn("combo tìm kiếm", than,
                      "phải chỉ ra đường dùng được thay thế")

    def test_khong_doi_thong_bao_khi_KHONG_dung_search(self):
        """Request thường mà 429 thì đúng là hết hạn mức thật — đừng đổ nhầm."""
        src = (GOC / "services/providers/gemini_free.py").read_text(encoding="utf-8")
        i = src.index('if tim_web and "429" in str(last_error')
        self.assertIn("tim_web and", src[i:i + 60])


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
