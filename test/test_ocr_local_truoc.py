"""Đọc LOCAL trước, model thị giác chỉ là ngoại lệ đo đếm được.

Vì sao đảo chiều: đo thật 17/08 trên một trang hợp đồng tiếng Việt in sạch,
tesseract đạt 93% khớp từ trong 0,5 giây; Qwen3-VL-2B đạt 58% trong 103,7 giây
và đọc "Độc lập - Tự do - Hạnh phúc" thành "Điều lệp - Tà do - Hành phác". Với
chữ thường thì đọc local vừa đúng hơn vừa nhanh gấp hai trăm lần, nên gửi mọi
trang lên model là vừa chậm vừa kém vừa tốn lượt gọi.

Nhưng tesseract mù ba thứ: công thức toán, bảng, và trang chụp mờ. Test ở đây
khoá đúng ba ngoại lệ đó — nới ra là chất lượng tụt, siết vào là đốt lượt model
vô ích.
"""

from __future__ import annotations

import pytest


@pytest.mark.pure
def test_trang_chu_sach_thi_khong_goi_model():
    """Trang chữ thường, tesseract tự tin → dùng luôn, không tốn lượt model."""
    from services import pdf_to_word as p2w

    text = (
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
        "Độc lập - Tự do - Hạnh phúc\n"
        "Điều 3. Nghĩa vụ của bên thuê\n"
        "Trả tiền thuê đúng hạn, chậm nhất ngày 05 hàng tháng.\n"
        "Giữ gìn tài sản; hư hỏng phải bồi thường theo giá thị trường.\n")
    du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm(text, 93.0)
    assert du_tin, vi_sao


@pytest.mark.pure
def test_tin_cay_thap_thi_nhuong_cho_model():
    """Trang mờ/nghiêng: tesseract vẫn trả chữ nhưng điểm tự chấm tụt xuống."""
    from services import pdf_to_word as p2w

    text = "Điều 3. Nghĩa vụ của bên thuê " * 5
    du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm(text, 55.0)
    assert not du_tin
    assert "tin cậy" in vi_sao


@pytest.mark.pure
def test_trang_gan_nhu_trong_thi_nhuong_cho_model():
    """Vài chữ mà điểm cao thì điểm đó không nói lên gì — vẫn phải nhìn lại."""
    from services import pdf_to_word as p2w

    du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm("Trang 12", 99.0)
    assert not du_tin
    assert "ký tự" in vi_sao


@pytest.mark.pure
def test_co_ky_hieu_toan_thi_nhuong_cho_model():
    """tesseract không có khái niệm phân số hay chỉ số trên: x² thành x2."""
    from services import pdf_to_word as p2w

    nen = "Bài tập chương hai, phần hình học phẳng và đại số cơ bản. " * 3
    for cong_thuc in ["Tính S = πr²", "Giải √(x + 1) = 3", "Cho ∑ a_i ≤ 10",
                      "Rút gọn \\frac{a}{b}"]:
        du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm(nen + cong_thuc, 95.0)
        assert not du_tin, cong_thuc
        assert "toán" in vi_sao


@pytest.mark.pure
def test_co_ve_la_bang_thi_nhuong_cho_model():
    """tesseract trả chữ theo dòng, mất ranh giới ô nên bảng đọc ra dính nhau."""
    from services import pdf_to_word as p2w

    bang = (
        "Số thứ tự     Tên hàng          Số lượng     Đơn giá\n"
        "1             Bàn gỗ tự nhiên   10           1.200.000\n"
        "2             Ghế xoay văn phòng 25          850.000\n"
        "3             Tủ tài liệu sắt   4            2.400.000\n")
    assert p2w._co_ve_la_bang(bang)
    du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm(bang, 95.0)
    assert not du_tin
    assert "bảng" in vi_sao


@pytest.mark.pure
def test_van_ban_thuong_khong_bi_nham_la_bang():
    """Chiều ngược lại: đoạn văn bình thường không được rơi vào nhánh bảng."""
    from services import pdf_to_word as p2w

    van = ("Hợp đồng này được lập thành hai bản có giá trị pháp lý như nhau.\n"
           "Mỗi bên giữ một bản để làm căn cứ thực hiện.\n"
           "Hai bên cam kết thực hiện đúng các điều khoản đã thỏa thuận.\n")
    assert not p2w._co_ve_la_bang(van)


@pytest.mark.pure
def test_nguong_nam_trong_vung_do_duoc():
    """Ngưỡng lấy từ số đo thật, không phải con số nghĩ ra."""
    from services import pdf_to_word as p2w

    # tesseract đạt 93% trên bản in sạch; đặt trần trên mức đó là loại luôn
    # chính đường local vừa chứng minh là tốt hơn.
    assert p2w.OCR_TIN_CAY_TOI_THIEU <= 90.0
    # Quá thấp thì trang mờ cũng lọt, mất luôn tác dụng của lưới lọc.
    assert p2w.OCR_TIN_CAY_TOI_THIEU >= 60.0


@pytest.mark.pure
def test_ca_hai_duong_ocr_dung_CHUNG_mot_phep_quyet_dinh():
    """Dự án có HAI đường OCR — cả hai phải hỏi cùng một hàm.

    ``services/ocr_rules`` đã cảnh báo đúng cái bẫy này: "Giữ hai bản prompt
    song song là bảo đảm mọi lần vá chỉ vá được một nửa dự án." Lần đầu đảo
    chiều sang đọc local, đúng là chỉ vá được ``pdf_to_word`` còn
    ``sgk_taphuan`` vẫn gửi hết lên model.

    Test này khoá lại: đường sách giáo khoa phải soi chiếu chính
    ``pdf_to_word._du_tin_de_bo_qua_vlm``, không được tự viết ngưỡng riêng —
    nếu không thì lần chỉnh ngưỡng sau lại chỉ ăn một nửa.
    """
    import inspect

    from services.agent import sgk_taphuan

    nguon = inspect.getsource(sgk_taphuan.book_markdown)
    assert "_tess_page_conf" in nguon, "đường SGK không đọc local trước"
    assert "_du_tin_de_bo_qua_vlm" in nguon, "đường SGK tự nghĩ ngưỡng riêng"
