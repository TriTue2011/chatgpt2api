"""Lịch tự đánh giá: phát hiện luật duyệt CHẾT (khớp nguồn nhưng điều kiện chặn mãi, 0 lần chạy) từ nhật ký kích hoạt.
Chủ máy 04/10/2026: "bot giải lúc đầu, sau chạy tự động; bót định kỳ học lại, đánh giá để tối ưu"."""
from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services import nhat_ky_kich_hoat as nk  # noqa: E402


@pytest.fixture
def db(tmp_path):
    nk._reset_for_tests(tmp_path / "nk.sqlite")
    yield
    nk._reset_for_tests(tmp_path / "nk.sqlite")


def test_luat_chet_khop_nhung_chan_mai_khong_chay(db):
    now = time.time()
    # #5: bị chặn 25 lần, chưa lần nào làm → CHẾT
    for _ in range(25):
        nk.ghi("fan.pk", "on", "khong", ly_do="trường hợp duyệt #5: chưa đủ điều kiện — binary_sensor.x=off✗")
    # #13: bị chặn 10 lần (dưới ngưỡng 20) → chưa gọi chết
    for _ in range(10):
        nk.ghi("fan.pk", "on", "khong", ly_do="trường hợp duyệt #13: chưa đủ điều kiện — a=off✗")
    # #20: bị chặn 30 lần NHƯNG có 2 lần làm → KHÔNG chết
    for _ in range(30):
        nk.ghi("fan.pk", "off", "khong", ly_do="trường hợp duyệt #20: chưa đủ điều kiện — kc=0✗")
    for _ in range(2):
        nk.ghi("fan.pk", "off", "lam", ly_do="trường hợp duyệt #20: kc=4✓")
    chet = nk.luat_chet(so_ngay=5)
    assert chet.get("fan.pk") == [5], f"chỉ #5 chết, được {chet}"


def test_luat_chet_bo_qua_ngoai_khoang_thoi_gian(db):
    now = time.time()
    with nk._khoa:
        conn = nk._db()
        for _ in range(25):
            conn.execute("INSERT INTO nhat_ky (ts, thiet_bi, hanh_dong, ket_qua, nguon, ly_do, dieu_kien) VALUES (?,?,?,?,?,?,?)",
                         (now - 10 * 86400, "fan.pk", "on", "khong", "", "trường hợp duyệt #5: chưa đủ điều kiện — x=off✗", ""))
        conn.commit()
    assert nk.luat_chet(so_ngay=5) == {}, "cũ hơn cửa sổ thì không tính"


def test_luat_dao_dong_bat_roi_tat_ngay(db):
    now = time.time()
    # #13 bật rồi tắt 2 phút sau — 3 cặp cách nhau 1 giờ → dao động
    for k in range(3):
        base = now - (k + 1) * 3600
        nk.ghi("fan.pk", "on", "lam", ly_do="trường hợp duyệt #13: person=on✓", luc=base)
        nk.ghi("fan.pk", "off", "lam", ly_do="kiểm lại sau khi bật: không ai thấy", luc=base + 120)
    # #10 bật rồi tắt chỉ 1 lần → dưới ngưỡng 3
    nk.ghi("fan.pk", "on", "lam", ly_do="trường hợp duyệt #10: cửa mở✓", luc=now - 500)
    nk.ghi("fan.pk", "off", "lam", ly_do="tắt vì vắng", luc=now - 380)
    # #6 bật rồi 12 phút sau mới tắt → KHÔNG phải dao động
    nk.ghi("fan.pk", "on", "lam", ly_do="trường hợp duyệt #6: ở lại✓", luc=now - 20000)
    nk.ghi("fan.pk", "off", "lam", ly_do="tắt vì vắng", luc=now - 20000 + 720)
    d = nk.luat_dao_dong(so_ngay=7)
    assert d.get("fan.pk") == {13: 3}, f"chỉ #13 dao động ≥3 lần, được {d}"
