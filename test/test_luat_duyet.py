"""Luật từ trường hợp chủ nhà đã duyệt — kiểm ở biên, kiểm điều kiện lúc chạy, áp luật đã chấm, chạy sai thì giải lại,
và bộ kích hoạt thi hành (chủ máy 02/10/2026). Không gọi HA, không gọi model."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import luat_duyet as ld  # noqa: E402

_TZ = timezone(timedelta(hours=7))
MA = {"binary_sensor.cua", "binary_sensor.pk", "sensor.kc", "light.den"}


def _luat(**k):
    return {"so": 1, "nen": "bat", "khi": ["binary_sensor.pk có người vào"], "neu": [], "xac_minh": False, **k}


def test_kiem_bien_loai_ma_la_nguon_sai_va_bo_sot():
    data = {"luat": [_luat(neu=[{"ma": "sensor.kc", "duoi": 3.66}, {"ma": "ca_nha", "la": "ngu", "phu_dinh": True}]),
                     _luat(so=2, neu=[{"ma": "sensor.khong_co", "la": "on"}]),
                     _luat(so=3, khi=["binary_sensor.pk ở lại 5 giây"]),
                     _luat(so=4, khi=["binary_sensor.pk ở lại 30 giây"], neu=[{"ma": "gio", "tu": "6h", "den": "21:45"}])],
            "khong_chuyen_duoc": [{"so": 5, "ly_do": "cần nhận mặt"}]}
    luat, khong, loi = ld.kiem(data, 6, MA, {"ngu"})
    assert [l["so"] for l in luat] == [1] and luat[0]["neu"][1] == {"ma": "ca_nha", "la": "ngu", "phu_dinh": True}
    assert khong == [{"so": 5, "ly_do": "cần nhận mặt"}]
    assert any("sensor.khong_co" in x for x in loi) and any("10–3600" in x for x in loi)
    assert any("khung giờ" in x for x in loi) and any("bỏ sót trường hợp [2, 3, 4, 6]" in x for x in loi)


def test_lien_giay_va_trong_giay_khong_di_chung():
    _, _, loi = ld.kiem({"luat": [_luat(neu=[{"ma": "binary_sensor.cua", "la": "on", "lien_giay": 5,
                                              "trong_giay": 60}])]}, 1, MA, set())
    assert loi and "không đi chung" in loi[0]


def _st(ma, gt, cach_giay=0.0, luc=1_000_000.0):
    return {"entity_id": ma, "state": gt,
            "last_changed": datetime.fromtimestamp(luc - cach_giay, _TZ).isoformat()}


def test_kiem_dieu_kien_so_lien_giay_trong_giay_va_phu_dinh(monkeypatch):
    luc = 1_000_000.0
    st = {"sensor.kc": _st("sensor.kc", "2.1"), "binary_sensor.pk": _st("binary_sensor.pk", "on", 40),
          "binary_sensor.cua": _st("binary_sensor.cua", "off", 20)}
    monkeypatch.setattr(ld, "_da_o_trong", lambda ma, la, tu: ma == "binary_sensor.cua" and tu == luc - 60)
    ok, doc = ld.kiem_dieu_kien([{"ma": "sensor.kc", "duoi": 3.66}, {"ma": "binary_sensor.pk", "la": "on", "lien_giay": 30},
                                 {"ma": "binary_sensor.cua", "la": "on", "trong_giay": 60}], luc, st)
    assert ok and doc[0] == "sensor.kc=2.1✓"
    ok, _ = ld.kiem_dieu_kien([{"ma": "binary_sensor.pk", "la": "on", "lien_giay": 60}], luc, st)
    assert not ok, "mới có người 40 giây"
    ok, _ = ld.kiem_dieu_kien([{"ma": "sensor.kc", "duoi": 3.66, "phu_dinh": True}], luc, st)
    assert not ok


def test_loc_mem_cam_bien_nhieu_phai_giu_du_lau(monkeypatch):
    """Cảm biến NHIỄU: điều kiện «= on» chỉ đúng khi giữ ≥ ngưỡng giữ (lọc mềm). Lành thì tin ngay. Phủ định không lọc."""
    from services import do_tin_cam_bien as dt
    luc = 1_000_000.0
    monkeypatch.setattr(dt, "nguong_giu_nhanh", lambda ma, now=None: 30.0 if ma == "binary_sensor.nhieu" else None)
    # nhiễu vừa bật 10 giây trước → chưa đủ 30s giữ → chưa tin
    st = {"binary_sensor.nhieu": _st("binary_sensor.nhieu", "on", 10), "binary_sensor.lanh": _st("binary_sensor.lanh", "on", 1)}
    assert ld.kiem_dieu_kien([{"ma": "binary_sensor.nhieu", "la": "on"}], luc, st)[0] is False
    # giữ 40 giây → tin
    st["binary_sensor.nhieu"] = _st("binary_sensor.nhieu", "on", 40)
    assert ld.kiem_dieu_kien([{"ma": "binary_sensor.nhieu", "la": "on"}], luc, st)[0] is True
    # cảm biến lành: bật 1 giây vẫn tin ngay
    assert ld.kiem_dieu_kien([{"ma": "binary_sensor.lanh", "la": "on"}], luc, st)[0] is True
    # phủ định «KHÔNG on» của cảm biến nhiễu vừa chớp: tin ngay, không chờ
    st["binary_sensor.nhieu"] = _st("binary_sensor.nhieu", "off", 2)
    assert ld.kiem_dieu_kien([{"ma": "binary_sensor.nhieu", "la": "on", "phu_dinh": True}], luc, st)[0] is True


def test_cam_bien_trung_phat_hien_cap_cung_tin_hieu(monkeypatch, tmp_path):
    """Hai cảm biến gần như cùng tín hiệu → vào mục B3 để model không viết điều kiện bắt chúng khác nhau."""
    import sqlite3
    from services import lich_su_nha
    db = tmp_path / "ls.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE su_kien (ts REAL, nguon TEXT, thiet_bi TEXT, truong TEXT, gia_tri TEXT, gia_tri_cu TEXT, do_ai INT, gio INT, thu INT)")
    import time as _t
    now = _t.time()
    for k in range(60):
        g = "on" if k % 2 else "off"
        conn.execute("INSERT INTO su_kien (ts, thiet_bi, truong, gia_tri) VALUES (?,?,?,?)", (now - (60 - k) * 60, "binary_sensor.a_all_occupancy", "state", g))
        conn.execute("INSERT INTO su_kien (ts, thiet_bi, truong, gia_tri) VALUES (?,?,?,?)", (now - (60 - k) * 60 + 0.01, "binary_sensor.a_person_occupancy", "state", g))
        conn.execute("INSERT INTO su_kien (ts, thiet_bi, truong, gia_tri) VALUES (?,?,?,?)", (now - (60 - k) * 60, "binary_sensor.khac", "state", "on" if k % 5 else "off"))
    conn.commit(); conn.close()
    monkeypatch.setattr(lich_su_nha, "_DB_PATH", db)
    trung = ld._cam_bien_trung(["binary_sensor.a_all_occupancy", "binary_sensor.a_person_occupancy", "binary_sensor.khac", "sensor.kc"])
    cap = {frozenset((a, b)) for a, b, _ in trung}
    assert frozenset(("binary_sensor.a_all_occupancy", "binary_sensor.a_person_occupancy")) in cap
    assert all("binary_sensor.khac" not in c for c in cap), "cảm biến khác nhịp không bị gộp"


def test_radar_khoang_cach_0_la_KHONG_CO_MUC_TIEU(monkeypatch):
    """Radar mmwave báo 0 = không bắt được ai, không phải «0 mét». Đo 04/10/2026: luật TẮT «distance > 3.66» bị chặn
    96 lần vì distance=0. Nay 0 → «gần hơn X» sai, «xa hơn X / không ai trong X» đúng; chỉ cho cảm biến độ dài."""
    luc = 1_000_000.0

    def kc(gt, dc="distance", unit="m"):
        return {"entity_id": "sensor.kc", "state": gt,
                "attributes": {"device_class": dc, "unit_of_measurement": unit}}

    # 0 = không mục tiêu: KHÔNG phải «gần hơn 3.66», mà LÀ «xa hơn 3.66 / không ai trong 3.66»
    assert ld.kiem_dieu_kien([{"ma": "sensor.kc", "duoi": 3.66}], luc, {"sensor.kc": kc("0")})[0] is False
    assert ld.kiem_dieu_kien([{"ma": "sensor.kc", "tren": 3.66}], luc, {"sensor.kc": kc("0")})[0] is True
    # Không đọc được (unavailable) cũng vậy
    assert ld.kiem_dieu_kien([{"ma": "sensor.kc", "tren": 3.66}], luc, {"sensor.kc": kc("unavailable")})[0] is True
    # Số thật vẫn so bình thường
    assert ld.kiem_dieu_kien([{"ma": "sensor.kc", "duoi": 3.66}], luc, {"sensor.kc": kc("2.4")})[0] is True
    assert ld.kiem_dieu_kien([{"ma": "sensor.kc", "tren": 3.66}], luc, {"sensor.kc": kc("4.4")})[0] is True
    # Cảm biến KHÔNG phải độ dài (vd công suất) thì 0 là số thật
    assert ld.kiem_dieu_kien([{"ma": "sensor.kc", "duoi": 10}], luc, {"sensor.kc": kc("0", dc="power", unit="W")})[0] is True
    assert ld.kiem_dieu_kien([{"ma": "sensor.kc", "tren": 10}], luc, {"sensor.kc": kc("0", dc="power", unit="W")})[0] is False


def test_khung_gio_qua_nua_dem():
    luc = datetime(2026, 10, 2, 23, 30, tzinfo=_TZ).timestamp()
    assert ld._trong_khung("21:45", "06:00", luc) and not ld._trong_khung("06:00", "21:45", luc)


@pytest.fixture
def so(tmp_path, monkeypatch):
    ld._reset_for_tests(tmp_path / "ld.json")
    d = {"light.den": {"lan": [
        {"id": 1, "luc": 1, "luat": [_luat(chieu="bat"), _luat(so=2, nen="khong_lam", chieu="bat")], "truong_hop": ["a", "b"]},
        {"id": 2, "luc": 2, "luat": [_luat(chieu="bat")], "truong_hop": ["a"]}],
        "cham": [{"lan": 1, "so": 1, "dung": True}, {"lan": 1, "so": 2, "dung": True}]}}
    (tmp_path / "ld.json").write_text(json.dumps(d), encoding="utf-8")
    giai: list[str] = []
    monkeypatch.setattr(ld, "giai_va_bao", lambda tb: giai.append(tb) or {})
    return giai


def test_ap_lan_moi_chua_cham_thi_lan_da_cham_van_chay(so):
    assert [(l["lan"], l["so"]) for l in ld.ap("light.den")] == [(1, 1), (1, 2)]
    ld.cham("light.den", 1, True, cham_boi="claude")             # chấm lần 2
    assert [(l["lan"], l["so"]) for l in ld.ap("light.den")] == [(2, 1)]


def test_chay_sai_ghi_gia_tri_cham_sai_va_giai_lai(so):
    import time
    ld.chay_sai("light.den", 1, 1, ["binary_sensor.pk=on✓"], "chủ nhà trả lời sai")
    time.sleep(0.2)
    assert so == ["light.den"]
    assert [l["so"] for l in ld.ap("light.den")] == [2], "luật chạy sai thôi chạy"
    x = ld.so()["light.den"]
    assert x["chay_sai"][-1]["doc"] == ["binary_sensor.pk=on✓"]


def test_bo_kich_hoat_lam_theo_luat_bi_chan_va_xac_minh(monkeypatch):
    from services import du_doan_nha as dd, ha_client, kich_hoat_nha as kh, thong_bao

    lam: list[tuple] = []
    tin: list[str] = []
    luat = [_luat(chieu="bat", lan=1), _luat(so=2, nen="khong_lam", chieu="bat", lan=1,
                                              neu=[{"ma": "binary_sensor.cua", "la": "on"}])]
    monkeypatch.setattr(kh, "_luat_duyet", lambda tb: luat)
    monkeypatch.setattr(ld, "so", lambda: {"light.den": {"lan": [{"id": 1, "truong_hop": ["người vào", "x"]}]}})
    trang = {"light.den": "off", "binary_sensor.cua": "off"}
    monkeypatch.setattr(ha_client, "get_states", lambda use_cache=True: [{"entity_id": k, "state": v} for k, v in trang.items()])
    for ten, gia in (("_vua_lam", lambda *a, **k: False), ("_nguoi_vua_cham", lambda *a: False), ("_nk", lambda *a, **k: None),
                     ("_ten_tb", lambda tb: "Đèn trần"), ("_hen_kiem_lai", lambda *a: None)):
        monkeypatch.setattr(kh, ten, gia)
    monkeypatch.setattr(kh, "_lam", lambda tb, hd, tu_lam: lam.append((tb, hd)) or True)
    monkeypatch.setattr(dd, "ghi_nhan", lambda *a, **k: 7)
    monkeypatch.setattr(dd, "_cam_tu_lam", lambda ten: False)
    monkeypatch.setattr(thong_bao, "gui", lambda khoa, t, anh_url="": tin.append(t) or 1)
    kh._xu_ly_duyet("light.den", [luat[0]], "binary_sensor.pk có người vào", 1.0)
    assert lam == [("light.den", "on")] and "theo trường hợp anh duyệt #1 «người vào»" in tin[-1]
    trang["binary_sensor.cua"] = "on"                     # luật chặn khớp
    trang["light.den"] = "off"
    kh._xu_ly_duyet("light.den", [luat[0]], "binary_sensor.pk có người vào", 2.0)
    assert len(lam) == 1, "luật «không bật» đang khớp thì chặn"
    trang["binary_sensor.cua"] = "off"
    luat[0]["xac_minh"] = True
    monkeypatch.setattr(kh, "_co_nguoi_that", lambda tb, luc: (False, "camera không thấy ai"))
    kh._xu_ly_duyet("light.den", [luat[0]], "binary_sensor.pk có người vào", 3.0)
    assert len(lam) == 1, "xác minh không thấy người thì không bật"


def test_luat_hoi_tu_kiem_bang_ngoai_vi_roi_lam_va_hoi_dung_sai(monkeypatch):
    """Chủ máy 03/10/2026: "bật quạt phòng khách vẫn hỏi, chưa thực hiện rồi hỏi đúng sai, chưa dùng các ngoại vi để
    kiểm tra" — trường hợp duyệt #10 («người nhà mở cửa vào rồi ở lại») nên «hỏi», xac_minh false."""
    from services import du_doan_nha as dd, ha_client, kich_hoat_nha as kh, thong_bao

    lam: list[tuple] = []
    tin: list[str] = []
    nk: list[str] = []
    luat = [_luat(nen="hoi", chieu="bat", lan=1)]
    monkeypatch.setattr(kh, "_luat_duyet", lambda tb: luat)
    monkeypatch.setattr(ld, "so", lambda: {"fan.q": {"lan": [{"id": 1, "truong_hop": ["vào rồi ở lại"]}]}})
    trang = {"fan.q": "off"}
    monkeypatch.setattr(ha_client, "get_states", lambda use_cache=True: [{"entity_id": k, "state": v} for k, v in trang.items()])
    for ten, gia in (("_vua_lam", lambda *a, **k: False), ("_nguoi_vua_cham", lambda *a: False),
                     ("_nk", lambda tb, hd, kq, ng, ly="", *a, **k: nk.append(f"{kq}: {ly}")),
                     ("_ten_tb", lambda tb: "Quạt phòng khách"), ("_hen_kiem_lai", lambda *a: None)):
        monkeypatch.setattr(kh, ten, gia)
    monkeypatch.setattr(kh, "_lam", lambda tb, hd, tu_lam: lam.append((tb, hd)) or True)
    monkeypatch.setattr(dd, "ghi_nhan", lambda *a, **k: 9)
    monkeypatch.setattr(dd, "_cam_tu_lam", lambda ten: False)
    monkeypatch.setattr(thong_bao, "gui", lambda khoa, t, anh_url="": tin.append(t) or 1)
    xm = {"kq": (True, "khoảng cách radar 2,4 m trong vùng Phòng khách")}
    monkeypatch.setattr(kh, "_co_nguoi_that", lambda tb, luc: xm["kq"])

    kh._xu_ly_duyet("fan.q", luat, "binary_sensor.pk có người vào", 1.0)
    assert lam == [("fan.q", "on")], "ngoại vi thấy người → bật luôn, không hỏi trước"
    assert "Em đã bật Quạt phòng khách" in tin[-1] and "tự kiểm (khoảng cách radar 2,4 m" in tin[-1]
    assert "Đúng hay sai" in tin[-1]

    xm["kq"] = (False, "Cam phòng khách không thấy ai")
    kh._xu_ly_duyet("fan.q", luat, "binary_sensor.pk có người vào", 2.0)
    assert len(lam) == 1 and len(tin) == 1, "ngoại vi nhìn được mà không ai → không bật, không làm phiền"
    assert "không làm, không hỏi" in nk[-1]

    xm["kq"] = (None, "camera không nhìn được")
    kh._xu_ly_duyet("fan.q", luat, "binary_sensor.pk có người vào", 3.0)
    assert len(lam) == 1 and "không ạ?" in tin[-1], "ngoại vi không trả lời được → mới hỏi trước"

    monkeypatch.setattr(dd, "_cam_tu_lam", lambda ten: True)
    xm["kq"] = (True, "thấy người")
    kh._xu_ly_duyet("fan.q", luat, "binary_sensor.pk có người vào", 4.0)
    assert len(lam) == 1 and "không ạ?" in tin[-1], "khoá cửa / bếp / bình nóng lạnh: luôn hỏi"
