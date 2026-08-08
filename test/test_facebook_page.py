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
