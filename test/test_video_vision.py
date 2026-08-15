"""Vision cục bộ cho phụ đề: chọn cảnh, đường lui và không làm đứt SRT."""

from __future__ import annotations

import pytest

from services import video_vision as vv


@pytest.mark.pure
def test_moi_canh_chi_lay_toi_da_hai_khung():
    canh = [(0.0, 9.0), (9.0, 12.0)]
    assert vv.chon_moc_khung(canh, moi_canh=1) == [4.5, 10.5]
    assert vv.chon_moc_khung(canh, moi_canh=2) == [3.0, 6.0, 10.0, 11.0]


@pytest.mark.pure
def test_nhieu_canh_thi_lay_mau_deu_trong_gioi_han():
    canh = [(float(i), float(i + 1)) for i in range(10)]
    moc = vv.chon_moc_khung(canh, moi_canh=1, toi_da_canh=3)
    assert moc == [0.5, 4.5, 9.5]


def test_qwen_loi_thi_tra_canh_bao_thay_vi_nem_ra_ngoai(monkeypatch):
    monkeypatch.setattr(vv, "dung_duoc", lambda: True)
    monkeypatch.setattr(vv, "tach_canh", lambda _p: [(0.0, 4.0)])
    monkeypatch.setattr(vv, "trich_khung", lambda _p, _t: b"jpeg")
    monkeypatch.setattr(vv, "phan_tich_khung", lambda *_a, **_k:
                        (_ for _ in ()).throw(vv.LoiVision("GPU hết VRAM")))

    kq = vv.phan_tich_video("/tmp/phim.mp4")

    assert kq.engine == "fallback"
    assert "Qwen3-VL" in kq.canh_bao
    assert kq.ranh_canh == []


def test_frigate_chiem_vram_thi_bo_vision_nhung_khong_ngat_cau_dao(monkeypatch):
    monkeypatch.setattr(vv, "dung_duoc", lambda: True)
    monkeypatch.setattr(vv, "co_vram_an_toan", lambda: False)

    kq = vv.phan_tich_video("/tmp/phim.mp4")

    assert kq.engine == "fallback"
    assert "Frigate" in kq.canh_bao


def test_tep_audio_khong_goi_qwen_va_khong_lam_dong_cau_dao(monkeypatch):
    monkeypatch.setattr(vv, "dung_duoc", lambda: True)
    vv._nghi_toi = 0.0

    kq = vv.phan_tich_video("/tmp/podcast.mp3")

    assert kq.engine == "off"
    assert vv._nghi_toi == 0.0


def test_gpu_dang_ban_thi_bo_vision_nhung_khong_phat_qwen_nghi_nam_phut(monkeypatch):
    from contextlib import contextmanager
    from services import gpu_queue

    monkeypatch.setattr(vv, "dung_duoc", lambda: True)
    monkeypatch.setattr(vv, "co_vram_an_toan", lambda: True)
    monkeypatch.setattr(vv, "tach_canh", lambda _p: [(0.0, 4.0)])
    monkeypatch.setattr(vv, "trich_khung", lambda _p, _t: b"jpeg")

    @contextmanager
    def _ban(_nguon):
        raise gpu_queue.QuaTaiGpu("đang chạy Whisper")
        yield

    monkeypatch.setattr(gpu_queue, "giu", _ban)
    vv._nghi_toi = 0.0
    kq = vv.phan_tich_video("/tmp/phim.mp4")

    assert kq.engine == "fallback"
    assert vv._nghi_toi == 0.0


def test_qwen_thanh_cong_tra_ranh_canh_de_khong_gop_loi_thoai_qua_canh(monkeypatch):
    monkeypatch.setattr(vv, "dung_duoc", lambda: True)
    monkeypatch.setattr(vv, "tach_canh", lambda _p: [(0.0, 2.0), (2.0, 5.0)])
    monkeypatch.setattr(vv, "trich_khung", lambda _p, _t: b"jpeg")
    monkeypatch.setattr(vv, "phan_tich_khung", lambda *_a, **_k: "bếp, một người")

    kq = vv.phan_tich_video("/tmp/phim.mp4")

    assert kq.engine == "gpu"
    assert kq.ranh_canh == [2.0]
    assert kq.mo_ta == ["bếp, một người", "bếp, một người"]
    assert kq.so_canh == 2


def test_vision_giu_moc_canh_va_dua_ca_loi_thoai_cua_canh_vao_qwen(monkeypatch):
    monkeypatch.setattr(vv, "dung_duoc", lambda: True)
    monkeypatch.setattr(vv, "co_vram_an_toan", lambda: True)
    monkeypatch.setattr(vv, "tach_canh", lambda _p: [(0.0, 2.0), (2.0, 5.0)])
    monkeypatch.setattr(vv, "trich_khung", lambda _p, _t: b"jpeg")
    da_nhan = []

    def _qwen(_jpeg, _moc, loi_thoai):
        da_nhan.append(loi_thoai)
        return "mô tả cảnh"

    monkeypatch.setattr(vv, "phan_tich_khung", _qwen)
    loi = [
        type("D", (), {"bat_dau": 0.1, "ket_thuc": 0.6, "chu": "câu đầu"})(),
        type("D", (), {"bat_dau": 1.1, "ket_thuc": 1.7, "chu": "câu sau"})(),
        type("D", (), {"bat_dau": 2.1, "ket_thuc": 2.5, "chu": "cảnh hai"})(),
    ]

    kq = vv.phan_tich_video("/tmp/phim.mp4", loi)

    assert kq.ngu_canh_canh == [
        {"bat_dau": 0.0, "ket_thuc": 2.0, "mo_ta": "mô tả cảnh"},
        {"bat_dau": 2.0, "ket_thuc": 5.0, "mo_ta": "mô tả cảnh"},
    ]
    assert da_nhan == ["câu đầu câu sau", "cảnh hai"]
