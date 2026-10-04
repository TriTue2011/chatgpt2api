"""Luật ANH ĐẶT (29/09/2026): KHI … NẾU … THÌ bật/tắt — quạt phòng khách, đèn cửa sổ, đèn tủ lạnh.

Đo 30 ngày thật: bot không học ra được — automation HA cũ bật quạt bằng nút hồng ngoại mà không
đổi trạng thái quạt; đèn cửa sổ / tủ lạnh chỉ 6–7 lần bật. Ngưỡng nhiệt của quạt bot tự rút từ
lịch sử quạt đang bật theo nhiệt độ (60 ngày: 29–33 °C, quạt bật 50–83% thời gian có người).
"""
from __future__ import annotations

import threading
from unittest import mock

import pytest

from test.test_kich_hoat_nha import TT, _sk, kh  # noqa: F401 — fixture dùng chung

QUAT = "fan.phong_khach"
PK = "binary_sensor.hien_dien_phong_khach_presence"
NHIET = "sensor.nhiet_am_phong_khach_temperature"
CUA = "binary_sensor.cam_bien_cua_chinh_contact"
NGU = "binary_sensor.hien_dien_phong_ngu_occupancy"
LUAT_QUAT = [
    {"hanh_dong": "on", "khi": [f"{PK} có người vào"],
     "neu": [{"loai": "muc_hay_bat", "cam_bien": NHIET, "co_mat": PK}]},
    {"hanh_dong": "on", "khi": [f"{CUA} có người vào"],
     "neu": [{"loai": "nha_trong", "tru": [CUA]}, {"loai": "muc_hay_bat", "cam_bien": NHIET, "co_mat": PK}]},
]


def _nhiet(o_5p: int, v: float) -> None:
    from services import lich_su_nha as ls
    with ls._khoa_db:
        ls._db().execute("INSERT INTO so_do (o_5p, thiet_bi, truong, nho, lon, tb, n) VALUES (?,?,?,?,?,?,1)",
                         (o_5p, NHIET, "state", v, v, v))
        ls._db().commit()


def test_kiem_dau_vao(kh):
    for sai in ([{"hanh_dong": "bat", "khi": [f"{PK} vắng"]}],
                [{"hanh_dong": "on", "khi": ["sensor.x có người vào"]}],
                [{"hanh_dong": "on", "khi": [f"{PK} vắng"], "neu": [{"loai": "doan_bua"}]}],
                [{"hanh_dong": "on", "khi": [f"{PK} vắng"],
                  "neu": [{"loai": "muc_hay_bat", "cam_bien": PK, "co_mat": PK}]}]):
        with pytest.raises(ValueError):
            kh._kiem_luat_chu(sai)
    assert kh._kiem_luat_chu(LUAT_QUAT)[1]["neu"][0] == {"loai": "nha_trong", "tru": [CUA]}


def test_hoc_muc_hay_bat_bo_quang_bot_bat(kh):
    import sqlite3
    from services import lich_su_nha as ls

    o0 = 10_000
    _sk(PK, "on", o0 * 300 - 10)
    # 20 ô ở 31 °C: quạt người bật; 20 ô ở 25 °C: quạt tắt; 20 ô ở 31 °C sau đó: BOT bật.
    _sk(QUAT, "on", o0 * 300)
    for i in range(20):
        _nhiet(o0 + i, 31.2)
    _sk(QUAT, "off", (o0 + 20) * 300)
    for i in range(20, 40):
        _nhiet(o0 + i, 25.4)
    _sk(QUAT, "on", (o0 + 40) * 300, do_ai=1)
    for i in range(40, 60):
        _nhiet(o0 + i, 31.7)
    with sqlite3.connect(f"file:{ls._DB_PATH}?mode=ro", uri=True) as ro:
        bang = kh._hoc_hay_bat(ro, QUAT, NHIET, PK, o0 * 300 - 5, (o0 + 60) * 300)
    assert bang == {"31": [20, 20], "25": [20, 0]}          # 20 ô bot bật không tính


def test_muc_hay_bat_quyet_theo_ti_le_va_du_mau(kh):
    kh._nap()["mo_hinh"][QUAT] = {"hay_bat": {NHIET: {"31": [20, 17], "25": [20, 2], "28": [3, 3]}}}
    d = {"loai": "muc_hay_bat", "cam_bien": NHIET, "co_mat": PK, "nguong": 0.5}
    with mock.patch.object(kh, "_trang_thai_mot", return_value="31.4"):
        assert kh._muc_hay_bat(QUAT, d)[0] is True
    with mock.patch.object(kh, "_trang_thai_mot", return_value="25.0"):
        assert kh._muc_hay_bat(QUAT, d)[0] is False
    with mock.patch.object(kh, "_trang_thai_mot", return_value="28.2"):     # 3 mẫu → gộp 27–29: vẫn 3
        ok, ly_do = kh._muc_hay_bat(QUAT, d)
    assert ok is False and "chưa đủ dữ liệu" in ly_do


def test_nha_trong(kh):
    assert kh._nha_trong({"tru": [CUA]})[0] is True
    co_nguoi = [dict(x, state="on") if x["entity_id"] == NGU else x for x in TT]
    with mock.patch.object(kh, "_trang_thai_ha", lambda: co_nguoi):
        ok, ly_do = kh._nha_trong({"tru": [CUA]})
    assert ok is False and NGU in ly_do


def test_luat_anh_dat_thang_luat_hoc_cung_huong(kh):
    kh._nap()["thiet_bi"][QUAT] = {"bat": True, "luat_chu": kh._kiem_luat_chu(LUAT_QUAT)}
    kh._nap()["mo_hinh"][QUAT] = {"on": {"nguon": [f"{PK} có người vào"]}, "off": {"nguon": [f"{PK} vắng"]}}
    chay = []
    with mock.patch.object(kh, "_xu_ly_chu", lambda tb, l, n, luc: chay.append(("chu", tb, n))), \
            mock.patch.object(kh, "_xu_ly", lambda tb, hd, n, luc: chay.append(("hoc", tb, hd))), \
            mock.patch.object(threading, "Thread", lambda target, args, **k: mock.Mock(start=lambda: target(*args))):
        kh._phat(f"{PK} có người vào", 1.0)
        kh._phat(f"{PK} vắng", 1.0)
    assert chay == [("chu", QUAT, f"{PK} có người vào"), ("hoc", QUAT, "off")]


def test_xu_ly_chu_lam_khi_du_dieu_kien_nguoi_vua_cham_thi_thoi(kh):
    l = kh._kiem_luat_chu(LUAT_QUAT)[0]
    kh._nap()["thiet_bi"][QUAT] = {"bat": True, "luat_chu": [l]}
    kh._nap()["mo_hinh"][QUAT] = {"hay_bat": {NHIET: {"31": [20, 17]}}}
    tt = {QUAT: "off", NHIET: "31.2", PK: "on"}
    with mock.patch.object(kh, "_trang_thai_mot", lambda m: tt.get(m, "")), \
            mock.patch("services.thong_bao.gui", lambda *a, **k: None):
        with mock.patch.object(kh, "_nguoi_vua_cham", return_value=True):
            kh._xu_ly_chu(QUAT, l, f"{PK} có người vào", 1.0)
        assert kh.goi == []                                    # người vừa bật/tắt tay: bot im
        kh._xu_ly_chu(QUAT, l, f"{PK} có người vào", 1.0)
    assert kh.goi == [("fan", "turn_on", {"entity_id": QUAT})]


def test_im_lang_khong_nhan_viec_da_tu_lam_nhung_van_ghi_nhan(kh):
    """Đo 29/09/2026: quạt theo "phòng khách có người thật" ~22 lần/ngày mỗi chiều — ~44 tin/ngày."""
    l = kh._kiem_luat_chu(LUAT_QUAT)[0]
    kh._nap()["thiet_bi"][QUAT] = {"bat": True, "luat_chu": [l], "im_lang": True}
    kh._nap()["mo_hinh"][QUAT] = {"hay_bat": {NHIET: {"31": [20, 17]}}}
    tt = {QUAT: "off", NHIET: "31.2", PK: "on"}
    tin, ghi = [], []
    with mock.patch.object(kh, "_trang_thai_mot", lambda m: tt.get(m, "")), \
            mock.patch("services.thong_bao.gui", lambda *a, **k: tin.append(a)), \
            mock.patch("services.du_doan_nha.ghi_nhan", lambda *a, **k: ghi.append(a) or 1):
        kh._xu_ly_chu(QUAT, l, f"{PK} có người vào", 1.0)
    assert kh.goi == [("fan", "turn_on", {"entity_id": QUAT})] and tin == [] and len(ghi) == 1


def test_luat_hoc_chi_nhuong_o_NGUON_ma_luat_chu_va_luat_duyet_nghe(kh):
    """04/10/2026: đèn trần có luật duyệt «bật» chỉ nghe cửa chính → người vào phòng khách từ phòng ngủ (nguồn khác)
    bị nuốt hẳn: 72 lần/7 ngày không được xét. Nay luật bot học chỉ nhường ở ĐÚNG nguồn luật kia nghe."""
    NGUOI = "binary_sensor.phong_khach_person_occupancy"
    kh._nap()["thiet_bi"][QUAT] = {"bat": True, "luat_chu": kh._kiem_luat_chu(LUAT_QUAT)}
    kh._nap()["mo_hinh"][QUAT] = {"on": {"nguon": [f"{PK} có người vào", f"{NGUOI} có người vào"]}, "off": {"nguon": []}}
    chay = []
    duyet = [{"so": 14, "nen": "bat", "chieu": "bat", "khi": [f"{CUA} có người vào"], "neu": [], "lan": 1}]
    with mock.patch.object(kh, "_xu_ly_chu", lambda tb, l, n, luc: chay.append(("chu", n))), \
            mock.patch.object(kh, "_xu_ly", lambda tb, hd, n, luc: chay.append(("hoc", n))), \
            mock.patch.object(kh, "_xu_ly_duyet", lambda tb, khop, n, luc, **k: chay.append(("duyet", n))), \
            mock.patch.object(kh, "_cho_nguoi_vao", lambda f, *a: f(*a)), \
            mock.patch.object(kh, "_luat_duyet", lambda tb: duyet), \
            mock.patch.object(threading, "Thread", lambda target, args, **k: mock.Mock(start=lambda: target(*args))):
        kh._phat(f"{NGUOI} có người vào", 1.0)     # không luật chủ / duyệt nào nghe → luật học xét
        kh._phat(f"{PK} có người vào", 1.0)        # luật chủ nghe nguồn này → luật học nhường
        kh._phat(f"{CUA} có người vào", 1.0)       # luật chủ + luật duyệt nghe cửa → luật học nhường
    assert ("hoc", f"{NGUOI} có người vào") in chay
    assert ("hoc", f"{PK} có người vào") not in chay and ("chu", f"{PK} có người vào") in chay
    assert ("duyet", f"{CUA} có người vào") in chay and ("hoc", f"{CUA} có người vào") not in chay


def test_luat_hoc_ton_trong_luat_chan_da_duyet(kh):
    """Luật học không còn nhường cả hướng nên phải tự xét luật CHẶN đã duyệt (khong_lam khi bật, giu khi tắt)."""
    from services import ha_client
    chan = [{"so": 4, "nen": "khong_lam", "chieu": "bat", "khi": ["x"], "lan": 1,
             "neu": [{"ma": "binary_sensor.hien_dien_bep_presence", "la": "on"}]}]
    with mock.patch.object(kh, "_luat_duyet", lambda tb: chan):
        with mock.patch.object(ha_client, "get_states", lambda *a, **k: [
                {"entity_id": "binary_sensor.hien_dien_bep_presence", "state": "on", "last_changed": "2026-01-01T00:00:00+00:00"}]):
            assert (kh._chan_duyet(QUAT, "on", 2e9) or {}).get("so") == 4
            assert kh._chan_duyet(QUAT, "off", 2e9) is None, "khong_lam chỉ chặn hướng bật"
        with mock.patch.object(ha_client, "get_states", lambda *a, **k: [
                {"entity_id": "binary_sensor.hien_dien_bep_presence", "state": "off", "last_changed": "2026-01-01T00:00:00+00:00"}]):
            assert kh._chan_duyet(QUAT, "on", 2e9) is None
