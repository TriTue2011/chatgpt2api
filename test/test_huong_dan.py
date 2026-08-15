"""Hướng dẫn dùng — và chốt chặn quan trọng nhất: đừng dạy lệnh không có thật.

Người dùng đọc hướng dẫn rồi gõ theo, không thấy gì xảy ra, thì họ kết luận bot
hỏng chứ không kết luận tài liệu sai. Nên mọi lệnh nhắc trong bảng hướng dẫn
phải có mặt thật trong mã nguồn bot.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from services import huong_dan as hd

GOC = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _sach():
    hd._cho.clear()
    yield
    hd._cho.clear()


def test_moi_lenh_trong_huong_dan_deu_co_that_trong_code():
    nguon = "\n".join(
        (GOC / "services" / f).read_text(encoding="utf-8")
        for f in ("zalo_personal.py", "translate_service.py", "agent/persona.py")
    )
    lenh = set()
    for _ten, cach in hd.MUC:
        lenh |= set(re.findall(r"«(/[a-zA-Zà-ỹ]+)»", cach))
    assert lenh, "bảng hướng dẫn không nhắc lệnh nào — chắc đã viết hỏng"
    thieu = [l for l in sorted(lenh) if f'"{l}"' not in nguon]
    assert not thieu, f"hướng dẫn dạy lệnh không có trong code: {thieu}"


def test_nhan_dien_cau_xin_huong_dan():
    for cau in ("hướng dẫn", "/huongdan", "help", "cách dùng",
                "dùng thế nào", "trợ giúp"):
        assert hd.la_xin_huong_dan(cau), f"bỏ sót: {cau}"
    for cau in ("hôm nay trời đẹp", "anh hướng về phía đông"):
        assert not hd.la_xin_huong_dan(cau), f"bắt nhầm: {cau}"


def test_menu_danh_so_du_muc_va_chon_duoc():
    m = hd.mo("k")
    for i in range(1, len(hd.MUC) + 1):
        assert f"{i}. " in m
    ra = hd.chon("k", "2")
    assert ra and "/stt" in ra["text"]
    # Chọn xong thì menu đóng — không để số nhắn sau đó bị hiểu nhầm là chọn mục.
    assert hd.chon("k", "3") is None


def test_chua_mo_menu_thi_so_khong_bi_nuot():
    """Chưa hỏi hướng dẫn mà nhắn '2' thì đó là câu chuyện khác của người dùng."""
    assert hd.chon("chua-mo", "2") is None


def test_so_ngoai_bang_va_xin_bo():
    hd.mo("k")
    assert hd.chon("k", "99") is None
    assert hd.chon("k", "thôi") == {"bo": True}
