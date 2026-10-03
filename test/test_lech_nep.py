"""Nhắc lệch nếp (chủ máy 03/10/2026). Không gọi mạng: lịch sử nhà, HA, thông báo, model đều giả.

Đo trước khi viết (lịch sử thật 30/08–03/10): chỉ đèn có nếp; giả lập 14 ngày được 2 lần hỏi.
"""
from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import ha_client, hieu_thiet_bi_nha as ht, lech_nep as ln, lich_su_nha, su_co_thiet_bi, thong_bao  # noqa: E402


def _luc(ngay_lui: int, h: int, m: int = 0) -> float:
    """Giờ VIỆT NAM (khung +7 cố định như module) — CI chạy UTC, dùng time.localtime là lệch ngày/giờ."""
    return (ln._ngay(time.time()) - ngay_lui) * 86400 - ln._LECH_GIO + h * 3600 + m * 60


def _cung_loai(ngay_lui: int) -> bool:
    """Ngày lùi đó cùng loại (thường/cuối tuần) với hôm nay."""
    return ln._loai_ngay(ln._ngay(_luc(ngay_lui, 12))) == ln._loai_ngay(ln._ngay(_luc(0, 12)))


@pytest.fixture
def nha(tmp_path, monkeypatch):
    ln._reset_for_tests(tmp_path / "ln.json")
    ev: list[dict] = []
    # Đèn ngủ: ngày nào cùng loại cũng bật lúc 19:10 (và bot có lúc tự bật — vẫn tính).
    for d in range(1, 40):
        ev.append({"thiet_bi": "light.ngu", "ts": _luc(d, 19, 10), "gia_tri": "on"})
        ev.append({"thiet_bi": "switch.ngu", "ts": _luc(d, 19, 10), "gia_tri": "on"})   # gương
        if d % 3:
            ev.append({"thiet_bi": "light.thinh_thoang", "ts": _luc(d, 9), "gia_tri": "on"})
    monkeypatch.setattr(lich_su_nha, "doc_cua_so", lambda tu, den, **k: [e for e in ev if tu <= e["ts"] <= den])
    monkeypatch.setattr(ha_client, "thuc_the_boc", lambda tb: "light.ngu" if tb.endswith(".ngu") else None)
    monkeypatch.setattr(ha_client, "get_state", lambda tb: {"attributes": {"friendly_name": "Đèn ngủ"}})
    monkeypatch.setattr(su_co_thiet_bi, "chan_doan", lambda tb: {"nguyen_nhan": "thiết bị mất kết nối",
                                                                  "chi_tiet": "pin yếu"})
    gui: list[str] = []
    monkeypatch.setattr(thong_bao, "gui", lambda k, t, a="": gui.append(t) or 1)
    monkeypatch.setattr(ln, "is_enabled", lambda: True)
    from services import lich_sinh_hoat
    monkeypatch.setattr(lich_sinh_hoat, "ca_nha", lambda loai, luc: False)
    return ev, gui


def test_hoc_nep_gop_guong_va_bo_thiet_bi_khong_deu(nha):
    nep = ln.hoc(_luc(0, 12))
    assert list(nep) == ["light.ngu"], "gương switch gộp về đèn; thiết bị 2/3 ngày không đủ 85%"
    assert any(n["tu"] <= 19 * 60 + 10 < n["den"] for n in nep["light.ngu"])


def test_qua_gio_chua_hoat_dong_thi_hoi_kem_nguyen_nhan_mot_lan(nha):
    _, gui = nha
    assert ln.chay_mot_lan(_luc(0, 19, 30)) == 0, "chưa hết khung + trễ thì chưa hỏi"
    assert ln.chay_mot_lan(_luc(0, 20, 40)) == 1
    assert "Đèn ngủ" in gui[-1] and "thiết bị mất kết nối" in gui[-1]
    assert ln.chay_mot_lan(_luc(0, 20, 50)) == 0, "mỗi nếp một lần một ngày"


def test_da_hoat_dong_hom_nay_thi_khong_hoi(nha):
    ev, gui = nha
    ev.append({"thiet_bi": "light.ngu", "ts": _luc(0, 19, 20), "gia_tri": "on"})
    assert ln.chay_mot_lan(_luc(0, 20, 40)) == 0 and gui == []


def test_gio_khuya_va_ca_nha_vang_thi_khong_hoi(nha, monkeypatch):
    assert ln.quet(_luc(0, 22, 30)) == 0
    from services import lich_sinh_hoat
    monkeypatch.setattr(lich_sinh_hoat, "ca_nha", lambda loai, luc: loai == "vang")
    assert ln.quet(_luc(0, 20, 40)) == 0


def test_chua_tich_thi_khong_lam_gi(nha, monkeypatch):
    monkeypatch.setattr(ln, "is_enabled", lambda: False)
    assert ln.chay_mot_lan(_luc(0, 20, 40)) == 0


@pytest.mark.parametrize("loai,lan_sau_hoi", [("hong", False), ("nghi", False), ("doi_nep", False)])
def test_tra_loi_tu_nhien_model_hieu(nha, monkeypatch, loai, lan_sau_hoi):
    _, gui = nha
    ln.chay_mot_lan(_luc(0, 20, 40))
    de: list[str] = []
    monkeypatch.setattr(ht, "huong_dan", lambda ten="": ("HD", "v"))
    monkeypatch.setattr(ht, "_model", lambda: "m")
    monkeypatch.setattr(ht, "_goi_model", lambda m, h, d: de.append(d) or {
        "choices": [{"message": {"content": '{"loai": "%s", "dap": "Dạ em hiểu rồi ạ."}' % loai}}]})
    du_kien: list[str] = []
    monkeypatch.setattr(ht, "ghi_du_kien", lambda nd, **k: du_kien.append(nd) or 1)
    assert ln.tra_loi("nó bị mất mạng ấy mà, tối về ba sửa", now=_luc(0, 20, 45)) == "Dạ em hiểu rồi ạ."
    assert "nó bị mất mạng" in de[-1] and "Đèn ngủ" in de[-1]
    assert bool(du_kien) is (loai in ("hong", "doi_nep"))
    assert ln.tra_loi("thêm câu nữa", now=_luc(0, 20, 46)) is None, "đã trả lời thì hết chờ"


def test_khong_lien_quan_thi_nhuong_handler_khac(nha, monkeypatch):
    ln.chay_mot_lan(_luc(0, 20, 40))
    monkeypatch.setattr(ht, "huong_dan", lambda ten="": ("HD", "v"))
    monkeypatch.setattr(ht, "_model", lambda: "m")
    monkeypatch.setattr(ht, "_goi_model", lambda m, h, d: {
        "choices": [{"message": {"content": '{"loai": "khong_lien_quan", "dap": ""}'}}]})
    assert ln.tra_loi("mai mấy giờ họp", now=_luc(0, 20, 45)) is None


def test_khong_co_cau_hoi_cho_thi_khong_goi_model(nha, monkeypatch):
    monkeypatch.setattr(ht, "_goi_model", lambda *a: pytest.fail("không được gọi model"))
    assert ln.tra_loi("chào em") is None


def test_bao_hong_thi_thoi_hoi_toi_khi_chay_lai(nha, monkeypatch):
    ev, gui = nha
    ln.chay_mot_lan(_luc(1, 20, 40)) if _cung_loai(1) else None
    import json
    d = {"hong": {"light.ngu": _luc(1, 21)}, "hoi": []}
    ln._PATH.write_text(json.dumps(d))
    ev[:] = [e for e in ev if e["ts"] < _luc(1, 0)]          # từ hôm qua không còn hoạt động
    assert ln.chay_mot_lan(_luc(0, 20, 40)) == 0, "đang hỏng thì không hỏi"
    ev.append({"thiet_bi": "light.ngu", "ts": _luc(0, 8), "gia_tri": "on"})   # sáng nay chạy lại
    assert ln.chay_mot_lan(_luc(0, 20, 40)) == 1, "chạy lại rồi thì hết «hỏng», lệch tối nay hỏi như thường"
