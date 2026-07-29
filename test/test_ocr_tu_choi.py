"""Model TỪ CHỐI đọc PDF thì KHÔNG được nạp lời từ chối vào kho.

Đo thật 2026-07-29, `book_markdown` trên sgk-tieng-viet-1-tap-mot (8 trang): PDF
không tới được model, model trả về đúng một câu "Không có tệp PDF hoặc hình ảnh
trang sách nào được đính kèm... Vui lòng tải lên PDF". Pipeline khi đó:

  · `pdf_to_word.looks_like_ocr_failure` → ĐI QUA (chỉ bắt "Gemini error …")
  · `ocr_rules.looks_degenerate`         → ĐI QUA (chỉ bắt output thoái hoá)
  · `book_markdown`                      → ghi cảnh báo "KHÔNG KIỂM CHỨNG ĐƯỢC"
                                            rồi VẪN TRẢ VỀ 425 ký tự đó

→ lời từ chối được nạp vào `kb_giao_duc` như nội dung trang sách. Bộ nạp hàng
loạt sẽ nhân nó lên cả quyển, cả lớp. Cảnh báo mà vẫn nhận thì bằng không có.

Bất biến khoá ở đây (mạnh hơn danh sách từ khoá, không cần bảo trì): prompt ĐÃ
yêu cầu mốc `<<<TRANG n>>>`, nên bản trích ĐÚNG phải có ít nhất một mốc. Không
mốc nào trên cả quyển = không nhận được trang nào = phải trả rỗng.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytestmark = pytest.mark.pure

_SRC = _ROOT / "services" / "agent" / "sgk_taphuan.py"

# Nguyên văn model trả về khi PDF không tới được nó (đo 2026-07-29).
TU_CHOI = (
    "Không có tệp PDF hoặc hình ảnh trang sách nào được đính kèm trong cuộc trò "
    "chuyện này, nên tôi không thể OCR nội dung 8 trang.\n\n"
    "Vui lòng tải lên PDF hoặc ảnh của 8 trang cần chép. Khi có tệp, tôi sẽ xuất "
    "đúng định dạng bắt đầu từ\n\nTRANG 1\n\nvà có đủ các mốc TRANG 1 đến TRANG 8 "
    "theo yêu cầu."
)

NOI_DUNG_THAT = (
    "<<<TRANG 1>>> (số in: bìa)\nSGK TIẾNG VIỆT 1\n\n---\n\n"
    "<<<TRANG 2>>>\nBÀI 1 — A a\n1. Nhận biết\nNam và Hà ca hát."
)


def _pages_seen():
    """Lấy `pages_seen` thật của dự án — không viết lại biểu thức mốc trang."""
    from services import ocr_rules
    return ocr_rules.pages_seen


class TestBatDuocLoiTuChoi:
    def test_loi_tu_choi_khong_co_moc_trang(self):
        """Đây là dấu hiệu máy đọc được: lời từ chối NHẮC tới 'TRANG 1' bằng chữ
        nhưng không có mốc `<<<TRANG n>>>` nào."""
        assert _pages_seen()(TU_CHOI) == set()
        assert "TRANG 1" in TU_CHOI, "tiền đề: lời từ chối có nhắc chữ TRANG"

    def test_noi_dung_that_co_moc_trang(self):
        assert _pages_seen()(NOI_DUNG_THAT) == {1, 2}

    def test_hai_lop_chan_cu_deu_khong_bat_duoc(self):
        """Ghi lại VÌ SAO cần lớp chặn thứ ba — nếu sau này ai thấy nó dư."""
        from services import ocr_rules
        assert not ocr_rules.looks_degenerate(TU_CHOI), (
            "nếu looks_degenerate đã bắt được thì test này cần viết lại")


class TestBookMarkdownTraRong:
    """`book_markdown` phải TRẢ RỖNG khi cả quyển không có mốc trang nào."""

    def test_co_chot_chan_truoc_khi_tra_ve(self):
        src = _SRC.read_text(encoding="utf-8")
        i = src.index('body = "\\n\\n---\\n\\n".join(out)')
        j = src.index("if unverified:", i)
        khoi = src[i:j]
        assert "pages_seen" in khoi, (
            "phải kiểm mốc trang NGAY sau khi ghép body, TRƯỚC nhánh unverified")
        assert re.search(r"return\s+\"\"", khoi), (
            "không có mốc trang thì phải `return \"\"`, không được trả body")

    def test_chan_dat_truoc_nhanh_canh_bao(self):
        """Thứ tự quan trọng: nhánh `unverified` chỉ GHI CẢNH BÁO rồi trả body —
        đặt chốt chặn sau nó thì lời từ chối vẫn ra khỏi hàm."""
        src = _SRC.read_text(encoding="utf-8")
        assert src.index("sgk_taphuan_tu_choi_ocr") < src.index(
            "sgk_taphuan_khong_kiem_chung")

    def test_ghi_log_kem_dau_ra_de_chan_doan(self):
        """Không có mẫu output trong log thì lần sau lại phải dựng lại phép đo."""
        src = _SRC.read_text(encoding="utf-8")
        i = src.index("sgk_taphuan_tu_choi_ocr")
        assert "dau_ra" in src[i:i + 400]
