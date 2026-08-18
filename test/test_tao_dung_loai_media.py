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
@pytest.mark.parametrize("cau,mo_ta", [
    ("tạo nhạc ballast nhẹ nhàng", "ballast nhẹ nhàng"),
    ("Tạo anh bản nhạc ballast nhẹ nhàng", "ballast nhẹ nhàng"),
    ("tạo nhạc vui", "vui"),
    ("tạo bài hát về mùa thu", "mùa thu"),
    ("tạo ca khúc buồn", "buồn"),
])
def test_nhac_di_duong_tat_nhu_anh_va_video(cau, mo_ta):
    """ĐỔI 19/08: nhạc đi đường tắt, không phó cho model tự nhớ gọi tool.

    Bản cũ trả None để "bộ định tuyến gọi generate_music". Đo thật 23:33 ngày
    18/08 trên bot: model CÓ tool (nhóm 'music' bật cho cả hai kênh) mà vẫn trả
    lời "trong khung chat này em chưa có công cụ xuất ra file nhạc thật" rồi
    không làm gì — người dùng mất trắng lượt.

    Vì sao nhạc KHÔNG cần qua model như ảnh/video: ảnh và video có nhiều nhà
    cung cấp nên phải hiện menu chọn; nhạc chỉ có MỘT đường (Gemini/Lyria qua
    trình duyệt, handler nhận đúng một tham số prompt) — không có gì để hỏi.
    """
    from services.agent.orchestrator import _la_yeu_cau_tao_media

    kq = _la_yeu_cau_tao_media(cau)
    assert kq is not None, "nhạc phải được nhận, không được trả None"
    kind, prompt = kq
    assert kind == "music"
    assert prompt == mo_ta, "mô tả phải bỏ cả động từ lẫn danh từ loại"


@pytest.mark.pure
def test_tao_nhac_khong_kem_mo_ta_thi_van_nhan():
    """Rỗng cũng hợp lệ — handler tự hỏi lại muốn nhạc thế nào."""
    from services.agent.orchestrator import _la_yeu_cau_tao_media

    assert _la_yeu_cau_tao_media("tạo nhạc") == ("music", "")


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
