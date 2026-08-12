"""Dịch TỆP và ẢNH — owner duy nhất của concern này.

Không kiểm client/lệnh /dich (`test_translate_service.py`) hay trục dịch quanh
LLM (`test_translate_pivot.py`).
"""

from __future__ import annotations

import pytest

from services import translate_service as ts
from test._fakes import FakeTranslate, install_translate


@pytest.fixture(autouse=True)
def _co_may_chu_dich(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "http://libretranslate:5000")
    monkeypatch.setitem(config.data, "translate_api_key", "")
    monkeypatch.setitem(config.data, "translate_docx_threshold", 3000)


@pytest.fixture
def chu_trong_tep(monkeypatch):
    """Thay bộ đọc tài liệu (pdf-inspector/OCR/markitdown) bằng chuỗi cố định."""
    def _dat(chu: str):
        monkeypatch.setattr(ts, "_trich_chu_tep", lambda _p: chu)
    return _dat


# ── Định dạng máy chủ dịch được ─────────────────────────────────────────────


@pytest.mark.adapter
def test_doc_dinh_dang_tu_may_chu_chu_khong_doan():
    with install_translate(FakeTranslate(dinh_dang_tep=(".txt", ".docx"))):
        assert ts.dinh_dang_tep_ho_tro() == (".txt", ".docx")


@pytest.mark.adapter
def test_admin_tat_dich_tep_tren_may_chu_thi_khong_con_dinh_dang_nao():
    with install_translate(FakeTranslate(dich_tep_duoc=False)):
        assert ts.dinh_dang_tep_ho_tro() == ()


@pytest.mark.adapter
def test_khong_doc_duoc_settings_thi_dung_bang_du_phong_cua_argos():
    with install_translate(FakeTranslate(loi="đang tải model")):
        assert ts.dinh_dang_tep_ho_tro() == ts.DINH_DANG_TEP_ARGOS
    # PDF và Excel KHÔNG nằm trong đó — argos-translate-files không dựng lại được
    assert ".pdf" not in ts.DINH_DANG_TEP_ARGOS
    assert ".xlsx" not in ts.DINH_DANG_TEP_ARGOS


# ── Tệp giữ nguyên định dạng (docx/pptx/odt/txt/epub/html) ──────────────────


@pytest.mark.adapter
def test_docx_quay_lai_dung_dinh_dang_docx(chu_trong_tep):
    chu_trong_tep("This is an English report about sales.")
    with install_translate(FakeTranslate(lang="en")) as fake:
        r = ts.dich_tep("/tmp/bao-cao.docx", "bao-cao.docx")
    assert r["ok"] and r["kieu"] == "tep"
    assert r["data"] == b"PK-da-dich"
    assert r["nguon"] == "en" and r["dich"] == "vi"
    assert fake.file_calls[0]["target"] == "vi"
    assert fake.file_calls[0]["source"] == "en"


@pytest.mark.adapter
def test_tep_tieng_viet_thi_dich_sang_tieng_anh(chu_trong_tep):
    chu_trong_tep("Báo cáo doanh thu quý ba của công ty.")
    with install_translate(FakeTranslate(lang="vi")) as fake:
        r = ts.dich_tep("/tmp/bao-cao.docx", "bao-cao.docx")
    assert r["dich"] == "en"
    assert fake.file_calls[0]["target"] == "en"


@pytest.mark.adapter
def test_kenh_khong_gui_duoc_tep_thi_buoc_tra_chu(chu_trong_tep):
    """Zalo Bot không gửi tệp — trả kieu='tep' ở đó là bản dịch không có đường
    nào tới tay người dùng."""
    chu_trong_tep("An English report.")
    with install_translate(FakeTranslate(lang="en")) as fake:
        r = ts.dich_tep("/tmp/a.docx", "a.docx", chi_chu=True)
    assert r["kieu"] == "chu"
    assert fake.file_calls == []
    assert r["text"] == "vi:An English report."


# ── PDF / Excel: argos không dựng lại được → trả chữ ───────────────────────


@pytest.mark.adapter
def test_pdf_tra_ve_chu_chu_khong_goi_translate_file(chu_trong_tep):
    chu_trong_tep("Quarterly report for the board.")
    with install_translate(FakeTranslate(lang="en")) as fake:
        r = ts.dich_tep("/tmp/a.pdf", "a.pdf")
    assert r["ok"] and r["kieu"] == "chu"
    assert r["text"] == "vi:Quarterly report for the board."
    assert fake.file_calls == []


@pytest.mark.adapter
def test_khong_doc_duoc_noi_dung_thi_noi_ro(chu_trong_tep):
    chu_trong_tep("")
    with install_translate(FakeTranslate()):
        r = ts.dich_tep("/tmp/a.pdf", "a.pdf")
    assert r["ok"] is False
    assert "không đọc được" in r["error"]


@pytest.mark.adapter
def test_tep_da_dung_ngon_ngu_dich_thi_bao_thay_vi_dich_khong(chu_trong_tep):
    chu_trong_tep("Báo cáo doanh thu.")
    with install_translate(FakeTranslate(lang="vi")):
        r = ts.dich_tep("/tmp/a.pdf", "a.pdf", "vi")
    assert r["ok"] is False and "đã là" in r["error"]


@pytest.mark.pure
def test_chua_cau_hinh_may_chu_thi_khong_lam_gi(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "")
    r = ts.dich_tep("/tmp/a.pdf", "a.pdf")
    assert r["ok"] is False and "translate_url" in r["error"]


# ── Bản dịch dài → gửi bằng .docx ──────────────────────────────────────────


@pytest.mark.adapter
def test_ban_dich_dai_duoc_dong_thanh_docx(chu_trong_tep, monkeypatch):
    """Telegram chặn một tin ở 4096 ký tự: bản dịch tài liệu vài trang gửi bằng
    tin nhắn sẽ bị cắt thành chuỗi tin vụn."""
    from services.config import config

    chu_trong_tep("x" * 200)
    monkeypatch.setitem(config.data, "translate_docx_threshold", 50)
    monkeypatch.setattr(ts, "chu_thanh_docx",
                        lambda text, ten="": (b"DOCX-BYTES", "ban-dich.docx"))
    with install_translate(FakeTranslate(lang="en")):
        r = ts.dich_tep("/tmp/a.pdf", "a.pdf")
    assert r["kieu"] == "tep" and r["data"] == b"DOCX-BYTES"
    assert r["ten"].endswith(".docx")
    assert r["text"]            # vẫn giữ bản chữ để kênh nào không gửi được tệp thì rơi về


@pytest.mark.adapter
def test_duoi_nguong_thi_van_gui_bang_tin_nhan(chu_trong_tep):
    chu_trong_tep("short")
    with install_translate(FakeTranslate(lang="en")):
        r = ts.dich_tep("/tmp/a.pdf", "a.pdf")
    assert r["kieu"] == "chu"


@pytest.mark.adapter
def test_nguong_bang_khong_thi_luon_gui_tin_nhan(chu_trong_tep, monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_docx_threshold", 0)
    chu_trong_tep("y" * 9000)
    with install_translate(FakeTranslate(lang="en")):
        r = ts.dich_tep("/tmp/a.pdf", "a.pdf")
    assert r["kieu"] == "chu"


@pytest.mark.adapter
def test_dung_docx_loi_thi_roi_ve_gui_chu(chu_trong_tep, monkeypatch):
    """Thiếu python-docx không được phép làm mất luôn bản dịch."""
    from services.config import config

    monkeypatch.setitem(config.data, "translate_docx_threshold", 10)
    chu_trong_tep("z" * 500)

    def _no(*_a, **_k):
        raise RuntimeError("No module named 'docx'")

    monkeypatch.setattr(ts, "chu_thanh_docx", _no)
    with install_translate(FakeTranslate(lang="en")):
        r = ts.dich_tep("/tmp/a.pdf", "a.pdf")
    assert r["ok"] and r["kieu"] == "chu" and r["text"]


# ── Ảnh: OCR bằng vision rồi dịch ──────────────────────────────────────────


@pytest.mark.adapter
def test_dich_chu_trong_anh(monkeypatch):
    from services import photo_intent

    ghi: dict = {}

    def _ocr(_data, prompt, **kw):
        ghi.update(kw)
        ghi["prompt"] = prompt
        return "STOP\nNo entry"

    monkeypatch.setattr(photo_intent, "analyze_photo", _ocr)
    with install_translate(FakeTranslate(lang="en")):
        r = ts.dich_anh(b"\x89PNG")
    assert r["ok"] and r["kieu"] == "chu"
    assert r["text"] == "vi:STOP\nNo entry"
    assert r["goc"] == "STOP\nNo entry"
    # Câu neo tiếng Việt PHẢI tắt, kẻo model tự dịch ảnh rồi máy dịch nhận vào
    # một bản đã Việt hoá.
    assert ghi["neo_tieng_viet"] is False


@pytest.mark.adapter
def test_anh_khong_co_chu_thi_noi_ro(monkeypatch):
    from services import photo_intent

    monkeypatch.setattr(photo_intent, "analyze_photo",
                        lambda *_a, **_k: "KHONGCOCHU")
    with install_translate(FakeTranslate()):
        r = ts.dich_anh(b"\x89PNG")
    assert r["ok"] is False and "không thấy chữ" in r["error"]


@pytest.mark.adapter
def test_vision_loi_thi_khong_nem_ra_ngoai(monkeypatch):
    from services import photo_intent

    def _no(*_a, **_k):
        raise RuntimeError("vision down")

    monkeypatch.setattr(photo_intent, "analyze_photo", _no)
    with install_translate(FakeTranslate()):
        r = ts.dich_anh(b"\x89PNG")
    assert r["ok"] is False and "vision down" in r["error"]


# ── Chi tiết giao thức /translate_file ─────────────────────────────────────


@pytest.mark.pure
@pytest.mark.parametrize("url,cho_doi", [
    ("http://localhost:5000/download_file/abc.docx", "/download_file/abc.docx"),
    ("http://libretranslate:5000/download_file/a.txt?x=1", "/download_file/a.txt?x=1"),
    ("", ""),
])
def test_chi_lay_duong_dan_cua_url_may_chu_tra_ve(url, cho_doi):
    """URL đó do Flask dựng từ header Host — sau reverse proxy nó có thể trỏ
    localhost, địa chỉ gateway không gọi tới được. Đường dẫn thì luôn đúng."""
    assert ts._duong_tai(url) == cho_doi


@pytest.mark.integration
def test_multipart_dung_khuon_form_data(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"hello")
    body, ranh = ts._multipart(str(p), "a.txt", {"source": "en", "target": "vi"})
    assert body.startswith(f"--{ranh}".encode())
    assert b'name="source"' in body and b"en" in body
    assert b'name="target"' in body
    assert b'name="file"; filename="a.txt"' in body
    assert b"hello" in body
    assert body.endswith(f"--{ranh}--\r\n".encode())
