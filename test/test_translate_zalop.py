"""Zalo cá nhân: lệnh /dich phải do CODE chặn, không được rơi vào LLM.

Đo thật 13/08: `_process_ai` thiếu khối chặn nên "/dich <khối yaml dài>" đi
thẳng vào orchestrate — LLM dịch dở dang rồi xin người dùng gửi tiếp phần bị
cắt. Telegram / Zalo Bot đã có chặn từ trước; test này giữ cho zalop không tụt
lại lần nữa.
"""

from __future__ import annotations

import pytest

from test._fakes import FakeTranslate, install_translate


@pytest.fixture(autouse=True)
def _co_may_chu_dich(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "http://vn-translate:5000")
    monkeypatch.setitem(config.data, "translate_api_key", "")


def _ev(text: str) -> dict:
    return {"msg_id": "m1", "thread_id": "123", "thread_type": 0, "text": text,
            "account_id": "acc1", "sender_id": "u9", "display_name": "Người thử",
            "mentions": []}


def test_dich_tren_zalo_ca_nhan_do_code_tra_loi(monkeypatch):
    from services import zalo_personal as zp
    import services.agent as agent_pkg
    from services.agent import capabilities as caps

    # Thread được phép giao tiếp, không đòi tag, người gửi không phải admin.
    monkeypatch.setattr(caps, "allowed_groups_for_member", lambda *a, **k: None)
    monkeypatch.setattr(caps, "duoc_giao_tiep", lambda *a, **k: True)
    monkeypatch.setattr(caps, "mention_required_for", lambda *a, **k: (False, ""))
    monkeypatch.setattr(zp, "_chat_ids", lambda: ["123"])
    monkeypatch.setattr(zp, "_is_admin_thread", lambda *a, **k: False)
    monkeypatch.setattr(zp, "_la_admin_nguoi_gui", lambda *a, **k: False)

    def _khong_duoc_goi(*a, **k):
        raise AssertionError("/dich không được rơi vào LLM")

    monkeypatch.setattr(agent_pkg, "orchestrate", _khong_duoc_goi)

    sent: list[str] = []
    monkeypatch.setattr(
        zp, "send_message",
        lambda tid, text, ttype=0, **k: (sent.append(text), {"ok": True})[1])

    with install_translate(FakeTranslate(lang="en", codes=("en", "vi"))):
        zp._process_ai(_ev("/dich\naction: ai_task.generate_data"))

    assert sent, "bot phải trả lời ngay bằng bản dịch, không im lặng"
    assert sent[0].startswith("🌐")
    assert "vi:" in sent[0]  # nội dung đã qua máy dịch (en → vi), không phải LLM
