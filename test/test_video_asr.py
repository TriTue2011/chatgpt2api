"""Bộ nghe tệp video — các phần THUẦN: cắt đoạn tiếng, gom khung, nhận đuôi tệp.

Không đụng sherpa/ffmpeg: phần đắt đã kiểm bằng đo thật trên máy chủ; ở đây
kiểm phần ghép số liệu — chỗ dễ hỏng âm thầm nhất.
"""

from __future__ import annotations

import numpy as np
import pytest

from services import video_asr as va


# ── Nhận đuôi tệp ───────────────────────────────────────────────────────────


@pytest.mark.pure
@pytest.mark.parametrize("ten", [
    "vlog_720p.mp4", "clip.MOV", "bai-giang.mkv", "podcast.mp3", "ghi-am.m4a",
    "YTSave_YouTube_Vlog_1kVWCjilNU8_002_720p.mp4",
])
def test_nhan_tep_nghe_duoc(ten):
    assert va.la_tep_nghe_duoc(ten) is True


@pytest.mark.pure
@pytest.mark.parametrize("ten", ["bao-cao.pdf", "anh.jpg", "tai-lieu.docx", "", "mp4"])
def test_khong_nham_tep_khac(ten):
    assert va.la_tep_nghe_duoc(ten) is False


# ── Cắt đoạn có tiếng theo năng lượng ───────────────────────────────────────


def _tieng(giay: float, rate: int = 16000, bien_do: float = 0.3):
    t = np.arange(int(giay * rate)) / rate
    return (bien_do * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _lang(giay: float, rate: int = 16000):
    return np.zeros(int(giay * rate), dtype=np.float32)


def test_cat_dung_hai_doan_tieng():
    mau = np.concatenate([_lang(2), _tieng(3), _lang(1.5), _tieng(4), _lang(1)])
    doan = va.cat_doan_tieng(mau, 16000)
    assert len(doan) == 2
    (b1, k1), (b2, k2) = doan
    assert abs(b1 - 2.0) < 0.3 and abs(k1 - 5.0) < 0.3
    assert abs(b2 - 6.5) < 0.3 and abs(k2 - 10.5) < 0.3


def test_nghi_lay_hoi_ngan_khong_bi_cat_doi():
    """Khoảng lặng dưới ngưỡng là người nói đang lấy hơi — vẫn một đoạn."""
    mau = np.concatenate([_tieng(2), _lang(0.2), _tieng(2)])
    assert len(va.cat_doan_tieng(mau, 16000)) == 1


def test_doan_qua_dai_bi_cat_nho():
    mau = _tieng(65)
    doan = va.cat_doan_tieng(mau, 16000)
    assert len(doan) >= 3
    assert all(k - b <= va.DOAN_TOI_DA + 0.01 for b, k in doan)


def test_im_lang_hoan_toan_khong_co_doan_nao():
    assert va.cat_doan_tieng(_lang(10), 16000) == []


def test_nen_on_to_van_tim_ra_tieng():
    """Ngưỡng phải TƯƠNG ĐỐI theo nền ồn của chính tệp: video quay điện thoại
    nền ồn 0.02 vẫn phải phân biệt được tiếng nói 0.3."""
    on = (0.02 * np.random.default_rng(7).standard_normal(16000 * 8)).astype(np.float32)
    mau = on.copy()
    mau[16000 * 3:16000 * 5] += _tieng(2)
    doan = va.cat_doan_tieng(mau, 16000)
    assert len(doan) == 1
    b, k = doan[0]
    assert abs(b - 3.0) < 0.4 and abs(k - 5.0) < 0.4


# ── Gom token thành khung phụ đề ────────────────────────────────────────────


@pytest.mark.pure
def test_gom_khung_tach_o_khoang_nghi_dai():
    tokens = [" HÔM", " NAY", " TRỜI", " ĐẸP", " CHÚNG", " TA", " ĐI", " CHƠI"]
    moc = [0.0, 0.3, 0.6, 0.9, 2.5, 2.8, 3.1, 3.4]   # nghỉ 1.6s sau "ĐẸP"
    ra = va.gom_khung(tokens, moc, goc=10.0)
    assert [c.chu for c in ra] == ["HÔM NAY TRỜI ĐẸP", "CHÚNG TA ĐI CHƠI"]
    assert ra[0].bat_dau == 10.0
    assert abs(ra[1].bat_dau - 12.5) < 1e-9          # goc + 2.5


@pytest.mark.pure
def test_gom_khung_khong_de_khung_dai_qua():
    n = 40
    tokens = [f" T{i}" for i in range(n)]
    moc = [i * 0.5 for i in range(n)]                # nói liền 20 giây
    ra = va.gom_khung(tokens, moc, goc=0.0)
    assert len(ra) >= 2
    assert all(c.ket_thuc - c.bat_dau <= va.KHUNG_TOI_DA_GIAY + 1.0 for c in ra)


@pytest.mark.pure
def test_gom_khung_lech_so_luong_thi_bo():
    assert va.gom_khung([" A"], [0.0, 1.0], 0.0) == []
    assert va.gom_khung([], [], 0.0) == []


# ── Dò ngôn ngữ bằng độ tự tin hai model ────────────────────────────────────
#
# Đo thật 13/08 trên máy chủ: model ĐÚNG ngôn ngữ tự tin ~-0.04, model SAI
# ~-0.5÷-0.6, nhạc nền ~-1.7 hoặc im lặng. Test dùng đúng các con số đo được.


def _lap_engines_gia(monkeypatch, ket_qua, ghi_nhan=None):
    """Cắm module engines GIẢ: ``ket_qua[lang] = (logprob, token mỗi cửa sổ)``."""
    import sys
    import threading
    import types

    eng = types.ModuleType("services.voice.engines")
    eng._stt_lock = threading.Lock()

    class _Rec:
        def __init__(self, lang):
            self.lang = lang

        def create_stream(self):
            lp, n = ket_qua[self.lang]

            def _nhan(rate, thu):
                if ghi_nhan is not None:
                    ghi_nhan.append((self.lang, thu))

            return types.SimpleNamespace(
                accept_waveform=_nhan,
                result=types.SimpleNamespace(ys_log_probs=[lp] * n))

        def decode_stream(self, stream):
            pass

    eng._get_recognizer = lambda lang: _Rec(lang)
    goi = types.ModuleType("services.voice")
    goi.engines = eng
    monkeypatch.setitem(sys.modules, "services.voice", goi)
    monkeypatch.setitem(sys.modules, "services.voice.engines", eng)


_RATE_GIA = 100  # đủ để chỉ số lát cắt ra nguyên, mảng test bé


def _doan_deu(so: int):
    """``so`` đoạn tiếng, mỗi đoạn 1 giây, nối liền nhau."""
    return [(float(i), float(i + 1)) for i in range(so)]


def test_chon_en_khi_model_en_tu_tin_hon(monkeypatch):
    _lap_engines_gia(monkeypatch, {"vi": (-0.518, 4), "en": (-0.042, 4)})
    mau = np.zeros(40 * _RATE_GIA, dtype=np.float32)
    assert va._chon_ngon_ngu(mau, _RATE_GIA, _doan_deu(40)) == "en"


def test_chon_vi_khi_model_vi_tu_tin_hon(monkeypatch):
    _lap_engines_gia(monkeypatch, {"vi": (-0.043, 4), "en": (-0.621, 6)})
    mau = np.zeros(40 * _RATE_GIA, dtype=np.float32)
    assert va._chon_ngon_ngu(mau, _RATE_GIA, _doan_deu(40)) == "vi"


def test_suyt_soat_thi_uu_tien_tieng_viet(monkeypatch):
    """Video Việt chêm từ Anh là chuyện thường — en phải hơn RÕ mới thắng."""
    _lap_engines_gia(monkeypatch, {"vi": (-0.35, 4), "en": (-0.30, 4)})
    mau = np.zeros(40 * _RATE_GIA, dtype=np.float32)
    assert va._chon_ngon_ngu(mau, _RATE_GIA, _doan_deu(40)) == "vi"


def test_ca_hai_cam_lang_thi_mac_dinh_vi(monkeypatch):
    _lap_engines_gia(monkeypatch, {"vi": (0.0, 0), "en": (0.0, 0)})
    mau = np.zeros(10 * _RATE_GIA, dtype=np.float32)
    assert va._chon_ngon_ngu(mau, _RATE_GIA, _doan_deu(10)) == "vi"


def test_vi_cam_en_noi_thi_chon_en(monkeypatch):
    _lap_engines_gia(monkeypatch, {"vi": (0.0, 0), "en": (-0.05, 3)})
    mau = np.zeros(40 * _RATE_GIA, dtype=np.float32)
    assert va._chon_ngon_ngu(mau, _RATE_GIA, _doan_deu(40)) == "en"


def test_en_it_token_qua_khong_du_tin(monkeypatch):
    """1 cửa sổ × 4 token < ngưỡng 5 — dù tự tin cũng chưa đủ bằng chứng."""
    _lap_engines_gia(monkeypatch, {"vi": (0.0, 0), "en": (-0.05, 4)})
    mau = np.zeros(1 * _RATE_GIA, dtype=np.float32)
    assert va._chon_ngon_ngu(mau, _RATE_GIA, _doan_deu(1)) == "vi"


def test_mau_lay_giua_than_video_khong_dinh_nhac_mo_man(monkeypatch):
    """Video Zootopia hỏng vì lấy mẫu 20s đầu toàn nhạc — mẫu phải rải từ 1/4
    danh sách đoạn trở đi, không đụng phần mở màn."""
    ghi: list = []
    _lap_engines_gia(monkeypatch, {"vi": (-0.5, 4), "en": (-0.05, 4)},
                     ghi_nhan=ghi)
    mau = np.arange(40 * _RATE_GIA, dtype=np.float32)   # giá trị = vị trí
    va._chon_ngon_ngu(mau, _RATE_GIA, _doan_deu(40))
    assert ghi, "phải có cửa sổ mẫu"
    # 40 đoạn → mốc 1/4 là đoạn 10 → mọi lát cắt bắt đầu từ giây 10 trở đi.
    assert min(thu[0] for _, thu in ghi) >= 10 * _RATE_GIA


def test_ung_vien_theo_cap_viet_trung(monkeypatch):
    """Người dùng chọn cặp Việt↔Trung → so vi với zh (không phải en),
    model zh tự tin hơn thì nghe bằng zh."""
    _lap_engines_gia(monkeypatch, {"vi": (-0.5, 4), "zh": (-0.05, 4)})
    mau = np.zeros(40 * _RATE_GIA, dtype=np.float32)
    assert va._chon_ngon_ngu(mau, _RATE_GIA, _doan_deu(40),
                             ung_vien=("vi", "zh")) == "zh"


def test_ung_vien_chua_tai_model_thi_ve_vi(monkeypatch):
    """Chọn cặp Việt↔Nhật nhưng model ja CHƯA tải (raise) → rơi về vi,
    không nổ."""
    import sys

    def _khong_co(lang):
        raise RuntimeError("chưa tải model")

    _lap_engines_gia(monkeypatch, {"vi": (-0.3, 9)})
    eng = sys.modules["services.voice.engines"]
    goc = eng._get_recognizer
    eng._get_recognizer = lambda lang: goc(lang) if lang == "vi" else _khong_co(lang)
    mau = np.zeros(10 * _RATE_GIA, dtype=np.float32)
    assert va._chon_ngon_ngu(mau, _RATE_GIA, _doan_deu(10),
                             ung_vien=("vi", "ja")) == "vi"


def test_doan_it_khong_nghe_trung_lap(monkeypatch):
    """1 đoạn duy nhất mà 3 mốc lấy mẫu đều trỏ vào — chỉ nghe MỘT lần/model."""
    ghi: list = []
    _lap_engines_gia(monkeypatch, {"vi": (-0.04, 9), "en": (-0.6, 9)},
                     ghi_nhan=ghi)
    mau = np.zeros(5 * _RATE_GIA, dtype=np.float32)
    assert va._chon_ngon_ngu(mau, _RATE_GIA, [(0.0, 5.0)]) == "vi"
    assert len([1 for lang, _ in ghi if lang == "vi"]) == 1
    assert len([1 for lang, _ in ghi if lang == "en"]) == 1


# ── dich_tep_video: hợp đồng, không đụng sherpa ─────────────────────────────


@pytest.fixture(autouse=True)
def _co_may_chu_dich(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "http://vn-translate:5000")
    monkeypatch.setitem(config.data, "translate_api_key", "")


def test_dich_tep_video_ra_srt_dat_chuan(monkeypatch):
    from test._fakes import FakeTranslate, install_translate
    from services import video_dich as vd

    def _nghe_gia(duong, tran_giay=0, **kw):
        return ([va.Cau(0.0, 2.0, "Hôm nay chúng ta nấu bít tết"),
                 va.Cau(2.5, 5.0, "Đầu tiên ướp thịt với muối và tiêu")],
                "vi", 4.5)

    monkeypatch.setattr(vd, "dich_tep_video", vd.dich_tep_video)  # giữ nguyên
    import services.video_asr as va_mod
    monkeypatch.setattr(va_mod, "nghe_tep", _nghe_gia)
    with install_translate(FakeTranslate(lang="vi", codes=("en", "vi"))):
        r = vd.dich_tep_video("/tmp/x.mp4", "x.mp4")
    assert r["ok"] is True
    assert r["nguon"] == "vi" and r["dich"] == "en"   # vi → mặc định dịch sang en
    assert "en:" in r["chu"]
    assert vd.soat_srt(r["srt"].decode()) == []


def test_dich_tep_video_cung_ngon_ngu_thi_tra_ban_chep(monkeypatch):
    """Video tiếng Việt, đích tiếng Việt → bản CHÉP LỜI, không gọi máy dịch."""
    from test._fakes import FakeTranslate, install_translate
    from services import video_dich as vd
    import services.video_asr as va_mod

    def _nghe_gia(duong, tran_giay=0, **kw):
        return [va.Cau(0.0, 2.0, "Xin chào cả nhà")], "vi", 2.0

    monkeypatch.setattr(va_mod, "nghe_tep", _nghe_gia)
    with install_translate(FakeTranslate(lang="vi", codes=("en", "vi"))) as fake:
        r = vd.dich_tep_video("/tmp/x.mp4", "x.mp4", target="vi")
    assert r["ok"] is True and r["dich"] == "vi"
    assert "Xin chào cả nhà" in r["chu"]


def test_dich_tep_video_loi_nghe_khong_nem_ra_ngoai(monkeypatch):
    from services import video_dich as vd
    import services.video_asr as va_mod

    def _no(duong, tran_giay=0, **kw):
        raise va_mod.LoiNghe("không thấy tiếng nói nào trong tệp")

    monkeypatch.setattr(va_mod, "nghe_tep", _no)
    r = vd.dich_tep_video("/tmp/x.mp4", "x.mp4")
    assert r["ok"] is False and "tiếng nói" in r["error"]
