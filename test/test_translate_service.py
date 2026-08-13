"""Client LibreTranslate + lệnh /dich — owner duy nhất của hai concern này.

Không kiểm trục dịch quanh LLM (xem `test_translate_pivot.py`).
"""

from __future__ import annotations

import pytest

from services import translate_service as ts
from test._fakes import FakeTranslate, install_translate


@pytest.fixture(autouse=True)
def _co_may_chu_dich(monkeypatch):
    """Mọi test ở đây coi như đã cấu hình máy chủ dịch trong stack."""
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "http://libretranslate:5000")
    monkeypatch.setitem(config.data, "translate_api_key", "")


# ── Nhận lệnh ───────────────────────────────────────────────────────────────


@pytest.mark.pure
@pytest.mark.parametrize("text", [
    "/dich hello world",
    "/dịch hello world",
    "/translate hello",
    "/tr hello",
    "/dich@BenBapBot hello",
    "@BenBapBot /dich hello",
    "  /dich  hello  ",
    # Lệnh rồi XUỐNG DÒNG dán cả khối — khuôn tin thật 13/08 trên Zalo cá nhân.
    "/dich\naction: ai_task.generate_data\ndata:\n  task_name: Generate content",
])
def test_nhan_moi_dang_lenh_dich(text):
    assert ts.la_lenh_dich(text) is True


@pytest.mark.pure
@pytest.mark.parametrize("text", [
    "", "dich hello", "/dichvu abc", "hôm nay trời thế nào", "/id", "@BenBapBot xin chào",
])
def test_khong_nhan_lam_lenh_dich(text):
    assert ts.la_lenh_dich(text) is False


@pytest.mark.pure
def test_bo_tag_dau_khong_an_ten_mien_email():
    """photo_intent.bo_tag xoá mọi '@…' nên nó ăn luôn tên miền email — với lệnh
    dịch thì đó là làm hỏng chính thứ cần dịch."""
    ra = ts._bo_tag_dau("@BenBapBot /dich mail cho john@example.com")
    assert ra == "/dich mail cho john@example.com"


# ── Bảo vệ đoạn không được dịch ─────────────────────────────────────────────


@pytest.mark.pure
def test_tach_doan_giu_khoi_ma_url_email_marker():
    text = (
        "Chạy thử đoạn này:\n"
        "```python\nprint('xin chào')\n```\n"
        "Xem thêm https://example.com/a?b=1 hoặc mail john@example.com, "
        "biến `x_channel` và ảnh image://abc123 nhé."
    )
    giu = [s for dich_duoc, s in ts._tach_doan(text) if not dich_duoc]
    assert "```python\nprint('xin chào')\n```" in giu
    assert "https://example.com/a?b=1" in giu
    assert "john@example.com" in giu
    assert "`x_channel`" in giu
    assert "image://abc123" in giu


@pytest.mark.adapter
def test_translate_khong_gui_khoi_ma_len_may_chu():
    text = "Sửa hàm này:\n```py\nprint(1)\n```\nrồi chạy lại."
    with install_translate(FakeTranslate(lang="vi")) as fake:
        ra = ts.translate(text, "en", "vi")
    assert "```py\nprint(1)\n```" in ra          # khối mã còn nguyên trong kết quả
    assert all("print(1)" not in x for x in fake.da_gui)  # và chưa từng bay lên


@pytest.mark.adapter
def test_giu_bo_xuong_markdown():
    """Không chừa markup ra thì Argos ăn luôn cấu trúc: "## Tiêu đề" mất dấu
    thăng, "- mục" mất gạch đầu dòng, bảng mất cột. Bản dịch vẫn đúng nghĩa nhưng
    hiện ra là một khối chữ liền — với câu trả lời có bảng thì mất sạch thông tin
    sắp xếp."""
    text = (
        "## Báo cáo quý ba\n"
        "\n"
        "- Doanh thu tăng\n"
        "- Chi phí giảm\n"
        "\n"
        "1. Bước một\n"
        "2. Bước hai\n"
        "\n"
        "| Tháng | Doanh thu |\n"
        "|-------|-----------|\n"
        "| Bảy | 100 |\n"
        "\n"
        "> Ghi chú quan trọng\n"
        "\n"
        "---\n"
    )
    with install_translate(FakeTranslate(lang="vi")):
        ra = ts.translate(text, "en", "vi")
    for xuong in ("## ", "- ", "1. ", "2. ", "|", "> ", "---"):
        assert xuong in ra, f"mất markup {xuong!r}"
    # Cấu trúc dòng giữ nguyên: cùng số dòng, đúng thứ tự
    assert ra.count("\n") == text.count("\n")
    assert ra.splitlines()[0].startswith("## ")
    assert ra.splitlines()[2].startswith("- ")
    # Và chữ bên trong thì ĐÃ được dịch
    assert "en:" in ra


@pytest.mark.adapter
def test_o_bang_duoc_dich_rieng_tung_o():
    with install_translate(FakeTranslate(lang="vi")) as fake:
        ts.translate("| Tháng | Doanh thu |", "en", "vi")
    assert [x.strip() for x in fake.da_gui] == ["Tháng", "Doanh thu"]


@pytest.mark.adapter
def test_translate_gop_moi_doan_vao_mot_luot_goi():
    """Một câu có 3 đoạn dịch-được vẫn chỉ tốn ĐÚNG một POST /translate (q dạng
    danh sách) — không phải 3 lượt HTTP."""
    text = "Mở `app.py` rồi xem https://a.vn và sửa lại."
    with install_translate(FakeTranslate(lang="vi")) as fake:
        ts.translate(text, "en", "vi")
    assert sum(1 for path, _ in fake.calls if path == "/translate") == 1


@pytest.mark.adapter
def test_translate_batch_dung_bo_dem_lan_sau():
    with install_translate(FakeTranslate(lang="vi")) as fake:
        assert ts.translate_batch(["xin chào"], "en", "vi") == ["en:xin chào"]
        assert ts.translate_batch(["xin chào"], "en", "vi") == ["en:xin chào"]
    assert fake.da_gui == ["xin chào"]  # lượt hai lấy từ bộ đệm


@pytest.mark.adapter
def test_translate_batch_bo_qua_chuoi_rong():
    with install_translate(FakeTranslate(lang="vi")) as fake:
        ra = ts.translate_batch(["", "  ", "xin chào"], "en", "vi")
    assert ra == ["", "  ", "en:xin chào"]
    assert fake.da_gui == ["xin chào"]


@pytest.mark.adapter
def test_translate_batch_bao_loi_khi_may_chu_tra_thieu_doan():
    class LechSo(FakeTranslate):
        def goi(self, path, payload=None):
            if path == "/translate":
                return {"translatedText": ["chỉ một"]}
            return super().goi(path, payload)

    with install_translate(LechSo()):
        with pytest.raises(ts.LoiDich):
            ts.translate_batch(["a", "b"], "en", "vi")


# ── Ngôn ngữ đích ───────────────────────────────────────────────────────────


@pytest.mark.adapter
@pytest.mark.parametrize("arg,ma,con_lai", [
    ("en xin chào", "en", "xin chào"),
    ("vi good morning", "vi", "good morning"),
    ("tiếng anh xin chào", "en", "xin chào"),
    ("Tiếng Anh xin chào", "en", "xin chào"),
    ("tiếng việt hello", "vi", "hello"),
    # "ja" hợp cú pháp nhưng máy chủ chỉ nạp en,vi → là NỘI DUNG
    ("ja xin chào", "", "ja xin chào"),
    ("xin chào cả nhà", "", "xin chào cả nhà"),
])
def test_phan_giai_ngon_ngu_dich(arg, ma, con_lai):
    with install_translate(FakeTranslate(codes=("en", "vi"))):
        assert ts._phan_giai_dich(arg) == (ma, con_lai)


@pytest.mark.adapter
@pytest.mark.parametrize("cau", [
    "anh ơi giúp em với",       # "anh" = đại từ, KHÔNG phải tiếng Anh
    "đức tính tốt của em ấy",   # "đức" = phẩm chất, KHÔNG phải tiếng Đức
    "hoa này tên gì",           # "hoa" = bông hoa, KHÔNG phải tiếng Hoa
])
def test_ten_ngon_ngu_tro_khong_bi_hieu_thanh_ngon_ngu_dich(cau):
    """Tên ngôn ngữ trong tiếng Việt gần như đều là từ thông dụng. Chỉ nhận sau
    chữ "tiếng"; nhận tên trơ là cắt mất chữ đầu câu của người dùng."""
    with install_translate(FakeTranslate(codes=("en", "vi", "de", "zh"))):
        assert ts._phan_giai_dich(cau) == ("", cau)


@pytest.mark.adapter
def test_phan_giai_khong_chan_oan_khi_may_chu_chua_doc_duoc_languages():
    """/languages lỗi (máy chủ đang tải model) thì vẫn tin mã ISO —
    /translate sẽ tự báo nếu mã sai. Chặn ở client lúc đó là chặn oan."""
    with install_translate(FakeTranslate(loi="đang tải model")):
        assert ts._phan_giai_dich("ja こんにちは") == ("ja", "こんにちは")


# ── Bốn cặp đang dựng: en⇄vi, vi⇄ja, vi⇄ko, vi⇄zh ──────────────────────────

#: Đúng những mã `/languages` khai khi LT_LOAD_ONLY="en,vi,ja,ko,zh". Chú ý
#: `zh-Hans` chứ không phải `zh`: LibreTranslate đổi tên mã model khi trả ra
#: (bảng `aliases` trong libretranslate/language.py).
_MA_DANG_NAP = ("en", "vi", "ja", "ko", "zh-Hans")


@pytest.mark.adapter
@pytest.mark.parametrize("cau,ma,con_lai", [
    ("ja xin chào", "ja", "xin chào"),
    ("ko xin chào", "ko", "xin chào"),
    ("tiếng nhật xin chào", "ja", "xin chào"),
    ("tiếng hàn xin chào", "ko", "xin chào"),
    # "trung"/"hoa" phải ra mã máy chủ ĐANG KHAI, không phải mã model "zh"
    ("tiếng trung xin chào", "zh-hans", "xin chào"),
    ("tiếng hoa xin chào", "zh-hans", "xin chào"),
    # Người dùng gõ thẳng mã model, hoặc mã đầy đủ, đều phải nhận
    ("zh xin chào", "zh-hans", "xin chào"),
    ("zh-Hans xin chào", "zh-hans", "xin chào"),
    # Thái KHÔNG nạp → "th" là NỘI DUNG, không phải ngôn ngữ đích
    ("th xin chào", "", "th xin chào"),
])
def test_bon_cap_dang_dung(cau, ma, con_lai):
    with install_translate(FakeTranslate(codes=_MA_DANG_NAP)):
        assert ts._phan_giai_dich(cau) == (ma, con_lai)


@pytest.mark.adapter
def test_khong_doan_khi_may_chu_nap_ca_hai_bien_the_chu_han():
    """Nạp cả zh-Hans và zh-Hant thì "tiếng trung" vẫn phải ra GIẢN THỂ. Đoán sai
    biến thể chữ Hán là trả về thứ người dùng không đọc được."""
    with install_translate(FakeTranslate(codes=("en", "vi", "zh-Hans", "zh-Hant"))):
        assert ts._phan_giai_dich("tiếng trung a")[0] == "zh-hans"
        assert ts._phan_giai_dich("zt a")[0] == "zh-hant"


@pytest.mark.adapter
def test_lenh_dich_viet_sang_nhat():
    with install_translate(FakeTranslate(lang="vi", codes=_MA_DANG_NAP)):
        ra = ts.lenh_dich("/dich tiếng nhật xin chào")
    assert "vi → ja" in ra and "ja:xin chào" in ra


@pytest.mark.adapter
def test_lenh_dich_trung_sang_viet_tu_nhan_dien():
    """Chiều Trung→Việt: /detect của máy chủ trả mã ĐÃ đổi tên (zh-Hans), mã đó
    phải đi thẳng vào /translate mà không bị client chặn."""
    with install_translate(FakeTranslate(lang="zh-Hans", codes=_MA_DANG_NAP)) as fake:
        ra = ts.lenh_dich("/dich 你好")
    assert "zh-hans → vi" in ra and "vi:你好" in ra
    assert fake.calls[-1][1]["source"] == "zh-hans"
    assert fake.calls[-1][1]["target"] == "vi"


# ── Lệnh /dich đầu-cuối ─────────────────────────────────────────────────────


@pytest.mark.adapter
def test_lenh_dich_viet_sang_anh_khi_khong_chi_dinh_dich():
    with install_translate(FakeTranslate(lang="vi", confidence=97.0)):
        ra = ts.lenh_dich("/dich xin chào cả nhà")
    assert "vi → en" in ra
    assert "en:xin chào cả nhà" in ra


@pytest.mark.adapter
def test_lenh_dich_ngoai_ngu_sang_viet_khi_khong_chi_dinh_dich():
    with install_translate(FakeTranslate(lang="en", confidence=99.0)):
        ra = ts.lenh_dich("/dich good morning")
    assert "en → vi" in ra
    assert "vi:good morning" in ra


@pytest.mark.adapter
def test_lenh_dich_theo_ngon_ngu_chi_dinh():
    with install_translate(FakeTranslate(lang="vi")) as fake:
        ra = ts.lenh_dich("/dich en xin chào")
    assert "en:xin chào" in ra
    assert fake.da_gui == ["xin chào"]  # token "en" không bị dịch theo


@pytest.mark.adapter
def test_lenh_dich_khong_co_noi_dung_thi_tro_giup():
    with install_translate(FakeTranslate()):
        ra = ts.lenh_dich("/dich")
    assert "Dịch văn bản" in ra
    assert "en" in ra and "vi" in ra


@pytest.mark.adapter
def test_lenh_dich_noi_ro_khi_da_dung_ngon_ngu():
    with install_translate(FakeTranslate(lang="vi")):
        ra = ts.lenh_dich("/dich vi xin chào")
    assert "đã là" in ra


@pytest.mark.adapter
def test_lenh_dich_bao_loi_thay_vi_im_lang():
    with install_translate(FakeTranslate(loi="Connection refused")):
        ra = ts.lenh_dich("/dich hello")
    assert "lỗi" in ra.lower()
    assert "Connection refused" in ra


@pytest.mark.pure
def test_lenh_dich_chua_cau_hinh_thi_chi_duong(monkeypatch):
    from services.config import config

    monkeypatch.delenv("TRANSLATE_URL", raising=False)
    monkeypatch.setitem(config.data, "translate_url", "")
    ra = ts.lenh_dich("/dich hello")
    assert "translate_url" in ra
    assert ts.is_configured() is False


# ── Bật bằng compose: biến môi trường là đủ, không sửa config.json ─────────


@pytest.mark.pure
def test_chi_can_bien_moi_truong_la_dich_chay(monkeypatch):
    """Mục đích của cả thay đổi này: `docker compose up -d` là xong. Compose khai
    TRANSLATE_URL cho service c2a; config.json không có khoá nào."""
    from services.config import config

    monkeypatch.delitem(config.data, "translate_url", raising=False)
    monkeypatch.setenv("TRANSLATE_URL", "http://libretranslate:5000")
    assert ts.is_configured() is True
    assert config.translate_url == "http://libretranslate:5000"


@pytest.mark.pure
def test_bien_moi_truong_thang_config_json(monkeypatch):
    """Cùng nếp CHATGPT2API_BASE_URL: env đè config.json, để Portainer →
    Environment là nơi chốt cuối, không phải file trong volume."""
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "http://cu:5000")
    monkeypatch.setenv("TRANSLATE_URL", "http://moi:5000")
    assert config.translate_url == "http://moi:5000"


@pytest.mark.pure
def test_xoa_bien_moi_truong_la_tat_han(monkeypatch):
    from services.config import config

    monkeypatch.delitem(config.data, "translate_url", raising=False)
    monkeypatch.setenv("TRANSLATE_URL", "")
    assert ts.is_configured() is False


@pytest.mark.pure
def test_truc_dich_bat_duoc_bang_bien_moi_truong(monkeypatch):
    from services import translate_pivot as tp
    from services.config import config

    monkeypatch.setenv("TRANSLATE_URL", "http://libretranslate:5000")
    monkeypatch.delitem(config.data, "translate_pivot_enabled", raising=False)
    monkeypatch.delenv("TRANSLATE_PIVOT", raising=False)
    assert tp.dang_bat() is False          # mặc định compose: TRANSLATE_PIVOT=0
    monkeypatch.setenv("TRANSLATE_PIVOT", "0")
    assert tp.dang_bat() is False
    monkeypatch.setenv("TRANSLATE_PIVOT", "1")
    assert tp.dang_bat() is True


# ── Cặp ngôn ngữ của tab Dịch web ───────────────────────────────────────────


@pytest.mark.pure
@pytest.mark.parametrize("nguon, target, cho_doi", [
    ("vi", "", "en"), ("en", "", "vi"), ("zh", "", "vi"),   # mặc định Việt↔Anh
    ("vi", "cap:zh", "zh"), ("zh", "cap:zh", "vi"),          # cặp Việt↔Trung
    ("en", "cap:zh", "vi"),   # nguồn NGOÀI cặp → về tiếng Việt
    ("vi", "cap:ja", "ja"), ("ja", "cap:ja", "vi"),
    ("vi", "cap:ko", "ko"), ("ko", "cap:ko", "vi"),
    ("vi", "en", "en"), ("en", "vi", "vi"),                  # mã trơ giữ nguyên
    ("vi", "cap:", "en"),                                     # cặp rỗng → như en
])
def test_giai_ma_target_theo_cap(nguon, target, cho_doi):
    assert ts.giai_ma_target(nguon, target) == cho_doi
