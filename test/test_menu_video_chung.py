"""MỘT menu duy nhất cho video, dùng chung link và tệp gửi lên.

Chủ máy chốt 18/08. Trước đó có HAI menu rời nhau, không mục nào giống mục nào:

  · Link  → bot tự bịa: Tóm tắt · Ý chính · Dịch · Phân tích đoạn · Ghi chú
            (không có phụ đề, không có lồng tiếng)
  · Tệp   → dich_cho.VIEC: Phụ đề .srt · Dịch ra chữ · Chép lời .srt ·
            Chép lời chữ thuần · Lồng tiếng

Ô lồng tiếng còn bị giấu khỏi link vì "link hiện chưa tải cả hình về gateway" —
nay ``services.video_tai.tai_video`` tải được nên lý do đó hết.

Kiến trúc chủ máy chốt: "chuyển thành phụ đề rồi mới qua llm để làm 12345" —
mọi video đều tạo phụ đề trước, phụ đề là đầu vào cho cả 5 ô LLM lẫn 2 ô video.

Ô phụ đề phải hỏi ĐỦ HAI câu: chữ TRÊN hay DƯỚI, rồi trả .srt hay ghép vào
video. Bản cũ tự đoán rồi gửi CẢ HAI tệp .srt cùng lúc.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def dc(monkeypatch):
    from services import dich_cho
    monkeypatch.setattr(dich_cho, "_CHO", {}, raising=False)
    return dich_cho


@pytest.mark.pure
def test_menu_du_bay_muc():
    from services.dich_cho import VIEC

    assert [v[0] for v in VIEC.values()] == list("1234567")
    nhan = " ".join(v[1].lower() for v in VIEC.values())
    for phai_co in ("tóm tắt", "ý chính", "phân tích", "ghi chú",
                    "phụ đề", "lồng tiếng"):
        assert phai_co in nhan, f"menu thiếu mục {phai_co!r}"


@pytest.mark.pure
def test_link_va_tep_video_cung_menu(dc):
    """Đúng yêu cầu: 'kể cả gửi video cũng có các lựa chọn như video gửi link'."""
    tu_link = dc._viec_hop_le({"url": "https://youtu.be/abc"})
    tu_tep = dc._viec_hop_le({"path": "/tmp/a.mp4", "ten": "a.mp4"})
    assert set(tu_link) == set(tu_tep), "hai đầu vào vẫn ra hai menu khác nhau"
    assert "long-tieng" in tu_link, "link phải lồng tiếng được"


@pytest.mark.pure
def test_tep_phu_de_khong_co_o_long_tieng(dc):
    """Tệp .srt không có luồng hình để thay tiếng."""
    assert "long-tieng" not in dc._viec_hop_le({"path": "/tmp/a.srt", "ten": "a.srt"})


@pytest.mark.pure
def test_phu_de_hoi_du_hai_buoc(dc):
    """1) chọn Phụ đề → 2) tiếng nguồn → 3) tiếng đích → 4) vị trí → 5) dạng."""
    k = "phien1"
    dc.set_pending(k, url="https://youtu.be/abc", ten="abc")

    assert dc.tra_loi_buoc(k, "6") == {"tiep": True}          # chọn Phụ đề
    assert dc.tra_loi_buoc(k, "2") == {"tiep": True}          # tiếng nguồn
    assert dc.tra_loi_buoc(k, "1") == {"tiep": True}          # tiếng đích

    menu_vi_tri = dc.menu_buoc(k).lower()
    assert "dưới" in menu_vi_tri and "trên" in menu_vi_tri, "không hỏi vị trí chữ"
    assert dc.tra_loi_buoc(k, "2") == {"tiep": True}          # chọn chữ TRÊN

    menu_dang = dc.menu_buoc(k).lower()
    assert ".srt" in menu_dang and "ghép" in menu_dang, "không hỏi dạng trả"
    kq = dc.tra_loi_buoc(k, "2")                              # chọn GHÉP video
    assert kq["kieu"] == "phu-de"
    assert kq["vi_tri"] == "tren"
    assert kq["dang_ra"] == "ghep"


@pytest.mark.pure
def test_chon_srt_thi_khong_ghep(dc):
    k = "phien2"
    dc.set_pending(k, url="https://youtu.be/abc", ten="abc")
    for tra_loi in ("6", "2", "1", "1"):
        dc.tra_loi_buoc(k, tra_loi)
    kq = dc.tra_loi_buoc(k, "1")
    assert kq["dang_ra"] == "srt" and kq["vi_tri"] == "duoi"


@pytest.mark.pure
@pytest.mark.parametrize("so,viec", [("1", "tom-tat"), ("2", "y-chinh"),
                                     ("4", "phan-tich"), ("5", "ghi-chu")])
def test_nam_o_llm_khong_hoi_them_tieng(dc, so, viec):
    """Chạy trên phụ đề đã có → hỏi tiếng nguồn/đích chỉ làm bấm thừa."""
    k = f"phien_{so}"
    dc.set_pending(k, url="https://youtu.be/abc", ten="abc")
    kq = dc.tra_loi_buoc(k, so)
    assert kq == {"kieu": "llm", "viec": viec}


@pytest.mark.pure
def test_long_tieng_van_di_duong_cu(dc):
    """Vá menu không được làm hỏng nhánh lồng tiếng sẵn có."""
    k = "phien_lt"
    dc.set_pending(k, path="/tmp/a.mp4", ten="a.mp4")
    assert dc.tra_loi_buoc(k, "7") == {"tiep": True}
    assert dc.tra_loi_buoc(k, "2") == {"tiep": True}
    kq = dc.tra_loi_buoc(k, "1")
    assert kq["kieu"] == "long-tieng"
