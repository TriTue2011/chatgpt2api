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
def test_loi_403_thi_chi_luon_cach_chua(monkeypatch):
    """Ca thật 20/08 20:04: bot chỉ hiện đúng dòng «HTTP Error 403: Forbidden».

    Nguyên nhân là yt-dlp cũ hơn lần YouTube đổi cách ký URL — đo được vì
    2026.7.4 hỏng trên cả máy chủ lẫn máy dev, còn 2026.8.19 tải trơn. Dòng lỗi
    này là thứ DUY NHẤT người vận hành nhìn thấy, nên nó phải nói cách chữa.
    """
    from services import video_tai

    class _YtGia:
        class YoutubeDL:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def extract_info(self, *a, **k):
                raise RuntimeError("ERROR: unable to download video data: "
                                   "HTTP Error 403: Forbidden")

    monkeypatch.setattr(video_tai, "co_yt_dlp", lambda: True, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", _YtGia)
    with pytest.raises(video_tai.LoiTaiVideo) as e:
        video_tai.tai_video("https://youtu.be/abc")
    loi = str(e.value)
    assert "403" in loi                      # vẫn giữ nguyên văn lỗi gốc
    assert "yt-dlp" in loi and "image" in loi  # và chỉ ra việc cần làm


@pytest.mark.pure
def test_loi_khac_403_thi_khong_gan_goi_y_sai(monkeypatch):
    """Mạng đứt hay link hỏng mà cũng khuyên nâng yt-dlp là chỉ sai đường."""
    from services import video_tai

    class _YtGia:
        class YoutubeDL:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def extract_info(self, *a, **k):
                raise RuntimeError("ERROR: Video unavailable")

    monkeypatch.setattr(video_tai, "co_yt_dlp", lambda: True, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", _YtGia)
    with pytest.raises(video_tai.LoiTaiVideo) as e:
        video_tai.tai_video("https://youtu.be/abc")
    assert "yt-dlp" not in str(e.value)


@pytest.mark.pure
def test_ban_gui_lai_tran_1080p():
    """Chủ máy chốt lại sau khi thấy 4K: 1080p thôi.

    Đốt chữ vào hình mã hoá lại toàn bộ luồng hình bằng CPU, chi phí đi theo số
    điểm ảnh — 2160p gấp bốn lần 1080p, trên máy chủ đang phục vụ thật, cho một
    khác biệt không ai thấy trong khung chat điện thoại.
    """
    from services.video_tai import CHAT_LUONG

    assert "height<=1080" in CHAT_LUONG["cao"]
    assert "bestaudio" in CHAT_LUONG["cao"], "trần chỉ đặt trên HÌNH"
    assert "height<=2160" not in CHAT_LUONG["cao"]


@pytest.mark.pure
def test_nguon_khong_co_muc_duoi_tran_thi_van_tai_duoc():
    """Thà lấy bản nét hơn trần còn hơn không tải được gì."""
    from services.video_tai import CHAT_LUONG

    for muc, dinh_dang in CHAT_LUONG.items():
        assert dinh_dang.split("/")[-1] == "best", f"{muc} thiếu lưới đỡ cuối"


@pytest.mark.pure
def test_ban_de_xu_ly_ha_hinh_nhung_giu_nguyen_tieng():
    """Chia hai bản chỉ đúng khi bản nhẹ KHÔNG hạ luồng tiếng: mọi bước máy làm
    (nghe lời thoại, tách nhạc khỏi giọng, đo nhịp câu) đều chỉ nghe."""
    from services.video_tai import CHAT_LUONG

    assert "height<=720" in CHAT_LUONG["vua"]
    assert "bestaudio" in CHAT_LUONG["vua"], "hạ cả tiếng thì chữ nghe ra sẽ tệ đi"


@pytest.mark.pure
def test_ban_xu_ly_du_ret_cho_qwen_nhin():
    """720p chứ không 480p: video_vision.trich_khung ép mọi khung vào khung 768
    điểm ảnh. Nguồn rộng 1280 thu nhỏ 1,67 lần thì ảnh sạch; nguồn rộng 854 thu
    nhỏ 0,9 lần, tức nhiễu nén đi thẳng vào model (đo 18/08: khung JPEG nhẹ hơn
    11%, mất đúng phần chi tiết mịn)."""
    import re

    from services.video_tai import CHAT_LUONG

    cao_vua = int(re.search(r"height<=(\d+)", CHAT_LUONG["vua"]).group(1))
    cao_net = int(re.search(r"height<=(\d+)", CHAT_LUONG["cao"]).group(1))
    # 16:9 → chiều rộng phải vượt 768 đủ nhiều để còn thu nhỏ thật sự.
    assert cao_vua * 16 / 9 >= 768 * 1.5
    assert cao_vua < cao_net, "bản xử lý vẫn phải nhẹ hơn bản đem gửi"


@pytest.mark.pure
def test_hai_luot_tai_chay_cung_luc_va_khong_de_len_nhau(monkeypatch):
    """Cùng thư mục là hai lượt ghi đè nhau (yt-dlp đặt tên theo mã video)."""
    import threading
    import time

    from services import video_tai as vt

    dang_chay: list[str] = []
    cao_nhat = []

    def _tai_gia(url, thu_muc=None, *, chat_luong="cao"):
        dang_chay.append(chat_luong)
        cao_nhat.append(len(dang_chay))
        time.sleep(0.2)
        dang_chay.remove(chat_luong)
        return f"/tmp/{chat_luong}/abc.mp4"

    monkeypatch.setattr(vt, "tai_video", _tai_gia)
    tai = vt.TaiSongSong("https://youtu.be/abc")
    try:
        assert tai.ban_vua() == "/tmp/vua/abc.mp4"
        assert tai.ban_cao() == "/tmp/cao/abc.mp4"
    finally:
        tai.dong()
    assert max(cao_nhat) == 2, "hai lượt tải phải chạy cùng lúc, không nối đuôi"
    assert threading.active_count() >= 1


@pytest.mark.pure
def test_ban_net_hong_thi_van_lam_tiep_tren_ban_nhe(monkeypatch):
    """Video hơi mờ vẫn hơn một câu báo lỗi."""
    from services import video_tai as vt

    def _tai_gia(url, thu_muc=None, *, chat_luong="cao"):
        if chat_luong == "cao":
            raise vt.LoiTaiVideo("nguồn chặn bản 4K")
        return "/tmp/vua/abc.mp4"

    monkeypatch.setattr(vt, "tai_video", _tai_gia)
    tai = vt.TaiSongSong("https://youtu.be/abc")
    try:
        assert tai.ban_vua() == "/tmp/vua/abc.mp4"
        assert tai.ban_cao() == ""
    finally:
        tai.dong()


@pytest.mark.pure
def test_ban_net_hong_thi_giu_lai_LY_DO_cho_tang_goi(monkeypatch):
    """Ca thật 21/08: cả hai lượt tải dính 403, log ghi đủ, người dùng chỉ nhận
    «Em không tải được video về» — không lý do, không cách chữa."""
    from services import video_tai as vt

    def _tai_gia(url, thu_muc=None, *, chat_luong="cao"):
        if chat_luong == "cao":
            raise vt.LoiTaiVideo("Không tải được video: ERROR: unable to "
                                 "download video data: HTTP Error 403: Forbidden")
        return "/tmp/vua/abc.mp4"

    monkeypatch.setattr(vt, "tai_video", _tai_gia)
    tai = vt.TaiSongSong("https://youtu.be/abc")
    try:
        assert tai.ban_cao() == ""
        assert "403" in tai.ly_do_hong()
    finally:
        tai.dong()


@pytest.mark.pure
def test_chua_hong_thi_khong_co_ly_do_nao(monkeypatch):
    """Không bịa lý do khi mọi thứ chạy ngon."""
    from services import video_tai as vt

    monkeypatch.setattr(vt, "tai_video",
                        lambda url, thu_muc=None, *, chat_luong="cao":
                        f"/tmp/{chat_luong}/abc.mp4")
    tai = vt.TaiSongSong("https://youtu.be/abc")
    try:
        assert tai.ban_cao() == "/tmp/cao/abc.mp4"
        assert tai.ly_do_hong() == ""
    finally:
        tai.dong()


@pytest.mark.pure
def test_ban_nhe_hong_thi_nem_loi_ra_ngoai(monkeypatch):
    """Không có bản nhẹ thì không nghe được gì — cả việc phải dừng."""
    from services import video_tai as vt

    def _tai_gia(url, thu_muc=None, *, chat_luong="cao"):
        raise vt.LoiTaiVideo("link hỏng")

    monkeypatch.setattr(vt, "tai_video", _tai_gia)
    tai = vt.TaiSongSong("https://youtu.be/abc")
    try:
        with pytest.raises(vt.LoiTaiVideo):
            tai.ban_vua()
    finally:
        tai.dong()


@pytest.mark.pure
def test_chat_luong_la_khong_chay_bua(monkeypatch):
    from services import video_tai as vt

    with pytest.raises(ValueError):
        vt.tai_video("https://youtu.be/abc", chat_luong="4k")


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
