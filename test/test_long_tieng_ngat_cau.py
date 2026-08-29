"""Ngắt câu cho lồng tiếng — chấm câu lại chữ trần, và SRT riêng cho giọng đọc.

Lỗi gốc (đo thật 29/08/2026 trên một video YouTube 9 phút): phụ đề tự sinh
không có một dấu chấm nào, nên ``gop_doan`` và ``video_dub._gop_cau`` — cả hai
đều ngắt bằng dấu câu — rơi xuống trần độ dài và cắt GIỮA CÂU; đồng thời khâu
lồng tiếng nhận bản SRT đã đóng gói cho MÀN HÌNH (42 ký tự/dòng, trần 7 giây)
nên bị cắt thêm lần nữa. Hai test dưới khoá đúng hai chỗ đó.

Không chạm mạng/GPU: máy dịch và model LLM đều giả lập.
"""
from __future__ import annotations

import pytest

from services import cham_cau as cc
from services import video_dich as vd
from services import video_dub as vdub
from test._fakes import FakeCallModel, install_call_model


# Chữ trần đúng kiểu YouTube tự sinh: không dấu câu, không viết hoa.
CHU_TRAN = [
    "swim through the layers of cervical mucus that guard",
    "the entrance to the uterus during ovulation this barrier",
    "becomes thinner and changes its acidity creating a",
    "friendlier environment for the sperm on the other side",
]
DA_CHAM = ("Swim through the layers of cervical mucus that guard the entrance "
           "to the uterus during ovulation. This barrier becomes thinner and "
           "changes its acidity, creating a friendlier environment for the "
           "sperm on the other side.")


@pytest.fixture(autouse=True)
def _co_may_chu_dich(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "http://vn-translate:5000")
    monkeypatch.setitem(config.data, "translate_api_key", "")


@pytest.fixture
def _bat_llm(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "dich_llm", {"bat": True, "model": "m"})


# ── Nhận ra bản chép thiếu dấu câu ──────────────────────────────────────────


@pytest.mark.pure
def test_chu_tran_dai_bi_nhan_ra_la_thieu_dau_cau():
    assert cc.thieu_dau_cau([" ".join(CHU_TRAN)] * 6) is True


@pytest.mark.pure
def test_phu_de_co_dau_cau_khong_bi_dong_vao():
    day = ["Xin chào anh. Hôm nay trời đẹp quá! Anh đi đâu đấy?"] * 8
    assert cc.thieu_dau_cau(day) is False


@pytest.mark.pure
def test_clip_ngan_khong_xet():
    """Vài câu ngắn không có dấu thì cũng chẳng có gì để ngắt lại."""
    assert cc.thieu_dau_cau(["hello there", "how are you"]) is False


# ── Rải chữ đã chấm câu về đúng từng mảnh ───────────────────────────────────


@pytest.mark.pure
def test_giu_nguyen_so_chu_tung_manh():
    ra = cc._rai_lai(CHU_TRAN, DA_CHAM)

    assert ra is not None
    assert len(ra) == len(CHU_TRAN)
    for goc, moi in zip(CHU_TRAN, ra):
        assert len(moi.split()) == len(goc.split())
    assert " ".join(ra) == DA_CHAM


@pytest.mark.pure
def test_bo_qua_loi_dan_thua_cua_model():
    raw = "Đây là bản đã chấm câu:\n\n" + DA_CHAM
    assert " ".join(cc._rai_lai(CHU_TRAN, raw) or []) == DA_CHAM


@pytest.mark.pure
def test_bo_qua_ghi_chu_thua_o_cuoi():
    raw = DA_CHAM + "\n\n(Đã giữ nguyên toàn bộ từ ngữ.)"
    assert " ".join(cc._rai_lai(CHU_TRAN, raw) or []) == DA_CHAM


@pytest.mark.pure
def test_bo_chu_cut_o_mep_lo_thi_van_nhan_va_chep_lai_nguyen_van():
    """Lô cắt theo số ký tự nên hay kết bằng một chữ cụt; model gạt nó đi. Đo
    thật 29/08/2026: 1/3 lô bị bỏ cả lô chỉ vì đúng một chữ "the" ở cuối."""
    goc = CHU_TRAN + ["the"]
    ra = cc._rai_lai(goc, DA_CHAM)           # model gạt hẳn chữ "the" cụt đi

    assert ra is not None
    assert ra[-1] == "the"                   # chữ bị bỏ được chép lại nguyên văn
    assert [cc._khoa(t) for m in ra for t in m.split()] == \
           [cc._khoa(t) for m in goc for t in m.split()]


@pytest.mark.pure
def test_bo_qua_nhieu_chu_o_mep_thi_van_truot():
    goc = CHU_TRAN + ["on the other side"]
    assert cc._rai_lai(goc, DA_CHAM) is None


@pytest.mark.pure
@pytest.mark.parametrize("hong", [
    DA_CHAM.replace("cervical ", ""),                     # bớt chữ
    DA_CHAM.replace("barrier", "wall"),                   # đổi chữ
    DA_CHAM.replace("during ovulation", "during the ovulation"),  # chen chữ
])
def test_model_doi_chu_thi_bo_ca_lo(hong):
    assert cc._rai_lai(CHU_TRAN, hong) is None


@pytest.mark.pure
def test_model_loi_thi_giu_nguyen_ban_goc():
    def _no(_m, _msg):
        raise cc.LoiChamCau("model bận")

    assert cc.phuc_hoi(CHU_TRAN, "m", _no) == CHU_TRAN


@pytest.mark.pure
def test_khong_co_model_thi_tra_nguyen_dau_vao():
    assert cc.phuc_hoi(CHU_TRAN, "", lambda *_a: DA_CHAM) == CHU_TRAN


# ── Chấm câu xong thì đơn vị dịch mới ngắt đúng chỗ ─────────────────────────


@pytest.mark.adapter
def test_chua_cham_cau_thi_don_vi_dich_dut_giua_cau():
    """Chốt lại HÀNH VI CŨ để thấy rõ bước chấm câu sửa cái gì."""
    dai = [vd.Doan(i * 3.0, i * 3.0 + 3.0, CHU_TRAN[i % len(CHU_TRAN)])
           for i in range(40)]
    nhom = vd.gop_doan(dai)

    assert len(nhom) > 1
    assert not any(d.chu.rstrip().endswith((".", "?", "!", "…")) for d in nhom)


@pytest.mark.adapter
def test_cham_cau_lai_roi_moi_gop_thi_moi_don_vi_la_mot_cau(_bat_llm):
    doan = [vd.Doan(i * 3.0, i * 3.0 + 3.0, t) for i, t in enumerate(CHU_TRAN)]
    # Ép qua ngưỡng ký tự để bước chấm câu chịu chạy.
    doan = doan * 4
    doan = [vd.Doan(i * 3.0, i * 3.0 + 3.0, d.chu) for i, d in enumerate(doan)]

    def _tra_loi(_model, messages, **_kw):
        goc = messages[-1]["content"]
        # Model thật chỉ thêm dấu; ở đây chấm sau mỗi "side" cho tất định.
        return goc.replace("other side ", "other side. ").rstrip() + "."

    with install_call_model(FakeCallModel(replies=[_tra_loi] * 4)):
        sach = vd._cham_cau_neu_thieu(doan)

    nhom = vd.gop_doan(sach)
    assert len(nhom) == 4
    assert all(d.chu.rstrip().endswith(".") for d in nhom)


# ── Tách đúng tại dấu câu, không phụ thuộc ranh giới mảnh ───────────────────


@pytest.mark.pure
def test_cat_dung_tai_dau_cham_nam_giua_manh():
    """Chỗ ``gop_doan`` không với tới: dấu chấm nằm giữa mảnh phụ đề."""
    doan = [vd.Doan(0.0, 10.0, "Câu một xong rồi. Câu hai bắt"),
            vd.Doan(10.0, 16.0, "đầu ở đây và kết thúc.")]

    ra = vd.tach_theo_cau(doan)

    assert [d.chu for d in ra] == ["Câu một xong rồi.",
                                   "Câu hai bắt đầu ở đây và kết thúc."]
    assert ra[0].bat_dau == pytest.approx(0.0)
    # "Câu một xong rồi." chiếm 17/29 ký tự của mảnh đầu (dài 10 giây).
    assert ra[0].ket_thuc == pytest.approx(10.0 * 17 / 29, abs=0.1)
    assert ra[1].ket_thuc == pytest.approx(16.0, abs=0.05)


@pytest.mark.pure
def test_khong_co_dau_cau_thi_tra_y_nguyen():
    """Đường cũ (chưa chấm câu được) phải chạy KHÔNG ĐỔI."""
    doan = [vd.Doan(0.0, 3.0, t) for t in CHU_TRAN]
    assert vd.tach_theo_cau(doan) == doan


@pytest.mark.pure
def test_phu_de_nguoi_lam_moi_khung_mot_cau_thi_moc_khong_xe_dich():
    """Đường .srt của phim: mốc do người làm, không được nội suy lệch đi."""
    doan = [vd.Doan(0.0, 2.5, "Anh có nghe thấy không?"),
            vd.Doan(3.2, 6.0, "Tôi nghe rõ lắm."),
            vd.Doan(7.0, 9.5, "Vậy thì đi thôi!")]

    assert vd.tach_theo_cau(doan) == doan


@pytest.mark.pure
def test_khong_xe_so_thap_phan():
    doan = [vd.Doan(0.0, 6.0, "Giá 1.5 triệu và 12.30 giờ chiều nhé.")]
    assert len(vd.tach_theo_cau(doan)) == 1


@pytest.mark.pure
def test_ton_trong_khoang_lang_giua_hai_manh():
    """Câu kết thúc trong mảnh nào thì mốc nằm trong mảnh đó, không lấn sang
    khoảng lặng trước mảnh sau."""
    doan = [vd.Doan(0.0, 4.0, "Câu một."), vd.Doan(30.0, 34.0, "Câu hai.")]
    ra = vd.tach_theo_cau(doan)

    assert len(ra) == 2
    assert ra[0].ket_thuc == pytest.approx(4.0, abs=0.05)
    assert ra[1].bat_dau == pytest.approx(30.0, abs=0.05)


@pytest.mark.pure
def test_gop_doan_khong_gop_lai_cau_da_tron():
    doan = [vd.Doan(0.0, 10.0, "Câu một xong rồi. Câu hai bắt"),
            vd.Doan(10.0, 16.0, "đầu ở đây và kết thúc.")]
    nhom = vd.gop_doan(vd.tach_theo_cau(doan))

    assert len(nhom) == 2
    assert all(d.chu.rstrip().endswith(".") for d in nhom)


@pytest.mark.adapter
def test_tat_llm_thi_khong_goi_model_va_khong_hong(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "dich_llm", {"bat": False, "model": "m"})
    doan = [vd.Doan(i * 3.0, i * 3.0 + 3.0, CHU_TRAN[i % 4]) for i in range(20)]

    with install_call_model(FakeCallModel()) as fake:
        assert vd._cham_cau_neu_thieu(doan) == doan
    assert not fake.calls


# ── SRT riêng cho giọng đọc ─────────────────────────────────────────────────


@pytest.mark.pure
def test_srt_long_tieng_khong_ep_tran_bay_giay_nen_khong_de_ra_khoang_lang_gia():
    """Trần 7 giây là luật MÀN HÌNH; nó cắt cụt mốc kết thúc và đẻ ra một
    khoảng lặng không có thật, thứ mà ``_gop_cau`` hiểu thành "người ta ngừng
    nói" rồi cắt câu."""
    cau = "Đây là một câu rất dài " * 12
    doan = [vd.Doan(0.0, 20.0, cau.strip()),
            vd.Doan(20.0, 26.0, "Câu thứ hai ngắn hơn.")]

    hien_thi = vd.doc_phu_de(vd.lam_srt(doan))
    doc = vd.doc_phu_de(vd.lam_srt_long_tieng(doan))

    # Bản hiển thị: khung đầu bị cắt còn 7 giây → hở 13 giây trước khung sau.
    assert hien_thi[0].ket_thuc == pytest.approx(vd.GIAY_TOI_DA, abs=0.01)
    assert (hien_thi[1].bat_dau - hien_thi[0].ket_thuc) > vdub.NGAT_CAU_GIAY
    # Bản cho giọng đọc: giữ nguyên mốc thật, không hở.
    assert len(doc) == 2
    assert doc[0].bat_dau == pytest.approx(0.0)
    assert doc[0].ket_thuc == pytest.approx(20.0, abs=0.01)
    assert doc[0].chu == cau.strip()
    assert (doc[1].bat_dau - doc[0].ket_thuc) <= vdub.NGAT_CAU_GIAY


@pytest.mark.pure
def test_srt_long_tieng_khong_de_khung_nay_de_len_khung_sau():
    doan = [vd.Doan(0.0, 9.0, "Câu một."), vd.Doan(5.0, 8.0, "Câu hai.")]
    ra = vd.doc_phu_de(vd.lam_srt_long_tieng(doan))

    assert ra[0].bat_dau == pytest.approx(0.0)
    assert ra[0].ket_thuc <= ra[1].bat_dau
    assert ra[1].bat_dau == pytest.approx(5.0)


@pytest.mark.pure
def test_gop_cau_cua_long_tieng_khong_cat_them_tren_ban_theo_cau():
    """Đầu ra mới đưa thẳng vào khâu lồng tiếng phải giữ nguyên từng câu."""
    doan = [vd.Doan(0.0, 20.0, "Một câu rất dài " * 10 + "kết thúc."),
            vd.Doan(24.0, 30.0, "Câu sau một khoảng lặng dài."),
            vd.Doan(30.0, 34.0, "Câu cuối cùng.")]

    cau = vdub._gop_cau(vd.doc_phu_de(vd.lam_srt_long_tieng(doan)))

    assert len(cau) == 3
    assert all(vdub._het_cau(c.chu) for c in cau)
    assert cau[0].bat_dau == pytest.approx(0.0)
    assert cau[1].bat_dau == pytest.approx(24.0)


# ── Đấu nối: hai lối gọi đều phải lấy bản cho giọng đọc ─────────────────────


@pytest.mark.adapter
def test_ket_qua_dich_co_ban_srt_rieng_cho_long_tieng(monkeypatch):
    monkeypatch.setattr(vd.ts, "translate_batch", lambda *_a:
                        ["Câu một rất dài. " * 8])

    r = vd._dich_va_dong_goi(
        [vd.Doan(0.0, 24.0, "Sentence one is quite long.")], "en", "vi", 24.0)

    assert r["ok"] is True
    doc = vd.doc_phu_de(vd.srt_cho_long_tieng(r).decode("utf-8"))
    hien_thi = vd.doc_phu_de(r["srt"].decode("utf-8"))
    assert len(doc) == 1                      # một đơn vị dịch = một khối
    assert len(hien_thi) > 1                  # bản màn hình vẫn cắt vụn như cũ
    assert doc[0].ket_thuc - doc[0].bat_dau > vd.GIAY_TOI_DA


@pytest.mark.pure
def test_ket_qua_cu_khong_co_khoa_moi_van_dung_duoc():
    assert vd.srt_cho_long_tieng({"srt": b"cu"}) == b"cu"
