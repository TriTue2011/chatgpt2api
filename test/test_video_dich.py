"""Dịch video từ link — gộp mảnh phụ đề, khuôn SRT, nhận link, đường lỗi.

Không gọi mạng: chặn ``lay_phu_de`` bằng dữ liệu giả. Cái đáng hỏng ở đây là
ghép chữ và mốc thời gian, kiểm được mà không cần YouTube.
"""

from __future__ import annotations

import pytest

from services import video_dich as vd
from test._fakes import FakeTranslate, install_translate


@pytest.fixture(autouse=True)
def _co_may_chu_dich(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "http://vn-translate:5000")
    monkeypatch.setitem(config.data, "translate_api_key", "")


# ── Nhận link ───────────────────────────────────────────────────────────────


@pytest.mark.pure
@pytest.mark.parametrize("text", [
    "https://www.youtube.com/watch?v=aircAruvnKk",
    "https://youtu.be/aircAruvnKk",
    "https://www.youtube.com/shorts/aircAruvnKk",
    "dịch giúp em video này https://youtu.be/aircAruvnKk với",
    "https://www.youtube.com/watch?feature=share&v=aircAruvnKk",
    "https://www.tiktok.com/@ai/video/7300000000000000000",
    "https://vm.tiktok.com/ZSabcdef",
])
def test_nhan_ra_link_video(text):
    assert vd.la_link_video(text) != ""


@pytest.mark.pure
@pytest.mark.parametrize("text", [
    "", "xin chào", "https://example.com/phim.mp4",
    "https://vimeo.com/123456", "youtube",
])
def test_khong_nham_la_link_video(text):
    assert vd.la_link_video(text) == ""


@pytest.mark.pure
def test_lay_dung_ma_video():
    assert vd._ma_video("https://youtu.be/aircAruvnKk") == "aircAruvnKk"
    assert vd._ma_video("https://www.tiktok.com/@a/video/7300000000000000000") == ""


# ── Gộp mảnh vụn thành câu ──────────────────────────────────────────────────


@pytest.mark.pure
def test_gop_mach_vun_toi_het_cau():
    """Phụ đề tự sinh cắt giữa câu; gộp lại thì máy dịch mới có ngữ cảnh."""
    doan = [
        vd.Doan(0.0, 1.5, "the neural network"),
        vd.Doan(1.5, 3.0, "learns from examples."),
        vd.Doan(3.0, 4.5, "Each layer extracts"),
        vd.Doan(4.5, 6.0, "different features."),
    ]
    ra = vd.gop_doan(doan)
    assert [d.chu for d in ra] == [
        "the neural network learns from examples.",
        "Each layer extracts different features.",
    ]
    assert (ra[0].bat_dau, ra[0].ket_thuc) == (0.0, 3.0)
    assert (ra[1].bat_dau, ra[1].ket_thuc) == (3.0, 6.0)


@pytest.mark.pure
def test_khong_gop_qua_nguong_thoi_gian():
    """Người nói không ngắt câu suốt cả phút thì vẫn phải cắt, kẻo một khung
    phụ đề dài cả phút không ai đọc kịp."""
    doan = [vd.Doan(i * 5.0, i * 5.0 + 5.0, f"phan {i}") for i in range(8)]
    ra = vd.gop_doan(doan)
    assert len(ra) > 1
    assert all(d.ket_thuc - d.bat_dau <= vd.GOP_TOI_GIAY + 5.0 for d in ra)


@pytest.mark.pure
def test_khong_gop_qua_nguong_ky_tu():
    doan = [vd.Doan(i * 1.0, i * 1.0 + 1.0, "x" * 80) for i in range(6)]
    ra = vd.gop_doan(doan)
    assert all(len(d.chu) <= vd.GOP_TOI_KY_TU for d in ra)


# ── Khuôn SRT ───────────────────────────────────────────────────────────────


@pytest.mark.pure
def test_moc_thoi_gian_dung_khuon_srt():
    assert vd._moc(0) == "00:00:00,000"
    assert vd._moc(3661.5) == "01:01:01,500"
    assert vd._moc(-3) == "00:00:00,000"


@pytest.mark.pure
def test_moc_phan_le_tron_len_phai_nhay_giay():
    """0.9996s làm tròn kiểu 'phần lẻ × 1000' ra ',1000' — bốn chữ số ms,
    không nhảy giây. Đo thật 13/08: 5/429 khung video Zootopia dính."""
    assert vd._moc(455.9996) == "00:07:36,000"
    assert vd._moc(59.9999) == "00:01:00,000"
    assert vd._moc(3599.9995) == "01:00:00,000"


@pytest.mark.pure
def test_srt_dung_khuon_va_danh_so_tu_1():
    """Khung đầu kết thúc SỚM hơn 24 ms so với mốc bắt đầu khung sau — chừa
    khoảng hở, không thì trình phát đè hai dòng lên nhau."""
    srt = vd.lam_srt([vd.Doan(0.0, 2.0, "câu một"), vd.Doan(2.0, 4.25, "câu hai")])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,976\ncâu một\n")
    assert "2\n00:00:02,000 --> 00:00:04,250\ncâu hai\n" in srt


@pytest.mark.pure
def test_khung_qua_ngan_duoc_keo_dai_toi_thieu():
    """Mốc kết thúc trùng mốc bắt đầu thì trình phát bỏ qua khung. Kéo lên mức
    tối thiểu 1000 ms (mặc định của Subtitle Edit)."""
    srt = vd.lam_srt([vd.Doan(5.0, 5.0, "nhanh")])
    assert "00:00:05,000 --> 00:00:06,000" in srt


# ── Đường đầy đủ ────────────────────────────────────────────────────────────


def _phu_de_gia(doan, ma="en"):
    def _lay(url, dich_sang="vi"):
        return doan, ma
    return _lay


def test_dich_video_tra_ve_srt_va_chu(monkeypatch):
    monkeypatch.setattr(vd, "lay_phu_de", _phu_de_gia([
        vd.Doan(0.0, 2.0, "Hello there."),
        vd.Doan(2.0, 4.0, "This is a test."),
    ]))
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        r = vd.dich_video("https://youtu.be/aircAruvnKk")
    assert r["ok"] is True
    assert r["ten"] == "phu-de.vi.srt"
    assert r["nguon"] == "en" and r["dich"] == "vi"
    assert r["so_doan"] == 2
    srt = r["srt"].decode()
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,976\nvi:Hello there.")
    assert "vi:This is a test." in srt
    assert vd.soat_srt(srt) == []


def test_khong_co_link_thi_noi_ro():
    r = vd.dich_video("xin chào")
    assert r["ok"] is False and "không thấy link" in r["error"]


def test_tiktok_noi_ro_chua_lam(monkeypatch):
    r = vd.dich_video("https://www.tiktok.com/@ai/video/7300000000000000000")
    assert r["ok"] is False and "chưa làm" in r["error"]


def test_video_qua_dai_thi_tu_choi(monkeypatch):
    monkeypatch.setattr(vd, "lay_phu_de", _phu_de_gia([
        vd.Doan(0.0, vd.TRAN_GIAY + 600, "quá dài"),
    ]))
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        r = vd.dich_video("https://youtu.be/aircAruvnKk")
    assert r["ok"] is False and "quá mức" in r["error"]


def test_phu_de_da_dung_tieng_dich_thi_bao(monkeypatch):
    monkeypatch.setattr(vd, "lay_phu_de", _phu_de_gia(
        [vd.Doan(0.0, 2.0, "xin chào")], ma="vi"))
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        r = vd.dich_video("https://youtu.be/aircAruvnKk")
    assert r["ok"] is False and "đã là tiếng" in r["error"]


def test_khong_lay_duoc_phu_de_thi_khong_nem_ra_ngoai(monkeypatch):
    def _no(url, dich_sang="vi"):
        raise ValueError(vd.LOI_CHUA_CO_TIENG)

    monkeypatch.setattr(vd, "lay_phu_de", _no)
    r = vd.dich_video("https://youtu.be/aircAruvnKk")
    assert r["ok"] is False and "chưa làm" in r["error"]


def test_chua_cau_hinh_may_chu_dich(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "")
    r = vd.dich_video("https://youtu.be/aircAruvnKk")
    assert r["ok"] is False and "chưa cấu hình" in r["error"]


@pytest.mark.pure
def test_thu_tu_lay_dung_tieng_NOI_trong_video():
    """Video giảng bài tiếng Anh có phụ đề cộng đồng 31 thứ tiếng xếp theo bảng
    chữ cái. Lấy bản đầu danh sách là lấy bản tiếng Ả Rập rồi dịch tiếp sang
    tiếng Việt — dịch hai lần qua ba thứ tiếng (đo thật 13/08)."""
    ban = [("ar", False), ("bn", False), ("en", True), ("vi", False),
           ("zh", False)]
    assert vd._thu_tu(ban, "vi")[0] == "en"


@pytest.mark.pure
def test_thu_tu_uu_tien_ban_NGUOI_lam_hon_ban_tu_sinh():
    ban = [("en", True), ("en-US", False)]
    assert vd._thu_tu(ban, "vi")[0] == "en-US"


@pytest.mark.pure
def test_thu_tu_bo_ban_da_dich_san_xuong_cuoi():
    """Phụ đề tiếng Việt trên YouTube phần lớn là máy dịch lại từ gốc — lấy nó
    rồi dịch nữa là dịch hai lần."""
    assert vd._thu_tu([("vi", False), ("ko", True)], "vi")[0] == "ko"
    assert vd._thu_tu([("vi", False), ("ko", True)], "vi")[-1] == "vi"


@pytest.mark.pure
def test_thu_tu_khong_co_ban_tu_sinh_thi_uu_tien_tieng_anh():
    assert vd._thu_tu([("th", False), ("en", False), ("ru", False)], "vi")[0] == "en"


# ── Chuẩn hiển thị: đếm ký tự, cắt khung, mốc thời gian ─────────────────────


@pytest.mark.pure
def test_dem_ky_tu_chuan_hoa_unicode():
    """Cùng một dòng lưu hai dạng Unicode trông y hệt nhau nhưng len() chênh
    nhau rất nhiều — đếm trên dạng tách dấu sẽ cắt oan dòng hợp lệ."""
    import unicodedata

    nfc = "Nghiên cứu tiếng Việt đã được thực hiện"
    nfd = unicodedata.normalize("NFD", nfc)
    assert len(nfd) > len(nfc)          # len() thô: hai số khác nhau
    assert vd._dai(nfd) == vd._dai(nfc)  # _dai: bằng nhau


@pytest.mark.pure
def test_goi_dong_moi_DONG_deu_trong_gioi_han():
    """Cắt khung rồi mới ngắt dòng thì chỉ dòng TRÊN được ràng buộc, dòng dưới
    tràn — đo thật 13/08 lọt 43 dòng dài 43–45 ký tự."""
    chu = " ".join(["Việt"] * 60)
    khung = vd.goi_dong(chu)
    assert len(khung) > 1
    for k in khung:
        dong = k.split("\n")
        assert len(dong) <= vd.SO_DONG_TOI_DA
        assert all(vd._dai(d) <= vd.KY_TU_MOI_DONG for d in dong)
    assert " ".join(" ".join(khung).split()) == chu   # không mất chữ nào


@pytest.mark.pure
def test_goi_dong_cau_ngan_giu_mot_dong():
    assert vd.goi_dong("xin chào") == ["xin chào"]


@pytest.mark.pure
def test_goi_dong_tu_don_dai_hon_ca_dong_thi_de_nguyen():
    """Cắt giữa một URL hay tên hoá chất tệ hơn là để nó tràn dòng."""
    dai = "x" * 60
    assert vd.goi_dong(dai) == [dai]


@pytest.mark.pure
def test_cat_khung_khong_de_khung_qua_dai():
    """Khung gộp để dịch có thể 150 ký tự; hiển thị chỉ được 2×42."""
    chu = " ".join(["từ"] * 90)          # ~270 ký tự
    ra = vd.cat_khung([vd.Doan(0.0, 20.0, chu)])
    assert len(ra) > 1
    for d in ra:
        for dong in d.chu.split("\n"):
            assert vd._dai(dong) <= vd.KY_TU_MOI_DONG
    assert ra[0].bat_dau == 0.0
    assert all(ra[i].bat_dau <= ra[i + 1].bat_dau for i in range(len(ra) - 1))


@pytest.mark.pure
def test_bo_trung_phu_de_cuon():
    """Phụ đề tự sinh cuộn: mảnh sau lặp đuôi mảnh trước."""
    doan = [
        vd.Doan(0.0, 2.0, "hôm nay chúng ta"),
        vd.Doan(1.0, 3.0, "hôm nay chúng ta sẽ nói về"),
        vd.Doan(2.0, 4.0, "sẽ nói về mạng nơ-ron"),
    ]
    ra = vd.bo_trung(doan)
    ghep = " ".join(d.chu for d in ra)
    assert ghep.count("hôm nay chúng ta") == 1
    assert ghep.count("sẽ nói về") == 1
    assert "mạng nơ-ron" in ghep


@pytest.mark.pure
def test_chuan_thoi_gian_chua_khe_va_ep_toi_thieu():
    doan = [vd.Doan(0.0, 0.1, "ngắn"), vd.Doan(1.0, 1.2, "kế tiếp")]
    ra = vd.chuan_thoi_gian(doan)
    assert ra[0].ket_thuc <= ra[1].bat_dau - vd.KHE_TOI_THIEU + 1e-9
    assert ra[1].ket_thuc - ra[1].bat_dau >= vd.GIAY_TOI_THIEU - 1e-9


@pytest.mark.pure
def test_chuan_thoi_gian_khong_vuot_toi_da():
    ra = vd.chuan_thoi_gian([vd.Doan(0.0, 30.0, "x" * 80)])
    assert ra[0].ket_thuc - ra[0].bat_dau <= vd.GIAY_TOI_DA + 1e-9


@pytest.mark.pure
def test_soat_srt_bat_duoc_loi_that():
    xau = ("1\n00:00:00,000 --> 00:00:20,000\n" + "x" * 60 + "\n\n"
           "2\n00:00:10,000 --> 00:00:12,000\nchong khung\n")
    loi = vd.soat_srt(xau)
    assert any("ký tự" in x for x in loi)
    assert any("tối đa" in x for x in loi)
    assert any("chồng" in x for x in loi)


def test_srt_sinh_ra_dat_toan_bo_chuan(monkeypatch):
    """Vòng kiểm chứng thật: dịch xong thì tệp .srt phải đạt cả bốn luật."""
    doan = [vd.Doan(i * 6.0, i * 6.0 + 5.5,
                    "This is a fairly long sentence number %d that will need "
                    "splitting into several cues." % i) for i in range(6)]
    monkeypatch.setattr(vd, "lay_phu_de", _phu_de_gia(doan))
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        r = vd.dich_video("https://youtu.be/aircAruvnKk")
    assert r["ok"] is True
    assert vd.soat_srt(r["srt"].decode()) == []


# ── Từ khoá giảng dạy ───────────────────────────────────────────────────────


def _khung_day_cat_chop():
    """Rút từ video thật: mỗi từ được dạy phải đạt CẢ ba cửa — có tín hiệu
    giảng, ≥5 lần xuất hiện, ≥2 dạng biến hình."""
    return [
        vd.Doan(0, 4, 'Today we learn the word "cut" and the word "chop".'),
        vd.Doan(4, 8, "We could say that >> [snorts] >> I'm kind of chopping "
                      "the potatoes, kind of cutting them."),
        vd.Doan(8, 12, "If I was chopping them, it would be like this."),
        vd.Doan(12, 15, "So I am cutting the potatoes into small cubes."),
        vd.Doan(15, 18, "We say to cut something into pieces."),
        vd.Doan(18, 20, "You cut it twice, then chop the rest."),
        vd.Doan(20, 23, "One more cut here and one chop there."),
    ]


@pytest.mark.pure
def test_do_ra_tu_dang_duoc_giang():
    khoa = vd.tu_khoa_giang_day(_khung_day_cat_chop())
    assert "cut" in khoa and "chop" in khoa


@pytest.mark.pure
def test_video_thuong_khong_do_nham():
    """Video nấu ăn thường (không giảng từ) → tập rỗng, không chú thích bậy.
    Có cả từ lặp nhiều ("potatoes") lẫn câu cảm thán ngắn — hai bẫy đã dính."""
    nhom = [
        vd.Doan(0, 4, "Today I will cook a steak with potatoes."),
        vd.Doan(4, 8, "First, season the beef with salt and pepper."),
        vd.Doan(8, 12, "Then cut the potatoes and boil the potatoes well."),
        vd.Doan(12, 16, "Cook each side for three minutes."),
        vd.Doan(16, 18, "Beautiful."),
        vd.Doan(18, 20, "Oh. Trust me."),
        vd.Doan(20, 24, "The potatoes and the potato skins look great."),
    ]
    assert vd.tu_khoa_giang_day(nhom) == set()


@pytest.mark.pure
def test_goc_tu_quy_dang_bien_hinh():
    assert vd._goc_tu("cutting") == "cut"
    assert vd._goc_tu("chopping") == "chop"
    assert vd._goc_tu("chops") == "chop"
    assert vd._goc_tu("cuts") == "cut"


@pytest.mark.pure
def test_dinh_dung_DANG_xuat_hien_vao_ban_dich():
    khoa = {"chop", "cut"}
    ra = vd.dinh_tu_goc("I'm kind of chopping the potatoes, kind of cutting them.",
                        "Tôi đang cắt khoai tây, đang cắt chúng.", khoa)
    assert ra.endswith("[chopping, cutting]")
    ra2 = vd.dinh_tu_goc("So I am cutting the potatoes.",
                         "Vậy tôi đang cắt khoai tây.", khoa)
    assert ra2.endswith("[cutting]")


@pytest.mark.pure
def test_khung_khong_co_tu_khoa_thi_giu_nguyen():
    assert vd.dinh_tu_goc("Let's get started.", "Bắt đầu thôi.",
                          {"cut"}) == "Bắt đầu thôi."


@pytest.mark.pure
def test_bao_cao_doc_duoc():
    assert "Không dịch được" in vd.bao_cao({"ok": False, "error": "x"})
    ok = vd.bao_cao({"ok": True, "nguon": "en", "dich": "vi", "phut": 18,
                     "so_doan": 42})
    assert "en → vi" in ok and "18 phút" in ok and "42 khung" in ok
