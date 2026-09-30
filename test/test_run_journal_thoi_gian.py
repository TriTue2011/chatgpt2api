"""Đo thời gian từng khâu của lượt bot (chủ máy 30/09/2026, học Hermes Agent: đo trước rồi mới sửa)."""

import os
import time

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.agent import run_journal as rj  # noqa: E402


def test_do_tung_khau_va_khong_tinh_trung_model_trong_tool():
    rj.bat_dau_do()
    time.sleep(0.03)                                  # chuẩn bị
    with rj.do("model", "cx/auto"):
        time.sleep(0.02)
    with rj.do("tool", "khuon_mat"):
        with rj.do("model", "gemini"):                # model gọi bên trong tool
            time.sleep(0.02)
    tk = rj.tong_ket_do()
    assert tk["chuan_bi_ms"] >= 25 and tk["model_ms"] >= 15 and tk["tool_ms"] >= 15
    assert tk["model_ms"] < 40, "model trong tool không cộng vào model_ms"
    assert [m["loai"] for m in tk["moc"]] == ["model", "tool", "model"]
    assert [m.get("trong_tool") for m in tk["moc"]] == [None, None, 1]
    assert rj.tong_ket_do() is None, "tổng kết xong là thôi đo"


def test_ngoai_luot_bot_thi_khong_do(monkeypatch):
    from services.agent import runtime
    monkeypatch.setattr(runtime, "_call_model", lambda model, messages, **k: {"ok": model})
    assert rj.tong_ket_do() is None
    assert runtime.call_model("m", []) == {"ok": "m"}
    rj.bat_dau_do()
    runtime.call_model("cx/auto", [], max_tokens=10)
    tk = rj.tong_ket_do()
    assert [(m["loai"], m["ten"]) for m in tk["moc"]] == [("model", "cx/auto")]


def test_duong_di_combo_vao_moc_model(monkeypatch):
    """Chủ máy 30/09/2026: "free chatgpt còn nhiều mà" — mỗi lượt phải thấy model nào thử / bỏ qua / lỗi, vì sao."""
    from services.agent import runtime
    duong = [{"m": "chatgpt_free/cgf/auto", "vi": "bỏ qua: đang nghỉ sau lỗi trước"},
             {"m": "nvidia_nim/nemotron", "vi": "ok"}]
    monkeypatch.setattr(runtime, "_call_model", lambda model, messages, **k: {"choices": [], "x_c2a_duong": duong})
    rj.bat_dau_do()
    runtime.call_model("AI text", [])
    tk = rj.tong_ket_do()
    assert tk["moc"][0]["duong"] == duong
