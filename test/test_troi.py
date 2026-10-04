"""Trời tối / sáng (05/10/2026) — công thức mặt trời và điều kiện «troi» của luật duyệt. Không gọi HA."""
from __future__ import annotations

import datetime as dt
import os

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import luat_duyet as ld, troi  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=7))
HN = (21.03, 105.85)


def _ts(h, m, ngay=5, thang=10):
    return dt.datetime(2026, thang, ngay, h, m, tzinfo=TZ).timestamp()


def test_goc_mat_troi_ha_noi_khop_gio_moc_lan():
    """Hà Nội 05/10/2026: mọc ~05:53, lặn ~17:40 (lịch thiên văn) — sai số vài phút."""
    assert troi.goc_mat_troi(_ts(5, 45), *HN) < 0 < troi.goc_mat_troi(_ts(6, 5), *HN)
    assert troi.goc_mat_troi(_ts(17, 30), *HN) > 0 > troi.goc_mat_troi(_ts(17, 50), *HN)
    assert troi.goc_mat_troi(_ts(12, 0), *HN) > 60
    # mùa hè ngày dài hơn: 19:00 tháng 6 vẫn hơi tối hẳn chưa? lặn ~18:45
    assert troi.goc_mat_troi(_ts(18, 30, 21, 6), *HN) > 0 > troi.goc_mat_troi(_ts(19, 0, 21, 6), *HN)


def test_dieu_kien_troi_trong_luat(monkeypatch):
    from services import ha_client
    monkeypatch.setattr(ha_client, "get_state", lambda m: None)
    troi._reset_for_tests(HN)
    toi = ld.kiem_dieu_kien([{"ma": "troi", "la": "toi"}], _ts(21, 0), {})
    sang = ld.kiem_dieu_kien([{"ma": "troi", "la": "toi"}], _ts(10, 0), {})
    assert toi[0] is True and toi[1] == ["troi=trời tối✓"]
    assert sang[0] is False
    assert ld.kiem_dieu_kien([{"ma": "troi", "la": "sang"}], _ts(10, 0), {})[0] is True
    troi._reset_for_tests(None)
    assert ld.kiem_dieu_kien([{"ma": "troi", "la": "toi"}], _ts(21, 0), {})[0] is False, "không biết → không đúng"


def test_kiem_bien_nhan_troi_hop_le():
    assert ld._kiem_dk({"ma": "troi", "la": "toi"}, set(), set()) == {"ma": "troi", "la": "toi"}
    import pytest
    with pytest.raises(ValueError):
        ld._kiem_dk({"ma": "troi", "la": "chieu"}, set(), set())


def test_doc_toa_do_tu_api_config_dang_chuoi_json(monkeypatch):
    """05/10/2026: `_api_request` trả body là CHUỖI JSON — bản đầu chờ dict nên máy thật luôn «không biết trời»."""
    from services import ha_client
    monkeypatch.setattr(ha_client, "_api_request", lambda m, p, *a, **k: (200, '{"latitude": 21.03, "longitude": 105.85}'))
    monkeypatch.setattr(ha_client, "get_state", lambda m: None)
    with troi._khoa:
        troi._toa_do.update(luc=0.0, gt=None)
    assert troi._toa_do_nha() == (21.03, 105.85)
    assert troi.toi(_ts(21, 0)) is True and troi.toi(_ts(10, 0)) is False
    monkeypatch.setattr(ha_client, "_api_request", lambda m, p, *a, **k: (0, "HA chưa cấu hình url/token"))
    with troi._khoa:
        troi._toa_do.update(luc=0.0, gt=None)
    assert troi.toi(_ts(21, 0)) is None
    monkeypatch.setattr(ha_client, "_api_request", lambda m, p, *a, **k: (200, '{"latitude": 21.03, "longitude": 105.85}'))
    with troi._khoa:
        troi._toa_do["luc"] -= 301            # lỗi chỉ được nhớ 5 phút
    assert troi.toi(_ts(21, 0)) is True, "HA có lại thì hỏi lại toạ độ"
