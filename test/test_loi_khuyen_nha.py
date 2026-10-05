"""Hỏi chủ nhà TỪNG luật / từng thời gian (ở lại, vắng), lời khuyên từ nhật ký theo chu kỳ học giãn dần, sự kiện
«vắng N giây» (chủ máy 05/10/2026). Không gọi HA, không gọi model."""
from __future__ import annotations

import json
import os
import sqlite3
import time

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import loi_khuyen_nha as lk, luat_duyet as ld  # noqa: E402


def _luat(so, **k):
    return {"so": so, "nen": "bat", "khi": ["binary_sensor.pk có người vào"], "xac_minh": False, "chieu": "bat",
            "neu": [{"ma": "sensor.kc", "duoi": 3.5}], **k}


@pytest.fixture
def hoi(tmp_path, monkeypatch):
    from services import ha_client, hieu_thiet_bi_nha as ht, kich_hoat_nha as kh
    ld._reset_for_tests(tmp_path / "ld.json")
    lk._reset_for_tests(tmp_path / "lk.json")
    d = {"light.den": {"lan": [{"id": 1, "luc": 1, "luat": [_luat(1), _luat(2)], "truong_hop": ["vào", "ở lại"]}],
                       "cham": []}}
    (tmp_path / "ld.json").write_text(json.dumps(d), encoding="utf-8")
    tin: list[str] = []
    monkeypatch.setattr(ht, "bao_nhom", lambda t: tin.append(t) or 1)
    monkeypatch.setattr(kh, "_ten_ha", lambda: {"light.den": "Đèn trần", "sensor.kc": "Khoảng cách PK"})
    monkeypatch.setattr(ha_client, "get_states", lambda use_cache=True: [
        {"entity_id": "sensor.kc", "state": "2", "attributes": {"unit_of_measurement": "m"}}])
    giai: list[str] = []
    monkeypatch.setattr(ld, "giai_va_bao", lambda tb: giai.append(tb) or {})
    dat: list[tuple] = []
    monkeypatch.setattr(lk, "dat", lambda tb, loai, g: dat.append((tb, loai, g)))
    import threading
    # Câu kế gửi trong luồng nền — chạy ngay cho test đọc được.
    monkeypatch.setattr(threading, "Thread", lambda target, args=(), kwargs=None, **k: type(
        "T", (), {"start": lambda self: target(*args, **(kwargs or {}))})())
    return {"tin": tin, "giai": giai, "dat": dat}


def test_hoi_tung_luat_dung_thi_chay_sua_thi_giai_lai(hoi):
    ld.hoi_tiep()
    assert len(hoi["tin"]) == 1 and "trường hợp 1" in hoi["tin"][0]
    assert "Khoảng cách PK [sensor] dưới 3.5 m" in hoi["tin"][0], "khoảng cách kèm đơn vị cho chủ nhà đọc"
    assert ld.hoi_tiep() is None, "đang có câu chờ thì không gửi chồng"
    h = ld._hoi_nap()
    h["cho"]["luc"] -= ld.CHO_HOI_GIAY + 60                        # quá 24 giờ chưa trả lời
    ld._hoi_luu(h)
    assert "trường hợp 1" in ld.hoi_tiep(), "chủ máy: «khi nào có câu trả lời thì mới đến 2» — nhắc lại câu 1"
    hoi["tin"].pop()
    assert "anh duyệt" in ld.tra_loi("Đúng")
    assert [l["so"] for l in ld.ap("light.den")] == [1]
    assert "trường hợp 2" in hoi["tin"][-1], "trả lời xong tự gửi câu kế"
    dap = ld.tra_loi("sửa khoảng cách dưới 3 m")
    assert "cần sửa" in dap and hoi["giai"] == ["light.den"], "hết luật của thiết bị mà có lời sửa → giải lại"
    c = ld.so()["light.den"]["cham"][-1]
    assert c["dung"] is False and "dưới 3 m" in c["ghi_chu"], "lời sửa vào đề lần sau (mục D)"
    assert ld.tra_loi("đúng") is None, "hết câu chờ thì không nhận"


def test_dung_tron_nhuong_cau_hoi_bat_tat_moi_hon(hoi):
    ld.hoi_tiep()
    assert ld.tra_loi("đúng", sau=time.time() + 5) is None, "bot vừa tự bật đèn hỏi đúng/sai — «đúng» là của câu đó"
    assert ld.tra_loi("sửa vắng 30 giây", sau=time.time() + 5) is not None, "«sửa …» chỉ thuộc câu luật"


def test_hoi_thoi_gian_o_lai_vang_tung_cai_va_loi_khuyen(hoi):
    (ld._PATH).write_text("{}", encoding="utf-8")                 # không còn luật chờ
    ld.xep_hoi([{"kieu": "cai_dat", "tb": "light.den", "loai": "o_lai", "cu": None},
                {"kieu": "cai_dat", "tb": "light.den", "loai": "vang", "cu": 120}])
    assert "thời gian ở lại" in hoi["tin"][-1] and "bật ngay" in hoi["tin"][-1]
    assert "đặt thời gian ở lại = 10 giây" in ld.tra_loi("sửa 10 giây")
    assert hoi["dat"] == [("light.den", "o_lai", 10.0)]
    assert "thời gian vắng" in hoi["tin"][-1] and "2 phút" in hoi["tin"][-1]
    assert "xác nhận" in ld.tra_loi("đúng") and len(hoi["dat"]) == 1
    ld.xep_hoi([{"kieu": "khuyen", "tb": "light.den", "loai": "vang", "cu": 120, "moi": 180, "vi": "6 lần bật lại"}])
    assert "«đồng ý»" in hoi["tin"][-1] and "2 phút → 3 phút" in hoi["tin"][-1]
    assert "em đổi" in ld.tra_loi("đồng ý") and hoi["dat"][-1] == ("light.den", "vang", 180.0)
    ld.xep_hoi([{"kieu": "khuyen", "tb": "light.den", "loai": "o_lai", "cu": 10, "moi": 30, "vi": "x"}])
    assert "giữ nguyên" in ld.tra_loi("không") and len(hoi["dat"]) == 2
    assert "chưa đọc được số" in (ld.xep_hoi([{"kieu": "cai_dat", "tb": "light.den", "loai": "vang", "cu": 60}])
                                  or ld.tra_loi("sửa lâu hơn"))


def test_luat_khong_doi_giu_loi_duyet_cua_chu_nha():
    th = ["vào", "ở lại"]
    x = {"lan": [{"id": 1, "luat": [_luat(1), _luat(2)], "truong_hop": th},
                 {"id": 2, "luat": [_luat(1), _luat(2, xac_minh=True)], "truong_hop": th}],
         "cham": [{"lan": 1, "so": 1, "dung": True, "cham_boi": "chu_may"},
                  {"lan": 1, "so": 2, "dung": True, "cham_boi": "chu_may"}]}
    assert ld._mang_sang(x, x["lan"][1]) == [1], "luật 2 đổi (thêm xác minh) → hỏi lại"
    y = {"lan": [{"id": 1, "luat": [_luat(1)], "truong_hop": th}, {"id": 2, "luat": [_luat(1)], "truong_hop": th}],
         "cham": [{"lan": 1, "so": 1, "dung": True, "cham_boi": "claude"}]}
    assert ld._mang_sang(y, y["lan"][1]) == [] and len(y["cham"]) == 1, "giáo viên chấm không phải lời duyệt"
    z = {"lan": [{"id": 1, "luat": [_luat(1)], "truong_hop": ["vào"]},
                 {"id": 2, "luat": [_luat(1)], "truong_hop": ["trường hợp khác"]}],
         "cham": [{"lan": 1, "so": 1, "dung": True, "cham_boi": "chu_may"}]}
    assert ld._mang_sang(z, z["lan"][1]) == [], "cùng số mà khác trường hợp → không mang sang"


def test_doc_so():
    assert lk.doc_so("30 giây") == 30 and lk.doc_so("2 phút") == 120 and lk.doc_so("1 phút 30") == 90
    assert lk.doc_so("90s") == 90 and lk.doc_so("lâu hơn") is None


def test_chu_ky_gian_dan():
    assert [lk.cach_ngay(i) for i in range(8)] == [5, 5, 7, 7, 7, 7, 30, 30]


@pytest.fixture
def nhat_ky(tmp_path, monkeypatch):
    from services import nhat_ky_kich_hoat as nk
    nk._reset_for_tests(tmp_path / "nk.sqlite")
    return nk


def test_do_va_khuyen_tu_nhat_ky(nhat_ky):
    t0 = time.time() - 86400
    # bot tắt 10 lần, 3 lần người bật lại trong 2 phút; bot bật 4 lần, 2 lần người tắt ngay
    for i in range(10):
        nhat_ky.ghi("light.den", "off", "lam", luc=t0 + i * 3600)
        if i < 3:
            nhat_ky.ghi("light.den", "on", "nguoi", luc=t0 + i * 3600 + 120)
    for i in range(4):
        nhat_ky.ghi("light.den", "on", "lam", luc=t0 + 50000 + i * 3600)
        nhat_ky.ghi("light.den", "off", "nguoi" if i < 2 else "lam", luc=t0 + 50000 + i * 3600 + 60)
    so = lk.do("light.den", t0 - 1)
    assert so == {"bot_bat": 4, "bot_tat": 12, "bat_bi_tat": 2, "tat_bi_bat": 3}
    kq = {x["loai"]: x for x in lk.khuyen("light.den", {"o_lai": None, "vang": 120}, so, 5)}
    assert kq["o_lai"]["moi"] == 30 and kq["vang"]["moi"] == 180
    rut = lk.khuyen("light.den", {"o_lai": 30, "vang": 600}, {"bot_bat": 0, "bot_tat": 12, "bat_bi_tat": 0,
                                                              "tat_bi_bat": 0}, 7)
    assert rut[0]["moi"] == 450, "12 lần tắt không lần nào bị bật lại → đề xuất rút ngắn"
    assert lk.khuyen("light.den", {"o_lai": 30, "vang": 120}, {"bot_bat": 20, "bot_tat": 20, "bat_bi_tat": 1,
                                                               "tat_bi_bat": 1}, 7) == []


def test_chay_chi_khi_toi_ky_va_bo_so_vua_doi(tmp_path, monkeypatch):
    from services import kich_hoat_nha as kh
    lk._reset_for_tests(tmp_path / "lk.json")
    monkeypatch.setattr(kh, "ds_thiet_bi", lambda: {"light.den": {"bat": True}})
    gt = {"o_lai": None, "vang": 120}
    monkeypatch.setattr(lk, "gia_tri", lambda tb: dict(gt))
    monkeypatch.setattr(lk, "do", lambda tb, tu, den: {"bot_bat": 0, "bot_tat": 10, "bat_bi_tat": 0, "tat_bi_bat": 4})
    xep: list = []
    monkeypatch.setattr(ld, "xep_hoi", lambda m: xep.extend(m))
    now = time.time()
    assert lk.chay(now) == [] and lk.chu_ky(now)["lan"] == 0, "lần đầu chỉ bắt đầu đếm"
    assert lk.chay(now + 4 * 86400) == []
    assert [x["loai"] for x in lk.chay(now + 5 * 86400 + 1)] == ["vang"] and len(xep) == 1
    gt["vang"] = 180                                    # chủ nhà đổi giữa kỳ
    assert lk.chay(now + 10 * 86400 + 2) == [], "số vừa đổi → dữ liệu là của số cũ, chờ kỳ sau"
    assert lk.chu_ky()["lan"] == 2 and lk.cach_ngay(2) == 7


def test_su_kien_vang_n_giay_qua_kiem_bien():
    luat, _, loi = ld.kiem({"luat": [{"so": 1, "nen": "tat", "khi": ["binary_sensor.pk vắng 30 giây"]},
                                     {"so": 2, "nen": "tat", "khi": ["binary_sensor.pk vắng 5 giây"]}]},
                           2, {"binary_sensor.pk"}, set())
    assert [l["so"] for l in luat] == [1] and "ngoài 10–3600" in loi[0]


def test_bo_kich_hoat_hen_vang_n_giay(monkeypatch):
    from services import kich_hoat_nha as kh
    hen: list[tuple] = []
    monkeypatch.setattr(kh, "ds_thiet_bi", lambda: {"light.hoc": {}})
    monkeypatch.setattr(kh, "_luat_duyet", lambda tb: [{"khi": ["binary_sensor.hoc vắng 30 giây"], "nen": "tat"}])
    import threading
    monkeypatch.setattr(threading, "Timer", lambda giay, f, args=(): type(
        "T", (), {"daemon": False, "start": lambda self: hen.append((giay, args))})())
    kh._hen_vang_duyet("binary_sensor.hoc", 100.0)
    kh._hen_vang_duyet("binary_sensor.khac", 100.0)
    assert hen == [(30, ("light.hoc", "binary_sensor.hoc", "binary_sensor.hoc vắng 30 giây", 100.0, "off"))]


def test_viec_heartbeat_co_ham_thi_phai_duoc_chay(tmp_path):
    """Bài học 05/10/2026: `luat_duyet` và `tu_bat_theo_nep` có hàm trong `_HANDLERS` mà không có trong danh sách
    việc → chưa chạy lần nào. `khoa_cua_nha` cố ý chạy vòng riêng."""
    from services.agent import heartbeat as hb
    hb._reset_for_tests(tmp_path)
    co = {t["id"] for t in hb._parse_tasks()}
    assert set(hb._HANDLERS) - co == {"khoa_cua_nha"}
