"""Tên COMBO phải được giải ra model thật trước khi so tiền tố nhà cung cấp.

Đo 18/08 trên máy chủ thật: nhánh Tạo video cấu hình model ``"AI Video"`` và
MỌI lượt tạo đều hỏng —

    Agnes AI error (HTTP 400): Model agnes-video-v2.0 is a video model.
                               Use /v1/videos.

tức model video bị đẩy vào endpoint CHAT. Nguyên nhân: ``handle_video_generation``
chỉ so tiền tố ``agnes/`` và ``flow/`` trên CHUỖI THÔ, nên ``"AI Video"`` không
khớp nhánh nào rồi rơi xuống đường khác.

Combo đó gồm cả hai nhà cung cấp::

    agnes/agnes-video-v2.0, flow/omni-flash, flow/veo-3.1-lite,
    flow/veo-3.1-fast, flow/veo-3.1-quality

Sau khi giải combo, lượt chạy thật ra video mp4 1,37 MB trong 85 giây.
"""

from __future__ import annotations

import asyncio

import pytest


def _chay(coro):
    # asyncio.get_event_loop() ném RuntimeError trên Python 3.12+ khi luồng
    # chính chưa có vòng lặp nào — CI chạy 3.13 nên bản cũ đỏ ngay ở dòng này.
    return asyncio.run(coro)


@pytest.mark.pure
def test_combo_duoc_giai_va_goi_dung_nha_cung_cap(monkeypatch):
    """Combo → thử thành viên đầu; agnes/ phải vào đường video của Agnes."""
    import api.veo_video as vv
    from services.backend_router import backend_router as br

    monkeypatch.setattr(br, "is_combo", lambda m: m == "AI Video", raising=False)
    monkeypatch.setattr(br, "_get_combo_models",
                        lambda m: ["agnes/agnes-video-v2.0", "flow/veo-3.1-fast"],
                        raising=False)
    da_goi: list[str] = []

    class _Gia:
        def generate_video(self, **kw):
            da_goi.append(str(kw.get("model")))
            return {"data": [{"url": "http://x/v.mp4"}]}

    import services.providers.agnes as ag
    monkeypatch.setattr(ag, "agnes_provider", _Gia(), raising=False)
    monkeypatch.setattr(vv, "_luu_thu_vien", lambda r: r, raising=False)

    r = _chay(vv.handle_video_generation({"model": "AI Video", "prompt": "x"}, None))
    assert da_goi == ["agnes/agnes-video-v2.0"], "không giải combo ra model thật"
    assert r["data"][0]["url"] == "http://x/v.mp4"


@pytest.mark.pure
def test_thanh_vien_dau_hong_thi_sang_thanh_vien_sau(monkeypatch):
    """Combo có cả agnes lẫn flow chính là để còn đường lui."""
    import api.veo_video as vv
    from services.backend_router import backend_router as br

    monkeypatch.setattr(br, "is_combo", lambda m: m == "AI Video", raising=False)
    monkeypatch.setattr(br, "_get_combo_models",
                        lambda m: ["agnes/agnes-video-v2.0", "flow/veo-3.1-fast"],
                        raising=False)
    da_thu: list[str] = []

    class _Hong:
        def generate_video(self, **kw):
            da_thu.append("agnes")
            raise RuntimeError("agnes bận")

    import services.providers.agnes as ag
    monkeypatch.setattr(ag, "agnes_provider", _Hong(), raising=False)

    goc = vv.handle_video_generation

    async def _gia(body, auth=None):
        if str(body.get("model") or "").startswith("flow/"):
            da_thu.append("flow")
            return {"data": [{"url": "http://x/flow.mp4"}]}
        return await goc(body, auth)

    monkeypatch.setattr(vv, "handle_video_generation", _gia, raising=False)
    r = _chay(_gia({"model": "AI Video", "prompt": "x"}, None))
    assert "flow" in da_thu, "thành viên đầu hỏng mà không lui sang Flow"
    assert r["data"][0]["url"] == "http://x/flow.mp4"


@pytest.mark.pure
def test_model_thuong_khong_bi_dung_toi(monkeypatch):
    """Đừng biến mọi model thành combo."""
    from services.backend_router import backend_router as br

    assert not br.is_combo("agnes/agnes-video-v2.0")
    assert not br.is_combo("flow/veo-3.1-fast")
