"""API tab Chi tiêu — mỗi tài khoản chỉ thấy sổ của mình, kể cả admin; admin chỉ thấy TÊN sổ để gán Zalo."""
from __future__ import annotations

import os
from unittest import mock

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api.chi_tieu as ac  # noqa: E402
from services.chi_tieu import kho  # noqa: E402

DANH = {"admin": {"id": "admin", "name": "Chủ", "role": "admin"},
        "vo": {"id": "k-vo", "name": "Vợ", "role": "user"}}


def _id(auth):
    return DANH[str(auth).split()[-1]]


def _admin(auth):
    d = _id(auth)
    if d["role"] != "admin":
        from fastapi import HTTPException
        raise HTTPException(403, "cần quản trị")
    return d


@pytest.fixture
def c(tmp_path):
    kho._reset_for_tests(tmp_path / "ct.db")
    app = FastAPI()
    app.include_router(ac.create_router())
    with mock.patch.object(ac, "require_identity", side_effect=_id), mock.patch.object(ac, "require_admin",
                                                                                         side_effect=_admin):
        yield TestClient(app)


def H(ai):
    return {"Authorization": f"Bearer {ai}"}


def test_moi_tai_khoan_mot_so_rieng_ke_ca_admin(c):
    a = c.get("/api/chi-tieu", headers=H("admin")).json()
    v = c.get("/api/chi-tieu", headers=H("vo")).json()
    assert a["ok"] and v["ok"] and a["so"]["id"] != v["so"]["id"]
    hu = v["hu"][0]["id"]
    assert c.post("/api/chi-tieu/chi", json={"hu_id": hu, "so_tien": 120000, "ghi_chu": "chợ"}, headers=H("vo")).json()["da_ghi"]
    assert c.get("/api/chi-tieu", headers=H("admin")).json()["ngan_sach"]["tong_da_chi"] == 0
    id_vo = c.get("/api/chi-tieu/lich-su", headers=H("vo")).json()["giao_dich"][0]["id"]
    assert not c.delete(f"/api/chi-tieu/chi/{id_vo}", headers=H("admin")).json()["ok"], "admin không xoá được chi của vợ"
    assert not c.post(f"/api/chi-tieu/chi/{id_vo}", json={"so_tien": 1}, headers=H("admin")).json()["ok"]
    assert c.get("/api/chi-tieu/lich-su", headers=H("vo")).json()["so_luong"] == 1


def test_quan_tri_chi_thay_ten_so_va_gan_kenh(c):
    c.get("/api/chi-tieu", headers=H("vo"))
    with mock.patch("services.channel_contacts.list_directory", return_value=[
            {"kind": "user", "thread_id": "123", "name": "Vợ Zalo", "bot_id": "acc1", "bot_label": "+84"}]):
        q = c.get("/api/chi-tieu/quan-tri", headers=H("admin")).json()
    assert q["ok"] and q["nguoi"][0]["kenh_user"] in ("zalop_123", "zalo_123", "123")
    so_vo = next(s for s in q["so"] if s["chu"] == "k-vo")
    assert set(so_vo) == {"id", "ten", "chu", "tao_luc", "lien_ket"}, "không lộ lương / số tiền"
    assert c.get("/api/chi-tieu/quan-tri", headers=H("vo")).status_code == 403
    with mock.patch("services.agent.reminders._send") as gui:
        r = c.post("/api/chi-tieu/quan-tri/gan", json={"kenh_user": "zalop_123", "so_id": so_vo["id"], "ten": "Vợ Zalo",
                                                        "bot_id": "acc1"}, headers=H("admin")).json()
    assert r["da_gan"] and r["da_bao"] and "Sổ của Vợ" in gui.call_args[0][2]
    assert kho.so_cua_kenh("zalop_123") == so_vo["id"]
    assert c.get("/api/chi-tieu", headers=H("vo")).json()["lien_ket"][0]["kenh_user"] == "zalop_123"


def test_sua_cau_hinh_hu_va_ky(c):
    v = c.get("/api/chi-tieu", headers=H("vo")).json()
    assert c.post("/api/chi-tieu/cau-hinh", json={"luong": 20_000_000, "ngay_bat_dau": 5}, headers=H("vo")).json()["ok"]
    assert not c.post("/api/chi-tieu/cau-hinh", json={"ngay_bat_dau": 30}, headers=H("vo")).json()["ok"]
    r = c.post("/api/chi-tieu/hu", json={"ten": "Thú cưng", "ty_le": 0}, headers=H("vo")).json()
    assert r["ok"]
    assert c.post(f"/api/chi-tieu/hu/{r['id']}", json={"ten": "Mèo", "ty_le": 3}, headers=H("vo")).json()["ok"]
    assert c.delete(f"/api/chi-tieu/hu/{r['id']}", headers=H("vo")).json()["ok"]
    k = c.post("/api/chi-tieu/ky/thu-nhap", json={"mo_ta": "thưởng", "so_tien": 1_000_000}, headers=H("vo")).json()
    assert k["ok"] and c.post(f"/api/chi-tieu/ky/thu-nhap/{k['id']}", json={"so_tien": 2_000_000}, headers=H("vo")).json()["ok"]
    assert c.get("/api/chi-tieu", headers=H("vo")).json()["ngan_sach"]["thu_nhap_hieu_qua"] == 22_000_000
    assert c.delete(f"/api/chi-tieu/ky/thu-nhap/{k['id']}", headers=H("vo")).json()["ok"]
    assert not c.post("/api/chi-tieu/ky/bay", json={}, headers=H("vo")).json()["ok"]
    assert v["tong_ty_le"] == 100.0


def test_lien_ket_ma_va_cong_ty(c):
    m = c.post("/api/chi-tieu/lien-ket/ma", headers=H("vo")).json()
    assert m["ok"] and len(m["ma"]) == 6
    assert c.post("/api/chi-tieu/cong-ty", json={"loai": "tam_ung", "so_tien": 500000, "mo_ta": "đi HN"},
                  headers=H("vo")).json()["so_du"] == 500000
    g = c.post("/api/chi-tieu/cong-ty/giai-chi", headers=H("vo")).json()
    assert g["ok"] and c.get(f"/api/chi-tieu/giai-chi/{g['id']}", headers=H("vo")).json()["ok"]
    assert not c.get(f"/api/chi-tieu/giai-chi/{g['id']}", headers=H("admin")).json()["ok"]
    t = c.get("/api/chi-tieu/thong-ke?so_ky=3", headers=H("vo")).json()
    assert t["ok"] and len(t["ky"]) == 3
