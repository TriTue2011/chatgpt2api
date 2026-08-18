"""Bốn ô đọc-hiểu chạy trên phụ đề: services/video_hoi.py.

Kiến trúc chủ máy chốt 18/08: "chuyển thành phụ đề rồi mới qua llm để làm
12345". Module này là nửa sau — nó KHÔNG nghe video, chỉ nhận chữ đã có.
"""

from __future__ import annotations

import pytest

from services import video_hoi as vh


@pytest.fixture
def model_gia(monkeypatch):
    """Thay lời gọi model bằng một hàm ghi lại payload."""
    from services.agent import orchestrator, runtime

    ghi: dict = {}

    def _goi(model, messages, **k):
        ghi["model"] = model
        ghi["messages"] = messages
        ghi["kwargs"] = k
        return {"choices": [{"message": {"content": "xong rồi ạ"}}]}

    monkeypatch.setattr(orchestrator, "_main_model", lambda hint="chat": "cx/auto")
    monkeypatch.setattr(runtime, "call_model", _goi)
    return ghi


def test_moi_o_dung_mot_cau_dan_rieng(model_gia):
    for viec in ("tom-tat", "y-chinh", "phan-tich", "ghi-chu"):
        assert vh.hoi(viec, "lời thoại") == "xong rồi ạ"
    assert vh.la_viec_llm("tom-tat") and not vh.la_viec_llm("phu-de")


def test_o_phan_tich_dua_doan_nguoi_dung_neu_vao_cau_hoi(model_gia):
    vh.hoi("phan-tich", "1\n00:10:20,000 --> 00:10:25,000\nlãi kép",
           them="từ 10:20 đến 12:00")
    hoi_gi = model_gia["messages"][-1]["content"]
    assert "từ 10:20 đến 12:00" in hoi_gi
    assert "lãi kép" in hoi_gi


def test_khong_duoc_di_tra_web(model_gia):
    """Đọc thứ ĐÃ CÓ trong tay. Bỏ trống thì gateway bật web search tự động và
    lấy nguyên prompt làm câu truy vấn — lỗi đã đo ở services/digest.py."""
    vh.hoi("tom-tat", "lời thoại")
    assert model_gia["kwargs"]["allowed_groups"] == {"summary"}


def test_phu_de_qua_dai_thi_cat_va_NOI_ro_da_cat(model_gia, monkeypatch):
    monkeypatch.setattr(vh, "TOI_DA_CHU", 100)
    ra = vh.hoi("tom-tat", "a" * 500)
    assert len(model_gia["messages"][-1]["content"]) < 400
    assert "dài quá" in ra, "cắt bớt mà im lặng là để người dùng tin nhầm"


def test_viec_la_hoac_phu_de_rong_thi_bao_loi(model_gia):
    with pytest.raises(vh.LoiHoiVideo):
        vh.hoi("khong-co-o-nay", "lời thoại")
    with pytest.raises(vh.LoiHoiVideo):
        vh.hoi("tom-tat", "   ")


def test_model_hong_thi_nem_loi_chu_khong_tra_chuoi_rong(monkeypatch):
    from services.agent import orchestrator, runtime

    monkeypatch.setattr(orchestrator, "_main_model", lambda hint="chat": "cx/auto")
    monkeypatch.setattr(runtime, "call_model",
                        lambda *a, **k: {"error": "provider 500"})
    with pytest.raises(vh.LoiHoiVideo, match="provider 500"):
        vh.hoi("tom-tat", "lời thoại")

    monkeypatch.setattr(runtime, "call_model",
                        lambda *a, **k: {"choices": [{"message": {"content": ""}}]})
    with pytest.raises(vh.LoiHoiVideo):
        vh.hoi("tom-tat", "lời thoại")
