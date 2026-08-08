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


class MotBackendMotCho_Tests(unittest.TestCase):
    """Cấu hình một backend không nên trải ra hai tab.

    `search_model` CHỈ `GeminiGrounding` dùng tới, nên nó thuộc về tab Search —
    ngay cạnh chỗ bật backend `gemini`. Khoá và model mặc định của Gemini thì ở
    lại Cài đặt, vì chúng phục vụ cả chat, vision và HA chứ không riêng tìm kiếm.
    """

    TRANG = (GOC / "web/src/app/search/page.tsx").read_text(encoding="utf-8")
    CARD = (GOC / "web/src/app/settings/components/gemini-card.tsx").read_text(encoding="utf-8")

    def test_o_chon_nam_o_tab_Search(self):
        self.assertIn("Model cho Gemini Google Search", self.TRANG)
        self.assertIn("search_model: modelGrounding", self.TRANG)

    def test_KHONG_con_o_do_o_Cai_dat(self):
        self.assertNotIn("search_model", self.CARD,
                         "hai chỗ sửa cùng một trường thì sớm muộn cũng lệch nhau")

    def test_chi_hien_khi_backend_gemini_dang_dung(self):
        self.assertIn('combo.includes("gemini") &&', self.TRANG)

    def test_chi_gui_search_model_KHONG_kem_khoa(self):
        """Gửi một khoá đơn từng xoá sạch pool khoá Gemini (sự cố 08/08)."""
        i = self.TRANG.index("gemini_free: {search_model")
        khoi = self.TRANG[i:i + 160]
        self.assertNotIn("api_key", khoi)

    def test_danh_sach_lay_tu_Quan_ly_Model_va_bo_model_anh(self):
        self.assertIn("enabled_models || {}).gemini_free", self.TRANG)
        self.assertIn('!m.startsWith("gemini-image/")', self.TRANG)

    def test_khoa_Gemini_o_LAI_Cai_dat(self):
        """Khoá phục vụ cả chat/vision — kéo sang tab Search là chia sai."""
        self.assertIn("api_keys:     keyList", self.CARD)


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

    def test_o_chon_model_mac_dinh_dung_danh_sach_da_loc(self):
        """Ô «Model tìm kiếm» đã chuyển sang tab Search; ở đây còn ô mặc định."""
        i = self.CARD.index("Model mặc định")
        than = self.CARD[i:i + 900]
        self.assertIn("modelTraLoi.map", than, "ô «Model mặc định» chưa lọc model ảnh")
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
