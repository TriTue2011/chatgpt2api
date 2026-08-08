"""Model dùng cho tra web chọn được riêng, và chọn từ danh sách Quản lý Model.

`search_service._get_model()` đọc `providers.gemini_free.search_model` rồi mới
rơi về `model`. Nhưng KHÔNG có ô nào trong giao diện đặt trường đó, nên nó luôn
rỗng và tra web dùng chung model với chat — muốn dùng một model rẻ/nhanh cho
grounding thì phải sửa tay `config.json`.

Danh sách phải lấy từ CHÍNH các model đã tick ở "Quản lý Model", không phải một
danh sách cứng viết riêng: danh sách cứng sẽ lệch khỏi thực tế ngay lần thượng
nguồn đổi tên model, và lệch một cách im lặng.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

GOC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

CARD = (GOC / "web/src/app/settings/components/gemini-card.tsx").read_text(encoding="utf-8")


class ChonModelRiengChoTimKiemTests(unittest.TestCase):
    def setUp(self):
        from services.config import config
        self.config = config
        self._cu = config.data
        self.addCleanup(lambda: setattr(config, "data", self._cu))

    def _model(self, gemini_free: dict) -> str:
        from services.search_service import GeminiGrounding
        self.config.data = {"providers": {"gemini_free": gemini_free}}
        # `__new__` để khỏi chạy `__init__` (nó dựng state không cần cho phép đo).
        return GeminiGrounding._get_model(GeminiGrounding.__new__(GeminiGrounding))

    def test_uu_tien_search_model(self):
        self.assertEqual(
            self._model({"model": "gemini-2.5-flash",
                         "search_model": "gemini-3.5-flash-lite"}),
            "gemini-3.5-flash-lite")

    def test_de_trong_thi_dung_model_mac_dinh(self):
        self.assertEqual(
            self._model({"model": "gemini-3.6-flash", "search_model": ""}),
            "gemini-3.6-flash")

    def test_boc_tien_to_provider(self):
        """`/v1/models` trả `gemini_free/…`; URL của Google chỉ nhận tên trơn.

        Để nguyên là đường dẫn thành `/models/gemini_free/…` — dấu `/` thừa làm
        Google trả 404 với body RỖNG, nên tra cứu chết mà không ai thấy (đo
        01/08/2026).
        """
        self.assertEqual(
            self._model({"search_model": "gemini_free/gemini-3.5-flash-lite"}),
            "gemini-3.5-flash-lite")

    def test_khong_co_gi_thi_van_co_mac_dinh(self):
        self.assertEqual(self._model({}), "gemini-2.5-flash")


class GiaoDienLayTuQuanLyModelTests(unittest.TestCase):
    def test_co_o_chon_model_tim_kiem(self):
        self.assertIn("Model tìm kiếm", CARD)
        self.assertIn("search_model: searchModel", CARD)

    def test_danh_sach_lay_tu_model_DA_TICK(self):
        """Danh sách cứng sẽ lệch khỏi thực tế ngay lần thượng nguồn đổi tên."""
        i = CARD.index("Model tìm kiếm")
        than = CARD[i:i + 1200]
        self.assertIn("modelTraLoi.map", than,
                      "ô này phải dùng chung nguồn với Quản lý Model (đã lọc model ảnh)")

    def test_co_lua_chon_de_trong(self):
        """Không có lựa chọn rỗng thì không quay lại dùng model mặc định được."""
        i = CARD.index("Model tìm kiếm")
        self.assertIn('<option value="">', CARD[i:i + 1200])

    def test_nap_lai_gia_tri_da_luu(self):
        self.assertIn('setSearchModel(p.search_model || "")', CARD)


if __name__ == "__main__":
    unittest.main()


class LocModelVeAnhTests(unittest.TestCase):
    """`/v1/models` xếp cả `gemini-image/*` vào owned_by=gemini_free.

    Hai ô chọn model TRẢ LỜI vì thế từng liệt kê cả `imagen-3.0-generate-001`.
    Chọn nó làm model chat hay model tra web thì gọi là hỏng, mà giao diện chẳng
    có gì cho thấy đó là model VẼ ẢNH.
    """

    CARD = (GOC / "web/src/app/settings/components/gemini-card.tsx").read_text(encoding="utf-8")

    def test_co_danh_sach_rieng_cho_model_tra_loi(self):
        self.assertIn('modelTraLoi = enabledModels.filter', self.CARD)
        self.assertIn('!m.startsWith("gemini-image/")', self.CARD)

    def test_hai_o_chon_deu_dung_danh_sach_da_loc(self):
        for neo in ("Model mặc định", "Model tìm kiếm"):
            i = self.CARD.index(neo)
            than = self.CARD[i:i + 900]
            self.assertIn("modelTraLoi.map", than, f"ô «{neo}» chưa lọc model ảnh")
            self.assertNotIn("enabledModels.map", than)

    def test_phan_TICK_van_giu_model_anh(self):
        """Tick quyết định model nào hiện ra trong /v1/models cho cả hệ thống —
        ảnh thì đúng là cần, chỉ không được lẫn vào ô chọn model trả lời."""
        # Lần xuất hiện ĐẦU là trong chú thích của hàm nạp; khối giao diện có
        # biểu tượng đứng trước.
        i = self.CARD.index("🧩 Quản lý Model")
        self.assertIn("allModels.map", self.CARD[i:i + 1200])


class TickPhaiVaoDUNG_CHO_Tests(unittest.TestCase):
    """`/v1/models` lọc theo `model_settings.enabled_models`, không phải
    `providers.gemini_free.extra_models`.

    `extra_models` KHÔNG có dòng mã Python nào đọc tới — tick ở card Gemini vì
    thế chẳng ảnh hưởng gì, trong khi trang Quản lý Model tick vào chỗ khác.
    Hai danh sách lệch nhau mà không có dấu hiệu nào; chủ máy chỉ phát hiện khi
    thấy ô chọn model liệt kê thứ mình không bật.
    """

    CARD = (GOC / "web/src/app/settings/components/gemini-card.tsx").read_text(encoding="utf-8")

    def test_extra_models_thuc_su_khong_ai_doc(self):
        """Nếu về sau có nơi đọc nó thì test này phải đỏ để xem lại thiết kế."""
        import subprocess
        # Bỏ thư mục test: chính test này có nhắc tên trường.
        ra = subprocess.run(["grep", "-rn", "extra_models", "--include=*.py",
                             "services", "api", "captcha-solver", "vn-mcp-hub"],
                            cwd=str(GOC), capture_output=True, text=True)
        self.assertEqual(ra.stdout.strip(), "",
                         "đã có nơi đọc extra_models — thiết kế đổi, xem lại card")

    def test_card_doc_tu_model_settings(self):
        self.assertIn("ms?.enabled_models?.gemini_free", self.CARD)

    def test_card_GHI_vao_model_settings(self):
        i = self.CARD.index("async function save")
        than = self.CARD[i:i + 1800]
        self.assertIn("model_settings: ms", than)
        self.assertNotIn("extra_models", than, "vẫn ghi vào trường chết")

    def test_giu_nguyen_phan_con_lai_cua_model_settings(self):
        """`config.update` thay nguyên khối — gửi thiếu `default_models` là xoá."""
        i = self.CARD.index("const ms = {")
        self.assertIn("...modelSettings", self.CARD[i:i + 300])
        self.assertIn("...(modelSettings?.enabled_models || {})", self.CARD[i:i + 400])
