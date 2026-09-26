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
    from services import lich_sinh_hoat
    lich_sinh_hoat._reset_for_tests(tmp_path / "lsh.json")
    monkeypatch.setattr(kich_hoat_nha, "_trang_thai_ha", lambda: TT)
    monkeypatch.setattr(kich_hoat_nha, "_so_do", lambda tb: (set(), set()))   # sơ đồ rỗng → tự dò
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
    assert "không làm" in kh.xet(DEN, "on", f"{NGU} có người vào", luc + 600)["ly_do"]
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


def test_cho_tu_lam_ngay_van_giu_hai_chot(kh):
    """Chủ máy 26/09/2026: "tôi muốn test thử tính năng bot tự thực hiện" — không chờ
    50 lượt, nhưng sai 2/10 vẫn quay về hỏi, và khoá/bếp/bình nóng lạnh không bao giờ."""
    from services import du_doan_nha as dd
    _hoc_xong(kh)
    luc = _luc(0, 19, 5)
    _sk("switch.phong_hoc_l1", "on", luc - 3600)
    nguon = f"{NGU} có người vào"
    assert kh.xet(DEN, "on", nguon, luc)["lam"] == "hoi"
    kh.dat_thiet_bi(DEN, tu_lam=True)
    assert kh.xet(DEN, "on", nguon, luc)["lam"] == "tu_lam"
    for _ in range(2):
        dd.ghi_sai(dd.ghi_nhan(f"{DEN}#on", "on", 0.9, {}, "tu_lam"))
    assert kh.xet(DEN, "on", nguon, luc)["lam"] == "hoi"
    kh.dat_thiet_bi("switch.binh_nong_lanh", bat=True, tu_lam=True)
    assert not kh._duoc_tu_lam("switch.binh_nong_lanh", "on")


def test_bot_vua_tu_lam_thi_khong_doi_chieu_ngay(kh):
    """Không nhiễu như automation HA: bot vừa bật thì không tắt ngay vì radar báo vắng."""
    from services import du_doan_nha as dd
    dd.ghi_nhan(f"{DEN}#on", "on", 0.9, {}, "tu_lam")
    assert kh._vua_lam(DEN, "off") and kh._vua_lam(DEN, "on")
    assert not kh._vua_lam("switch.khac", "off")
    dd.ghi_nhan("switch.khac#on", "on", 0.9, {}, "hoi")
    assert not kh._vua_lam("switch.khac", "off"), "chỉ HỎI thì chưa đổi gì — hướng kia vẫn được"


def test_quanh_gio_tu_lam_hoi_im():
    from services import kich_hoat_nha as kh
    g = [[0, 0] for _ in range(24)]
    g[19] = [20, 20]
    g[22] = [3, 5]
    g[23] = [0, 5]
    assert kh.quanh_gio(g, 19.5)[2] == "tu_lam"
    assert kh.quanh_gio(g, 21.5)[2] == "hoi"       # 20–22h: 3/5 — lưng chừng
    assert kh.quanh_gio(g, 0.5)[2] == "im"         # 23h–1h: 0/5
    assert kh.quanh_gio(g, 10)[2] == "hoi"         # chưa đủ lần nào: hỏi, không tự làm


def test_gio_ngu_im_khung_doc_sach_thi_hoi(kh):
    """Đo 30 ngày: lúc 23h luật nói bật 5/5 lần có người vào, người bật 0/5 — đang ngủ
    trở mình. Bot im (không nhắn đánh thức). Chủ máy đặt khung «Đọc sách» luôn hỏi thì hỏi."""
    _hoc_xong(kh)
    kh.dat_thiet_bi(DEN, tu_lam=True)
    mh = kh._nap()["mo_hinh"][DEN]["on"]
    mh["theo_gio"][23] = [0, 5]
    mh["theo_gio"][22] = [0, 3]
    luc = _luc(0, 23, 10)
    _sk("switch.phong_hoc_l1", "on", luc - 3600)
    nguon = f"{NGU} có người vào"
    x = kh._dac_trung(luc, nguon, mh["nguon"], {LUX: ([luc - 1], ["5"])})
    if kh.doan_cay(mh["cay"], x) < kh.P_HOI:
        mh["cay"] = {"p": 0.9, "n": 20, "k": 18}      # giả như luật chỉ biết "từ 15:52"
    q = kh.xet(DEN, "on", nguon, luc)
    assert q["lam"] == "im" and "ít khi" in q["ly_do"], q
    kh.dat_thiet_bi(DEN, ngoai_le=[{"hanh_dong": "on", "tu": "21:00", "den": "23:30",
                                    "cach": "hoi", "ten": "Đọc sách"}])
    q = kh.xet(DEN, "on", nguon, luc)
    assert q["lam"] == "hoi" and "Đọc sách" in q["ly_do"], q
    with pytest.raises(ValueError):
        kh.dat_thiet_bi(DEN, ngoai_le=[{"hanh_dong": "on", "tu": "21:00", "den": "23:30", "cach": "bat"}])


def test_tach_dieu_khien_va_kiem_bao_ao(kh):
    """Chủ máy 26/09/2026: thấy cảm biến ban công trong danh sách của đèn phòng ngủ — "nên
    tách điều khiển và check báo ảo". Nguồn cây không bao giờ bật theo thì là "đã xét"."""
    _hoc_xong(kh)
    mh = kh._nap()["mo_hinh"][DEN]["on"]
    assert f"{NGU} có người vào" in mh["dieu_khien"]
    mh["nguon"] = mh["nguon"] + [f"{BEP} có người vào"]        # ứng viên cây không dùng
    tq = kh.tong_quan()[0]
    assert [n["ma"] for n in tq["huong"]["on"]["nguon"]] == [f"{NGU} có người vào"]
    assert [n["ma"] for n in tq["huong"]["on"]["da_xet"]] == [f"{BEP} có người vào"]
    assert tq["kiem_ao"]["ap_cho"] == ["Hiện diện phòng ngủ có người vào"]
    assert tq["kiem_ao"]["cua"] == ["Cửa chính"] and tq["kiem_ao"]["nhin_lai_gio"] == 6
    # Lần chặn báo ảo được giữ lại cho chủ máy xem.
    kh._xu_ly(DEN, "on", f"{NGU} có người vào", _luc(0, 19, 5))
    chan = kh.tong_quan()[0]["kiem_ao"]["chan_gan_day"]
    assert len(chan) == 1 and "Hiện diện phòng ngủ" in chan[0]["nguon"]
    assert kh.goi == [], "báo ảo thì không bật"



def test_hoc_theo_so_do_chi_nguon_trong_so_do(kh, monkeypatch):
    """Chủ máy 26/09/2026: bật/tắt thiết bị "cơ sở là lấy theo sơ đồ kích hoạt". Cảm biến
    ngoài sơ đồ (radar bếp báo trước lúc bật) không được thành nguồn."""
    for n in range(29, 0, -1):
        t = _luc(n, 19, n % 20)
        _sk(BEP, "off", t - 700)
        _sk(BEP, "on", t - 60)
    _nep_30_ngay()
    kh.dat_thiet_bi(DEN, bat=True)
    assert f"{BEP} có người vào" in kh.hoc(DEN)["on"]["nguon"], "tự dò thì bếp lọt vào"
    monkeypatch.setattr(kh, "_so_do", lambda tb: ({NGU}, {LUX}))
    ra = kh.hoc(DEN)
    assert ra["co_so"] == "so_do" and ra["dac_trung_so"] == [LUX]
    assert all(n.startswith(NGU) for n in ra["on"]["nguon"]), ra["on"]["nguon"]


def test_kiem_bao_ao_theo_cau_hinh_chu_may(kh):
    """"Check thiết bị gì trong bao lâu (có thể chỉnh sửa)": chỉ bằng chứng đã chọn, đúng số giờ."""
    luc = _luc(0, 19, 5)
    _sk("switch.phong_hoc_l1", "on", luc - 3600)
    assert kh.nha_co_nguoi({NGU}, luc, DEN), "mặc định: công tắc bấm tay là bằng chứng"
    kh.dat_thiet_bi(DEN, kiem_ao={"gio": 2, "bang_chung": [CUA]})
    assert not kh.nha_co_nguoi({NGU}, luc, DEN), "bỏ công tắc khỏi bằng chứng thì không tính"
    _sk(CUA, "on", luc - 3 * 3600)
    assert not kh.nha_co_nguoi({NGU}, luc, DEN), "mở cửa 3 giờ trước, nhìn lại 2 giờ"
    _sk(CUA, "on", luc - 1800)
    assert kh.nha_co_nguoi({NGU}, luc, DEN)
    for sai in ({"gio": 0, "bang_chung": [CUA]}, {"gio": 3, "bang_chung": []},
                {"gio": 3, "bang_chung": ["khong_phai_ma"]}):
        with pytest.raises(ValueError):
            kh.dat_thiet_bi(DEN, kiem_ao=sai)


def test_tat_khi_vang(kh, monkeypatch):
    """Cảm biến chọn cùng báo vắng liền N phút mà đèn còn bật thì tắt; có người lại thì huỷ;
    người vừa tự bật thì chưa tắt."""
    tt = {x["entity_id"]: dict(x) for x in TT}
    tt[DEN]["state"] = "on"
    monkeypatch.setattr(kh, "_trang_thai_ha", lambda: list(tt.values()))
    from services import ha_client
    monkeypatch.setattr(ha_client, "get_state", lambda e: tt.get(e))
    hen: list = []

    class HenGia:
        def __init__(self, giay, ham, args=()):
            self.giay, self.ham, self.args, self.huy = giay, ham, args, False
            hen.append(self)

        def start(self):
            pass

        def cancel(self):
            self.huy = True
    monkeypatch.setattr(kh.threading, "Timer", HenGia)
    with pytest.raises(ValueError):
        kh.dat_thiet_bi(DEN, bat=True, tat_khi_vang={"bat": True, "cam_bien": [], "phut": 10})
    kh.dat_thiet_bi(DEN, bat=True, tat_khi_vang={"bat": True, "cam_bien": [NGU], "phut": 10})
    tt[NGU]["state"] = "off"
    kh._theo_vang(NGU, "off", kh.ds_thiet_bi())
    assert len(hen) == 1 and hen[0].giay == 600
    kh._theo_vang(NGU, "on", kh.ds_thiet_bi())
    assert hen[0].huy, "có người lại thì huỷ hẹn"
    kh._theo_vang(NGU, "off", kh.ds_thiet_bi())
    _sk(DEN, "on", time.time() - 60)                           # người vừa tự bật
    hen[-1].ham(*hen[-1].args)
    assert kh.goi == [], "người vừa chạm thì chưa tắt"
    assert hen[-1].giay == kh.HEN_LAI and not hen[-1].huy, "chặn tạm thì hẹn kiểm lại, không bỏ hẳn"
    from services import lich_su_nha as ls
    with ls._khoa_db:
        ls._db().execute("DELETE FROM su_kien WHERE thiet_bi=?", (DEN,)); ls._db().commit()
    hen[-1].ham(*hen[-1].args)
    assert kh.goi == [("switch", "turn_off", {"entity_id": DEN})]
    assert kh.tong_quan()[0]["tat_khi_vang"]["cam_bien"][0]["ma"] == NGU


def test_goi_y_them_cam_bien_ngoai_so_do(kh, monkeypatch):
    """Sơ đồ thiếu nguồn mạnh (đèn trần thiếu cửa chính) thì GỢI Ý, không tự thêm."""
    for n in range(29, 0, -1):
        t = _luc(n, 19, n % 20)
        _sk(CUA, "off", t - 700)
        _sk(CUA, "on", t - 60)
    _nep_30_ngay()
    monkeypatch.setattr(kh, "_so_do", lambda tb: ({NGU}, {LUX}))
    kh.dat_thiet_bi(DEN, bat=True)
    ra = kh.hoc(DEN)
    assert [x["ma"] for x in ra["goi_y_them"]] == [CUA]
    assert all(n.startswith(NGU) for n in ra["on"]["nguon"]), "gợi ý không tự vào nguồn"
    assert kh.tong_quan()[0]["goi_y_them"][0]["ten"] == "Cửa chính"


def test_goi_y_bo_cam_bien_nguoi_di_ngang(kh, monkeypatch):
    """Ban công báo có người hàng trăm lần mà hiếm khi kèm lần bật đèn phòng ngủ (đo: 6%) —
    không gợi ý, dù nó hay "đứng trước" lúc bật (chủ máy đã hỏi nó để làm gì)."""
    for n in range(29, 0, -1):
        t = _luc(n, 19, n % 20)
        _sk(CUA, "off", t - 700)
        _sk(CUA, "on", t - 60)                         # đi ngang TRƯỚC lúc bật…
        for h in range(8, 18):                         # …và đi ngang cả ngày, không ai bật
            s = _luc(n, h, 30)
            _sk(CUA, "off", s - 600)
            _sk(CUA, "on", s)
    _nep_30_ngay()
    monkeypatch.setattr(kh, "_so_do", lambda tb: ({NGU}, {LUX}))
    kh.dat_thiet_bi(DEN, bat=True)
    assert kh.hoc(DEN)["goi_y_them"] == []


def test_tich_thi_mac_dinh_tat_khi_vang_theo_so_do(kh, monkeypatch):
    """Chủ máy 26/09/2026: phần tắt "chính là ngược với bật" — tích thiết bị là có luôn tắt khi
    vắng, cảm biến lấy từ sơ đồ; thiết bị không có cảm biến hiện diện thì không bật."""
    monkeypatch.setattr(kh, "_so_do", lambda tb: ({NGU, CUA}, {LUX}))
    cd = kh.dat_thiet_bi(DEN, bat=True)
    assert cd["tat_khi_vang"] == {"bat": True, "cam_bien": [NGU], "phut": kh.MAC_DINH_VANG_PHUT}
    kh.dat_thiet_bi(DEN, tat_khi_vang={"bat": False, "cam_bien": [NGU], "phut": 20})
    assert kh.dat_thiet_bi(DEN, bat=True)["tat_khi_vang"]["phut"] == 20, "không đè cài đặt của chủ máy"
    monkeypatch.setattr(kh, "_so_do", lambda tb: (set(), set()))
    assert kh.dat_thiet_bi("switch.khac", bat=True)["tat_khi_vang"]["bat"] is False


def test_bang_vang_roi_quay_lai(kh, monkeypatch):
    _nep_30_ngay()                                     # mỗi tối vắng 600 s rồi vào lại
    monkeypatch.setattr(kh, "_so_do", lambda tb: ({NGU}, {LUX}))
    kh.dat_thiet_bi(DEN, bat=True)
    bang = kh.hoc(DEN)["vang_quay_lai"][NGU]
    assert bang["5"] > 0 and bang["60"] < bang["5"]


def _thu(ngay_trong_tuan: int, gio: int, phut: int = 0) -> float:
    """Mốc gần nhất trong quá khứ rơi đúng thứ (0 = thứ 2) và giờ đó."""
    d = datetime.now(_TZ).replace(hour=gio, minute=phut, second=0, microsecond=0)
    while d.weekday() != ngay_trong_tuan:
        d -= timedelta(days=1)
    return d.timestamp()


def test_lich_qua_nua_dem_thuoc_ngay_bat_dau(kh):
    """Chủ máy 26/09/2026: "Cả nhà thường đi ngủ lúc 21h45". «Ngủ, thứ 6» vẫn đang diễn ra
    lúc 2 giờ sáng thứ 7; 2 giờ sáng thứ 6 là giấc của thứ 5 — không thuộc mục này."""
    from services import lich_sinh_hoat as lsh
    lsh.dat([{"ma": "ngu", "ten": "Ngủ", "loai": "ngu", "tu": "21:45", "den": "06:00", "thu": [4]}])
    m = lsh.tim("ngu")
    assert lsh.trong(m, _thu(4, 22)) and lsh.trong(m, _thu(5, 2))
    assert not lsh.trong(m, _thu(4, 2)) and not lsh.trong(m, _thu(5, 22)) and not lsh.trong(m, _thu(4, 21, 30))
    for sai in ({"ten": "Ngủ", "tu": "21:45", "den": "06:00", "thu": []},
                {"ten": "Ngủ", "tu": "21:45", "den": "06:00", "thu": [7]},
                {"ten": "Ngủ", "loai": "ngu_trua", "tu": "12:00", "den": "13:00", "thu": [0]},
                {"ten": "", "tu": "21:45", "den": "06:00", "thu": [0]}):
        with pytest.raises(ValueError):
            lsh.dat([sai])
    with pytest.raises(ValueError):
        lsh.dat([{"ma": "a", "ten": "A", "tu": "01:00", "den": "02:00", "thu": [0]}] * 2)
    assert lsh.tim("ngu"), "lịch sai thì không ghi đè lịch cũ"
    ra = lsh.dat([{"ten": "Ăn tối", "tu": "19:00", "den": "19:45", "thu": [1]},
                  {"ten": "Ăn tối", "tu": "19:45", "den": "20:30", "thu": [0]}, lsh.tim("ngu")])
    assert [m["ma"] for m in ra] == ["an_toi", "an_toi_2", "ngu"]
    assert [m["ma"] for m in lsh.dat(ra[1:])] == ["an_toi_2", "ngu"], "xoá mục trên không đổi mã mục dưới"


def test_khung_theo_lich_ngu_thi_khong_tat_khi_vang(kh, monkeypatch):
    """Chủ máy 26/09/2026: ngủ mà "đèn còn bật tức là còn sử dụng thì không được tắt dù là
    cảm biến trống". Khung «Ngủ» của đèn ĐI THEO lịch: sửa giờ ngủ ở lịch là mọi thiết bị
    theo — không phải sửa từng khung."""
    from services import lich_sinh_hoat as lsh
    now = datetime.now(_TZ)
    gio = lambda d: d.strftime("%H:%M")  # noqa: E731
    lsh.dat([{"ma": "ngu", "ten": "Ngủ", "loai": "ngu", "tu": gio(now - timedelta(hours=1)),
              "den": gio(now + timedelta(hours=1)), "thu": list(range(7))}])
    tt = {x["entity_id"]: dict(x) for x in TT}
    tt[DEN]["state"] = "on"
    tt[NGU]["state"] = "off"
    monkeypatch.setattr(kh, "_trang_thai_ha", lambda: list(tt.values()))
    from services import ha_client
    monkeypatch.setattr(ha_client, "get_state", lambda e: tt.get(e))
    with pytest.raises(ValueError):
        kh.dat_thiet_bi(DEN, ngoai_le=[{"hanh_dong": "off", "lich": "khong_co"}])
    kh.dat_thiet_bi(DEN, bat=True, tat_khi_vang={"bat": True, "cam_bien": [NGU], "phut": 3},
                    ngoai_le=[{"hanh_dong": "off", "lich": "ngu", "cach": "khong"}])
    kh._tat_vi_vang(DEN)
    assert kh.goi == [], "đang giờ ngủ: đèn còn bật là còn dùng"
    lsh.dat([{"ma": "ngu", "ten": "Ngủ", "loai": "ngu", "tu": gio(now + timedelta(hours=2)),
              "den": gio(now + timedelta(hours=3)), "thu": list(range(7))}])
    kh._tat_vi_vang(DEN)
    assert kh.goi == [("switch", "turn_off", {"entity_id": DEN})], "đổi giờ ngủ ở lịch là khung theo"


def test_khung_gio_co_thu(kh):
    """Khung giờ thường chọn được thứ: «Ăn tối muộn» chỉ thứ 2 và thứ 7."""
    kh.dat_thiet_bi(DEN, ngoai_le=[{"hanh_dong": "on", "tu": "19:30", "den": "20:30", "thu": [0, 5],
                                    "ten": "Ăn tối muộn"}])
    x = kh._nap()["thiet_bi"][DEN]["ngoai_le"][0]
    assert kh._khung_dang(x, _thu(0, 19, 45)) and kh._khung_dang(x, _thu(5, 20))
    assert not kh._khung_dang(x, _thu(1, 19, 45))


def test_lich_la_dac_trung_cua_cay(kh):
    """Giờ thôi thì cây không phân biệt được thứ 2 ăn tối 19:45 với thứ 3 ăn 19:00 —
    mục lịch là đặc trưng, và luật đọc ra bằng tên mục."""
    from services import lich_sinh_hoat as lsh
    lsh.dat([{"ma": "an_muon", "ten": "Ăn tối muộn", "loai": "an", "tu": "19:30", "den": "20:30", "thu": [0, 5]}])
    x = kh._dac_trung(_thu(0, 19, 45), "a", ["a"], {})
    assert x["lịch:an_muon"] == 1.0
    assert kh._dac_trung(_thu(1, 19, 45), "a", ["a"], {})["lịch:an_muon"] == 0.0
    assert kh._dieu_kien_doc("lịch:an_muon", False, 0.5, {}) == "đang giờ Ăn tối muộn"
    assert kh._dieu_kien_doc("lịch:an_muon", True, 0.5, {}) == "ngoài giờ Ăn tối muộn"


def test_bot_lam_danh_dau_ca_thuc_the_guong(kh, monkeypatch):
    """Đo 26/09/2026 19:45: bot bật switch.phong_ngu_l1 (do_ai=1) mà light.phong_ngu_l1 — cùng
    bóng đèn qua switch_as_x — ghi do_ai=0 → "người vừa bật" chặn tắt khi vắng."""
    from services import ha_client, lich_su_nha as ls
    guong = {"switch.phong_ngu_l1": "light.phong_ngu_l1", "light.phong_ngu_l1": "switch.phong_ngu_l1"}
    monkeypatch.setattr(ha_client, "thuc_the_guong", lambda e: guong.get(e))
    kh._lam("switch.phong_ngu_l1", "on", tu_lam=True)
    assert ls.la_bot_tu_lam("light.phong_ngu_l1") and ls.la_bot_tu_lam("switch.phong_ngu_l1")
    assert not ls.la_bot_tu_lam("switch.phong_ngu_l2"), "kênh khác cùng công tắc không phải gương"


def test_so_dang_ky_ra_cap_guong_switch_as_x():
    from services import ha_client
    ents = [{"entity_id": "light.phong_ngu_l1", "platform": "switch_as_x", "device_id": "d",
             "options": {"switch_as_x": {"entity_id": "switch.phong_ngu_l1", "invert": False}}},
            {"entity_id": "switch.phong_ngu_l1", "platform": "mqtt", "device_id": "d", "options": {}},
            {"entity_id": "switch.phong_ngu_l2", "platform": "mqtt", "device_id": "d", "options": {}}]
    g = ha_client._chi_muc_registry([], ents, [{"id": "d", "identifiers": [["mqtt", "x"]]}])["entity_mirror"]
    assert g == {"light.phong_ngu_l1": "switch.phong_ngu_l1", "switch.phong_ngu_l1": "light.phong_ngu_l1"}


def test_tu_lam_tra_loi_dung_sai(kh):
    """Chủ máy 26/09/2026: tin "em đã bật" phải cho chọn đúng / sai. Sai thì làm ngược lại
    ngay; với việc ĐÃ tự làm chỉ nhận đúng hai chữ — "không" nhắn cho việc khác không được
    tắt nhầm đèn."""
    from services import du_doan_nha as dd
    id1 = dd.ghi_nhan(f"{DEN}#on", "on", 0.9, {}, "tu_lam")
    assert kh.tra_loi("không") is None and kh.tra_loi("ok") is None
    assert "tắt lại" in kh.tra_loi("Sai rồi")
    assert kh.goi == [("switch", "turn_off", {"entity_id": DEN})]
    assert dd._db().execute("SELECT ket_qua FROM du_doan WHERE id=?", (id1,)).fetchone()[0] == "sai"
    id2 = dd.ghi_nhan(f"{DEN}#on", "on", 0.9, {}, "tu_lam")
    assert "đúng" in kh.tra_loi(f"đúng {id2}")
    assert dd._db().execute("SELECT ket_qua FROM du_doan WHERE id=?", (id2,)).fetchone()[0] == "dung"
    assert len(kh.goi) == 1, "đúng thì không làm gì thêm"
