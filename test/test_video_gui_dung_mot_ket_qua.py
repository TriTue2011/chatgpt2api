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


@pytest.fixture
def tai_gia(monkeypatch):
    """Hai lượt tải song song giả — ghi lại bản nào được dùng vào việc gì."""
    from services import video_tai as vt

    ghi: dict = {"url": "", "vua": 0, "cao": 0, "dong": 0}

    class _Tai:
        def __init__(self, url):
            ghi["url"] = url

        def ban_vua(self):
            ghi["vua"] += 1
            return "/tmp/vua/abc.mp4"

        def ban_cao(self):
            ghi["cao"] += 1
            return "/tmp/cao/abc.mp4"

        def dong(self):
            ghi["dong"] += 1

    monkeypatch.setattr(vt, "TaiSongSong", _Tai)
    monkeypatch.setattr(vt, "co_yt_dlp", lambda: True)
    return ghi


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


def test_link_chon_ghep_thi_dot_chu_len_ban_NET(bot, phu_de_gia, tai_gia,
                                                monkeypatch):
    """'Khi gửi link thì khi trả lại kèm video nếu là phụ đề' — và bản gửi lại
    phải là bản NÉT, không phải bản nhẹ dùng để xử lý."""
    from services import video_tai as vt

    da_ghep: list[tuple] = []
    monkeypatch.setattr(vt, "ghep_phu_de",
                        lambda duong, srt, vi_tri="duoi", duong_ra=None:
                        (da_ghep.append((duong, vi_tri)), "/tmp/cao/abc_sub.mp4")[1])

    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "phu-de", "dang_ra": "ghep", "vi_tri": "tren",
                        "target": "vi", "nguon": "en"})

    assert tai_gia["url"] == "https://youtu.be/abc"
    assert da_ghep and da_ghep[0][0] == "/tmp/cao/abc.mp4", "đốt chữ lên bản nét"
    assert da_ghep[0][1] == "tren", "phải ghép đúng vị trí đã chọn"
    assert len(bot._ghi["duong"]) == 1, "trả lại đúng một video"
    assert bot._ghi["duong"][0][1] == "/tmp/cao/abc_sub.mp4"
    assert not bot._ghi["tep"], "chọn ghép thì không gửi kèm .srt nữa"
    assert tai_gia["dong"] == 1, "phải dọn hai thư mục tải tạm"


def test_co_phu_de_san_thi_khong_cho_tai_xong_moi_lam(bot, phu_de_gia, tai_gia,
                                                      monkeypatch):
    """Hai lượt tải bật NGAY, còn phụ đề vẫn lấy từ YouTube trong lúc đó —
    không nối đuôi 'tải xong rồi mới lấy chữ'."""
    from services import video_dich as vd
    from services import video_tai as vt

    thu_tu: list[str] = []
    monkeypatch.setattr(vd, "dich_video",
                        lambda url, target="", **k: (
                            thu_tu.append("lấy phụ đề"),
                            {"ok": True, "srt": SRT, "ten": "phu-de.vi.srt",
                             "chu": "hello", "nguon": "en", "dich": "vi"})[1])
    monkeypatch.setattr(vt, "ghep_phu_de",
                        lambda duong, srt, vi_tri="duoi", duong_ra=None: (
                            thu_tu.append("ghép"), "/tmp/cao/abc_sub.mp4")[1])

    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "phu-de", "dang_ra": "ghep", "vi_tri": "duoi",
                        "target": "vi", "nguon": "en"})

    assert thu_tu == ["lấy phụ đề", "ghép"]
    assert tai_gia["vua"] == 0, "có phụ đề sẵn thì khỏi cần bản nhẹ để nghe"
    assert tai_gia["cao"] == 1


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


def test_link_khong_co_phu_de_san_thi_tai_ban_NHE_ve_tu_nghe(bot, monkeypatch):
    """Lỗi 'không có phụ đề sẵn' nay chữa được, không còn là đường cụt. Chỉ cần
    bản NHẸ: nghe là việc của luồng tiếng, mà luồng tiếng bản nhẹ vẫn tốt nhất."""
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
    muc: list[str] = []
    monkeypatch.setattr(vt, "tai_video",
                        lambda url, thu_muc=None, *, chat_luong="cao": (
                            muc.append(chat_luong), "/tmp/x.mp4")[1])

    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "phu-de", "dang_ra": "srt", "vi_tri": "duoi",
                        "target": "vi", "nguon": "en"})
    assert nghe == ["/tmp/x.mp4"], "phải tải về rồi tự nghe"
    assert muc == ["vua"], "ô .srt không cần bản nét, tải nó là phí"
    assert len(bot._ghi["tep"]) == 1


def test_may_chua_cai_yt_dlp_thi_noi_ro(bot, phu_de_gia, monkeypatch):
    """Không phụ thuộc máy chạy test có yt-dlp hay không — ép hẳn hai chiều."""
    from services import video_tai as vt

    monkeypatch.setattr(vt, "co_yt_dlp", lambda: False)
    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "phu-de", "dang_ra": "ghep", "vi_tri": "duoi",
                        "target": "vi", "nguon": "en"})
    assert any("yt-dlp" in t for t in bot._ghi["tin"])
    assert not bot._ghi["duong"]


def test_ca_hai_ban_tai_deu_hong_thi_van_gui_phu_de(bot, phu_de_gia, monkeypatch):
    """Tải hỏng mà vẫn còn phụ đề trong tay thì đừng để cả lượt thành công cốc."""
    from services import video_tai as vt

    monkeypatch.setattr(vt, "co_yt_dlp", lambda: True)

    class _TaiHong:
        def __init__(self, url): pass
        def ban_vua(self): raise vt.LoiTaiVideo("nguồn chặn")
        def ban_cao(self): return ""
        def dong(self): pass

    monkeypatch.setattr(vt, "TaiSongSong", _TaiHong)

    def _khong_duoc_goi(*a, **k):
        raise AssertionError("không có tệp video thì đừng gọi ffmpeg")

    monkeypatch.setattr(vt, "ghep_phu_de", _khong_duoc_goi)

    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "phu-de", "dang_ra": "ghep", "vi_tri": "duoi",
                        "target": "vi", "nguon": "en"})
    assert any("không tải được video" in t.lower() for t in bot._ghi["tin"])
    assert len(bot._ghi["tep"]) == 1, "vẫn phải nhận được tệp .srt"
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


def test_long_tieng_lam_tren_ban_nhe_roi_dua_len_ban_NET(bot, phu_de_gia,
                                                          tai_gia, monkeypatch):
    """Tách lời và tổng hợp giọng chạy trên bản nhẹ cho nhanh; giọng xong rồi
    mới đổi khung hình sang bản nét (chép luồng, không mã hoá lại)."""
    from services import tach_am_gpu as tg
    from services import video_dub as vdub
    from services import video_tai as vt

    monkeypatch.setattr(tg, "xac_nhan_san_sang", lambda: None)

    class _Dub:
        video_path = "/tmp/vua/abc_dub.mp4"
        prosody_path = "/tmp/vua/abc.json"
        voice = "vi-VN-A"
        canh_bao = ""

    nhan: list[str] = []
    monkeypatch.setattr(vdub, "chon_giong", lambda dich: "vi-VN-A")
    monkeypatch.setattr(vdub, "long_tieng",
                        lambda duong, srt, dich, voice="": (
                            nhan.append(duong), _Dub())[1])
    doi_hinh: list[tuple] = []
    monkeypatch.setattr(vt, "thay_tieng",
                        lambda hinh, tieng, duong_ra=None: (
                            doi_hinh.append((hinh, tieng)),
                            "/tmp/cao/abc_dub.mp4")[1])

    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "long-tieng", "target": "vi", "nguon": "en"})

    assert nhan == ["/tmp/vua/abc.mp4"], "xử lý trên bản nhẹ"
    assert doi_hinh == [("/tmp/cao/abc.mp4", "/tmp/vua/abc_dub.mp4")]
    assert [d[1] for d in bot._ghi["duong"]] == ["/tmp/cao/abc_dub.mp4",
                                                 "/tmp/vua/abc.json"]


def test_ban_net_hong_thi_van_gui_ban_nhe_da_long_tieng(bot, phu_de_gia,
                                                        monkeypatch):
    from services import tach_am_gpu as tg
    from services import video_dub as vdub
    from services import video_tai as vt

    monkeypatch.setattr(tg, "xac_nhan_san_sang", lambda: None)
    monkeypatch.setattr(vt, "co_yt_dlp", lambda: True)

    class _Tai:
        def __init__(self, url): pass
        def ban_vua(self): return "/tmp/vua/abc.mp4"
        def ban_cao(self): return ""        # nguồn chặn bản nét
        def dong(self): pass

    class _Dub:
        video_path = "/tmp/vua/abc_dub.mp4"
        prosody_path = "/tmp/vua/abc.json"
        voice = "vi-VN-A"
        canh_bao = ""

    monkeypatch.setattr(vt, "TaiSongSong", _Tai)
    monkeypatch.setattr(vdub, "chon_giong", lambda dich: "vi-VN-A")
    monkeypatch.setattr(vdub, "long_tieng",
                        lambda duong, srt, dich, voice="": _Dub())

    def _khong_duoc_goi(*a, **k):
        raise AssertionError("không có bản nét thì đừng đổi khung hình")

    monkeypatch.setattr(vt, "thay_tieng", _khong_duoc_goi)

    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "long-tieng", "target": "vi", "nguon": "en"})
    assert bot._ghi["duong"][0][1] == "/tmp/vua/abc_dub.mp4"


def test_doi_sang_ban_net_hong_thi_van_gui_ban_da_long_tieng(bot, phu_de_gia,
                                                             tai_gia, monkeypatch):
    """Phần đắt nhất (tách lời, tổng hợp giọng) đã xong — mất nó vì một bước
    chép luồng là quá phí."""
    from services import tach_am_gpu as tg
    from services import video_dub as vdub
    from services import video_tai as vt

    monkeypatch.setattr(tg, "xac_nhan_san_sang", lambda: None)

    class _Dub:
        video_path = "/tmp/vua/abc_dub.mp4"
        prosody_path = "/tmp/vua/abc.json"
        voice = "vi-VN-A"
        canh_bao = ""

    monkeypatch.setattr(vdub, "chon_giong", lambda dich: "vi-VN-A")
    monkeypatch.setattr(vdub, "long_tieng",
                        lambda duong, srt, dich, voice="": _Dub())

    def _hong(hinh, tieng, duong_ra=None):
        raise vt.LoiTaiVideo("codec không chép thẳng sang mp4 được")

    monkeypatch.setattr(vt, "thay_tieng", _hong)

    bot._lam_viec_dich("t1", 0, {"url": "https://youtu.be/abc", "ten": "abc"},
                       {"kieu": "long-tieng", "target": "vi", "nguon": "en"})

    assert bot._ghi["duong"][0][1] == "/tmp/vua/abc_dub.mp4"
    assert any("bản nét" in t for t in bot._ghi["tin"])
