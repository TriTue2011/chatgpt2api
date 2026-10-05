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


def test_kiem_loai_luat_tu_mau_thuan():
    """Luật đòi cùng cảm biến hai trạng thái (hoặc <X và >Y) bị loại ở biên, không vào sổ chạy."""
    ma_co = {"binary_sensor.p", "sensor.kc", "binary_sensor.x"}
    data = {"luat": [
        {"so": 1, "nen": "bat", "khi": ["binary_sensor.x có người vào"],
         "neu": [{"ma": "binary_sensor.p", "la": "on"}, {"ma": "binary_sensor.p", "la": "off"}]},
        {"so": 2, "nen": "bat", "khi": ["binary_sensor.x có người vào"],
         "neu": [{"ma": "binary_sensor.p", "la": "on"}, {"ma": "binary_sensor.p", "la": "on", "phu_dinh": True}]},
        {"so": 3, "nen": "bat", "khi": ["binary_sensor.x có người vào"],
         "neu": [{"ma": "sensor.kc", "duoi": 2.0}, {"ma": "sensor.kc", "tren": 3.0}]},
        {"so": 4, "nen": "bat", "khi": ["binary_sensor.x có người vào"],
         "neu": [{"ma": "binary_sensor.p", "la": "on"}, {"ma": "sensor.kc", "duoi": 3.0}]}]}
    luat, khong, loi = ld.kiem(data, 4, ma_co, set())
    hop_le = {l["so"] for l in luat}
    assert hop_le == {4}, "chỉ luật 4 không mâu thuẫn"
    assert any("1:" in e and "mâu thuẫn" in e for e in loi)
    assert any("mâu thuẫn" in e for e in loi if e.startswith("luật 3"))
    # băng Y<v<X (duoi>tren) KHÔNG phải mâu thuẫn
    ok = ld._mau_thuan_trong_luat([{"ma": "sensor.kc", "duoi": 5.0}, {"ma": "sensor.kc", "tren": 2.0}])
    assert ok is None


def test_do_tin_vao_de_chi_cam_bien_trong_de(monkeypatch):
    """B4: chỉ liệt cảm biến NHIỄU/KẸT có trong đề; lành không liệt."""
    from services import do_tin_cam_bien as dt
    monkeypatch.setattr(dt, "tat_ca", lambda so_ngay=3.0: {"nhi_phan": [
        {"ma": "binary_sensor.x", "nhan": "nhieu", "doi_ngay": 900, "ngan_tl": 0.5},
        {"ma": "binary_sensor.y", "nhan": "ket", "im_gio": 30},
        {"ma": "binary_sensor.z", "nhan": "lanh", "doi_ngay": 20, "ngan_tl": 0.02},
        {"ma": "binary_sensor.ngoai_de", "nhan": "nhieu", "doi_ngay": 500, "ngan_tl": 0.5}],
        "so": [{"ma": "sensor.kc", "nhan": "nhieu", "cham0_tl": 0.8}]})
    ra = dict(ld._do_tin_cam_bien(["binary_sensor.x", "binary_sensor.y", "binary_sensor.z", "sensor.kc"]))
    assert "binary_sensor.x" in ra and "NHIỄU" in ra["binary_sensor.x"]
    assert "binary_sensor.y" in ra and "KẸT" in ra["binary_sensor.y"]
    assert "binary_sensor.z" not in ra, "lành không liệt"
    assert "binary_sensor.ngoai_de" not in ra, "ngoài đề không liệt"
    assert "sensor.kc" in ra and "radar" in ra["sensor.kc"]


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
        "cham": [{"lan": 1, "so": 1, "dung": True, "cham_boi": "chu_may"},
                 {"lan": 1, "so": 2, "dung": True, "cham_boi": "chu_may"}]}}
    (tmp_path / "ld.json").write_text(json.dumps(d), encoding="utf-8")
    giai: list[str] = []
    monkeypatch.setattr(ld, "giai_va_bao", lambda tb: giai.append(tb) or {})
    return giai


def test_ap_chi_chu_nha_quyet_theo_tung_truong_hop(so):
    """Lần 2 chỉ còn trường hợp «a»: luật «b» thôi chạy. Lần 2 chưa ai trả lời → luật «a» anh duyệt ở lần 1 vẫn chạy.
    Giáo viên chấm KHÔNG làm luật nào chạy hay thôi chạy (chủ máy 05/10/2026: "bạn chỉ chấm đúng sai")."""
    assert [(l["lan"], l["so"]) for l in ld.ap("light.den")] == [(1, 1)]
    ld.cham("light.den", 1, False, cham_boi="claude")            # giáo viên chấm sai lần 2 — chỉ là ghi chú
    assert [(l["lan"], l["so"]) for l in ld.ap("light.den")] == [(1, 1)]
    ld.cham("light.den", 1, True, cham_boi="chu_may")            # chủ nhà duyệt luật lần 2
    assert [(l["lan"], l["so"]) for l in ld.ap("light.den")] == [(2, 1)]
    ld.cham("light.den", 1, False, cham_boi="chu_may")
    assert ld.ap("light.den") == [], "chủ nhà nói sai → thôi chạy"


def test_chay_sai_ghi_gia_tri_cham_sai_va_giai_lai(so):
    import time
    ld.chay_sai("light.den", 1, 1, ["binary_sensor.pk=on✓"], "chủ nhà trả lời sai")
    time.sleep(0.2)
    assert so == ["light.den"]
    assert ld.ap("light.den") == [], "luật chạy sai (chủ nhà nói sai) thôi chạy"
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


def test_loi_cham_cu_doi_so_theo_loi_truong_hop():
    """Danh sách trường hợp đổi (chủ máy bỏ 19/24): lời chấm cũ theo số phải đổi sang số mới, cái đã bỏ thì thôi."""
    x = {"lan": [{"id": 5, "truong_hop": ["a", "b", "c"]}],
         "cham": [{"lan": 5, "so": 1, "dung": False, "ghi_chu": "về a"}, {"lan": 5, "so": 3, "dung": False, "ghi_chu": "về c"},
                  {"lan": 9, "so": 1, "dung": True, "ghi_chu": "lần không còn"}]}
    th = [{"tinh_huong": "c"}, {"tinh_huong": "z"}]
    assert [(c["so"], c["ghi_chu"]) for c in ld._theo_loi(x, x["cham"], th)] == [(1, "về c")]


def test_cam_bien_ghep_doc_duoc_trong_dieu_kien(monkeypatch, tmp_path):
    """Đo 05/10/2026: «Tivi phòng khách đang bật» (cảm biến GHÉP do c2a tính) không có trong trạng thái HA — điều
    kiện dùng nó luôn sai. Nay tính từ chính trạng thái đang xét."""
    from services import cam_bien_ghep
    cam_bien_ghep._reset_for_tests(tmp_path / "ghep.json")
    cam_bien_ghep.dat("binary_sensor.c2a_tivi", "Tivi đang bật", {"ma": "media_player.tv", "la": ["on", "playing"]})
    st = {"media_player.tv": {"entity_id": "media_player.tv", "state": "playing"}}
    assert ld.kiem_dieu_kien([{"ma": "binary_sensor.c2a_tivi", "la": "on"}], 1.0, st)[0]
    st["media_player.tv"]["state"] = "off"
    assert not ld.kiem_dieu_kien([{"ma": "binary_sensor.c2a_tivi", "la": "on"}], 1.0, st)[0]


def test_khoang_cach_dung_yen(monkeypatch, tmp_path):
    """Nhận ra người NẰM YÊN (ngủ ở phòng khách): những lúc có số đo thì gần như không đổi suốt N giây; số 0 (radar
    không thấy cử động — đo thật: người nằm yên làm khoảng cách về 0) không phá đứng yên."""
    import sqlite3
    import time as _t
    from services import lich_su_nha as ls
    db = tmp_path / "ls.sqlite"
    monkeypatch.setattr(ls, "_DB_PATH", db)
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE so_do (o_5p INT, thiet_bi TEXT, truong TEXT, nho REAL, lon REAL, tb REAL, n INT)")
    now = _t.time()
    for k in range(7):
        c.execute("INSERT INTO so_do VALUES (?,?,?,?,?,?,?)", (int(now // 300) - k, "sensor.kc", "state", 2.1, 2.3, 2.2, 5))
    c.commit()
    dk = [{"ma": "sensor.kc", "dung_yen_giay": 1800, "lech": 0.3}]
    st = {"sensor.kc": {"state": "2.2"}}
    assert ld.kiem_dieu_kien(dk, now, st)[0]
    assert ld.kiem_dieu_kien(dk, now, {"sensor.kc": {"state": "0"}})[0], "0 = radar không thấy cử động — nằm yên"
    c.execute("UPDATE so_do SET lon=3.4 WHERE o_5p=?", (int(now // 300) - 3,))
    c.commit()
    assert not ld.kiem_dieu_kien(dk, now, st)[0], "có lúc đi lại trong 30 phút → không đứng yên"
    assert ld._kiem_dk({"ma": "sensor.kc", "dung_yen_giay": 1800}, {"sensor.kc"}, set()) == \
        {"ma": "sensor.kc", "dung_yen_giay": 1800, "lech": 0.3}


def test_kiem_mot_chuan_hoa_chu_nguoi_go(monkeypatch):
    """Chủ máy 05/10/2026: «Lưu & chạy» bị từ chối vì gõ 6:30 và «liền 0». Chữ người gõ được chuẩn hoá ở biên web."""
    monkeypatch.setattr(ld, "cam_bien", lambda: [{"ma": "binary_sensor.pk"}, {"ma": "binary_sensor.cam"},
                                                  {"ma": "sensor.kc"}])
    from services import lich_sinh_hoat
    monkeypatch.setattr(lich_sinh_hoat, "ds", lambda: [])
    l = {"chieu": "bat", "nen": "bat", "khi": ["binary_sensor.pk có người vào"], "xac_minh": False,
         "neu": [{"ma": "gio", "tu": "6:30", "den": "21h45"}, {"ma": "sensor.kc", "duoi": 4},
                 {"ma": "binary_sensor.cam", "la": "on", "lien_giay": 0}]}
    r = ld.kiem_mot("light.x", l)
    assert r["neu"][0] == {"ma": "gio", "tu": "06:30", "den": "21:45"}
    assert r["neu"][2] == {"ma": "binary_sensor.cam", "la": "on"}, "liền 0 giây = không đòi kéo dài"
    with pytest.raises(ValueError, match="khung giờ"):
        ld.kiem_mot("light.x", {**l, "neu": [{"ma": "gio", "tu": "25:00", "den": "21:45"}]})
    with pytest.raises(ValueError, match="ngoài 1–86400"):
        ld.kiem_mot("light.x", {**l, "neu": [{"ma": "binary_sensor.cam", "la": "on", "lien_giay": -5}]})


def test_vua_chuyen_giay_kiem_bien_va_khong_di_chung():
    """Chủ máy 06/10/2026: điều kiện cảm biến cần chế độ «chuyển trạng thái» — cửa mở sẵn không được tính."""
    assert ld._kiem_dk({"ma": "binary_sensor.cua", "la": "on", "vua_chuyen_giay": 30}, MA, set()) == \
        {"ma": "binary_sensor.cua", "la": "on", "vua_chuyen_giay": 30}
    _, _, loi = ld.kiem({"luat": [_luat(neu=[{"ma": "binary_sensor.cua", "la": "on", "lien_giay": 5,
                                              "vua_chuyen_giay": 30}])]}, 1, MA, set())
    assert loi and "không đi chung" in loi[0]
    assert ld._chuan_dk_nguoi({"ma": "binary_sensor.cua", "la": "on", "vua_chuyen_giay": 0}) == \
        {"ma": "binary_sensor.cua", "la": "on"}


def test_vua_chuyen_doc_so_lich_su_that(tmp_path, monkeypatch):
    import sqlite3

    from services import cam_bien_ghep, lich_su_nha
    db = tmp_path / "ls.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE su_kien (thiet_bi TEXT, truong TEXT, gia_tri TEXT, gia_tri_cu TEXT, ts REAL)")
    luc = 1_000_000.0
    c.executemany("INSERT INTO su_kien VALUES (?,?,?,?,?)", [
        ("binary_sensor.cua", "state", "on", "off", luc - 3600),     # mở từ 1 giờ trước, để mở luôn
        ("binary_sensor.cua2", "state", "on", "off", luc - 20),      # vừa mở 20 giây trước
        ("binary_sensor.cua2", "state", "off", "on", luc - 10),      # rồi đóng ngay — vẫn là «vừa mở»
        ("binary_sensor.cua3", "state", "on", "on", luc - 5),        # ghi lặp cùng trạng thái — không phải chuyển
    ])
    c.commit(); c.close()
    monkeypatch.setattr(lich_su_nha, "_DB_PATH", db)
    monkeypatch.setattr(cam_bien_ghep, "la_ghep", lambda ma: False)
    assert not ld._vua_chuyen("binary_sensor.cua", "on", luc - 30), "cửa để mở từ trước không tính"
    assert ld._vua_chuyen("binary_sensor.cua2", "on", luc - 30), "mở rồi đóng ngay vẫn là vừa mở"
    assert not ld._vua_chuyen("binary_sensor.cua3", "on", luc - 30)
    st = {"binary_sensor.cua": _st("binary_sensor.cua", "on", 3600, luc)}
    ok, _ = ld.kiem_dieu_kien([{"ma": "binary_sensor.cua", "la": "on", "vua_chuyen_giay": 30}], luc, st)
    assert not ok, "đang mở nhưng không VỪA mở → điều kiện sai, đèn không bật lại"


def test_so_do_trong_ngoai_khoang():
    """Chủ máy 06/10/2026: số đo có «trong khoảng», «ngoài khoảng» ngoài trên / dưới."""
    assert ld._kiem_dk({"ma": "sensor.kc", "tren": 1, "duoi": 3}, MA, set()) == {"ma": "sensor.kc", "tren": 1.0, "duoi": 3.0}
    with pytest.raises(ValueError, match="khoảng sai"):
        ld._kiem_dk({"ma": "sensor.kc", "tren": 3, "duoi": 1}, MA, set())
    luc = 1_000_000.0
    st = lambda v: {"sensor.kc": _st("sensor.kc", v)}               # noqa: E731
    trong = [{"ma": "sensor.kc", "tren": 1.0, "duoi": 3.0}]
    ngoai = [{"ma": "sensor.kc", "tren": 1.0, "duoi": 3.0, "phu_dinh": True}]
    assert ld.kiem_dieu_kien(trong, luc, st("2.1"))[0] and not ld.kiem_dieu_kien(trong, luc, st("3.5"))[0]
    assert ld.kiem_dieu_kien(ngoai, luc, st("3.5"))[0] and not ld.kiem_dieu_kien(ngoai, luc, st("2.1"))[0]
    assert ld._mau_thuan_trong_luat(trong + [{"ma": "sensor.kc", "duoi": 0.5}]), "dưới 0.5 VÀ trong 1–3: không bao giờ đúng"
    assert ld._mau_thuan_trong_luat(ngoai + [{"ma": "sensor.kc", "duoi": 0.5}]) is None


def test_gio_kem_thu_va_khoang_ngay():
    """Chủ máy 06/10/2026: thời gian chọn kèm ngày. Khung qua nửa đêm tính theo ngày BẮT ĐẦU."""
    x = ld._kiem_dk({"ma": "gio", "tu": "22:00", "den": "06:00", "thu": [4], "tu_ngay": "2026-10-01"}, MA, set())
    assert x == {"ma": "gio", "tu": "22:00", "den": "06:00", "thu": [4], "tu_ngay": "2026-10-01"}
    tz = timezone(timedelta(hours=7))
    t6_23h = datetime(2026, 10, 9, 23, 0, tzinfo=tz).timestamp()      # thứ 6
    t7_2h = datetime(2026, 10, 10, 2, 0, tzinfo=tz).timestamp()       # 2 giờ sáng thứ 7 — thuộc khung tối thứ 6
    t7_23h = datetime(2026, 10, 10, 23, 0, tzinfo=tz).timestamp()
    truoc = datetime(2026, 9, 25, 23, 0, tzinfo=tz).timestamp()       # thứ 6 nhưng trước tu_ngay
    ok = lambda luc: ld.kiem_dieu_kien([x], luc, {})[0]               # noqa: E731
    assert ok(t6_23h) and ok(t7_2h) and not ok(t7_23h) and not ok(truoc)
    assert "thu" not in ld._kiem_dk({"ma": "gio", "tu": "06:00", "den": "07:00", "thu": list(range(7))}, MA, set())
    for sai in ({"thu": []}, {"thu": [7]}, {"tu_ngay": "10/10/2026"}, {"tu_ngay": "2026-10-10", "den_ngay": "2026-10-01"}):
        with pytest.raises(ValueError):
            ld._kiem_dk({"ma": "gio", "tu": "06:00", "den": "07:00", **sai}, MA, set())


def test_so_sanh_hai_cam_bien():
    """Chủ máy 06/10/2026: "so sánh 2 cảm biến mà giống nhau thì thực hiện"."""
    assert ld._kiem_dk({"ma": "binary_sensor.pk", "so_voi": "binary_sensor.cua"}, MA, set()) == \
        {"ma": "binary_sensor.pk", "so_voi": "binary_sensor.cua"}
    with pytest.raises(ValueError):
        ld._kiem_dk({"ma": "binary_sensor.pk", "so_voi": "binary_sensor.pk"}, MA, set())
    with pytest.raises(ValueError):
        ld._kiem_dk({"ma": "binary_sensor.pk", "so_voi": "binary_sensor.khong_co"}, MA, set())
    luc = 1_000_000.0
    dk = [{"ma": "binary_sensor.pk", "so_voi": "binary_sensor.cua"}]
    st = lambda a, b: {"binary_sensor.pk": _st("binary_sensor.pk", a), "binary_sensor.cua": _st("binary_sensor.cua", b)}  # noqa: E731
    assert ld.kiem_dieu_kien(dk, luc, st("on", "ON"))[0]
    assert not ld.kiem_dieu_kien(dk, luc, st("on", "off"))[0]
    assert not ld.kiem_dieu_kien(dk, luc, st("unavailable", "unavailable"))[0], "cùng mất tín hiệu không phải giống"
    assert ld._giong("21", "21.0") and not ld._giong("21", "21.5")
    assert ld.kiem_dieu_kien([{**dk[0], "phu_dinh": True}], luc, st("on", "off"))[0], "phủ định = khác nhau"
