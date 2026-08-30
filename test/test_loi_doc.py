"""Chuẩn hoá LỜI ĐỌC cho giọng máy — services/loi_doc.py.

Lỗi gốc (đo thật 30/08/2026 trên một video kỹ thuật 4 phút): 29/34 câu còn chỗ
giọng Việt không phát âm nổi — mã ``3wl``, cả cụm ``incoming feeder,
distribution tie và outgoing feeder``, tên hãng ``Seamans``. Chủ máy nghe ra
"lồng tiếng bị ngọng".

Luật chủ máy chốt: danh từ riêng đọc PHIÊN ÂM tiếng Việt, mã thiết bị đọc theo
tiếng đích, và phụ đề để XEM giữ nguyên — chỉ bản đọc mới được viết lại.

Không chạm mạng: model được giả lập, kho ghi vào DATA_DIR tạm.
"""
from __future__ import annotations

import json

import pytest

from services import loi_doc as ld

# Câu thật của lượt chạy 30/08, kèm câu gốc tương ứng.
VI_CUM = ("Được sử dụng làm bộ ngắt mạch incoming feeder, distribution tie "
          "và outgoing feeder, chúng là trung tâm.")
EN_CUM = ("Used as incoming feeder, distribution tie, and outgoing feeder "
          "circuit breakers, they are at the heart of many.")


@pytest.fixture
def kho(tmp_data_dir, monkeypatch):
    """DATA_DIR tạm + xoá nhớ đệm glossary giữa các test."""
    import services.config as cfg
    from services import thuat_ngu as tn

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_data_dir)
    (tmp_data_dir / "glossary").mkdir(parents=True, exist_ok=True)
    tn._reset_cache_cho_test()
    yield tmp_data_dir
    tn._reset_cache_cho_test()


# ── Dò chỗ giọng Việt không đọc được ────────────────────────────────────────


@pytest.mark.pure
def test_gop_cum_nhieu_chu_va_dau_phay_cat_cum():
    """Kho thuật ngữ giữ nguyên cụm 'incoming feeder'; tách lẻ là tra trượt."""
    assert ld.cho_kho_doc(VI_CUM, EN_CUM) == [
        "incoming feeder", "distribution tie", "outgoing feeder"]


@pytest.mark.pure
def test_bat_ma_thiet_bi_lan_chu_va_so():
    assert ld.cho_kho_doc("Bộ ngắt mạch 3wl nhỏ gọn.", "3wl breakers are small.") \
        == ["3wl"]
    assert ld.la_ma_thiet_bi("S7-1200") is True
    assert ld.la_ma_thiet_bi("50") is False


@pytest.mark.pure
def test_bat_ten_hang_con_nguyen_trong_ban_dich():
    assert ld.cho_kho_doc("Seamans đã sản xuất trong hơn 50 năm.",
                          "Seamans has been manufacturing for over 50 years.") \
        == ["Seamans"]


@pytest.mark.pure
def test_khong_bat_nham_tu_viet_khong_dau():
    """Dò bằng 'không có dấu thanh' bắt nhầm hàng loạt (đo thật 30/08): dao,
    minh, trang đều là từ Việt. Vì thế phải đối chiếu với CÂU GỐC."""
    cau = "Nó có thiết kế mô-đun, dao động minh bạch trên trang chủ."
    assert ld.cho_kho_doc(cau, "It has a modular design available in versions.") == []


@pytest.mark.pure
def test_khong_co_cau_goc_van_bat_duoc_ma_va_chu_cai_ngoai():
    """f/j/w/z không có trong bảng chữ cái tiếng Việt."""
    assert ld.cho_kho_doc("Dùng chuẩn Wifi và mã 3wl.") == ["Wifi", "3wl"]


@pytest.mark.pure
def test_bo_qua_so_tran_va_tu_mot_ky_tu():
    assert ld.cho_kho_doc("Trong hơn 50 năm và 3 phiên bản.",
                          "For over 50 years and 3 versions.") == []


# ── Thay bằng cách đọc đã biết ──────────────────────────────────────────────


@pytest.mark.pure
def test_thay_cum_dai_truoc_cum_ngan():
    """'feeder' mà thay trước thì 'incoming feeder' không còn nguyên để khớp."""
    ra = ld._thay("bộ ngắt mạch incoming feeder ở đây",
                  {"feeder": "bộ cấp", "incoming feeder": "bộ cấp nguồn vào"})
    assert ra == "bộ ngắt mạch bộ cấp nguồn vào ở đây"


@pytest.mark.pure
def test_thay_khop_ca_tu_khong_an_vao_giua_chu():
    ra = ld._thay("tie và tienbac", {"tie": "liên kết"})
    assert ra == "liên kết và tienbac"


# ── Kho cách đọc: học một lần, lần sau khỏi cần mạng ────────────────────────


@pytest.mark.adapter
def test_ghi_kho_roi_lan_sau_chua_duoc_ma_khong_can_model(kho):
    assert ld.ghi_kho({"3wl": "ba vê kép eo"}, "vi") == 1
    assert ld.doc_kho("vi") == {"3wl": "ba vê kép eo"}

    ra, so_sua, hoc = ld.chuan_hoa(
        ["Bộ ngắt mạch 3wl nhỏ gọn."], ["3wl breakers are small."],
        nguon="en", dich="vi", model="", goi_model=None)

    assert ra == ["Bộ ngắt mạch ba vê kép eo nhỏ gọn."]
    assert (so_sua, hoc) == (1, 0)


@pytest.mark.adapter
def test_ghi_kho_khong_de_muc_cu_bi_de(kho):
    ld.ghi_kho({"3wl": "ba vê kép eo"}, "vi")
    assert ld.ghi_kho({"3wl": "khác hẳn", "DP": "đê pê"}, "vi") == 1
    assert ld.doc_kho("vi")["3wl"] == "ba vê kép eo"


@pytest.mark.adapter
def test_lay_duoc_thuat_ngu_da_hoc_o_luot_truoc_khong_can_mang(kho):
    """Đúng tình huống 30/08: kho đã có 'incoming feeder' → 'bộ cấp nguồn vào'
    mà bản lồng tiếng vẫn đọc nguyên tiếng Anh."""
    (kho / "glossary" / "en.hoc.json").write_text(json.dumps({"ky_thuat": {
        "incoming feeder": "bộ cấp nguồn vào",
        "distribution tie": "liên kết phân phối",
        "outgoing feeder": "bộ cấp nguồn ra",
    }}, ensure_ascii=False), encoding="utf-8")

    ra, so_sua, hoc = ld.chuan_hoa([VI_CUM], [EN_CUM], nguon="en", dich="vi",
                                   model="", goi_model=None)

    assert "incoming feeder" not in ra[0]
    assert "bộ cấp nguồn vào" in ra[0] and "bộ cấp nguồn ra" in ra[0]
    assert (so_sua, hoc) == (3, 0)


@pytest.mark.adapter
def test_khong_co_model_thi_cho_chua_biet_giu_nguyen(kho):
    ra, so_sua, hoc = ld.chuan_hoa(["Chuẩn PROFIBUS ở đây."],
                                   ["PROFIBUS is used here."],
                                   nguon="en", dich="vi", model="", goi_model=None)
    assert ra == ["Chuẩn PROFIBUS ở đây."]
    assert (so_sua, hoc) == (0, 0)


# ── Hỏi model: nhận đúng phần đã hỏi, và học lại ────────────────────────────


@pytest.mark.adapter
def test_hoi_model_roi_hoc_lai_cach_doc(kho):
    goi = []

    def _model(_m, messages):
        goi.append(messages)
        return json.dumps([{"goc": "Seamans", "doc": "Xi-mừn"},
                           {"goc": "3wl", "doc": "ba vê kép eo"}],
                          ensure_ascii=False)

    ra, so_sua, hoc = ld.chuan_hoa(
        ["Seamans làm bộ ngắt mạch 3wl."], ["Seamans makes the 3wl breaker."],
        nguon="en", dich="vi", model="m", goi_model=_model)

    assert ra == ["Xi-mừn làm bộ ngắt mạch ba vê kép eo."]
    assert (so_sua, hoc) == (2, 2)
    assert ld.doc_kho("vi") == {"Seamans": "Xi-mừn", "3wl": "ba vê kép eo"}
    assert len(goi) == 1


@pytest.mark.adapter
def test_bo_qua_muc_khong_hoi_va_muc_model_tra_lai_y_nguyen(kho):
    def _model(_m, _msg):
        return json.dumps([{"goc": "3wl", "doc": "3wl"},          # trả lại y nguyên
                           {"goc": "khong-hoi", "doc": "bịa"}],   # không nằm trong câu hỏi
                          ensure_ascii=False)

    ra, so_sua, hoc = ld.chuan_hoa(["Mã 3wl ở đây."], ["The 3wl code here."],
                                   nguon="en", dich="vi", model="m", goi_model=_model)
    assert ra == ["Mã 3wl ở đây."]
    assert (so_sua, hoc) == (0, 0)
    assert ld.doc_kho("vi") == {}


@pytest.mark.adapter
def test_model_hong_thi_giu_nguyen_ban_dich(kho):
    def _model(_m, _msg):
        raise ld.LoiLoiDoc("model bận")

    ra, so_sua, _ = ld.chuan_hoa(["Mã 3wl ở đây."], ["The 3wl code here."],
                                 nguon="en", dich="vi", model="m", goi_model=_model)
    assert ra == ["Mã 3wl ở đây."] and so_sua == 0


# ── Đấu nối: phụ đề để XEM không đổi, chỉ bản đọc đổi ───────────────────────


@pytest.mark.adapter
def test_phu_de_giu_thuat_ngu_goc_con_ban_doc_thi_viet_lai(kho, monkeypatch):
    """Chủ máy chốt 30/08: 'Chỉ đổi bản đọc'."""
    from services import video_dich as vd

    (kho / "glossary" / "en.hoc.json").write_text(json.dumps({"ky_thuat": {
        "incoming feeder": "bộ cấp nguồn vào"}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(__import__("services.config", fromlist=["config"]).config.data,
                        "dich_llm", {"bat": False, "model": ""})
    monkeypatch.setattr(vd.ts, "translate_batch", lambda *_a:
                        ["Dùng làm bộ ngắt mạch incoming feeder."])

    r = vd._dich_va_dong_goi(
        [vd.Doan(0.0, 5.0, "Used as an incoming feeder breaker.")],
        "en", "vi", 5.0)

    xem = r["srt"].decode("utf-8")
    doc = vd.srt_cho_long_tieng(r).decode("utf-8")
    assert "incoming feeder" in xem
    assert "incoming feeder" not in doc
    assert "bộ cấp nguồn vào" in doc
    assert r["loi_doc"]["so_cho_sua"] == 1


@pytest.mark.adapter
def test_ban_chep_loi_tieng_viet_khong_bi_dong_toi(kho, monkeypatch):
    """``nguon == dich`` là chép lời, câu "gốc" chính là câu "dịch" — đối chiếu
    lúc đó coi MỌI chữ không dấu là chữ ngoại và phá hỏng bản chép."""
    from services import video_dich as vd

    cau = "Hom nay troi dep, minh di dao o trang trai."
    r = vd._dich_va_dong_goi([vd.Doan(0.0, 5.0, cau)], "vi", "vi", 5.0)

    assert cau in vd.srt_cho_long_tieng(r).decode("utf-8")
    assert r["loi_doc"] == {}
