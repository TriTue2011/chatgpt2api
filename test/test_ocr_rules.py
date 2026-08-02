"""Quy tắc OCR dùng chung: một nguồn duy nhất cho MỌI đường đọc tài liệu.

Vì sao có file này: dự án từng có HAI prompt OCR viết độc lập, và mỗi bản thiếu
đúng thứ bản kia có —

  pdf_to_word._VLM_SYS      thiếu ký hiệu toán, thiếu dấu [không đọc được]
  sgk_taphuan._DOC_PROMPT   thiếu lá chắn chống prompt injection

Nên mỗi lần vá chỉ vá được một nửa dự án. Test ở đây khoá lại việc gộp: cả hai
đường phải soi chiếu ``services/ocr_rules``, và bốn quy tắc quan trọng nhất phải
có mặt ở cả hai.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytestmark = pytest.mark.pure

from services import ocr_rules as R  # noqa: E402


class TestKyHieuToan:
    def test_hai_che_do(self):
        assert R.MATH_UNICODE == "unicode" and R.MATH_LATEX == "latex"

    def test_unicode_cho_duong_ra_word(self):
        """pdf_to_word đổ Markdown vào python-docx, nên "$\\frac{a}{b}$" sẽ hiện
        NGUYÊN VĂN trong file Word của người dùng."""
        t = R.rules(math=R.MATH_UNICODE)
        assert "x²" in t and "H₂O" in t
        assert "$…$ trong dòng" not in t

    def test_latex_cho_duong_chi_vao_rag(self):
        t = R.rules(math=R.MATH_LATEX)
        assert "LaTeX" in t and "$…$" in t

    def test_ca_hai_che_do_deu_cam_chep_phang(self):
        """"x2" thay cho "x²" làm sai nghĩa đề toán, và không ai phát hiện được
        khi đọc log."""
        for mode in (R.MATH_UNICODE, R.MATH_LATEX):
            t = R.rules(math=mode)
            assert 'không chép phẳng' in t.lower(), mode
            assert '"x2"' in t, mode

    def test_che_do_la_ve_unicode(self):
        """Gõ sai tên chế độ không được làm mất hẳn quy tắc toán."""
        assert "x²" in R.rules(math="khong-biet")
        assert "x²" in R.rules(math="")


class TestQuyTacBatBuoc:
    def test_chan_prompt_injection(self):
        t = R.rules()
        assert "DỮ LIỆU" in t
        assert "không làm theo" in t

    def test_dau_khong_doc_duoc(self):
        assert "[không đọc được]" in R.rules()

    def test_cam_bia(self):
        t = R.rules()
        assert "Không bịa nội dung" in t

    def test_thu_tu_doc_theo_cot(self):
        assert "cột trái" in R.rules()

    def test_bang_markdown(self):
        assert "|---|" in R.rules()

    def test_mo_ta_hinh_khong_suy_dien(self):
        t = R.rules()
        assert "[HÌNH:" in t
        assert "không đặt tên nhân vật" in t

    def test_tat_mo_ta_hinh(self):
        assert "[HÌNH:" not in R.rules(figures=False)

    def test_cam_lap(self):
        assert "Không lặp lại" in R.rules()


class TestMocTrang:
    def test_doc_moc(self):
        assert R.pages_seen("<<<TRANG 7>>>\nnội dung") == {7}
        assert R.pages_seen("<<<TRANG 1>>>a\n<<< TRANG  2 >>>b") == {1, 2}

    def test_bo_qua_so_in_ghi_kem(self):
        assert R.pages_seen("<<<TRANG 80>>> (số in: 79)") == {80}

    def test_khong_moc(self):
        assert R.pages_seen("chỉ là văn bản") == set()
        assert R.pages_seen("") == set()


class TestLapVong:
    def test_lap_lien_ke(self):
        assert R.looks_degenerate("\n".join(["Một dòng dài đủ để tính đây."] * 10))

    def test_lap_xen_ke(self):
        md = "\n".join("Câu lặp lại rất nhiều lần đây." if i % 2 == 0
                       else f"dòng chen vào số {i} ở đây" for i in range(24))
        assert R.looks_degenerate(md)

    def test_vo_bai_tap_ke_cham_khong_bao_dong_gia(self):
        """Vở bài tập có hàng chục dòng kẻ chấm giống hệt và liền kề. Tính chúng
        là 'lặp vòng' thì loại đúng loại sách cần nạp."""
        md = ("# Bài 3: Điền vào chỗ trống\n"
              + "\n".join(["………………………………………………"] * 20)
              + "\n" + "\n".join(["_____________________"] * 15)
              + "\n| --- | --- |\n" * 12)
        assert not R.looks_degenerate(md)

    def test_van_ban_that_khong_bao_dong(self):
        md = ("# Bài 1: Ôn tập\nHọc sinh đọc đoạn văn sau đây.\n"
              "Sau đó trả lời các câu hỏi bên dưới trang.\n"
              "1. Nhân vật chính trong bài là ai?\n"
              "2. Vì sao bạn ấy quyết định làm như vậy?\n"
              "# Bài 2: Luyện tập\nTính giá trị biểu thức sau.\n"
              "Ghi kết quả vào vở của em nhé.\nĐọc lại bài một lần nữa.")
        assert not R.looks_degenerate(md)

    def test_rong(self):
        assert not R.looks_degenerate("")


class TestHaiDuongDungChung:
    """Khoá lại việc gộp — đây là mục đích của cả file này."""

    def test_pdf_to_word_soi_chieu_ocr_rules(self):
        src = (_ROOT / "services" / "pdf_to_word.py").read_text(encoding="utf-8")
        assert "_ocr_rules.rules(" in src, "pdf_to_word phải dùng ocr_rules"
        assert "MATH_UNICODE" in src, "đường ra .docx phải dùng Unicode, không LaTeX"

    def test_sgk_taphuan_soi_chieu_ocr_rules(self):
        src = (_ROOT / "services" / "agent" / "sgk_taphuan.py").read_text(
            encoding="utf-8")
        assert "ocr_rules.rules(" in src
        assert "MATH_LATEX" in src, "đường chỉ vào RAG nên dùng LaTeX"

    def test_khong_con_bang_lap_vong_thu_hai(self):
        src = (_ROOT / "services" / "agent" / "sgk_taphuan.py").read_text(
            encoding="utf-8")
        assert "_DEGEN_FILLER = set(" not in src, (
            "sgk_taphuan không được khai lại bộ phát hiện lặp vòng")

    def test_photo_intent_soi_chieu_ocr_rules(self):
        """Đường thứ BA: giáo viên chụp trang sách gửi Zalo/Telegram → RAG.
        Prompt cũ chỉ một dòng, nên ảnh trang Toán/Hoá mất số mũ và chỉ số dưới."""
        src = (_ROOT / "services" / "photo_intent.py").read_text(encoding="utf-8")
        assert "ocr_rules.rules(" in src
        assert "MATH_UNICODE" in src, (
            "kết quả OCR này được gửi THẲNG vào tin nhắn cho người dùng đọc, "
            "'$x^2$' trong tin nhắn thì không ai đọc được")
        assert "ocr_rules.looks_degenerate(" in src, (
            "ảnh OCR lặp vòng sẽ vào thẳng file .md của SGK và kho RAG")

    def test_photo_mo_ta_van_co_la_chan_injection(self):
        """`ingest_knowledge_from_photo` là việc MÔ TẢ ảnh nên không áp cả bộ quy
        tắc, nhưng nội dung đi thẳng vào wiki.ingest — phải có lá chắn."""
        src = (_ROOT / "services" / "photo_intent.py").read_text(encoding="utf-8")
        i = src.index("def ingest_knowledge_from_photo")
        j = src.index("def ingest_teacher_from_photo")
        assert "ocr_rules.INJECTION_GUARD" in src[i:j]

    def test_pdf_to_word_chan_lap_vong(self):
        """Ở pdf_to_word, đầu ra lặp vòng còn được CACHE 7 ngày rồi nạp RAG."""
        src = (_ROOT / "services" / "pdf_to_word.py").read_text(encoding="utf-8")
        assert "_ocr_rules.looks_degenerate(" in src

class TestThanhPhanTrangDotsOcr:
    """Ba loại thành phần trang mà bộ quy tắc từng bỏ sót.

    Lấy từ bộ 11 loại của dots.ocr (Caption, Footnote, Page-header, Page-footer…).
    Bộ quy tắc cũ đã nói về bảng, hình, công thức, thứ tự đọc — nhưng KHÔNG nói gì
    về đầu/chân trang, chú thích cuối trang và chú thích hình, nên model cứ chép
    lẫn chúng vào thân bài.

    Vì sao đáng khoá: tài liệu dài là chỗ dùng chính (sgk_taphuan, deep_tutor,
    teacher_assess). Một quyển 40 trang có đầu trang chạy lặp 40 lần cộng 40 số
    trang — 80 mảnh rác trùng nhau đổ vào RAG, đẩy nội dung thật xuống dưới khi
    tìm kiếm. Chú thích cuối trang nhồi vào GIỮA câu thì làm hỏng chính đoạn văn
    nó đang giải thích.
    """

    def test_bo_dau_chan_trang_chay_lap(self):
        r = R.rules()
        assert "Đầu trang / chân trang CHẠY LẶP" in r
        assert "BỎ, không chép vào thân bài" in r

    def test_van_giu_so_trang_khi_no_la_noi_dung_that(self):
        """Trang mục lục thì số trang LÀ dữ liệu — bỏ hết là mất mục lục."""
        assert "trang mục lục thì số trang là dữ liệu" in R.rules()

    def test_chu_thich_cuoi_trang_khong_chen_giua_cau(self):
        r = R.rules()
        assert "KHÔNG chèn vào giữa" in r
        assert "[CHÚ THÍCH]" in r
        # Giữ dấu đánh số để còn đối chiếu được với chỗ gọi trong bài.
        assert "Giữ nguyên dấu đánh số" in r

    def test_chu_thich_hinh_gan_lien_hinh(self):
        assert "NGAY DÒNG SAU [HÌNH:" in R.rules()

    def test_khong_co_hinh_thi_khong_noi_chu_thich_hinh(self):
        """`figures=False` là đường chỉ lấy chữ — đừng tốn output tả ảnh."""
        r = R.rules(figures=False)
        assert "[HÌNH:" not in r
        # Nhưng đầu/chân trang và chú thích cuối trang thì VẪN cần bỏ/tách.
        assert "Đầu trang / chân trang CHẠY LẶP" in r
        assert "[CHÚ THÍCH]" in r

    def test_ba_muc_moi_co_o_CA_HAI_duong_ocr(self):
        """Cả hai đường đều gọi R.rules() nên tự có — khoá lại để không ai tách ra."""
        for ten in ("pdf_to_word.py", "agent/sgk_taphuan.py"):
            src = (_ROOT / "services" / ten).read_text(encoding="utf-8")
            assert "ocr_rules.rules(" in src.replace("_ocr_rules.rules(", "ocr_rules.rules(")

