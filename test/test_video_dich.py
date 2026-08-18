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
def test_khong_gop_loi_thoai_qua_ranh_canh_vision():
    """Đổi cảnh hay đổi nhân vật: không đưa hai vế sang máy dịch như một câu."""
    doan = [vd.Doan(0.0, 2.0, "He opens the door"),
            vd.Doan(2.0, 4.0, "and she walks in.")]
    ra = vd.gop_doan(doan, ranh_canh=[2.0])
    assert [d.chu for d in ra] == ["He opens the door", "and she walks in."]


@pytest.mark.pure
def test_vision_hai_phu_nu_chi_sua_sang_xung_ho_trung_tinh(monkeypatch):
    """Biết giới tính không đủ để đoán vai vế chị/em/cô/bà."""
    monkeypatch.setattr(vd.ts, "translate_batch", lambda *_a:
                        ["Tôi nói chuyện với anh được không? Một mình?"])

    r = vd._dich_va_dong_goi(
        [vd.Doan(0.0, 3.0, "Can I talk to you? Alone?")], "en", "vi", 3.0,
        vision={"engine": "gpu", "ngu_canh_canh": [{
            "bat_dau": 0.0, "ket_thuc": 3.0,
            "mo_ta": "Hai phụ nữ đang nói chuyện.",
        }]},
    )

    assert "Tôi nói chuyện với bạn được không?" in r["chu"]


@pytest.mark.pure
def test_vision_noi_ro_hai_chi_em_moi_duoc_dung_chi(monkeypatch):
    monkeypatch.setattr(vd.ts, "translate_batch", lambda *_a:
                        ["Tôi nói chuyện với anh được không?"])

    r = vd._dich_va_dong_goi(
        [vd.Doan(0.0, 3.0, "Can I talk to you?")], "en", "vi", 3.0,
        vision={"engine": "gpu", "ngu_canh_canh": [{
            "bat_dau": 0.0, "ket_thuc": 3.0,
            "mo_ta": "Hai chị em đang nói chuyện.",
        }]},
    )

    assert "Tôi nói chuyện với chị được không?" in r["chu"]


@pytest.mark.pure
def test_phu_de_hai_phu_nu_loc_nhan_am_thanh_va_giu_xung_ho_trung_tinh(monkeypatch):
    """Không để nhãn ASR và lối xưng hô thô lọt vào phụ đề phim."""
    monkeypatch.setattr(vd.ts, "translate_batch", lambda *_a: [
        "Không, anh không thể, và tôi nghĩ anh nên đi. "
        "Tao đã làm gì mày? [think]",
    ])

    r = vd._dich_va_dong_goi(
        [vd.Doan(0.0, 6.0, "No, you can't. What did I ever do to you? [think]")],
        "en", "vi", 6.0,
        vision={"engine": "gpu", "ngu_canh_canh": [{
            "bat_dau": 0.0, "ket_thuc": 6.0,
            "mo_ta": "Hai phụ nữ đang nói chuyện.",
        }]},
    )

    assert "bạn không thể" in r["chu"]
    assert "Tôi đã làm gì với bạn?" in r["chu"]
    assert "[think]" not in r["chu"]
    assert "Tao" not in r["chu"] and "mày" not in r["chu"]


@pytest.mark.pure
def test_chi_bo_nhan_am_thanh_da_biet_khong_xoa_chu_trong_ngoac_vuong():
    assert vd.loc_nhan_khong_phai_loi("[think] Mã cửa [A-12]") == "Mã cửa [A-12]"


def test_may_dich_loi_van_xuat_srt_loi_goc(monkeypatch):
    """ASR xong thì lỗi dịch không được làm người dùng mất toàn bộ SRT."""
    def _loi(*_a, **_k):
        raise vd.ts.LoiDich("CPU dịch đang khởi động")

    monkeypatch.setattr(vd.ts, "translate_batch", _loi)
    r = vd._dich_va_dong_goi(
        [vd.Doan(0.0, 2.0, "Hello there.")], "en", "vi", 2.0,
    )

    assert r["ok"] is True
    assert r["dich"] == "en"
    assert "Hello there." in r["srt"].decode()
    assert "bản gốc" in r["canh_bao_dich"]


def test_tep_srt_khong_co_may_dich_van_tra_ban_goc(monkeypatch, tmp_path):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "")
    tep = tmp_path / "goc.srt"
    tep.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello there.\n", encoding="utf-8")

    r = vd.dich_tep_phu_de(str(tep), "goc.srt", target="vi")

    assert r["ok"] is True
    assert r["dich"] == "goc"
    assert "Hello there." in r["srt"].decode()
    assert "bản gốc" in r["canh_bao_dich"]


@pytest.mark.pure
def test_vision_khong_chac_chan_giu_nguyen_xung_ho(monkeypatch):
    """Không được đổi xưng hô khi frame có cả nam lẫn nữ hoặc không rõ."""
    monkeypatch.setattr(vd.ts, "translate_batch", lambda *_a:
                        ["Tôi nói chuyện với anh được không?"])

    r = vd._dich_va_dong_goi(
        [vd.Doan(0.0, 3.0, "Can I talk to you?")], "en", "vi", 3.0,
        vision={"engine": "gpu", "ngu_canh_canh": [{
            "bat_dau": 0.0, "ket_thuc": 3.0,
            "mo_ta": "Một nam và một nữ đang nói chuyện.",
        }]},
    )

    assert r["chu"] == "Tôi nói chuyện với anh được không?"


@pytest.mark.pure
def test_vision_chi_sua_xung_ho_o_dung_canh(monkeypatch):
    """Cảnh hai phụ nữ không được đổi đại từ của cảnh kế có nam giới."""
    monkeypatch.setattr(vd.ts, "translate_batch", lambda *_a: [
        "Tôi nói chuyện với anh được không?",
        "Anh nên đi.",
    ])

    r = vd._dich_va_dong_goi(
        [vd.Doan(0.0, 2.0, "Can I talk to you?"),
         vd.Doan(10.0, 12.0, "You should leave.")],
        "en", "vi", 12.0,
        vision={"engine": "gpu", "ngu_canh_canh": [
            {"bat_dau": 0.0, "ket_thuc": 2.0,
             "mo_ta": "Hai phụ nữ đang nói chuyện."},
            {"bat_dau": 10.0, "ket_thuc": 12.0,
             "mo_ta": "Một người đàn ông đang nói chuyện."},
        ]},
        ranh_canh=[2.0],
    )

    assert "Tôi nói chuyện với bạn được không?" in r["chu"]
    assert "Anh nên đi." in r["chu"]


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
def test_srt_chu_tren_chen_the_an8_moi_khung():
    """Video có chữ in cứng ở đáy hình → bản {\\an8} đẩy phụ đề lên mép trên
    (ảnh chủ máy gửi 13/08: hai lớp chữ đè nhau không đọc nổi)."""
    srt = ("1\n00:00:01,000 --> 00:00:02,000\nDòng một\nDòng hai\n\n"
           "2\n00:00:03,000 --> 00:00:04,000\nKhung hai\n")
    ra = vd.srt_chu_tren(srt)
    khoi = ra.strip().split("\n\n")
    assert khoi[0].split("\n")[2] == "{\\an8}Dòng một"
    assert khoi[0].split("\n")[3] == "Dòng hai"      # chỉ dòng đầu mang thẻ
    assert khoi[1].split("\n")[2] == "{\\an8}Khung hai"
    # Bỏ thẻ đi thì phải y nguyên bản gốc — không được đổi gì khác.
    assert ra.replace("{\\an8}", "").strip() == srt.strip()


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


def test_tiktok_noi_ro_la_khong_co_phu_de_san(monkeypatch):
    """Lỗi phải nêu ĐÚNG nguyên nhân để tầng gọi chữa được.

    ĐỔI 18/08: trước đây thông báo ghi "phần đó chưa làm" — nay làm rồi
    (services.video_tai tải hình về, dich_tep_video tự nghe), nên tầng gọi
    nhận ra bằng ``thieu_phu_de_san`` rồi tự chữa thay vì báo lỗi cho xong.
    """
    r = vd.dich_video("https://www.tiktok.com/@ai/video/7300000000000000000")
    assert r["ok"] is False and vd.thieu_phu_de_san(r)
    assert "không có phụ đề sẵn" in r["error"]


def test_loi_khac_khong_bi_nham_la_thieu_phu_de():
    """"Video dài quá mức" mà cũng tải về nghe thì vừa lâu vừa vẫn hỏng."""
    assert not vd.thieu_phu_de_san({"ok": False, "error": "video dài 200 phút"})


def test_video_qua_dai_thi_tu_choi(monkeypatch):
    monkeypatch.setattr(vd, "lay_phu_de", _phu_de_gia([
        vd.Doan(0.0, vd.TRAN_GIAY + 600, "quá dài"),
    ]))
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        r = vd.dich_video("https://youtu.be/aircAruvnKk")
    assert r["ok"] is False and "quá mức" in r["error"]


def test_phu_de_tieng_viet_mac_dinh_dich_sang_anh(monkeypatch):
    """Không chỉ định đích thì theo CẶP Việt ↔ Anh — phụ đề vi dịch sang en,
    nhất quán với /dich chữ (đổi hành vi 14/08: trước đây báo lỗi vô ích
    "phụ đề đã là tiếng vi")."""
    monkeypatch.setattr(vd, "lay_phu_de", _phu_de_gia(
        [vd.Doan(0.0, 2.0, "xin chào")], ma="vi"))
    with install_translate(FakeTranslate(lang="vi", codes=("en", "vi"))):
        r = vd.dich_video("https://youtu.be/aircAruvnKk")
    assert r["ok"] is True and r["nguon"] == "vi" and r["dich"] == "en"


def test_phu_de_da_dung_tieng_dich_chi_dinh_tro_thi_bao(monkeypatch):
    """Chỉ định TRƠ đúng tiếng của phụ đề thì vẫn phải báo — không có gì để dịch."""
    monkeypatch.setattr(vd, "lay_phu_de", _phu_de_gia(
        [vd.Doan(0.0, 2.0, "xin chào")], ma="vi"))
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        r = vd.dich_video("https://youtu.be/aircAruvnKk", target="vi")
    assert r["ok"] is False and "đã là tiếng" in r["error"]


def test_khong_lay_duoc_phu_de_thi_khong_nem_ra_ngoai(monkeypatch):
    def _no(url, dich_sang="vi"):
        raise ValueError(vd.LOI_CHUA_CO_TIENG)

    monkeypatch.setattr(vd, "lay_phu_de", _no)
    r = vd.dich_video("https://youtu.be/aircAruvnKk")
    assert r["ok"] is False and "không có phụ đề sẵn" in r["error"]


def test_chua_cau_hinh_may_chu_dich_van_xuat_phu_de_goc(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "")
    monkeypatch.setattr(vd, "lay_phu_de", _phu_de_gia(
        [vd.Doan(0.0, 2.0, "Hello there.")], ma="en"))
    r = vd.dich_video("https://youtu.be/aircAruvnKk")
    assert r["ok"] is True
    assert r["dich"] == "en"
    assert "bản gốc" in r["canh_bao_dich"]


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


@pytest.mark.pure
@pytest.mark.parametrize("target, cho_doi", [
    ("cap:zh", ("vi", "zh")), ("cap:ja", ("vi", "ja")),
    ("cap:ko", ("vi", "ko")), ("cap:en", ("vi", "en")),
])
def test_ung_vien_nghe_theo_cap_nguoi_dung_chon(target, cho_doi):
    """Chọn CẶP thì chỉ so hai tiếng đó — không đi dò cả 5 (chậm, dễ sai)."""
    assert vd._ung_vien_nghe(target) == cho_doi


@pytest.mark.pure
@pytest.mark.parametrize("target", ["", "en", "vi"])
def test_ung_vien_nghe_khong_neu_cap_thi_theo_cai_dat(target, monkeypatch):
    """Không nêu cặp → lấy nhóm tiếng của TÍNH NĂNG phụ đề (đè được theo
    thread). Chưa cấu hình gì thì về ("vi","en") như cũ."""
    from services.config import config
    monkeypatch.setitem(config.data, "voice", {})
    assert vd._ung_vien_nghe(target) == ("vi", "en")
    monkeypatch.setitem(config.data, "voice",
                        {"dung_cho": {"phu_de": {"stt_tieng": "vi,ja,ko"}}})
    assert vd._ung_vien_nghe(target) == ("vi", "ja", "ko")


# ── Tệp phụ đề có sẵn (.srt/.vtt) ───────────────────────────────────────────


@pytest.mark.pure
def test_doc_phu_de_srt_du_kieu():
    """SRT chuẩn: số thứ tự, khối nhiều dòng, thẻ <i> và {\\an8} phải bị bóc."""
    raw = ("﻿1\n00:00:01,500 --> 00:00:03,000\n<i>Hello</i> there\n\n"
           "2\n00:00:03,500 --> 00:00:05,000\n{\\an8}Line one\nLine two\n\n"
           "khối hỏng không có mốc\n\n"
           "3\n00:00:07,000 --> 00:00:06,000\nmốc ngược bị bỏ\n")
    doan = vd.doc_phu_de(raw)
    assert [(d.bat_dau, d.chu) for d in doan] == [
        (1.5, "Hello there"), (3.5, "Line one Line two")]


@pytest.mark.pure
def test_doc_phu_de_vtt():
    """VTT: header WEBVTT, mili-giây dùng dấu chấm, có thể vắng phần giờ."""
    raw = ("WEBVTT\n\n00:01.000 --> 00:02.500\nXin chào\n\n"
           "01:00:03.000 --> 01:00:04.000\nCâu hai\n")
    doan = vd.doc_phu_de(raw)
    assert [(d.bat_dau, d.ket_thuc, d.chu) for d in doan] == [
        (1.0, 2.5, "Xin chào"), (3603.0, 3604.0, "Câu hai")]


@pytest.mark.pure
def test_la_tep_phu_de():
    assert vd.la_tep_phu_de("phim.srt") and vd.la_tep_phu_de("PHIM.VTT")
    assert not vd.la_tep_phu_de("phim.ass") and not vd.la_tep_phu_de("phim.mp4")


def test_dich_tep_phu_de_ra_srt_dat_chuan(tmp_path, monkeypatch):
    tep = tmp_path / "phim.srt"
    tep.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello there.\n\n"
                   "2\n00:00:02,000 --> 00:00:04,000\nThis is a test.\n",
                   encoding="utf-8")
    with install_translate(FakeTranslate(lang="en", codes=("en", "vi"))):
        r = vd.dich_tep_phu_de(str(tep), "phim.srt")
    assert r["ok"] is True
    assert r["nguon"] == "en" and r["dich"] == "vi"
    assert r["ten"] == "phu-de.vi.srt"
    assert vd.soat_srt(r["srt"].decode()) == []


def test_dich_tep_phu_de_khong_doc_duoc_thi_bao(tmp_path, monkeypatch):
    tep = tmp_path / "rong.srt"
    tep.write_text("chỉ có chữ, không có mốc thời gian nào", encoding="utf-8")
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        r = vd.dich_tep_phu_de(str(tep), "rong.srt")
    assert r["ok"] is False and "không đọc được khung" in r["error"]


@pytest.mark.pure
def test_chep_loi_giu_nguyen_tieng_goc(monkeypatch):
    """Chọn «3. GIỮ nguyên tiếng gốc» → đích = chính tiếng nguồn, KHÔNG dịch."""
    monkeypatch.setattr(vd, "lay_phu_de", _phu_de_gia(
        [vd.Doan(0.0, 2.0, "Hello there.")], ma="en"))
    with install_translate(FakeTranslate(lang="en", codes=("en", "vi"))) as fake:
        r = vd.dich_video("https://youtu.be/aircAruvnKk", chep_loi=True)
    assert r["ok"] is True and r["nguon"] == "en" and r["dich"] == "en"
    assert "Hello there." in r["chu"]      # nguyên văn, không có tiền tố "vi:"
    assert fake.da_gui == []               # KHÔNG gọi máy dịch lượt nào
