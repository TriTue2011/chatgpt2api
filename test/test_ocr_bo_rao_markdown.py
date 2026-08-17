"""Nhãn ngôn ngữ model chèn thêm không được coi là chữ của trang.

Vì sao có test này: đo 18/08 trên máy chủ thật, model đọc trang scan trả về

    'markdown\\nBài 5. Diện tích hình tròn\\n\\nCông thức tính diện tích S πr²'

tức là chữ ``markdown`` đứng MỘT MÌNH ở dòng đầu, KHÔNG kèm rào ```. Bản cũ
chỉ xử lý nhánh có rào (``out.startswith("```")``) nên chữ đó lọt vào đầu mọi
trang do model đọc — rồi được cache bảy ngày và nạp vào RAG như chữ của trang.
"""

from __future__ import annotations

import pytest


@pytest.mark.pure
def test_nhan_tran_khong_co_rao_van_bi_bo():
    """Đúng chuỗi model trả về trong lần đo 18/08."""
    from services import pdf_to_word as p2w

    that = "markdown\nBài 5. Diện tích hình tròn\n\nCông thức tính diện tích S πr²"
    assert p2w.bo_rao_markdown(that).startswith("Bài 5.")


@pytest.mark.pure
def test_nhan_kem_rao_cung_bi_bo():
    """Nhánh cũ vẫn phải chạy: rào ``` kèm nhãn, có cả rào đóng."""
    from services import pdf_to_word as p2w

    assert p2w.bo_rao_markdown("```markdown\nNội dung trang\n```") == "Nội dung trang"
    assert p2w.bo_rao_markdown("```\nNội dung trang\n```") == "Nội dung trang"
    assert p2w.bo_rao_markdown("```md\nNội dung trang\n```") == "Nội dung trang"


@pytest.mark.pure
def test_khong_an_nham_chu_that_cua_trang():
    """Chỉ bỏ khi CẢ DÒNG đầu đúng bằng nhãn, không bỏ khi nó nằm trong câu."""
    from services import pdf_to_word as p2w

    van = "markdown là một cách viết văn bản.\nDòng sau."
    assert p2w.bo_rao_markdown(van) == van

    van2 = "Bài 1. Định dạng markdown\nNội dung"
    assert p2w.bo_rao_markdown(van2) == van2


@pytest.mark.pure
def test_chi_co_moi_nhan_thi_ra_rong():
    """Model chỉ nhả mỗi nhãn — không được trả về chuỗi 'markdown' làm nội dung."""
    from services import pdf_to_word as p2w

    assert p2w.bo_rao_markdown("markdown") == ""
    assert p2w.bo_rao_markdown("```markdown\n```") == ""


@pytest.mark.pure
def test_ca_hai_duong_OCR_dung_CHUNG_ham_nay():
    """Dự án có HAI đường OCR — vá một nửa là bệnh cũ của kho này.

    ``services/ocr_rules`` đã cảnh báo đúng cái bẫy này. Lần đo 18/08 cho thấy
    đường sách giáo khoa KHÔNG dọn rào gì cả, còn nặng hơn đường kia.
    """
    from pathlib import Path

    # Đọc THẲNG tệp nguồn, không nạp module: nạp services.agent.sgk_taphuan kéo
    # theo services.config và đòi khoá xác thực, nên test sẽ hỏng trên CI vì lý
    # do chẳng liên quan gì tới điều nó muốn khoá. Cùng cách với test_ocr_rules.
    goc = Path(__file__).resolve().parents[1]
    nguon = (goc / "services" / "agent" / "sgk_taphuan.py").read_text(encoding="utf-8")
    assert "bo_rao_markdown" in nguon, "đường sách giáo khoa không dọn nhãn model"
