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


def test_am_dau_khop_tron_khong_khop_mot_phan():
    # Bẫy chính: "n-" không được ăn khớp với "nhà", "ng-" không ăn với "nghỉ".
    assert kpa._am_dau("nha") == "nh"
    assert kpa._am_dau("nghi") == "ngh"
    assert kpa._am_dau("qua") == "qu"
    assert kpa._am_dau("em") == ""
    assert not kpa._nghe_thay("n-", "nhà em", "vi")
    assert kpa._nghe_thay("n-", "nam thanh", "vi")
    assert not kpa._nghe_thay("ng-", "nghỉ học", "vi")


def test_am_cuoi_khop_tron():
    assert kpa._am_cuoi("sinh") == "nh"
    assert kpa._am_cuoi("hoc") == "c"
    assert kpa._am_cuoi("ba") == ""
    assert kpa._nghe_thay("-ng", "hát vang", "vi")
    # "phà" mất hẳn âm cuối → bắt; còn "phan" thì xem test lẫn -n/-ng bên dưới.
    assert not kpa._nghe_thay("-ng", "hát phà", "vi")


def test_lech_thanh_dieu_khong_tinh_la_rung_phu_am():
    """STT nghe "kem" ra "Kèm" là lệch THANH, phụ âm /k/ vẫn nguyên."""
    assert kpa._nghe_thay("k-", "Kèm không đường", "vi")
    # Nhưng mất hẳn /k/ ("Em không đường") thì phải báo sai.
    assert not kpa._nghe_thay("k-", "Em không đường", "vi")


def test_chu_khac_nhung_cung_am_thi_khong_tinh_la_rung():
    """Bắc bộ: d/gi/r cùng /z/, s/x cùng /s/, ch/tr cùng /tɕ/."""
    assert kpa._nghe_thay("d-", "Ra tay hơi khô", "vi")      # d → r, âm /z/ còn
    assert kpa._nghe_thay("x-", "sin chào các bạn", "vi")    # x → s, âm /s/ còn
    assert kpa._nghe_thay("ch-", "trào buổi sáng", "vi")     # ch → tr
    # Nhưng thay bằng âm KHÁC hẳn thì vẫn phải bắt.
    assert not kpa._nghe_thay("d-", "Ta tay hơi khô", "vi")   # d → t, mất /z/
    assert not kpa._nghe_thay("x-", "chin chào các bạn", "vi")  # đúng ca người dùng báo
    assert not kpa._nghe_thay("d-", "Chặt tay hơi khô", "vi")


def test_am_cuoi_chi_doi_con_am_khong_doi_dung_chu():
    assert kpa._nghe_thay("-t", "tác văn bài ca", "vi")   # -t → -c, phương ngữ
    assert kpa._nghe_thay("-ng", "hát văn bài ca", "vi")  # -ng → -n
    assert not kpa._nghe_thay("-t", "hà vang bài ca", "vi")   # mất hẳn âm cuối
    assert not kpa._nghe_thay("-p", "học sinh lớ một", "vi")


def test_tieng_anh_so_theo_chuoi_con_vi_ghep_tu():
    """STT viết "sea shells" liền thành "seashells" — /ʃ/ vẫn đọc đủ."""
    assert kpa._nghe_thay("shells", "She sells seashells.", "en")
    assert not kpa._nghe_thay("shells", "She sells sea shirts.", "en")


def test_cau_thu_tieng_anh_khong_dung_tu_chi_so():
    """STT viết lại "nine" thành "9" nên từ chỉ số làm phép đo báo oan."""
    so = ("one", "two", "three", "four", "five", "six", "seven", "eight",
          "nine", "ten")
    for _cau, dich, _nhan in kpa.BO_TEST["en"]:
        for d in dich:
            assert d not in so, f"câu thử tiếng Anh không nên lấy đích {d!r}"


def test_bo_thanh_giu_dau_chu():
    assert kpa._bo_thanh("quýt") == "quyt"
    assert kpa._bo_thanh("đường") == "đương"   # ư là chữ, không phải thanh
    assert kpa._bo_thanh("bận") == "bân"


def test_nghe_thay_tieng_a_dong_theo_chuoi_con():
    # STT tiếng Trung/Nhật/Hàn không chèn dấu cách nên phải so theo chuỗi con.
    assert kpa._nghe_thay("天気", "今日はいい天気ですね", "ja")
    assert kpa._nghe_thay("八", "八百八十八块钱", "zh")
    assert not kpa._nghe_thay("雨", "今日はいい天気ですね", "ja")
