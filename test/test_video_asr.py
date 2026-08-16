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


def test_doan_dai_co_chong_len_de_khong_cup_tu_o_mep_cat():
    """Model nghe từng đoạn cần thấy lại một ít tiếng quanh biên 28 giây."""
    doan = va.cat_doan_tieng(_tieng(65), 16000)
    assert any(b_sau < k_truoc
               for (_, k_truoc), (b_sau, _) in zip(doan, doan[1:]))


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


def test_tieng_nho_hon_san_cu_van_duoc_dua_vao_stt():
    """File quay nhỏ tiếng vẫn cần thử STT; sàn 0.008 cũ bỏ trắng cả tệp."""
    doan = va.cat_doan_tieng(_tieng(3, bien_do=0.006), 16000)
    assert len(doan) == 1
    b, k = doan[0]
    assert b < 0.3 and k > 2.7


def test_gpu_co_chu_nhung_bo_sot_mot_doan_tieng_thi_nghe_bu_tai_cho(monkeypatch):
    """Một kết quả GPU không rỗng chưa có nghĩa là đã nghe hết cả tệp.

    Đây là đúng dạng lỗi người dùng gặp: Whisper trả được câu đầu nên đường cũ
    coi là xong, trong khi cụm thoại sau hoàn toàn biến mất khỏi SRT.
    """
    import sys
    import threading
    import types

    from services import nghe_gpu

    eng = types.ModuleType("services.voice.engines")
    eng._stt_lock = threading.Lock()
    eng._get_recognizer = lambda _lang: object()
    eng._normalize_stt = lambda text: str(text).strip()
    voice = types.ModuleType("services.voice")
    voice.engines = eng
    monkeypatch.setitem(sys.modules, "services.voice", voice)
    monkeypatch.setitem(sys.modules, "services.voice.engines", eng)
    monkeypatch.setattr(va, "_boc_tieng", lambda _path: "/tmp/nghe-gia.wav")
    monkeypatch.setattr(va, "_doc_wav", lambda _path: (np.zeros(600), 100))
    monkeypatch.setattr(va, "cat_doan_tieng", lambda *_a: [(0.0, 2.0), (4.0, 6.0)])
    monkeypatch.setattr(va, "doan_nang_luong_chi_tiet",
                        lambda *_a: [(0.0, 0.55), (4.0, 6.0)])
    monkeypatch.setattr(va, "_chon_ngon_ngu", lambda *_a: "en")
    monkeypatch.setattr(nghe_gpu, "dung_duoc", lambda _lang: True)
    monkeypatch.setattr(nghe_gpu, "nghe", lambda *_a:
                        ([" First", " sentence"], [0.0, 0.2]))
    monkeypatch.setattr(va, "_nghe_mot_doan", lambda *_a:
                        ([" Second", " sentence", " completed", " now"],
                         [0.0, 0.5, 1.0, 1.5]))

    kq = va.nghe_tep("/tmp/phim.mp4", ung_vien=("en",), chi_tiet=True)

    assert [c.chu for c in kq.cau] == ["First sentence", "Second sentence completed now"]
    assert kq.engine == "gpu_recovered"
    assert "bù" in kq.canh_bao.lower()


def test_gpu_bo_sot_cau_ngan_hon_bon_giay_van_phai_nghe_bu(monkeypatch):
    """Câu 2–3 giây có thể bị VAD của Whisper bỏ, không được lọt qua ngưỡng 4s.

    Đây là dạng còn lại của lỗi 1:30/2:23: GPU có câu ngay trước đó nên kết
    quả không rỗng, nhưng một lượt thoại ngắn trong cùng cụm năng lượng biến
    mất hoàn toàn.
    """
    import sys
    import threading
    import types

    from services import nghe_gpu

    eng = types.ModuleType("services.voice.engines")
    eng._stt_lock = threading.Lock()
    eng._get_recognizer = lambda _lang: object()
    eng._normalize_stt = lambda text: str(text).strip()
    voice = types.ModuleType("services.voice")
    voice.engines = eng
    monkeypatch.setitem(sys.modules, "services.voice", voice)
    monkeypatch.setitem(sys.modules, "services.voice.engines", eng)
    monkeypatch.setattr(va, "_boc_tieng", lambda _path: "/tmp/nghe-gia.wav")
    monkeypatch.setattr(va, "_doc_wav", lambda _path: (np.zeros(300), 100))
    monkeypatch.setattr(va, "cat_doan_tieng", lambda *_a: [(0.0, 3.0)])
    monkeypatch.setattr(va, "doan_nang_luong_chi_tiet",
                        lambda *_a: [(0.0, 0.55), (0.8, 3.0)])
    monkeypatch.setattr(va, "_chon_ngon_ngu", lambda *_a: "en")
    monkeypatch.setattr(nghe_gpu, "dung_duoc", lambda _lang: True)
    monkeypatch.setattr(nghe_gpu, "nghe", lambda *_a:
                        ([" First", " sentence"], [0.0, 0.2]))
    monkeypatch.setattr(va, "_nghe_mot_doan", lambda *_a:
                        ([" Missing", " line", " continues", " now"],
                         [0.0, 0.5, 1.0, 1.85]))

    kq = va.nghe_tep("/tmp/phim.mp4", ung_vien=("en",), chi_tiet=True)

    assert " ".join(c.chu for c in kq.cau) == "First sentence Missing line continues now"
    assert kq.engine == "gpu_recovered"


def test_gpu_bo_sot_nhung_local_loi_van_bao_phu_de_chua_du(monkeypatch):
    """Đã có chữ từ GPU thì lỗi đường bù không được làm mất cả SRT."""
    import sys
    import threading
    import types

    from services import nghe_gpu

    eng = types.ModuleType("services.voice.engines")
    eng._stt_lock = threading.Lock()
    eng._get_recognizer = lambda _lang: object()
    eng._normalize_stt = lambda text: str(text).strip()
    voice = types.ModuleType("services.voice")
    voice.engines = eng
    monkeypatch.setitem(sys.modules, "services.voice", voice)
    monkeypatch.setitem(sys.modules, "services.voice.engines", eng)
    monkeypatch.setattr(va, "_boc_tieng", lambda _path: "/tmp/nghe-gia.wav")
    monkeypatch.setattr(va, "_doc_wav", lambda _path: (np.zeros(600), 100))
    monkeypatch.setattr(va, "cat_doan_tieng", lambda *_a: [(0.0, 2.0), (4.0, 6.0)])
    monkeypatch.setattr(va, "doan_nang_luong_chi_tiet",
                        lambda *_a: [(0.0, 0.55), (4.0, 6.0)])
    monkeypatch.setattr(va, "_chon_ngon_ngu", lambda *_a: "en")
    monkeypatch.setattr(nghe_gpu, "dung_duoc", lambda _lang: True)
    monkeypatch.setattr(nghe_gpu, "nghe", lambda *_a:
                        ([" First", " sentence"], [0.0, 0.2]))
    monkeypatch.setattr(va, "_nghe_mot_doan", lambda *_a:
                        (_ for _ in ()).throw(RuntimeError("model local lỗi")))

    kq = va.nghe_tep("/tmp/phim.mp4", ung_vien=("en",), chi_tiet=True)

    assert [c.chu for c in kq.cau] == ["First sentence"]
    assert kq.engine == "gpu_incomplete"
    assert "cần kiểm tra" in kq.canh_bao


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


def test_dich_tep_video_bao_tien_do_tung_cong_doan(monkeypatch):
    from test._fakes import FakeTranslate, install_translate
    from services import video_dich as vd
    import services.video_asr as va_mod

    monkeypatch.setattr(va_mod, "nghe_tep", lambda *_a, **_kw:
                        ([va.Cau(0.0, 2.0, "Hello there.")], "en", 2.0))
    tien_do: list[tuple[str, int | None, bool]] = []
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        r = vd.dich_tep_video("/tmp/x.mp4", "x.mp4", target="vi",
                              tien_do=lambda *a: tien_do.append(a))

    assert r["ok"] is True
    assert [x[0] for x in tien_do] == [
        "đang bóc tiếng và nhận lời thoại…",
        "đã nhận lời thoại, đang phân tích cảnh…",
        "đang dịch phụ đề (1/1)…",
        "đang đóng tệp SRT…",
    ]
    # Phần trăm phải TĂNG DẦN và chỉ vắng ở giai đoạn nghe — Whisper GPU nhận cả
    # tệp trong một lần gọi nên không có gì để đếm bên trong.
    assert tien_do[0][1] is None
    so = [x[1] for x in tien_do[1:]]
    assert all(isinstance(x, int) for x in so) and so == sorted(so)
    assert so[-1] < 100                      # 100 chỉ đặt khi việc đã xong hẳn


def test_kenh_chat_chi_nhan_moc_chuyen_giai_doan(monkeypatch):
    """Zalo không có thanh tiến độ: báo từng lô dịch là spam cả chục tin."""
    from test._fakes import FakeTranslate, install_translate
    from services import video_dich as vd
    import services.video_asr as va_mod

    monkeypatch.setattr(va_mod, "nghe_tep", lambda *_a, **_kw:
                        ([va.Cau(i * 2.0, i * 2.0 + 1.5, f"Line {i}.")
                          for i in range(vd.LO_MOI_LUOT * 3)], "en", 90.0))
    tin: list[str] = []
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        r = vd.dich_tep_video(
            "/tmp/x.mp4", "x.mp4", target="vi",
            tien_do=lambda buoc, _pt, moc: moc and tin.append(buoc))

    assert r["ok"] is True
    assert tin == [
        "đang bóc tiếng và nhận lời thoại…",
        "đã nhận lời thoại, đang phân tích cảnh…",
        "đang dịch phụ đề (1/3)…",
    ]


def test_dich_tep_video_ghi_ro_nguon_nghe_de_kiem_chung_chat_luong(monkeypatch):
    """Phụ đề tiếng Anh phải nói rõ đã qua Whisper GPU hay chưa.

    Không có dấu vết này, một GPU tắt sẽ rơi im lặng về Parakeet tại chỗ và
    người dùng chỉ thấy phụ đề sai tên riêng sau cả tiếng chờ. Đây là bệ đỏ cho
    lỗi triển khai thực tế: file Frozen được nghe bằng local dù image đã mới.
    """
    from test._fakes import FakeTranslate, install_translate
    from services import video_dich as vd
    import services.video_asr as va_mod

    class _KetQua:
        engine = "gpu"
        canh_bao = ""

        def __iter__(self):
            yield [va.Cau(0.0, 2.0, "Hello, Elsa.")]
            yield "en"
            yield 2.0

    monkeypatch.setattr(va_mod, "nghe_tep", lambda *_a, **_kw: _KetQua())
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        r = vd.dich_tep_video("/tmp/frozen.mp3", "frozen.mp3", target="vi",
                               nguon_biet="en")

    assert r["nghe"]["engine"] == "gpu"
    assert "Whisper GPU" in vd.bao_cao(r)


def test_vision_loi_van_xuat_srt_va_bao_canh_bao(monkeypatch):
    """Qwen hỏng chỉ mất ngữ cảnh hình, không được làm rơi toàn bộ phụ đề."""
    from test._fakes import FakeTranslate, install_translate
    from services import video_dich as vd
    import services.video_asr as va_mod
    from services import video_vision as vv

    class _KetQua:
        engine = "gpu"
        canh_bao = ""

        def __iter__(self):
            yield [va.Cau(0.0, 2.0, "Hello, Elsa.")]
            yield "en"
            yield 2.0

    monkeypatch.setattr(va_mod, "nghe_tep", lambda *_a, **_kw: _KetQua())
    monkeypatch.setattr(vv, "phan_tich_video", lambda *_a, **_kw:
                        vv.KetQuaVision("fallback", [], [],
                                        "Qwen3-VL GPU lỗi; dùng lời thoại."))
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        r = vd.dich_tep_video("/tmp/frozen.mp4", "frozen.mp4", target="vi",
                               nguon_biet="en")

    assert r["ok"] is True
    assert r["vision"]["engine"] == "fallback"
    assert "Qwen3-VL GPU lỗi" in vd.bao_cao(r)


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
