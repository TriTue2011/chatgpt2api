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
    ("Giá 3.399 USD", "Giá 3.399 u ét đê"),                                            # chấm phân nghìn giữ nguyên
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
    ("Giá RAM tăng từ 52 USD lên 239 USD.", "năm mươi hai u ét đê"),
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
