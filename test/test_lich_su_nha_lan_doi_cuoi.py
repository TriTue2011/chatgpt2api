"""lan_doi_cuoi: lần đổi giá trị thật gần nhất, bỏ unavailable/unknown (dùng xét «thiết bị còn sống»)."""

from __future__ import annotations


def test_lan_doi_cuoi_bo_mat_ket_noi(tmp_path, monkeypatch):
    from services import lich_su_nha as l
    monkeypatch.setattr(l, "_DB_PATH", tmp_path / "ls.sqlite", raising=False)
    monkeypatch.setattr(l, "_conn", None, raising=False)
    db = l._db()
    for ts, tb, gt in [(10, "a", "on"), (20, "a", "off"), (30, "a", "unavailable"), (15, "b", "unknown")]:
        db.execute("INSERT INTO su_kien(ts, nguon, thiet_bi, truong, gia_tri, gio, thu) VALUES (?,?,?,?,?,0,0)",
                   (ts, "ha", tb, "state", gt))
    assert l.lan_doi_cuoi(["a", "b", "c"]) == {"a": 20.0}
    assert l.lan_doi_cuoi([]) == {}
