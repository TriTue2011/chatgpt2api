"""Menu video: gửi lại ĐÚNG thứ người dùng đã chọn, đúng một thứ.

Chủ máy chốt 18/08, ba câu:

  · "nếu phụ đề kèm 2 lựa chọn bên trên hay bên dưới, KHÔNG gửi 2 cái như bây
    giờ" — bản cũ gửi luôn cả hai tệp .srt (bản thường + bản chữ-trên) vì nó
    không hỏi vị trí.
  · "hỏi trả file phụ đề srt hay ghép luôn vào video rồi trả user".
  · "không gpu báo không có gpu, chỉ tạo được phụ đề".

Và kiến trúc: "chuyển thành phụ đề rồi mới qua llm để làm 12345" — bốn ô đọc
hiểu chạy trên phụ đề vừa tạo, không nghe lại video.
"""

from __future__ import annotations

import pytest

SRT = b"1\n00:00:01,000 --> 00:00:02,000\nhello\n\n"


@pytest.fixture
def bot(monkeypatch):
    """zalo_personal với mọi cửa gửi ra ngoài bị chặn lại để đếm."""
    from services import zalo_personal as zp

    ghi: dict[str, list] = {"tin": [], "tep": [], "duong": []}
    monkeypatch.setattr(zp, "send_message",
                        lambda tid, text, ttype=0, **k: ghi["tin"].append(text))
    monkeypatch.setattr(zp, "send_typing", lambda *a, **k: None)
    monkeypatch.setattr(zp, "_serve_bytes",
                        lambda tid, tt, du_lieu, ten, ghi_chu="":
                        ghi["tep"].append((ten, du_lieu, ghi_chu)))
    monkeypatch.setattr(zp, "_serve_path",
                        lambda tid, tt, duong, ten, ghi_chu="":
                        ghi["duong"].append((ten, duong, ghi_chu)))
    zp._ghi = ghi
    return zp


@pytest.fixture
def phu_de_gia(monkeypatch):
    """video_dich trả sẵn một kết quả phụ đề, không nghe/dịch gì thật."""
    from services import video_dich as vd

    goi: dict[str, list] = {"link": [], "tep": []}
    r = {"ok": True, "srt": SRT, "ten": "phu-de.vi.srt", "chu": "hello",
         "nguon": "en", "dich": "vi", "so_doan": 1, "phut": 1}

    def _link(url, target="", **k):
        goi["link"].append(url)
        return dict(r)

    def _tep(duong, ten="", target="", **k):
        goi["tep"].append(duong)
        return dict(r)

    monkeypatch.setattr(vd, "dich_video", _link)
    monkeypatch.setattr(vd, "dich_tep_video", _tep)
    monkeypatch.setattr(vd, "bao_cao", lambda r: "✅ xong")
    return goi


def test_phu_de_srt_chu_tren_chi_gui_mot_tep(bot, phu_de_gia):
    """Chọn .srt + chữ TRÊN → đúng MỘT tệp, và là bản chữ-trên."""
    bot._lam_viec_dich("t1", 0, {"path": "/tmp/a.mp4", "ten": "a.mp4"},
                       {"kieu": "phu-de", "dang_ra": "srt", "vi_tri": "tren",
                        "target": "vi", "nguon": "en"})
    tep = bot._ghi["tep"]
    assert len(tep) == 1, f"phải gửi đúng một tệp, đang gửi {len(tep)}"
    ten, du_lieu, _ = tep[0]
    assert "tren" in ten
    assert b"{\\an8}" in du_lieu, "bản chữ-trên phải có thẻ căn lề trên"


def test_phu_de_srt_chu_duoi_khong_kem_ban_thu_hai(bot, phu_de_gia):
    bot._lam_viec_dich("t1", 0, {"path": "/tmp/a.mp4", "ten": "a.mp4"},
                       {"kieu": "phu-de", "dang_ra": "srt", "vi_tri": "duoi",
                        "target": "vi", "nguon": "en"})
    assert len(bot._ghi["tep"]) == 1
    assert bot._ghi["tep"][0][1] == SRT


def test_link_chon_ghep_thi_tai_video_ve_va_tra_lai_video(bot, phu_de_gia,
                                                          monkeypatch):
    """'Khi gửi link thì khi trả lại kèm video nếu là phụ đề'."""
    from services import video_tai as vt

    da_tai: list[str] = []
    da_ghep: list[tuple] = []
    monkeypatch.setattr(vt, "tai_video",
                        lambda url, thu_muc=None: (da_tai.append(url),
                                                   "/tmp/tai/abc.mp4")[1])
    monkeypatch.setattr(vt, "ghep_phu_de",
                        lambda duong, srt, vi_tri="duoi", duong_ra=None:
                        (da_ghep.append((duong, vi_tri)), "/tmp/tai/abc_sub.mp4")[1])

    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "phu-de", "dang_ra": "ghep", "vi_tri": "tren",
                        "target": "vi", "nguon": "en"})

    assert da_tai == ["https://youtu.be/abc"], "link chọn ghép thì phải tải về"
    assert da_ghep and da_ghep[0][1] == "tren", "phải ghép đúng vị trí đã chọn"
    assert len(bot._ghi["duong"]) == 1, "trả lại đúng một video"
    assert bot._ghi["duong"][0][1] == "/tmp/tai/abc_sub.mp4"
    assert not bot._ghi["tep"], "chọn ghép thì không gửi kèm .srt nữa"


def test_chon_srt_thi_khong_tai_video_ve(bot, phu_de_gia, monkeypatch):
    """Tải mấy trăm MB về chỉ để trả một tệp chữ là phí."""
    from services import video_tai as vt

    def _khong_duoc_goi(*a, **k):
        raise AssertionError("ô .srt không được tải video về")

    monkeypatch.setattr(vt, "tai_video", _khong_duoc_goi)
    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "phu-de", "dang_ra": "srt", "vi_tri": "duoi",
                        "target": "vi", "nguon": "en"})
    assert len(bot._ghi["tep"]) == 1


def test_link_khong_co_phu_de_san_thi_tai_ve_tu_nghe(bot, monkeypatch):
    """Lỗi 'không có phụ đề sẵn' nay chữa được, không còn là đường cụt."""
    from services import video_dich as vd
    from services import video_tai as vt

    monkeypatch.setattr(vd, "dich_video",
                        lambda url, target="", **k: {
                            "ok": False, "error": vd.LOI_CHUA_CO_TIENG})
    nghe: list[str] = []
    monkeypatch.setattr(vd, "dich_tep_video",
                        lambda duong, ten="", target="", **k: (
                            nghe.append(duong),
                            {"ok": True, "srt": SRT, "ten": "phu-de.vi.srt",
                             "chu": "hello", "nguon": "en", "dich": "vi"})[1])
    monkeypatch.setattr(vd, "bao_cao", lambda r: "✅ xong")
    monkeypatch.setattr(vt, "tai_video", lambda url, thu_muc=None: "/tmp/x.mp4")

    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "phu-de", "dang_ra": "srt", "vi_tri": "duoi",
                        "target": "vi", "nguon": "en"})
    assert nghe == ["/tmp/x.mp4"], "phải tải về rồi tự nghe"
    assert len(bot._ghi["tep"]) == 1


def test_loi_tai_video_thi_bao_chu_khong_im_lang(bot, phu_de_gia, monkeypatch):
    from services import video_tai as vt

    def _hong(url, thu_muc=None):
        raise vt.LoiTaiVideo("Máy chủ chưa cài yt-dlp nên chưa tải được video về.")

    monkeypatch.setattr(vt, "tai_video", _hong)
    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "phu-de", "dang_ra": "ghep", "vi_tri": "duoi",
                        "target": "vi", "nguon": "en"})
    assert any("yt-dlp" in t for t in bot._ghi["tin"])
    assert not bot._ghi["duong"]


def test_khong_co_gpu_thi_bao_chi_lam_duoc_phu_de(bot, monkeypatch):
    """Đúng câu chủ máy chốt: 'không gpu báo không có gpu chỉ tạo được phụ đề'."""
    from services import tach_am_gpu as tg
    from services import video_dich as vd

    def _khong_san_sang():
        raise tg.LoiTachAm("chưa có máy tách lời")

    monkeypatch.setattr(tg, "xac_nhan_san_sang", _khong_san_sang)

    def _khong_duoc_goi(*a, **k):
        raise AssertionError("thiếu GPU thì không được chạy tiếp")

    monkeypatch.setattr(vd, "dich_tep_video", _khong_duoc_goi)

    bot._lam_viec_dich("t1", 0, {"path": "/tmp/a.mp4", "ten": "a.mp4"},
                       {"kieu": "long-tieng", "target": "vi", "nguon": "en"})
    loi = "\n".join(bot._ghi["tin"])
    assert "PHỤ ĐỀ" in loi and "GPU" in loi
    assert not bot._ghi["tep"] and not bot._ghi["duong"]


def test_o_tom_tat_chay_tren_phu_de_chu_khong_nghe_lai(bot, phu_de_gia,
                                                       monkeypatch):
    from services import video_hoi as vh

    da_hoi: list[tuple] = []
    monkeypatch.setattr(vh, "hoi",
                        lambda viec, noi_dung, them="": (
                            da_hoi.append((viec, noi_dung, them)),
                            "Video nói về hai việc…")[1])

    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "llm", "viec": "tom-tat"})

    assert da_hoi and da_hoi[0][0] == "tom-tat"
    assert da_hoi[0][1] == "hello", "ba ô đọc-hiểu nhận LỜI THOẠI, không cần mốc giờ"
    assert any("hai việc" in t for t in bot._ghi["tin"])
    assert not bot._ghi["tep"], "câu trả lời ngắn thì nhắn thẳng, khỏi đóng tệp"


def test_o_phan_tich_nhan_phu_de_co_moc_gio(bot, phu_de_gia, monkeypatch):
    """Không có mốc giờ thì model không tìm được 'đoạn từ 10:20'."""
    from services import video_hoi as vh

    da_hoi: list[tuple] = []
    monkeypatch.setattr(vh, "hoi",
                        lambda viec, noi_dung, them="": (
                            da_hoi.append((viec, noi_dung, them)), "phân tích…")[1])

    bot._lam_viec_dich("t1", 0, {"path": "/tmp/a.mp4", "ten": "a.mp4"},
                       {"kieu": "llm", "viec": "phan-tich", "doan": "từ 10:20"})

    assert "00:00:01,000" in da_hoi[0][1], "ô phân tích phải nhận nguyên .srt"
    assert da_hoi[0][2] == "từ 10:20"


def test_llm_hong_van_giu_lai_phu_de(bot, phu_de_gia, monkeypatch):
    """Nghe cả video xong mà mất trắng vì model bận là lần sau phải chờ lại."""
    from services import video_hoi as vh

    def _hong(viec, noi_dung, them=""):
        raise vh.LoiHoiVideo("model đang bận")

    monkeypatch.setattr(vh, "hoi", _hong)
    bot._lam_viec_dich("t1", 0, {"path": "/tmp/a.mp4", "ten": "a.mp4"},
                       {"kieu": "llm", "viec": "ghi-chu"})
    assert bot._ghi["tep"] and bot._ghi["tep"][0][1] == SRT


def test_long_tieng_tu_link_phai_tai_video_ve_truoc(bot, phu_de_gia, monkeypatch):
    """Link lồng tiếng được là nhờ có tệp hình trong tay — trước đây ô này bị
    giấu khỏi link vì gateway chưa tải video về bao giờ."""
    from services import tach_am_gpu as tg
    from services import video_dub as vdub
    from services import video_tai as vt

    monkeypatch.setattr(tg, "xac_nhan_san_sang", lambda: None)
    monkeypatch.setattr(vt, "tai_video", lambda url, thu_muc=None: "/tmp/tai/abc.mp4")

    class _Dub:
        video_path = "/tmp/tai/abc_dub.mp4"
        prosody_path = "/tmp/tai/abc.json"
        voice = "vi-VN-A"
        canh_bao = ""

    nhan: list[str] = []
    monkeypatch.setattr(vdub, "chon_giong", lambda dich: "vi-VN-A")
    monkeypatch.setattr(vdub, "long_tieng",
                        lambda duong, srt, dich, voice="": (
                            nhan.append(duong), _Dub())[1])

    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "long-tieng", "target": "vi", "nguon": "en"})

    assert nhan == ["/tmp/tai/abc.mp4"], "phải lồng tiếng trên tệp vừa tải về"
    assert [d[1] for d in bot._ghi["duong"]] == ["/tmp/tai/abc_dub.mp4",
                                                 "/tmp/tai/abc.json"]
