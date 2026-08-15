"""Bản dịch song ngữ đóng .docx — ngưỡng đóng tệp và chỗ ghép cặp lệch dòng."""

from __future__ import annotations

import io
import zipfile

from services import song_ngu as sn


def test_ngan_thi_nhan_thang_dai_thi_dong_tep():
    """Mở tệp để đọc ba câu là phiền hơn có ích; còn bản dài gửi thẳng thì Zalo
    cắt thành hàng chục tin (2000 ký tự/tin)."""
    assert sn.nen_dong_tep("ngắn gọn") is False
    assert sn.nen_dong_tep("x" * (sn.NGUONG_DONG_TEP + 1)) is True

    goi = sn.dong_goi("hello", "xin chào", nguon="en", dich="vi")
    assert goi == {"chu": "xin chào"}

    dai = "\n".join(f"câu số {i}" for i in range(400))
    goi = sn.dong_goi(dai, dai, nguon="en", dich="vi")
    assert goi.get("ten", "").endswith(".docx") and goi.get("tep")


def test_tach_cap_lech_dong_thi_khong_mat_chu():
    """Máy dịch trả về số dòng khác bản gốc là chuyện thường — thà lệch vài
    dòng cuối còn hơn cắt mất chữ."""
    cap = sn.tach_cap("một\nhai\nba", "one\ntwo")
    assert cap == [("một", "one"), ("hai", "two"), ("ba", "")]

    cap = sn.tach_cap("một", "one\ntwo")
    assert cap == [("một", "one"), ("", "two")]


def test_docx_co_ca_hai_ban_va_mo_duoc():
    cap = [("Good morning", "Chào buổi sáng"), ("It is hot", "Trời nóng")]
    du = sn.docx_song_ngu(cap, nguon="en", dich="vi", tieu_de="Thử")
    assert du[:2] == b"PK"          # .docx là zip
    with zipfile.ZipFile(io.BytesIO(du)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    for chu in ("Good morning", "Chào buổi sáng", "It is hot", "Trời nóng"):
        assert chu in xml, f"thiếu «{chu}» trong tệp"
    assert "Tiếng Anh" in xml and "tiếng Việt" in xml


def test_cap_thieu_mot_ve_van_ghi_ve_con_lai():
    du = sn.docx_song_ngu([("", "chỉ có bản dịch"), ("chỉ có bản gốc", "")])
    with zipfile.ZipFile(io.BytesIO(du)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "chỉ có bản dịch" in xml and "chỉ có bản gốc" in xml
