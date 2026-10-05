"""Danh sách TRƯỜNG HỢP cho trang web (chủ máy 05/10/2026): mỗi thiết bị / mỗi chiều, anh ✓ chạy · ✗ tạm dừng · 🗑 xoá ·
✎ sửa (sửa là duyệt) · thêm; bot chỉ ĐỀ XUẤT luật học từ lịch sử. Không gọi HA, không gọi model."""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import luat_duyet as ld  # noqa: E402

TB = "light.den"
MA = {"binary_sensor.pk", "binary_sensor.cua", "sensor.kc", TB}


def _luat(so, **k):
    return {"so": so, "nen": "bat", "chieu": "bat", "khi": ["binary_sensor.pk có người vào"], "neu": [],
            "xac_minh": False, **k}


@pytest.fixture
def so(tmp_path, monkeypatch):
    from services import kich_ban_nha as kb, kich_hoat_nha as kh
    ld._reset_for_tests(tmp_path / "ld.json")
    d = {TB: {"lan": [{"id": 1, "luc": 1, "luat": [_luat(1), _luat(2, khi=["binary_sensor.cua có người vào"])],
                       "truong_hop": ["vào", "cửa"]}], "cham": []}}
    (tmp_path / "ld.json").write_text(json.dumps(d), encoding="utf-8")
    duyet = {TB: {"bat": [{"tinh_huong": "vào", "nguon": "chu_may", "nen": "bat"},
                          {"tinh_huong": "cửa", "nguon": "bot", "nen": "bat"}], "tat": []}}
    bo: list = []
    monkeypatch.setattr(kb, "duyet", lambda: duyet)
    monkeypatch.setattr(kb, "sua_duyet", lambda tb, h, viec, so_=None, nd="": bo.append((h, so_)) or "")
    monkeypatch.setattr(kh, "_ten_ha", lambda: {})
    monkeypatch.setattr(kh, "_trang_thai_ha", lambda: [])
    monkeypatch.setattr(kh, "tong_quan", lambda: [])
    monkeypatch.setattr(ld, "cam_bien", lambda: [{"ma": m} for m in MA - {TB}])
    from services import lich_sinh_hoat
    monkeypatch.setattr(lich_sinh_hoat, "ds", lambda: [])
    return bo


def _tt(id_):
    ds = ld.danh_sach(TB, {})
    return next(x for h in ds for x in ds[h] if x["id"] == id_ or x["loi"] == id_)["trang_thai"]


def test_duyet_dung_xoa_tren_web(so):
    assert _tt("lan:1:1") == "cho" and ld.ap(TB) == []
    ld.quyet(TB, "duyet", "lan:1:1")
    assert _tt("lan:1:1") == "chay" and [l["loi"] for l in ld.ap(TB)] == ["vào"]
    ld.quyet(TB, "dung", "lan:1:1")
    assert _tt("lan:1:1") == "dung" and ld.ap(TB) == [], "tạm dừng → thôi chạy, không tính là sai"
    assert not [c for c in ld.so()[TB]["cham"] if not c["dung"]], "tạm dừng không ghi lời chấm SAI"
    ld.quyet(TB, "duyet", "lan:1:1")
    assert [l["loi"] for l in ld.ap(TB)] == ["vào"], "bật lại"
    ld.quyet(TB, "xoa", "lan:1:2")
    assert so == [("bat", 2)], "xoá = gỡ trường hợp «cửa» (số 2 chiều bật) khỏi danh sách duyệt"


def test_sua_la_duyet_va_vao_bai_hoc(so):
    moi = {"chieu": "bat", "khi": ["binary_sensor.pk có người vào"], "neu": [{"ma": "sensor.kc", "duoi": 3}]}
    ld.quyet(TB, "sua", "lan:1:1", moi)
    ap = ld.ap(TB)
    assert len(ap) == 1 and ap[0]["neu"] == [{"ma": "sensor.kc", "duoi": 3.0}] and ap[0]["lan"] == 0
    c = ld.so()[TB]["cham"][-1]
    assert c["cham_boi"] == "chu_may" and "chủ nhà sửa thành" in c["ghi_chu"] and "dưới 3" in c["ghi_chu"]
    assert _tt("vào") == "chay"
    ld.quyet(TB, "duyet", "lan:1:1")                     # anh duyệt luật bot SAU khi sửa → lời sau cùng thắng
    assert ld.ap(TB)[0]["lan"] == 1
    with pytest.raises(ValueError):
        ld.quyet(TB, "sua", "lan:1:1", {"chieu": "bat", "khi": ["binary_sensor.khong_co có người vào"]})


def test_them_luat_cua_anh_va_chay_sai_thi_tam_dung(so):
    ld.quyet(TB, "them", "", {"chieu": "bat", "khi": ["binary_sensor.cua có người vào"], "neu": []}, "cửa mở")
    ap = ld.ap(TB)
    assert [(l["loi"], l["lan"]) for l in ap] == [("cửa mở", 0)]
    ld.chay_sai(TB, 0, ap[0]["so"], ["binary_sensor.cua=on✓"], "sai")
    assert ld.ap(TB) == [] and _tt("cửa mở") == "dung", "luật anh đặt chạy sai → tạm dừng chờ anh sửa"
    ld.quyet(TB, "xoa", f"chu:{ap[0]['so']}")
    assert not ld.so()[TB]["chu"]


def test_de_xuat_tu_luat_bot_hoc(so, monkeypatch):
    from services import kich_hoat_nha as kh
    tq = {"thiet_bi": TB, "huong": {"on": {"luat": [
        {"p": 0.97, "k": 30, "n": 30, "dk": [
            {"key": "[binary_sensor.cua có người vào]", "nho_hon": False, "nguong": 0.5},
            {"key": "giờ", "nho_hon": False, "nguong": 15.4},
            {"key": "sensor.kc", "nho_hon": True, "nguong": 2.0}]},
        {"p": 0.4, "k": 4, "n": 10, "dk": [{"key": "[binary_sensor.pk có người vào]", "nho_hon": False, "nguong": 0.5}]},
        {"p": 0.9, "k": 9, "n": 10, "dk": [{"key": kh.PHUT_DA_O, "nho_hon": False, "nguong": 3}]}]}, "off": {}}}
    dx = ld.de_xuat_hoc(TB, tq)
    assert len(dx) == 1, "chỉ luật đủ chắc và nói được bằng dạng luật"
    assert dx[0]["khi"] == ["binary_sensor.cua có người vào"]
    assert dx[0]["neu"] == [{"ma": "gio", "tu": "15:24", "den": "24:00"}, {"ma": "sensor.kc", "duoi": 2.0}]
    assert ld.ap(TB) == [], "đề xuất KHÔNG tự chạy"
    monkeypatch.setattr(ld, "de_xuat_hoc", lambda tb, tq=None, _g=ld.de_xuat_hoc: _g(tb, tq or {"huong": tq_["huong"]}))
    tq_ = tq
    ld.quyet(TB, "duyet", dx[0]["id"])
    ap = ld.ap(TB)
    assert len(ap) == 1 and ap[0]["nguon"] == "bot_hoc" and ap[0]["neu"] == dx[0]["neu"]
    assert ld.de_xuat_hoc(TB, tq) == [], "đã nhận thì không đề xuất lại"


def test_bot_hoc_nhuong_ca_huong_khi_anh_da_duyet(monkeypatch):
    """Hướng nào anh đã duyệt luật thì luật bot học thôi chạy ở hướng đó, với MỌI nguồn."""
    from services import kich_hoat_nha as kh
    monkeypatch.setattr(kh, "ds_thiet_bi", lambda: {TB: {}})
    monkeypatch.setattr(kh, "_luat_duyet", lambda tb: [_luat(1, lan=1)])
    import threading
    monkeypatch.setattr(threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    assert kh._phat_duyet("binary_sensor.khac vắng", 1.0, False) == {f"{TB}|on"}


def test_kich_ban_chua_duyet_la_cho_anh_khong_phai_bot_hong(so, monkeypatch):
    """Đo 05/10/2026: 66 trường hợp của 3 đèn hiện «bot chưa chuyển» suốt 3 ngày — thật ra là chờ chủ nhà duyệt kịch
    bản (danh sách gửi Zalo chưa ai trả lời). Đã có luật thì giữ trạng thái luật."""
    from services import kich_ban_nha as kb
    duyet = {TB: {"bat": [{"tinh_huong": "vào", "nguon": "bot", "nen": "bat"},
                          {"tinh_huong": "chó đi qua", "nguon": "bot", "nen": "khong_lam"}],
                  "tat": [{"tinh_huong": "ra ngoài", "nguon": "bot", "nen": "tat"}],
                  "bat_xong": False, "tat_xong": False, "buoc": "bat", "gui_luc": 1791185295.0}}
    monkeypatch.setattr(kb, "duyet", lambda: duyet)
    ds = ld.danh_sach(TB, {})
    tt = {x["loi"]: x for h in ds for x in ds[h]}
    assert tt["vào"]["trang_thai"] == "cho", "đã có luật (lan 1) → giữ trạng thái luật"
    cho = tt["chó đi qua"]
    assert cho["trang_thai"] == "cho_kich_ban" and cho["so_kb"] == 2 and cho["nen"] == "khong_lam"
    assert "chờ anh duyệt kịch bản phần Bật" in cho["ly_do"] and "đã gửi Zalo lúc" in cho["ly_do"]
    ra = tt["ra ngoài"]
    assert ra["trang_thai"] == "cho_kich_ban" and "phần Tắt" in ra["ly_do"] and "chưa gửi Zalo" in ra["ly_do"]
    duyet[TB]["bat_xong"] = True
    assert {x["loi"]: x["trang_thai"] for x in ld.danh_sach(TB, {})["bat"]}["chó đi qua"] == "chua_chuyen", \
        "đã duyệt mà bot chưa chuyển → đúng là chưa chuyển"
