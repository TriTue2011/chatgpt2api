"""Test capability dang_facebook / facebook_trang_thai + menu /facebook.

Mock ở tầng services.facebook_page (đã có test HTTP riêng) — ở đây chỉ kiểm
luồng chọn page, thông điệp hướng dẫn, và khối <<<ASK>>>.
"""

from __future__ import annotations

import pytest

import services.facebook_page as fbp
from services.agent import capabilities as caps


_PAGES = [
    {"id": "111", "name": "Page Nhà", "access_token": "tokA"},
    {"id": "222", "name": "Page Shop", "access_token": "tokB"},
]


@pytest.mark.pure
def test_dang_ky_capability_va_nhom():
    assert caps.group_of("dang_facebook") == "facebook"
    assert caps.group_of("facebook_trang_thai") == "facebook"
    assert "facebook" in caps.all_groups()
    ten = [s["function"]["name"] for s in caps.tools_schema({"facebook"})]
    assert "dang_facebook" in ten and "facebook_trang_thai" in ten
    # nhóm tắt → tool biến khỏi schema
    ten_khong = [s["function"]["name"] for s in caps.tools_schema({"web"})]
    assert "dang_facebook" not in ten_khong


@pytest.mark.pure
def test_menu_ask_chua_ket_noi_khong_co_khoi_ask(monkeypatch):
    monkeypatch.setattr(fbp, "danh_sach_page", lambda: [])
    menu = fbp.menu_ask("-100")
    assert "<<<ASK>>>" not in menu
    assert "Cài đặt" in menu


@pytest.mark.pure
def test_menu_ask_du_muc_va_canh_bao_chua_gan(monkeypatch):
    monkeypatch.setattr(fbp, "danh_sach_page", lambda: list(_PAGES))
    monkeypatch.setattr(fbp, "pages_cho_thread", lambda uid: [])
    menu = fbp.menu_ask("-100")
    assert "<<<ASK>>>" in menu and "<<<END>>>" in menu
    assert "chưa gắn Page" in menu
    for muc in ("Đăng bài chữ", "Đăng link", "Đăng ảnh", "Đăng video",
                "Nhờ AI soạn bài", "Kiểm tra kết nối"):
        assert muc in menu
    monkeypatch.setattr(fbp, "pages_cho_thread", lambda uid: [_PAGES[0]])
    assert "Đăng lên: Page Nhà" in fbp.menu_ask("-100")


@pytest.mark.pure
def test_handler_chua_ket_noi_va_chua_gan_page(monkeypatch):
    h = caps.CAPABILITIES["dang_facebook"].handler
    monkeypatch.setattr(fbp, "danh_sach_page", lambda: [])
    monkeypatch.setattr(fbp, "pages_cho_thread", lambda uid: [])
    out = h({"loai": "chu", "message": "x"}, {"user_id": "-100"})
    assert "Chưa kết nối" in out["text"]
    monkeypatch.setattr(fbp, "danh_sach_page", lambda: list(_PAGES))
    out = h({"loai": "chu", "message": "x"}, {"user_id": "-100"})
    assert "chưa gắn Page" in out["text"]


@pytest.mark.pure
def test_handler_nhieu_page_tra_menu_chon_deliver_now(monkeypatch):
    h = caps.CAPABILITIES["dang_facebook"].handler
    monkeypatch.setattr(fbp, "pages_cho_thread", lambda uid: list(_PAGES))
    out = h({"loai": "chu", "message": "dòng một\ndòng hai"}, {"user_id": "-100"})
    assert out.get("deliver_now") is True
    assert "<<<ASK>>>" in out["text"]
    assert "đăng lên facebook page 111" in out["text"]
    assert "đăng lên facebook page 222" in out["text"]
    # nội dung nhồi vào send phải về MỘT dòng (luật _mot_dong của khối ASK)
    dong_send = [d for d in out["text"].splitlines() if "page 111" in d]
    assert "dòng một dòng hai" in dong_send[0]


@pytest.mark.pure
def test_handler_mot_page_dang_chu_goi_dung_ham(monkeypatch):
    h = caps.CAPABILITIES["dang_facebook"].handler
    goi = {}

    def _fake_dang_bai_chu(page_id, noi_dung, link=""):
        goi.update({"page": page_id, "msg": noi_dung, "link": link})
        return {"id": "111_5", "url": "https://fb.com/p/5"}

    monkeypatch.setattr(fbp, "pages_cho_thread", lambda uid: [_PAGES[0]])
    monkeypatch.setattr(fbp, "dang_bai_chu", _fake_dang_bai_chu)
    out = h({"loai": "chu", "message": "chào cả nhà"}, {"user_id": "-100"})
    assert goi == {"page": "111", "msg": "chào cả nhà", "link": ""}
    assert "✅ Đã đăng lên Page Nhà" in out["text"]
    assert "https://fb.com/p/5" in out["text"]


@pytest.mark.pure
def test_handler_thieu_du_lieu_hoi_lai_khong_dang(monkeypatch):
    h = caps.CAPABILITIES["dang_facebook"].handler
    monkeypatch.setattr(fbp, "pages_cho_thread", lambda uid: [_PAGES[0]])
    da_goi = []
    for f in ("dang_bai_chu", "dang_anh", "dang_video"):
        monkeypatch.setattr(fbp, f, lambda *a, **k: da_goi.append(1))
    assert "nội dung" in h({"loai": "chu"}, {"user_id": "-1"})["text"]
    assert "ảnh" in h({"loai": "anh"}, {"user_id": "-1"})["text"]
    assert "video" in h({"loai": "video"}, {"user_id": "-1"})["text"]
    assert "link" in h({"loai": "link"}, {"user_id": "-1"})["text"]
    assert not da_goi


@pytest.mark.pure
def test_handler_loi_facebook_dich_va_nhac_noi_lai(monkeypatch):
    h = caps.CAPABILITIES["dang_facebook"].handler
    monkeypatch.setattr(fbp, "pages_cho_thread", lambda uid: [_PAGES[0]])

    def _no(page_id, noi_dung, link=""):
        raise fbp.LoiFacebook("Token Facebook hết hạn", can_noi_lai=True)

    monkeypatch.setattr(fbp, "dang_bai_chu", _no)
    out = h({"loai": "chu", "message": "x"}, {"user_id": "-1"})
    assert "❌" in out["text"] and "Kết nối lại" in out["text"]


@pytest.mark.pure
def test_handler_suy_loai_tu_du_lieu(monkeypatch):
    h = caps.CAPABILITIES["dang_facebook"].handler
    monkeypatch.setattr(fbp, "pages_cho_thread", lambda uid: [_PAGES[0]])
    nhan = {}
    monkeypatch.setattr(fbp, "dang_anh",
                        lambda page_id, urls, caption="": nhan.update(
                            {"urls": urls, "cap": caption}) or
                        {"id": "x", "url": "u"})
    out = h({"message": "cap", "media_urls": ["https://x/1.jpg"]},
            {"user_id": "-1"})
    assert nhan["urls"] == ["https://x/1.jpg"]
    assert "✅" in out["text"]
