"""Đọc viết tắt / ký hiệu / đơn vị cho đúng (25/09/2026) — ca lấy từ câu trả lời THẬT của bot."""
from __future__ import annotations

import os
import re

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from services.voice import doc_theo_nghia as d  # noqa: E402


def sea_gia(t: str) -> str:
    """sea_g2p giả: KHÔNG biết chữ viết tắt nào — đánh vần trơn như sea làm với "API"."""
    return re.sub(r"[A-Z]{2,}", lambda m: " ".join(m.group(0).lower()), t)


@pytest.mark.parametrize("vao, ra", [
    ("- 60% cỏ đen làm nền.\n- 25% đá lát.", "60% cỏ đen làm nền.\n25% đá lát."),   # gạch đầu dòng ≠ dấu âm
    ("Gió nhẹ khoảng 7.3 km/h.", "Gió nhẹ khoảng 7,3 km/h."),                        # chấm thập phân kiểu Anh
    ("Giá 3.399 USD", "Giá 3.399 đô la Mỹ"),                                           # chấm phân nghìn giữ nguyên
    ("Không mưa trong 120 ph.", "Không mưa trong 120 phút."),
    ("Thiết bị 12V, 800W, pin 10Ah, mô-men 235 Nm, 650 kcal.",
     "Thiết bị 12 vôn, 800 oát, pin 10 am pe giờ, mô-men 235 niu tơn mét, 650 ki lô ca lo."),
    ("Lúc 24h qua", "Lúc 24 giờ qua"),
    ("Bản hybrid (350h)", "Bản hai brít (350h)"),                                       # tên mẫu, không phải giờ
    ("Xăng RON 92-II, RON 95-III, quý IV", "Xăng ron 92 2, ron 95 3, quý 4"),
    ("1g. Giải trí 1h. Thế giới", "1 gờ. Giải trí 1 hát. Thế giới"),                   # chuỗi nhãn mục
    ("Hẹn đến 1h. Nhé", "Hẹn đến 1 giờ. Nhé"),                                         # một mình: là giờ
    ("bệnh nhân L.T.M.P (51 tuổi)", "bệnh nhân lờ tê mờ phê (51 tuổi)"),
])
def test_lop_loi_co_quy_luat(vao, ra):
    assert d.chuan_bi(vao, sea_gia) == ra


def test_ma_chu_so_danh_van_kieu_viet():
    assert "xê tê 4 bê ích 2" in " ".join(d.chuan_bi("Tòa nhà CT4B-X2", sea_gia).replace(",", " ").split())
    assert "gờ phê tê" in d.chuan_bi("GPT-5 mới", sea_gia)
    assert "nờ 8 nờ" in " ".join(d.chuan_bi("Bot n8n", sea_gia).split())


def test_viet_tat_la_danh_van_doc_duoc_thi_doc_tu():
    assert d.chuan_bi("Có API mới", sea_gia) == "Có a phê i mới"
    assert d.chuan_bi("Giá RAM tăng", sea_gia) == "Giá ram tăng"
    assert d.chuan_bi("vô địch ASEAN Cup", sea_gia) == "vô địch a xê an Cup"


def test_viet_tat_sea_biet_thi_de_sea():
    def sea_biet_tp(t):
        return t.replace("TP", "thành phố")
    assert d.chuan_bi("TP HCM", sea_biet_tp).startswith("TP")


def test_tieu_de_in_hoa_doc_nhu_chu_thuong():
    assert d.chuan_bi("TIN CẢNH BÁO LŨ QUÉT", sea_gia) == "tin cảnh báo lũ quét"
    assert d.chuan_bi("Ở ĐẢO LỚN có mưa", sea_gia) == "ở đảo lớn có mưa"   # chữ HOA có dấu (Ở, Ả…)
    assert d.chuan_bi("một CAMERA GIÁM SÁT trong nhà", sea_gia) == "một ca mê ra giám sát trong nhà"
    # Chữ thường có dấu KHÔNG bị coi là in hoa ("Bộ", "Mở")
    assert d.chuan_bi("Mở HA lên", sea_gia) == "Mở hát a lên"


def test_don_cuoi_phu_am_tron():
    assert d.don_cuoi("tám mươi b p m") == "tám mươi bê phê mờ"
    assert d.don_cuoi("đi xe") == "đi xe"


def test_doc_vi_goi_buoc_chuan_bi_va_loi_thi_doc_nhu_cu(monkeypatch):
    from services.voice import engines

    class SeaGia:
        def normalize(self, t):
            return t.lower()

    monkeypatch.setattr(engines, "_chuan_hoa_vi", SeaGia())
    assert engines._doc_vi("- 60% và API") == "60% và a phê i"   # không khoá chết khi gọi sea lồng

    def hong(*a, **k):
        raise ValueError("gia")
    monkeypatch.setattr(d, "chuan_bi", hong)
    assert engines._doc_vi("- 60%") == "- 60%"                    # lỗi: đọc qua sea như cũ


@pytest.mark.parametrize("vao, co", [
    ("- 60% cỏ đen làm nền.", "sáu mươi phần trăm cỏ"),
    ("Gió nhẹ khoảng 7.3 km/h.", "bảy phẩy ba ki lô mét trên giờ"),
    ("Giá RAM tăng từ 52 USD lên 239 USD.", "năm mươi hai đô la mỹ"),
    ("Không có mưa trong ít nhất 120 ph.", "một trăm hai mươi phút"),
    ("Dầu DO 0,05S-II: 28.540đ/lít.", "không phẩy không năm ét hai"),
    ("RAM DDR5 16 GB", "mười sáu gigabyte"),
])
def test_voi_sea_g2p_that(vao, co):
    pytest.importorskip("sea_g2p")
    from sea_g2p import Normalizer

    n = Normalizer("vi")

    def sea(t):
        return re.sub(r"</?en>", "", n.normalize(t))
    assert co in d.don_cuoi(sea(d.chuan_bi(vao, sea)))


# Phiên âm từ tiếng Anh (25/09/2026): để nguyên thì STT chỉ nhận ra ~18% từ giọng Nghị
# đọc ("google" → "graham le"); phiên âm theo từ điển → ~36%.
@pytest.mark.parametrize("vao, ra", [
    ("Bật Bluetooth rồi mở YouTube.", "Bật blu tút rồi mở yu túp."),
    ("Home Assistant cập nhật firmware cho camera.", "hôm a xi xtần cập nhật phơm ue cho ca mê ra."),
    ("Anh gửi link qua Zalo nhé.", "Anh gửi linh qua za lô nhé."),
])
def test_phien_am_tu_tieng_anh_trong_cau_viet(vao, ra):
    assert d.phien_am_anh(vao) == ra


@pytest.mark.parametrize("cau", [
    "Nghe nhạc trên xe, pin còn 50%.",                          # âm tiết Việt không dấu: giữ
    "It rests for another 30 hours before fertilization.",     # đoạn thuần tiếng Anh: giữ
    "Mở trang google.com hoặc gửi về a@gmail.com nhé.",        # tên miền / email: giữ
    "Đường 5 km, nặng 3 kg.",                                   # ký hiệu đo: giữ
])
def test_phien_am_khong_dung_cho_khong_phai_tu_anh(cau):
    assert d.phien_am_anh(cau) == cau


def test_chuan_bi_co_phien_am():
    assert "yu túp" in d.chuan_bi("Mở YouTube trên tivi.", sea_gia)


def test_ma_tien_sau_so_la_don_vi_tien():
    """Chủ máy 25/09/2026: "10 BTC" nghe thành "mười ban tổ chức"."""
    def sea_btc(t):
        return t.replace("BTC", "ban tổ chức")
    assert d.chuan_bi("BTC trao giải 10 BTC", sea_btc).endswith("trao giải 10 bít côi")
    assert d.chuan_bi("thưởng 0,1 BTC và 52 USD", sea_btc) == "thưởng 0,1 bít côi và 52 đô la Mỹ"


# Chọn nghĩa tự học (cách 1): chữ viết tắt NHIỀU NGHĨA theo từ xung quanh.
@pytest.mark.parametrize("vao, co", [
    ("BTC trao giải thưởng cho công ty CP và DV brecus 10 BTC", "công ty cổ phần và dịch vụ"),
    ("ĐT Việt Nam vừa thắng, anh nhớ gọi ĐT cho em nhé.", "đội tuyển Việt Nam"),
    ("ĐT Việt Nam vừa thắng, anh nhớ gọi ĐT cho em nhé.", "gọi điện thoại cho em"),
    ("CP vừa ban hành nghị định.", "chính phủ vừa ban hành"),
])
def test_chon_nghia_viet_tat_theo_ngu_canh(vao, co):
    assert co in d.chuan_bi(vao, sea_gia)


def test_chon_nghia_khong_hoc_thi_bo_qua():
    assert d.chon_nghia("XYZ", "câu có XYZ", 7, 10) is None


def test_viet_tat_truoc_so_la_ma_khong_doan_nghia():
    """"ĐT 767" là ĐƯỜNG TỈNH — nghĩa không có trong từ điển; đứng trước số thì không đoán."""
    ra = d.chuan_bi("Chiều nay, đường ĐT 767 bị ngập.", lambda t: t)
    assert not any(ng in ra for ng in ("điện thoại", "đào tạo", "đội tuyển"))


def test_chon_nghia_tren_ca_bai_truoc_khi_cat_cau():
    """Chủ máy 25/09/2026 nghe "CP chỉ đạo" thành "cổ phiếu chỉ đạo": engine cắt câu ở dấu
    phẩy TRƯỚC khi chuẩn hoá, mẩu sau mất vế "UBND… họp với BQL dự án"."""
    cau = "UBND TP.HCM họp với BQL dự án, CP chỉ đạo giảm 15% giá CP của DNNN trong quý III/2026."
    ca_bai = d.chon_nghia_ca_bai(cau)
    assert "chính phủ chỉ đạo" in ca_bai and "giá cổ phiếu" in ca_bai
    assert d.chuan_bi(ca_bai.split(", ", 1)[1], sea_gia).startswith("chính phủ chỉ đạo")


def test_chon_nghia_ca_bai_giu_ma_tien_va_ma_so():
    assert d.chon_nghia_ca_bai("Giá 10 BTC, đường ĐT 767") == "Giá 10 BTC, đường ĐT 767"


def test_doc_cong_thuc_chon_nghia_tren_toan_van():
    from services.voice import engines
    ra = engines._doc_cong_thuc("UBND họp với BQL dự án, CP chỉ đạo giảm giá CP.", "nghi:ban-mai")
    assert "chính phủ chỉ đạo" in ra


# 14 câu khó chủ máy thử 25/09/2026 — mỗi dòng một LỚP lỗi, đo với sea_g2p thật.
@pytest.mark.parametrize("vao, co", [
    # tiêu đề in hoa không được nuốt chữ viết tắt ("GĐ BV" từng thành "gđ bv", không đọc)
    ("PGS.TS Nguyễn Văn A, GĐ BV Bạch Mai, cho biết", "giám đốc bệnh viện bạch mai"),
    # viết tắt MỘT nghĩa sea không biết: từ điển (≥3 ký tự, hoặc có Đ)
    ("UBND họp với BQL dự án về DNNN", "ban quản lý dự án về doanh nghiệp nhà nước"),
    ("chẩn đoán ĐTĐ type 2", "đái tháo đường"),
    # viết tắt ghép gạch nối, cả sau "/" của số hiệu văn bản
    ("thay thế NĐ 100/2019/NĐ-CP", "nghị định chính phủ"),
    # số La Mã viết đúng luật tới 39 — "XXX" từng đọc "ích ích ích"
    ("Hội nghị lần thứ XXX, thế kỷ XXI", "lần thứ ba mươi, thế kỷ hai mươi mốt"),
    # mã có phần chữ đọc được thành từ
    ("Hội nghị COP30 bàn về COVID-19", "cop ba mươi"),
    ("Hội nghị COP30 bàn về COVID-19", "cô vít"),
    # khoảng số trước đơn vị: sea đọc thành NGÀY THÁNG hoặc mất "đến"
    ("mất 2-3 ngày, khoảng 8-10 giờ", "hai đến ba ngày, khoảng tám đến mười giờ"),
    ("Xe chạy 0-100 km/h", "không đến một trăm ki lô mét trên giờ"),
    ("diễn ra ngày 10-21/11/2025", "ngày mười đến ngày hai mươi mốt tháng mười một"),
    # cặp số không tăng là tỉ số, không phải phép trừ; là ngày thì sea tự đọc
    ("báo kết quả 3-1 trước Thái Lan", "kết quả ba một trước"),
    ("ngày 25-9 tại Hà Nội", "ngày hai mươi lăm tháng chín"),
    # "0 K" là kelvin; "4K" là độ phân giải
    ("đạt 0 K, màn hình 4K", "không ken vin, màn hình bốn ca"),
    # đường dẫn web
    ("website https://c2a.vn/huong-dan?id=5.", "xê hai a chấm vê nờ gạch chéo huong dan"),
])
def test_cau_kho_voi_sea_that(vao, co):
    pytest.importorskip("sea_g2p")
    from sea_g2p import Normalizer

    n = Normalizer("vi")

    def sea(t):
        return re.sub(r"</?en>", "", n.normalize(t))
    assert co in d.don_cuoi(sea(d.chuan_bi(d.chon_nghia_ca_bai(vao), sea)))


def test_so_la_ma_chi_nhan_so_dung_luat():
    assert [d._so_la_ma(x) for x in ("IV", "XXX", "XXXIX", "XIX", "VIX", "IIII", "")] == \
        [4, 30, 39, 19, None, None, None]
