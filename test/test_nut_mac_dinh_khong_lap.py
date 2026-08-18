"""Bấm "Mặc định" ở menu tạo ảnh/video/nhạc phải chạy, không được hỏi lại.

Quan sát thật trên bot lúc 12:20 ngày 18/08:

    Nguyễn Việt: Tạo anh bản nhạc ballast nhẹ nhàng
    Bot:  muốn vẽ "bản nhạc ballast nhẹ nhàng" … 1. Mặc định …
    Nguyễn Việt: 1
    Bot:  muốn vẽ "bằng mặc định: bản nhạc ballast nhẹ nhàng" … 1. Mặc định …
    Nguyễn Việt: 1
    Bot:  muốn vẽ "bằng mặc định: bằng mặc định: bản nhạc balla…" …

Nút "Mặc định" gửi lại câu ``vẽ bằng mặc định: <mô tả>``. Bản cũ CỐ Ý không bắt
chuỗi đó (chú thích ghi "lựa chọn ít gặp"), nên nó rơi xuống đường LLM và
"bằng mặc định:" bị nuốt vào làm một phần mô tả. Menu hiện lại với mô tả đã
bẩn, mỗi lần bấm lại bẩn thêm một lớp — không bao giờ thoát.

Giả định "ít gặp" sai ngay từ đầu: đó là lựa chọn SỐ 1 của mọi menu.
"""

from __future__ import annotations

import pytest


@pytest.mark.pure
@pytest.mark.parametrize("cau,mong_kind", [
    ("vẽ bằng mặc định: bản nhạc ballast nhẹ nhàng", "image"),
    ("tạo ảnh bằng mặc định: một con mèo", "image"),
    ("tạo video bằng mặc định: lá phong rơi xuống hồ", "video"),
    ("tạo nhạc bằng mặc định: giai điệu buồn", "music"),
])
def test_nut_mac_dinh_duoc_nhan_dien(cau, mong_kind):
    from services.agent.orchestrator import _doc_nut_menu_media

    kq = _doc_nut_menu_media(cau)
    assert kq is not None, "không nhận ra nút Mặc định → sẽ hỏi lại vô hạn"
    kind, args = kq
    assert kind == mong_kind


@pytest.mark.pure
def test_mo_ta_khong_con_dinh_chu_mac_dinh():
    """Đây chính là thứ phình ra qua từng vòng lặp."""
    from services.agent.orchestrator import _doc_nut_menu_media

    _, args = _doc_nut_menu_media("vẽ bằng mặc định: bản nhạc ballast nhẹ nhàng")
    assert args["prompt"] == "bản nhạc ballast nhẹ nhàng"
    assert "mặc định" not in args["prompt"]


@pytest.mark.pure
def test_bao_cho_handler_biet_da_chon_roi():
    """Thiếu tín hiệu này thì handler thấy model rỗng và lại dựng menu."""
    from services.agent.orchestrator import _doc_nut_menu_media
    from services.agent.capabilities import _IMAGE_DEFAULT_TOKENS

    _, args = _doc_nut_menu_media("vẽ bằng mặc định: con mèo")
    assert args.get("tool", "").lower() in _IMAGE_DEFAULT_TOKENS


@pytest.mark.pure
def test_tao_nhac_khong_nhan_tham_so_tool():
    """generate_music không khai tham số 'tool' — truyền vào là sai hợp đồng."""
    from services.agent.orchestrator import _doc_nut_menu_media

    _, args = _doc_nut_menu_media("tạo nhạc bằng mặc định: giai điệu buồn")
    assert "tool" not in args


@pytest.mark.pure
def test_van_bat_dung_nut_chon_model_cu_the():
    """Vá xong không được làm hỏng nhánh chọn model cụ thể."""
    from services.agent.orchestrator import _doc_nut_menu_media

    kq = _doc_nut_menu_media("vẽ bằng model gpt-image-2: con mèo")
    assert kq is not None
    kind, args = kq
    assert kind == "image" and args["model"] == "gpt-image-2"
    assert args["prompt"] == "con mèo"


@pytest.mark.pure
def test_cau_thuong_khong_bi_bat_nham():
    """Câu người gõ bình thường phải đi đường LLM như cũ."""
    from services.agent.orchestrator import _doc_nut_menu_media

    assert _doc_nut_menu_media("tạo anh bản nhạc ballast nhẹ nhàng") is None
    assert _doc_nut_menu_media("hôm nay trời đẹp") is None
