"""Combo tự loại thành viên đã mất provider — thêm/xoá provider khỏi phải sửa combo.

Yêu cầu 02/08: "thêm provider khác thì tự thêm vào phần lựa chọn, hoặc provider
nào xoá thì tự xoá khỏi lựa chọn. model cũng không hiển thị nữa nếu không còn
provider, trong combo cũng tự động loại bỏ".

Ba chỗ hiển thị lựa chọn, trạng thái TRƯỚC khi có file này:

  · danh sách loa       → đã động (`permissions.visible_speakers` đọc live)
  · menu model ảnh/video → đã động (`list_models` + `_drop_unavailable` ẩn model
    của provider không còn tài khoản / API key)
  · combo               → CHƯA. `combo_models` là danh sách chuỗi cố định trong
    cấu hình, nên một Custom Provider đã xoá vẫn nằm trong chuỗi fallback: mỗi
    lượt chat gửi một tên model vô nghĩa sang ChatGPT rồi mới rơi xuống thành
    viên sau.

Bất biến quan trọng nhất: lọc sạch hết thì GIỮ NGUYÊN danh sách gốc. Combo không
còn đường nào để thử còn tệ hơn thử một đường đã chết.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backend_router import BackendRouter  # noqa: E402


class MatProviderTests(unittest.TestCase):
    """Tiền tố dạng `x/` mà phân giải rơi về 'chatgpt' ⇒ provider đã biến mất."""

    def setUp(self):
        self.br = BackendRouter()

    def _mat(self, s: str) -> bool:
        prov, _ = self.br.resolve_model(s)
        return self.br._provider_da_mat(s, prov)

    def test_tien_to_khong_con_phan_giai_duoc_la_MAT(self):
        for s in ("daxoa/gpt-4", "provider-cu/llama-3", "tr-cu/kimi"):
            self.assertTrue(self._mat(s), s)

    def test_provider_con_song_thi_KHONG_mat(self):
        for s in ("cx/gpt-5.5", "oc/laguna-s-2.1-free", "nv/openai/gpt-oss-120b",
                  "gemini_free/gemini-2.5-flash", "flow/banana-pro"):
            self.assertFalse(self._mat(s), s)

    def test_model_chatgpt_khong_co_gach_cheo_thi_KHONG_mat(self):
        """'gpt-image-2' đi đúng đường mặc định, đừng loại oan."""
        for s in ("gpt-image-2", "gpt-5-5-image", "auto"):
            self.assertFalse(self._mat(s), s)

    def test_alias_chatgpt_khong_bi_loai(self):
        """'chatgpt/…' phân giải ra chatgpt_free nên không lọt vào phép kiểm."""
        for s in ("chatgpt/auto", "chatgpt/free/auto", "cgf/auto", "free/auto"):
            self.assertFalse(self._mat(s), s)


class LocThanhVienTests(unittest.TestCase):
    def setUp(self):
        self.br = BackendRouter()
        # Không cho phép đo phụ thuộc pool tài khoản thật của máy.
        self.p = mock.patch.object(BackendRouter, "_het_credential",
                                   staticmethod(lambda mid: False))
        self.p.start()
        self.addCleanup(self.p.stop)

    def test_bo_dung_thanh_vien_chet_giu_thu_tu_con_lai(self):
        goc = ["cx/gpt-5.5:text", "daxoa/gpt-4:text", "oc/mimo-v2.5-free:text",
               "khac-cu/llama:text", "gemini_free/gemini-2.5-flash:text"]
        self.assertEqual(self.br._loc_thanh_vien_song(goc, "AI text"),
                         ["cx/gpt-5.5:text", "oc/mimo-v2.5-free:text",
                          "gemini_free/gemini-2.5-flash:text"])

    def test_khong_co_ai_chet_thi_y_nguyen(self):
        goc = ["cx/gpt-5.5:text", "oc/mimo-v2.5-free:text"]
        self.assertEqual(self.br._loc_thanh_vien_song(goc, "AI text"), goc)

    def test_chet_HET_thi_giu_nguyen_danh_sach_goc(self):
        """Thà thử và hỏng còn hơn combo rỗng."""
        goc = ["daxoa/gpt-4", "khac-cu/llama"]
        self.assertEqual(self.br._loc_thanh_vien_song(goc, "AI text"), goc)

    def test_giu_nguyen_dau_dinh_dang_cua_thanh_vien(self):
        """':text' quyết định lời văn nói-vs-viết — không được rụng khi lọc."""
        ra = self.br._loc_thanh_vien_song(["cx/gpt-5.5:text", "daxoa/x"], "AI text")
        self.assertEqual(ra, ["cx/gpt-5.5:text"])

    def test_het_credential_thi_cung_bi_bo(self):
        with mock.patch.object(BackendRouter, "_het_credential",
                               staticmethod(lambda mid: mid.startswith("nv/"))):
            ra = self.br._loc_thanh_vien_song(
                ["cx/gpt-5.5", "nv/openai/gpt-oss-120b", "oc/mimo-v2.5-free"], "AI text")
        self.assertEqual(ra, ["cx/gpt-5.5", "oc/mimo-v2.5-free"])


class RouteComboDiQuaBoLocTests(unittest.TestCase):
    def test_route_combo_bo_thanh_vien_chet(self):
        br = BackendRouter()
        combos = {"AI test": ["cx/gpt-5.5:text", "daxoa/gpt-4:text",
                              "oc/mimo-v2.5-free:text"]}
        with mock.patch.object(BackendRouter, "_het_credential",
                               staticmethod(lambda mid: False)), \
             mock.patch.object(BackendRouter, "_get_combo_models",
                               lambda self, name: combos.get(name)):
            routes = br.route_combo("AI test")
        self.assertEqual([r.provider for r in routes], ["openai_oauth", "opencode"])

    def test_combo_khong_ton_tai_van_tra_rong(self):
        br = BackendRouter()
        with mock.patch.object(BackendRouter, "_get_combo_models",
                               lambda self, name: None):
            self.assertEqual(br.route_combo("khong co"), [])


class DungLaiLuatCuaTabModelTests(unittest.TestCase):
    """Chỉ được có MỘT định nghĩa "provider còn sống" trong dự án."""

    def test_het_credential_goi_thang_drop_unavailable(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "services" / "backend_router.py").read_text("utf-8")
        i = src.index("def _het_credential")
        self.assertIn("_drop_unavailable", src[i:i + 900])

    def test_provider_con_song_thi_giu(self):
        """Phép đo thật, chạm pool thật: cx/ có tài khoản codex thì KHÔNG bị bỏ."""
        br = BackendRouter()
        from services.account_service import account_group, account_service
        co_codex = any(account_group(a) == "codex"
                       and str(a.get("status")) not in ("disabled", "error", "limited")
                       for a in account_service.list_accounts())
        if not co_codex:
            self.skipTest("máy này không có tài khoản codex dùng được")
        self.assertFalse(br._het_credential("cx/gpt-5.5"))


if __name__ == "__main__":
    unittest.main()
