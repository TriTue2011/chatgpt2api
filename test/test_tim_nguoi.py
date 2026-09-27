"""Tool tim_nguoi — «con trai đang ở đâu»: chụp mọi camera, nhận mặt, báo vị trí.

Chủ máy 27/09/2026: "ví dụ con trai đang ở đâu thì chụp ảnh tất cả các cam rồi nhận diện
khuôn mặt xác định vị trí để báo lại" — "đầu tiên khi báo cần báo rằng ở đâu có bao nhiêu
người cùng câu trả lời người cần hỏi có đó không" — "nếu không nhận ra người cần hỏi ở đâu
thì báo ở đâu có bao người".
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from unittest import mock

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from services import camera_nha, nhin_nha, so_mat_nha, yolo_nha  # noqa: E402
from services.config import config  # noqa: E402

pytestmark = pytest.mark.pure

NGUOI = [{"id": "p1", "ten": "Con trai Trí Anh"}, {"id": "p2", "ten": "Con gái Tuệ Nhị"},
         {"id": "p3", "ten": "Vợ tôi"}]
CAM = ["Cam cửa", "Cam phòng khách", "Cam bếp"]


def _mat(nguoi_id: str, ten: str, do_giong: float, loai: str = "quen") -> dict:
    return {"nguoi_id": nguoi_id, "ten": ten, "do_giong": do_giong, "loai": loai,
            "hop": [0, 0, 10, 10], "diem_do": 0.9, "nguoi_so": 0}


def _k(so_nguoi: int, *mat: dict) -> nhin_nha.KhungDaXem:
    return nhin_nha.KhungDaXem(20, 20, [yolo_nha.VatThe("person", 0.9, (0, 0, 5, 9))] * so_nguoi, list(mat))


@pytest.fixture
def goi(monkeypatch):
    from services.agent import capabilities as C

    tmp = tempfile.TemporaryDirectory()
    monkeypatch.setattr(type(config), "images_dir", mock.PropertyMock(return_value=Path(tmp.name)))
    monkeypatch.setattr(C, "gateway_base_url", lambda: "http://cong:5000")
    monkeypatch.setattr(camera_nha, "danh_sach", lambda **_k: [{"name": c} for c in CAM])
    # Ảnh mang số thứ tự camera ở điểm ảnh đầu — khung giả tra theo số đó (mỗi camera có thể
    # được nhìn nhiều lần, lần lượt theo danh sách, lần cuối lặp lại).
    monkeypatch.setattr(camera_nha, "khung_ben_bi",
                        lambda cam, luong="phu": np.full((20, 20, 3), CAM.index(cam), np.uint8))
    monkeypatch.setattr(nhin_nha, "co_mat", lambda: True)
    monkeypatch.setattr(nhin_nha, "ve_khung", lambda anh, k: b"anh-ve")
    monkeypatch.setattr(camera_nha, "_thu_nho", lambda tho, canh: tho)
    monkeypatch.setattr(so_mat_nha, "danh_sach_nguoi", lambda: NGUOI)
    monkeypatch.setattr(so_mat_nha, "tim_nguoi", lambda ten: next((n for n in NGUOI if n["ten"] == ten), None))
    monkeypatch.setattr(so_mat_nha, "su_kien_gan", lambda *a, **k: [])
    canh: dict[str, list] = {}

    def _phan_tich(anh):
        ds = canh[CAM[int(anh[0, 0, 0])]]
        return ds.pop(0) if len(ds) > 1 else ds[0]
    monkeypatch.setattr(nhin_nha, "phan_tich_khung", _phan_tich)

    def _goi(ten: str, khung: dict[str, list]):
        canh.clear()
        canh.update({c: list(khung.get(c, [_k(0)])) for c in CAM})
        return C.CAPABILITIES["tim_nguoi"].handler({"ten": ten}, {"is_admin": True})
    yield _goi
    tmp.cleanup()


def test_bao_moi_noi_bao_nhieu_nguoi_va_nguoi_can_tim_o_dau(goi):
    ra = goi("con trai", {
        "Cam phòng khách": [_k(2, _mat("p1", "Con trai Trí Anh", 66))],
        "Cam bếp": [_k(1, _mat("p3", "Vợ tôi", 70))],
    })
    t = ra["text"]
    assert "• **Cam phòng khách**: 2 người — **Con trai Trí Anh**; 1 người chưa nhận ra mặt" in t, t
    assert "• **Cam bếp**: 1 người — Vợ tôi" in t
    assert "Không có ai: Cam cửa." in t
    assert t.index("Cam phòng khách") < t.index("→ 📍 **Con trai Trí Anh** đang ở **Cam phòng khách**")
    assert ra["image_url"].startswith("http://cong:5000/images/")


def test_khong_nhan_ra_nguoi_can_tim_van_bao_o_dau_bao_nhieu_nguoi(goi, monkeypatch):
    monkeypatch.setattr(so_mat_nha, "su_kien_gan",
                        lambda *a, **k: [{"ts": time.time() - 600, "camera": "Cam cửa"}])
    ra = goi("Con trai Trí Anh", {"Cam bếp": [_k(1)]})
    t = ra["text"]
    assert "• **Cam bếp**: 1 người — 1 người chưa nhận ra mặt" in t, t
    assert "→ Em chưa nhận ra **Con trai Trí Anh** ở camera nào." in t
    assert "Lần cuối camera gặp Con trai Trí Anh: Cam cửa" in t
    assert ra["image_url"].startswith("http://cong:5000/images/"), "có người chưa nhận ra thì gửi ảnh camera đó"


def test_nhin_them_khung_khi_co_nguoi_chua_nhan_ra(goi):
    """Đo 27/09/2026: 6 khung liền chủ máy ở bếp — 4 «có thể là Tôi», 2 «người lạ». Khung đầu
    xấu thì nhìn thêm, không kết luận từ một khung."""
    ra = goi("Con trai Trí Anh", {"Cam bếp": [_k(1), _k(1, _mat("p1", "Con trai Trí Anh", 45, "co_the"))]})
    assert "→ 📍 **Con trai Trí Anh** đang ở **Cam bếp** (giống 45/100, chưa chắc lắm)" in ra["text"], ra["text"]


def test_ten_mo_ho_thi_hoi_lai(goi):
    ra = goi("con", {})
    assert "chưa rõ «con»" in ra["text"] and "Con gái Tuệ Nhị" in ra["text"]


def test_khong_ai_o_dau_ca(goi):
    ra = goi("", {})
    assert ra["text"].startswith("Không camera nào thấy người lúc này (3 camera).")
    assert "image_url" not in ra


def test_cau_hoi_dang_o_dau_mo_nhom_camera():
    from services.agent import orchestrator as o
    assert "camera" in o._nhom_viec("Con trai đang ở đâu", {"camera"})
    assert "camera" in o._nhom_viec("bà ở phòng nào vậy", {"camera"})
