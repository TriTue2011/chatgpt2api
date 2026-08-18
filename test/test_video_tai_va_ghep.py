"""Tải video về và ghép phụ đề vào khung hình.

Hai việc này là mắt xích còn thiếu để một LINK đi trọn đường "phụ đề / lồng
tiếng". Trước đây ô "lồng tiếng" chỉ hiện cho tệp video tải lên, vì như chú
thích trong ``dich_cho.VIEC``: "link hiện chưa tải cả hình về gateway".

Chủ máy chốt 18/08: không giới hạn độ dài, tải ở độ phân giải cao nhất, và khi
người dùng chọn phụ đề thì hỏi tiếp chữ TRÊN hay DƯỚI, rồi hỏi trả tệp .srt
hay ghép thẳng vào video.

Đo thật cùng ngày trên máy chủ, ghép vào một video 2,1 MB:
    dưới → 2.072.643 bytes | luồng ['video', 'audio']
    trên → 2.061.771 bytes | luồng ['video', 'audio']
Kích thước khác nhau xác nhận chữ được vẽ ở hai chỗ khác nhau, và video ra vẫn
đủ cả hình lẫn tiếng.
"""

from __future__ import annotations

import pytest


@pytest.mark.pure
def test_hai_vi_tri_dung_ma_can_le_cua_libass():
    """2 = giữa-dưới, 8 = giữa-trên — cùng quy ước với thẻ {\\an8} của .srt."""
    from services.video_tai import VI_TRI

    assert VI_TRI["duoi"] == 2
    assert VI_TRI["tren"] == 8
    assert set(VI_TRI) == {"duoi", "tren"}


@pytest.mark.pure
def test_vi_tri_la_thi_bao_ngay(tmp_path):
    """Gõ sai vị trí phải hỏng NGAY, đừng lặng lẽ ghép vào chỗ mặc định."""
    from services.video_tai import ghep_phu_de

    v = tmp_path / "v.mp4"
    v.write_bytes(b"khong phai video that")
    with pytest.raises(ValueError):
        ghep_phu_de(str(v), "1\n00:00:00,000 --> 00:00:01,000\nx\n", "giua")


@pytest.mark.pure
def test_thieu_yt_dlp_thi_noi_ro_cach_sua(monkeypatch):
    """Thiếu gói thì báo tên gói, đừng để người vận hành tự đoán."""
    from services import video_tai

    monkeypatch.setattr(video_tai, "co_yt_dlp", lambda: False, raising=False)
    with pytest.raises(video_tai.LoiTaiVideo) as e:
        video_tai.tai_video("https://youtu.be/abc")
    assert "yt-dlp" in str(e.value)


@pytest.mark.pure
def test_tai_o_do_phan_giai_cao_nhat():
    """Chủ máy chốt: tải bản NÉT NHẤT, không hạ chất lượng cho nhẹ."""
    import inspect

    from services import video_tai

    src = inspect.getsource(video_tai.tai_video)
    assert "bestvideo" in src and "bestaudio" in src


@pytest.mark.pure
def test_khong_chan_theo_do_dai():
    """Chủ máy chốt 18/08: KHÔNG giới hạn độ dài video."""
    import inspect

    from services import video_tai

    src = inspect.getsource(video_tai.tai_video)
    for cam in ("max_duration", "duration >", "qua dài", "quá dài"):
        assert cam not in src, f"có vẻ đang chặn theo độ dài: {cam!r}"


@pytest.mark.pure
def test_giu_nguyen_luong_tieng_khi_ghep():
    """Chỉ mã hoá lại HÌNH; chép nguyên TIẾNG cho nhanh và không hao chất lượng."""
    import inspect

    from services import video_tai

    src = inspect.getsource(video_tai.ghep_phu_de)
    assert '"-c:a", "copy"' in src
