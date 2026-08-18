"""Telegram dùng CHUNG menu bảy ô với Zalo cá nhân.

Trước 18/08 chỉ Zalo có menu; Telegram nhận video là tự nghe rồi trả .srt tiếng
Việt, không hỏi gì. Đó không phải quyết định nào cả — chỉ là chỗ chưa nối, nên
mọi lần sửa menu suốt tuần qua Telegram không được hưởng.

Phần NGHIỆP VỤ nằm ở services/video_giao.py; mỗi kênh chỉ đưa vào bốn cửa gửi
ra của mình. Test này ghim đúng bốn cửa đó cho Telegram.
"""

from __future__ import annotations

import pytest

SRT = b"1\n00:00:01,000 --> 00:00:02,000\nhello\n\n"


@pytest.fixture
def tg(monkeypatch):
    from services import telegram_bot as tb

    ghi: dict[str, list] = {"tin": [], "tep": []}
    monkeypatch.setattr(tb, "send_message",
                        lambda cid, chu, **k: ghi["tin"].append(chu))
    monkeypatch.setattr(tb, "send_document",
                        lambda cid, du_lieu, ten, caption="", **k:
                        ghi["tep"].append((ten, du_lieu, caption)))
    monkeypatch.setattr(tb, "_api_call", lambda *a, **k: {})
    monkeypatch.setattr(tb, "_bot_id", lambda: "bot1")
    tb._ghi = ghi
    return tb


def test_mo_menu_khi_nhan_tep_video(tg):
    """Nhận video là HỎI, không tự nghe rồi trả .srt như bản cũ."""
    from services import dich_cho as dc

    tg._mo_menu_video("123", "u9", b"gia-lap-video", "bai-giang.mp4")

    menu = tg._ghi["tin"][-1]
    for phai_co in ("Tóm tắt", "Ý chính", "Phụ đề", "Lồng tiếng"):
        assert phai_co.lower() in menu.lower(), f"menu thiếu {phai_co}"
    p = dc.get_pending("tg:bot1:123:u9")
    assert p and p["ten"] == "bai-giang.mp4" and p["so_byte"] == len(b"gia-lap-video")
    dc.don_tep(dc.pop_pending("tg:bot1:123:u9"))


def test_menu_tren_telegram_giong_het_ben_zalo(tg):
    """Cùng một bảng VIEC nên không có cửa nào để hai bên lệch nhau."""
    from services import dich_cho as dc

    tg._mo_menu_video("123", "u9", b"x", "a.mp4")
    menu = tg._ghi["tin"][-1]
    for so, nhan, _ in dc.VIEC.values():
        assert f"{so}. {nhan}" in menu
    dc.don_tep(dc.pop_pending("tg:bot1:123:u9"))


def test_kenh_gui_bytes_thanh_document(tg):
    kenh = tg._kenh_tg("123")
    kenh.gui_bytes(SRT, "phu-de.vi.srt", "Phụ đề")
    assert tg._ghi["tep"] == [("phu-de.vi.srt", SRT, "Phụ đề")]


def test_kenh_gui_tep_doc_tu_dia(tg, tmp_path):
    duong = tmp_path / "video.mp4"
    duong.write_bytes(b"noi-dung-video")
    kenh = tg._kenh_tg("123")
    kenh.gui_tep(str(duong), "phu-de-tren.vi.mp4", "Video đã ghép chữ")
    assert tg._ghi["tep"][0][1] == b"noi-dung-video"


def test_tep_qua_50mb_thi_noi_ro_chu_khong_im(tg, tmp_path, monkeypatch):
    """Bot Telegram gửi tối đa 50 MB. Để API trả lỗi thì người dùng chỉ thấy
    bot im sau khi đã chờ cả chục phút."""
    monkeypatch.setattr(tg, "TG_TOI_DA_GUI", 10)
    duong = tmp_path / "to.mp4"
    duong.write_bytes(b"x" * 100)
    kenh = tg._kenh_tg("123")
    kenh.gui_tep(str(duong), "phu-de.mp4", "Video")

    assert not tg._ghi["tep"], "quá cỡ thì đừng gửi để API tự lỗi"
    loi = tg._ghi["tin"][-1]
    assert "MB" in loi and (".srt" in loi or "Zalo" in loi), "phải chỉ đường khác"


def test_chay_viec_qua_kenh_telegram(tg, monkeypatch):
    """Cùng một hàm video_giao.chay chạy cho cả hai kênh."""
    from services import video_dich as vd
    from services import video_giao as vg

    monkeypatch.setattr(vd, "dich_tep_video",
                        lambda duong, ten="", target="", **k: {
                            "ok": True, "srt": SRT, "ten": "phu-de.vi.srt",
                            "chu": "hello", "nguon": "en", "dich": "vi"})
    monkeypatch.setattr(vd, "bao_cao", lambda r: "✅ xong")

    vg.chay(tg._kenh_tg("123"), {"path": "/tmp/a.mp4", "ten": "a.mp4"},
            {"kieu": "phu-de", "dang_ra": "srt", "vi_tri": "tren",
             "target": "vi", "nguon": "en"})

    assert len(tg._ghi["tep"]) == 1, "gửi đúng MỘT tệp, y như bên Zalo"
    ten, du_lieu, _ = tg._ghi["tep"][0]
    assert "tren" in ten and b"{\\an8}" in du_lieu
