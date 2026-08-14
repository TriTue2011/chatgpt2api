"""Bệ đo phát âm (scripts/kiem_phat_am.py) — kiểm chính cái thước trước khi đo.

Một lỗi chính tả trong bảng câu thử sẽ khiến MỌI giọng cùng "sai" ở câu đó và
trông y như giọng bị rụng âm. Test dưới đây chặn đúng kiểu lỗi ấy: mỗi âm tiết
cần nghe lại phải thật sự có trong câu đọc ra.

Không nạp model, không đụng mạng.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

GOC = Path(__file__).resolve().parents[1]


def _nap():
    if str(GOC) not in sys.path:
        sys.path.insert(0, str(GOC))
    spec = importlib.util.spec_from_file_location(
        "kiem_phat_am", GOC / "scripts" / "kiem_phat_am.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kpa = _nap()


def test_du_nam_tieng():
    assert set(kpa.BO_TEST) == {"vi", "en", "zh", "ja", "ko"}


@pytest.mark.parametrize("lang", ["vi", "en", "zh", "ja", "ko"])
def test_am_tiet_can_nghe_co_that_trong_cau(lang):
    """Âm tiết đích phải nằm trong chính câu đọc — nếu không, phép đo vô nghĩa."""
    for cau, dich, nhan in kpa.BO_TEST[lang]:
        assert dich, f"{lang}: câu {cau!r} không khai âm tiết nào để nghe lại"
        assert nhan, f"{lang}: câu {cau!r} thiếu nhãn phụ âm"
        for d in dich:
            assert kpa._nghe_thay(d, cau, lang), \
                f"{lang}: {d!r} không có trong câu {cau!r}"


def test_chuan_bo_dau_cau_giu_dau_tieng_viet():
    assert kpa._chuan("Xin chào, các bạn!") == "xin chào các bạn"
    assert kpa._chuan("  A—B  ") == "a b"


def test_nghe_thay_tieng_viet_theo_tu_khong_theo_chuoi_con():
    # "in" nằm trong chuỗi "xin" nhưng KHÔNG phải từ — không được tính là nghe thấy.
    assert not kpa._nghe_thay("in", "xin chào", "vi")
    assert kpa._nghe_thay("xin", "xin chào", "vi")


def test_nghe_thay_tieng_a_dong_theo_chuoi_con():
    # STT tiếng Trung/Nhật/Hàn không chèn dấu cách nên phải so theo chuỗi con.
    assert kpa._nghe_thay("天気", "今日はいい天気ですね", "ja")
    assert kpa._nghe_thay("八", "八百八十八块钱", "zh")
    assert not kpa._nghe_thay("雨", "今日はいい天気ですね", "ja")
