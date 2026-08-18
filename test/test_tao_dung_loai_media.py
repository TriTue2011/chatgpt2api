"""Định tuyến theo DANH TỪ, không theo chữ đứng ngay sau động từ.

Luật do người vận hành chốt 18/08: phải có "tạo" VÀ danh từ — "ảnh", "video"
hoặc "nhạc". Chữ "anh" trần không tính vì nó thường là đại từ.

Quan sát thật trên bot lúc 12:20 ngày 18/08:

    Nguyễn Việt: Tạo anh bản nhạc ballast nhẹ nhàng
    Bot:  🎨 muốn VẼ "bản nhạc ballast nhẹ nhàng" … (menu model vẽ ảnh)

    Nguyễn Việt: Tạo anh video một chiếc lá phong rụng rơi xuống mặt hồ
    Bot:  🎨 muốn VẼ "video một chiếc lá phong rụng…" … (menu model vẽ ảnh)

Hai nguyên nhân chồng nhau:
  1. ``_TAT_TAO_MEDIA`` nhận "anh" trần làm danh từ ảnh, nên nó khớp trước và
     nuốt luôn danh từ thật vào phần mô tả.
  2. Dòng định tuyến viết "video nếu kind==video, còn lại là ảnh" — nên kể cả
     khi phân loại đúng là nhạc thì vẫn gọi generate_image.
"""

from __future__ import annotations

import pytest


@pytest.mark.pure
@pytest.mark.parametrize("cau,mong_kind,mong_prompt", [
    ("Tạo anh video một chiếc lá phong rụng rơi xuống mặt hồ",
     "video", "một chiếc lá phong rụng rơi xuống mặt hồ"),
    ("tạo ảnh con mèo", "image", "con mèo"),
    ("tạo video cảnh biển", "video", "cảnh biển"),
])
def test_dinh_tuyen_theo_danh_tu(cau, mong_kind, mong_prompt):
    from services.agent.orchestrator import _la_yeu_cau_tao_media

    kq = _la_yeu_cau_tao_media(cau)
    assert kq is not None, f"không nhận ra yêu cầu tạo media: {cau!r}"
    kind, prompt = kq
    assert kind == mong_kind, f"{cau!r} → {kind}, đáng lẽ {mong_kind}"
    assert mong_prompt in prompt, f"mô tả sai: {prompt!r}"


@pytest.mark.pure
def test_khong_dinh_chu_video_vao_mo_ta():
    """Bản cũ để mô tả thành 'video một chiếc lá…' — máy vẽ sẽ vẽ chữ 'video'."""
    from services.agent.orchestrator import _la_yeu_cau_tao_media

    _, prompt = _la_yeu_cau_tao_media("Tạo anh video một chiếc lá phong rụng")
    assert not prompt.lower().startswith("video")


@pytest.mark.pure
def test_nhac_nhuong_cho_bo_dinh_tuyen():
    """Nhạc CỐ Ý không đi đường tắt — đường tắt chỉ lo ảnh/video.

    Việc duy nhất cần ở đây: ĐỪNG nhận nhầm nhạc thành ảnh. Trả None thì bộ
    định tuyến gọi generate_music như thiết kế cũ, thay vì hiện menu VẼ.
    """
    from services.agent.orchestrator import _la_yeu_cau_tao_media

    assert _la_yeu_cau_tao_media("Tạo anh bản nhạc ballast nhẹ nhàng") is None
    assert _la_yeu_cau_tao_media("tạo nhạc vui") is None
    assert _la_yeu_cau_tao_media("tạo bài hát về mùa thu") is None


@pytest.mark.pure
def test_anh_khong_dau_van_hieu_khi_khong_co_danh_tu_khac():
    """Người gõ thiếu dấu thật sự: 'tao anh con meo' vẫn phải ra ảnh."""
    from services.agent.orchestrator import _la_yeu_cau_tao_media

    kq = _la_yeu_cau_tao_media("tao anh con meo")
    assert kq is not None
    kind, _ = kq
    assert kind == "image"


@pytest.mark.pure
def test_cau_khong_phai_tao_moi_van_bi_loai():
    """Đừng cướp mất câu của các luồng khác."""
    from services.agent.orchestrator import _la_yeu_cau_tao_media

    assert _la_yeu_cau_tao_media("xoá ảnh vừa tạo") is None
    assert _la_yeu_cau_tao_media("tạo video bằng model flow/veo-3.1: biển") is None


@pytest.mark.pure
def test_nhac_co_nhanh_rieng_trong_dinh_tuyen():
    """Dòng định tuyến cũ gộp mọi thứ không-phải-video vào generate_image."""
    import inspect

    from services.agent import orchestrator

    src = inspect.getsource(orchestrator)
    assert "generate_music" in src, "không có nhánh nhạc trong đường tắt tạo media"
