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


class XungDotModelMacDinhTests(unittest.TestCase):
    """"Model mặc định" (Cài đặt) và "Quản lý Model" là HAI nguồn, và chúng đè nhau.

    `backend_router.route()` giải `<provider>/auto` theo thứ tự:
        providers.<tên>.model  →  PROVIDER_DEFAULT_MODELS  →  LỌC theo
        model_settings.enabled_models

    Bước lọc cuối ĐÈ LÊN hai bước trước: bỏ tick đúng model đang đặt làm mặc
    định thì hệ thống lặng lẽ chuyển sang model đầu danh sách. Không ai thấy
    gì, chỉ thấy "sao nó trả lời bằng model khác".
    """

    SRC = (GOC / "services/backend_router.py").read_text(encoding="utf-8")

    def test_van_giu_thu_tu_giai(self):
        """default_models → providers.*.model (cấu hình cũ) → mặc định của mã."""
        i = self.SRC.index('if resolved_model == "auto" or not resolved_model:')
        than = self.SRC[i:i + 1600]
        self.assertIn('(ms.get("default_models") or {}).get(provider)', than)
        self.assertIn('provider_cfg.get("model")', than)
        self.assertIn("PROVIDER_DEFAULT_MODELS", than)

    def test_khi_bi_de_thi_GHI_LOG_chu_khong_im_lang(self):
        self.assertIn("model_mac_dinh_bi_de", self.SRC)
        i = self.SRC.index("model_mac_dinh_bi_de")
        than = self.SRC[i:i + 700]
        self.assertIn('"cau_hinh"', than, "phải ghi model đã cấu hình")
        self.assertIn('"dung_thay"', than, "phải ghi model thực sự dùng")

    def test_chi_canh_bao_khi_THAT_SU_bi_de(self):
        """`auto` bị thay là chuyện bình thường — cảnh báo ở đó là tiếng ồn."""
        i = self.SRC.index("model_mac_dinh_bi_de")
        truoc = self.SRC[:i]
        self.assertIn('if resolved_model != "auto" and resolved_model not in real_models:',
                      truoc[-400:])


class BaTabBaViecTests(unittest.TestCase):
    """Chốt phân chia của chủ máy — mỗi thứ đúng một chỗ.

        Cài đặt        → chỉ API KEY
        Quản lý Model  → model cho chat / vision / HA / ảnh
        tab Search     → model tra web

    Trước đây card Gemini có cả ô "Model mặc định" lẫn phần tick riêng, trong
    khi trang Quản lý Model cũng có cả hai. Hai nguồn cho một việc, và bước lọc
    `enabled_models` lặng lẽ đè lên ô ở Cài đặt khi chúng lệch nhau — người
    dùng chỉ thấy "sao nó trả lời bằng model khác".
    """

    CARD = (GOC / "web/src/app/settings/components/gemini-card.tsx").read_text(encoding="utf-8")
    TRANG_SEARCH = (GOC / "web/src/app/search/page.tsx").read_text(encoding="utf-8")
    ROUTER = (GOC / "services/backend_router.py").read_text(encoding="utf-8")

    def test_card_Cai_dat_chi_con_KHOA(self):
        self.assertIn("geminiKey", self.CARD)
        for da_bo in ("setGeminiModel", "toggleModel", "enabledModels", "search_model"):
            self.assertNotIn(da_bo, self.CARD, f"card vẫn còn «{da_bo}»")

    def test_card_tro_nguoi_dung_sang_dung_tab(self):
        self.assertIn('href="/models"', self.CARD)
        self.assertIn('href="/search"', self.CARD)

    def test_model_tra_web_o_tab_Search(self):
        self.assertIn("search_model: modelGrounding", self.TRANG_SEARCH)

    def test_router_doc_default_models_TRUOC(self):
        """Nguồn duy nhất cho model mặc định là tab Quản lý Model."""
        i = self.ROUTER.index('if resolved_model == "auto" or not resolved_model:')
        than = self.ROUTER[i:i + 1400]
        vi_moi = than.index('(ms.get("default_models") or {}).get(provider)')
        vi_cu = than.index('provider_cfg.get("model")')
        self.assertLess(vi_moi, vi_cu, "vẫn ưu tiên trường cũ ở providers.*")

    def test_van_doc_duoc_cau_hinh_CU(self):
        """Bỏ hẳn `providers.*.model` là đổi hành vi của bản đang chạy."""
        i = self.ROUTER.index('if resolved_model == "auto" or not resolved_model:')
        self.assertIn('provider_cfg.get("model")', self.ROUTER[i:i + 1400])
