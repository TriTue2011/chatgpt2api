"""Nạp tài liệu qua KÊNH CHAT (Zalo/Telegram) — đúng kho, đúng loại, vào RAG thật.

Ba lỗi im lặng module này chặn, cả ba đều báo "đã nạp" cho người gửi:

1. ẢNH CHỈ VÀO .md, KHÔNG VÀO RAG. `ingest_teacher_from_photo` bản cũ ghi duy
   nhất `data/agent/teacher/sgk/lopN/{mon}.md` rồi trả "Đã nạp ảnh vào SGK
   teacher 🎓". Nhưng .md chỉ được `search_sgk` (khớp từ khoá) đọc; còn `ask_sgk`
   của MCP hub — thứ mà bài giảng, bài tập ba mức và mọi câu hỏi qua bot dùng —
   đọc kho vector. Ảnh trang sách gửi vào rồi mà bot KHÔNG BAO GIỜ tìm ra.

2. MỌI THỨ VÀO KHO HỌC SINH. Cả hai đường (ảnh và PDF) đóng cứng `kb_giao_duc`.
   Gửi một quyển sách giáo viên qua Zalo thì lời hướng dẫn dạy nằm trong kho nội
   dung học sinh, rồi `ask_sgk` đọc ra như thể học sinh phải học. Đúng lỗi đã vá
   ở đường crawl và đường tải lên, nhưng đường KÊNH CHAT chưa vá theo.

3. "TIẾNG VIỆT" → MÃ `van`. `parse_teacher_meta` có bảng môn RIÊNG của nó, ánh xạ
   "tiếng việt" sang `van`. Nhưng `van` là Ngữ văn (lớp 6–12); Tiếng Việt (lớp
   1–5) là mã `tviet`. Gõ "lớp 2 tiếng việt" → tài liệu vào Ngữ văn lớp 2, một tổ
   hợp không tồn tại. Bảng đó cũng chỉ biết 3/10 môn.

Không gọi mạng: chặn `push_sgk_to_rag` / `import_sgk_pdf` và soi THAM SỐ được
truyền. Cái cần khoá là "có đẩy vào RAG không, vào kho nào, kind nào" — đúng chỗ
lỗi nằm, và đo được chắc chắn.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import pdf_intent as pi
from services import photo_intent as phi
from services.agent import sgk_fetch as sf


class TestParseTeacherMeta(unittest.TestCase):
    def test_giu_nguyen_hanh_vi_cu(self):
        """Ba ca cũ phải y nguyên — không có `kind`/`volume` khi không ai khai."""
        self.assertEqual(pi.parse_teacher_meta("5 toán"),
                         {"grade": 5, "subject": "toan"})
        self.assertEqual(pi.parse_teacher_meta("lớp 9 văn"),
                         {"grade": 9, "subject": "van"})
        self.assertIsNone(pi.parse_teacher_meta("toán thôi"))
        self.assertIsNone(pi.parse_teacher_meta("lớp 5"))

    def test_tieng_viet_ra_tviet_khong_phai_van(self):
        """`van` là Ngữ văn 6–12. Tiếng Việt 1–5 là `tviet` — hai mã khác nhau."""
        self.assertEqual(pi.parse_teacher_meta("lớp 2 tiếng việt")["subject"],
                         "tviet")

    def test_bay_mon_con_lai_nap_duoc(self):
        for cau, mong in (("lớp 10 hoá", "hoa"), ("lớp 11 vật lí", "ly"),
                          ("lớp 12 sinh học", "sinh"), ("lớp 10 địa lí", "dia"),
                          ("lớp 11 lịch sử", "su")):
            self.assertEqual(pi.parse_teacher_meta(cau)["subject"], mong, cau)

    def test_lich_su_va_dia_li_khong_roi_ve_su_hay_dia(self):
        """Sách gộp lớp 4–9 có mã riêng `sudia`. Cụm dài phải thắng cụm ngắn."""
        self.assertEqual(pi.parse_teacher_meta("lớp 4 lịch sử và địa lí")["subject"],
                         "sudia")

    def test_khai_loai(self):
        for cau, mong in (("lớp 4 sgv toán", "sgv"),
                          ("lớp 4 sách giáo viên toán", "sgv"),
                          ("lớp 4 vở bài tập toán", "vbt"),
                          ("lớp 4 toán tài liệu tập huấn", "tap_huan")):
            self.assertEqual(pi.parse_teacher_meta(cau).get("kind"), mong, cau)

    def test_khong_khai_loai_thi_khong_co_khoa(self):
        """Caller mặc định "sgk"; trả sẵn "sgk" là mất phân biệt "không khai"."""
        self.assertNotIn("kind", pi.parse_teacher_meta("lớp 4 toán"))

    def test_cum_loai_khong_an_vao_ten_mon(self):
        """"sách giáo viên" chứa "viên"; "vở bài tập" chứa "tập" — cắt trước khi
        tìm môn, không thì môn nhận sai."""
        r = pi.parse_teacher_meta("lớp 4 sách giáo viên toán")
        self.assertEqual((r["subject"], r["kind"]), ("toan", "sgv"))

    def test_khai_tap(self):
        self.assertEqual(pi.parse_teacher_meta("lớp 2 tiếng việt tập hai")["volume"],
                         "tập hai")
        self.assertEqual(pi.parse_teacher_meta("lớp 4 toán tập một")["volume"],
                         "tập một")

    def test_khong_khai_tap_thi_khong_doan(self):
        """Gắn "tập một" cho quyển chưa rõ tập là bộ lọc theo tập trả sai tập."""
        self.assertNotIn("volume", pi.parse_teacher_meta("lớp 4 toán"))

    def test_bai_tap_2_khong_thanh_tap_hai(self):
        """"vở bài tập 2" — số 2 là thứ tự bài, không phải tập hai."""
        r = pi.parse_teacher_meta("lớp 4 vở bài tập toán 2")
        self.assertEqual(r.get("kind"), "vbt")
        self.assertNotIn("volume", r)

    def test_alias_ngan_khong_khop_giua_tu(self):
        """"en" là alias của Tiếng Anh. Không có biên từ thì "kiến" cũng khớp,
        và mọi câu tiếng Việt thành môn Tiếng Anh."""
        self.assertIsNone(pi.parse_teacher_meta("lớp 4 kiến thức"))


class TestAnhVaoRAG(unittest.TestCase):
    """Lỗi 1 + 2: ảnh phải VÀO RAG, và vào ĐÚNG kho theo loại."""

    def _chay(self, **kw):
        with mock.patch.object(phi, "analyze_photo",
                               return_value="# Trang 12\n\nNội dung bài học."), \
             mock.patch("services.agent.teacher_workspace.push_sgk_to_rag") as day:
            day.return_value = {"ok": True, "chunks_added": 3,
                                "collection": kw.get("_col", "kb_giao_duc")}
            r = phi.ingest_teacher_from_photo(
                b"\x89PNG-gia", grade=kw.get("grade", 4),
                subject=kw.get("subject", "toan"),
                kind=kw.get("kind", "sgk"), caption=kw.get("caption", ""))
        return r, day

    def test_co_day_vao_rag(self):
        """Bản cũ KHÔNG gọi hàm này lần nào — ảnh không bao giờ vào kho vector."""
        r, day = self._chay()
        self.assertTrue(r["ok"])
        day.assert_called_once()

    def test_dung_kho_theo_loai(self):
        for kind in ("sgk", "sgv", "vbt", "tap_huan"):
            _, day = self._chay(kind=kind)
            self.assertEqual(day.call_args.kwargs["collection"],
                             sf.KIND_COLLECTION[kind], kind)

    def test_kind_di_kem_vao_metadata(self):
        _, day = self._chay(kind="sgv")
        self.assertEqual(day.call_args.kwargs["kind"], "sgv")

    def test_suy_tap_tu_loi_kem_anh(self):
        _, day = self._chay(caption="lớp 2 tiếng việt tập hai")
        self.assertEqual(day.call_args.kwargs["volume"], "tập hai")

    def test_khong_co_loi_kem_thi_tap_trong(self):
        _, day = self._chay(caption="")
        self.assertEqual(day.call_args.kwargs["volume"], "")

    def test_bao_so_doan_rag_cho_nguoi_gui(self):
        """Không nói ra thì "đã nạp" chỉ nói về .md, mà bot tra bằng kho vector."""
        r, _ = self._chay()
        self.assertIn("3 đoạn", r["text"])

    def test_rag_that_bai_thi_canh_bao_chu_khong_bao_xong(self):
        with mock.patch.object(phi, "analyze_photo", return_value="# T\n\nnội dung"), \
             mock.patch("services.agent.teacher_workspace.push_sgk_to_rag",
                        return_value={"ok": False, "chunks_added": 0,
                                      "errors": ["hub 500"]}):
            r = phi.ingest_teacher_from_photo(b"x", grade=4, subject="toan")
        self.assertIn("RAG chưa nhận", r["text"])
        self.assertIn("hub 500", r["text"])

    def test_chi_sgk_ghi_vao_md(self):
        """`search_sgk` đọc .md và KHÔNG phân biệt loại — nhét SGV vào là trộn."""
        import services.agent.teacher_workspace as tw
        for kind, mong in (("sgk", True), ("sgv", False), ("vbt", False)):
            with mock.patch.object(phi, "analyze_photo", return_value="# T\n\nx"), \
                 mock.patch("services.agent.teacher_workspace.push_sgk_to_rag",
                            return_value={"ok": True, "chunks_added": 1}), \
                 mock.patch.object(tw, "_ensure_seeded"), \
                 mock.patch("pathlib.Path.write_text") as ghi, \
                 mock.patch("pathlib.Path.mkdir"), \
                 mock.patch("pathlib.Path.exists", return_value=False):
                phi.ingest_teacher_from_photo(b"x", grade=4, subject="toan",
                                              kind=kind)
            self.assertEqual(ghi.called, mong, kind)


class TestPdfQuaKenh(unittest.TestCase):
    """Lỗi 2 cho đường PDF: `ingest_teacher` đóng cứng kho học sinh."""

    def _chay(self, **kw):
        with mock.patch("services.agent.teacher_workspace.import_sgk_pdf") as nap:
            nap.return_value = {"ok": True, "chars": 100, "mode": "append",
                                "path": "/x.md", "grade": 4, "subject": "toan",
                                "rag": {"ok": True, "chunks_added": 5,
                                        "collection": "kb_giao_duc"}}
            r = pi.ingest_teacher("/tmp/x.pdf", grade=4, subject="toan",
                                  name="x.pdf", kind=kw.get("kind", "sgk"),
                                  caption=kw.get("caption", ""))
        return r, nap

    def test_dung_kho_theo_loai(self):
        for kind in ("sgk", "sgv", "vbt", "tap_huan"):
            _, nap = self._chay(kind=kind)
            self.assertEqual(nap.call_args.kwargs["collection"],
                             sf.KIND_COLLECTION[kind], kind)

    def test_truyen_kind_xuong_duoi(self):
        _, nap = self._chay(kind="tap_huan")
        self.assertEqual(nap.call_args.kwargs["kind"], "tap_huan")

    def test_chi_sgk_ghi_md(self):
        _, nap = self._chay(kind="sgk")
        self.assertTrue(nap.call_args.kwargs["write_md"])
        _, nap = self._chay(kind="sgv")
        self.assertFalse(nap.call_args.kwargs["write_md"])

    def test_suy_tap_tu_loi_kem(self):
        _, nap = self._chay(caption="lớp 2 tiếng việt tập hai")
        self.assertEqual(nap.call_args.kwargs["volume"], "tập hai")

    def test_bao_so_doan_rag(self):
        r, _ = self._chay()
        self.assertIn("5 đoạn", r["text"])


class TestKindTuKho(unittest.TestCase):
    """Suy `kind` từ tên kho — bản cũ chỉ biết 2/5 loại."""

    def test_dung_cho_ca_nam_loai(self):
        from services.agent import teacher_workspace as tw
        for kind in ("sgk", "sgv", "vbt", "tap_huan", "slide"):
            self.assertEqual(tw._kind_tu_kho(sf.KIND_COLLECTION[kind]), kind, kind)

    def test_bo_sach_khac_van_la_sgk(self):
        from services.agent import teacher_workspace as tw
        self.assertEqual(tw._kind_tu_kho("kb_giao_duc_bo2"), "sgk")

    def test_kind_truyen_thang_thang_phep_suy(self):
        """`tap_huan` và `other` chung kho nên suy ngược không phân biệt được —
        caller truyền `kind` thì phải dùng cái đó."""
        from services.agent import teacher_workspace as tw
        with mock.patch.object(tw, "config_hub_url", return_value=""):
            # hub rỗng → thoát sớm, nhưng kind_meta đã tính trước đó; ở đây chỉ
            # cần chắc hàm nhận tham số `kind` mà không lỗi.
            r = tw.push_sgk_to_rag("nội dung", title="t", grade=4,
                                   subject="toan", kind="tap_huan")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main()
