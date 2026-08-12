"""Test services/facebook_page.py — client Graph API (seam S1: httpx.MockTransport).

Không gọi mạng thật: mọi request đi qua `facebook_page._transport`.
"""

from __future__ import annotations

import json

import httpx
import pytest

import services.facebook_page as fb


class _FakeConfig:
    def __init__(self, data=None, base_url="https://bot.example.com"):
        self.data = dict(data or {})
        self.base_url = base_url

    def get(self):
        return self.data

    def update(self, d):
        self.data.update(d)
        return self.data


def _lap(monkeypatch, cfg: _FakeConfig, handler):
    monkeypatch.setattr(fb, "config", cfg)
    monkeypatch.setattr(fb, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(fb.time, "sleep", lambda *_: None)


_CFG_DAY_DU = {
    "facebook": {
        "app_id": "ap1", "app_secret": "s3cret", "user_token": "ngan",
        "pages": [
            {"id": "111", "name": "Page Nhà", "access_token": "tokA"},
            {"id": "222", "name": "Page Shop", "access_token": "tokB"},
        ],
        "thread_pages": {"tg:-100": ["222"], "tg:-100#7": ["111"]},
    },
}


# ── Lỗi & retry ──────────────────────────────────────────────────────────────

@pytest.mark.adapter
def test_loi_khong_thoang_qua_nem_ngay_va_dich_tieng_viet(monkeypatch):
    dem = {"n": 0}

    def handler(request):
        dem["n"] += 1
        return httpx.Response(400, json={"error": {
            "message": "raw", "code": 368, "error_subcode": 1390008}})

    _lap(monkeypatch, _FakeConfig(_CFG_DAY_DU), handler)
    with pytest.raises(fb.LoiFacebook) as exc:
        fb.goi_graph("POST", "111/feed", {"message": "hi"}, token="tokA")
    assert "Đăng quá nhanh" in str(exc.value)
    assert dem["n"] == 1  # subcode nội dung — thử lại vô ích


@pytest.mark.adapter
def test_token_hong_gan_co_can_noi_lai(monkeypatch):
    def handler(request):
        return httpx.Response(400, json={"error": {
            "message": "Error validating access token", "code": 190}})

    _lap(monkeypatch, _FakeConfig(_CFG_DAY_DU), handler)
    with pytest.raises(fb.LoiFacebook) as exc:
        fb.goi_graph("GET", "me", token="tokA")
    assert exc.value.can_noi_lai
    assert "nối lại" in str(exc.value)


@pytest.mark.adapter
def test_loi_thoang_qua_duoc_thu_lai_roi_thanh_cong(monkeypatch):
    dem = {"n": 0}

    def handler(request):
        dem["n"] += 1
        if dem["n"] == 1:
            return httpx.Response(500, json={"error": {
                "message": "tam thoi", "code": 2, "is_transient": True}})
        return httpx.Response(200, json={"id": "111_9"})

    _lap(monkeypatch, _FakeConfig(_CFG_DAY_DU), handler)
    out = fb.goi_graph("POST", "111/feed", {"message": "hi"}, token="tokA")
    assert out["id"] == "111_9"
    assert dem["n"] == 2


@pytest.mark.adapter
def test_appsecret_proof_di_kem_moi_loi_goi(monkeypatch):
    thay = {}

    def handler(request):
        thay.update(httpx.QueryParams(request.url.query))
        return httpx.Response(200, json={"id": "x"})

    _lap(monkeypatch, _FakeConfig(_CFG_DAY_DU), handler)
    fb.goi_graph("GET", "me", token="tokA")
    assert thay.get("access_token") == "tokA"
    assert len(thay.get("appsecret_proof", "")) == 64  # hex sha256


# ── Kết nối: đổi token + nạp page ────────────────────────────────────────────

@pytest.mark.adapter
def test_ket_noi_doi_token_dai_va_luu_pages_phan_trang(monkeypatch):
    cfg = _FakeConfig(_CFG_DAY_DU)

    def handler(request):
        p = request.url.path
        q = httpx.QueryParams(request.url.query)
        if p.endswith("/oauth/access_token"):
            assert q["grant_type"] == "fb_exchange_token"
            assert q["fb_exchange_token"] == "ngan"
            return httpx.Response(200, json={"access_token": "DAI"})
        if p.endswith("/me/accounts"):
            assert q["access_token"] == "DAI"
            if q.get("after"):
                return httpx.Response(200, json={
                    "data": [{"id": "333", "name": "Trang Ba",
                              "access_token": "tokC"}], "paging": {}})
            return httpx.Response(200, json={
                "data": [{"id": "111", "name": "Page Nhà", "access_token": "tokA",
                          "picture": {"data": {"url": "http://pic"}}}],
                "paging": {"cursors": {"after": "CUR"}, "next": "http://next"}})
        raise AssertionError(f"đường lạ: {p}")

    _lap(monkeypatch, cfg, handler)
    pages = fb.ket_noi()
    assert [p["id"] for p in pages] == ["111", "333"]
    da_luu = cfg.data["facebook"]
    assert da_luu["user_token_long"] == "DAI"
    assert da_luu["user_token"] == ""  # token ngắn dùng xong phải xoá
    assert da_luu["pages"][0]["picture"] == "http://pic"


@pytest.mark.pure
def test_ket_noi_thieu_cau_hinh_bao_ro(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig({"facebook": {}}))
    with pytest.raises(fb.LoiFacebook) as exc:
        fb.ket_noi()
    assert "app_id" in str(exc.value)


@pytest.mark.adapter
def test_ket_noi_lam_tuoi_bang_token_dai_han(monkeypatch):
    """user_token ngắn bị xoá sau lần nối trước — bấm «Kết nối» không dán gì
    phải dùng lại user_token_long, không được báo «Chưa đủ … user_token»."""
    cfg = _FakeConfig({"facebook": {
        "app_id": "ap1", "app_secret": "s3cret",
        "user_token": "", "user_token_long": "DAI-CU"}})

    def handler(request):
        p = request.url.path
        q = httpx.QueryParams(request.url.query)
        if p.endswith("/oauth/access_token"):
            assert q["fb_exchange_token"] == "DAI-CU"
            return httpx.Response(200, json={"access_token": "DAI-MOI"})
        if p.endswith("/me/accounts"):
            return httpx.Response(200, json={
                "data": [{"id": "111", "name": "Page Nhà",
                          "access_token": "tokA"}], "paging": {}})
        raise AssertionError(f"đường lạ: {p}")

    _lap(monkeypatch, cfg, handler)
    pages = fb.ket_noi()
    assert [p["id"] for p in pages] == ["111"]
    assert cfg.data["facebook"]["user_token_long"] == "DAI-MOI"


# ── Gắn Page theo thread ─────────────────────────────────────────────────────

@pytest.mark.pure
def test_pages_cho_thread_khoa_hep_thang_rong(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_DAY_DU))
    # topic 7 gắn page 111; nhóm -100 (không topic) gắn page 222
    assert [p["id"] for p in fb.pages_cho_thread("-100#7:u5")] == ["111"]
    assert [p["id"] for p in fb.pages_cho_thread("-100:u5")] == ["222"]


@pytest.mark.pure
def test_thread_chua_gan_nhieu_page_tra_rong_mot_page_dung_luon(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_DAY_DU))
    assert fb.pages_cho_thread("zalop_g99") == []  # 2 page, chưa gắn → bắt gắn
    mot = {"facebook": {**_CFG_DAY_DU["facebook"],
                        "pages": [{"id": "111", "name": "A", "access_token": "t"}],
                        "thread_pages": {}}}
    monkeypatch.setattr(fb, "config", _FakeConfig(mot))
    assert [p["id"] for p in fb.pages_cho_thread("zalop_g99")] == ["111"]


# ── URL media công khai ──────────────────────────────────────────────────────

@pytest.mark.pure
def test_url_cong_khai_chan_host_lan(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_DAY_DU))
    for xau in ("http://172.16.10.38/images/a.jpg",
                "http://127.0.0.1/images/a.jpg", "http://localhost/x.jpg"):
        with pytest.raises(fb.LoiFacebook):
            fb.url_cong_khai(xau)


@pytest.mark.pure
def test_url_cong_khai_ghep_base_va_ky(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_DAY_DU))
    monkeypatch.setattr("services.signed_url.ky_url",
                        lambda u, **k: f"{u}?sig=OK")
    ra = fb.url_cong_khai("/images/2026/08/a.jpg")
    assert ra == "https://bot.example.com/images/2026/08/a.jpg?sig=OK"
    # URL ngoài (không phải host mình) giữ nguyên, không ký
    assert fb.url_cong_khai("https://cdn.zalo.me/v.mp4") == "https://cdn.zalo.me/v.mp4"


# ── Đăng bài ─────────────────────────────────────────────────────────────────

@pytest.mark.adapter
def test_dang_anh_gom_attached_media_mot_bai_feed(monkeypatch):
    cac_goi = []

    def handler(request):
        cac_goi.append((request.url.path, json.loads(request.content or b"{}")))
        if request.url.path.endswith("/photos"):
            return httpx.Response(200, json={"id": f"ph{len(cac_goi)}"})
        return httpx.Response(200, json={"id": "111_88",
                                         "permalink_url": "/111/posts/88"})

    _lap(monkeypatch, _FakeConfig(_CFG_DAY_DU), handler)
    out = fb.dang_anh("111", ["https://cdn.example.com/1.jpg",
                              "https://cdn.example.com/2.jpg"], caption="hai ảnh")
    duong = [p for p, _ in cac_goi]
    assert duong.count("/v23.0/111/photos") == 2
    assert duong[-1] == "/v23.0/111/feed"
    body_feed = cac_goi[-1][1]
    assert body_feed["attached_media"] == [{"media_fbid": "ph1"},
                                           {"media_fbid": "ph2"}]
    assert body_feed["message"] == "hai ảnh"
    assert all(not b.get("published") for _, b in cac_goi[:-1])  # ảnh nạp ẩn
    assert out["url"] == "https://www.facebook.com/111/posts/88"


@pytest.mark.adapter
def test_dang_bai_chu_kem_link(monkeypatch):
    cac_goi = []

    def handler(request):
        cac_goi.append(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={"id": "111_1",
                                         "permalink_url": "https://fb.com/p/1"})

    _lap(monkeypatch, _FakeConfig(_CFG_DAY_DU), handler)
    out = fb.dang_bai_chu("111", "đọc bài này", link="https://blog.example.com/a")
    assert cac_goi[0]["message"] == "đọc bài này"
    assert cac_goi[0]["link"] == "https://blog.example.com/a"
    assert out["url"] == "https://fb.com/p/1"


@pytest.mark.adapter
def test_dang_video_tra_link_reel(monkeypatch):
    def handler(request):
        assert request.url.path == "/v23.0/222/videos"
        body = json.loads(request.content)
        assert body["file_url"] == "https://cdn.example.com/v.mp4"
        return httpx.Response(200, json={"id": "vid9"})

    _lap(monkeypatch, _FakeConfig(_CFG_DAY_DU), handler)
    out = fb.dang_video("222", "https://cdn.example.com/v.mp4", mo_ta="clip")
    assert out == {"id": "vid9", "url": "https://www.facebook.com/reel/vid9"}


@pytest.mark.pure
def test_dang_len_page_chua_nap_bao_ro(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_DAY_DU))
    with pytest.raises(fb.LoiFacebook) as exc:
        fb.dang_bai_chu("999", "x")
    assert "Kết nối lại" in str(exc.value)


# ── Luồng đăng bài CÓ TRẠNG THÁI CHỜ (chữ / link / video-URL) ────────────────
# Bịt lỗi 11/08: sau khi chọn «đăng link» từ menu /facebook, dán URL (repo
# GitHub) thì LLM lạc sang trợ lý code, đứt mạch. Nay code giữ trạng thái chờ.

_CFG_1PAGE = {"facebook": {"pages": [
    {"id": "111", "name": "Blog cá nhân", "access_token": "tokA"}]}}


@pytest.mark.pure
def test_menu_ask_dung_sentinel_cho_chu_link_video(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    menu = fb.menu_ask("zalop_1")
    assert fb.FLOW_CHU in menu
    assert fb.FLOW_LINK in menu
    assert fb.FLOW_VIDEO in menu


@pytest.mark.pure
def test_flow_dang_chu_bat_input_thang(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_chu"
    fb.xoa_flow(k)
    nhac = fb.bat_dau_flow(k, fb.FLOW_CHU)
    assert nhac and "NỘI DUNG" in nhac
    assert fb.co_flow(k)
    r = fb.tiep_flow(k, "Chào cả nhà nhé")
    assert "hoi" in r and fb.co_flow(k)            # hỏi đăng y nguyên hay nhờ AI
    r2 = fb.tiep_flow(k, fb.CHON_NGUYEN)
    assert r2 == {"dang": {"loai": "chu", "message": "Chào cả nhà nhé"}}
    assert not fb.co_flow(k)


@pytest.mark.pure
def test_flow_dang_link_url_khong_bi_dien_giai(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_link"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_LINK)
    # dán đúng URL từng gây lỗi — phải được BẮT làm link, không lạc
    r1 = fb.tiep_flow(k, "https://github.com/colbymchenry/codegraph")
    assert "hoi" in r1 and fb.co_flow(k)          # hỏi lời dẫn, giữ chờ
    r2 = fb.tiep_flow(k, "Repo hay nè")
    assert "hoi" in r2 and fb.co_flow(k)           # hỏi đăng y nguyên hay nhờ AI
    r3 = fb.tiep_flow(k, fb.CHON_NGUYEN)
    assert r3["dang"]["loai"] == "link"
    assert r3["dang"]["link"] == "https://github.com/colbymchenry/codegraph"
    assert r3["dang"]["message"] == "Repo hay nè"
    assert not fb.co_flow(k)


@pytest.mark.pure
def test_flow_link_bo_qua_loi_dan(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_link2"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_LINK)
    fb.tiep_flow(k, "https://x.com")
    r = fb.tiep_flow(k, "đăng")
    assert r["dang"]["message"] == ""
    assert r["dang"]["link"] == "https://x.com"


@pytest.mark.pure
def test_flow_video_url_va_mo_ta(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_vid"
    fb.xoa_flow(k)
    nhac = fb.bat_dau_flow(k, fb.FLOW_VIDEO)
    assert "video" in nhac.lower()
    fb.tiep_flow(k, "https://cdn/x.mp4")
    assert "hoi" in fb.tiep_flow(k, "clip nè")
    r = fb.tiep_flow(k, fb.CHON_NGUYEN)
    assert r["dang"] == {"loai": "video", "media_urls": ["https://cdn/x.mp4"],
                         "message": "clip nè"}


@pytest.mark.pure
def test_flow_gui_thang_video_o_buoc_cho_video(monkeypatch):
    """«hoặc gửi thẳng video vào đây» — kênh bơm một câu, phải lấy đúng URL."""
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_vid2"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_VIDEO)
    r = fb.tiep_flow(k, "thêm video vào bài đăng facebook: https://cdn/y.mp4")
    assert "hoi" in r and "mô tả" in r["hoi"].lower()
    assert fb._flow[k]["video"] == "https://cdn/y.mp4"     # KHÔNG nuốt cả câu
    fb.tiep_flow(k, "clip nè")
    r2 = fb.tiep_flow(k, fb.CHON_NGUYEN)
    assert r2["dang"]["media_urls"] == ["https://cdn/y.mp4"]


@pytest.mark.pure
def test_flow_gui_anh_giua_chung_khong_bi_nuot_lam_link(monkeypatch):
    """Đang chờ LINK mà gửi ảnh: không được biến cả câu bơm thành link."""
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_anh"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_LINK)
    r = fb.tiep_flow(k, "thêm ảnh vào bài đăng facebook: https://x/a.png")
    assert "hoi" in r
    assert "không ghép" in r["hoi"]
    assert "LINK" in r["hoi"]                    # hỏi lại đúng bước đang đứng
    assert fb.co_flow(k)                         # giữ bản chờ
    assert "link" not in fb._flow[k]             # chưa nhận gì làm link
    # gõ link thật vẫn chạy tiếp bình thường
    assert "hoi" in fb.tiep_flow(k, "https://vd.com/bai")
    assert fb._flow[k]["link"] == "https://vd.com/bai"


@pytest.mark.pure
def test_flow_chon_nho_ai_tra_yeu_cau_kem_link(monkeypatch):
    """Nhánh AI: trả câu giao việc có đủ yêu cầu gốc + link, không trả «dang»."""
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_ai"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_LINK)
    fb.tiep_flow(k, "https://github.com/colbymchenry/codegraph")
    fb.tiep_flow(k, "viết bài về tác dụng của repo với coder")
    r = fb.tiep_flow(k, fb.CHON_AI)
    assert "dang" not in r
    assert "viết bài về tác dụng của repo với coder" in r["ai"]
    assert "https://github.com/colbymchenry/codegraph" in r["ai"]
    assert not fb.co_flow(k)


@pytest.mark.pure
def test_flow_huy_thoat_sach(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_huy"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_LINK)
    assert fb.tiep_flow(k, "thôi") == {"huy": True}
    assert not fb.co_flow(k)


@pytest.mark.pure
def test_bat_dau_flow_khong_sentinel_tra_none(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    assert fb.bat_dau_flow("k", "một câu bình thường") is None
    assert fb.tiep_flow("k_khong_cho", "gì đó") is None


@pytest.mark.pure
def test_bat_dau_flow_chua_gan_page_khong_dat_cho(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig({"facebook": {}}))
    k = "zalop_nopage"
    fb.xoa_flow(k)
    nhac = fb.bat_dau_flow(k, fb.FLOW_LINK)
    assert nhac and "Chưa kết nối" in nhac
    assert not fb.co_flow(k)   # không có page thì không mở trạng thái chờ


@pytest.mark.pure
def test_buoc_loi_dan_link_co_menu_bon_huong(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_menu_ld"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_LINK)
    hoi = fb.tiep_flow(k, "https://vd.com/bai")["hoi"]
    assert "<<<ASK>>>" in hoi
    for s in (fb.CHON_AI_LINK, fb.CHON_AI_Y, fb.CHON_TU_GO, fb.CHON_TRAN):
        assert s in hoi


@pytest.mark.pure
def test_loi_dan_chon_ai_doc_link_khoi_go_gi(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_ld_ai"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_LINK)
    fb.tiep_flow(k, "https://vd.com/bai")
    r = fb.tiep_flow(k, fb.CHON_AI_LINK)
    assert "https://vd.com/bai" in r["ai"]
    assert "«»" not in r["ai"]           # không đẻ ra yêu cầu rỗng
    assert not fb.co_flow(k)


@pytest.mark.pure
def test_loi_dan_chon_cho_y_chinh_roi_ai_viet(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_ld_y"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_LINK)
    fb.tiep_flow(k, "https://vd.com/bai")
    assert "ý chính" in fb.tiep_flow(k, fb.CHON_AI_Y)["hoi"]
    r = fb.tiep_flow(k, "repo này giúp coder đọc code nhanh")
    assert "repo này giúp coder đọc code nhanh" in r["ai"]
    assert "https://vd.com/bai" in r["ai"]
    assert not fb.co_flow(k)


@pytest.mark.pure
def test_loi_dan_chon_tu_go_thi_dang_y_nguyen_khong_hoi_lai(monkeypatch):
    """Đã chốt tự gõ thì khỏi hỏi «y nguyên hay nhờ viết» lần nữa."""
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_ld_go"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_LINK)
    fb.tiep_flow(k, "https://vd.com/bai")
    assert "lời dẫn" in fb.tiep_flow(k, fb.CHON_TU_GO)["hoi"].lower()
    r = fb.tiep_flow(k, "Repo hay nè")
    assert r["dang"] == {"loai": "link", "link": "https://vd.com/bai",
                         "message": "Repo hay nè"}
    assert not fb.co_flow(k)


@pytest.mark.pure
def test_loi_dan_chon_dang_tran(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_ld_tran"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_LINK)
    fb.tiep_flow(k, "https://vd.com/bai")
    r = fb.tiep_flow(k, fb.CHON_TRAN)
    assert r["dang"] == {"loai": "link", "link": "https://vd.com/bai",
                         "message": ""}
    assert not fb.co_flow(k)


@pytest.mark.pure
def test_yeu_cau_ai_bat_goi_tool_dang_khong_de_bai_roi_mat(monkeypatch):
    """Đo thật 12/08: model in bài ra rồi dừng, lượt sau bài không còn đâu.

    Lời giao việc phải nêu ĐÚNG lời gọi tool, và nói rõ gọi tool không phải tự
    đăng — nếu không nó xung với câu "không tự đăng" trong skill.
    """
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_ai_goi"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_LINK)
    fb.tiep_flow(k, "https://vd.com/bai")
    y = fb.tiep_flow(k, fb.CHON_AI_LINK)["ai"]
    assert "dang_facebook" in y
    assert 'loai="link"' in y
    assert 'link="https://vd.com/bai"' in y
    assert "KHÔNG phải là tự đăng" in y
    assert ":::" in y                      # có dặn bỏ khung model tự bịa


@pytest.mark.pure
def test_yeu_cau_ai_bai_video_goi_dung_media_urls(monkeypatch):
    monkeypatch.setattr(fb, "config", _FakeConfig(_CFG_1PAGE))
    k = "zalop_ai_vid"
    fb.xoa_flow(k)
    fb.bat_dau_flow(k, fb.FLOW_VIDEO)
    fb.tiep_flow(k, "https://cdn/x.mp4")
    fb.tiep_flow(k, "viết giúp tôi bài giới thiệu clip")
    y = fb.tiep_flow(k, fb.CHON_AI)["ai"]
    assert 'loai="video"' in y
    assert 'media_urls=["https://cdn/x.mp4"]' in y
