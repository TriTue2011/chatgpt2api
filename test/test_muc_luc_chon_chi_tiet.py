"""Danh sách dài phải có MÃ MỤC để chọn xem chi tiết.

Yêu cầu chủ máy 24/08, sau hai bản tin thật trên Zalo (bản tin 8 mục × 3 tin, và
danh sách 5 tin theo chủ đề): "với những thông tin dài và nhiều lựa chọn nên tạo
đánh số kiểu A, I, 1, a để lựa chọn cần xem chi tiết. Không chỉ ở tin tức mà cả
ở phần khác".

Hai thứ dễ hỏng nhất, đều được khoá ở đây:

  * ĐÁNH NHẦM CHỖ — dòng tóm tắt (thụt lề) của bản tin theo chủ đề nằm ngay
    trước tin kế tiếp, rất dễ bị nhận là đầu mục rồi lĩnh mã "B.";
  * NUỐT CÂU THƯỜNG — bản chờ sống 30 phút, nên `resolve_reply` chỉ được nhận
    đúng một mã trần, không nhận câu có chữ.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import muc_luc as ml  # noqa: E402

# Bản tin thật gửi cho chủ máy 24/08 08:53 (rút còn 3 mục cho gọn).
BAN_TIN = """**⚽ Thể thao**
- Tiền đạo Thái Lan: 'Nỗ lực hết sức để lấy cup khỏi Việt Nam'
- Lịch thi đấu bóng chuyền nữ Việt Nam đấu Hồng Kông
- Barcelona giành chiến thắng 5-0 ở trận mở màn La Liga

**💼 Kinh tế**
- Chứng khoán tuần này có thể tăng lên vùng 1.800 điểm
- Người trẻ Mỹ từ bỏ giấc mơ mua nhà
- Đấu giá tiếp gần 39.000 xe máy vi phạm ở TPHCM

**🏙️ Xã hội**
- Bão Narra gần như đứng yên trong vịnh Bắc Bộ
- Luật Phát triển đô thị 'bệ phóng thể chế'
- Xe cứu hộ va chạm ô tô tải trên cao tốc, 2 người tử vong"""

# Bản tin theo chủ đề, 24/08 09:57 — mỗi tin kèm MỘT dòng tóm tắt thụt lề.
THEO_CHU_DE = """1. **Hà Nội: Hàng loạt trường hoãn tựu trường** · Dan Tri
   (Dân trí) - Đêm qua và sáng nay, hàng loạt trường học lùi giờ tập trung.

2. **Suýt chết vì những 'viên thuốc quen thuộc'** · Google News
   Thanh niên 28 tuổi phù não nguy kịch vì tự mua thuốc Nam trên mạng.

3. **Truy tìm nghi phạm đâm chết em trai rồi bỏ trốn** · Tuoi Tre
   Đâm chết em trai trong đêm, nghi phạm ở xã biên giới Nghệ An bỏ trốn.

4. **Israel - Thổ Nhĩ Kỳ: cuộc chiến gay cấn ở Trung Đông** · Google News
   Xem thêm tiêu đề và góc nhìn khác trên Google Tin tức.

5. **Thường trực Ban Bí thư lên đường thăm Singapore** · Google News
   Xem thêm tiêu đề và góc nhìn khác trên Google Tin tức."""


class DanhMaTests(unittest.TestCase):
    def test_ban_tin_chia_muc_ra_ma_hai_bac(self):
        ra, muc = ml.danh_so(BAN_TIN)
        self.assertEqual([m["ma"] for m in muc],
                         ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"])
        self.assertIn("A1. Tiền đạo Thái Lan", ra)
        self.assertIn("C3. Xe cứu hộ va chạm", ra)

    def test_dau_muc_van_dam_nguyen_ven(self):
        """Mã phải nằm TRONG cặp `**`. Để ra ngoài thì `zalo_markdown` dựng vùng
        đậm lệch một nửa đầu mục — đúng kiểu lỗi 'còn nguyên dấu sao' cũ."""
        ra, _ = ml.danh_so(BAN_TIN)
        self.assertIn("**A. ⚽ Thể thao**", ra)
        self.assertIn("**B. 💼 Kinh tế**", ra)
        self.assertNotIn("A. **⚽", ra)

    def test_co_cau_huong_dan_cach_chon(self):
        ra, _ = ml.danh_so(BAN_TIN)
        self.assertIn("A1", ra.rsplit("\n", 1)[-1], "câu cuối phải nêu ví dụ mã")

    def test_danh_sach_phang_dung_so_tran(self):
        ra, muc = ml.danh_so(THEO_CHU_DE)
        self.assertEqual([m["ma"] for m in muc], ["1", "2", "3", "4", "5"])
        self.assertIn("Hà Nội", muc[0]["noi_dung"])

    def test_dong_tom_tat_khong_thanh_dau_muc(self):
        """Dòng tóm tắt thụt lề đứng ngay trước tin sau — không được lĩnh mã."""
        ra, _ = ml.danh_so(THEO_CHU_DE)
        self.assertNotIn("A. ", ra)
        self.assertIn("   (Dân trí) - Đêm qua", ra, "dòng tóm tắt phải nguyên vẹn")

    def test_muc_con_xuong_bac_chu_thuong(self):
        van = ("**Việc nhà**\n"
               "- Quét nhà\n"
               "  - Tầng một\n"
               "  - Tầng hai\n"
               "- Rửa bát\n"
               "\n"
               "**Việc công ty**\n"
               "- Họp sáng\n"
               "- Gửi báo cáo")
        _, muc = ml.danh_so(van)
        self.assertEqual([m["ma"] for m in muc],
                         ["A1", "A1a", "A1b", "A2", "B1", "B2"])

    def test_dau_muc_cach_mot_dong_trong_van_nhan_ra(self):
        """Model hay xuống dòng trống giữa tiêu đề và danh sách. Không nhận ra
        thì cả bản tin rơi về đánh số phẳng 1..N, mất chữ cái mục."""
        van = ("## Thể thao\n\n- Tin một\n- Tin hai\n\n"
               "## Kinh tế\n\n- Tin ba\n- Tin bốn")
        ra, muc = ml.danh_so(van)
        self.assertEqual([m["ma"] for m in muc], ["A1", "A2", "B1", "B2"])
        self.assertIn("## A. Thể thao", ra)

    def test_danh_sach_ngan_de_yen(self):
        """Ba gạch đầu dòng trong một câu trả lời thường là câu văn, không phải
        bảng chọn — đánh mã vào đó chỉ làm rối."""
        van = "Em làm ba việc:\n- gọi điện\n- gửi mail\n- đặt lịch"
        ra, muc = ml.danh_so(van)
        self.assertEqual(muc, [])
        self.assertEqual(ra, van)

    def test_khoi_ma_de_yen(self):
        van = ("Chạy thử:\n```bash\n- a\n- b\n- c\n- d\n- e\n- f\n```\n")
        ra, muc = ml.danh_so(van)
        self.assertEqual(muc, [])
        self.assertEqual(ra, van)

    def test_bang_markdown_de_yen(self):
        van = ("| Tên | Giá |\n|---|---|\n"
               "- một\n- hai\n- ba\n- bốn\n- năm")
        _, muc = ml.danh_so(van)
        self.assertEqual(muc, [])


class MaKhongTrungTests(unittest.TestCase):
    def test_qua_26_dau_muc_van_moi_muc_mot_ma(self):
        """Lấy dư 26 quay vòng thì mục 27 lại mang mã «A» — gõ A1 ra tin của
        mục khác mà không ai hiểu vì sao."""
        ma = [ml._ma_bac(0, i) for i in range(ml._TOI_DA)]
        self.assertEqual(len(set(ma)), ml._TOI_DA)
        self.assertEqual(ma[26], "AA")

    def test_ma_hai_chu_van_go_chon_duoc(self):
        with patch.object(ml, "_db", lambda: None):
            ml._reset_for_tests()
            ml.set_pending("u5", [{"ma": "AA2", "noi_dung": "tin xa tít"}])
            self.assertEqual((ml.resolve_reply("u5", "aa2") or {}).get("noi_dung"),
                             "tin xa tít")


class ChonMucTests(unittest.TestCase):
    def setUp(self):
        ml._reset_for_tests()
        # Test chỉ dùng bộ nhớ: không đẻ file SQLite trong data/ của máy dev.
        self._db = patch.object(ml, "_db", lambda: None)
        self._db.start()
        self.addCleanup(self._db.stop)
        _, muc = ml.danh_so(BAN_TIN)
        ml.set_pending("u1", muc)

    def test_go_ma_ra_dung_muc(self):
        chon = ml.resolve_reply("u1", "B2")
        self.assertIsNotNone(chon)
        self.assertEqual(chon["ma"], "B2")
        self.assertEqual(chon["noi_dung"], "Người trẻ Mỹ từ bỏ giấc mơ mua nhà")
        self.assertIn("Người trẻ Mỹ từ bỏ giấc mơ mua nhà", chon["cau_hoi"])

    def test_khong_phan_biet_hoa_thuong_va_dau_cham(self):
        for go in ("b2", "B2.", " b2 ", "B2)"):
            ml._reset_for_tests()
            _, muc = ml.danh_so(BAN_TIN)
            ml.set_pending("u1", muc)
            self.assertIsNotNone(ml.resolve_reply("u1", go), f"gõ {go!r} phải nhận")

    def test_chon_xong_thi_het_hieu_luc(self):
        self.assertIsNotNone(ml.resolve_reply("u1", "A1"))
        self.assertIsNone(ml.resolve_reply("u1", "A1"),
                          "chọn rồi mà số cũ còn hiệu lực thì câu sau bị nuốt")

    def test_ma_khong_co_thi_bo_qua(self):
        self.assertIsNone(ml.resolve_reply("u1", "Z9"))

    def test_cau_thuong_khong_bi_nuot(self):
        for cau in ("bão số 3 thế nào", "cảm ơn em", "2 giờ chiều nhắc anh",
                    "A1 là tin gì vậy em"):
            self.assertIsNone(ml.resolve_reply("u1", cau), f"nuốt mất: {cau!r}")

    def test_nguoi_khac_khong_thay_ban_cho(self):
        self.assertIsNone(ml.resolve_reply("u2", "A1"))

    def test_cau_hoi_chi_tiet_khong_roi_vao_duong_tat_ban_tin(self):
        """Câu bơm vào phải ĐỦ DÀI để `_la_yeu_cau_tin_tuc` bỏ qua — nếu không,
        chọn một tin lại nhận về nguyên bản tin tổng hợp lần nữa."""
        from services.agent.orchestrator import _la_yeu_cau_tin_tuc
        chon = ml.resolve_reply("u1", "C1")
        self.assertIsNone(_la_yeu_cau_tin_tuc(chon["cau_hoi"]))


class GanVaoKetQuaTests(unittest.TestCase):
    def setUp(self):
        ml._reset_for_tests()
        self._db = patch.object(ml, "_db", lambda: None)
        self._db.start()
        self.addCleanup(self._db.stop)

    def test_gan_ma_va_bat_co_muc_luc(self):
        kq = ml.apply_to_result({"text": BAN_TIN}, "u9")
        self.assertTrue(kq.get("muc_luc"))
        self.assertIn("A1. ", kq["text"])
        self.assertIsNotNone(ml.resolve_reply("u9", "A1"))

    def test_menu_chon_thi_khong_dong_them_ma(self):
        """Tin đã có `choices` là menu của ask_choices — hai hệ mã trong một tin
        thì người dùng gõ số nào cũng sai."""
        kq = ml.apply_to_result(
            {"text": BAN_TIN, "choices": [{"label": "x", "send": "x"}]}, "u9")
        self.assertNotIn("A1. ", kq["text"])
        self.assertFalse(kq.get("muc_luc"))

    def test_cau_tra_loi_thuong_khong_bi_dong_dau(self):
        kq = ml.apply_to_result({"text": "Dạ vâng ạ, em làm ngay."}, "u9")
        self.assertEqual(kq["text"], "Dạ vâng ạ, em làm ngay.")
        self.assertFalse(kq.get("muc_luc"))

    def test_orchestrator_co_goi_qua_duong_nay(self):
        """Khoá ĐIỂM ĐẤU NỐI: mọi câu trả lời của agent đi qua `_finalize`. Gỡ
        lời gọi ở đó thì mã mục biến mất mà không test nào khác kêu."""
        from services.agent.orchestrator import _finalize
        kq = _finalize("u_finalize", {"text": BAN_TIN})
        self.assertIn("A1. ", kq.get("text") or "")
        self.assertTrue(kq.get("muc_luc"))
        self.assertIsNotNone(ml.resolve_reply("u_finalize", "A1"))


class NguonBanTinTests(unittest.TestCase):
    """Mục của BẢN TIN phải được đánh dấu `nguon="tin"`.

    Đó là thứ duy nhất phân biệt "tra tin theo tiêu đề" với "hỏi trợ lý". Mất
    dấu này thì tiêu đề tin lại chui vào vòng trợ lý, và mọi tầng tra cứu phía
    sau nhận nguyên câu lời dặn làm truy vấn — đúng lỗi ngày 24/08 (bot kể sách
    giáo khoa Tiếng Việt lớp 2 cho tin "Thần đồng 7 tuổi đi học ở đại học").
    """

    def setUp(self):
        ml._reset_for_tests()
        self._db = patch.object(ml, "_db", lambda: None)
        self._db.start()
        self.addCleanup(self._db.stop)

    def test_ban_tin_giu_nguon_tin(self):
        kq = ml.apply_to_result({"text": BAN_TIN, "muc_luc_nguon": "tin"}, "u1")
        self.assertNotIn("muc_luc_nguon", kq,
                         "cờ nội bộ không được lọt xuống kênh chat")
        chon = ml.resolve_reply("u1", "B2")
        self.assertEqual(chon["nguon"], "tin")
        self.assertEqual(chon["noi_dung"], "Người trẻ Mỹ từ bỏ giấc mơ mua nhà")

    def test_danh_sach_thuong_khong_mang_nguon_tin(self):
        """Danh sách việc cần làm vẫn đi đường hỏi trợ lý như cũ."""
        ml.apply_to_result({"text": BAN_TIN}, "u2")
        self.assertEqual(ml.resolve_reply("u2", "B2")["nguon"], "")

    def test_ban_ghi_cu_khong_co_nguon_van_doc_duoc(self):
        """Bản chờ ghi trước lần nâng cấp này là list trần trong SQLite. Đọc
        không ra thì người đang đọc dở bản tin gõ mã xong nhận 'chưa rõ ý'."""
        import json
        ban = [{"ma": "A1", "noi_dung": "tin cũ"}]

        class _GiaDB:
            def execute(self, sql, args=()):
                self.sql = sql
                return self

            def fetchone(self):
                return (json.dumps(ban, ensure_ascii=False), time.time())

            def commit(self):
                pass

        with patch.object(ml, "_db", lambda: _GiaDB()):
            ml._reset_for_tests()
            chon = ml.resolve_reply("u3", "A1")
        self.assertEqual(chon["noi_dung"], "tin cũ")
        self.assertEqual(chon["nguon"], "")


class CauBomKhongEpTraCuuTests(unittest.TestCase):
    """Chọn một mục KHÔNG được ép bot đi tra web.

    Đo thật trên Zalo 29/08: người dùng tra "stroke", bot liệt kê 12 nghĩa rồi
    mời nhắn mã mục. Bấm «1» (nghĩa y khoa: đột quỵ) thì câu bơm vào vòng trợ
    lý ra lệnh "Tra cứu thêm rồi kể đầy đủ", nên bot chạy searxng tìm "đột quỵ"
    rồi mới trả lời — trong khi nghĩa đó là định nghĩa từ điển CHÍNH NÓ vừa
    đưa ra, đang nằm sẵn trong ngữ cảnh. Người dùng báo "phản hồi hơi lâu".

    Vẫn KHÔNG cấm tra cứu: có mục thật sự cần dữ liệu mới (một tin trong bản
    tin, một chủ đề mới nêu tên), chặn hẳn thì hỏng chiều ngược lại.
    """

    def setUp(self):
        ml._reset_for_tests()
        self._db = patch.object(ml, "_db", lambda: None)
        self._db.start()
        self.addCleanup(self._db.stop)

    def test_khong_con_menh_lenh_tra_cuu(self):
        cau = ml._cau_hoi("Trong y khoa: đột quỵ")
        self.assertNotIn("Tra cứu thêm rồi kể đầy đủ", cau)

    def test_bao_uu_tien_dung_ngu_canh_san_co(self):
        cau = ml._cau_hoi("Trong y khoa: đột quỵ")
        self.assertIn("có sẵn trong ngữ cảnh", cau)
        self.assertIn("trả lời thẳng", cau)

    def test_van_cho_phep_tra_khi_that_su_can(self):
        self.assertIn("tra cứu", ml._cau_hoi("Giá vàng hôm nay"))

    def test_van_mang_nguyen_noi_dung_muc(self):
        self.assertIn("Trong y khoa: đột quỵ", ml._cau_hoi("Trong y khoa: đột quỵ"))

    def test_resolve_reply_dung_cau_moi(self):
        ml.apply_to_result({"text": BAN_TIN}, "u_bom")
        chon = ml.resolve_reply("u_bom", "B2")
        self.assertNotIn("Tra cứu thêm rồi kể đầy đủ", chon["cau_hoi"])
        self.assertIn(chon["noi_dung"], chon["cau_hoi"])


class DauNoiTinTucTests(unittest.TestCase):
    """Khoá ĐIỂM ĐẤU NỐI phía tin tức: đường tắt bản tin phải gắn cờ nguồn, và
    orchestrator phải có nhánh tra thẳng tiêu đề (mục 1.3)."""

    def test_duong_tat_ban_tin_gan_co_nguon(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "services" / "agent" / "orchestrator.py").read_text("utf-8")
        self.assertIn('_kq_ws["muc_luc_nguon"] = "tin"', src,
                      "bản tin không gắn nguồn thì mã mục mất đường tra tin")
        self.assertIn("_tin_da_chon", src,
                      "thiếu nhánh tra thẳng tiêu đề tin vừa chọn")

    def test_tra_thang_bang_tieu_de_tran(self):
        """Query phải là TIÊU ĐỀ TRẦN. Thêm chữ 'tin tức' vào là gateway tắt
        phần tiêm kết quả tìm kiếm (dedicated_mcp) rồi trông chờ MCP tin tức —
        mà MCP đó chỉ có bản tin tổng hợp, không có bài chi tiết."""
        from services.mcp_client import query_has_specialized_mcp as _qhs
        ml._reset_for_tests()
        with patch.object(ml, "_db", lambda: None):
            ml.apply_to_result({"text": BAN_TIN, "muc_luc_nguon": "tin"}, "u4")
            chon = ml.resolve_reply("u4", "A1")
        self.assertFalse(_qhs(chon["noi_dung"]),
                         "tiêu đề trần không được kích hoạt MCP chuyên dụng")


class ChonTinChayThatTests(unittest.TestCase):
    """Chạy THẬT qua `orchestrate`: gõ mã tin → tra web bằng ĐÚNG tiêu đề.

    Test nguồn (đọc chuỗi trong file) chỉ chứng minh dòng code còn đó. Cái hỏng
    hôm 24/08 nằm ở ĐƯỜNG ĐI: câu bơm ra bị mọi tầng tra cứu phía sau lấy nguyên
    văn làm truy vấn. Nên chỗ cần khoá là truy vấn thật sự gửi đi.
    """

    def setUp(self):
        from test._fakes import FakeCallModel, install_call_model, install_data_dir
        import services.agent.orchestrator as orch
        self.orch = orch
        self._uid = "zalop_test_ma_muc"
        ml._reset_for_tests()
        self._data = install_data_dir()
        self._data.__enter__()
        self.addCleanup(lambda: self._data.__exit__(None, None, None))
        self._db = patch.object(ml, "_db", lambda: None)
        self._db.start()
        self.addCleanup(self._db.stop)
        # Model giả: câu THƯỜNG vẫn đi qua nó, còn tin đã chọn thì KHÔNG được.
        self._llm = install_call_model(FakeCallModel(text="dạ em nghe ạ"))
        self.model = self._llm.__enter__()
        self.addCleanup(lambda: self._llm.__exit__(None, None, None))

        self.da_tra: list[str] = []
        _that = orch.caps.get

        def _tra_gia(args, ctx):
            self.da_tra.append(str(args.get("query") or ""))
            return {"text": "Chi tiết vụ này: … (bản tin đầy đủ)"}

        class _CapGia:
            handler = staticmethod(_tra_gia)

        def _gia(ten):
            return _CapGia if ten == "web_search" else _that(ten)

        self._caps = patch.object(orch.caps, "get", _gia)
        self._caps.start()
        self.addCleanup(self._caps.stop)

    def test_go_ma_tin_thi_tra_dung_tieu_de_tran(self):
        self.orch._finalize(self._uid, {"text": BAN_TIN, "muc_luc_nguon": "tin"})
        out = self.orch.orchestrate("B2", self._uid)
        self.assertEqual(self.da_tra, ["Người trẻ Mỹ từ bỏ giấc mơ mua nhà"],
                         "truy vấn phải là TIÊU ĐỀ TRẦN, không bọc lời dặn")
        self.assertIn("Chi tiết vụ này", out.get("text") or "")
        self.assertEqual(self.model.calls, [],
                         "tin đã chọn thì tra thẳng, không vòng qua model")

    def test_ma_khong_co_ban_cho_thi_noi_ly_do_that(self):
        """Không có bản chờ mà gõ mã trần "B2" → CODE nói thẳng lý do THẬT
        ("bảng đã trống"), KHÔNG tra web, KHÔNG vòng qua model (yêu cầu chủ máy
        04/09: code nói lý do thật thay vì để model đọc thuộc)."""
        out = self.orch.orchestrate("B2", self._uid)
        self.assertEqual(self.da_tra, [], "không được tự đi tra web")
        self.assertEqual(self.model.calls, [], "code trả thẳng, không qua model")
        txt = out.get("text") or ""
        self.assertIn("B2", txt)
        self.assertIn("chưa có danh sách", txt)


class HuongDanChoTroLyTests(unittest.TestCase):
    """Lời dặn cho model phải KHỚP thứ code thật sự làm.

    Hai chỗ lệch đã đo được ngày 24/08:
      * model không hề được kể MÃ MỤC là gì (mã do code gắn) — nên khi người
        dùng nhắc "có lựa chọn E1 mà" thì nó đáp "Dạ đúng rồi anh ạ… anh chọn
        lại E1 giúp em nhé", tức là gật đầu với một thứ nó không thấy;
      * bảng chỉ đường kể tên 8 mục bản tin KHÁC hẳn 8 mục code gửi đi, nên khi
        phải nói về chính bản tin vừa gửi thì nó đối chiếu với bố cục không có
        thật.
    """

    def setUp(self):
        from test._fakes import install_data_dir
        import services.agent.orchestrator as orch
        self.orch = orch
        self._data = install_data_dir()
        self._data.__enter__()
        self.addCleanup(lambda: self._data.__exit__(None, None, None))
        # Prompt giờ nạp theo VIỆC: khối mã mục + 8 mục bản tin chỉ hiện khi lượt
        # này là yêu cầu tin tức — nên dựng prompt với đúng một câu hỏi tin.
        self.prompt = orch._build_system_prompt("u_huong_dan", None, "tin tức hôm nay")

    def test_co_day_du_luat_ve_ma_muc(self):
        self.assertIn("MÃ MỤC", self.prompt)
        for y in ("hết hiệu lực", "KHÔNG tự đánh mã",
                  "không đoán mục đó nói về gì"):
            self.assertIn(y, self.prompt, f"thiếu ý «{y}» trong lời dặn mã mục")

    def test_ten_8_muc_ban_tin_dung_nhu_code_gui(self):
        for ten in ("⚽ Thể thao", "💼 Kinh tế", "🏙️ Xã hội",
                    "💻 Công nghệ thông tin", "🎓 Giáo dục", "🩺 Y tế",
                    "🎬 Giải trí", "🌍 Thế giới"):
            self.assertIn(ten, self.prompt, f"bảng chỉ đường thiếu mục {ten}")
        for sai in ("Thời sự Việt Nam", "Pháp luật & Xã hội",
                    "Sức khỏe & Đời sống", "Công nghệ & Khoa học"):
            self.assertNotIn(sai, self.prompt,
                             f"còn kể mục «{sai}» — bản tin thật không có mục này")


if __name__ == "__main__":
    unittest.main()
