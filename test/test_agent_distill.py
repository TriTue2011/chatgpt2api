"""Unit tests: truy hồi lai RRF (state/wiki), link graph wiki, distill hồ sơ.

Bốn cải tiến học từ kiến trúc TencentDB-Agent-Memory, cài thuần Python:
rrf.py, state._tim_trong_index, wiki.search/read + [[link]], distill.run_once.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import distill  # noqa: E402
from services.agent import rrf  # noqa: E402
from services.agent import session as sess  # noqa: E402
from services.agent import state  # noqa: E402
from services.agent import wiki  # noqa: E402
from services.config import config  # noqa: E402
from test._fakes import FakeCallModel, install_call_model  # noqa: E402


class RRFTests(unittest.TestCase):
    def test_tron_hang_uu_tien_muc_dong_thuan(self) -> None:
        # b đứng cao ở cả ba bảng → phải thắng a (chỉ đứng đầu một bảng)
        ra = rrf.xep_hang_rrf([["a", "b", "c"], ["b", "c", "a"], ["b"]])
        self.assertEqual(ra[0], "b")
        self.assertEqual(set(ra), {"a", "b", "c"})

    def test_tron_hang_on_dinh_khi_hoa(self) -> None:
        self.assertEqual(rrf.xep_hang_rrf([["x", "y"]]), ["x", "y"])

    def test_diem_tam_gram(self) -> None:
        self.assertAlmostEqual(rrf.diem_tam_gram("tiem phong", "tiem phong"), 1.0)
        self.assertEqual(rrf.diem_tam_gram("abc", "xyz"), 0.0)
        self.assertEqual(rrf.diem_tam_gram("", "abc"), 0.0)

    def test_bao_phu_tam_gram(self) -> None:
        cao = rrf.bao_phu_tam_gram("tiem phong", "be tiem phong ngay mai")
        thap = rrf.bao_phu_tam_gram("tiem phong", "hom nay troi mua to")
        self.assertGreater(cao, 0.8)
        self.assertLess(thap, 0.2)


class _StateTmpMixin(unittest.TestCase):
    """Trỏ toàn bộ đường dẫn trí nhớ của state.py vào thư mục tạm."""

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._patches = [
            mock.patch.object(state, "_AGENT_DIR", root),
            mock.patch.object(state, "_USERS_DIR", root / "users"),
            mock.patch.object(state, "_MEMORY_FILE", root / "MEMORY.md"),
            mock.patch.object(state, "_MEMORY_DB_PATH", root / "memory_fts.sqlite"),
            mock.patch.object(state, "_MEMORY_SCOPE_DIR", root / "memory"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        for c in state._mem_conn.values():
            try:
                c.close()
            except Exception:
                pass
        state._mem_conn.clear()
        self._tmp.cleanup()
        super().tearDown()


class MemorySearchTests(_StateTmpMixin):
    def test_bm25_thang_dong_moi_chi_khop_mot_tu(self) -> None:
        state.append_memory("Bé Bin tiêm phòng viêm gan B mũi 2 ngày 05-08-2026")
        state.append_memory("Bé thích ăn kem dâu")
        state.append_memory("Nhà đổi mật khẩu wifi")
        state.append_memory("Bé ngủ sớm hơn từ tuần này")
        ra = state.search_memory("lịch tiêm phòng của bé", limit=3)
        self.assertTrue(ra, "phải có kết quả")
        self.assertIn("tiêm phòng", ra[0])

    def test_tam_gram_vot_query_dinh_tu(self) -> None:
        # "tiemphong viemgan" không khớp TỪ nguyên vẹn nào → FTS trắng tay,
        # quét tam-gram phải vớt được dòng gần đúng.
        state.append_memory("Bé Bin tiêm phòng viêm gan B mũi 2 ngày 05-08-2026")
        state.append_memory("Nhà đổi mật khẩu wifi")
        ra = state.search_memory("tiemphong viemgan", limit=3)
        self.assertTrue(any("tiêm phòng" in ln for ln in ra))

    def test_khong_khop_gi_tra_rong(self) -> None:
        state.append_memory("Nhà đổi mật khẩu wifi")
        self.assertEqual(state.search_memory("zzz qqq www", limit=3), [])

    def test_dong_khop_moi_nhat_luon_co_mat(self) -> None:
        # 60 dòng cũ cùng chủ đề (ngắn, bm25 khoẻ) không được che mất fact
        # MỚI NHẤT — bảo đảm kế thừa từ bản cũ ORDER BY id DESC.
        for i in range(60):
            state.append_memory(f"đổi mật khẩu wifi lần {i}")
        state.append_memory(
            "mật khẩu wifi mới của cả nhà từ 11-08-2026 là hoa-sen-2026, "
            "nhớ báo cho khách tới chơi")
        ra = state.search_memory("mật khẩu wifi", limit=6)
        self.assertTrue(any("hoa-sen-2026" in ln for ln in ra))


class UserProfileTests(_StateTmpMixin):
    def test_ghi_va_doc_ho_so(self) -> None:
        ok = state.save_user_profile("u9", "- Thích cà phê sáng")
        self.assertTrue(ok)
        text = state.load_user_profile("u9")
        self.assertIn(state.PROFILE_AUTO_MARKER, text)
        self.assertIn("Thích cà phê sáng", text)

    def test_giu_phan_soan_tay(self) -> None:
        users = Path(self._tmp.name) / "users"
        users.mkdir(parents=True, exist_ok=True)
        (users / "u9.md").write_text("Ghi chú tay của chủ nhà", encoding="utf-8")
        state.save_user_profile("u9", "- Thích cà phê sáng")
        state.save_user_profile("u9", "- Thích trà đá")
        text = state.load_user_profile("u9")
        self.assertIn("Ghi chú tay của chủ nhà", text)
        self.assertIn("Thích trà đá", text)
        self.assertNotIn("Thích cà phê sáng", text)
        self.assertEqual(text.count(state.PROFILE_AUTO_MARKER), 1)

    def test_ho_so_rong_khong_ghi(self) -> None:
        self.assertFalse(state.save_user_profile("u9", "   "))
        self.assertEqual(state.load_user_profile("u9"), "")


class WikiLinkGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        wiki._reset_for_tests(root)
        (root / "notes").mkdir(parents=True, exist_ok=True)
        (root / "notes" / "note-a.md").write_text(
            "# Lịch tiêm phòng\n\nLịch tiêm phòng viêm gan cho bé, "
            "xem thêm [[note-b]].\n",
            encoding="utf-8",
        )
        time.sleep(0.02)  # mtime tách bạch để thứ tự độ mới ổn định
        (root / "notes" / "note-b.md").write_text(
            "# Sổ sức khỏe\n\nCân nặng của bé theo tháng.\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_search_kem_ghi_chu_lien_quan(self) -> None:
        hits = wiki.search("tiêm phòng viêm gan")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["slug"], "note-a")
        self.assertEqual(hits[0]["related"], ["note-b"])

    def test_search_vot_query_dinh_tu(self) -> None:
        hits = wiki.search("tiemphong viemgan cho be")
        self.assertTrue(any(h["slug"] == "note-a" for h in hits))

    def test_read_co_footer_link_xuoi_va_backlink(self) -> None:
        a = wiki.read("note-a")
        b = wiki.read("note-b")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertIn("`note-b`", a)   # link xuôi
        self.assertIn("`note-a`", b)   # backlink

    def test_link_toi_note_khong_ton_tai_bi_loai(self) -> None:
        root = Path(self._tmp.name)
        (root / "notes" / "note-c.md").write_text(
            "# C\n\nnhắc [[note-ma]] không tồn tại và [[note-a]].\n",
            encoding="utf-8",
        )
        hits = wiki.search("nhắc không tồn tại")
        hit_c = next(h for h in hits if h["slug"] == "note-c")
        self.assertEqual(hit_c["related"], ["note-a"])

    def test_link_dang_notes_prefix_va_pipe(self) -> None:
        # Biến thể index.md ([[notes/<slug>|Tiêu đề]]) cũng phải thành cạnh.
        root = Path(self._tmp.name)
        (root / "notes" / "note-d.md").write_text(
            "# D\n\nxem hồ sơ [[notes/note-a|Lịch tiêm phòng]] nhé.\n",
            encoding="utf-8",
        )
        hits = wiki.search("hồ sơ nhé")
        hit_d = next(h for h in hits if h["slug"] == "note-d")
        self.assertEqual(hit_d["related"], ["note-a"])

    def test_footer_khong_vuot_tran_va_khong_bi_xen(self) -> None:
        # Note dài hơn max_note_chars: footer vẫn nguyên vẹn ở cuối và tổng
        # độ dài không vượt trần (hợp đồng cũ của read()).
        root = Path(self._tmp.name)
        than = "# Dài\n\n" + ("nội dung rất dài. " * 600) + "\n[[note-b]]\n"
        self.assertGreater(len(than), wiki.max_note_chars())
        (root / "notes" / "note-dai.md").write_text(than, encoding="utf-8")
        text = wiki.read("note-dai")
        self.assertIsNotNone(text)
        self.assertLessEqual(len(text), wiki.max_note_chars())
        self.assertIn("`note-b`", text[-250:])


_REPLY_CHUAN = (
    "## HỒ SƠ\n"
    "- Tên Tùng, thích cà phê sáng\n"
    "- Quan tâm lịch học của con\n"
    "## FACT MỚI\n"
    "- Hẹn khám răng ngày 15-08-2026\n"
)


class DistillParseTests(unittest.TestCase):
    def test_tach_khuon_chuan(self) -> None:
        ho_so, facts = distill._tach_ket_qua(_REPLY_CHUAN)
        self.assertIn("cà phê sáng", ho_so)
        self.assertEqual(facts, ["Hẹn khám răng ngày 15-08-2026"])

    def test_khong_co_fact(self) -> None:
        ho_so, facts = distill._tach_ket_qua(
            "## HỒ SƠ\n- Tên Tùng\n## FACT MỚI\n- KHÔNG CÓ\n")
        self.assertIn("Tên Tùng", ho_so)
        self.assertEqual(facts, [])

    def test_fact_chua_cum_khong_co_van_duoc_giu(self) -> None:
        # sentinel so cả dòng — fact phủ định thật ("không có dị ứng")
        # không được nuốt.
        _, facts = distill._tach_ket_qua(
            "## HỒ SƠ\n- Tên Tùng\n## FACT MỚI\n"
            "- Bé không có dị ứng penicillin, bác sĩ xác nhận 10-08-2026\n")
        self.assertEqual(len(facts), 1)
        self.assertIn("không có dị ứng", facts[0])

    def test_khuon_vo_tra_rong(self) -> None:
        ho_so, facts = distill._tach_ket_qua("xin chào, tôi không theo khuôn")
        self.assertEqual(ho_so, "")
        self.assertEqual(facts, [])


class DistillRunTests(_StateTmpMixin):
    def setUp(self) -> None:
        super().setUp()
        root = Path(self._tmp.name)
        sess._reset_for_tests(root / "sessions.sqlite")
        distill._reset_for_tests(root / "distill_state.json")
        self._cfg = mock.patch.dict(config.data, {
            "agent_distill": {"enabled": True, "hour": 0, "min_new_turns": 2},
            "agent_session": {"enabled": True},
        })
        self._cfg.start()

    def tearDown(self) -> None:
        self._cfg.stop()
        sess._reset_for_tests()
        super().tearDown()

    def _seed_user(self, uid: str = "u1") -> None:
        for role, text in [
            ("user", "Anh tên Tùng, hay uống cà phê sáng"),
            ("assistant", "Dạ em nhớ rồi ạ"),
            ("user", "Mai anh đi khám răng lúc 9h"),
        ]:
            sess.append_turn(uid, role, text)
        sess.save_history(uid, [
            {"role": "user", "content": "Anh tên Tùng, hay uống cà phê sáng"},
            {"role": "assistant", "content": "Dạ em nhớ rồi ạ"},
        ])

    def test_run_once_ghi_ho_so_va_fact(self) -> None:
        self._seed_user()
        with install_call_model(FakeCallModel(text=_REPLY_CHUAN)) as fake:
            out = distill.run_once()
        self.assertTrue(out["ok"])
        self.assertEqual(out["users"], 1)
        self.assertEqual(out["profiles"], 1)
        self.assertEqual(out["facts"], 1)
        self.assertEqual(len(fake.calls), 1)
        prof = state.load_user_profile("u1")
        self.assertIn("cà phê sáng", prof)
        self.assertIn(state.PROFILE_AUTO_MARKER, prof)
        from services.agent.scope import khoa_du_lieu
        mem = state.load_memory(limit_chars=6000, pham_vi=khoa_du_lieu("u1"))
        self.assertIn("khám răng", mem)

    def test_moi_ngay_mot_lan_va_bo_qua_user_thieu_turn(self) -> None:
        self._seed_user()
        self.assertTrue(distill.due_now())
        with install_call_model(FakeCallModel(text=_REPLY_CHUAN)):
            distill.run_once()
        self.assertFalse(distill.due_now())  # hôm nay đã chạy
        # chạy lại ngay: không user nào đủ turn MỚI kể từ mốc đã chưng cất
        with install_call_model(FakeCallModel(text=_REPLY_CHUAN)) as fake:
            out = distill.run_once()
        self.assertEqual(out["users"], 0)
        self.assertEqual(len(fake.calls), 0)

    def test_model_loi_khong_ghi_gi_va_giu_watermark(self) -> None:
        self._seed_user()
        with install_call_model(FakeCallModel(replies=[{"error": "boom"}])):
            out = distill.run_once()
        self.assertTrue(out["ok"])
        self.assertEqual(out["profiles"], 0)
        self.assertEqual(state.load_user_profile("u1"), "")
        # Model lỗi thì watermark PHẢI giữ nguyên: chạy lại khi model đã
        # khoẻ, chất liệu cũ vẫn được chưng cất (không mất ngày hôm đó).
        with install_call_model(FakeCallModel(text=_REPLY_CHUAN)) as fake:
            out2 = distill.run_once()
        self.assertEqual(out2["profiles"], 1)
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("cà phê sáng", state.load_user_profile("u1"))

    def test_tat_qua_config(self) -> None:
        with mock.patch.dict(config.data, {"agent_distill": {"enabled": False}}):
            out = distill.run_once()
        self.assertFalse(out["ok"])

    def test_phien_nhom_dung_chung_khong_chung_ho_so(self) -> None:
        # Khoá nhóm KHÔNG mang ':u<uid>' (tắt tách-người) → bỏ qua, không
        # được trộn nhiều người vào một "hồ sơ nhóm".
        self._seed_user("-100#2")
        with install_call_model(FakeCallModel(text=_REPLY_CHUAN)) as fake:
            out = distill.run_once()
        self.assertEqual(out["users"], 0)
        self.assertEqual(len(fake.calls), 0)
        self.assertEqual(state.load_user_profile("-100#2"), "")

    def test_phien_nhom_tach_nguoi_van_duoc_chung(self) -> None:
        # Cùng nhóm nhưng khoá mang ':u9' (mặc định tách người) → mỗi người
        # một hồ sơ riêng, chưng bình thường.
        self._seed_user("-100#2:u9")
        with install_call_model(FakeCallModel(text=_REPLY_CHUAN)):
            out = distill.run_once()
        self.assertEqual(out["profiles"], 1)
        self.assertIn("cà phê sáng", state.load_user_profile("-100#2:u9"))


if __name__ == "__main__":
    unittest.main()
