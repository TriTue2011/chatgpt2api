"""Dán TRẦN link video thì bot phải MỞ MENU, không được rơi xuống LLM.

Ca thật 20/08/2026 trên Zalo cá nhân (chủ máy ↔ Botmitbap):

    14:07:48  chủ máy: https://youtu.be/5cbuWsRYZss?si=…
    14:08:02  bot: "Anh muốn em làm gì với video này ạ? Tóm tắt / Lấy các ý
              chính / Dịch nội dung / Phân tích / Viết lại thành bài đăng"
    14:08:20  chủ máy: "Lồng tiếng"
    14:08:26  bot: "Anh muốn lồng tiếng cho nội dung nào ạ? Anh gửi cho em
              video cần lồng tiếng…"          ← link vừa gửi đã mất
    14:08:33  chủ máy: dán lại đúng link đó
    14:08:49  chủ máy: "3"
    14:08:54  bot: "em thấy anh gửi «3». Anh muốn em làm tiếp phần số 3 hay
              đang chọn một mục nào đó ạ?"

Ba chỗ hỏng, cùng một gốc — link không vào được menu bảy ô của
``services/dich_cho.py`` nên cả lượt do LLM đỡ:

1. Năm mục kia là LLM TỰ BỊA theo đúng những gì nó có tool (transcript). Menu
   thật có bảy ô, trong đó ô 6 (phụ đề) và ô 7 (lồng tiếng) LLM không có tool
   nào để làm — đúng cái danh sách hẹp mà chủ máy đã bỏ ngày 18/08 khi chốt
   "MỘT menu duy nhất, dùng chung cho link và tệp".
2. Vì "lồng tiếng" không phải tool của nó, LLM chỉ biết hỏi lại — và hỏi như
   thể chưa từng thấy cái link.
3. Menu của LLM in ra dạng VĂN XUÔI, không phải khối ``<<<ASK>>>``, nên
   ``ask_choices`` không ghi bản chờ nào; "3" tra không ra gì.

Menu do CODE mở thì "3" đi vào ``dich_cho.tra_loi_buoc`` và "lồng tiếng" là ô 7.
"""

from __future__ import annotations

import pytest

LINK = "https://youtu.be/5cbuWsRYZss?si=uIm0TFAybquBC5n1"
PKEY = "zalop:acc1:123:u9"


def _ev(text: str) -> dict:
    return {"msg_id": "m1", "thread_id": "123", "thread_type": 0, "text": text,
            "account_id": "acc1", "sender_id": "u9", "display_name": "Người thử",
            "mentions": []}


@pytest.fixture
def bot(monkeypatch):
    """`_process_ai` với thread mở, không đòi tag, và LLM bị CẤM gọi."""
    from services import zalo_personal as zp
    import services.agent as agent_pkg
    from services.agent import capabilities as caps
    from services import dich_cho as dc

    monkeypatch.setattr(caps, "allowed_groups_for_member", lambda *a, **k: None)
    monkeypatch.setattr(caps, "duoc_giao_tiep", lambda *a, **k: True)
    monkeypatch.setattr(caps, "mention_required_for", lambda *a, **k: (False, ""))
    monkeypatch.setattr(zp, "_chat_ids", lambda: ["123"])
    monkeypatch.setattr(zp, "_is_admin_thread", lambda *a, **k: False)
    monkeypatch.setattr(zp, "_la_admin_nguoi_gui", lambda *a, **k: False)

    def _cam_llm(*a, **k):
        raise AssertionError("link video dán trần không được rơi vào LLM")

    monkeypatch.setattr(agent_pkg, "orchestrate", _cam_llm)

    da_gui: list[str] = []
    monkeypatch.setattr(
        zp, "send_message",
        lambda tid, text, ttype=0, **k: (da_gui.append(text), {"ok": True})[1])

    dc.don_tep(dc.pop_pending(PKEY))
    yield zp, da_gui
    dc.don_tep(dc.pop_pending(PKEY))


def test_link_dan_tran_mo_menu_bay_o(bot):
    zp, da_gui = bot
    from services import dich_cho as dc

    zp._process_ai(_ev(LINK))

    assert da_gui, "bot phải trả lời ngay, không im lặng"
    menu = da_gui[0]
    assert "🎬" in menu and "Nhắn số" in menu
    # Đủ bảy ô — hai ô cuối là thứ LLM không làm được, và là thứ chủ máy xin.
    assert "7. Lồng tiếng" in menu, menu
    assert "6. Phụ đề" in menu, menu
    # Bản chờ phải được ghi, nếu không thì lượt sau nhắn "3" lại rơi vào LLM.
    assert (dc.get_pending(PKEY) or {}).get("url") == LINK


def test_nhan_so_sau_do_di_vao_menu_chu_khong_vao_llm(bot):
    """Đúng chỗ hỏng của ca thật: "3" phải được menu nhận, không hỏi lại."""
    zp, da_gui = bot
    from services import dich_cho as dc

    zp._process_ai(_ev(LINK))
    zp._process_ai(_ev("3"))

    assert len(da_gui) >= 2, da_gui
    # Ô 3 là "Dịch ra bản chữ" → bước kế tiếp là hỏi tệp nói tiếng gì.
    assert "tiếng gì" in da_gui[1], da_gui[1]
    assert (dc.get_pending(PKEY) or {}).get("viec") == "dich-chu"


def test_dung_ca_that_link_roi_go_chu_long_tieng(bot):
    """Chạy lại ĐÚNG hai lượt của ca thật: dán link, rồi gõ chữ "Lồng tiếng"."""
    zp, da_gui = bot
    from services import dich_cho as dc

    zp._process_ai(_ev(LINK))
    zp._process_ai(_ev("Lồng tiếng"))

    assert len(da_gui) >= 2, da_gui
    # Ô 7 → bước kế tiếp là hỏi tiếng nguồn, KHÔNG phải đòi gửi lại video.
    assert "tiếng gì" in da_gui[1], da_gui[1]
    assert (dc.get_pending(PKEY) or {}).get("viec") == "long-tieng"


def test_da_neu_yeu_cau_thi_van_de_llm_lo(monkeypatch, bot):
    """Nói rõ yêu cầu kèm link thì KHÔNG mở menu — không cướp việc của LLM."""
    zp, da_gui = bot
    import services.agent as agent_pkg
    from services import dich_cho as dc

    goi: list[str] = []
    monkeypatch.setattr(agent_pkg, "orchestrate",
                        lambda inject, skey, **k: (goi.append(inject),
                                                   {"text": "dạ"})[1])
    zp._process_ai(_ev(f"tóm tắt video này {LINK}"))

    assert goi, "câu đã nêu yêu cầu thì vẫn phải tới LLM"
    assert not dc.has_pending(PKEY), "không được mở menu khi người dùng đã nói rõ"
