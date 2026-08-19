r"""Directive tạo ảnh của model web không được đi ra tin nhắn người dùng.

Lỗi thật 19/08/2026 trên Zalo Bot: hỏi "sân nhỏ cỏ đen" thì bot trả về nguyên cục

    image_group\ue202{"layout":"carousel","aspect_ratio":"16:9","query":[…]}

Bộ lọc `_IMAGE_GROUP_LEAK` đã có sẵn và mắt thường nhìn log thì thấy khớp, nhưng
model web chèn ký tự VÙNG RIÊNG `\ue202` vào giữa tên directive và dấu '{' — mẫu
cũ dùng `\s*` nên không khớp, directive lọt hết. Cùng lớp lỗi đã xử lý cho
_CITE_TURN và _ENTITY_LEAK: mọi mẫu bắt rác của model web đều phải tính ký tự
vùng riêng.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.pure

# Đúng chuỗi đo được trên máy chủ (giữ nguyên \ue202)
THAT = ('image_group\ue202{"layout":"carousel","aspect_ratio":"16:9",'
        '"query":["small garden black grass landscape design",'
        '"black mondo grass courtyard garden"],"num_per_query":2}')


def _loc(text: str) -> str:
    from services.protocol.openai_v1_chat_complete import _strip_artifacts_inline
    return _strip_artifacts_inline(text)


class TestXoaDirectiveRoRi:
    def test_dung_chuoi_gay_loi_that(self):
        ra = _loc("Dạ anh 😊 em gợi ý vài mẫu:\n\n" + THAT + "\n\nNền chính: cỏ đen.")
        assert "image_group" not in ra
        assert "\ue202" not in ra
        assert "Nền chính: cỏ đen." in ra, "phần trả lời thật phải còn nguyên"

    def test_dang_khong_co_ky_tu_vung_rieng_van_xoa(self):
        assert "image_group" not in _loc('image_group{"layout":"carousel"}')

    def test_directive_dung_dau_cau_tra_loi(self):
        assert "image_group" not in _loc(THAT + "\n\nNền chính: cỏ đen.")


class TestKhongAnOanVanBanThuong:
    """Bộ lọc phải HẸP — không được nuốt chữ của người dùng."""

    def test_nhac_ten_directive_trong_cau_van_giu(self):
        cau = "em dùng image_group để gom ảnh lại nhé"
        assert _loc(cau) == cau

    def test_dau_ngoac_nhon_thuong_khong_bi_xoa(self):
        cau = 'cú pháp JSON là {"key": "value"} anh nhé'
        assert _loc(cau) == cau
