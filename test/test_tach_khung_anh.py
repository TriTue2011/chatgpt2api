"""Nhiều ảnh trong một lượt phải được chen chữ để model không gộp cặp khung.

llama.cpp coi các ảnh nằm sát nhau là khung video của Qwen3-VL và gộp từng
cặp lại, làm một người đi ngang bị tả thành hai người. Chen chữ vào giữa là
cách duy nhất tách chúng ra, vì Home Assistant gửi ảnh dưới dạng danh sách
đính kèm thuần.
"""

from services.providers.custom_openai import _PREFIX_MAY_NHA, _tach_khung_anh


def _anh(ten: str) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{ten}"}}


def test_ba_anh_duoc_danh_so_theo_thu_tu():
    ra = _tach_khung_anh([
        {"role": "user", "content": [{"type": "text", "text": "Mô tả."}, _anh("a"), _anh("b"), _anh("c")]}
    ])
    phan = ra[0]["content"]
    assert [p.get("text") for p in phan if p["type"] == "text"] == [
        "Mô tả.", "Frame 1 of 3:", "Frame 2 of 3:", "Frame 3 of 3:"
    ]
    # Nhãn phải đứng NGAY TRƯỚC ảnh nó nói tới, nếu không thì không tách được cặp.
    for i, p in enumerate(phan):
        if p["type"] == "image_url":
            assert phan[i - 1]["text"].startswith("Frame ")
    assert sum(1 for p in phan if p["type"] == "image_url") == 3


def test_mot_anh_giu_nguyen():
    goc = [{"role": "user", "content": [{"type": "text", "text": "Ảnh gì?"}, _anh("a")]}]
    assert _tach_khung_anh(goc) == goc


def test_content_dang_chuoi_giu_nguyen():
    goc = [{"role": "user", "content": "chào"}, {"role": "assistant", "content": "vâng"}]
    assert _tach_khung_anh(goc) == goc


def test_khong_sua_messages_goc():
    goc = [{"role": "user", "content": [_anh("a"), _anh("b")]}]
    _tach_khung_anh(goc)
    assert goc[0]["content"] == [_anh("a"), _anh("b")]


def test_chi_ap_dung_cho_may_nha():
    # Đổi tên biến môi trường mà quên đồng bộ tập prefix thì test này gãy.
    assert _PREFIX_MAY_NHA == {"lv", "ol"}
