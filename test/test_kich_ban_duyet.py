"""Duyệt trường hợp BẬT rồi TẮT (chủ máy 02/10/2026): bot gửi danh sách, chủ nhà duyệt / sửa / thêm / bỏ qua kênh
hoặc web; duyệt xong chiều bật thì tới chiều tắt; bản đã duyệt vào lời mô tả nhà. Không gọi mạng."""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import hieu_thiet_bi_nha as ht, kich_ban_nha as kb, kich_hoat_nha, so_do_nha  # noqa: E402


def _th(tb, nen, chu, hien="sai"):
    return {"thiet_bi": tb, "loai": "vao", "tinh_huong": chu, "cam_bien_thay": "", "nen": nen, "hien_tai": hien}


@pytest.fixture
def so(tmp_path, monkeypatch):
    kb._reset_for_tests(tmp_path / "kb.json")
    (tmp_path / "kb.json").write_text(json.dumps({"lan": [{"id": 2, "kich_ban": [
        _th("light.den", "bat", "Mở cửa bước vào", "dung"),
        _th("light.den", "khong_lam", "Nấu ăn ở bếp làm cảm biến báo lây"),
        _th("light.den", "giu", "Rời đi lấy đồ rồi quay lại"),
        _th("light.den", "tat", "Phòng trống quá 3 phút"),
        _th("light.den", "bao", "Nhà vắng mà có người"),
        _th("fan.quat", "bat", "Ngồi xem tivi"),
    ]}], "hoi": []}), encoding="utf-8")
    gui: list[str] = []
    mo_ta: list[tuple[str, str]] = []
    monkeypatch.setattr(ht, "bao_nhom", lambda tin: gui.append(tin) or 1)
    monkeypatch.setattr(kich_hoat_nha, "_ten_ha", lambda: {"light.den": "Đèn trần", "fan.quat": "Quạt"})
    monkeypatch.setattr(so_do_nha, "them_mo_ta", lambda nd, nguon="", thay_cu=False: mo_ta.append((nguon, nd)) or 1)
    return gui, mo_ta


def test_gui_danh_sach_bat_truoc_dung_chieu(so):
    gui, _ = so
    kb.bat_dau_duyet()
    assert gui[-1].startswith("📋 Duyệt trường hợp BẬT — Đèn trần (2)")
    assert "Mở cửa bước vào → bật [✓ đang làm đúng]" in gui[-1]
    assert "báo lây → không làm gì" in gui[-1]
    assert "Phòng trống" not in gui[-1] and "Nhà vắng" not in gui[-1], "tắt sang sau; «báo» không vào bật/tắt"


def test_sua_them_bo_qua_kenh_roi_duyet_thi_sang_tat(so):
    gui, mo_ta = so
    kb.bat_dau_duyet()
    kb.tra_loi_duyet("thêm: đi từ bếp vào ngồi ghế → bật")
    kb.tra_loi_duyet("sửa 2: nấu ăn ở bếp → không bật")
    assert "Không có trường hợp số 9" in kb.tra_loi_duyet("bỏ 9")
    assert "3. đi từ bếp vào ngồi ghế → bật (anh thêm)" in kb._soan("light.den", "bat", kb.duyet()["light.den"]["bat"])
    kb.tra_loi_duyet("bỏ 1")
    tl = kb.tra_loi_duyet("duyệt")
    assert "đã duyệt" in tl
    nguon, nd = mo_ta[-1]
    assert nguon == "duyet:light.den:bat" and "nấu ăn ở bếp → không làm gì" in nd and "Mở cửa" not in nd
    assert gui[-1].startswith("📋 Duyệt trường hợp TẮT — Đèn trần (2)")
    kb.tra_loi_duyet("duyệt")
    assert gui[-1].startswith("📋 Duyệt trường hợp BẬT — Quạt"), "xong một thiết bị thì sang thiết bị kế"
    assert kb.duyet()["light.den"]["xong"] is True


def test_chay_lai_khong_mat_phan_da_sua(so):
    kb.bat_dau_duyet()
    kb.tra_loi_duyet("thêm: ngồi đọc sách → bật")
    kb.bat_dau_duyet()
    assert any(m["tinh_huong"] == "ngồi đọc sách" for m in kb.duyet()["light.den"]["bat"])


def test_loi_khong_hieu_thi_huong_dan(so):
    kb.bat_dau_duyet()
    assert "duyệt" in kb.tra_loi_duyet("hôm nay trời đẹp")
    assert "Không có trường hợp số 9" in kb.tra_loi_duyet("sửa 9: x")
