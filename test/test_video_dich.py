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
def test_srt_dung_khuon_va_danh_so_tu_1():
    srt = vd.lam_srt([vd.Doan(0.0, 2.0, "câu một"), vd.Doan(2.0, 4.25, "câu hai")])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,000\ncâu một\n")
    assert "2\n00:00:02,000 --> 00:00:04,250\ncâu hai\n" in srt


@pytest.mark.pure
def test_khung_qua_ngan_duoc_keo_dai_toi_thieu():
    """Phụ đề có mốc kết thúc trùng mốc bắt đầu thì trình phát bỏ qua."""
    srt = vd.lam_srt([vd.Doan(5.0, 5.0, "nhanh")])
    assert "00:00:05,000 --> 00:00:05,500" in srt


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
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,000\nvi:Hello there.")
    assert "vi:This is a test." in srt


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


@pytest.mark.pure
def test_bao_cao_doc_duoc():
    assert "Không dịch được" in vd.bao_cao({"ok": False, "error": "x"})
    ok = vd.bao_cao({"ok": True, "nguon": "en", "dich": "vi", "phut": 18,
                     "so_doan": 42})
    assert "en → vi" in ok and "18 phút" in ok and "42 khung" in ok
