"""Trí nhớ bền (MEMORY.md) tách theo phạm vi — không còn một file dùng chung.

Đây là chỗ rò nặng nhất trong ba chỗ: nội dung MEMORY.md được nhét vào system
prompt CỦA MỌI LƯỢT (`orchestrator._build_system_prompt`), nên điều một người
dặn riêng đi thẳng vào prompt của mọi kênh, mọi nhóm, mọi người — không cần ai
gọi tool nào.

Ba điều file này khoá:
  1. fact mới ghi ở phạm vi này KHÔNG lọt sang phạm vi khác;
  2. fact CŨ trong kho chung vẫn đọc được ở mọi phạm vi (chưa migration);
  3. sửa điều đã nhớ vẫn hoạt động — kể cả khi dòng cũ nằm ở kho chung. Nếu
     không, người dùng lại KHÔNG THỂ đổi điều bot đã nhớ, đúng lỗi mà
     `state.nho_hoac_cap_nhat` sinh ra để chữa.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import state  # noqa: E402

PV_A = "v1|tg|555||"
PV_B = "v1|tg|556||"


class _TriNhoTam(unittest.TestCase):
    def setUp(self):
        self.thu_muc = pathlib.Path(tempfile.mkdtemp(prefix="tri-nho-"))
        self.addCleanup(shutil.rmtree, self.thu_muc, True)
        self.chung = self.thu_muc / "MEMORY.md"
        self.chung.write_text("", encoding="utf-8")
        self._goc = (state._MEMORY_FILE, state._MEMORY_DB_PATH,
                     state._MEMORY_SCOPE_DIR, state._mem_conn)
        state._MEMORY_FILE = self.chung
        state._MEMORY_DB_PATH = self.thu_muc / "chung.sqlite"
        state._MEMORY_SCOPE_DIR = self.thu_muc / "memory"
        state._MEMORY_SCOPE_DIR.mkdir(parents=True, exist_ok=True)
        state._mem_conn = {}

    def tearDown(self):
        (state._MEMORY_FILE, state._MEMORY_DB_PATH,
         state._MEMORY_SCOPE_DIR, state._mem_conn) = self._goc


class TachTheoPhamVi(_TriNhoTam):
    def test_fact_moi_khong_lot_sang_pham_vi_khac(self):
        state.append_memory("mật khẩu wifi nhà là 12345678", pham_vi=PV_A)
        self.assertIn("12345678", state.load_memory(pham_vi=PV_A))
        self.assertNotIn("12345678", state.load_memory(pham_vi=PV_B))

    def test_hai_pham_vi_hai_file_khac_nhau(self):
        self.assertNotEqual(state._memory_file(PV_A), state._memory_file(PV_B))

    def test_ten_file_la_bam_khong_phai_khoa_lam_sach(self):
        ten = state._memory_file(PV_A).name
        self.assertRegex(ten, r"^[0-9a-f]{16}\.md$")

    def test_khong_co_pham_vi_thi_dung_kho_chung_nhu_truoc(self):
        state.append_memory("việc chung của nhà", pham_vi="")
        self.assertIn("việc chung", self.chung.read_text("utf-8"))

    def test_fact_cu_o_kho_chung_moi_pham_vi_deu_thay(self):
        self.chung.write_text("- [2026-07-01] Nhà ở Hà Nội.\n", encoding="utf-8")
        self.assertIn("Hà Nội", state.load_memory(pham_vi=PV_A))
        self.assertIn("Hà Nội", state.load_memory(pham_vi=PV_B))

    def test_index_fts_cung_tach(self):
        state.append_memory("con trai học lớp bốn trường Kim Đồng", pham_vi=PV_A)
        self.assertTrue(state.search_memory("Kim Đồng", pham_vi=PV_A))
        self.assertEqual(state.search_memory("Kim Đồng", pham_vi=PV_B), [])

    def test_search_thay_ca_fact_cu_o_kho_chung(self):
        self.chung.write_text("- [2026-07-01] Nhà có hai con mèo tam thể.\n",
                              encoding="utf-8")
        self.assertTrue(state.search_memory("mèo tam thể", pham_vi=PV_A))


class ChanTrungTheoPhamVi(_TriNhoTam):
    FACT = "Anh thích uống cà phê sữa đá vào buổi sáng."

    def test_trung_trong_pham_vi_thi_khong_ghi_lai(self):
        self.assertEqual(state.nho_hoac_cap_nhat(self.FACT, pham_vi=PV_A), "them")
        self.assertEqual(state.nho_hoac_cap_nhat(self.FACT, pham_vi=PV_A), "trung")

    def test_pham_vi_khac_thi_KHONG_bi_coi_la_trung(self):
        """Người khác dặn điều tương tự vẫn phải được ghi cho riêng họ."""
        state.nho_hoac_cap_nhat(self.FACT, pham_vi=PV_A)
        self.assertEqual(state.nho_hoac_cap_nhat(self.FACT, pham_vi=PV_B), "them")

    def test_fact_da_co_o_kho_chung_thi_khong_ghi_them(self):
        self.chung.write_text(f"- [2026-07-01] {self.FACT}\n", encoding="utf-8")
        self.assertEqual(state.nho_hoac_cap_nhat(self.FACT, pham_vi=PV_A), "trung")

    def test_memory_contains_chi_soi_pham_vi_cua_minh(self):
        state.append_memory(self.FACT, pham_vi=PV_A)
        self.assertTrue(state.memory_contains(self.FACT, 0.97, pham_vi=PV_A))
        self.assertFalse(state.memory_contains(self.FACT, 0.97, pham_vi=PV_B))


class SuaDieuDaNho(_TriNhoTam):
    CU = ("Khi hỏi tin tức thì chia các mục Thể thao, Kinh tế, Xã hội; "
          "mỗi mục ba tin gạch đầu dòng, có tóm tắt ngắn.")
    MOI = ("Khi hỏi tin tức thì chia các mục Thể thao, Kinh tế, Xã hội; "
           "mỗi mục ba tin gạch đầu dòng, bỏ tóm tắt.")

    def _dong(self, pham_vi: str) -> list[str]:
        p = state._memory_file(pham_vi)
        if not p.exists():
            return []
        return [d for d in p.read_text("utf-8").splitlines() if d.strip()]

    def test_sua_trong_cung_pham_vi_thi_THAY_dong_cu(self):
        state.nho_hoac_cap_nhat(self.CU, pham_vi=PV_A)
        self.assertEqual(state.nho_hoac_cap_nhat(self.MOI, pham_vi=PV_A), "cap_nhat")
        dong = self._dong(PV_A)
        self.assertEqual(len(dong), 1)
        self.assertIn("bỏ tóm tắt", dong[0])

    def test_dong_cu_nam_o_KHO_CHUNG_van_sua_duoc(self):
        """Dữ liệu có trước khi tách phạm vi. Chừa lại là hai lời dặn ngược nhau
        cùng sống, và người dùng lại không sửa được điều bot đã nhớ."""
        self.chung.write_text(f"- [2026-07-01] {self.CU}\n", encoding="utf-8")
        self.assertEqual(state.nho_hoac_cap_nhat(self.MOI, pham_vi=PV_A), "cap_nhat")
        self.assertNotIn("có tóm tắt ngắn", self.chung.read_text("utf-8"))
        self.assertIn("bỏ tóm tắt", "\n".join(self._dong(PV_A)))

    def test_khong_xoa_lay_sang_pham_vi_khac(self):
        state.nho_hoac_cap_nhat(self.CU, pham_vi=PV_B)
        state.nho_hoac_cap_nhat(self.MOI, pham_vi=PV_A)
        self.assertIn("có tóm tắt ngắn", "\n".join(self._dong(PV_B)))


class SoThichTrinhBayVanApDung(_TriNhoTam):
    """Lời dặn cách trình bày lưu ở kho riêng thì đường tắt vẫn phải đọc được.

    Không thế thì `remember` ghi vào kho riêng mà `_so_thich_trinh_bay` đọc kho
    chung → bot "nhớ" mà không làm, đúng lỗi test_ap_so_thich_trinh_bay.py khoá.
    """

    def test_loi_dan_o_kho_rieng_van_vao_duoc_duong_tat(self):
        from services.agent import orchestrator as orch
        state.append_memory("Trả lời ngắn gọn thôi, đừng dài dòng.", pham_vi=PV_A)
        self.assertEqual(len(orch._so_thich_trinh_bay(pham_vi=PV_A)), 1)
        self.assertEqual(orch._so_thich_trinh_bay(pham_vi=PV_B), [])

    def test_dang_bay_tin_doc_loi_dan_cua_dung_pham_vi(self):
        from services.agent import orchestrator as orch
        state.append_memory("Khi hỏi tin tức thì bỏ tóm tắt đi nhé.", pham_vi=PV_A)
        self.assertFalse(orch._dang_bay_tin(PV_A)["tom_tat"])
        self.assertTrue(orch._dang_bay_tin(PV_B)["tom_tat"])


if __name__ == "__main__":
    unittest.main()
