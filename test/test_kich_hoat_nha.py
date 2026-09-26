"""Học theo kích hoạt (26/09/2026): "khi có người vào phòng ngủ buổi tối thì bật đèn",
hỏi trước — đủ tin thì tự làm; cảm biến báo ảo khi nhà vắng thì im.

Mỗi ca dựng lại một tình huống ĐÃ ĐO trên kho thật (xem docstring `kich_hoat_nha`).
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import pytest  # noqa: E402

_TZ = timezone(timedelta(hours=7))
DEN = "switch.phong_ngu_l1"
NGU = "binary_sensor.hien_dien_phong_ngu_occupancy"
BEP = "binary_sensor.hien_dien_bep_presence"
CUA = "binary_sensor.cam_bien_cua_chinh_contact"
LUX = "sensor.hien_dien_phong_ngu_illuminance"
TT = [
    {"entity_id": DEN, "state": "off", "attributes": {"friendly_name": "Đèn phòng ngủ"}},
    {"entity_id": NGU, "state": "off", "attributes": {"friendly_name": "Hiện diện phòng ngủ",
                                                      "device_class": "occupancy"}},
    {"entity_id": BEP, "state": "off", "attributes": {"friendly_name": "Hiện diện bếp",
                                                      "device_class": "occupancy"}},
    {"entity_id": CUA, "state": "off", "attributes": {"friendly_name": "Cửa chính", "device_class": "door"}},
    {"entity_id": LUX, "state": "20", "attributes": {"device_class": "illuminance"}},
]


@pytest.fixture
def kh(tmp_path, monkeypatch):
    from services import du_doan_nha as dd, ha_client, kich_hoat_nha, lich_su_nha as ls

    ls._reset_for_tests()
    monkeypatch.setattr(ls, "_DB_PATH", tmp_path / "ls.sqlite")
    dd._reset_for_tests()
    monkeypatch.setattr(dd, "_DB_PATH", tmp_path / "dd.sqlite")
    kich_hoat_nha._reset_for_tests(tmp_path / "kh.json")
    monkeypatch.setattr(kich_hoat_nha, "_trang_thai_ha", lambda: TT)
    goi: list[tuple] = []
    monkeypatch.setattr(ha_client, "call_service", lambda d, s, data=None: goi.append((d, s, data)) or True)
    monkeypatch.setattr(ha_client, "get_state", lambda e: next((x for x in TT if x["entity_id"] == e), None))
    kich_hoat_nha.goi = goi
    ls._db()                    # tạo bảng
    yield kich_hoat_nha
    kich_hoat_nha._reset_for_tests(tmp_path / "kh.json")
    dd._reset_for_tests()
    ls._reset_for_tests()


def _sk(ma: str, gt: str, ts: float, do_ai: int = 0) -> None:
    from services import lich_su_nha as ls
    with ls._khoa_db:
        ls._db().execute(
            "INSERT INTO su_kien (ts, nguon, thiet_bi, truong, gia_tri, gia_tri_cu, do_ai, gio, thu)"
            " VALUES (?,?,?,?,?,?,?,0,0)", (ts, "ha", ma, "state", gt, "", do_ai))
        ls._db().commit()


def _luc(ngay_truoc: int, gio: int, phut: int = 0) -> float:
    d = datetime.now(_TZ).replace(hour=gio, minute=phut, second=0, microsecond=0) - timedelta(days=ngay_truoc)
    return d.timestamp()


def _nep_30_ngay() -> None:
    """Nếp thật của đèn phòng ngủ: tối người vào phòng (radar tắt > 3 phút rồi bật),
    30 giây sau bật đèn, 22h tắt. Ban ngày người vào mà không bật. Đèn bếp bật kèm
    ngay trước — việc làm kèm, không phải nguồn."""
    for n in range(29, 0, -1):
        t = _luc(n, 19, n % 20)
        _sk(LUX, "20", t - 900)
        _sk(NGU, "off", t - 600)
        _sk("switch.bep_left", "on", t - 40)
        _sk(NGU, "on", t)
        _sk(DEN, "on", t + 30)
        _sk(NGU, "off", t + 3000)
        _sk(NGU, "on", t + 3600)            # vào lại khi đèn đang bật: không phải lúc để bật
        _sk(DEN, "off", _luc(n, 22))
        _sk("switch.bep_left", "off", _luc(n, 22) + 5)
        s = _luc(n, 10)
        _sk(LUX, "300", s - 900)
        _sk(NGU, "off", s - 600)
        _sk(NGU, "on", s)                   # ban ngày: vào mà không bật


def test_hoc_ra_nguon_la_cam_bien_va_qua_kiem(kh):
    _nep_30_ngay()
    kh.dat_thiet_bi(DEN, bat=True)
    ra = kh.hoc(DEN)["on"]
    assert f"{NGU} có người vào" in ra["nguon"]
    assert not any(n.startswith("switch.") for n in ra["nguon"]), "đèn bật kèm không phải nguồn"
    assert ra["kiem"]["dat"] and ra["kiem"]["trung"] == ra["kiem"]["doan"]
    assert ra["luat"][0]["p"] >= kh.P_HOI


def _hoc_xong(kh) -> None:
    _nep_30_ngay()
    kh.dat_thiet_bi(DEN, bat=True)
    kh.hoc(DEN)


def test_toi_co_nguoi_vao_thi_hoi_ban_ngay_thi_im(kh):
    _hoc_xong(kh)
    _sk("switch.phong_hoc_l1", "on", _luc(0, 18))       # có người ở nhà
    q = kh.xet(DEN, "on", f"{NGU} có người vào", _luc(0, 19, 5))
    assert q["lam"] == "hoi", q
    assert kh.xet(DEN, "on", f"{NGU} có người vào", _luc(0, 10))["lam"] == "im"


def test_bao_ao_khi_nha_vang(kh):
    """Dịp lễ 30/08–02/09: radar phòng ngủ báo có người mà 61 giờ không ai bấm gì."""
    _hoc_xong(kh)
    luc = _luc(0, 19, 5)
    _sk(BEP, "on", luc - 3600)              # cảm biến khác cũng báo — không phải bằng chứng
    for i, ma in enumerate(("switch.a", "switch.b", "switch.c")):
        _sk(ma, "off", luc - 7200 + 0.1 * i)  # đồng loạt một giây — việc của máy
    q = kh.xet(DEN, "on", f"{NGU} có người vào", luc)
    assert q["lam"] == "im" and "báo ảo" in q["ly_do"]
    _sk(CUA, "on", luc - 1800)              # mở cửa chính — người về
    assert kh.xet(DEN, "on", f"{NGU} có người vào", luc)["lam"] == "hoi"


def test_nguoi_vua_tu_cham_va_ngoai_le(kh):
    _hoc_xong(kh)
    luc = _luc(0, 19, 5)
    _sk("switch.phong_hoc_l1", "on", luc - 3600)
    _sk(DEN, "off", luc - 60)
    assert "vừa tự" in kh.xet(DEN, "on", f"{NGU} có người vào", luc)["ly_do"]
    kh.dat_thiet_bi(DEN, ngoai_le=[{"hanh_dong": "on", "tu": "18:30", "den": "20:00"}])
    assert "ngoại lệ" in kh.xet(DEN, "on", f"{NGU} có người vào", luc + 600)["ly_do"]
    with pytest.raises(ValueError):
        kh.dat_thiet_bi(DEN, ngoai_le=[{"hanh_dong": "on", "tu": "25:00", "den": "20:00"}])
    with pytest.raises(ValueError):
        kh.dat_thiet_bi("sensor.x", bat=True)


def test_tra_loi_co_khong(kh):
    from services import du_doan_nha as dd
    id1 = dd.ghi_nhan(f"{DEN}#on", "on", 0.8, {}, "hoi")
    assert kh.tra_loi("mấy giờ rồi") is None
    assert "đã bật" in kh.tra_loi("Có!")
    assert kh.goi == [("switch", "turn_on", {"entity_id": DEN})]
    assert dd.so_luot(f"{DEN}#on") == 1 and dd.diem(f"{DEN}#on") > 0.5
    assert kh.tra_loi("có") is None, "không còn câu nào chờ thì không nhận"
    id2 = dd.ghi_nhan(f"{DEN}#off", "off", 0.8, {}, "hoi")
    assert "không tắt" in kh.tra_loi(f"không {id2}")
    assert dd.sai_gan_day(f"{DEN}#off") == 1 and id1 != id2


def test_tu_lam_nguoi_lam_nguoc_la_sai_im_lang_la_dung(kh, monkeypatch):
    from services import du_doan_nha as dd
    kh.dat_thiet_bi(DEN, bat=True)
    id1 = dd.ghi_nhan(f"{DEN}#on", "on", 0.9, {}, "tu_lam")
    kh._nguoi_lam(DEN, "off", time.time())
    assert dd._db().execute("SELECT ket_qua FROM du_doan WHERE id=?", (id1,)).fetchone()[0] == "sai"
    id2 = dd.ghi_nhan(f"{DEN}#on", "on", 0.9, {}, "tu_lam")
    assert kh.cham_tu_lam() == 0
    monkeypatch.setattr(time, "time", lambda t=time.time(): t + kh.CHAM_TU_LAM + 1)
    assert kh.cham_tu_lam() == 1
    assert dd._db().execute("SELECT ket_qua FROM du_doan WHERE id=?", (id2,)).fetchone()[0] == "dung"


def test_bot_tu_lam_ghi_do_ai():
    from services import lich_su_nha as ls
    ls.bot_tu_lam(DEN)
    assert ls.la_bot_tu_lam(DEN) and not ls.la_bot_tu_lam("switch.khac")
    ls._reset_for_tests()
    assert not ls.la_bot_tu_lam(DEN)


def test_su_kien_song_cung_luat_voi_luc_hoc(kh):
    """Radar mất người 1–2 phút rồi thấy lại (chủ máy 26/09/2026) không phải "vào"."""
    assert kh._nguon_cua(NGU, "off", 1000.0) == []
    assert kh._nguon_cua(NGU, "on", 1100.0) == []
    kh._nguon_cua(NGU, "off", 1200.0)
    assert kh._nguon_cua(NGU, "on", 1200.0 + kh.VANG) == [f"{NGU} có người vào"]
    assert kh._nguon_cua("switch.bep_left", "on", 2000.0) == []


def test_nhan_cham_cua_chu_may_thang_nhan_suy_ra(kh):
    """Chủ máy trả lời «không» thì mẫu đó là 0 dù sau đó người có bật."""
    from services import du_doan_nha as dd
    _hoc_xong(kh)
    t = _luc(3, 19, 3)
    with dd._khoa:
        dd._db().execute("INSERT INTO du_doan (ts, ten, hanh_dong, p, cach, ket_qua) VALUES (?,?,?,?,?,?)",
                         (t + 5, f"{DEN}#on", "on", 0.9, "hoi", "sai"))
        dd._db().commit()
    ra = kh.hoc(DEN)["on"]
    assert ra["kiem"]["trung"] == ra["kiem"]["doan"] - 1


def test_vao_lay_do_khong_thanh_luat_tat_den(kh):
    """Đo 26/09/2026: 17 lần "vào phòng ngủ rồi tắt đèn" đều là bật đèn, radar báo chậm
    vài chục giây, rồi tắt — người đang tự lo, không phải lúc bot hỏi "tắt không?"."""
    for n in range(29, 0, -1):
        t = _luc(n, 17, n % 20)
        _sk(NGU, "off", t - 600)
        _sk(DEN, "on", t)
        _sk(NGU, "on", t + 30)
        _sk(DEN, "off", t + 90)
    kh.dat_thiet_bi(DEN, bat=True)
    assert kh.hoc(DEN)["off"]["kiem"]["doan"] == 0


@pytest.mark.parametrize("cau, ra", [("đúng", "dung"), ("Đúng rồi!", "dung"), ("khong", "sai"),
                                     ("dừng", "sai"), ("dung", None), ("bật", None)])
def test_dung_va_dung_khong_lan(kh, cau, ra):
    """Bỏ dấu thì "đúng" (có) và "dừng" (không) cùng thành "dung" — so trên chữ có dấu."""
    from services import du_doan_nha as dd
    id_ = dd.ghi_nhan(f"{DEN}#off", "off", 0.8, {}, "hoi")
    kh.tra_loi(cau)
    kq = dd._db().execute("SELECT ket_qua FROM du_doan WHERE id=?", (id_,)).fetchone()[0]
    assert kq == (ra or "cho")
