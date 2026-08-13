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


@pytest.mark.pure
def test_cau_duyet_hien_link_va_media_khong_chi_loi_dan():
    """Duyệt bài link mà chỉ thấy lời dẫn thì không biết mình đẩy link nào."""
    from services.agent import approval_gate as ag
    s = ag.summarize_action(
        "dang_facebook",
        {"loai": "link", "message": "Repo hay nè",
         "link": "https://github.com/colbymchenry/codegraph"})
    assert "Repo hay nè" in s
    assert "https://github.com/colbymchenry/codegraph" in s

    v = ag.summarize_action(
        "dang_facebook",
        {"loai": "video", "message": "clip nè",
         "media_urls": ["https://cdn/x.mp4"]})
    assert "https://cdn/x.mp4" in v

    # Bài chữ trần: vẫn chỉ là nội dung, không đẻ thêm dòng rỗng
    assert ag.summarize_action(
        "dang_facebook", {"loai": "chu", "message": "Chào cả nhà"}) == "Chào cả nhà"


@pytest.mark.pure
def test_cau_duyet_khong_cat_mat_link_khi_loi_dan_dai():
    """Lời dẫn dài không được đẩy link ra ngoài phần bị cắt."""
    from services.agent import approval_gate as ag
    s = ag.summarize_action(
        "dang_facebook",
        {"loai": "link", "message": "x" * 600, "link": "https://vd.com/bai-viet"})
    assert "https://vd.com/bai-viet" in s


@pytest.mark.pure
def test_cau_duyet_capability_khac_giu_nguyen():
    """Chỉ thêm nhánh cho dang_facebook — tool khác giữ nguyên cách tóm tắt."""
    from services.agent import approval_gate as ag
    assert ag.summarize_action("send_to_contact",
                               {"to": "Mẹ", "message": "con về muộn"}) == "→ Mẹ: con về muộn"
    assert ag.summarize_action("control_home", {"command": "bật đèn"}) == "bật đèn"


@pytest.mark.pure
def test_dang_xong_nho_bai_va_moi_chia_se_nhom(monkeypatch):
    """Đăng Page xong: nhớ bài cho «chia sẻ vào nhóm», auto tắt → gắn nút hỏi."""
    import services.facebook_group as fbg
    h = caps.CAPABILITIES["dang_facebook"].handler
    monkeypatch.setattr(fbp, "pages_cho_thread", lambda uid: [_PAGES[0]])
    monkeypatch.setattr(fbp, "dang_bai_chu",
                        lambda p, m, link="": {"id": "111_5",
                                               "url": "https://fb.com/p/5"})
    monkeypatch.setattr(fbg, "nap_nhom", lambda: [{"id": "g1", "name": "g1"}])
    monkeypatch.setattr(fbg, "auto_share_bat", lambda: False)
    fbg._bai_cuoi.clear()
    out = h({"loai": "link", "message": "bài", "link": "https://vd.com"},
            {"user_id": "u7"})
    assert "Chia sẻ vào 1 nhóm" in out["text"]
    assert "__fb_nhom__:chia_se" in out["text"]
    # bài được nhớ với link GỐC (không phải permalink) để nhóm có giá trị thật
    p = fbg.bai_cuoi("u7")
    assert p["message"] == "bài" and p["link"] == "https://vd.com"


@pytest.mark.pure
def test_dang_xong_auto_bat_thi_chia_se_ngay(monkeypatch):
    import services.facebook_group as fbg
    h = caps.CAPABILITIES["dang_facebook"].handler
    monkeypatch.setattr(fbp, "pages_cho_thread", lambda uid: [_PAGES[0]])
    monkeypatch.setattr(fbp, "dang_bai_chu",
                        lambda p, m, link="": {"id": "111_5",
                                               "url": "https://fb.com/p/5"})
    monkeypatch.setattr(fbg, "nap_nhom", lambda: [{"id": "g1", "name": "g1"}])
    monkeypatch.setattr(fbg, "auto_share_bat", lambda: True)
    goi = {}

    def _gia(uid, bai, nhom=None):
        goi["bai"] = bai
        return "📤 đang chia sẻ nền"

    monkeypatch.setattr(fbg, "chia_se_nen", _gia)
    out = h({"loai": "chu", "message": "bài chữ"}, {"user_id": "u8"})
    assert "đang chia sẻ nền" in out["text"]
    # bài chữ không có link ngoài → nhóm nhận permalink bài Page
    assert goi["bai"]["link"] == "https://fb.com/p/5"


@pytest.mark.pure
def test_khong_co_nhom_thi_cau_bao_giu_nguyen(monkeypatch):
    """Không cấu hình nhóm → câu báo đăng Page y như trước, không thêm gì."""
    import services.facebook_group as fbg
    h = caps.CAPABILITIES["dang_facebook"].handler
    monkeypatch.setattr(fbp, "pages_cho_thread", lambda uid: [_PAGES[0]])
    monkeypatch.setattr(fbp, "dang_bai_chu",
                        lambda p, m, link="": {"id": "111_5", "url": ""})
    monkeypatch.setattr(fbg, "nap_nhom", lambda: [])
    out = h({"loai": "chu", "message": "bài"}, {"user_id": "u9"})
    assert out["text"] == "✅ Đã đăng lên Page Nhà."
