"""memory_service (memory.sqlite) phải khoá theo PHẠM VI ĐẦY ĐỦ, không global.

Đây là kho ký ức thứ HAI (tách với agent state.py): nó recall + inject trên MỌI
lượt gọi model, và tự lưu lại từng lượt. Trước đây đường agent/bot gọi model
KHÔNG kèm khoá phạm vi nên memory_service rơi về khoá mặc định "chatgpt2api" —
MỘT KHO CHUNG cho mọi nhóm/chat/kênh. Hỏi ở nhóm này lại lòi ký ức nhóm khác.

Nay orchestrator gắn `_mem_scope` (= scope.khoa_du_lieu, đầy đủ kênh/chat/topic/
người) và `_mem_doc_them` (phạm vi đọc thêm nhờ kết nối bộ nhớ) vào payload.
File này khoá:
  * cách li: phạm vi khác KHÔNG đọc được của nhau;
  * kết nối: có doc_them thì đọc được (một chiều/hai chiều do scope quyết định);
  * ghi: chỉ vào phạm vi của chính mình (kết nối chỉ mở đường đọc);
  * lượt agent-internal KHÔNG có scope → KHÔNG dùng kho chung (chặn rò);
  * client API ngoài (không phải agent-internal) vẫn theo `_principal` như cũ.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import pathlib
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.memory_service import MemoryService  # noqa: E402

A = "v1|zalo|111||"
B = "v1|zalo|222||"


def _fresh() -> MemoryService:
    """MemoryService trỏ vào sqlite in-memory với đúng schema thật."""
    ms = MemoryService()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        "CREATE TABLE memories (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL,"
        " content TEXT NOT NULL, model TEXT DEFAULT '', hash TEXT UNIQUE,"
        " created_at REAL, last_seen_at REAL, uses INTEGER DEFAULT 0)")
    conn.execute(
        "CREATE VIRTUAL TABLE memories_fts USING fts5(content,"
        " content='memories', content_rowid='id', tokenize='unicode61')")
    conn.commit()
    ms._conn = conn
    return ms


class CachLiVaKetNoi(unittest.TestCase):
    def setUp(self):
        self.ms = _fresh()

    def test_pham_vi_khac_khong_doc_duoc(self):
        self.ms._store("USER: mã két sắt nhà là 4321", A)
        self.assertTrue(self.ms.recall("két sắt", A))
        self.assertEqual(self.ms.recall("két sắt", B), [])

    def test_doc_them_thi_doc_duoc(self):
        self.ms._store("USER: lịch tiêm phòng của con thứ Ba", A)
        self.assertEqual(self.ms.recall("tiêm phòng", B), [])
        self.assertTrue(self.ms.recall("tiêm phòng", B, doc_them=[A]))

    def test_ghi_chi_vao_pham_vi_cua_minh(self):
        self.ms._store("USER: bố hẹn nha sĩ thứ Sáu", A)
        n_b = self.ms._db().execute(
            "SELECT COUNT(*) FROM memories WHERE user_id=?", (B,)).fetchone()[0]
        self.assertEqual(n_b, 0)

    def test_reinforce_khong_cham_kho_muon(self):
        """recall qua doc_them chỉ ĐỌC — không bump uses của kho mượn."""
        self.ms._store("USER: xe máy biển số 29X1 màu đỏ", A)
        self.ms.recall("biển số", B, doc_them=[A])
        uses = self.ms._db().execute(
            "SELECT uses FROM memories WHERE user_id=?", (A,)).fetchone()[0]
        self.assertEqual(uses, 0)

    def test_recall_cua_chinh_minh_co_bump_uses(self):
        self.ms._store("USER: xe máy biển số 29X1 màu đỏ", A)
        self.ms.recall("biển số", A)
        uses = self.ms._db().execute(
            "SELECT uses FROM memories WHERE user_id=?", (A,)).fetchone()[0]
        self.assertGreaterEqual(uses, 1)


class PrepareLayScopeTuPayload(unittest.TestCase):
    def setUp(self):
        self.ms = _fresh()

    def _body(self, **kw):
        b = {"model": "auto",
             "messages": [{"role": "user", "content": "câu hỏi đủ dài để recall"}]}
        b.update(kw)
        return b

    def test_dung_mem_scope_lam_khoa(self):
        with mock.patch.object(self.ms, "recall", return_value=[]) as r:
            ctx = self.ms.prepare(self._body(_mem_scope=A, _mem_doc_them=[B],
                                             x_agent_internal=True))
        self.assertIsNotNone(ctx)
        self.assertEqual(r.call_args[0][1], A)             # user_id = scope
        self.assertEqual(r.call_args[1].get("doc_them"), [B])
        self.assertEqual(ctx.user_id, A)

    def test_agent_internal_khong_scope_thi_BO_QUA(self):
        """Lời gọi phụ của agent (tóm tắt…) không được dùng kho chung → chặn rò."""
        with mock.patch.object(self.ms, "recall", return_value=["x"]) as r:
            ctx = self.ms.prepare(self._body(x_agent_internal=True))
        self.assertIsNone(ctx)
        r.assert_not_called()

    def test_client_ngoai_van_theo_principal(self):
        """Không phải agent-internal → đường client API, khoá theo _principal."""
        with mock.patch.object(self.ms, "recall", return_value=[]) as r:
            self.ms.prepare(self._body(_principal="u_ngoai"))
        self.assertEqual(r.call_args[0][1], "u_ngoai")

    def test_capture_luu_dung_pham_vi(self):
        with mock.patch.object(self.ms, "recall", return_value=[]):
            ctx = self.ms.prepare(self._body(_mem_scope=A, x_agent_internal=True))
        with mock.patch.object(self.ms, "store_async") as s:
            ctx._store_turn("assistant trả lời")
        self.assertEqual(s.call_args[0][1], A)             # lưu vào scope A


class DuongDiTuCallModel(unittest.TestCase):
    """Chốt hồi quy: call_model + orchestrator phải thật sự gắn scope vào payload."""

    def test_ma_nguon_noi_du_duong(self):
        goc = pathlib.Path(__file__).resolve().parents[1]
        rt = (goc / "services" / "agent" / "runtime.py").read_text("utf-8")
        self.assertIn('payload["_mem_scope"] = pham_vi', rt)
        self.assertIn('payload["_mem_doc_them"]', rt)
        orch = (goc / "services" / "agent" / "orchestrator.py").read_text("utf-8")
        self.assertIn("pham_vi=_pham_vi(user_id), doc_them=_doc_them(user_id)", orch)


if __name__ == "__main__":
    unittest.main()
