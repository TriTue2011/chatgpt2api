"""Đọc công thức hoá học cho TTS tiếng Việt (24/09/2026)."""
from __future__ import annotations

import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

from services.voice import hoa_hoc as h  # noqa: E402


@pytest.mark.parametrize("viet, doc", [
    ("H₂O", "hát hai ô"),
    ("H2SO4", "hát hai ét ô bốn"),
    ("NaCl", "nờ a xê lờ"),
    ("C6H12O6", "xê sáu hát mười hai ô sáu"),
    ("Ca(OH)2", "xê a ô hát hai lần"),
    ("CuSO4.5H2O", "xê u ét ô bốn chấm năm hát hai ô"),
    ("SO4²⁻", "ét ô bốn hai trừ"),
    ("Fe³⁺", "ép e ba cộng"),
    ("Fe3+", "ép e ba cộng"),
    ("PO4^3-", "phê ô bốn ba trừ"),
    ("OH⁻", "ô hát trừ"),
])
def test_cong_thuc(viet, doc):
    assert h.doc(viet) == doc


def test_phuong_trinh_mui_ten_dau_cong_va_he_so():
    assert h.doc("3CO + Fe2O3 → 2Fe + 3CO2") == \
        "ba xê ô cộng ép e hai ô ba tạo thành hai ép e cộng ba xê ô hai"
    assert h.doc("BaCl2 + Na2SO4 → BaSO4↓ + 2NaCl").count("kết tủa") == 1
    assert "thuận nghịch" in h.doc("N2 + 3H2 ⇌ 2NH3")


@pytest.mark.parametrize("cau", [
    "Co giãn tốt.", "CON mèo.", "WHO họp.", "5 mg thuốc.", "iPhone 15.",
    "Ba mẹ đi làm. Ca sĩ hát hay. La hét.",
    "Nước sạch. Hôm nay Ông Bà Cô Chú về.",   # chữ hoa đầu từ có dấu không bị tách
    "As you know, In my opinion.",            # câu tiếng Anh: không áp luật âm tiết
    "Chương III.", "Covid-19.", "x² + 2x = 0, 10³", "Giá 100$.", "A4, MP3, G7.",
])
def test_khong_dung_chu_khong_phai_cong_thuc(cau):
    assert h.doc(cau) == cau


def test_dau_cau_dinh_cuoi_khong_thuoc_cong_thuc():
    assert h.doc("Axit là H2SO4.") == "Axit là hát hai ét ô bốn."


def test_doc_so():
    assert [h.doc_so(n) for n in (0, 4, 10, 12, 15, 21, 24, 25, 100, 105, 112)] == [
        "không", "bốn", "mười", "mười hai", "mười lăm", "hai mươi mốt", "hai mươi bốn",
        "hai mươi lăm", "một trăm", "một trăm linh năm", "một trăm mười hai"]


def test_engine_doi_chu_sau_khoa_cache_va_bo_qua_kokoro_anh(monkeypatch):
    from services.voice import config as vcfg
    from services.voice import engines, tts_cache

    monkeypatch.setattr(vcfg, "tts_backend", lambda: "local")
    khoa: list[bytes] = []
    monkeypatch.setattr(tts_cache, "get", lambda k: khoa.append(k))
    nhan: list[str] = []

    def nghi(text, voice, chen_nghi=True):
        nhan.append(text)
        yield 22050, b"\x10\x27" * 100

    monkeypatch.setattr(engines, "_nghi_phat", nghi)
    list(engines._stream_tao("Nước là H2O.", "nghi:ban-mai"))
    assert nhan == ["Nước là hát hai ô."]
    assert khoa[0] == tts_cache.key("stream", "Nước là H2O.", "nghi:ban-mai", "")
    assert engines._doc_cong_thuc("H2O", "kokoro:af") == "H2O"


def test_so_mu_dinh_dau_cau_khong_do_loi():
    assert h.doc("ion Fe³⁺, SO4²⁻.") == "ion ép e ba cộng, ét ô bốn hai trừ."


@pytest.mark.parametrize("viet, doc", [
    ("Mg trong máu cao.", "ma giê trong máu cao."),        # Mg ≠ mg; đứng riêng đọc TÊN
    ("Ca và Mg là kim loại.", "can xi và ma giê là kim loại."),
    ("Cho Ba vào dung dịch H2SO4.", "Cho ba ri vào dung dịch hát hai ét ô bốn."),
    ("Ion Cl- và Na+ trong NaCl.", "Ion xê lờ trừ và nờ a cộng trong nờ a xê lờ."),
    ("Ba mẹ đi làm. Cho Ba vào H2O.", "Ba mẹ đi làm. Cho ba ri vào hát hai ô."),
    ("Water is H2O.", "Water is hát hai ô."),                  # công thức chắc chắn thì vẫn đổi
])
def test_ky_hieu_dung_rieng_theo_ngu_canh(viet, doc):
    assert h.doc(viet) == doc


def test_mui_ten_nhac_lai_chu_da_viet_thi_khong_doc_lap():
    """Chủ máy 24/09/2026: "tạo kết tủa BaSO₄↓" bị đọc "kết tủa … kết tủa"."""
    assert h.doc("Để tạo kết tủa BaSO₄↓ trong giờ.") == "Để tạo kết tủa bê a ét ô bốn trong giờ."
    assert h.doc("BaCl2 + Na2SO4 → BaSO4↓ + 2NaCl").count("kết tủa") == 1


# Chủ máy 25/09/2026: "giảm lỗi giữa tên người và ký hiệu hoá học". Đo trên 2.000
# câu trả lời thật: lỗi nặng nhất là câu THƯỜNG bị tưởng là câu hoá học — chữ "C"
# trong "°C" bị coi là Cacbon, rồi "Thứ Ba" của bản tin sáng đọc thành "Thứ bê a".
@pytest.mark.parametrize("cau", [
    "Chào buổi sáng Thứ Ba nhé ạ, nhiệt độ khoảng 28.7°C.",       # bản tin thật
    "Ngoài trời đang có mưa, 27°C. Ra ngoài nhớ mang ô.",
    "Ra ngoài nhớ mang ô, trời 27°C.",
    "- Am – F – C – G (buồn, sâu lắng)",                            # hợp âm
    "Khu đô thị Tây Na → Phường Hai Bà Trưng",                      # chỉ đường
    "Hà Nội → Hải Phòng mất 2 tiếng.",
    "Nguyên tử khối của C là 12.",   # chữ cái đơn: để nguyên, bộ chuẩn hoá sau tự đọc tên chữ
    # URL thật của bot: "%C3%A0" từng thành "%xê…"
    "Mở https://www.google.com/maps/dir/?api=1&origin=t%C3%B2a+nh%C3%A0+CT4Bx2 nhé.",
])
def test_cau_thuong_khong_bi_tuong_la_hoa_hoc(cau):
    assert h.doc(cau) == cau


@pytest.mark.parametrize("viet, doc", [
    # Tên người sau từ xưng hô
    ("Cô Na cho Ba vào dung dịch H2SO4.", "Cô Na cho ba ri vào dung dịch hát hai ét ô bốn."),
    ("Bạn Na và bạn Hà làm thí nghiệm với NaCl.", "Bạn Na và bạn Hà làm thí nghiệm với nờ a xê lờ."),
    ("Anh Ba nhỏ HCl vào ống nghiệm.", "Anh Ba nhỏ hát xê lờ vào ống nghiệm."),
    ("Chị La mua 2 kg Ca(OH)2.", "Chị La mua 2 kg xê a ô hát hai lần."),
    ("Em Ti đã hiểu bài Mg tác dụng với HCl.", "Em Ti đã hiểu bài ma giê tác dụng với hát xê lờ."),
    # Chữ hoa nối tiếp chữ hoa giữa câu: một tên riêng
    ("Thầy Lê Văn Co giảng Fe + CuSO4 → FeSO4 + Cu.",
     "Thầy Lê Văn Co giảng ép e cộng xê u ét ô bốn tạo thành ép e ét ô bốn cộng xê u."),
    ("Nguyen Van Ba gui H2O.", "Nguyen Van Ba gui hát hai ô."),
    # Danh sách ký hiệu: chữ hoa đứng trước là KÝ HIỆU chứ không phải tên → vẫn là nguyên tố
    ("Các kim loại K Na Ca tác dụng với H2O.",
     "Các kim loại ka li nát tri can xi tác dụng với hát hai ô."),
    ("Đun H2SO4 ở 100°C.", "Đun hát hai ét ô bốn ở 100°C."),   # °C là đơn vị
    # Dấu phẩy ngắt: "Mg," đứng trước không làm "Na" thành tên (câu thật của bot)
    ("Các lần xuất hiện của Ba, K, Mg, Na, Fe đứng riêng:",
     "Các lần xuất hiện của ba ri, ka li, ma giê, nát tri, sắt đứng riêng:"),
])
def test_ten_nguoi_khong_bi_doc_thanh_nguyen_to(viet, doc):
    assert h.doc(viet) == doc


@pytest.mark.parametrize("cau", [
    "Galaxy S27 Ultra, xăng RON 95-III và quý IV.",   # S27 tạo ngữ cảnh, III/IV vẫn là số La Mã
    "Thế kỷ XXI, Chương II, lớp VII.",
])
def test_so_la_ma_khong_phai_cong_thuc(cau):
    assert "i i" not in h.doc(cau) and "vê" not in h.doc(cau)
    assert all(r in h.doc(cau) for r in ("III", "IV")) if "III" in cau else True


def test_ky_hieu_dung_rieng_doc_ten_nguyen_to():
    """Chủ máy 25/09/2026: "nồng độ K trong máu" — không ai gọi là K, đó là kali; còn
    "0 K" là kelvin (đơn vị ngay sau số)."""
    ra = h.doc("Nồng độ K trong máu là 4,2 mmol/L, còn nhiệt độ đạt 0 K.")
    assert "ka li trong máu" in ra and "0 K." in ra
    assert h.doc("Cho Na vào nước tạo NaOH.") == "Cho nát tri vào nước tạo nờ a ô hát."  # chủ máy 26/09: đọc "nát tri"
    # "↑" chỉ là trạng thái khí, câu vẫn là câu văn (câu thử của chủ máy 25/09/2026)
    assert h.doc("Chị Ba cho Na vào nước, Na phản ứng tạo NaOH và khí H2↑.").startswith(
        "Chị Ba cho nát tri vào nước, nát tri phản ứng")
    assert h.doc("Fe + CuSO4 → FeSO4 + Cu") .startswith("ép e cộng")   # phương trình: đọc kiểu công thức


def test_ma_so_khong_phai_cong_thuc():
    assert h.doc("Hội nghị COP30 và màn hình 4K, Xe điện") == "Hội nghị COP30 và màn hình 4K, Xe điện"
    assert h.doc("Khí CO2 và SO2") == "Khí xê ô hai và ét ô hai"


def test_chu_viet_tat_tu_dien_doc_duoc_khong_phai_cong_thuc():
    """"ThS" (thạc sĩ) có dáng Th + S; từ điển đọc được thành từ thì là chữ viết tắt. Đo
    26/09/2026: 43 công thức không chỉ số từ điển đều đánh vần — chúng vẫn là công thức."""
    biet = {"ThS", "ThS.BS"}.__contains__
    assert h.doc("ThS Lê B khám", chu_viet_tat=biet) == "ThS Lê B khám"
    assert "nờ a xê lờ" in h.doc("Cho NaCl vào", chu_viet_tat=biet)
    assert h.doc_cong_thuc("Mg", chu_viet_tat=lambda t: True) == "ma giê", "ký hiệu đơn không hỏi từ điển"
    assert h.doc("ThS Lê B khám") != "ThS Lê B khám", "không truyền từ điển thì như cũ"


@pytest.mark.parametrize("vao, co, khong", [
    # Chủ máy 26/09/2026: "chả lẽ natri cho natri vào nước được" — lặp trong một vế, lần đầu là người.
    ("Trong giờ thực hành hóa học, Na cho Na vào H2O", "Na cho nát tri vào", None),
    ("Ba cho Ba vào dung dịch H₂SO₄ loãng.", "Ba cho ba_ri", None),
    ("Na đang tìm hiểu vai trò của Na trong cơ thể, còn H2O thì không.", "Na đang tìm hiểu vai trò của nát tri", None),
    # Hai vế nói cùng một chất; phương trình — không áp.
    ("Na phản ứng mãnh liệt với H2O, cần bảo quản Na trong dầu hoả.", "nát tri phản ứng", "Na phản ứng"),
    ("Na → Na⁺ + e⁻", None, "Na tạo"),
])
def test_ky_hieu_lap_trong_mot_ve_lan_dau_la_nguoi(vao, co, khong):
    ra = h.doc(vao).replace("ba ri", "ba_ri")
    assert co is None or co in ra, ra
    assert khong is None or khong not in ra, ra
