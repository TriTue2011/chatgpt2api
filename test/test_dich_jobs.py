"""Sổ việc tab Dịch phải không biến mất im lặng khi gateway khởi động lại."""

from __future__ import annotations

def test_viec_dang_chay_sau_restart_duoc_bao_loi_ro_rang(tmp_path):
    from services import dich_jobs

    duong = tmp_path / "dich-jobs.json"
    dich_jobs.luu_so_viec(duong, {
        "viec-test": {
            "trang_thai": "dang_chay", "luc": 100.0,
            "buoc": "đang nghe tiếng trong tệp…",
        },
    })

    viec = dich_jobs.khoi_phuc_sau_restart(dich_jobs.tai_so_viec(duong), luc=200.0)

    assert viec["viec-test"]["trang_thai"] == "loi"
    assert "khởi động lại" in viec["viec-test"]["loi"]
