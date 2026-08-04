"""Kết nối bộ nhớ đi ĐÚNG QUA CHỖ GHÉP TẦNG: adapter → ctx → tool → kho.

Hai lần trước cùng một kiểu hỏng: hàm quy tắc đúng, test quy tắc xanh, nhưng chỗ
ghép hai tầng thì sai (đổi hình dạng khoá phiên; `--data-dir` chỉ đổi chỗ đọc).
Nên file này không test `pham_vi_doc_them` — đã có test_ket_noi_bo_nho.py. Nó
gọi CHÍNH handler tool với CHÍNH `ctx` mà orchestrator dựng, và soi cả bó ngữ
cảnh đi vào system prompt.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import capabilities as caps  # noqa: E402
from services.agent import scope, state  # noqa: E402

BO, ME, CON = "zalop_111", "zalop_222", "333"


def _ctx(user_id: str) -> dict:
    """Đúng `ctx` orchestrator dựng (services/agent/orchestrator.py)."""
    return {"user_id": user_id, "user_message": "", "auto_approve": False,
            "is_admin": False}


def tv(kenh: str, chat: str, topic: str = "", user: str = "") -> dict:
    return {"kenh": kenh, "chat": chat, "topic": topic, "user": user}


class _MoiTruong(unittest.TestCase):
    def setUp(self):
        self.cfg: dict = {}
        p = mock.patch("services.config.config.get", side_effect=lambda: self.cfg)
        p.start()
        self.addCleanup(p.stop)

        self.thu_muc = pathlib.Path(tempfile.mkdtemp(prefix="kn-tool-"))
        self.addCleanup(shutil.rmtree, self.thu_muc, True)
        from services.agent import wiki as w
        self.w = w
        w._reset_for_tests(self.thu_muc / "wiki")
        self._goc = (state._MEMORY_FILE, state._MEMORY_DB_PATH,
                     state._MEMORY_SCOPE_DIR, state._mem_conn)
        state._MEMORY_FILE = self.thu_muc / "MEMORY.md"
        state._MEMORY_FILE.write_text("", encoding="utf-8")
        state._MEMORY_DB_PATH = self.thu_muc / "chung.sqlite"
        state._MEMORY_SCOPE_DIR = self.thu_muc / "memory"
        state._MEMORY_SCOPE_DIR.mkdir(parents=True, exist_ok=True)
        state._mem_conn = {}

    def tearDown(self):
        (state._MEMORY_FILE, state._MEMORY_DB_PATH,
         state._MEMORY_SCOPE_DIR, state._mem_conn) = self._goc

    def _noi(self, *moi):
        self.cfg["memory_links"] = list(moi)

    def _binh_dang(self):
        self._noi({"id": "1", "kind": "binh_dang",
                   "members": [tv("zalop", "111"), tv("zalop", "222")]})

    def _chinh_phu(self):
        self._noi({"id": "1", "kind": "chinh_phu",
                   "primary": [tv("zalop", "111")],
                   "secondary": [tv("tg", "333")]})

    def _ingest(self, kp: str, noi_dung: str):
        out = caps._h_ingest({"content": noi_dung}, _ctx(kp))
        self.assertIn("Đã thu nạp", out["text"])


class ToolWikiTheoKetNoi(_MoiTruong):
    def test_chua_noi_thi_khong_thay(self):
        self._ingest(ME, "lịch tiêm phòng của con vào thứ Ba tuần sau")
        ra = caps._h_wiki_search({"query": "tiêm phòng"}, _ctx(BO))
        self.assertIn("Không thấy ghi chú", ra["text"])

    def test_binh_dang_thi_thay_qua_TOOL(self):
        self._ingest(ME, "lịch tiêm phòng của con vào thứ Ba tuần sau")
        self._binh_dang()
        ra = caps._h_wiki_search({"query": "tiêm phòng"}, _ctx(BO))
        # So bằng dấu hiệu TÌM THẤY, không so nội dung: câu "Không thấy ghi chú
        # khớp «tiêm phòng»" có chứa nguyên văn từ khoá nên assert theo từ khoá
        # là xanh ở cả hai chiều — đúng cái bẫy đã sập một lần trong file này.
        self.assertIn("Tìm thấy", ra["text"])

    def test_phu_KHONG_thay_cua_chinh_qua_TOOL(self):
        self._ingest(BO, "sổ tiết kiệm ngân hàng số 123456 kỳ hạn một năm")
        self._chinh_phu()
        ra = caps._h_wiki_search({"query": "tiết kiệm"}, _ctx(CON))
        self.assertIn("Không thấy ghi chú", ra["text"])

    def test_chinh_thay_cua_phu_qua_TOOL(self):
        self._ingest(CON, "bài kiểm tra toán giữa kỳ được tám điểm")
        self._chinh_phu()
        ra = caps._h_wiki_search({"query": "kiểm tra toán"}, _ctx(BO))
        self.assertIn("Tìm thấy", ra["text"])

    def test_wiki_read_theo_slug_cung_bi_chot(self):
        """Slug đoán được, nên chốt phải nằm cả ở `read` chứ không chỉ `search`."""
        self._ingest(BO, "mã khoá cửa nhà là 8642 nhớ đừng cho ai biết")
        ds = caps._h_wiki_search({"query": ""}, _ctx(BO))["text"]
        slug = ds.split("`")[1]
        self._chinh_phu()
        self.assertIn("Không có ghi chú",
                      caps._h_wiki_read({"slug": slug}, _ctx(CON))["text"])
        self.assertIn("8642", caps._h_wiki_read({"slug": slug}, _ctx(BO))["text"])

    def test_go_noi_thi_thoi_thay_ngay(self):
        self._ingest(ME, "lịch tiêm phòng của con vào thứ Ba tuần sau")
        self._binh_dang()
        self.assertIn("Tìm thấy", caps._h_wiki_search({"query": "tiêm phòng"},
                                                      _ctx(BO))["text"])
        self.cfg["memory_links"] = []
        self.assertIn("Không thấy ghi chú",
                      caps._h_wiki_search({"query": "tiêm phòng"}, _ctx(BO))["text"])


class GhiVanRIENG(_MoiTruong):
    def test_ingest_qua_tool_van_dong_dau_pham_vi_cua_minh(self):
        """Nối chỉ mở đường ĐỌC — ghi lẫn sang nhau thì gỡ nối không tách lại được."""
        self._binh_dang()
        self._ingest(BO, "bố hẹn nha sĩ vào sáng thứ Sáu tuần này")
        self.cfg["memory_links"] = []
        self.assertIn("Không thấy ghi chú",
                      caps._h_wiki_search({"query": "nha sĩ"}, _ctx(ME))["text"])

    def test_remember_qua_tool_ghi_vao_pham_vi_cua_minh(self):
        self._binh_dang()
        caps._h_remember({"fact": "Bố thích cà phê đen không đường"}, _ctx(BO))
        rieng_bo = state._memory_file(scope.khoa_du_lieu(BO))
        rieng_me = state._memory_file(scope.khoa_du_lieu(ME))
        self.assertIn("cà phê đen", rieng_bo.read_text("utf-8"))
        self.assertFalse(rieng_me.exists())


class BoNguCanhVaoSystemPrompt(_MoiTruong):
    """Bó ngữ cảnh đi vào prompt MỌI lượt — kết nối phải có hiệu lực ở đây."""

    def test_fact_muon_vao_duoc_prompt_khi_da_noi(self):
        from services.agent import super_context as sc
        state.append_memory("Mẹ dị ứng hải sản, tuyệt đối tránh tôm cua",
                            pham_vi=scope.khoa_du_lieu(ME))
        self.assertNotIn("dị ứng", sc.build_bundle(BO, "mẹ có kiêng gì không"))
        self._binh_dang()
        self.assertIn("dị ứng", sc.build_bundle(BO, "mẹ có kiêng gì không"))

    def test_PHU_khong_thay_gi_cua_CHINH_trong_prompt(self):
        from services.agent import super_context as sc
        state.append_memory("Lương bố tháng này ba mươi triệu",
                            pham_vi=scope.khoa_du_lieu(BO))
        self._chinh_phu()
        self.assertNotIn("Lương bố", sc.build_bundle(CON, "lương bố bao nhiêu"))


class MaNguonNoiDuDuong(unittest.TestCase):
    """Sửa hàm mà nơi gọi quên truyền `doc_them` là tính năng chết lặng lẽ."""

    def test_moi_duong_doc_deu_truyen_doc_them(self):
        goc = pathlib.Path(__file__).resolve().parents[1]
        for tep, ham in (("services/agent/capabilities.py", "w.search("),
                         ("services/agent/capabilities.py", "w.list_recent("),
                         ("services/agent/capabilities.py", "w.read("),
                         ("services/agent/super_context.py", "w.search("),
                         ("services/agent/super_context.py", "state.load_memory("),
                         ("services/agent/super_context.py", "state.search_memory(")):
            src = (goc / tep).read_text("utf-8")
            i = src.find(ham)
            self.assertGreater(i, 0, f"{tep}: {ham}")
            self.assertIn("doc_them", src[i:i + 200], f"{tep}: {ham}")


if __name__ == "__main__":
    unittest.main()
