"""Di trú dữ liệu cũ sang phạm vi — đúng chỗ, không mất gì, chạy lại được.

Di trú là thao tác KHÓ ĐẢO trên dữ liệu thật, nên ba tính chất phải khoá bằng
test chứ không bằng đọc mắt:

  * gán ĐÚNG phạm vi — suy từ nguồn đã ghi sẵn (`who` / `platform`+`chat_id`),
    không đoán;
  * KHÔNG MẤT gì — bản ghi không rõ nguồn thì giữ nguyên ở kho chung; tổng số
    dòng trí nhớ trước và sau bằng nhau;
  * CHẠY LẠI ĐƯỢC — lần hai không nhân bản, không đổi thêm gì.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

GOC = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOC))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import scope, state  # noqa: E402
from services.agent.skills import split_frontmatter  # noqa: E402


def _nap_script():
    """Nạp scripts/di_tru_pham_vi.py (không phải package nên import thường không tới)."""
    duong = GOC / "scripts" / "di_tru_pham_vi.py"
    spec = importlib.util.spec_from_file_location("di_tru_pham_vi", duong)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DT = _nap_script()

FM = """---
title: {title}
source: ingest
who: {who}
platform: {plat}
chat_id: {cid}
created_at: 2026-07-20 08:00
tags: ghi-chu
---

# {title}

{than}
"""


class KhoaPhienCuaNote(unittest.TestCase):
    def test_uu_tien_who(self):
        self.assertEqual(DT.khoa_phien_cua_note(
            {"who": "zalo_123:u456", "platform": "tg", "chat_id": "9"}),
            "zalo_123:u456")

    def test_dung_lai_tu_platform_va_chat_id(self):
        self.assertEqual(DT.khoa_phien_cua_note({"platform": "zalop", "chat_id": "9"}),
                         "zalop_9")
        self.assertEqual(DT.khoa_phien_cua_note({"platform": "zalo", "chat_id": "9"}),
                         "zalo_9")
        self.assertEqual(DT.khoa_phien_cua_note({"platform": "tg", "chat_id": "-100"}),
                         "-100")

    def test_khong_ro_nguon_thi_tra_rong(self):
        self.assertEqual(DT.khoa_phien_cua_note({}), "")
        self.assertEqual(DT.khoa_phien_cua_note({"platform": "tg"}), "")


class _MoiTruongTam(unittest.TestCase):
    def setUp(self):
        self.goc = pathlib.Path(tempfile.mkdtemp(prefix="di-tru-"))
        self.addCleanup(shutil.rmtree, self.goc, True)
        self.notes = self.goc / "agent" / "wiki" / "notes"
        self.notes.mkdir(parents=True)
        self.chung = self.goc / "agent" / "MEMORY.md"
        self.chung.write_text("", encoding="utf-8")

        # KHÔNG tự trỏ `state` vào thư mục tạm ở đây — để chính script làm việc
        # đó. Bản test đầu tự trỏ, nên nó xanh trong khi chạy CLI thật thì dòng
        # trí nhớ bay vào data/agent/memory của app: test khoá tầng quy tắc mà
        # bỏ trống đúng chỗ ghép tầng.
        self._goc_state = (state._MEMORY_FILE, state._MEMORY_DB_PATH,
                           state._MEMORY_SCOPE_DIR, state._mem_conn)
        self.cfg = {}
        p = mock.patch("services.config.config.get", side_effect=lambda: self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        (state._MEMORY_FILE, state._MEMORY_DB_PATH,
         state._MEMORY_SCOPE_DIR, state._mem_conn) = self._goc_state

    def _note(self, ten, *, who="", plat="", cid="", than="nội dung"):
        p = self.notes / f"{ten}.md"
        p.write_text(FM.format(title=ten, who=who, plat=plat, cid=cid, than=than),
                     encoding="utf-8")
        return p

    def _scope_cua(self, p: pathlib.Path) -> str:
        fm, _ = split_frontmatter(p.read_text("utf-8"))
        return str(fm.get("scope") or "")

    def _chay(self, thuc_hien=True):
        return DT.chay(self.goc, thuc_hien)

    def test_script_tu_tro_state_vao_dung_thu_muc(self):
        """Chốt hồi quy: `--data-dir` phải đổi CẢ chỗ đọc lẫn chỗ ghi."""
        that = state._MEMORY_FILE
        DT.chay(self.goc, False)
        self.assertEqual(state._MEMORY_FILE, self.chung)
        self.assertEqual(state._MEMORY_SCOPE_DIR, self.goc / "agent" / "memory")
        self.assertNotEqual(state._MEMORY_FILE, that)


class DiTruWiki(_MoiTruongTam):
    def test_gan_dung_pham_vi_theo_who(self):
        p = self._note("ghi-chu-a", who="zalo_123:u456", plat="zalo", cid="123")
        self._chay()
        self.assertEqual(self._scope_cua(p), scope.khoa_du_lieu("zalo_123:u456"))

    def test_hai_nguon_khac_nhau_ra_hai_pham_vi(self):
        a = self._note("a", who="555", plat="tg", cid="555")
        b = self._note("b", who="556", plat="tg", cid="556")
        self._chay()
        self.assertNotEqual(self._scope_cua(a), self._scope_cua(b))

    def test_note_khong_ro_nguon_GIU_NGUYEN(self):
        """Đoán bừa là hai kiểu hỏng: gán nhầm cho người này, người kia mất."""
        p = self._note("mo-coi")
        truoc = p.read_text("utf-8")
        self._chay()
        self.assertEqual(p.read_text("utf-8"), truoc)

    def test_giu_nguyen_moi_khoa_frontmatter_khac(self):
        p = self._note("a", who="555", plat="tg", cid="555")
        self._chay()
        fm, than = split_frontmatter(p.read_text("utf-8"))
        for k in ("title", "source", "who", "platform", "chat_id", "created_at", "tags"):
            self.assertIn(k, fm, k)
        self.assertIn("nội dung", than)

    def test_xem_truoc_KHONG_ghi_gi(self):
        p = self._note("a", who="555", plat="tg", cid="555")
        truoc = p.read_text("utf-8")
        self._chay(thuc_hien=False)
        self.assertEqual(p.read_text("utf-8"), truoc)

    def test_chay_lai_khong_gan_hai_lan(self):
        p = self._note("a", who="555", plat="tg", cid="555")
        self._chay()
        sau_lan_1 = p.read_text("utf-8")
        self._chay()
        self.assertEqual(p.read_text("utf-8"), sau_lan_1)
        self.assertEqual(sau_lan_1.count("scope:"), 1)

    def test_co_ban_sao_truoc_khi_ghi(self):
        self._note("a", who="555", plat="tg", cid="555")
        self._chay()
        self.assertTrue(list(self.notes.glob("a.md.truoc-di-tru-*")))

    def test_sau_di_tru_thi_pham_vi_khac_KHONG_doc_duoc(self):
        """Đích thực sự của cả việc này."""
        from services.agent import wiki as w
        w._reset_for_tests(self.goc / "agent" / "wiki")
        self._note("bi-mat", who="555", plat="tg", cid="555",
                   than="mã cửa nhà là 8642 đừng cho ai biết")
        pv_a, pv_b = scope.khoa_du_lieu("555"), scope.khoa_du_lieu("556")
        self.assertTrue(w.search("mã cửa", pham_vi=pv_b))   # trước: ai cũng thấy
        self._chay()
        self.assertTrue(w.search("mã cửa", pham_vi=pv_a))
        self.assertEqual(w.search("mã cửa", pham_vi=pv_b), [])


class DiTruTriNho(_MoiTruongTam):
    DONG_A = "- [2026-07-20 08:00] (555) Anh tên là Việt."
    DONG_B = "- [2026-07-20 08:01] (556) Chị thích trà sen."
    DONG_MO_COI = "- [2026-07-20 08:02] Nhà ở Hà Nội."
    DONG_WIKI = "- [2026-07-20 08:03] (wiki) Tóm tắt tài liệu abc."

    def _viet_chung(self, *dong):
        self.chung.write_text("\n".join(dong) + "\n", encoding="utf-8")

    def test_chuyen_dung_pham_vi(self):
        self._viet_chung(self.DONG_A, self.DONG_B)
        self._chay()
        self.assertIn("Việt", state.load_memory(pham_vi=scope.khoa_du_lieu("555")))
        self.assertNotIn("trà sen",
                         state.load_memory(pham_vi=scope.khoa_du_lieu("555")))

    def test_dong_khong_ro_nguon_GIU_o_kho_chung(self):
        self._viet_chung(self.DONG_A, self.DONG_MO_COI, self.DONG_WIKI)
        self._chay()
        con = self.chung.read_text("utf-8")
        self.assertIn("Hà Nội", con)
        self.assertIn("Tóm tắt tài liệu", con)
        self.assertNotIn("Anh tên là Việt", con)

    def test_khong_mat_dong_nao(self):
        self._viet_chung(self.DONG_A, self.DONG_B, self.DONG_MO_COI)
        self._chay()
        tong = len([d for d in self.chung.read_text("utf-8").splitlines() if d.strip()])
        for who in ("555", "556"):
            p = state._memory_file(scope.khoa_du_lieu(who))
            tong += len([d for d in p.read_text("utf-8").splitlines() if d.strip()])
        self.assertEqual(tong, 3)

    def test_index_fts_dung_lai_sau_di_tru(self):
        self._viet_chung(self.DONG_A, self.DONG_B)
        self._chay()
        pv_a = scope.khoa_du_lieu("555")
        self.assertTrue(state.search_memory("Việt", pham_vi=pv_a))
        self.assertEqual(state.search_memory("trà sen", pham_vi=pv_a), [])

    def test_xem_truoc_KHONG_ghi_gi(self):
        self._viet_chung(self.DONG_A)
        self._chay(thuc_hien=False)
        self.assertIn("Anh tên là Việt", self.chung.read_text("utf-8"))

    def test_chay_lai_khong_nhan_ban(self):
        self._viet_chung(self.DONG_A)
        self._chay()
        self._chay()
        p = state._memory_file(scope.khoa_du_lieu("555"))
        self.assertEqual(p.read_text("utf-8").count("Anh tên là Việt"), 1)

    def test_co_ban_sao_truoc_khi_ghi(self):
        self._viet_chung(self.DONG_A)
        self._chay()
        self.assertTrue(list((self.goc / "agent").glob("MEMORY.md.truoc-di-tru-*")))

    def test_nhom_chua_loc_user_thi_gop_ve_MOT_pham_vi(self):
        """Đúng quy tắc chia sẻ: nhóm chưa lọc user thì thành viên dùng chung."""
        self._viet_chung("- [2026-07-20 08:00] (-100:u9) Lịch trực nhật.",
                         "- [2026-07-20 08:01] (-100:u10) Quỹ lớp còn 2 triệu.")
        self._chay()
        pv = scope.khoa_du_lieu("-100:u9")
        noi_dung = state.load_memory(pham_vi=pv)
        self.assertIn("trực nhật", noi_dung)
        self.assertIn("Quỹ lớp", noi_dung)


if __name__ == "__main__":
    unittest.main()
