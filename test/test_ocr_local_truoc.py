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


def _sach(tb=96.0, thap_nhat=94.0, dong_cot=0):
    """Chỉ số của một trang chữ thường in sạch — lấy từ số đo thật 17/08."""
    return {"tb": tb, "thap_nhat": thap_nhat, "dong_cot": dong_cot}


VAN_SACH = (
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
    "Độc lập - Tự do - Hạnh phúc\n"
    "Điều 3. Nghĩa vụ của bên thuê\n"
    "Trả tiền thuê đúng hạn, chậm nhất ngày 05 hàng tháng.\n"
    "Giữ gìn tài sản; hư hỏng phải bồi thường theo giá thị trường.\n")


@pytest.mark.pure
def test_trang_chu_sach_thi_khong_goi_model():
    """Trang chữ thường, tesseract tự tin → dùng luôn, không tốn lượt model."""
    from services import pdf_to_word as p2w

    du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm(VAN_SACH, _sach())
    assert du_tin, vi_sao


@pytest.mark.pure
def test_tin_cay_trung_binh_thap_thi_nhuong_cho_model():
    """Trang mờ/nghiêng: tesseract vẫn trả chữ nhưng điểm tự chấm tụt xuống."""
    from services import pdf_to_word as p2w

    du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm(VAN_SACH, _sach(tb=55.0))
    assert not du_tin
    assert "tin cậy" in vi_sao


@pytest.mark.pure
def test_mot_chu_doc_bua_la_du_de_nhuong_cho_model():
    """Bài học 17/08: TRUNG BÌNH không phát hiện được công thức lẫn bảng.

    Đo trên bốn trang render: trung bình 92,8 đến 96,1 — trang bảng còn cao hơn
    ngưỡng, nên lọt qua. Nhưng TỪ THẤP NHẤT thì tách bạch: chữ thường 96 và 94,
    công thức 70, bảng 64. Đó là chỗ tesseract đọc bừa.
    """
    from services import pdf_to_word as p2w

    # Đúng chỉ số đo được ở trang công thức: trung bình đẹp, thấp nhất tụt.
    du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm(
        VAN_SACH, _sach(tb=93.5, thap_nhat=70.0))
    assert not du_tin, "trung bình 93,5 mà vẫn nhận là bỏ lọt công thức"
    assert "đọc bừa" in vi_sao


@pytest.mark.pure
def test_trang_gan_nhu_trong_thi_nhuong_cho_model():
    """Vài chữ mà điểm cao thì điểm đó không nói lên gì — vẫn phải nhìn lại."""
    from services import pdf_to_word as p2w

    du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm("Trang 12", _sach(thap_nhat=99.0))
    assert not du_tin
    assert "ký tự" in vi_sao


@pytest.mark.pure
def test_ky_hieu_toan_con_sot_van_bi_bat():
    """Lưới phụ: khi tesseract ĐỌC ĐÚNG ký hiệu thì bắt luôn từ văn bản."""
    from services import pdf_to_word as p2w

    nen = "Bài tập chương hai, phần hình học phẳng và đại số cơ bản. " * 3
    for cong_thuc in ["Tính S = πr²", "Giải √(x + 1) = 3", "Cho ∑ a ≤ 10"]:
        du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm(nen + cong_thuc, _sach())
        assert not du_tin, cong_thuc
        assert "toán" in vi_sao


@pytest.mark.pure
def test_bang_bi_bat_bang_TOA_DO_chu_khong_bang_khoang_trang():
    """Bài học 17/08: dò khoảng trắng trong chuỗi đã ghép là vô ích.

    _tess_page_conf ghép từ trong một dòng bằng " ".join, tức bóp mọi khoảng
    trắng thành một dấu cách. Phép dò cũ tìm ba khoảng trắng liên tiếp nên
    KHÔNG BAO GIỜ khớp. Nay đếm dòng bị chia cột bằng toạ độ, đo trước khi ghép.
    """
    from services import pdf_to_word as p2w

    # Văn bản trông như một dòng liền — đúng thứ tesseract trả về cho bảng.
    van = "Số TT Tên hàng Số lượng Đơn giá 1 Bàn gỗ tự nhiên 10 1.200.000 " * 3
    du_tin, _ = p2w._du_tin_de_bo_qua_vlm(van, _sach())
    assert du_tin, "không có chỉ số cột thì đây chỉ là văn bản thường"

    du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm(van, _sach(dong_cot=3))
    assert not du_tin
    assert "bảng" in vi_sao


@pytest.mark.pure
def test_mot_dong_lech_khong_du_ket_toi_ca_trang():
    """Chiều ngược lại: một dòng lệch ngẫu nhiên không biến trang thành bảng."""
    from services import pdf_to_word as p2w

    du_tin, vi_sao = p2w._du_tin_de_bo_qua_vlm(VAN_SACH, _sach(dong_cot=1))
    assert du_tin, vi_sao


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
