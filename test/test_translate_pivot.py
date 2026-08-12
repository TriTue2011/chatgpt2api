"""Trục dịch quanh LLM — owner duy nhất của concern này.

Không kiểm client LibreTranslate hay lệnh /dich (xem `test_translate_service.py`).
"""

from __future__ import annotations

import pytest

from services import translate_pivot as tp
from test._fakes import FakeTranslate, install_translate


@pytest.fixture
def bat_truc(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "http://libretranslate:5000")
    monkeypatch.setitem(config.data, "translate_pivot_enabled", True)


def _tin(vai: str, chu: str) -> dict:
    return {"role": vai, "content": chu}


# ── Công tắc ────────────────────────────────────────────────────────────────


@pytest.mark.pure
def test_mac_dinh_tat_du_da_co_may_chu_dich(monkeypatch):
    """Bật trục là đổi hành vi của MỌI lượt gọi model, nên phải tường minh."""
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "http://libretranslate:5000")
    monkeypatch.delitem(config.data, "translate_pivot_enabled", raising=False)
    assert tp.dang_bat() is False


@pytest.mark.pure
def test_bat_co_ma_khong_co_may_chu_thi_van_tat(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_url", "")
    monkeypatch.setitem(config.data, "translate_pivot_enabled", True)
    assert tp.dang_bat() is False


@pytest.mark.pure
def test_tat_thi_tra_lai_nguyen_danh_sach(monkeypatch):
    from services.config import config

    monkeypatch.setitem(config.data, "translate_pivot_enabled", False)
    msgs = [_tin("user", "xin chào")]
    ra, truc = tp.dich_truoc_khi_gui(msgs, None, {})
    assert ra is msgs and truc is None


# ── Chiều đi: dịch + chèn lời dặn ───────────────────────────────────────────


@pytest.mark.adapter
def test_dich_moi_tin_sang_tieng_anh_va_chen_loi_dan(bat_truc):
    msgs = [_tin("system", "Bạn là trợ lý."), _tin("user", "thời tiết thế nào")]
    with install_translate(FakeTranslate(lang="vi")):
        ra, truc = tp.dich_truoc_khi_gui(msgs, None, {})
    assert truc is not None and truc.da_dich is True
    # Lời dặn đứng SAU tin system gốc (nếp inject_response_format_prompt)
    assert ra[0]["content"] == "en:Bạn là trợ lý."
    assert ra[1]["role"] == "system" and tp.DAU_NHAN in ra[1]["content"]
    assert "Vietnamese" in ra[1]["content"]
    assert ra[2]["content"] == "en:thời tiết thế nào"


@pytest.mark.pure
def test_khong_nhet_token_noi_bo_vao_loi_nhac():
    """Model KHÔNG được thấy rác nội bộ của gateway. Bản đầu tôi chèn
    "[[c2a-vi-out]]" làm dấu nhận, nhưng dấu đó nằm trong lời nhắc nên model đọc
    được — model yếu còn nhại nó ra câu trả lời."""
    ra = tp._chen_loi_dan([_tin("user", "x")])
    dan = [m for m in ra if m.get("role") == "system"][0]["content"]
    assert dan == tp.LOI_DAN_TV
    assert "[[" not in dan and "c2a" not in dan


@pytest.mark.adapter
def test_khong_sua_danh_sach_goc_lich_su_van_la_tieng_viet(bat_truc):
    """Tầng trên giữ lịch sử hội thoại. Dịch tại chỗ là lần sau người dùng mở
    lại thấy bản dịch chứ không phải chữ mình gõ."""
    msgs = [_tin("user", "xin chào")]
    with install_translate(FakeTranslate(lang="vi")):
        ra, _ = tp.dich_truoc_khi_gui(msgs, None, {})
    assert msgs[0]["content"] == "xin chào"
    assert ra is not msgs


@pytest.mark.adapter
def test_yeu_cau_da_la_tieng_anh_thi_khong_goi_dich_nhung_van_chen_loi_dan(bat_truc):
    msgs = [_tin("user", "what is the weather")]
    with install_translate(FakeTranslate(lang="en")) as fake:
        ra, truc = tp.dich_truoc_khi_gui(msgs, None, {})
    assert truc is not None and truc.da_dich is False
    assert fake.da_gui == []                      # không tốn lượt /translate nào
    assert any(tp.DAU_NHAN in str(m.get("content")) for m in ra)


@pytest.mark.adapter
def test_dich_ca_phan_text_trong_content_dang_danh_sach(bat_truc):
    msgs = [{"role": "user", "content": [{"type": "text", "text": "xin chào"}]}]
    with install_translate(FakeTranslate(lang="vi")):
        ra, _ = tp.dich_truoc_khi_gui(msgs, None, {})
    dich = [m for m in ra if m.get("role") == "user"][0]
    assert dich["content"][0]["text"] == "en:xin chào"
    assert msgs[0]["content"][0]["text"] == "xin chào"   # bản gốc còn nguyên


@pytest.mark.adapter
def test_khong_chen_hai_lan_khi_dispatch_chay_lai(bat_truc):
    msgs = [_tin("user", "xin chào")]
    with install_translate(FakeTranslate(lang="vi")):
        lan1, _ = tp.dich_truoc_khi_gui(msgs, None, {})
        lan2, truc2 = tp.dich_truoc_khi_gui(lan1, None, {})
    assert lan2 is lan1
    assert truc2 is not None                       # vẫn giữ đường dịch về
    assert sum(1 for m in lan2 if tp.DAU_NHAN in str(m.get("content"))) == 1


# ── Bốn loại request phải bỏ qua ────────────────────────────────────────────


@pytest.mark.adapter
def test_bo_qua_khi_co_tools(bat_truc):
    """Tên hàm/tham số là hợp đồng máy-với-máy, và tên thiết bị Home Assistant
    là tiếng Việt — dịch đi thì gọi hàm trượt entity."""
    tools = [{"type": "function", "function": {"name": "control_home"}}]
    with install_translate(FakeTranslate(lang="vi")) as fake:
        ra, truc = tp.dich_truoc_khi_gui([_tin("user", "bật đèn")], tools, {})
    assert truc is None and fake.calls == []
    assert ra[0]["content"] == "bật đèn"


@pytest.mark.adapter
def test_bo_qua_khi_client_xin_json(bat_truc):
    body = {"response_format": {"type": "json_object"}}
    with install_translate(FakeTranslate(lang="vi")) as fake:
        _, truc = tp.dich_truoc_khi_gui([_tin("user", "đếm người")], None, body)
    assert truc is None and fake.calls == []


@pytest.mark.adapter
def test_bo_qua_khi_co_tin_tool(bat_truc):
    msgs = [_tin("user", "xin chào"),
            {"role": "tool", "tool_call_id": "x", "content": '{"ok": true}'}]
    with install_translate(FakeTranslate(lang="vi")) as fake:
        _, truc = tp.dich_truoc_khi_gui(msgs, None, {})
    assert truc is None and fake.calls == []


@pytest.mark.adapter
def test_bo_qua_luot_goi_noi_bo_cua_pipeline_code(bat_truc):
    """`_PIPELINE_REVIEWER_PROMPT` ghép thẳng `=== CODE ===\\n{code}` KHÔNG bọc
    ```, mà translate() chỉ bảo vệ khối mã có dấu huyền. Thiếu cờ này thì bật
    trục là code bị dịch thành văn xuôi và reviewer đọc phải rác — hỏng lặng lẽ,
    vì reviewer vẫn trả lời, chỉ là trả lời về một đoạn không còn là code."""
    loi_nhac = ("Bạn là người KIỂM DUYỆT code.\n"
                "=== CODE ===\ndef cong(a, b):\n    return a + b\n")
    body = {"stream": False, tp.NOI_BO: True}
    with install_translate(FakeTranslate(lang="vi")) as fake:
        ra, truc = tp.dich_truoc_khi_gui([_tin("user", loi_nhac)], None, body)
    assert truc is None and fake.calls == []
    assert ra[0]["content"] == loi_nhac          # code còn nguyên từng ký tự


@pytest.mark.adapter
def test_cung_loi_nhac_do_nhung_khong_co_co_thi_van_dich(bat_truc):
    """Đối chứng cho test trên: cờ NOI_BO là thứ DUY NHẤT chặn, không phải may
    mắn nhờ một guard nào khác bắt được 'trông giống code'."""
    with install_translate(FakeTranslate(lang="vi")) as fake:
        _, truc = tp.dich_truoc_khi_gui(
            [_tin("user", "=== CODE ===\ndef cong(a, b):\n    return a + b\n")],
            None, {"stream": False})
    assert truc is not None and fake.calls != []


@pytest.mark.adapter
def test_bo_qua_khi_co_anh(bat_truc):
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "ảnh này có mấy người"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}},
    ]}]
    with install_translate(FakeTranslate(lang="vi")) as fake:
        _, truc = tp.dich_truoc_khi_gui(msgs, None, {})
    assert truc is None and fake.calls == []


@pytest.mark.adapter
def test_may_chu_dich_chet_thi_request_di_nguyen_van(bat_truc):
    """Fail-open: dịch vụ dịch hỏng không được phép làm trợ lý câm."""
    msgs = [_tin("user", "xin chào")]
    with install_translate(FakeTranslate(loi="Connection refused")):
        ra, truc = tp.dich_truoc_khi_gui(msgs, None, {})
    assert ra is msgs and truc is None


# ── Chiều về: phản hồi không phải tiếng Việt → dịch về tiếng Việt ───────────


@pytest.mark.adapter
def test_phan_hoi_tieng_anh_duoc_dich_ve_tieng_viet():
    kq = {"choices": [{"message": {"role": "assistant", "content": "It is sunny"}}]}
    with install_translate(FakeTranslate(lang="en")):
        ra = tp.dich_lai_phan_hoi(kq, tp.Truc(nguon="vi", da_dich=True))
    assert ra["choices"][0]["message"]["content"] == "vi:It is sunny"


@pytest.mark.adapter
def test_phan_hoi_da_tieng_viet_thi_khong_dich_lai():
    kq = {"choices": [{"message": {"content": "Trời nắng ạ"}}]}
    with install_translate(FakeTranslate(lang="vi")) as fake:
        ra = tp.dich_lai_phan_hoi(kq, tp.Truc())
    assert ra["choices"][0]["message"]["content"] == "Trời nắng ạ"
    assert fake.da_gui == []


@pytest.mark.adapter
def test_phan_hoi_co_tool_calls_thi_khong_dich():
    kq = {"choices": [{"message": {"content": "", "tool_calls": [
        {"id": "1", "function": {"name": "control_home", "arguments": "{}"}}]}}]}
    with install_translate(FakeTranslate(lang="en")) as fake:
        ra = tp.dich_lai_phan_hoi(kq, tp.Truc())
    assert ra["choices"][0]["message"]["tool_calls"]
    assert fake.calls == []


@pytest.mark.adapter
def test_khong_co_truc_thi_khong_dich_phan_hoi():
    kq = {"choices": [{"message": {"content": "It is sunny"}}]}
    with install_translate(FakeTranslate(lang="en")) as fake:
        assert tp.dich_lai_phan_hoi(kq, None) is kq
    assert fake.calls == []


# ── Chiều về: stream ────────────────────────────────────────────────────────


def _stream(*noi_dung: str):
    for i, c in enumerate(noi_dung):
        yield {"choices": [{"index": 0, "delta": {"content": c}, "finish_reason": None}]}
    yield {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}


@pytest.mark.adapter
def test_stream_dich_ca_cau_chu_khong_tung_chunk_va_giu_finish_reason():
    with install_translate(FakeTranslate(lang="en")) as fake:
        ra = list(tp.dich_lai_phan_hoi(_stream("It ", "is ", "sunny"), tp.Truc()))
    chu = "".join(c["choices"][0]["delta"].get("content") or "" for c in ra)
    assert chu == "vi:It is sunny"
    assert fake.da_gui == ["It is sunny"]              # MỘT lượt dịch, không ba
    assert ra[-1]["choices"][0]["finish_reason"] == "stop"


@pytest.mark.adapter
def test_stream_xa_theo_tung_doan_khong_cho_het_cau_tra_loi():
    """Bản đầu tôi gom cả stream rồi mới dịch: người dùng nhìn màn hình trống
    suốt lúc model sinh chữ. Nay mỗi ĐOẠN (ngăn bởi dòng trống) dịch và phát
    ngay — đoạn 1 phải ra TRƯỚC khi đoạn 3 tới."""
    def gen():
        yield {"choices": [{"delta": {"role": "assistant", "content": "Para one.\n\n"}}]}
        yield {"choices": [{"delta": {"content": "Para two.\n\n"}}]}
        yield {"choices": [{"delta": {"content": "Para three."}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    with install_translate(FakeTranslate(lang="en")) as fake:
        ra = list(tp.dich_lai_phan_hoi(gen(), tp.Truc()))
    assert fake.da_gui == ["Para one.\n\n", "Para two.\n\n", "Para three."]
    chu = [c["choices"][0]["delta"].get("content") or "" for c in ra]
    assert "vi:Para one.\n\n" in chu
    assert ra[-1]["choices"][0]["finish_reason"] == "stop"
    assert "".join(chu) == "vi:Para one.\n\nvi:Para two.\n\nvi:Para three."


@pytest.mark.adapter
def test_stream_khong_cat_ngang_khoi_ma():
    """Cắt giữa khối ``` là dịch một nửa khối rồi ghép với nửa kia — vỡ cả khối."""
    def gen():
        yield {"choices": [{"delta": {"content": "Xem:\n\n```py\nx = 1\n\ny = 2\n```"}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    with install_translate(FakeTranslate(lang="en")) as fake:
        ra = list(tp.dich_lai_phan_hoi(gen(), tp.Truc()))
    chu = "".join(c["choices"][0]["delta"].get("content") or "" for c in ra)
    assert "```py\nx = 1\n\ny = 2\n```" in chu          # khối mã còn nguyên
    assert all("x = 1" not in x for x in fake.da_gui)   # và chưa từng bay lên


@pytest.mark.adapter
def test_stream_doan_dai_khong_co_dong_trong_van_duoc_xa():
    """Câu trả lời dài liền mạch (không dòng trống nào): chờ tới hết là bằng gom
    cả stream. Quá TRAN_KHOI ký tự thì cắt ở dấu kết câu và xả."""
    # Mỗi chunk một câu KHÁC nhau: trùng chữ thì lần xả sau lấy từ bộ đệm bản
    # dịch, không gọi HTTP, và test tưởng là "chỉ xả một lần".
    def gen():
        for i in range(4):
            yield {"choices": [{"delta": {"content": f"Cau so {i} day. " * 80}}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}

    with install_translate(FakeTranslate(lang="en")) as fake:
        list(tp.dich_lai_phan_hoi(gen(), tp.Truc()))
    assert len(fake.da_gui) >= 2, "phải xả nhiều lần, không dồn tới chunk kết"
    # Mọi lần xả đều cắt ở RANH GIỚI CÂU — cắt giữa câu là dịch máy nhận mảnh vụn
    assert all(x.rstrip().endswith(".") for x in fake.da_gui)


@pytest.mark.adapter
def test_stream_tieng_viet_di_qua_nguyen_ven():
    with install_translate(FakeTranslate(lang="vi")):
        ra = list(tp.dich_lai_phan_hoi(_stream("Trời ", "nắng"), tp.Truc()))
    assert "".join(c["choices"][0]["delta"].get("content") or "" for c in ra) == "Trời nắng"


@pytest.mark.adapter
def test_stream_khong_bao_gio_dich_tool_calls():
    """Thân `tool_calls` là hợp đồng máy-với-máy, dịch vào là gọi hàm trượt.

    Chữ đến TRƯỚC tool_calls thì vẫn dịch (đó là lời dẫn người dùng đọc), nhưng
    từ lúc thấy tool_calls trở đi thì cho qua thẳng, không đụng gì nữa.
    """
    def gen():
        yield {"choices": [{"delta": {"content": "Để em tra giúp."}}]}
        yield {"choices": [{"delta": {"tool_calls": [
            {"id": "1", "function": {"name": "control_home",
                                     "arguments": '{"room": "phòng khách"}'}}]}}]}
        yield {"choices": [{"delta": {"content": " xong rồi ạ"}}]}

    with install_translate(FakeTranslate(lang="en")) as fake:
        ra = list(tp.dich_lai_phan_hoi(gen(), tp.Truc()))
    tc = [c for c in ra if (c["choices"][0].get("delta") or {}).get("tool_calls")]
    assert tc, "chunk tool_calls phải được phát lại"
    args = tc[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
    assert args == '{"room": "phòng khách"}'        # nguyên văn, không dịch
    # Chữ đến SAU tool_calls không bị dịch nữa
    assert any((c["choices"][0].get("delta") or {}).get("content") == " xong rồi ạ"
               for c in ra)
    assert all("xong rồi ạ" not in x for x in fake.da_gui)
