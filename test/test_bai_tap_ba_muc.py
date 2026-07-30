"""Bài tập ba mức: mức phải THẬT khác nhau, và "không có bài mẫu" phải nói ra.

Hai lỗi module này tồn tại để chặn, cả hai đều KHÔNG lộ ra khi đọc đề:

  1. Ba mức mà thực chất một mức. Model hay trả `muc` sai chính tả ("medium",
     "khó", "trung bình") hoặc dồn hết vào một mức. Tin nguyên `muc` của model
     thì bộ đề "ba mức" có thể ra chín câu cùng mức — mỗi câu riêng lẻ đều hợp
     lệ, không có gì để thấy sai.

  2. Đề tự soạn trông y như đề dựa bài mẫu của sách. Kho VBT phần lớn là bài mẫu
     vài trang (135/145 quyển), nhiều lớp–môn chưa có gì. Sinh bừa mà không đánh
     dấu là đưa giáo viên một bộ đề không căn cứ mà họ tưởng là của sách.

Không gọi model thật: cái cần khoá là phép gán mức và phép báo căn cứ, cả hai
nằm ở `_lam_sach` và `_prompt` — thuần tính toán. Gọi model là đổi một phép đo
chắc chắn thành phép đo phụ thuộc mạng và độ ngẫu nhiên của model.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services.agent import teacher_bai_tap as bt


class TestGanMuc(unittest.TestCase):
    def test_ba_muc_dung_han_ngach(self):
        items = [{"muc": m, "de": f"đề {m}{i}"} for m in bt.MUC for i in range(2)]
        ra = bt._lam_sach(items, {m: 2 for m in bt.MUC})
        self.assertEqual(len(ra), 6)
        for m in bt.MUC:
            self.assertEqual(sum(1 for r in ra if r["muc"] == m), 2, m)

    def test_muc_sai_chinh_ta_van_nhan_ra(self):
        """"medium" / "khó" / "trung bình" là cách model hay trả."""
        items = [{"muc": "khó", "de": "a"}, {"muc": "medium", "de": "b"},
                 {"muc": "Sát", "de": "c"}]
        ra = bt._lam_sach(items, {m: 1 for m in bt.MUC})
        self.assertEqual({r["de"]: r["muc"] for r in ra},
                         {"a": "kho", "b": "trung_binh", "c": "sat"})

    def test_don_het_vao_mot_muc_thi_dan_lai_ra_ba_muc(self):
        """Lỗi chính: model trả 3 câu cùng "sat". Không được ra bộ đề một mức."""
        items = [{"muc": "sat", "de": f"đề {i}"} for i in range(3)]
        ra = bt._lam_sach(items, {m: 1 for m in bt.MUC})
        self.assertEqual(sorted(r["muc"] for r in ra), sorted(bt.MUC))

    def test_muc_do_suy_duoc_danh_dau(self):
        """Mức hệ thống gán KHÔNG được lẫn với mức model tự ghi — giáo viên phải
        biết câu nào chưa chắc đúng mức."""
        ra = bt._lam_sach([{"muc": "sat", "de": "a"}, {"de": "b"}],
                          {"sat": 1, "trung_binh": 1, "kho": 0})
        theo_de = {r["de"]: r for r in ra}
        self.assertNotIn("muc_do_suy", theo_de["a"])
        self.assertTrue(theo_de["b"].get("muc_do_suy"))

    def test_khong_vuot_han_ngach_khi_model_tra_thua(self):
        ra = bt._lam_sach([{"muc": "sat", "de": f"đ{i}"} for i in range(9)],
                          {"sat": 1, "trung_binh": 1, "kho": 1})
        self.assertEqual(len(ra), 3)

    def test_cau_rong_bi_bo(self):
        ra = bt._lam_sach([{"muc": "sat", "de": "  "}, {"muc": "sat", "de": "ok"}],
                          {"sat": 2, "trung_binh": 0, "kho": 0})
        self.assertEqual([r["de"] for r in ra], ["ok"])

    def test_sap_theo_thu_tu_de_den_kho(self):
        ra = bt._lam_sach([{"muc": "kho", "de": "k"}, {"muc": "sat", "de": "s"},
                           {"muc": "trung_binh", "de": "t"}],
                          {m: 1 for m in bt.MUC})
        self.assertEqual([r["muc"] for r in ra], list(bt.MUC))

    def test_id_lien_tuc(self):
        ra = bt._lam_sach([{"muc": m, "de": m} for m in bt.MUC],
                          {m: 1 for m in bt.MUC})
        self.assertEqual([r["id"] for r in ra], ["c1", "c2", "c3"])

    def test_nhan_khoa_tieng_anh_cua_model(self):
        """Model có thể trả question/answer/solution thay vì tên tiếng Việt."""
        ra = bt._lam_sach([{"muc": "sat", "question": "q", "answer": "a",
                            "solution": "s"}], {"sat": 1})
        self.assertEqual((ra[0]["de"], ra[0]["dap_an"], ra[0]["loi_giai"]),
                         ("q", "a", "s"))


class TestPromptBaMuc(unittest.TestCase):
    def _ng(self, co_mau: bool) -> dict:
        return {"grade": 4, "subject": "toan", "mon": "Toán", "bai": "Bài 5",
                "mau": "1. Tính: 12 + 5 = ?" if co_mau else "",
                "phan_hoa": "học sinh khá: thêm bước",
                "noi_dung": "cộng trong phạm vi 100",
                "co_mau": co_mau}

    def test_yeu_cau_tung_muc_deu_vao_prompt(self):
        sys_p, _ = bt._prompt(self._ng(True), {m: 2 for m in bt.MUC})
        for m in bt.MUC:
            self.assertIn(bt.MUC_LABEL[m], sys_p)
            self.assertIn(bt.MUC_YEU_CAU[m][:40], sys_p)

    def test_muc_khong_xin_thi_khong_vao_prompt(self):
        sys_p, _ = bt._prompt(self._ng(True), {"sat": 2, "trung_binh": 0, "kho": 0})
        self.assertIn(bt.MUC_LABEL["sat"], sys_p)
        self.assertNotIn(bt.MUC_YEU_CAU["kho"][:40], sys_p)

    def test_bai_mau_that_di_vao_prompt(self):
        _, user_p = bt._prompt(self._ng(True), {m: 1 for m in bt.MUC})
        self.assertIn("12 + 5", user_p)

    def test_khong_co_mau_thi_prompt_noi_thang(self):
        """Không nói ra thì model vẫn sinh đề trông như có căn cứ."""
        sys_p, user_p = bt._prompt(self._ng(False), {m: 1 for m in bt.MUC})
        self.assertIn("KHÔNG có bài mẫu", sys_p)
        self.assertIn("kho chưa có bài mẫu", user_p)

    def test_chan_kien_thuc_lop_tren(self):
        """"Nâng tầm độ khó" bằng kiến thức lớp trên là đề học sinh không làm
        được, mà đọc đề không thấy sai."""
        sys_p, _ = bt._prompt(self._ng(True), {m: 1 for m in bt.MUC})
        self.assertIn("KHÔNG bằng kiến thức", sys_p)
        self.assertIn("lớp 4", sys_p)

    def test_phan_hoa_sgv_vao_prompt_cho_muc_kho(self):
        _, user_p = bt._prompt(self._ng(True), {m: 1 for m in bt.MUC})
        self.assertIn("PHÂN HOÁ", user_p)
        self.assertIn("thêm bước", user_p)

    def test_yeu_cau_co_dap_an(self):
        sys_p, _ = bt._prompt(self._ng(True), {m: 1 for m in bt.MUC})
        self.assertIn("dap_an", sys_p)


class TestBaoCanCu(unittest.TestCase):
    """Giáo viên phải thấy đề có căn cứ hay không TRƯỚC khi giao."""

    def _bo(self, co_mau: bool, thieu: dict | None = None) -> dict:
        return {"id": "x", "grade": 4, "mon": "Toán", "bai": "Bài 5",
                "created": "2026-07-30 10:00",
                "grounded": {"bai_mau": co_mau, "sgk": True, "sgv": True},
                "thieu_cau": thieu or {},
                "items": [{"id": "c1", "muc": "sat", "de": "đề 1",
                           "dap_an": "17", "loi_giai": "12+5"},
                          {"id": "c2", "muc": "kho", "de": "đề 2",
                           "dap_an": "9", "muc_do_suy": True}]}

    def test_canh_bao_khi_khong_co_bai_mau(self):
        t = bt.format_cho_giao_vien(self._bo(False))
        self.assertIn("chưa có bài mẫu", t)

    def test_khong_canh_bao_khi_co_bai_mau(self):
        self.assertNotIn("chưa có bài mẫu", bt.format_cho_giao_vien(self._bo(True)))

    def test_canh_bao_thieu_cau(self):
        t = bt.format_cho_giao_vien(self._bo(True, {"kho": 2}))
        self.assertIn("Chưa đủ số câu", t)
        self.assertIn(bt.MUC_LABEL["kho"], t)

    def test_ban_hoc_sinh_KHONG_co_dap_an(self):
        """Đưa bản có đáp án cho học sinh là làm hỏng cả buổi luyện."""
        t = bt.format_cho_hoc_sinh(self._bo(True))
        self.assertIn("đề 1", t)
        self.assertNotIn("17", t)
        self.assertNotIn("Đáp án", t)

    def test_ban_giao_vien_co_dap_an(self):
        t = bt.format_cho_giao_vien(self._bo(True))
        self.assertIn("Đáp án", t)
        self.assertIn("17", t)

    def test_danh_dau_muc_do_suy_cho_giao_vien(self):
        self.assertIn("hệ thống gán", bt.format_cho_giao_vien(self._bo(True)))


class TestChanThamSoSai(unittest.TestCase):
    def test_lop_ngoai_1_12(self):
        r = bt.tao(grade=13, subject="toan")
        self.assertFalse(r["ok"])
        self.assertIn("1–12", r["error"])

    def test_mon_khong_nhan_ra(self):
        r = bt.tao(grade=4, subject="hoá học lượng tử")
        self.assertFalse(r["ok"])
        self.assertIn("không nhận ra môn", r["error"])




class TestChanKetQuaWebLotVaoBaiMau(unittest.TestCase):
    """`kb_ask` của hub trả `kb_text + live_text` — kho miss thì chỉ còn phần web.

    Đo thật 2026-07-30, `ask_bai_tap("lớp 4 Toán phép cộng bài tập")` trả về danh
    mục bài báo khoa học ("## Tìm kiếm quốc tế", "### CrossRef", DOI...). Coi
    chuỗi không rỗng là "có bài mẫu" thì đề mức «sát bài mẫu» soi theo tiêu đề
    luận văn về LSTM, mà `grounded.bai_mau` vẫn báo True.
    """

    KHO = ("## Kho tri thức (cập nhật: 2026-07-30) (2 kết quả)\n\n"
           "## Kết quả 1 — nguồn: `teacher_sgk/lop4/toan/vbt-toan-4-bai-mau`\n\n"
           "3. Đặt 2 câu với từ ngữ vừa tìm được.\n")
    WEB = ("## Tìm kiếm quốc tế (12 kết quả từ 4 nguồn)\n\n### CrossRef (3)\n"
           "1. **SỬ DỤNG MÔ HÌNH LSTM VÀO BÀI TOÁN TÌM KIẾM CÂU HỎI**\n"
           "   https://doi.org/10.34238/tnu-jst.5799\n")

    def test_chi_co_web_thi_coi_nhu_KHONG_co_bai_mau(self):
        self.assertEqual(bt._chi_phan_kho(self.WEB), "")

    def test_giu_phan_kho(self):
        ra = bt._chi_phan_kho(self.KHO)
        self.assertIn("Đặt 2 câu", ra)

    def test_cat_phan_web_khoi_phan_kho(self):
        """Kho hit + hub tìm thêm web: giữ kho, BỎ web — không nhồi danh mục bài
        báo vào chỗ đáng ra là bài mẫu của sách."""
        ra = bt._chi_phan_kho(self.KHO + "\n" + self.WEB)
        self.assertIn("Đặt 2 câu", ra)
        self.assertNotIn("CrossRef", ra)
        self.assertNotIn("LSTM", ra)

    def test_co_tieu_de_kho_ma_khong_co_nguon_thi_bo(self):
        self.assertEqual(bt._chi_phan_kho("## Kho tri thức (0 kết quả)\n\n"), "")

    def test_kho_chua_san_sang_thi_bo(self):
        self.assertEqual(
            bt._chi_phan_kho("[Kho tri thức kb_giao_duc_vbt chưa sẵn sàng]"), "")

    def test_rong(self):
        self.assertEqual(bt._chi_phan_kho(""), "")
        self.assertEqual(bt._chi_phan_kho(None), "")

    def test_bai_mau_bao_dung_co_mau(self):
        """`co_mau` phải theo phần KHO, không theo độ dài chuỗi trả về."""
        with mock.patch.object(bt, "_kb", side_effect=[self.WEB, self.WEB, self.WEB]):
            self.assertFalse(bt.bai_mau(4, "toan", bai="phép cộng")["co_mau"])
        with mock.patch.object(bt, "_kb", side_effect=[self.KHO, self.WEB, self.KHO]):
            ng = bt.bai_mau(4, "toan", bai="phép cộng")
        self.assertTrue(ng["co_mau"])
        self.assertEqual(ng["phan_hoa"], "")




class TestDoiChieuDanMau(unittest.TestCase):
    """`tu_bai_mau` là lời MODEL tự khai — phải đối chiếu được mới nói là có căn cứ.

    Đo thật 2026-07-30 (lớp 4 Toán, kho chỉ có 4 trang đầu vở bài tập = bìa + lời
    nói đầu + mục lục): model ghi «Dựa bài mẫu: Đặt tính rồi tính: 23 456 + 12 341»
    — câu đó KHÔNG có trong phần kho đã lấy. Đề vẫn đúng chương trình, nhưng dòng
    đó là thứ giáo viên tin để khỏi đọc lại đề.
    """

    MAU = ("## Kho tri thức\n\n## Kết quả 1 — nguồn: `teacher_sgk/lop4/toan/vbt`\n\n"
           "1. Đặt tính rồi tính: 34 567 + 23 421\n2. Tính nhẩm: 200 + 300\n")

    def test_dan_dung_thi_kiem_chung_duoc(self):
        items = [{"tu_bai_mau": "Đặt tính rồi tính: 34 567 + 23 421"}]
        bt._doi_chieu_dan_mau(items, self.MAU)
        self.assertTrue(items[0]["dan_mau_kiem_chung"])

    def test_doi_so_lieu_van_kiem_chung_duoc(self):
        """Model đổi số là chuyện BÌNH THƯỜNG — so nguyên văn thì cảnh báo vô nghĩa."""
        items = [{"tu_bai_mau": "Đặt tính rồi tính: 11 111 + 22 222"}]
        bt._doi_chieu_dan_mau(items, self.MAU)
        self.assertTrue(items[0]["dan_mau_kiem_chung"])

    def test_dan_khong_co_trong_kho_thi_bao_khong(self):
        items = [{"tu_bai_mau": "Vẽ hình thang cân rồi đo góc ở đáy"}]
        bt._doi_chieu_dan_mau(items, self.MAU)
        self.assertFalse(items[0]["dan_mau_kiem_chung"])

    def test_khong_dan_gi_thi_bao_khong(self):
        items = [{"tu_bai_mau": ""}]
        bt._doi_chieu_dan_mau(items, self.MAU)
        self.assertFalse(items[0]["dan_mau_kiem_chung"])

    def test_kho_rong_thi_moi_dan_deu_khong_kiem_chung(self):
        items = [{"tu_bai_mau": "Đặt tính rồi tính: 34 567 + 23 421"}]
        bt._doi_chieu_dan_mau(items, "")
        self.assertFalse(items[0]["dan_mau_kiem_chung"])

    def test_giao_vien_thay_canh_bao(self):
        bo = {"id": "x", "grade": 4, "mon": "Toán", "bai": "b",
              "created": "2026-07-30", "grounded": {"bai_mau": True},
              "thieu_cau": {},
              "items": [{"muc": "sat", "de": "d1", "dap_an": "1",
                         "tu_bai_mau": "câu model tự nêu",
                         "dan_mau_kiem_chung": False},
                        {"muc": "kho", "de": "d2", "dap_an": "2",
                         "tu_bai_mau": "câu có thật",
                         "dan_mau_kiem_chung": True}]}
        t = bt.format_cho_giao_vien(bo)
        self.assertIn("không đối chiếu được", t)
        # Câu đối chiếu được thì KHÔNG bị dán cảnh báo — nếu dán hết thì cảnh báo
        # mất nghĩa và người đọc bỏ qua.
        self.assertEqual(t.count("không đối chiếu được"), 1)




class TestCuuJsonBiCat(unittest.TestCase):
    """JSON cụt vì hết max_tokens — vẫn phải dùng được các câu đã hoàn chỉnh.

    Đo thật 2026-07-30: model trả 2014 ký tự JSON ĐÚNG CHUẨN nhưng cụt ở câu thứ
    ba ("...tuần thứ ba may đượ"). `_parse_json_obj` lấy từ `{` đầu đến `}` cuối
    nên thiếu dấu đóng của object ngoài là trượt sạch → module báo "model không
    trả đúng dạng — thử lại", trong khi hai câu đầu đã dùng được. Bỏ cả lượt là
    tốn thêm một lượt gọi model để nhận lại đúng thứ vừa có.
    """

    DAY_DU = ('{"items":[{"muc":"sat","de":"d1","dap_an":"1"},'
              '{"muc":"kho","de":"d2","dap_an":"2"}]}')
    BI_CAT = ('```json\n{"items":[\n{"muc":"sat","de":"d1","dap_an":"1"},\n'
              '{"muc":"trung_binh","de":"d2","dap_an":"2"},\n'
              '{"muc":"kho","de":"Một xí nghiệp may đượ')

    def test_json_day_du_van_doc_binh_thuong(self):
        ra = bt._doc_items(self.DAY_DU)
        self.assertEqual([r["de"] for r in ra], ["d1", "d2"])

    def test_json_bi_cat_van_cuu_duoc_cau_hoan_chinh(self):
        ra = bt._doc_items(self.BI_CAT)
        self.assertEqual([r["de"] for r in ra], ["d1", "d2"])

    def test_khong_dung_object_cut(self):
        """Câu cụt KHÔNG được nhận — đề thiếu chữ là đề sai."""
        for r in bt._doc_items(self.BI_CAT):
            self.assertNotIn("xí nghiệp", r["de"])

    def test_ngoac_trong_de_bai_khong_lam_lech(self):
        """Đề bài có thể chứa dấu ngoặc — quét ngoặc phải bỏ qua ngoặc trong chuỗi."""
        raw = '{"items":[{"muc":"sat","de":"Tính (3 + 4) × 2 = ?","dap_an":"14"}'
        ra = bt._doc_items(raw)
        self.assertEqual(len(ra), 1)
        self.assertIn("(3 + 4)", ra[0]["de"])

    def test_object_khong_co_de_thi_bo(self):
        """Object bao ngoài / object rác không được tính thành câu."""
        self.assertEqual(bt._doc_items('{"meta":{"a":1}}'), [])

    def test_rong(self):
        self.assertEqual(bt._doc_items(""), [])
        self.assertEqual(bt._doc_items("không phải json"), [])


class TestBoTrangBia(unittest.TestCase):
    """Mục lục trúng truy vấn rất cao mà không có bài nào để soi.

    Đo thật 2026-07-30: hỏi bài mẫu Toán 4 «phép cộng», kết quả số 1 là trang MỤC
    LỤC — nó chứa đúng cụm "Ôn tập các phép tính trong phạm vi 100 000". Model
    nhận một danh sách tên bài rồi phải tự nghĩ ra câu mẫu.
    """

    BIA = ("## Kết quả 1 — nguồn: `teacher_sgk/lop4/toan/vbt`\n\n"
           "## MỤC LỤC\n\nBài 1. Ôn tập các số đến 100 000 ... 5\n")
    BAI = ("## Kết quả 2 — nguồn: `teacher_sgk/lop4/toan/vbt`\n\n"
           "1. Đặt tính rồi tính: 34 567 + 23 421\n")

    def test_bo_doan_muc_luc(self):
        ra = bt._bo_trang_bia(self.BIA + self.BAI)
        self.assertNotIn("MỤC LỤC", ra)
        self.assertIn("Đặt tính rồi tính", ra)

    def test_bo_loi_noi_dau(self):
        loi = ("## Kết quả 1 — nguồn: `x`\n\n## LỜI NÓI ĐẦU\n\nCác em thân mến\n")
        ra = bt._bo_trang_bia(loi + self.BAI)
        self.assertNotIn("LỜI NÓI ĐẦU", ra)

    def test_chi_co_bia_thi_TRA_RONG(self):
        """Chỉ còn bìa/mục lục ⇒ trả rỗng ⇒ `co_mau=False`.

        Bản đầu tôi viết ngược lại ("thà đưa mục lục còn hơn nói kho rỗng"), và
        đo thật cho thấy nó sai: đưa mục lục + dòng kẻ trống vào prompt thì model
        trả về `{}` — hỏng cả lượt. Nói thẳng "kho chưa có bài mẫu dùng được" thì
        prompt chuyển sang ra đề theo chuẩn chương trình và đề vẫn dùng được, lại
        còn báo đúng mức căn cứ cho giáo viên.
        """
        self.assertEqual(bt._bo_trang_bia(self.BIA), "")

    def test_dong_ke_trong_bi_bo(self):
        """Vở bài tập là phiếu điền: phần lớn diện tích là dòng kẻ, OCR ra dấu
        chấm. Đo thật: một "bài mẫu" chỉ gồm "## Bài giải" + ba dòng dấu chấm."""
        ke = ("## Kết quả 3 — nguồn: `teacher_sgk/lop4/toan/vbt`\n\n## Bài giải\n"
              + "." * 300 + "\n")
        self.assertEqual(bt._bo_trang_bia(ke), "")
        # Nhưng bài tập NGẮN thật thì phải giữ.
        self.assertIn("Tính nhẩm", bt._bo_trang_bia(
            "## Kết quả 1 — nguồn: `x/vbt`\n\n2. Tính nhẩm: 200 + 300 = ?\n"))

    def test_khong_co_bia_thi_giu_nguyen(self):
        self.assertEqual(bt._bo_trang_bia(self.BAI).strip(), self.BAI.strip())

    def test_rong(self):
        self.assertEqual(bt._bo_trang_bia(""), "")




class TestLuiVeChuan(unittest.TestCase):
    """Kho CÓ bài mẫu nhưng khớp kém → lùi về chuẩn chương trình, và BÁO ĐÚNG.

    Đo thật 2026-07-30: hỏi «phép cộng» Toán 4; sau khi lọc bìa/mục lục/dòng kẻ
    trống, đoạn duy nhất còn lại là một mẩu cụt về SO SÁNH SỐ ("Số bé nhất là").
    Model trả `{}`. Trả lỗi cho giáo viên là bỏ cả lượt vì kho thiếu dữ liệu; thử
    lại theo chuẩn chương trình thì họ có bộ đề dùng được.

    Nhưng khi đó `grounded.bai_mau` PHẢI là False: đề này không dựa bài mẫu. Báo
    True chỉ vì kho có gì đó là đúng cái nhầm lẫn cả module dựng lên để tránh.
    """

    NG = {"grade": 4, "subject": "toan", "mon": "Toán", "bai": "phép cộng",
          "mau": "## Kho tri thức\n\n## Kết quả 1 — nguồn: `x`\n\nSố bé nhất là",
          "phan_hoa": "", "noi_dung": "", "co_mau": True}

    def _chay(self, lan1, lan2):
        """lan1/lan2 = nội dung model trả ở lượt 1 và lượt 2."""
        goi = {"n": 0}

        def _cm(*a, **k):
            goi["n"] += 1
            return {"choices": [{"message": {"content":
                    lan1 if goi["n"] == 1 else lan2}}]}

        with mock.patch.object(bt, "bai_mau", return_value=dict(self.NG)), \
             mock.patch("services.agent.runtime.call_model", side_effect=_cm), \
             mock.patch.object(bt, "_luu"):
            r = bt.tao(grade=4, subject="toan", bai="phép cộng", so_moi_muc=1)
        return r, goi["n"]

    CAU = ('{"items":[{"muc":"sat","de":"d1","dap_an":"1"},'
           '{"muc":"trung_binh","de":"d2","dap_an":"2"},'
           '{"muc":"kho","de":"d3","dap_an":"3"}]}')

    def test_lan_dau_ra_duoc_thi_KHONG_goi_lai(self):
        r, n = self._chay(self.CAU, "{}")
        self.assertTrue(r["ok"])
        self.assertEqual(n, 1)
        self.assertFalse(r["bo_de"]["lui_ve_chuan"])
        self.assertTrue(r["bo_de"]["grounded"]["bai_mau"])

    def test_model_tra_rong_thi_thu_lai_mot_lan(self):
        r, n = self._chay("{}", self.CAU)
        self.assertTrue(r["ok"])
        self.assertEqual(n, 2)
        self.assertEqual(len(r["bo_de"]["items"]), 3)

    def test_lui_ve_chuan_thi_bao_KHONG_dua_bai_mau(self):
        r, _ = self._chay("{}", self.CAU)
        self.assertTrue(r["bo_de"]["lui_ve_chuan"])
        self.assertFalse(r["bo_de"]["grounded"]["bai_mau"])

    def test_giao_vien_thay_ly_do_lui(self):
        r, _ = self._chay("{}", self.CAU)
        t = bt.format_cho_giao_vien(r["bo_de"])
        self.assertIn("khớp kém", t)

    def test_khong_co_mau_thi_bao_ly_do_khac(self):
        ng = {**self.NG, "co_mau": False, "mau": ""}
        with mock.patch.object(bt, "bai_mau", return_value=ng), \
             mock.patch("services.agent.runtime.call_model",
                        return_value={"choices": [{"message": {"content": self.CAU}}]}), \
             mock.patch.object(bt, "_luu"):
            r = bt.tao(grade=4, subject="toan", bai="x", so_moi_muc=1)
        t = bt.format_cho_giao_vien(r["bo_de"])
        self.assertIn("chưa có bài mẫu", t)
        self.assertNotIn("khớp kém", t)

    def test_ca_hai_luot_deu_rong_thi_bao_loi(self):
        r, n = self._chay("{}", "{}")
        self.assertFalse(r["ok"])
        self.assertEqual(n, 2)

    def test_lui_ve_chuan_thi_khong_doi_chieu_dan_mau(self):
        """Đề không dựa bài mẫu thì mọi trích dẫn đều là model tự nêu."""
        r, _ = self._chay("{}", self.CAU)
        for it in r["bo_de"]["items"]:
            self.assertFalse(it.get("dan_mau_kiem_chung"))


if __name__ == "__main__":
    unittest.main()
