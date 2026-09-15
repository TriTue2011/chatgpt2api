"""Phiên hai mốc (mềm/cứng) + mã tin trong bảng `turns`.

Vì sao có bộ test này:

* **Mốc cũ gộp làm một.** `_NGHI_DONG_PHIEN = 600` vừa cấp phiên mới vừa XOÁ
  đuôi hội thoại, nên nghỉ ăn trưa xong hỏi tiếp là mất mạch. Nay tách: mốc
  MỀM (30') chỉ đổi mã phiên và GIỮ đuôi; mốc CỨNG (2h) mới nén + xoá.
  Lẫn hai mốc là hỏng đúng thứ vừa sửa, nên khoá bằng test.

* **Khớp tin trích theo mốc thời gian ±900 giây là đoán.** Trong nhóm đông,
  15 phút có hàng chục tin. Có `message_id` thì phải tra CHÍNH XÁC.

* **Bảng cũ trên máy chủ không có cột mới.** `CREATE TABLE IF NOT EXISTS`
  không thêm cột — phải `ALTER TABLE`, và mở lại lần hai không được nổ.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import session as sess  # noqa: E402


def _db_moi() -> Path:
    return Path(tempfile.mkdtemp()) / "s.sqlite"


class MaTinTrongTurnsTests(unittest.TestCase):
    def setUp(self):
        sess._reset_for_tests(_db_moi())

    def test_ghi_va_tra_theo_ma_tin(self):
        sess.append_turn("u1", "user", "vụ cháy sao rồi", message_id="m-100")
        row = sess.turn_by_message_id("u1", "m-100")
        self.assertEqual(row["content"], "vụ cháy sao rồi")
        self.assertEqual(row["role"], "user")

    def test_ma_tin_khong_co_tra_none(self):
        sess.append_turn("u1", "user", "abc", message_id="m-1")
        self.assertIsNone(sess.turn_by_message_id("u1", "m-khong-co"))
        self.assertIsNone(sess.turn_by_message_id("u1", ""))

    def test_khong_lan_sang_nguoi_khac(self):
        """Mã tin phải xét trong phạm vi TỪNG người, không tra chéo."""
        sess.append_turn("u1", "user", "của u1", message_id="trung-ma")
        sess.append_turn("u2", "user", "của u2", message_id="trung-ma")
        self.assertEqual(sess.turn_by_message_id("u1", "trung-ma")["content"], "của u1")
        self.assertEqual(sess.turn_by_message_id("u2", "trung-ma")["content"], "của u2")

    def test_va_ma_tin_sau_khi_gui(self):
        """Lượt bot ghi TRƯỚC lúc gửi nên chưa có mã — phải vá được sau."""
        rid = sess.append_turn("u1", "assistant", "bản tin đây ạ")
        self.assertIsNotNone(rid)
        self.assertIsNone(sess.turn_by_message_id("u1", "m-out"))
        sess.set_message_id(rid, "m-out")
        self.assertEqual(sess.turn_by_message_id("u1", "m-out")["content"], "bản tin đây ạ")

    def test_va_ma_rong_thi_bo_qua_khong_no(self):
        rid = sess.append_turn("u1", "assistant", "x")
        sess.set_message_id(rid, "")
        sess.set_message_id(None, "m-1")   # không có rowid → im lặng

    def test_tim_kiem_toan_van_van_chay(self):
        """Thêm cột không được làm hỏng FTS đang có."""
        sess.append_turn("u1", "user", "đột quỵ là gì", message_id="m-1")
        self.assertEqual(len(sess.search("u1", "đột quỵ")), 1)


class DiChuyenBangCuTests(unittest.TestCase):
    """Bảng đã nằm sẵn trên máy chủ (chưa có cột mới) phải nâng cấp được."""

    def test_bang_cu_van_nang_cap_va_giu_du_lieu(self):
        p = _db_moi()
        p.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(p))
        c.execute("CREATE TABLE sessions (user_id TEXT PRIMARY KEY,"
                  " messages TEXT NOT NULL DEFAULT '[]',"
                  " summary TEXT NOT NULL DEFAULT '', updated_at REAL)")
        c.execute("CREATE TABLE turns (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL,"
                  " role TEXT NOT NULL, content TEXT NOT NULL, created_at REAL)")
        c.execute("CREATE VIRTUAL TABLE turns_fts USING fts5(content,"
                  " content='turns', content_rowid='id', tokenize='unicode61')")
        c.execute("INSERT INTO turns (user_id, role, content, created_at)"
                  " VALUES ('u9','user','tin cũ',1.0)")
        c.commit()
        c.close()

        sess._reset_for_tests(p)
        self.assertIsNotNone(sess.append_turn("u9", "user", "tin mới", message_id="mm"))
        self.assertIsNotNone(sess.turn_by_message_id("u9", "mm"))
        con = sess._db().execute(
            "SELECT content FROM turns WHERE content='tin cũ'").fetchone()
        self.assertIsNotNone(con, "dữ liệu cũ không được mất khi nâng cấp bảng")

        # Mở lại lần hai: ALTER chạy lại KHÔNG được nổ.
        sess._reset_for_tests(p)
        self.assertIsNotNone(sess.append_turn("u9", "user", "tin ba"))


class MocMemVaCungTests(unittest.TestCase):
    """Mốc MỀM đổi phiên nhưng GIỮ đuôi; mốc CỨNG mới nén + xoá."""

    def setUp(self):
        sess._reset_for_tests(_db_moi())
        from services.agent import orchestrator as orch
        self.orch = orch
        orch._history.pop("u1", None)

    def _im_lang(self, giay: float):
        """Giả lập người này im lặng `giay` giây."""
        return patch.object(sess, "last_activity", return_value=time.time() - giay)

    def test_chua_toi_moc_mem_thi_khong_doi_gi(self):
        with self._im_lang(60):
            self.assertEqual(self.orch._muc_nghi("u1"), "")

    def test_qua_moc_mem_la_soft(self):
        with self._im_lang(sess.soft_idle_s() + 60):
            self.assertEqual(self.orch._muc_nghi("u1"), "soft")

    def test_qua_moc_cung_la_hard(self):
        with self._im_lang(sess.hard_idle_s() + 60):
            self.assertEqual(self.orch._muc_nghi("u1"), "hard")

    def test_dong_phien_khong_bat_lenh_nha_cho_tom_tat(self):
        """Đo 15/09/2026: lệnh HA sau ≥2h nghỉ chờ 20 s vì tóm tắt chạy TRƯỚC.

        Tóm tắt giả chậm 2 giây; đường tắt nhà phải tới trong chưa đầy 1 giây,
        và tóm tắt vẫn phải được ghi sau đó.
        """
        import threading as _th
        from services.agent import compaction as compact
        from services.agent import state
        import services.protocol.openai_v1_chat_complete as api

        sess.save_history("u1", [{"role": "user", "content": "mai nhắc anh họp 9h"},
                                 {"role": "assistant", "content": "dạ em nhớ rồi ạ"}])
        bat_dau = time.time()
        moc = {}

        def _tom_tat_cham(*a, **k):
            time.sleep(2)
            moc["tom_tat_xong"] = time.time() - bat_dau
            return "- có hẹn họp 9h mai"

        def _den(*a, **k):
            moc["den"] = time.time() - bat_dau
            return ("Đã thực hiện xong lệnh điều khiển thiết bị.", True, "_ha_local_intent")

        with self._im_lang(sess.hard_idle_s() + 60), \
             patch.object(compact, "summarize", side_effect=_tom_tat_cham), \
             patch.object(api, "ha_local_fastpath_chi_tiet", side_effect=_den), \
             patch.object(self.orch, "call_model",
                          return_value={"choices": [{"message": {"content": "Dạ em tắt rồi ạ"}}]}), \
             patch.object(state, "load_memory", return_value=""):
            self.orch._orchestrate_locked("tắt đèn bếp", "u1", ha_fastpath=True)
            for t in _th.enumerate():
                if t.name == "nen-phien-cu":
                    t.join(5)
        self.assertLess(moc["den"], 1.0, "lệnh nhà vẫn phải chờ tóm tắt xong")
        self.assertIn("họp 9h", sess.load_summary("u1"))

    def test_moc_cung_luon_lon_hon_hoac_bang_moc_mem(self):
        self.assertGreaterEqual(sess.hard_idle_s(), sess.soft_idle_s())

    def test_moc_cung_mac_dinh_dai_hon_10_phut_cu(self):
        """Cả điểm của việc tách mốc: đừng đóng hội thoại sau 10 phút nữa."""
        self.assertGreater(sess.hard_idle_s(), 600)

    def test_cap_phien_moi_doi_ma(self):
        a = sess.moi_phien("u1")
        b = sess.moi_phien("u1")
        self.assertTrue(a and b)
        self.assertNotEqual(a, b)
        self.assertEqual(sess.current_session_id("u1"), b)

    def test_turn_duoc_dong_dau_ma_phien(self):
        sid = sess.moi_phien("u1")
        sess.append_turn("u1", "user", "xin chào", session_id=sid)
        row = sess._db().execute(
            "SELECT session_id FROM turns WHERE user_id='u1'").fetchone()
        self.assertEqual(row[0], sid)


class DongPhienNenTests(unittest.TestCase):
    """Đóng phiên phải NÉN đuôi vào tóm tắt, kể cả hội thoại NGẮN.

    `maybe_compact` chỉ chạy khi lịch sử đủ dài, nên trước đây phiên ngắn bị
    đóng là mất trắng — `hist.clear()` vứt thẳng.
    """

    def setUp(self):
        sess._reset_for_tests(_db_moi())

    def test_nen_ca_hoi_thoai_ngan(self):
        from services.agent import compaction as compact
        hist = [{"role": "user", "content": "mai nhắc anh họp 9h"},
                {"role": "assistant", "content": "dạ em nhớ rồi ạ"}]
        with patch.object(compact, "summarize", return_value="- có hẹn họp 9h mai"):
            self.assertTrue(compact.dong_phien("u1", hist))
        self.assertIn("họp 9h", sess.load_summary("u1"))

    def test_hoi_thoai_rong_thi_khong_lam_gi(self):
        from services.agent import compaction as compact
        self.assertFalse(compact.dong_phien("u1", []))

    def test_tom_tat_hong_thi_khong_nem_loi(self):
        from services.agent import compaction as compact
        with patch.object(compact, "summarize", side_effect=RuntimeError("model die")):
            self.assertFalse(compact.dong_phien("u1", [{"role": "user", "content": "x"}]))


if __name__ == "__main__":
    unittest.main()
