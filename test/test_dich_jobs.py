"""Sổ việc tab Dịch phải không biến mất im lặng khi gateway khởi động lại."""

from __future__ import annotations


def test_tien_do_khong_ghi_so_moi_cau_nhung_trang_thai_thi_ghi_ngay():
    """Lồng tiếng phim dài báo tiến độ cả nghìn lượt; fsync từng lượt là phí."""
    from services import dich_jobs

    viec = {"trang_thai": "dang_chay", "luu_luc": 1000.0}
    assert dich_jobs.nen_luu_ngay(viec, {"buoc": "câu 1"}, luc=1000.5) is False
    assert dich_jobs.nen_luu_ngay(viec, {"buoc": "câu 9"}, luc=1002.5) is True
    # Trạng thái là thứ khôi phục sau restart cần — không được giãn nhịp.
    assert dich_jobs.nen_luu_ngay(
        viec, {"trang_thai": "xong"}, luc=1000.1) is True
    # Sổ cũ chưa có trường nhịp thì lần đầu phải ghi, không im lặng bỏ qua.
    assert dich_jobs.nen_luu_ngay({}, {"buoc": "câu 1"}, luc=1000.0) is True


def test_chi_xoa_thu_muc_ket_qua_uuid_hop_le(tmp_path):
    from services import dich_jobs

    hop_le = tmp_path / "abcdef123456"
    hop_le.mkdir()
    (hop_le / "video.mp4").write_bytes(b"video")
    ngoai_le = tmp_path / "khong-duoc-xoa"
    ngoai_le.mkdir()
    dich_jobs.xoa_ket_qua_da_luu({"ket_qua": {"tep": [
        {"url": "/images/docs/abcdef123456/video.mp4"},
        {"url": "/images/docs/../../khong-duoc-xoa/file"},
    ]}}, tmp_path)

    assert not hop_le.exists()
    assert ngoai_le.exists()


def test_don_ca_ket_qua_zalo_khong_co_job_nhung_khong_xoa_thu_muc_la(tmp_path):
    import os
    from services import dich_jobs

    cu = tmp_path / "123456abcdef"
    cu.mkdir()
    (cu / ".expire-24h").touch()
    moi = tmp_path / "abcdef123456"
    moi.mkdir()
    (moi / ".expire-24h").touch()
    thu_muc_la = tmp_path / "khong-phai-job"
    thu_muc_la.mkdir()
    os.utime(cu, (100.0, 100.0))
    os.utime(moi, (300.0, 300.0))

    assert dich_jobs.don_thu_muc_ket_qua(tmp_path, cu_hon=200.0) == 1
    assert not cu.exists()
    assert moi.exists()
    assert thu_muc_la.exists()


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
